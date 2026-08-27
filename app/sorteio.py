"""Randomização de cor + escolha de foto.

- Cor: sorteia UMA combinação inteira da paleta oficial (config/paleta-salesjobs.json,
  extraída dos frames do Figma). Nunca mistura cores de combinações diferentes.
- Foto: pega o resultado mais relevante do pool retornado pela busca Pexels
  (já ordenado por relevância), pulando as últimas N usadas (state.py).
"""
import json
import random

from . import config, state

with open(config.PALETA_PATH, encoding="utf-8") as f:
    PALETA = json.load(f)["combinacoes"]


def sortear_combinacao() -> dict:
    return random.choice(PALETA)


def escolher_foto(pool: list[dict]) -> dict:
    """Recebe [{'id': ..., 'url': ...}, ...] (ordenado por relevância do Pexels)
    e devolve o primeiro que não esteja entre as últimas N usadas.

    Se a exclusão esvaziar o pool (pool menor que N), cai para o top do pool —
    melhor repetir foto do que travar a geração.
    """
    if not pool:
        raise ValueError("busca no Pexels não retornou nenhuma foto")
    recentes = state.fotos_recentes(config.FOTOS_EXCLUIR_ULTIMAS_N)
    candidatas = [p for p in pool if p["id"] not in recentes] or pool
    escolhida = candidatas[0]
    state.registrar_foto(escolhida["id"])
    return escolhida
