"""All lesing og skriving mot Google Sheets, batchet for å holde seg innenfor
Sheets API-kvoter (ingen per-rad/per-celle-kall)."""

import json
import logging

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

from src import config
from src.models import Listing

logger = logging.getLogger(__name__)

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

_HISTORIKK_EXTRA_COLS = ["siste_kjente_pris", "fjernet_dato", "status", "dager_til_fjernet"]

_MERKER_HEADER = ["Merke", "Modell", "Min år", "Maks år", "Maks pris", "Maks km", "Aktiv", "Notater"]
_KJORELOGG_HEADER = [
    "Tidspunkt",
    "Varighet (s)",
    "Merker skannet",
    "Nye",
    "Oppdaterte",
    "Fjernet",
    "Feil (antall)",
    "Feilmelding",
    "Status",
]
_INNSTILLINGER_DEFAULTS = [
    ["Nøkkel", "Verdi", "Forklaring"],
    ["GodtKjopTerskel", str(config.DEFAULT_GODT_KJOP_TERSKEL), "Score (0-100) som utløser e-postvarsel"],
    ["MinKohort", str(config.DEFAULT_MIN_COHORT), "Minimum sammenligningsbiler før vi gir en vurdering"],
    ["RegresjonKohort", str(config.DEFAULT_REGRESJON_COHORT), "Minimum sammenligningsbiler før vi bruker regresjon i stedet for persentil"],
    ["LookbackDager", str(config.DEFAULT_LOOKBACK_DAYS), "Hvor mange dager bakover som telles med i sammenligningsgrunnlaget"],
]
_ENKELTSJEKK_HEADER = ["Tidspunkt", "URL"] + Listing.columns()


def get_client():
    if config.GOOGLE_SERVICE_ACCOUNT_JSON:
        info = json.loads(config.GOOGLE_SERVICE_ACCOUNT_JSON)
        creds = Credentials.from_service_account_info(info, scopes=_SCOPES)
    elif config.GOOGLE_SERVICE_ACCOUNT_FILE:
        creds = Credentials.from_service_account_file(config.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=_SCOPES)
    else:
        raise RuntimeError("Verken GOOGLE_SERVICE_ACCOUNT_JSON eller GOOGLE_SERVICE_ACCOUNT_FILE er satt")
    return gspread.authorize(creds)


def open_sheet(client=None):
    client = client or get_client()
    if not config.SHEET_ID:
        raise RuntimeError("SHEET_ID er ikke satt")
    return client.open_by_key(config.SHEET_ID)


def _get_or_create_worksheet(spreadsheet, title, header, rows=1000, cols=26):
    try:
        worksheet = spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=title, rows=rows, cols=max(cols, len(header)))
        worksheet.update([header], "A1")
        return worksheet
    if not worksheet.row_values(1):
        worksheet.update([header], "A1")
    return worksheet


def ensure_tabs(spreadsheet):
    """Oppretter faner med riktig header hvis de ikke finnes fra før. Trygt å kjøre flere ganger."""
    _get_or_create_worksheet(spreadsheet, config.TAB_MERKER, _MERKER_HEADER)
    _get_or_create_worksheet(spreadsheet, config.TAB_AKTIVE, Listing.columns())
    _get_or_create_worksheet(spreadsheet, config.TAB_HISTORIKK, Listing.columns() + _HISTORIKK_EXTRA_COLS)
    _get_or_create_worksheet(spreadsheet, config.TAB_KJORELOGG, _KJORELOGG_HEADER)
    _get_or_create_worksheet(spreadsheet, config.TAB_ENKELTSJEKK, _ENKELTSJEKK_HEADER)
    _get_or_create_worksheet(spreadsheet, config.TAB_STATISTIKK, ["(fylles automatisk av scriptet)"])

    innstillinger = spreadsheet.worksheet(config.TAB_INNSTILLINGER) if _has_tab(spreadsheet, config.TAB_INNSTILLINGER) else None
    if innstillinger is None:
        innstillinger = spreadsheet.add_worksheet(title=config.TAB_INNSTILLINGER, rows=20, cols=3)
        innstillinger.update(_INNSTILLINGER_DEFAULTS, "A1")


def _has_tab(spreadsheet, title):
    return any(ws.title == title for ws in spreadsheet.worksheets())


def read_settings(spreadsheet):
    """Returnerer aktive rader fra Merker-fanen som liste av dict."""
    worksheet = spreadsheet.worksheet(config.TAB_MERKER)
    records = worksheet.get_all_records()
    active = []
    for row in records:
        if str(row.get("Aktiv", "")).strip().upper() not in ("TRUE", "1", "JA", "YES"):
            continue
        active.append(
            {
                "merke": str(row.get("Merke", "")).strip(),
                "modell": str(row.get("Modell", "")).strip(),
                "filters": {
                    "min_year": row.get("Min år") or None,
                    "max_year": row.get("Maks år") or None,
                    "max_price": row.get("Maks pris") or None,
                    "max_km": row.get("Maks km") or None,
                },
            }
        )
    return [row for row in active if row["merke"]]


def read_settings_overrides(spreadsheet):
    defaults = {
        "GodtKjopTerskel": config.DEFAULT_GODT_KJOP_TERSKEL,
        "MinKohort": config.DEFAULT_MIN_COHORT,
        "RegresjonKohort": config.DEFAULT_REGRESJON_COHORT,
        "LookbackDager": config.DEFAULT_LOOKBACK_DAYS,
    }
    if not _has_tab(spreadsheet, config.TAB_INNSTILLINGER):
        return defaults
    worksheet = spreadsheet.worksheet(config.TAB_INNSTILLINGER)
    for row in worksheet.get_all_records():
        key = row.get("Nøkkel")
        if key in defaults and row.get("Verdi") not in (None, ""):
            try:
                defaults[key] = float(row["Verdi"])
            except (TypeError, ValueError):
                pass
    return defaults


def _worksheet_to_df(worksheet, columns):
    values = worksheet.get_all_values()
    if len(values) <= 1:
        return pd.DataFrame(columns=columns)
    header, rows = values[0], values[1:]
    df = pd.DataFrame(rows, columns=header)
    for col in ("pris", "kilometerstand", "aarsmodell", "deal_score"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def read_active_listings(spreadsheet):
    worksheet = spreadsheet.worksheet(config.TAB_AKTIVE)
    return _worksheet_to_df(worksheet, Listing.columns())


def listings_from_df(df):
    """Konverterer en DataFrame (fra read_active_listings) tilbake til Listing-objekter."""
    listings = []
    for record in df.to_dict("records"):
        cleaned = {}
        for key, value in record.items():
            if key not in Listing.columns():
                continue
            if value == "" or (isinstance(value, float) and pd.isna(value)):
                cleaned[key] = None
            else:
                cleaned[key] = value
        for int_field in ("aarsmodell", "kilometerstand", "pris"):
            if cleaned.get(int_field) is not None:
                cleaned[int_field] = int(cleaned[int_field])
        cleaned["varslet"] = str(cleaned.get("varslet")).strip().upper() in ("TRUE", "1")
        cleaned.setdefault("finn_id", "")
        cleaned.setdefault("url", "")
        listings.append(Listing(**cleaned))
    return listings


def read_history(spreadsheet):
    worksheet = spreadsheet.worksheet(config.TAB_HISTORIKK)
    return _worksheet_to_df(worksheet, Listing.columns() + _HISTORIKK_EXTRA_COLS)


def write_active_listings(spreadsheet, listings):
    """Overskriver hele Aktive Annonser-fanen med gjeldende liste av Listing."""
    worksheet = spreadsheet.worksheet(config.TAB_AKTIVE)
    header = Listing.columns()
    rows = [listing.to_row() for listing in listings]
    worksheet.clear()
    worksheet.update([header] + rows, "A1")


def append_history_rows(spreadsheet, rows):
    if not rows:
        return
    worksheet = spreadsheet.worksheet(config.TAB_HISTORIKK)
    worksheet.append_rows(rows, value_input_option="USER_ENTERED")


def append_run_log(spreadsheet, row):
    worksheet = spreadsheet.worksheet(config.TAB_KJORELOGG)
    worksheet.append_row(row, value_input_option="USER_ENTERED")


def append_enkeltsjekk(spreadsheet, row):
    worksheet = spreadsheet.worksheet(config.TAB_ENKELTSJEKK)
    worksheet.append_row(row, value_input_option="USER_ENTERED")


def write_stats_tables(spreadsheet, tables):
    """tables: dict[navn -> DataFrame]. Skriver hver tabell under en overskrift,
    stablet vertikalt i Statistikk-fanen, med to tomme rader mellom hver."""
    worksheet = spreadsheet.worksheet(config.TAB_STATISTIKK)
    worksheet.clear()

    all_rows = []
    for title, df in tables.items():
        all_rows.append([title])
        if df.empty:
            all_rows.append(["(ingen data ennå)"])
        else:
            all_rows.append(list(df.columns))
            all_rows.extend(df.astype(object).where(pd.notna(df), "").values.tolist())
        all_rows.append([])
        all_rows.append([])

    if all_rows:
        worksheet.update(all_rows, "A1")
