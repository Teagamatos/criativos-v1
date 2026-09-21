"""Randomização de cor + escolha de foto.

- Cor: sorteia UMA combinação inteira da paleta oficial (config/paleta-salesjobs.json,
  extraída dos frames do Figma). Nunca mistura cores de combinações diferentes.
- Foto: pega a melhor do pool (rosto detectável + nota da curadoria por visão),
  pulando as últimas N usadas (state.py).
"""
import json
import random

from . import config, state

with open(config.PALETA_PATH, encoding="utf-8") as f:
    PALETA = json.load(f)["combinacoes"]


def sortear_combinacao() -> dict:
    return random.choice(PALETA)


def escolher_foto(pool: list[dict], notas: dict[str, int] | None = None) -> dict:
    """Recebe [{'id', 'url', 'rosto', ...}, ...] e escolhe uma foto.

    Filtros, do mais ao menos rígido (cada um só vale se sobrar alguma foto):
    1. fora as últimas N já usadas (state.py);
    2. só fotos com rosto detectado (`rosto` — sem ele `rosto.enquadrar` não
       consegue posicionar e o rosto cai debaixo da elipse);
    3. com `notas` da curadoria por visão, leva a de maior nota (empate: a de
       maior rosto). Nota 0 é eliminatória, mas só pesa se sobrar alternativa.

    Sem `notas` (curadoria indisponível) devolve a primeira que passou 1-2. Se a
    exclusão esvaziar o pool (pool menor que N), cai para o top do pool —
    melhor repetir foto do que travar a geração.
    """
    if not pool:
        raise ValueError("busca de fotos não retornou nenhuma foto")
    recentes = state.fotos_recentes(config.FOTOS_EXCLUIR_ULTIMAS_N)
    candidatas = [p for p in pool if p["id"] not in recentes] or pool
    candidatas = [p for p in candidatas if p.get("rosto")] or candidatas
    if notas:
        candidatas = [max(candidatas, key=lambda p: notas.get(p["id"], 0))]
    escolhida = candidatas[0]
    state.registrar_foto(escolhida["id"])
    return escolhida
