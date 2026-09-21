"""Orquestração — uma chamada à API = uma arte nova, anexada no card do ClickUp.

Payload de entrada (ver app/main.py: POST /generate):
{
  "cargo": str, "segmento": str|None, "empresa": str|None, "nivel": str|None,
  "localizacoes": [str, ...], "sigilosa": bool, "task": str (ClickUp task_id),
  "logo": str|None (URL assinada da logo, sem extensão — convertida pra PNG)
}
Quem chama (n8n) já resolveu os dados da vaga — o pipeline não busca mais nada
em sistema externo de vaga, só ClickUp (pra anexar o resultado), Pexels/Unsplash +
OpenAI (foto) e a própria URL da logo recebida.

Mapa dos critérios de aceite:
- sorteio de cor (paleta oficial) e foto (banco de imagens → rosto → curadoria
  por visão, exclui últimas N)                                   → etapa 1
- logo da contratante (recebida pronta no payload); sigilosa=true omite → etapa 1
- múltiplas localizações harmônicas                             → template (pills + auto-ajuste)
- PNG ≥1080px anexado, timestamp no nome do arquivo (sem comentário) → etapas 2-3
- retry 3x já embutido em pexels.py / unsplash.py / render.py / logo.py;
  falha final → comenta o ERRO no card + notifica o Discord            → except final
- sem dedup: cada chamada gera arte nova

Observabilidade: cada etapa loga início/fim com o task_id como prefixo. A falha
registra `log.exception` (traceback completo no stdout, que o Railway captura)
e dispara `notify.erro_discord` com a etapa em que quebrou.
"""
import asyncio
import logging
from datetime import datetime
from itertools import zip_longest

from . import clickup, config, logo, notify, openai_client, pexels, render, rosto, sorteio, unsplash

_PROVIDERS = {"pexels": pexels, "unsplash": unsplash}

log = logging.getLogger("pipeline")


def buscar_pool(provider, queries: list[str]) -> list[dict]:
    """Busca cada query no provider e junta os resultados sem repetir foto,
    intercalando (1º de cada query, 2º de cada query…) pra que todas as queries
    tenham representantes entre as primeiras candidatas. Uma query que falha
    (rate limit, etc.) é ignorada se outra respondeu; se todas falham, propaga."""
    resultados, erro = [], None
    for q in queries:
        try:
            resultados.append(provider.buscar_fotos(q))
        except Exception as err:
            log.warning("busca %r falhou (%s: %s)", q, type(err).__name__, err)
            erro = err
    if not resultados and erro:
        raise erro
    pool, vistos = [], set()
    for grupo in zip_longest(*resultados):
        for foto in grupo:
            if foto and foto["id"] not in vistos:
                vistos.add(foto["id"])
                pool.append(foto)
    return pool


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

        # 1. logo (já vem pronta no payload) + sorteios: cor + foto (query gerada por
        #    GPT → banco de imagens → rosto → curadoria por visão; exclui últimas N)
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
        queries = await openai_client.gerar_queries_foto(vaga["titulo"], contexto) or [f"{vaga['titulo']} portrait"]
        log.info("[%s] queries (%s): %r", task_id, provider_nome, queries)

        etapa = f"busca de foto ({provider_nome})"
        pool = await asyncio.to_thread(buscar_pool, provider, queries)
        pool = await asyncio.to_thread(rosto.ordenar_por_rosto, pool)
        com_rosto = rosto.candidatas_curadoria(pool)
        log.info("[%s] pool: %d fotos, %d com rosto detectado", task_id, len(pool), len(com_rosto))

        etapa = "curadoria da foto (OpenAI visão)"
        notas = await openai_client.curar_fotos(vaga["titulo"], contexto, com_rosto)
        log.info("[%s] curadoria: %s", task_id, notas if notas is not None else "indisponível (segue só com filtro de rosto)")

        etapa = "escolha e enquadramento da foto"
        foto = sorteio.escolher_foto(pool, notas)
        foto_uri = await asyncio.to_thread(rosto.enquadrar, foto)
        nota = (notas or {}).get(foto["id"])
        log.info("[%s] foto escolhida: %s (nota %s, rosto detectado: %s)", task_id, foto["id"], nota, foto.get("rosto") is not None)
        if nota is not None and nota < 6:
            log.warning("[%s] melhor foto do pool tem nota baixa (%s) — queries %r", task_id, nota, queries)

        # 2. montar HTML e renderizar em alta resolução (retry 3x embutido)
        etapa = "render HTML→PNG"
        html = render.montar_html(vaga, combinacao, foto_uri, logo_empresa, sigilosa)
        png = await render.render_png(html)
        log.info("[%s] render ok: %d KB", task_id, len(png) // 1024)

        # 3. anexar no card (só o anexo, sem comentário — não poluir o card);
        #    timestamp e combinação de cor vão no nome do arquivo
        etapa = "anexo no ClickUp"
        filename = f"arte-{task_id}-{combinacao['id']}-{datetime.now():%Y%m%d%H%M%S}.png"
        await clickup.attach_file(task_id, filename, png)
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
