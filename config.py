"""config.py - the ONE place where settings and secrets are loaded.

Every other file must use:  import config
No other file is allowed to read secrets in its own way.
"""
import os
from pathlib import Path

# ---------- Project folders ----------
PROJECT_DIR = Path(__file__).resolve().parent
CACHE_DIR = PROJECT_DIR / "cache"          # website text cache (no secrets here)

# ---------- Names ----------
SHEET_TITLE = "AI Marketing Agent - Database"
FORM_TITLE = "AI Marketing Agent - Business Signup"

# ---------- Supported options ----------
# Only platforms that really work. Add "LinkedIn" here later.
PLATFORMS = ["Facebook", "Instagram"]
LANGUAGES = ["English", "Urdu", "Roman Urdu"]
STATUSES = ["DRAFT", "APPROVED", "SCHEDULED", "PUBLISHED", "FAILED"]

# Schedule times are entered and checked in this timezone
TIMEZONE = "Asia/Karachi"

# ---------- AI model ----------
GEMINI_MODEL = "gemini-3.8-flash"
# Backup model: used automatically when the main model is busy (503/429) or not found.
# Set to "" to turn the backup off.
GEMINI_FALLBACK_MODEL = "gemini-3.5-flash-lite"
# Allowed for this model: LOW, MEDIUM, HIGH  ("MINIMAL" gives an error)
GEMINI_THINKING_LEVEL = "LOW"

# ---------- Meta Graph API ----------
GRAPH_VERSION = "v23.0"     # change here if Meta retires this version

# ---------- Website reading limits ----------
WEBSITE_MAX_PAGES = 4       # homepage + up to 3 useful public pages
WEBSITE_MAX_CHARS = 6000    # total text kept for the AI
WEBSITE_MIN_CHARS = 300     # below this we say "not enough information"
CACHE_HOURS = 24            # re-read the website after this many hours

# ---------- Secret names ----------
REQUIRED_SECRETS = [
    "GEMINI_API_KEY",
    "FB_PAGE_ACCESS_TOKEN",
    "FB_PAGE_ID",
    "IG_BUSINESS_ACCOUNT_ID",
    "UNSPLASH_ACCESS_KEY",
    "GOOGLE_SERVICE_ACCOUNT_JSON",
]
# Optional: if set, the dashboard asks for a password (username: admin)
OPTIONAL_SECRETS = ["APP_PASSWORD"]


def _read_secret(name):
    """Read one secret: Colab Secrets first, then environment variables."""
    try:
        from google.colab import userdata
        value = userdata.get(name)
        if value and value.strip():
            return value.strip()
    except Exception:
        pass
    return os.environ.get(name, "").strip()


# ---------- Load every secret ONE time ----------
GEMINI_API_KEY = _read_secret("GEMINI_API_KEY")
FB_PAGE_ACCESS_TOKEN = _read_secret("FB_PAGE_ACCESS_TOKEN")
FB_PAGE_ID = _read_secret("FB_PAGE_ID")
IG_BUSINESS_ACCOUNT_ID = _read_secret("IG_BUSINESS_ACCOUNT_ID")
UNSPLASH_ACCESS_KEY = _read_secret("UNSPLASH_ACCESS_KEY")
APP_PASSWORD = _read_secret("APP_PASSWORD")
# Paste the WHOLE service-account JSON key file content as one secret value.
# Used on Railway (and anywhere else outside Colab) to log into Google Sheets
# with no browser popup. Not needed inside Colab - Colab's own login still
# works there automatically as a fallback.
GOOGLE_SERVICE_ACCOUNT_JSON = _read_secret("GOOGLE_SERVICE_ACCOUNT_JSON")


def secret_status():
    """Return {secret name: True/False}. Never returns the values."""
    return {n: bool(globals().get(n)) for n in REQUIRED_SECRETS + OPTIONAL_SECRETS}


def missing_secrets():
    """Return the names of missing REQUIRED secrets."""
    return [n for n in REQUIRED_SECRETS if not globals().get(n)]


def safe_error(text):
    """Remove every secret value from a message before showing or saving it."""
    text = str(text)
    for n in REQUIRED_SECRETS + OPTIONAL_SECRETS:
        value = globals().get(n)
        if value and len(value) > 5:
            text = text.replace(value, "***")
    return text
