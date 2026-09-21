"""Escolhe e reenquadra a foto do banco de imagens pra deixar o rosto sempre visível.

A busca por palavra-chave não garante que o topo do resultado seja de fato
um retrato de rosto fechado — baixamos as miniaturas dos candidatos e rodamos
detecção de rosto local (OpenCV, sem custo de API). Isso faz DUAS coisas:
tira da disputa o que não tem rosto detectável (`ordenar_por_rosto` põe quem tem
rosto na frente; `sorteio.escolher_foto` só aceita esses) e localiza o rosto pra
recompor a foto vencedora (`enquadrar`). O Haar cascade não entende semântica
(painel de máquina, operário fumando…) — quem julga o conteúdo é a curadoria
por visão em `openai_client.curar_fotos`, que recebe as miniaturas baixadas aqui.

Geometria real do template (template-salesjobs.html): a foto entra num
container CIRCULAR (.foto-circulo, 897×896 em left:661 top:-57) com
object-fit:cover. Por cima tem uma ELIPSE de acento (.elipse) CONCÊNTRICA — mesmo
centro, raio menor (~252×239 contra 448) — criando um anel de largura constante.
Só ~419px do container ficam dentro do canvas de 1080 (o resto estoura pela
direita) e os ~57px de cima ficam fora pelo topo.

Como o CSS não consegue reposicionar a foto com precisão, `enquadrar` faz isso
no servidor: recorta/reamostra a foto (Python/OpenCV) de modo que o rosto caia
no anel visível COM TAMANHO CONTROLADO (rosto grande demais estoura o círculo e
some debaixo da elipse; pequeno demais perde presença), aumentando o zoom o
quanto precisar pra foto cobrir toda a área visível (sem sobrar vazio).
"""
import base64
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import NamedTuple

import cv2
import httpx
import numpy as np
from tenacity import before_sleep_log, retry, stop_after_attempt, wait_exponential

log = logging.getLogger("rosto")

_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
# CascadeClassifier NÃO é thread-safe (buffers internos): sem o lock, detecções
# concorrentes devolvem rostos fantasma. O download das miniaturas segue paralelo.
_CASCADE_LOCK = threading.Lock()
_RETRY = dict(
    stop=stop_after_attempt(2),
    wait=wait_exponential(min=1, max=4),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)


@retry(**_RETRY)
def _baixar_bytes(url: str) -> bytes:
    r = httpx.get(url, timeout=12)
    r.raise_for_status()
    return r.content


def _decodificar(dados: bytes, cor: int) -> np.ndarray | None:
    return cv2.imdecode(np.frombuffer(dados, dtype=np.uint8), cor)


class Rosto(NamedTuple):
    """Maior rosto detectado — tudo em fração (0-1) da foto original."""

    cx: float
    cy: float
    area: float
    largura: float
    largura_final: float = 0.0  # largura do rosto no container (px de 1033) depois do enquadramento


_AREA_MIN = 0.012  # abaixo disso o "rosto" é quase certamente falso positivo (estampa, textura)
_MAX_CANDIDATAS_CURADORIA = 16  # quantas miniaturas (com rosto) seguem pra curadoria por visão
# Rosto que, pra foto cobrir a área visível, acabaria com mais que isso (px de 1033)
# é close-up demais: estoura o anel e some debaixo da elipse. Foto descartada.
_LARGURA_FINAL_MAX = 250


def _detectar(img: np.ndarray | None) -> Rosto | None:
    """Maior rosto detectado, ou None se não achou nenhum.

    Quando há mais de um candidato (ex.: estampa numa roupa parecendo rosto),
    escolhe pelo PESO de confiança do Haar cascade (`outputRejectLevels`), não
    pela maior área — um falso positivo pode ser maior em pixels e ainda
    assim ter confiança bem menor que o rosto de verdade.
    """
    if img is None:
        return None
    altura, largura = img.shape
    lado_min = int(min(altura, largura) * 0.12)
    with _CASCADE_LOCK:
        faces, _niveis, pesos = _CASCADE.detectMultiScale3(
            img, scaleFactor=1.1, minNeighbors=5, minSize=(lado_min, lado_min), outputRejectLevels=True
        )
    if len(faces) == 0:
        return None
    x, y, w, h = faces[int(np.argmax(pesos))]
    rosto = Rosto(
        cx=(x + w / 2) / largura,
        cy=(y + h / 2) / altura,
        area=(w * h) / (largura * altura),
        largura=w / largura,
    )
    # escala sem teto: a miniatura é pequena, o teto de upscale só vale na foto real
    _, largura_final = _plano(rosto, largura, altura, limitar_upscale=False)
    return rosto._replace(largura_final=largura_final)


def _analisar(foto: dict) -> dict:
    """Baixa a miniatura e detecta o rosto APROVEITÁVEL (existe, não é falso
    positivo e cabe no anel). Falha ao baixar/decodificar = sem rosto (não
    interrompe a geração, só tira a foto da disputa)."""
    try:
        dados = _baixar_bytes(foto.get("thumb") or foto["url"])
        rosto = _detectar(_decodificar(dados, cv2.IMREAD_GRAYSCALE))
    except Exception:
        dados, rosto = None, None
    if rosto is not None and (rosto.area < _AREA_MIN or rosto.largura_final > _LARGURA_FINAL_MAX):
        rosto = None  # falso positivo provável, ou close-up que não enquadra
    return {**foto, "rosto": rosto, "thumb_bytes": dados}


def ordenar_por_rosto(pool: list[dict]) -> list[dict]:
    """Recebe [{'id', 'url', 'thumb'}, ...] e devolve as fotos COM rosto detectado
    na frente (maior rosto primeiro), seguidas das sem rosto na ordem original de
    relevância. Cada item ganha 'rosto' (`Rosto` ou None) — usado por `enquadrar`
    e por `sorteio.escolher_foto`, que só aceita fotos com rosto — e
    'thumb_bytes' (miniatura crua, pra curadoria por visão).
    """
    with ThreadPoolExecutor(max_workers=8) as ex:
        analisadas = list(ex.map(_analisar, pool))
    com_rosto = sorted((f for f in analisadas if f["rosto"]), key=lambda f: f["rosto"].area, reverse=True)
    sem_rosto = [f for f in analisadas if not f["rosto"]]
    return com_rosto + sem_rosto


def candidatas_curadoria(pool: list[dict]) -> list[dict]:
    """Fotos (já passadas por `ordenar_por_rosto`) que valem ir pra curadoria por visão."""
    return [f for f in pool if f.get("rosto") and f.get("thumb_bytes")][:_MAX_CANDIDATAS_CURADORIA]


# Alvo do rosto dentro do container (jpeg 1033×1033, que o CSS reescala pra 897).
# Ponto: meio do anel visível à altura do rosto (canvas ≈ (800, 230)); largura da
# caixa do Haar ~150px (≈130 no canvas) — a cabeça inteira, com cabelo, cabe
# entre a borda do círculo e a elipse sem encostar em nenhuma.
_CONTAINER = 1033
_ALVO_X = 160
_ALVO_Y = 331
_ALVO_LARGURA = 150
_ESCALA_MAX = 2.0  # não estica mais que isso só pra atingir o tamanho-alvo (pixeliza)
# Parte do container que aparece no canvas (o resto sai pela direita/topo):
_VIS_X_MAX = 420
_VIS_Y_MIN = 66  # 57px do container 897 → 66 em 1033


def _plano(rosto: Rosto, largura_src: int, altura_src: int, limitar_upscale: bool = True) -> tuple[float, float]:
    """(escala, largura final do rosto em px do container) pra encaixar o rosto
    no alvo. A escala leva o rosto ao tamanho-alvo mas nunca fica abaixo da
    necessária pra foto cobrir a área visível (senão sobra vazio nas bordas)."""
    face_cx, face_cy = rosto.cx * largura_src, rosto.cy * altura_src
    alvo = _ALVO_LARGURA / (rosto.largura * largura_src)
    escala = min(alvo, _ESCALA_MAX) if limitar_upscale else alvo
    escala = max(
        escala,
        _ALVO_X / face_cx,
        (_VIS_X_MAX - _ALVO_X) / max(largura_src - face_cx, 1),
        (_ALVO_Y - _VIS_Y_MIN) / face_cy,
        (_CONTAINER - _ALVO_Y) / max(altura_src - face_cy, 1),
    )
    return escala, rosto.largura * largura_src * escala


def enquadrar(foto: dict) -> str:
    """Recorta/reamostra a foto escolhida pra deixar o rosto no anel visível, com
    tamanho controlado. Sem rosto detectado (foto['rosto'] is None) ou em qualquer
    erro, devolve a URL original sem modificar — sem interromper a geração.
    """
    pos = foto.get("rosto")
    if pos is None:
        return foto["url"]
    try:
        img = _decodificar(_baixar_bytes(foto["url"]), cv2.IMREAD_COLOR)
        altura_src, largura_src = img.shape[:2]
        escala, _ = _plano(pos, largura_src, altura_src)
        largura_esc = round(largura_src * escala)
        altura_esc = round(altura_src * escala)
        interp = cv2.INTER_AREA if escala < 1 else cv2.INTER_CUBIC
        img_esc = cv2.resize(img, (largura_esc, altura_esc), interpolation=interp)

        crop_x = round(pos.cx * largura_esc - _ALVO_X)
        crop_y = round(pos.cy * altura_esc - _ALVO_Y)

        # Recorta o container. A escala já garante cobertura; o padding só
        # absorve 1px de arredondamento (replica a borda em vez de deixar vazio).
        pad_esq, pad_topo = max(0, -crop_x), max(0, -crop_y)
        pad_dir = max(0, crop_x + _CONTAINER - largura_esc)
        pad_baixo = max(0, crop_y + _CONTAINER - altura_esc)
        if pad_esq or pad_topo or pad_dir or pad_baixo:
            img_esc = cv2.copyMakeBorder(img_esc, pad_topo, pad_baixo, pad_esq, pad_dir, cv2.BORDER_REPLICATE)
            crop_x += pad_esq
            crop_y += pad_topo
        canvas = img_esc[crop_y : crop_y + _CONTAINER, crop_x : crop_x + _CONTAINER]

        ok, buf = cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            return foto["url"]
        return "data:image/jpeg;base64," + base64.b64encode(buf).decode()
    except Exception:
        log.exception("falha ao reenquadrar %s — usando a foto original", foto.get("id"))
        return foto["url"]
