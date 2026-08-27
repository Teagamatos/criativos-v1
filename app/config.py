"""Configuração central — tudo vem de variáveis de ambiente (ver .env.example)."""
import base64
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# ── ClickUp (só pra anexar o resultado) ───────────────────────
CLICKUP_API_TOKEN = os.getenv("CLICKUP_API_TOKEN", "")

# ── Trigger — POST /generate ───────────────────────────────────
GENERATE_TOKEN = os.getenv("GENERATE_TOKEN", "")

# ── Pexels (busca de fotos) + OpenAI (query de busca e condensação) ──
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
FOTOS_EXCLUIR_ULTIMAS_N = int(os.getenv("FOTOS_EXCLUIR_ULTIMAS_N", "5"))

# ── Notificação de falha (mesmo canal do inbound) ────────────
NOTIFY_WEBHOOK_URL = os.getenv("NOTIFY_WEBHOOK_URL", "")

# ── Render ───────────────────────────────────────────────────
TEMPLATE_PATH = BASE_DIR / "templates" / "template-salesjobs.html"
PALETA_PATH = BASE_DIR / "config" / "paleta-salesjobs.json"
LOGO_SALESJOBS_PATH = BASE_DIR / "templates" / "logo_Salesjobs.svg"  # asset fixo do rodapé (fundo branco)
LOGO_SALESJOBS_URL = "data:image/svg+xml;base64," + base64.b64encode(LOGO_SALESJOBS_PATH.read_bytes()).decode()
LOGO_SALESJOBS_BRANCO_PATH = BASE_DIR / "templates" / "logo_Salesjobs_branco.svg"  # variante branca (fundo colorido)
LOGO_SALESJOBS_BRANCO_URL = "data:image/svg+xml;base64," + base64.b64encode(LOGO_SALESJOBS_BRANCO_PATH.read_bytes()).decode()
RENDER_SCALE = float(os.getenv("RENDER_SCALE", "1"))  # 1 → 1200×1500 (≥ mínimo 1080)
STATE_DB = Path(os.getenv("STATE_DB", BASE_DIR / "state.db"))

PORT = int(os.getenv("PORT", "3001"))
