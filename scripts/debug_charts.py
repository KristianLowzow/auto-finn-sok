"""Engangs-feilsøkingsscript: gjenskaper stat_tables/chart_specs fra det som
allerede står i Aktive Annonser/Historikk (uten å skrape Finn.no på nytt), og
skriver ut selve JSON-forespørselen til addChart hvis den feiler -- brukt til
å diagnostisere "ChartData.sourceRange must be set"-feilen i apply_bubble_charts.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import sheets_client, stats
from src.logging_utils import setup_logging
from src.models import Listing


def main():
    setup_logging()
    spreadsheet = sheets_client.open_sheet()

    active_df = sheets_client.read_active_listings(spreadsheet)
    history_df = sheets_client.read_history(spreadsheet)
    print(f"Aktive Annonser: {len(active_df)} rader, Historikk: {len(history_df)} rader")

    stat_tables = {
        "Škoda Enyaq vs. VW ID.4 (per hjuldrift)": stats.build_model_drivetrain_comparison(
            active_df, [("Skoda", "Enyaq"), ("Volkswagen", "ID.4")]
        ),
    }

    chart_specs = []
    for brand, brand_df in stats.build_price_vs_km_by_brand(active_df).items():
        title = f"Pris vs. km — {brand}"
        stat_tables[title] = brand_df
        print(f"Merke-tabell {title!r}: {len(brand_df)} rader, kolonner={list(brand_df.columns)}")
        chart_specs.append(
            {"table_title": title, "chart_title": f"Pris vs. kilometerstand — {brand}", "group_col": "Batteristørrelse"}
        )

    drivetrain_titles = {"4x4": "Pris vs. km — 4x4 (alle merker)", "2-hjulsdrift": "Pris vs. km — 2-hjulsdrift (alle merker)"}
    for category, drivetrain_df in stats.build_price_vs_km_by_drivetrain(active_df).items():
        title = drivetrain_titles[category]
        stat_tables[title] = drivetrain_df
        print(f"Hjuldrift-tabell {title!r}: {len(drivetrain_df)} rader, kolonner={list(drivetrain_df.columns)}")
        chart_specs.append(
            {
                "table_title": title,
                "chart_title": f"Pris vs. kilometerstand — {category} (alle merker)",
                "group_col": "Merke",
                "size_col": "Batteri kWh",
            }
        )

    layout = sheets_client.write_stats_tables(spreadsheet, stat_tables)
    print("\nLayout:")
    for title, info in layout.items():
        print(f"  {title!r}: {info}")

    print(f"\n{len(chart_specs)} chart_specs:")
    for spec in chart_specs:
        print(f"  {spec}")

    try:
        sheets_client.apply_bubble_charts(spreadsheet, layout, chart_specs)
        print("\napply_bubble_charts OK")
    except Exception:
        print("\napply_bubble_charts FEILET -- se traceback + request-dump under")
        raise


if __name__ == "__main__":
    main()
