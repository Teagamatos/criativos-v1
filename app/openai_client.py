"""GPT (OpenAI) — gera a query de busca de foto.

Portado do repo mvp-arte (Node) mantendo o prompt e o contrato originais.
Sem OPENAI_API_KEY ou em qualquer erro, degrada graciosamente (devolve None)
— nunca interrompe a geração da arte.
"""
import json
import logging

import httpx

from . import config

log = logging.getLogger("openai_client")

_URL = "https://api.openai.com/v1/chat/completions"
_MODEL = "gpt-5-nano"

_INSTRUCOES_FOTO = """Você escolhe fotos de banco de imagens (Pexels) para artes de divulgação de vagas.

Para cada cargo recebido, escreva uma query de busca em INGLÊS (4 a 7 palavras) descrevendo UMA pessoa profissional daquela área, de preferência olhando para a câmera, no ambiente de trabalho típico do cargo.

- Use o contexto da vaga para resolver nomes ambíguos: "Engenheiro de Desenvolvimento de Mercado" numa empresa de agroquímicos é um perfil de agro/comercial → "agronomist portrait crop field looking at camera" — NADA de software/computadores.
- "perfilCandidato" (quando presente) é o sinal mais importante: descreve de onde vem o profissional (ex.: "Agronegócio, vendas" → cena de campo/comercial, não laboratório). "segmento" é o setor da empresa; "empresa" ajuda a desambiguar.
- Sempre inclua "portrait".
- Evite palavras de grupo (team, meeting, people, group).
- Cenário coerente com a área: campo/lavoura para agro, farmácia para farma, loja para varejo, escritório para corporativo etc.

Responda APENAS com JSON válido: {"queries": {"<cargo exatamente como recebido>": "<query>"}}"""


async def _chat(instrucoes: str, payload: dict, reasoning_effort: str, max_completion_tokens: int) -> dict | None:
    if not config.OPENAI_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=30) as cli:
            r = await cli.post(
                _URL,
                headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
                json={
                    "model": _MODEL,
                    "reasoning_effort": reasoning_effort,
                    "max_completion_tokens": max_completion_tokens,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": instrucoes},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                },
            )
        if r.is_error:
            log.error("status %s %s", r.status_code, r.text[:500])
            return None
        content = r.json()["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception:
        log.exception("falha na chamada à OpenAI")
        return None


async def gerar_query_foto(cargo: str, contexto: dict) -> str | None:
    """Query de busca Pexels (em inglês) para o cargo, considerando o contexto da vaga."""
    out = await _chat(
        _INSTRUCOES_FOTO,
        {"contexto": contexto, "cargos": [cargo]},
        reasoning_effort="low",
        max_completion_tokens=6000,
    )
    queries = out.get("queries") if out else None
    return queries.get(cargo) if isinstance(queries, dict) else None
