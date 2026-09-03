"""Notificação de falhas no Discord (bot API v10).

`erro_discord()` manda uma mensagem no canal `DISCORD_CHANNEL_ID` via
`POST /channels/{id}/messages` (`Authorization: Bot {DISCORD_BOT_TOKEN}`),
com um `content` curto de alerta + um embed vermelho trazendo os campos de
contexto e o traceback completo (truncado aos limites do Discord).

Sem token/canal configurados → só registra um WARNING no log e segue. Qualquer
erro na própria notificação é engolido — notificar falha nunca pode derrubar o
fluxo principal.
"""
import logging
import traceback
from datetime import datetime, timezone

import httpx

from . import config

log = logging.getLogger("notify")

_API = "https://discord.com/api/v10"
_COR_ERRO = 0xE01E37
_LIM_CONTENT = 2000
_LIM_DESCRICAO = 4000  # limite real 4096; folga pra cerca ```py e o aviso de corte
_LIM_CAMPO = 1024      # embed field value


def _auth_header() -> str:
    token = config.DISCORD_BOT_TOKEN.strip()
    if token.lower().startswith(("bot ", "bearer ")):
        return token
    return f"Bot {token}"


def _bloco_traceback(exc: BaseException) -> str:
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    if len(tb) > _LIM_DESCRICAO:
        tb = "…(início do traceback cortado)…\n" + tb[-_LIM_DESCRICAO:]  # o fim é a parte útil
    return f"```py\n{tb}\n```"


async def erro_discord(
    titulo: str,
    *,
    contexto: dict | None = None,
    exc: BaseException | None = None,
) -> None:
    if not (config.DISCORD_BOT_TOKEN and config.DISCORD_CHANNEL_ID):
        log.warning("Discord não configurado (DISCORD_BOT_TOKEN/DISCORD_CHANNEL_ID) — falha não notificada: %s", titulo)
        return

    content = f"🚨 **(URGENTE)**\nErro no workflow: **{config.DISCORD_PROJETO}**\n{titulo}"
    if config.DISCORD_MENTION:
        content = f"{config.DISCORD_MENTION}\n{content}"

    embed: dict = {
        "title": titulo[:256],
        "color": _COR_ERRO,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {"text": "gerador-arte-salesjobs"},
    }
    if contexto:
        embed["fields"] = [
            {"name": str(k)[:256], "value": (str(v) or "—")[:_LIM_CAMPO], "inline": True}
            for k, v in contexto.items()
        ]
    if exc is not None:
        embed["description"] = _bloco_traceback(exc)

    body = {
        "content": content[:_LIM_CONTENT],
        "allowed_mentions": {"parse": ["users", "roles", "everyone"]},
        "embeds": [embed],
    }

    try:
        async with httpx.AsyncClient(timeout=10) as cli:
            r = await cli.post(
                f"{_API}/channels/{config.DISCORD_CHANNEL_ID}/messages",
                headers={"Authorization": _auth_header()},
                json=body,
            )
        if r.is_error:
            log.error("Discord recusou a notificação: %s %s", r.status_code, r.text[:500])
    except Exception:
        log.exception("falha ao notificar o Discord")
