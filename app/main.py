"""Servidor HTTP — FastAPI.

- POST /generate  a API fica esperando a chamada com os dados prontos da vaga
                   (n8n já resolveu tudo): cargo, segmento, empresa, nivel,
                   localizacoes, sigilosa, task (ClickUp task_id) e logo (URL).
                   Aceita um objeto único ou uma lista com um objeto.
                   Protegido por Authorization: Bearer $GENERATE_TOKEN.
- GET  /health

Sem dedup por task: cada chamada gera uma arte nova.
"""
import hmac
import json
import logging

from fastapi import BackgroundTasks, Header, Request, Response
from fastapi import FastAPI

from . import config, render
from .pipeline import processar

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("server")

app = FastAPI(title="gerador-arte-salesjobs")

_CAMPOS_OBRIGATORIOS = ("cargo", "localizacoes", "task")


@app.post("/generate")
async def generate(
    request: Request,
    background: BackgroundTasks,
    authorization: str | None = Header(default=None),
):
    if config.GENERATE_TOKEN:
        recebido = (authorization or "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(recebido, config.GENERATE_TOKEN):
            return Response(status_code=401, content='{"error": "token inválido"}')
    else:
        log.warning("GENERATE_TOKEN não definido — endpoint aberto")

    try:
        payload = json.loads(await request.body())
    except json.JSONDecodeError:
        return Response(status_code=400, content='{"error": "body inválido"}')

    dados = payload[0] if isinstance(payload, list) else payload
    if not isinstance(dados, dict):
        return Response(status_code=400, content='{"error": "payload vazio ou inválido"}')

    faltantes = [c for c in _CAMPOS_OBRIGATORIOS if not dados.get(c)]
    if faltantes:
        return Response(
            status_code=400,
            content=json.dumps({"error": f"campos obrigatórios ausentes: {', '.join(faltantes)}"}),
        )

    background.add_task(processar, dados)
    return {"status": "accepted"}


@app.get("/health")
async def health():
    return {"ok": True}


@app.on_event("shutdown")
async def shutdown():
    await render.close_browser()
