import pandas as pd

from src.stats import build_price_vs_km_by_brand


def _active_df():
    return pd.DataFrame(
        [
            {"merke": "Skoda", "modell": "Enyaq", "pris": 400000, "kilometerstand": 50000, "deal_label": "Godt kjøp", "regresjon_avvik_pct": -12.5},
            {"merke": "Skoda", "modell": "Enyaq", "pris": 420000, "kilometerstand": 30000, "deal_label": "Dyrt", "regresjon_avvik_pct": 8.0},
            {"merke": "Volkswagen", "modell": "ID.4", "pris": 380000, "kilometerstand": 60000, "deal_label": "Gjennomsnittlig", "regresjon_avvik_pct": None},
            {"merke": "Volkswagen", "modell": "ID.4 GTX", "pris": 500000, "kilometerstand": 20000, "deal_label": "Godt kjøp", "regresjon_avvik_pct": -5.0},
        ]
    )


def test_build_price_vs_km_by_brand_groups_one_table_per_brand():
    tables = build_price_vs_km_by_brand(_active_df())

    assert set(tables.keys()) == {"Skoda", "Volkswagen"}
    assert len(tables["Skoda"]) == 2
    assert len(tables["Volkswagen"]) == 2


def test_build_price_vs_km_by_brand_pools_models_within_a_brand():
    tables = build_price_vs_km_by_brand(_active_df())

    vw_models = set(tables["Volkswagen"]["Modell"])
    assert vw_models == {"ID.4", "ID.4 GTX"}


def test_build_price_vs_km_by_brand_has_expected_columns():
    tables = build_price_vs_km_by_brand(_active_df())

    assert list(tables["Skoda"].columns) == ["Kilometerstand", "Pris", "Modell", "Vurdering", "Regresjonsavvik %"]


def test_build_price_vs_km_by_brand_empty_input():
    assert build_price_vs_km_by_brand(pd.DataFrame()) == {}


def test_build_price_vs_km_by_brand_drops_rows_missing_price_or_km():
    df = pd.DataFrame(
        [
            {"merke": "Skoda", "modell": "Enyaq", "pris": None, "kilometerstand": 50000, "deal_label": "", "regresjon_avvik_pct": None},
            {"merke": "Skoda", "modell": "Enyaq", "pris": 400000, "kilometerstand": 50000, "deal_label": "", "regresjon_avvik_pct": None},
        ]
    )

    tables = build_price_vs_km_by_brand(df)

    assert len(tables["Skoda"]) == 1
