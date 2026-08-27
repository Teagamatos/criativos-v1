"""Render HTML → PNG com Playwright (Chromium headless, singleton).

Viewport 1200×1500 (formato do Figma; atende o mínimo de 1080px do card).
RENDER_SCALE > 1 usa device_scale_factor para subir a resolução sem tocar no CSS.
"""
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup
from playwright.async_api import Browser, async_playwright
from tenacity import retry, stop_after_attempt, wait_exponential

from . import config

_env = Environment(
    loader=FileSystemLoader(config.TEMPLATE_PATH.parent),
    autoescape=select_autoescape(["html"]),
)

_browser: Browser | None = None
_pw = None


# Área máxima reservada pra logo no template (topo esquerdo) — a moldura
# (fundo/borda/sombra) é desenhada exatamente no tamanho final da imagem
# (calculado aqui, tipo "contain"), não numa caixa fixa maior que a logo.
_LOGO_MAX_W = 303
_LOGO_MAX_H = 189


def _logo_tamanho(logo_empresa: dict | None) -> tuple[int, int] | None:
    if not logo_empresa:
        return None
    escala = min(_LOGO_MAX_W / logo_empresa["largura"], _LOGO_MAX_H / logo_empresa["altura"])
    return round(logo_empresa["largura"] * escala), round(logo_empresa["altura"] * escala)


def montar_html(vaga: dict, combinacao: dict, foto_uri: str, logo_empresa: dict | None, sigilosa: bool) -> str:
    pills = Markup("").join(
        Markup('<span class="pill">{}</span>').format(loc) for loc in vaga["localizacoes"]
    )
    tamanho = _logo_tamanho(logo_empresa)
    fundo_colorido = combinacao["fundo"] != "#FFFFFF"
    tpl = _env.get_template(config.TEMPLATE_PATH.name)
    return tpl.render(
        CARGO=vaga["titulo"],
        LOCALIDADES_HTML=pills,
        FOTO_URL=foto_uri,
        LOGO_EMPRESA_URL=logo_empresa["url"] if logo_empresa else "",
        LOGO_EMPRESA_W=tamanho[0] if tamanho else 0,
        LOGO_EMPRESA_H=tamanho[1] if tamanho else 0,
        LOGO_SALESJOBS_URL=config.LOGO_SALESJOBS_BRANCO_URL if fundo_colorido else config.LOGO_SALESJOBS_URL,
        MODO_SIGILOSA="sigilosa" if sigilosa or not logo_empresa else "",
        MODO_FUNDO_COLORIDO="fundo-colorido" if fundo_colorido else "",
        COR_FUNDO=combinacao["fundo"],
        COR_TEXTO=combinacao["texto"],
        COR_PILL_FUNDO=combinacao["pill_fundo"],
        COR_PILL_TEXTO=combinacao["pill_texto"],
        COR_ELIPSE=combinacao["elipse"],
        COR_CARD_LOGO=combinacao["card_logo_fundo"],
        COR_BORDA_LOGO=combinacao["borda_logo_empresa"],
    )


async def _get_browser() -> Browser:
    global _browser, _pw
    if _browser is None or not _browser.is_connected():
        _pw = await async_playwright().start()
        _browser = await _pw.chromium.launch(args=["--no-sandbox"])
    return _browser


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8), reraise=True)
async def render_png(html: str) -> bytes:
    browser = await _get_browser()
    page = await browser.new_page(
        viewport={"width": 1200, "height": 1500},
        device_scale_factor=config.RENDER_SCALE,
    )
    try:
        await page.set_content(html, wait_until="networkidle")
        await page.evaluate("document.fonts.ready")
        await page.wait_for_timeout(150)  # deixa o script de auto-ajuste assentar
        return await page.screenshot(type="png")
    finally:
        await page.close()


async def close_browser() -> None:
    global _browser, _pw
    if _browser:
        await _browser.close()
        _browser = None
    if _pw:
        await _pw.stop()
        _pw = None
