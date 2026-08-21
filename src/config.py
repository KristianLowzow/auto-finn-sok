"""Innstillinger og hemmeligheter, lest fra miljøvariabler.

Alt som er hemmelig (nøkler, passord) kommer inn som env-variabler --
lokalt via en .env-fil (se .env.example), i GitHub Actions via repo-secrets.
Terskler som brukeren skal kunne justere uten kodeendring ligger i stedet i
Innstillinger-fanen i selve arket (se sheets_client.read_settings_overrides).
"""

import os

from dotenv import load_dotenv

load_dotenv()


def _env(name, default=None, required=False):
    value = os.environ.get(name, default)
    if required and not value:
        raise RuntimeError(f"Mangler påkrevd miljøvariabel: {name}")
    return value


# --- Google Sheets ---
GOOGLE_SERVICE_ACCOUNT_JSON = _env("GOOGLE_SERVICE_ACCOUNT_JSON")
GOOGLE_SERVICE_ACCOUNT_FILE = _env("GOOGLE_SERVICE_ACCOUNT_FILE")
SHEET_ID = _env("SHEET_ID")

# --- E-postvarsling (Gmail SMTP + app-passord) ---
SMTP_HOST = _env("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(_env("SMTP_PORT", "587"))
SMTP_USER = _env("SMTP_USER")
SMTP_APP_PASSWORD = _env("SMTP_APP_PASSWORD")
ALERT_EMAIL_TO = _env("ALERT_EMAIL_TO")

# --- Standardterskler (overstyres av Innstillinger-fanen i arket når den finnes) ---
DEFAULT_GODT_KJOP_TERSKEL = 75
DEFAULT_MIN_COHORT = 5
DEFAULT_REGRESJON_COHORT = 15
DEFAULT_LOOKBACK_DAYS = 90
DEFAULT_GRACE_PERIOD_RUNS = 2

# --- Skraping: unngå å belaste/bli blokkert av Finn.no ---
REQUEST_TIMEOUT_S = 15
MIN_DELAY_S = 2.0
MAX_DELAY_S = 6.0
LONG_PAUSE_EVERY_N_REQUESTS = 20
LONG_PAUSE_MIN_S = 10.0
LONG_PAUSE_MAX_S = 20.0
BACKOFF_SCHEDULE_S = [30, 60, 120]
MAX_SEARCH_PAGES_PER_QUERY = 10  # sikkerhetstak, ~46 annonser/side
MAX_NEW_DETAIL_FETCHES_PER_RUN = 40  # resten tas neste kjøring

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

# --- Faner i Google Sheet ---
TAB_MERKER = "Merker"
TAB_AKTIVE = "Aktive Annonser"
TAB_HISTORIKK = "Historikk"
TAB_STATISTIKK = "Statistikk"
TAB_KJORELOGG = "Kjørelogg"
TAB_INNSTILLINGER = "Innstillinger"
TAB_ENKELTSJEKK = "Sjekk enkeltannonse"
