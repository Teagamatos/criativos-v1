"""HTML do PDF Foursales (3 páginas 1080×1350) e render HTML → PDF.

As coordenadas são as do frame do Figma (1438×1797.52) e a página é reescalada
pra 1080 de largura. Tamanhos de fonte/espaçamento foram calibrados medindo o
export do Figma pixel a pixel.

Página 1: capa (imagem montada em capa.py) + textos da vaga.
Página 2: fundo do template + localização/modelo + desafio.
Página 3: export fixo do Figma (igual pra todas as vagas).
"""
import base64
import html
import logging
from functools import lru_cache

from tenacity import before_sleep_log, retry, stop_after_attempt, wait_exponential

from .. import config
from ..render import _get_browser

log = logging.getLogger("foursales.render")

ASSETS = config.BASE_DIR / "templates" / "foursales"
FW, FH = 1438.0167, 1797.521
GOLD = "#F2CB7A"


@lru_cache(maxsize=None)
def _b64(nome: str) -> str:
    return base64.b64encode((ASSETS / nome).read_bytes()).decode()


@lru_cache(maxsize=None)
def _svg(nome: str, cor_branca: str | None = None) -> str:
    s = (ASSETS / nome).read_text(encoding="utf-8")
    if cor_branca:
        s = s.replace('fill="white"', f'fill="{cor_branca}"')
    # ocupa a caixa onde é posicionado
    s = s.replace('width="', 'width="100%" data-w="', 1).replace('height="', 'height="100%" data-h="', 1)
    return s


CSS = f"""
@font-face {{ font-family: LF; src: url(data:font/ttf;base64,{{fonte}}); font-weight: 100 900; }}
@page {{ size: 1080px 1350px; margin: 0; }}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: LF, sans-serif; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
.sheet {{ width: 1080px; height: 1350px; overflow: hidden; position: relative; page-break-after: always; }}
.page {{ width: {FW}px; height: {FH}px; position: absolute; left: 0; top: 0; transform-origin: 0 0; transform: scale({1080 / FW}); overflow: hidden; }}
.abs {{ position: absolute; }}
.bg {{ position: absolute; left: -5.327px; top: 0; width: 1448.198px; height: {FH}px; object-fit: cover; }}
.eyebrow {{ color: {GOLD}; font-size: 32.7px; letter-spacing: .40em; line-height: 51px; text-transform: uppercase; white-space: nowrap; }}
.title {{ color: #fff; font-size: 80px; letter-spacing: .025em; line-height: 86.5px; font-weight: 300; }}
.title b {{ font-weight: 700; }}
.seg {{ color: #fff; font-size: 44.5px; letter-spacing: .03em; line-height: 48px; font-weight: 500; }}
.footer {{ color: #fff; font-size: 28px; letter-spacing: .035em; line-height: 32px; font-weight: 300; }}
.footer b {{ font-weight: 700; }}
.sobre {{ color: {GOLD}; font-size: 39.4px; letter-spacing: .435em; line-height: 59px; text-transform: uppercase; white-space: nowrap; }}
.local {{ color: rgba(255,255,255,.55); font-size: 23.8px; letter-spacing: .40em; line-height: 35px; white-space: nowrap; }}
.porto {{ color: #fff; font-size: 70px; line-height: 84.5px; font-weight: 600; }}
.modelo {{ color: #fff; font-size: 55px; letter-spacing: .02em; line-height: 84.5px; font-weight: 300; }}
.lorem {{ color: #fff; font-size: 41px; letter-spacing: .004em; line-height: 49.625px; font-weight: 400; }}
.box {{ border-radius: 28px; border: 1.5px solid rgba(255,255,255,.16); border-top-color: rgba(255,255,255,.07);
  border-left-color: rgba(255,255,255,.10); background: rgba(0,6,28,.32); }}
"""

# Ajustes dependentes do conteúdo, rodados no browser antes do PDF:
# - título longo: reduz a fonte até caber nas 4 linhas do template;
# - segmento logo abaixo do título;
# - várias localizações: a caixa cresce e empurra "O desafio".
AJUSTE_JS = """() => {
  const r = {};
  const t = document.getElementById('title'), s = document.getElementById('seg');
  let fs = 80; const maxH = 348;
  while (t.offsetHeight > maxH && fs > 56) { fs -= 2; t.style.fontSize = fs + 'px'; t.style.lineHeight = (fs * 1.081) + 'px'; }
  r.titulo_fonte = fs; r.titulo_cabe = t.offsetHeight <= maxH;
  s.style.top = (t.offsetTop + t.offsetHeight + 27.7) + 'px';
  const box = document.getElementById('box'), lb = document.getElementById('locblk');
  const delta = Math.max(0, (lb.offsetTop + lb.offsetHeight + 38.5) - box.offsetTop - 317.577);
  if (delta) { box.style.height = (317.577 + delta) + 'px';
    for (const id of ['dtit', 'desafio']) { const e = document.getElementById(id); e.style.top = (e.offsetTop + delta) + 'px'; } }
  const d = document.getElementById('desafio');
  r.desafio_cabe = d.offsetTop + d.offsetHeight < 1760;
  return r; }"""


def _titulo_html(t: str) -> str:
    """Template: primeira palavra (+ "de/da/do") em negrito na 1ª linha."""
    w = t.split()
    n = 2 if len(w) > 2 and w[1].lower() in ("de", "da", "do", "of") else 1
    return f"<b>{html.escape(' '.join(w[:n]))}</b><br>" + html.escape(" ".join(w[n:]))


def montar_html(vaga: dict, capa_uri: str) -> str:
    locs = "<br>".join(html.escape(x) for x in vaga["localizacoes"])
    modelo = f'<div class="modelo">{html.escape(vaga["modelo"])}</div>' if vaga.get("modelo") else ""
    rodape = '<b>Confira mais</b> posições<br>executivas no nosso site'
    p1 = f"""<div class="sheet"><div class="page">
  <img class="bg" src="{capa_uri}">
  <div class="abs" style="left:-678.6px;top:795.3px;width:1940.44px;height:1939.44px">{_svg("sombra_capa.svg")}</div>
  <div class="abs" style="left:106.518px;top:183.746px;width:266.113px;height:41.045px">{_svg("logo_foursales.svg")}</div>
  <div class="abs eyebrow" style="left:106.519px;top:354.178px">Posição em destaque</div>
  <div class="abs title" id="title" style="left:106.52px;top:470.7px;width:644.613px">{_titulo_html(vaga["titulo"])}</div>
  <div class="abs seg" id="seg" style="left:106.519px;top:850.926px;width:620px">{html.escape(vaga["segmento"])}</div>
  <div class="abs footer" style="left:106.519px;top:1645.7px;width:420px">{rodape}</div>
</div></div>"""
    p2 = f"""<div class="sheet"><div class="page">
  <img class="bg" style="left:-5.092px" src="data:image/jpeg;base64,{_b64("pagina2_fundo.jpg")}">
  <div class="abs" style="left:-1172.5px;top:-745.1px;width:2908.26px;height:2908.26px">{_svg("sombra_pagina2.svg")}</div>
  <div class="abs sobre" style="left:124.855px;top:288.398px">Sobre a posição</div>
  <div class="abs box" id="box" style="left:125.246px;top:416.779px;width:970.181px;height:317.577px"></div>
  <div class="abs" style="left:188.34px;top:527.79px;width:83.677px;height:97.403px">{_svg("icone_localizacao.svg")}</div>
  <div class="abs local" style="left:329.309px;top:474.269px">LOCALIZAÇÃO</div>
  <div class="abs" id="locblk" style="left:329.309px;top:526.932px;width:740px"><div class="porto">{locs}</div>{modelo}</div>
  <div class="abs sobre" id="dtit" style="left:124.855px;top:875.438px">O desafio</div>
  <div class="abs lorem" id="desafio" style="left:125.246px;top:1004.238px;width:960.875px">{html.escape(vaga["desafio"])}</div>
</div></div>"""
    p3 = f"""<div class="sheet"><div class="page">
  <img class="abs" style="left:0;top:0;width:{FW}px;height:{FH}px" src="data:image/jpeg;base64,{_b64("pagina3.jpg")}">
</div></div>"""
    css = CSS.replace("{fonte}", _b64("LibreFranklin.ttf"))
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{p1}{p2}{p3}</body></html>"


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=8),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)
async def render_pdf(html_doc: str) -> tuple[bytes, dict]:
    """HTML → PDF (3 páginas 1080×1350). Devolve também o resultado dos ajustes."""
    browser = await _get_browser()
    page = await browser.new_page(viewport={"width": 1080, "height": 1350})
    try:
        await page.set_content(html_doc, wait_until="load")
        await page.evaluate("document.fonts.ready")
        ajustes = await page.evaluate(AJUSTE_JS)
        pdf = await page.pdf(width="1080px", height="1350px", print_background=True)
        return pdf, ajustes
    finally:
        await page.close()
