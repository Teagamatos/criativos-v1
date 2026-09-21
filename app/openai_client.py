"""GPT (OpenAI) — gera as queries de busca de foto e faz a curadoria das candidatas.

Query: portada do repo mvp-arte (Node), com o prompt reescrito pra priorizar o
CARGO sobre o segmento (vendedor de máquinas não é operário de fábrica).
Curadoria: modelo de visão avalia as miniaturas e dá nota por foto — o detector
de rosto local (rosto.py) não entende o que está na imagem.
Sem OPENAI_API_KEY ou em qualquer erro, degrada graciosamente (devolve None)
— nunca interrompe a geração da arte.
"""
import base64
import json
import logging

import httpx

from . import config

log = logging.getLogger("openai_client")

_URL = "https://api.openai.com/v1/chat/completions"
_MODEL = "gpt-5-nano"
_MODEL_VISAO = "gpt-5-mini"

_INSTRUCOES_FOTO = """Você escolhe fotos de banco de imagens (Pexels/Unsplash) para artes de divulgação de vagas.

Para o cargo recebido, escreva DUAS queries de busca em INGLÊS (3 a 6 palavras cada). Cada uma descreve UMA pessoa em retrato, olhando para a câmera.

A pessoa precisa parecer o CARGO, não o setor da empresa:
- Cargo comercial (vendedor, consultor, representante, executivo de contas, "técnico comercial", vendedor técnico, promotor etc.) → profissional de vendas: "salesman", "sales representative", "sales consultant", em roupa social ou casual de negócios. NÃO é operário, mecânico nem operador de máquina, mesmo que a empresa venda máquinas ou equipamentos.
- Cargo operacional/técnico de campo ou fábrica (mecânico, soldador, operador, técnico de manutenção) → o próprio profissional de mão na massa.
- Cargo administrativo/corporativo/gestão → profissional de escritório.
- O segmento e a empresa só ajudam a escolher o cenário de fundo, e só quando não conflitam com o cargo (vendedor de máquinas agrícolas → "farm" ao fundo). Para cargo comercial o cenário é de NEGÓCIOS (showroom, dealership, farm, office, outdoors) e a pessoa está em roupa de negócios. Nunca use "factory", "industrial", "worker", "construction" nem "site" para cargo comercial: puxam operário de capacete e colete.

Query 1: cargo + cenário de negócios coerente com o segmento (ex.: "sales representative portrait farm equipment").
Query 2: só o cargo, genérica e segura (ex.: "smiling salesman portrait business casual"). Garante boas fotos mesmo quando o cenário do segmento é raro no banco.

- Sempre inclua "portrait" em ambas.
- Evite palavras de grupo (team, meeting, people, group) e enquadramentos que escondem o rosto (hands, back view, silhouette).

Responda APENAS com JSON válido: {"queries": ["<query 1>", "<query 2>"]}"""

_INSTRUCOES_CURADORIA = """Você faz a curadoria de fotos de banco de imagens para a arte de divulgação de uma vaga de emprego. Vai receber o cargo, o contexto da vaga e várias fotos, cada uma precedida do seu id.

A foto será recortada num círculo, com o rosto no canto superior esquerdo do círculo. Dê a cada foto uma nota inteira de 0 a 10: quão bem ela serve como imagem da pessoa que ocupa esse cargo.

NOTA 0 (eliminatória) se qualquer um for verdade:
- não há uma pessoa como assunto principal (só máquina, painel, objeto, mãos, paisagem, costas);
- o rosto não está visível e reconhecível (de costas, perfil extremo, olhando para baixo, coberto, cortado);
- há mais de uma pessoa em destaque;
- cigarro, bebida alcoólica, arma, cena de acidente, nudez ou aparência suja/degradada;
- marca, logo ou texto grande legível, ou marca d'água;
- foto desfocada, escura, muito antiga ou com cara de banco de imagem forçado/caricato;
- headset/fone de call center, exceto se o cargo for de telemarketing, atendimento ou SDR.

NOTA MÁXIMA 3, mesmo que tudo o mais esteja perfeito, quando o cargo é comercial (vendedor, consultor, representante, executivo de contas) e a pessoa está de capacete, colete refletivo, macacão ou uniforme de obra/fábrica/oficina: é um operário, não um vendedor. O cenário do segmento (obra, máquina, fábrica) NUNCA compensa isso. Essa regra não vale para cargos operacionais/técnicos, onde o uniforme é o esperado.

Nas demais, pontue por:
- aderência ao cargo (10 = parece exatamente o profissional do cargo). Para cargo comercial (vendedor, consultor, representante), é um vendedor/consultor em roupa de negócios ou casual profissional, NÃO um operário de fábrica; se o cargo for externo/de campo, alguém em cenário de visita a cliente ou ao ar livre é melhor que escritório; o segmento só entra como cenário;
- rosto grande, nítido, olhando para a câmera, expressão simpática ou confiante;
- iluminação boa e fundo limpo.

Responda APENAS com JSON válido: {"notas": {"<id>": <nota>}} incluindo todas as fotos recebidas."""


async def _chat(
    instrucoes: str,
    usuario: str | list,
    *,
    modelo: str = _MODEL,
    reasoning_effort: str = "low",
    max_completion_tokens: int = 6000,
    timeout: float = 30,
) -> dict | None:
    if not config.OPENAI_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=timeout) as cli:
            r = await cli.post(
                _URL,
                headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
                json={
                    "model": modelo,
                    "reasoning_effort": reasoning_effort,
                    "max_completion_tokens": max_completion_tokens,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": instrucoes},
                        {"role": "user", "content": usuario},
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


async def gerar_queries_foto(cargo: str, contexto: dict) -> list[str]:
    """Até 2 queries de busca (em inglês) para o cargo, considerando o contexto da vaga.
    Lista vazia quando a OpenAI não responde — o chamador cai no fallback."""
    out = await _chat(
        _INSTRUCOES_FOTO,
        json.dumps({"contexto": contexto, "cargo": cargo}, ensure_ascii=False),
        reasoning_effort="low",
    )
    queries = out.get("queries") if out else None
    if not isinstance(queries, list):
        return []
    return [q.strip() for q in queries if isinstance(q, str) and q.strip()][:2]


async def curar_fotos(cargo: str, contexto: dict, fotos: list[dict]) -> dict[str, int] | None:
    """Nota 0-10 por foto (chave = id) segundo o modelo de visão, ou None se a
    curadoria não rodou (sem chave/erro). Cada foto precisa de 'thumb_bytes'
    (JPEG/PNG da miniatura, baixado pelo rosto.py) — vai embutido em base64 pra
    não depender da OpenAI conseguir baixar do CDN do banco de imagens."""
    partes: list[dict] = [
        {"type": "text", "text": json.dumps({"cargo": cargo, "contexto": contexto}, ensure_ascii=False)}
    ]
    for foto in fotos:
        dados = foto.get("thumb_bytes")
        if not dados:
            continue
        uri = "data:image/jpeg;base64," + base64.b64encode(dados).decode()
        partes.append({"type": "text", "text": f"id: {foto['id']}"})
        partes.append({"type": "image_url", "image_url": {"url": uri, "detail": "low"}})
    if len(partes) == 1:  # nenhuma miniatura
        return None

    out = await _chat(
        _INSTRUCOES_CURADORIA,
        partes,
        modelo=_MODEL_VISAO,
        reasoning_effort="low",
        max_completion_tokens=8000,
        timeout=90,
    )
    notas = out.get("notas") if out else None
    if not isinstance(notas, dict):
        return None
    return {str(i): int(n) for i, n in notas.items() if isinstance(n, (int, float))}
