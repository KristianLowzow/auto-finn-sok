"""Kjør pipelinen lokalt mot ett ekte Finn-søk, uten å skrive til Google Sheets
(med mindre --write er satt og GOOGLE_SERVICE_ACCOUNT_* + SHEET_ID er konfigurert).

Bruk til å bekrefte at søk/parsing fungerer før du setter opp arket og
GitHub Actions-cronen.

Eksempel:
    python scripts/local_dry_run.py --brand Toyota --model Corolla
    python scripts/local_dry_run.py --brand Toyota --model Corolla --write
"""

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import scraper
from src.finn_client import FinnClient
from src.logging_utils import setup_logging

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "local_dry_run_output")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--brand", required=True)
    parser.add_argument("--model", default="")
    parser.add_argument("--max-details", type=int, default=5, help="Antall annonser å hente full detalj for (holdes lavt for å ikke belaste Finn)")
    parser.add_argument("--write", action="store_true", help="Skriv faktisk til Google Sheet (krever konfigurerte secrets)")
    args = parser.parse_args()

    setup_logging()
    client = FinnClient()

    print(f"Søker etter: {args.brand} {args.model}")
    results = scraper.search_listings(client, args.brand, args.model, filters={})
    print(f"Fant {len(results)} treff etter filtrering.")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    search_csv = os.path.join(OUTPUT_DIR, "sok_resultater.csv")
    with open(search_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["finn_id", "url", "merke", "modell", "variant", "pris", "bilde"])
        writer.writeheader()
        writer.writerows(results)
    print(f"Skrev søkeresultater til {search_csv}")

    details = []
    for entry in results[: args.max_details]:
        print(f"Henter detaljer for {entry['url']} ...")
        detail = scraper.fetch_detail(client, entry["finn_id"], entry["url"])
        details.append(detail)
        print(f"  {detail['merke']} {detail['modell']} {detail.get('aarsmodell')} "
              f"{detail.get('kilometerstand')} km, {detail['pris']} kr")

    detail_csv = os.path.join(OUTPUT_DIR, "annonse_detaljer.csv")
    if details:
        with open(detail_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(details[0].keys()))
            writer.writeheader()
            writer.writerows(details)
        print(f"Skrev {len(details)} annonsedetaljer til {detail_csv}")

    if args.write:
        print("Skriver til Google Sheet ...")
        from src import main as main_module

        main_module.run()
        print("Ferdig -- sjekk arket og Kjørelogg-fanen.")
    else:
        print("\n(--write ikke satt, ingenting skrevet til Google Sheet)")


if __name__ == "__main__":
    main()
