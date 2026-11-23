"""Orquestração Foursales — uma chamada = um PDF novo anexado no card (LAB-2239).

Payload (POST /generate-foursales, já resolvido pelo n8n):
  cargo, segmento, localizacoes[], desafio, modelo (opcional), nivel (opcional), task

Regras:
- dado obrigatório ausente (cargo, segmento, localizacoes, desafio) → comenta no
  card qual campo falta e encerra SEM erro (não notifica o Discord);
- modelo de trabalho vazio → PDF sai sem essa linha;
- nunca usa nome nem logo da contratante (vaga sigilosa ou não);
- falha técnica: retry embutido (busca de foto, render); persistindo, comenta o
  erro no card e notifica o Discord (mesmo canal do Salesjobs);
- sucesso: anexa o PDF e comenta "Gerado automaticamente" com data e hora.
"""
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from .. import clickup, notify, openai_client, pexels, rosto, sorteio, unsplash
from ..pipeline import buscar_pool
from . import capa, foto, render, textos

log = logging.getLogger("foursales")
_TZ = ZoneInfo("America/Sao_Paulo")
_OBRIGATORIOS = {"cargo": "título", "segmento": "segmento", "localizacoes": "localização", "desafio": "desafio"}


def faltantes(dados: dict) -> list[str]:
    return [nome for campo, nome in _OBRIGATORIOS.items() if not dados.get(campo)]


async def _segmento(segmento: str) -> str:
    s = segmento.replace("&amp;", "&").strip().rstrip(".;")
    if not textos.precisa_encurtar(s):
        return s
    out = await openai_client.resumir(
        'Resuma o segmento de mercado de uma empresa em no máximo 3 palavras em português, '
        'com iniciais maiúsculas, sem citar tipo de empresa (fabricante, distribuidora...). '
        'Ex.: "Distribuidora do segmento químicos & ingredientes para alimentos." → "Ingredientes para Alimentos". '
        'Responda APENAS com JSON: {"segmento": "<texto>"}',
        s,
    )
    curto = (out or {}).get("segmento")
    return curto.strip() if isinstance(curto, str) and 0 < len(curto.strip()) <= 34 else textos.segmento_curto_local(s)


async def _escolher_foto(vaga: dict) -> tuple[bytes, rosto.Rosto, str]:
    contexto = {"segmento": vaga["segmento"], "nivel": vaga.get("nivel") or ""}
    queries = await openai_client.gerar_queries_foto(vaga["titulo"], contexto, foto.INSTRUCOES_QUERIES) or [
        "executive portrait office",
        "confident executive portrait suit",
    ]
    log.info("queries: %r", queries)
    pool = []
    for prov in (pexels, unsplash):
        try:
            pool += await asyncio.to_thread(buscar_pool, prov, queries)
        except Exception as err:  # um provider fora não trava se o outro respondeu
            log.warning("busca em %s falhou: %s", prov.__name__, err)
    if not pool:
        raise RuntimeError("nenhuma foto encontrada nos bancos de imagem")
    pool = await asyncio.to_thread(foto.analisar, pool)
    notas = await openai_client.curar_fotos(
        vaga["titulo"], contexto, foto.candidatas_curadoria(pool), foto.INSTRUCOES_CURADORIA
    )
    escolhida = sorteio.escolher_foto(pool, notas)
    if not escolhida.get("rosto"):
        raise RuntimeError("nenhuma foto do banco atende aos critérios da capa (rosto, cor, enquadramento)")
    dados = await asyncio.to_thread(rosto._baixar_bytes, escolhida["url"])
    log.info("foto escolhida: %s (nota %s)", escolhida["id"], (notas or {}).get(escolhida["id"]))
    return dados, escolhida["rosto"], escolhida["id"]


async def processar(dados: dict) -> None:
    task_id = str(dados.get("task") or "?")
    etapa = "validação"
    try:
        falta = faltantes(dados)
        if falta:
            await clickup.post_comment(
                task_id, f"⚠️ PDF de divulgação não gerado: falta {', '.join(falta)} da vaga. Gerado automaticamente."
            )
            log.info("[%s] dados faltando: %s", task_id, falta)
            return

        etapa = "textos"
        locs = [textos.formatar_localizacao(l) for l in dados["localizacoes"] if l and l.strip()]
        vaga = {
            "titulo": textos.limpar_titulo(dados["cargo"], locs),
            "segmento": await _segmento(dados["segmento"]),
            "localizacoes": locs,
            "modelo": textos.formatar_modelo(dados.get("modelo")),
            "desafio": " ".join(str(dados["desafio"]).split()),
            "nivel": dados.get("nivel"),
        }
        log.info("[%s] vaga: %s", task_id, {k: v for k, v in vaga.items() if k != "desafio"})

        etapa = "escolha da foto"
        foto_bytes, r, foto_id = await _escolher_foto(vaga)

        etapa = "montagem da capa"
        capa_uri = await asyncio.to_thread(capa.montar, foto_bytes, r)

        etapa = "render HTML→PDF"
        pdf, ajustes = await render.render_pdf(render.montar_html(vaga, capa_uri))
        log.info("[%s] pdf ok: %d KB, ajustes %s", task_id, len(pdf) // 1024, ajustes)

        etapa = "anexo no ClickUp"
        agora = datetime.now(_TZ)
        nome = f"divulgacao-foursales-{task_id}-{agora:%Y%m%d-%H%M%S}.pdf"
        anexo = await clickup.attach_file(task_id, nome, pdf, "application/pdf")
        url = anexo.get("url") or ""
        await clickup.post_comment(
            task_id,
            f"📄 PDF de divulgação Foursales — Gerado automaticamente em {agora:%d/%m/%Y às %H:%M}.\n{nome}\n{url}".strip(),
        )
        log.info("[%s] concluída (%s, foto %s)", task_id, nome, foto_id)

    except Exception as err:
        log.exception("[%s] erro na etapa '%s'", task_id, etapa)
        try:
            await clickup.post_comment(task_id, f"❌ Erro ao gerar o PDF de divulgação (etapa: {etapa}): {err}")
        except Exception:
            log.exception("[%s] falha ao comentar o erro no card", task_id)
        await notify.erro_discord(
            f"❌ Falha ao gerar PDF Foursales — task {task_id}",
            contexto={"task": task_id, "cargo": dados.get("cargo"), "etapa": etapa, "erro": f"{type(err).__name__}: {err}"},
            exc=err,
        )
