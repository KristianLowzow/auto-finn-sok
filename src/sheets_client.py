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

_MERKER_HEADER = ["Merke", "Modell", "Min år", "Maks år", "Maks pris (varsel)", "Maks km", "Aktiv", "Notater"]
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
    ["GodtKjopTerskel", str(config.DEFAULT_GODT_KJOP_TERSKEL), "Persentil (0-100) pris/km/rekkevidde må slå for å telle som 'fremragende' og varsles om"],
    ["MinKohort", str(config.DEFAULT_MIN_COHORT), "Minimum sammenligningsbiler før vi gir en vurdering"],
    ["RegresjonKohort", str(config.DEFAULT_REGRESJON_COHORT), "Minimum sammenligningsbiler før vi bruker regresjon i stedet for persentil"],
    ["LookbackDager", str(config.DEFAULT_LOOKBACK_DAYS), "Hvor mange dager bakover som telles med i sammenligningsgrunnlaget"],
    ["StandardMaksPrisVarsel", str(config.DEFAULT_MAKS_PRIS_VARSEL), "Brukes når en Merker-rad ikke har egen 'Maks pris (varsel)'"],
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
    merker = _get_or_create_worksheet(spreadsheet, config.TAB_MERKER, _MERKER_HEADER)
    _migrate_merker_header(merker)
    _get_or_create_worksheet(spreadsheet, config.TAB_AKTIVE, Listing.columns())

    # Historikk og Sjekk enkeltannonse er append-only (ikke skrevet på nytt hver
    # kjøring som Aktive Annonser), så headeren tvinges i synk med Listing-skjemaet
    # hver gang. Trygt fordi disse fanene i praksis ikke har rukket å samle opp
    # data i det gamle kolonneoppsettet ennå.
    historikk = _get_or_create_worksheet(spreadsheet, config.TAB_HISTORIKK, Listing.columns() + _HISTORIKK_EXTRA_COLS)
    historikk.update([Listing.columns() + _HISTORIKK_EXTRA_COLS], "A1")

    enkeltsjekk = _get_or_create_worksheet(spreadsheet, config.TAB_ENKELTSJEKK, _ENKELTSJEKK_HEADER)
    enkeltsjekk.update([_ENKELTSJEKK_HEADER], "A1")

    _get_or_create_worksheet(spreadsheet, config.TAB_KJORELOGG, _KJORELOGG_HEADER)
    _get_or_create_worksheet(spreadsheet, config.TAB_STATISTIKK, ["(fylles automatisk av scriptet)"])

    innstillinger = spreadsheet.worksheet(config.TAB_INNSTILLINGER) if _has_tab(spreadsheet, config.TAB_INNSTILLINGER) else None
    if innstillinger is None:
        innstillinger = spreadsheet.add_worksheet(title=config.TAB_INNSTILLINGER, rows=20, cols=3)
        innstillinger.update(_INNSTILLINGER_DEFAULTS, "A1")
    else:
        _migrate_innstillinger_defaults(innstillinger)


def _has_tab(spreadsheet, title):
    return any(ws.title == title for ws in spreadsheet.worksheets())


def _migrate_innstillinger_defaults(worksheet):
    """Legger til nye standard-nøkler (f.eks. fra en kodeoppdatering) uten å
    røre verdier brukeren allerede har justert."""
    existing_keys = {row.get("Nøkkel") for row in worksheet.get_all_records()}
    missing_rows = [row for row in _INNSTILLINGER_DEFAULTS[1:] if row[0] not in existing_keys]
    if missing_rows:
        worksheet.append_rows(missing_rows, value_input_option="USER_ENTERED")


def _migrate_merker_header(worksheet):
    """Eldre ark kan ha kolonnen "Maks pris" fra før den ble et rent
    varselfilter -- gi den det nye navnet uten å røre dataene i kolonnen."""
    header = worksheet.row_values(1)
    if "Maks pris" in header and "Maks pris (varsel)" not in header:
        col_index = header.index("Maks pris") + 1
        worksheet.update_cell(1, col_index, "Maks pris (varsel)")


def read_settings(spreadsheet):
    """Returnerer aktive rader fra Merker-fanen som liste av dict.

    "Maks pris (varsel)" begrenser IKKE selve Finn-søket -- den brukes bare
    til å avgjøre om en annonse er billig nok til å varsles om (se
    scoring.evaluate_deal). Statistikken skal inneholde hele prisspennet.
    """
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
                    "max_km": row.get("Maks km") or None,
                },
                "alert_max_price": row.get("Maks pris (varsel)") or None,
            }
        )
    return [row for row in active if row["merke"]]


def read_settings_overrides(spreadsheet):
    defaults = {
        "GodtKjopTerskel": config.DEFAULT_GODT_KJOP_TERSKEL,
        "MinKohort": config.DEFAULT_MIN_COHORT,
        "RegresjonKohort": config.DEFAULT_REGRESJON_COHORT,
        "LookbackDager": config.DEFAULT_LOOKBACK_DAYS,
        "StandardMaksPrisVarsel": config.DEFAULT_MAKS_PRIS_VARSEL,
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
    for col in ("pris", "kilometerstand", "rekkevidde_wltp", "aarsmodell", "deal_score"):
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
        for int_field in ("aarsmodell", "kilometerstand", "rekkevidde_wltp", "pris"):
            if cleaned.get(int_field) is not None:
                cleaned[int_field] = int(cleaned[int_field])
        cleaned["varslet"] = str(cleaned.get("varslet")).strip().upper() in ("TRUE", "1")
        cleaned["fremragende_kjop"] = str(cleaned.get("fremragende_kjop")).strip().upper() in ("TRUE", "1")
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


def _col_letter(index):
    """0-indeksert kolonne -> bokstav(er) (0 -> A, 25 -> Z, 26 -> AA, ...)."""
    letters = ""
    index += 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def apply_conditional_formatting(spreadsheet):
    """Fargelegger radene i Aktive Annonser etter Vurdering (grønn/gul/rød) og
    fremhever Fremragende kjøp med gull -- kjøres på nytt hver gang slik at
    fargeleggingen aldri havner i utakt med dataene."""
    worksheet = spreadsheet.worksheet(config.TAB_AKTIVE)
    sheet_id = worksheet.id
    columns = Listing.columns()
    num_cols = len(columns)
    label_letter = _col_letter(columns.index("deal_label"))
    fremragende_letter = _col_letter(columns.index("fremragende_kjop"))

    metadata = spreadsheet.fetch_sheet_metadata()
    existing_rule_count = 0
    for sheet in metadata.get("sheets", []):
        if sheet["properties"]["sheetId"] == sheet_id:
            existing_rule_count = len(sheet.get("conditionalFormats", []))
            break
    delete_requests = [
        {"deleteConditionalFormatRule": {"sheetId": sheet_id, "index": i}}
        for i in range(existing_rule_count - 1, -1, -1)
    ]
    if delete_requests:
        spreadsheet.batch_update({"requests": delete_requests})

    data_range = {
        "sheetId": sheet_id,
        "startRowIndex": 1,
        "endRowIndex": 20000,
        "startColumnIndex": 0,
        "endColumnIndex": num_cols,
    }

    def rule(formula, background, bold=False):
        fmt = {"backgroundColor": background}
        if bold:
            fmt["textFormat"] = {"bold": True}
        return {
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [data_range],
                    "booleanRule": {
                        "condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": formula}]},
                        "format": fmt,
                    },
                },
                "index": 0,
            }
        }

    # Lagt til i omvendt prioritetsrekkefølge (index 0 settes sist -> høyest prioritet)
    add_requests = [
        rule(f'=${label_letter}2="Dyrt"', {"red": 0.98, "green": 0.85, "blue": 0.85}),
        rule(f'=${label_letter}2="Gjennomsnittlig"', {"red": 1.0, "green": 0.97, "blue": 0.80}),
        rule(f'=${label_letter}2="Godt kjøp"', {"red": 0.85, "green": 0.94, "blue": 0.83}),
        rule(f'=${fremragende_letter}2=TRUE', {"red": 1.0, "green": 0.90, "blue": 0.60}, bold=True),
    ]
    spreadsheet.batch_update({"requests": add_requests})


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
