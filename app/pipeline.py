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
  falha final → comenta no card + notifica o Discord            → except final
- sem dedup: cada chamada gera arte nova

Observabilidade: cada etapa loga início/fim com o task_id como prefixo. A falha
registra `log.exception` (traceback completo no stdout, que o Railway captura)
e dispara `notify.erro_discord` com a etapa em que quebrou.
"""
import asyncio
import logging
from datetime import datetime, timezone

from . import clickup, config, logo, notify, openai_client, pexels, render, rosto, sorteio, unsplash

_PROVIDERS = {"pexels": pexels, "unsplash": unsplash}

log = logging.getLogger("pipeline")


async def processar(dados: dict, foto_provider: str | None = None) -> None:
    task_id = str(dados.get("task") or "?")
    etapa = "validação"
    log.info("[%s] iniciando — cargo=%r sigilosa=%s", task_id, dados.get("cargo"), bool(dados.get("sigilosa")))
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
        etapa = "logo da contratante"
        logo_empresa = None
        if not sigilosa:
            logo_empresa = await asyncio.to_thread(logo.baixar_png, dados.get("logo"))
            log.info("[%s] logo: %s", task_id, "ok" if logo_empresa else "ausente/falhou (arte sai sem logo)")

        etapa = "sorteio de cor"
        combinacao = sorteio.sortear_combinacao()
        log.info("[%s] combinação sorteada: %s", task_id, combinacao["id"])

        provider = _PROVIDERS.get(foto_provider or config.FOTO_PROVIDER, pexels)
        provider_nome = provider.__name__.split(".")[-1]

        etapa = "query da foto (OpenAI)"
        contexto = {"segmento": vaga["segmento"], "empresa": vaga["empresa"], "nivel": vaga["nivel"]}
        query = await openai_client.gerar_query_foto(vaga["titulo"], contexto) or f"{vaga['titulo']} portrait"
        log.info("[%s] query (%s): %r", task_id, provider_nome, query)

        etapa = f"busca de foto ({provider_nome})"
        pool = await asyncio.to_thread(provider.buscar_fotos, query)
        pool = await asyncio.to_thread(rosto.ordenar_por_rosto, pool)
        foto = sorteio.escolher_foto(pool)
        foto_uri = await asyncio.to_thread(rosto.enquadrar, foto, combinacao["elipse"])
        log.info("[%s] foto escolhida: %s (rosto detectado: %s)", task_id, foto["id"], foto.get("rosto") is not None)

        # 2. montar HTML e renderizar em alta resolução (retry 3x embutido)
        etapa = "render HTML→PNG"
        html = render.montar_html(vaga, combinacao, foto_uri, logo_empresa, sigilosa)
        png = await render.render_png(html)
        log.info("[%s] render ok: %d KB", task_id, len(png) // 1024)

        # 3. anexar no card com timestamp + identificação
        etapa = "anexo no ClickUp"
        ts = datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M")
        filename = f"arte-{task_id}-{combinacao['id']}-{datetime.now():%Y%m%d%H%M%S}.png"
        await clickup.attach_file(task_id, filename, png)
        await clickup.post_comment(
            task_id,
            f"🤖 Gerado automaticamente — {ts}\n"
            f"{vaga['titulo']} · combinação {combinacao['id']}"
            f"{' · 🔒 sigilosa' if sigilosa else ''}",
        )
        log.info("[%s] concluída (%s)", task_id, filename)

    except Exception as err:  # falhas técnicas após os retries
        log.exception("[%s] erro na etapa '%s'", task_id, etapa)
        try:
            await clickup.post_comment(task_id, f"❌ Erro ao gerar arte (etapa: {etapa}): {err}")
        except Exception:
            log.exception("[%s] falha ao comentar o erro no card", task_id)
        await notify.erro_discord(
            f"❌ Falha ao gerar arte — task {task_id}",
            contexto={
                "task": task_id,
                "cargo": dados.get("cargo"),
                "etapa": etapa,
                "erro": f"{type(err).__name__}: {err}",
            },
            exc=err,
        )
