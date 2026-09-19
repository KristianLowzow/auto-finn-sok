"""Bygger Statistikk-fanen (tabeller + diagram) på nytt fra det som allerede
står i Aktive Annonser/Historikk -- uten å skrape Finn.no på nytt.

Nyttig når du har endret hvordan tabellene/diagrammene bygges (f.eks.
kolonneoppsett eller diagram-spesifikasjon) og vil se resultatet med en gang,
uten å vente på/belaste Finn.no med en full skanning.

Eksempel:
    python scripts/refresh_stats.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import main, sheets_client
from src.logging_utils import setup_logging


def run():
    setup_logging()
    spreadsheet = sheets_client.open_sheet()

    active_df = sheets_client.read_active_listings(spreadsheet)
    history_df = sheets_client.read_history(spreadsheet)

    main.refresh_statistics(spreadsheet, active_df, history_df, active_df)
    print(f"Statistikk-fanen oppdatert fra {len(active_df)} aktive annonser og {len(history_df)} historiske rader.")


if __name__ == "__main__":
    run()
