"""Engangsverktøy: tømmer "Aktive Annonser" og "Historikk" (beholder
headerraden) slik at neste periodiske skann behandler alle annonser som nye
og henter fulle detaljer på nytt for hver av dem.

Brukes typisk rett etter en kodeendring som legger til nye felt på
Listing (f.eks. batteristørrelse/utstyr), slik at gamle rader som mangler de
nye kolonnene ikke blir liggende igjen.

Kjøres via GitHub Actions-workflowen "Tøm Aktive Annonser og Historikk"
(workflow_dispatch), som gjenbruker de samme secrets som periodisk skann.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import sheets_client
from src.logging_utils import setup_logging
from src.models import Listing


def main():
    setup_logging()
    spreadsheet = sheets_client.open_sheet()
    sheets_client.ensure_tabs(spreadsheet)

    aktive = spreadsheet.worksheet(sheets_client.config.TAB_AKTIVE)
    aktive.clear()
    aktive.update([Listing.columns()], "A1")
    print(f"Tømte '{sheets_client.config.TAB_AKTIVE}' (header beholdt).")

    historikk_header = Listing.columns() + sheets_client._HISTORIKK_EXTRA_COLS
    historikk = spreadsheet.worksheet(sheets_client.config.TAB_HISTORIKK)
    historikk.clear()
    historikk.update([historikk_header], "A1")
    print(f"Tømte '{sheets_client.config.TAB_HISTORIKK}' (header beholdt).")


if __name__ == "__main__":
    main()
