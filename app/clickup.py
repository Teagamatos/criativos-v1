"""Cliente ClickUp API v2 — só o necessário pra anexar o resultado no card.

Observação herdada do fluxo atual (mvp-arte): o token pessoal vai PURO no
header Authorization (sem "Bearer").
"""
import httpx

from . import config

BASE = "https://api.clickup.com/api/v2"
_HEADERS = {"Authorization": config.CLICKUP_API_TOKEN}


async def post_comment(task_id: str, texto: str) -> None:
    async with httpx.AsyncClient(timeout=15) as cli:
        r = await cli.post(
            f"{BASE}/task/{task_id}/comment",
            headers=_HEADERS,
            json={"comment_text": texto},
        )
        r.raise_for_status()


async def attach_file(task_id: str, filename: str, content: bytes) -> None:
    async with httpx.AsyncClient(timeout=60) as cli:
        r = await cli.post(
            f"{BASE}/task/{task_id}/attachment",
            headers=_HEADERS,
            files={"attachment": (filename, content, "image/png")},
        )
        r.raise_for_status()
