"""Engangs-diagnostikk: sammenligner hva Finn.no faktisk har akkurat nå (kun
søkeresultater, ingen detaljhenting) mot hva som allerede står i Aktive
Annonser/Historikk, per merke/modell. Hjelper med å se om "mangler" skyldes
40-per-kjøring-taket (køes opp, løses over tid) eller noe annet (f.eks.
annonser som konsekvent feiler pga SchemaDriftError).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import scraper, sheets_client
from src.finn_client import FinnClient
from src.logging_utils import setup_logging
from src.parsers import SchemaDriftError


def main():
    setup_logging()
    spreadsheet = sheets_client.open_sheet()

    settings = sheets_client.read_settings(spreadsheet)
    active_df = sheets_client.read_active_listings(spreadsheet)
    history_df = sheets_client.read_history(spreadsheet)

    active_ids = set(active_df["finn_id"]) if not active_df.empty else set()
    history_ids = set(history_df["finn_id"]) if not history_df.empty else set()

    client = FinnClient()

    for setting in settings:
        merke, modell, filters = setting["merke"], setting["modell"], setting["filters"]
        print(f"\n=== {merke} {modell} (filtre: {filters}) ===")
        try:
            results = scraper.search_listings(client, merke, modell, filters)
        except SchemaDriftError as exc:
            print(f"  SØK FEILET: {exc}")
            continue

        finn_ids_now = {r["finn_id"] for r in results}
        already_active = finn_ids_now & active_ids
        already_in_history = finn_ids_now & history_ids
        missing = finn_ids_now - active_ids - history_ids

        print(f"  Finn.no akkurat nå: {len(finn_ids_now)} treff")
        print(f"  Allerede i Aktive Annonser: {len(already_active)}")
        print(f"  Allerede i Historikk (tidligere fjernet): {len(already_in_history)}")
        print(f"  MANGLER helt (verken aktive eller historikk): {len(missing)}")
        if missing:
            sample = list(missing)[:5]
            print(f"  Eksempel-URL-er som mangler: {sample}")
            for finn_id in sample:
                entry = next(r for r in results if r["finn_id"] == finn_id)
                try:
                    scraper.fetch_detail(client, finn_id, entry["url"])
                    print(f"    {finn_id}: hentet OK ved test (skulle vært plukket opp neste kjøring)")
                except SchemaDriftError as exc:
                    print(f"    {finn_id}: FEILER VEDVARENDE -- {exc}")


if __name__ == "__main__":
    main()
