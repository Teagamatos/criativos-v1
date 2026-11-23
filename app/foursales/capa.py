"""Montagem da imagem da capa sobre o template do Figma (frame "Posição em destaque").

Camadas, de baixo pra cima (mesmo comportamento do template original):
1. `capa_base.jpg`  — fundo do template sem a pessoa (painel escuro à esquerda);
2. a foto da vaga, com o cenário original: nítida à direita, desfocada perto da
   linha dourada e esmaecendo ~200px à esquerda dela;
3. a cabeça/ombros da pessoa por cima do painel escuro (como o capacete do template);
4. `capa_frente.png` — linha dourada + faixas do canto inferior direito, na frente de tudo.

Tudo em px da capa 2200×2731 (o HTML reescala pra 1080×1350).
"""
import base64
from functools import lru_cache

import cv2
import numpy as np

from .. import config, rosto
from . import foto as foto_mod

ASSETS = config.BASE_DIR / "templates" / "foursales"
W, H = foto_mod.CAPA_W, foto_mod.CAPA_H
# linha dourada esquerda, medida na imagem original do Figma: x = A*y + B
LINHA_A, LINHA_B = -0.3847, 1985.0 * W / 3300


@lru_cache(maxsize=1)
def _camadas():
    base = cv2.imread(str(ASSETS / "capa_base.jpg"), cv2.IMREAD_COLOR).astype(np.float32)
    frente = cv2.imread(str(ASSETS / "capa_frente.png"), cv2.IMREAD_UNCHANGED).astype(np.float32)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    dist = xx - (LINHA_A * yy + LINHA_B)                       # > 0 à direita da linha
    alpha_foto = np.clip((dist + 200) / 200, 0, 1)             # esmaece ~200px à esquerda da linha
    t_blur = np.clip(1 - (dist + 100) / 300, 0, 1)             # desfoque perto/à esquerda da linha
    lim_cabeca = np.clip((1130 - yy) / 270, 0, 1)              # só cabeça/ombros invadem o painel
    return base, frente, alpha_foto[..., None], t_blur[..., None], lim_cabeca, dist


def _enquadrar(img: np.ndarray, r: rosto.Rosto) -> tuple[np.ndarray, float, float, float]:
    """Escala/recorta a foto pra cobrir a capa com o rosto no alvo. Devolve a foto
    enquadrada e (cx, cy, largura) do rosto em px da capa."""
    h, w = img.shape[:2]
    s, _ = foto_mod.plano(r, w, h)
    img = cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    x0 = round(r.cx * w * s - foto_mod.ALVO_CX)
    y0 = round(r.cy * h * s - foto_mod.ALVO_CY)
    pad = [max(0, -y0), max(0, y0 + H - img.shape[0]), max(0, -x0), max(0, x0 + W - img.shape[1])]
    if any(pad):  # só absorve arredondamento
        img = cv2.copyMakeBorder(img, *pad, cv2.BORDER_REPLICATE)
        x0 += pad[2]
        y0 += pad[0]
    return img[y0 : y0 + H, x0 : x0 + W], foto_mod.ALVO_CX, foto_mod.ALVO_CY, r.largura * w * s


def _tom(img: np.ndarray) -> np.ndarray:
    """Puxa a foto pro azul do template (menos saturação + 20% de azul-marinho)."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[..., 1] *= 0.8
    img = cv2.cvtColor(hsv.clip(0, 255).astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.float32)
    return img * 0.8 + np.array([85, 32, 10], np.float32) * 0.2  # BGR


def montar(foto_bytes: bytes, r: rosto.Rosto) -> str:
    """Bytes da foto escolhida + rosto detectado → data URI JPEG da capa."""
    base, frente, alpha_foto, t_blur, lim_cabeca, dist = _camadas()
    img = cv2.imdecode(np.frombuffer(foto_bytes, np.uint8), cv2.IMREAD_COLOR)
    img, fcx, fcy, flarg = _enquadrar(img, r)
    img = _tom(img)

    # 2) foto: desfocada perto da linha, esmaecendo sobre o painel
    desfocada = cv2.GaussianBlur(img, (0, 0), 14)
    foto = img * (1 - t_blur) + desfocada * t_blur
    out = base * (1 - alpha_foto) + foto * alpha_foto

    # 3) cabeça/ombros por cima do painel: elipse em volta do rosto detectado
    cabeca = np.zeros((H, W), np.float32)
    cv2.ellipse(cabeca, (int(fcx), int(fcy - flarg * 0.15)), (int(flarg * 0.85), int(flarg * 1.15)), 0, 0, 360, 1.0, -1)
    cv2.ellipse(cabeca, (int(fcx), int(fcy + flarg * 1.6)), (int(flarg * 1.6), int(flarg * 0.9)), 0, 180, 360, 1.0, -1)
    cabeca = cv2.GaussianBlur(cabeca, (0, 0), flarg * 0.08) * lim_cabeca * (dist < 0)
    out = out * (1 - cabeca[..., None]) + img * cabeca[..., None]

    # 4) linha dourada + faixas da frente
    a = frente[..., 3:4] / 255.0
    out = out * (1 - a) + frente[..., :3] * a

    ok, buf = cv2.imencode(".jpg", out.clip(0, 255).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        raise RuntimeError("falha ao codificar a capa")
    return "data:image/jpeg;base64," + base64.b64encode(buf).decode()
