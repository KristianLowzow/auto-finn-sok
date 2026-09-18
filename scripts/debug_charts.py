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

    # Bygg addChart-requestene manuelt (samme logikk som apply_bubble_charts)
    # og send dem ETT ADT GANGEN, slik at vi ser nøyaktig hvilken spec som
    # feiler og får hele rå feilteksten fra Google (ikke bare gspreads
    # forkortede APIError-melding).
    worksheet = spreadsheet.worksheet(sheets_client.config.TAB_STATISTIKK)
    sheet_id = worksheet.id

    def col_range(info, columns, col_name):
        idx = columns.index(col_name)
        return {
            "sheetId": sheet_id,
            "startRowIndex": info["data_start_row"],
            "endRowIndex": info["data_end_row"] + 1,
            "startColumnIndex": idx,
            "endColumnIndex": idx + 1,
        }

    # Minimal-eksperiment: prøv tre stadig rikere varianter av EN request for å
    # isolere om domain+series alene fungerer, og hvilket ekstra felt som
    # eventuelt utløser "ChartData.sourceRange must be set".
    skoda_info = layout["Pris vs. km — Skoda"]
    skoda_cols = skoda_info["columns"]

    def skoda_col_range(col_name):
        idx = skoda_cols.index(col_name)
        return {
            "sheetId": sheet_id,
            "startRowIndex": skoda_info["data_start_row"],
            "endRowIndex": skoda_info["data_end_row"] + 1,
            "startColumnIndex": idx,
            "endColumnIndex": idx + 1,
        }

    variants = {
        "domain+series": {
            "domain": {"sourceRange": {"sources": [skoda_col_range("Kilometerstand")]}},
            "series": {"sourceRange": {"sources": [skoda_col_range("Pris")]}},
        },
        "domain+series+legend": {
            "domain": {"sourceRange": {"sources": [skoda_col_range("Kilometerstand")]}},
            "series": {"sourceRange": {"sources": [skoda_col_range("Pris")]}},
            "legendPosition": "RIGHT_LEGEND",
        },
        "domain+series+groupIds": {
            "domain": {"sourceRange": {"sources": [skoda_col_range("Kilometerstand")]}},
            "series": {"sourceRange": {"sources": [skoda_col_range("Pris")]}},
            "groupIds": {"sourceRange": {"sources": [skoda_col_range("Batteristørrelse")]}},
        },
    }
    for i, (name, bubble_chart_variant) in enumerate(variants.items()):
        request = {
            "addChart": {
                "chart": {
                    "spec": {"title": f"DEBUG {name}", "bubbleChart": bubble_chart_variant},
                    "position": {
                        "overlayPosition": {
                            "anchorCell": {"sheetId": sheet_id, "rowIndex": 400 + i * 22, "columnIndex": 12},
                            "widthPixels": 600,
                            "heightPixels": 371,
                        }
                    },
                }
            }
        }
        print(f"\n=== Variant {name!r} ===")
        print(json.dumps(request, ensure_ascii=False))
        try:
            spreadsheet.batch_update({"requests": [request]})
            print("OK")
        except Exception as exc:
            print(f"FEILET: {exc}")
            response = getattr(exc, "response", None)
            if response is not None:
                print(f"RAW RESPONSE BODY: {response.text}")

    print("\n\n### Nå de fulle chart_specs ###")
    for i, spec in enumerate(chart_specs):
        info = layout[spec["table_title"]]
        columns = info["columns"]
        bubble_chart = {
            "domain": {"sourceRange": {"sources": [col_range(info, columns, "Kilometerstand")]}},
            "series": {"sourceRange": {"sources": [col_range(info, columns, "Pris")]}},
            "legendPosition": "RIGHT_LEGEND",
        }
        if spec.get("group_col"):
            bubble_chart["groupIds"] = {"sourceRange": {"sources": [col_range(info, columns, spec["group_col"])]}}
        if spec.get("size_col"):
            bubble_chart["bubbleSizes"] = {"sourceRange": {"sources": [col_range(info, columns, spec["size_col"])]}}

        request = {
            "addChart": {
                "chart": {
                    "spec": {"title": spec["chart_title"], "bubbleChart": bubble_chart},
                    "position": {
                        "overlayPosition": {
                            "anchorCell": {"sheetId": sheet_id, "rowIndex": i * 22, "columnIndex": 12},
                            "widthPixels": 600,
                            "heightPixels": 371,
                        }
                    },
                }
            }
        }
        print(f"\n--- Spec {i}: {spec['table_title']!r} ---")
        print(json.dumps(request, ensure_ascii=False))
        try:
            spreadsheet.batch_update({"requests": [request]})
            print("OK")
        except Exception as exc:
            print(f"FEILET: {exc}")
            response = getattr(exc, "response", None)
            if response is not None:
                print(f"RAW RESPONSE BODY: {response.text}")


if __name__ == "__main__":
    main()
