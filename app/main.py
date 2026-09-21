"""Servidor HTTP — FastAPI.

- POST /generate  a API fica esperando a chamada com os dados prontos da vaga
                   (n8n já resolveu tudo): cargo, segmento, empresa, nivel,
                   localizacoes, sigilosa, task (ClickUp task_id) e logo (URL).
                   Aceita um objeto único ou uma lista com um objeto.
                   Protegido por Authorization: Bearer $GENERATE_TOKEN.
- GET  /health

Sem dedup por task: cada chamada gera uma arte nova.

Docs interativas (Swagger UI): /docs  ·  ReDoc: /redoc  ·  OpenAPI: /openapi.json
"""
import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Body, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from . import config, notify, render
from .pipeline import processar


def _configurar_logs() -> None:
    """stdout formatado — no Railway isso vira o feed de logs do serviço."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    for ruidoso in ("httpx", "httpcore"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)


_configurar_logs()
log = logging.getLogger("server")


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await render.close_browser()


DESCRICAO = """
Geração automática de artes de vaga da **Salesjobs** (HTML → PNG 1080×1350).

Quem chama (n8n) já resolveu todos os dados da vaga. A API só orquestra:

1. sorteio de cor (paleta oficial do Figma) e de foto (busca dinâmica no Pexels
   ou Unsplash, query gerada por GPT a partir do cargo/contexto, excluindo as
   últimas N usadas);
2. logo da contratante convertida pra PNG (`sigilosa=true` omite a logo);
3. render HTML→PNG com Playwright/Chromium;
4. anexo no card do ClickUp (só o PNG, com timestamp no nome; sem comentário).

Cada chamada gera **`CRIATIVOS_POR_VAGA` artes** (env, default 3): o endpoint
dispara N execuções independentes desse pipeline, cada uma sorteando cor e foto
próprias e anexando uma arte no mesmo card. Metade das artes usa foto do
Pexels e metade do Unsplash (o extra, quando N é ímpar, fica com o Pexels).

Falhas técnicas têm retry 3x com backoff; persistindo, a API comenta o erro no
card e notifica o Discord (`DISCORD_BOT_TOKEN` + `DISCORD_CHANNEL_ID`).

O processamento roda em *background*: `POST /generate` responde `202 accepted`
na hora e as artes aparecem no card alguns segundos depois.
""".strip()

app = FastAPI(
    title="gerador-arte-salesjobs",
    version="1.0.0",
    description=DESCRICAO,
    lifespan=lifespan,
    openapi_tags=[
        {"name": "geração", "description": "Disparo da geração de arte."},
        {"name": "infra", "description": "Health check e monitoramento."},
    ],
)

@app.exception_handler(Exception)
async def _erro_nao_tratado(request: Request, exc: Exception) -> JSONResponse:
    """Qualquer exceção não tratada num handler: loga com traceback e avisa o
    Discord. (HTTPException e erros de validação seguem o fluxo normal do
    FastAPI — não caem aqui.)"""
    log.exception("erro não tratado em %s %s", request.method, request.url.path)
    await notify.erro_discord(
        f"❌ Erro não tratado — {request.method} {request.url.path}",
        contexto={"método": request.method, "rota": request.url.path,
                  "erro": f"{type(exc).__name__}: {exc}"},
        exc=exc,
    )
    return JSONResponse(status_code=500, content={"error": "erro interno"})


# Habilita o botão "Authorize" no Swagger UI. auto_error=False: quando
# GENERATE_TOKEN não está definido o endpoint fica aberto (com warning no log).
_bearer = HTTPBearer(auto_error=False, description="GENERATE_TOKEN")


async def verificar_token(
    credenciais: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    if not config.GENERATE_TOKEN:
        log.warning("GENERATE_TOKEN não definido — endpoint aberto")
        return
    recebido = (credenciais.credentials if credenciais else "").strip()
    if not hmac.compare_digest(recebido, config.GENERATE_TOKEN):
        raise HTTPException(status_code=401, detail="token inválido")


class VagaPayload(BaseModel):
    """Dados da vaga já resolvidos por quem chama (n8n)."""

    cargo: str = Field(..., description="Título do cargo. Vai no H1 da arte.", examples=["Consultor de Vendas"])
    localizacoes: list[str] = Field(
        ...,
        min_length=1,
        description="Uma ou mais localizações; viram pills no template (vírgula → ' | ').",
        examples=[["São Paulo, SP", "Remoto"]],
    )
    task: str = Field(..., description="ID do card no ClickUp onde a arte é anexada.", examples=["86abc123"])
    segmento: str | None = Field(None, description="Segmento da empresa. Contexto pra query da foto.", examples=["Tecnologia"])
    empresa: str | None = Field(None, description="Nome da contratante. Contexto pra query da foto.", examples=["ACME"])
    nivel: str | None = Field(None, description="Nível/senioridade. Contexto pra query da foto.", examples=["Pleno"])
    sigilosa: bool = Field(False, description="Vaga sigilosa: omite a logo da contratante da arte.")
    logo: str | None = Field(
        None,
        description="URL assinada da logo da contratante (sem extensão). Ignorada se `sigilosa=true`.",
        examples=["https://s3.amazonaws.com/bucket/logo-acme?X-Amz-Signature=..."],
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "cargo": "Consultor de Vendas",
                "segmento": "Tecnologia",
                "empresa": "ACME",
                "nivel": "Pleno",
                "localizacoes": ["São Paulo, SP", "Remoto"],
                "sigilosa": False,
                "task": "86abc123",
                "logo": "https://s3.amazonaws.com/bucket/logo-acme?X-Amz-Signature=...",
            }
        }
    }


class AceitoResponse(BaseModel):
    status: str = Field("accepted", examples=["accepted"])


class HealthResponse(BaseModel):
    ok: bool = True


@app.post(
    "/generate",
    status_code=202,
    tags=["geração"],
    summary="Dispara a geração das artes de uma vaga",
    description=(
        "Aceita e enfileira o trabalho em *background* (responde na hora). "
        "Gera `CRIATIVOS_POR_VAGA` artes (default 3) no card do ClickUp indicado "
        "por `task` — cada uma com cor e foto próprias, metade via Pexels e "
        "metade via Unsplash. Um objeto de vaga, ou uma lista com um objeto "
        "(formato do n8n)."
    ),
    response_model=AceitoResponse,
    responses={
        401: {"description": "Token ausente ou inválido (quando `GENERATE_TOKEN` está definido)."},
        422: {"description": "Payload inválido (campo obrigatório ausente: `cargo`, `localizacoes`, `task`)."},
    },
)
async def generate(
    background: BackgroundTasks,
    _: None = Depends(verificar_token),
    payload: VagaPayload | list[VagaPayload] = Body(
        ...,
        description="Um objeto de vaga, ou uma lista com um objeto (formato que o n8n envia).",
    ),
) -> AceitoResponse:
    if isinstance(payload, list):
        if not payload:
            raise HTTPException(status_code=422, detail="lista de vagas vazia")
        payload = payload[0]
    dados = payload.model_dump()
    # N artes por vaga: cada uma é um pipeline independente (sorteia cor/foto
    # próprias). Metade com foto do Pexels, metade do Unsplash — o extra (N
    # ímpar) fica com o Pexels. As background tasks rodam em sequência após a
    # resposta.
    n = config.CRIATIVOS_POR_VAGA
    n_pexels = -(-n // 2)  # ceil(n / 2)
    providers = ["pexels"] * n_pexels + ["unsplash"] * (n - n_pexels)
    for provider in providers:
        background.add_task(processar, dados, provider)
    return AceitoResponse(status="accepted")


@app.get(
    "/health",
    tags=["infra"],
    summary="Health check",
    response_model=HealthResponse,
)
async def health() -> HealthResponse:
    return HealthResponse(ok=True)
