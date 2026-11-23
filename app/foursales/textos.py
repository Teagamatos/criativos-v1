"""Normalização dos textos que vão no PDF (título, segmento, localização, modelo)."""
import re
import unicodedata

_UFS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB",
    "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}
_SEP = re.compile(r"\s+[-–|]\s+")
_SEGMENTO_MAX = 30


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()


def _parece_local(parte: str, cidades: set[str]) -> bool:
    p = parte.strip()
    if re.fullmatch(r"\(?[A-Z]{2}\)?", p) and p.strip("()") in _UFS:
        return True
    if re.search(r"\((?:%s)\)\s*$" % "|".join(_UFS), p):  # "Biguaçu (SC)"
        return True
    base = _sem_acento(re.sub(r"\(.*?\)", "", p)).strip(" ,/")
    return bool(base) and any(base == c or base.startswith(c) for c in cidades)


def limpar_titulo(cargo: str, localizacoes: list[str]) -> str:
    """Tira a localização que alguns cards colam no título.

    "Gerente Marketing - Biguaçu (SC)" → "Gerente Marketing"
    "Executivo(a) de Vendas B2B | Porto Alegre (RS)" → "Executivo(a) de Vendas B2B"
    "Gerente Regional de Vendas | SP" → "Gerente Regional de Vendas"
    "Gerente de Vendas - Papel e Celulose" → mantém (não é local)
    """
    cidades = {_sem_acento(l.split(",")[0].split("|")[0]).strip() for l in localizacoes if l}
    partes = _SEP.split(cargo.strip())
    while len(partes) > 1 and _parece_local(partes[-1], cidades):
        partes.pop()
    return " - ".join(partes).strip()


def formatar_localizacao(loc: str) -> str:
    """"Taubaté | SP" / "Taubaté - SP" / "Taubaté (SP)" → "Taubaté, SP". "Remoto" fica igual."""
    s = re.sub(r"\s+", " ", loc).strip()
    m = re.match(r"^(.*?)\s*(?:[|/,-]|\()\s*([A-Za-z]{2})\)?$", s)
    if m and m.group(2).upper() in _UFS:
        return f"{m.group(1).strip()}, {m.group(2).upper()}"
    return s


def formatar_modelo(modelo: str | None) -> str | None:
    """Remoto / Híbrido / Presencial → "Modelo Remoto"…; vazio → None (linha omitida)."""
    if not modelo or not str(modelo).strip():
        return None
    m = str(modelo).strip()
    return m if _sem_acento(m).startswith("modelo") else f"Modelo {m[0].upper()}{m[1:]}"


def segmento_curto_local(segmento: str) -> str:
    """Fallback sem IA: limpa entidades/pontuação e corta no primeiro separador."""
    s = segmento.replace("&amp;", "&").strip().rstrip(".;")
    if len(s) <= _SEGMENTO_MAX:
        return s
    corte = re.split(r"[,;(/]| - ", s)[0].strip()
    return corte if len(corte) <= _SEGMENTO_MAX else corte[:_SEGMENTO_MAX].rsplit(" ", 1)[0]


def precisa_encurtar(segmento: str) -> bool:
    return len(segmento.replace("&amp;", "&").strip().rstrip(".;")) > _SEGMENTO_MAX
