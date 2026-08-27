"""Orquestração — uma chamada à API = uma arte nova, anexada no card do ClickUp.

Payload de entrada (ver app/main.py: POST /generate):
{
  "cargo": str, "segmento": str|None, "empresa": str|None, "nivel": str|None,
  "localizacoes": [str, ...], "sigilosa": bool, "task": str (ClickUp task_id),
  "logo": str|None (URL assinada da logo, sem extensão — convertida pra PNG)
}
Quem chama (n8n) já resolveu os dados da vaga — o pipeline não busca mais nada
em sistema externo de vaga, só ClickUp (pra anexar o resultado), Pexels/OpenAI
(foto) e a própria URL da logo recebida.

Mapa dos critérios de aceite:
- sorteio de cor (paleta oficial) e foto (Pexels, exclui últimas N)      → etapa 1
- logo da contratante (recebida pronta no payload); sigilosa=true omite → etapa 1
- múltiplas localizações harmônicas                             → template (pills + auto-ajuste)
- PNG ≥1080px anexado com timestamp e "Gerado automaticamente"  → etapas 2-3
- retry 3x já embutido em pexels.py / render.py / logo.py;
  falha final → comenta no card + notifica o canal              → except final
- sem dedup: cada chamada gera arte nova
"""
import asyncio
import logging
from datetime import datetime, timezone

import httpx

from . import clickup, config, logo, openai_client, pexels, render, rosto, sorteio

log = logging.getLogger("pipeline")


async def _notificar_falha(task_id: str, erro: str) -> None:
    """Mesmo canal já usado pelo fluxo de inbound para falhas de geração de arte."""
    if not config.NOTIFY_WEBHOOK_URL:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as cli:
            await cli.post(
                config.NOTIFY_WEBHOOK_URL,
                json={"origem": "gerador-arte-salesjobs", "task_id": task_id, "erro": erro},
            )
    except Exception:
        log.exception("falha ao notificar o canal")


async def processar(dados: dict) -> None:
    task_id = dados["task"]
    log.info("iniciando task %s", task_id)
    try:
        vaga = {
            "titulo": dados["cargo"],
            "segmento": dados.get("segmento") or "",
            "nivel": dados.get("nivel") or "",
            "empresa": dados.get("empresa") or "",
            "localizacoes": dados["localizacoes"],
        }
        sigilosa = bool(dados.get("sigilosa"))

        # 1. logo (já vem pronta no payload) + sorteios: cor + foto via Pexels
        #    (query gerada por GPT, exclui últimas N já usadas)
        logo_empresa = None
        if not sigilosa:
            logo_empresa = await asyncio.to_thread(logo.baixar_png, dados.get("logo"))

        combinacao = sorteio.sortear_combinacao()
        contexto = {"segmento": vaga["segmento"], "empresa": vaga["empresa"], "nivel": vaga["nivel"]}
        query = await openai_client.gerar_query_foto(vaga["titulo"], contexto) or f"{vaga['titulo']} portrait"
        pool = await asyncio.to_thread(pexels.buscar_fotos, query)
        pool = await asyncio.to_thread(rosto.ordenar_por_rosto, pool)
        foto = sorteio.escolher_foto(pool)
        foto_uri = await asyncio.to_thread(rosto.enquadrar, foto, combinacao["elipse"])

        # 2. montar HTML e renderizar em alta resolução (retry 3x embutido)
        html = render.montar_html(vaga, combinacao, foto_uri, logo_empresa, sigilosa)
        png = await render.render_png(html)

        # 3. anexar no card com timestamp + identificação
        ts = datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M")
        filename = f"arte-{task_id}-{combinacao['id']}-{datetime.now():%Y%m%d%H%M%S}.png"
        await clickup.attach_file(task_id, filename, png)
        await clickup.post_comment(
            task_id,
            f"🤖 Gerado automaticamente — {ts}\n"
            f"{vaga['titulo']} · combinação {combinacao['id']}"
            f"{' · 🔒 sigilosa' if sigilosa else ''}",
        )
        log.info("task %s concluída (%s)", task_id, filename)

    except Exception as err:  # falhas técnicas após os retries
        log.exception("erro na task %s", task_id)
        msg = f"❌ Erro ao gerar arte: {err}"
        try:
            await clickup.post_comment(task_id, msg)
        except Exception:
            log.exception("falha ao comentar o erro no card")
        await _notificar_falha(task_id, str(err))
