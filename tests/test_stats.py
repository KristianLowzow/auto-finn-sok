import pandas as pd

from src.stats import (
    build_model_drivetrain_comparison,
    build_price_vs_km_by_brand,
    build_price_vs_km_by_drivetrain,
)


def _active_df():
    return pd.DataFrame(
        [
            {
                "merke": "Skoda", "modell": "Enyaq", "pris": 400000, "kilometerstand": 50000,
                "deal_label": "Godt kjøp", "regresjon_avvik_pct": -12.5, "batteri_kapasitet_kwh": 77.0,
                "hjuldrift": "Bakhjulsdrift", "aarsmodell": 2021, "kr_per_gjenvaerende_km": 5.0,
            },
            {
                "merke": "Skoda", "modell": "Enyaq", "pris": 420000, "kilometerstand": 30000,
                "deal_label": "Dyrt", "regresjon_avvik_pct": 8.0, "batteri_kapasitet_kwh": 82.0,
                "hjuldrift": "Firehjulsdrift", "aarsmodell": 2022, "kr_per_gjenvaerende_km": 6.0,
            },
            {
                "merke": "Volkswagen", "modell": "ID.4", "pris": 380000, "kilometerstand": 60000,
                "deal_label": "Gjennomsnittlig", "regresjon_avvik_pct": None, "batteri_kapasitet_kwh": None,
                "hjuldrift": "Forhjulsdrift", "aarsmodell": 2021, "kr_per_gjenvaerende_km": 4.5,
            },
            {
                "merke": "Volkswagen", "modell": "ID.4 GTX", "pris": 500000, "kilometerstand": 20000,
                "deal_label": "Godt kjøp", "regresjon_avvik_pct": -5.0, "batteri_kapasitet_kwh": 77.0,
                "hjuldrift": "Firehjulsdrift", "aarsmodell": 2023, "kr_per_gjenvaerende_km": 5.5,
            },
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

    assert list(tables["Skoda"].columns) == [
        "Kilometerstand", "Pris", "Modell", "Vurdering", "Regresjonsavvik %", "Batteristørrelse",
    ]


def test_build_price_vs_km_by_brand_labels_battery_size_and_unknown():
    tables = build_price_vs_km_by_brand(_active_df())

    skoda_sizes = set(tables["Skoda"]["Batteristørrelse"])
    assert skoda_sizes == {"77 kWh", "82 kWh"}
    vw_sizes = set(tables["Volkswagen"]["Batteristørrelse"])
    assert "Ukjent" in vw_sizes  # ID.4 uten kjent batteristørrelse


def test_build_price_vs_km_by_brand_empty_input():
    assert build_price_vs_km_by_brand(pd.DataFrame()) == {}


def test_build_price_vs_km_by_brand_drops_rows_missing_price_or_km():
    df = pd.DataFrame(
        [
            {"merke": "Skoda", "modell": "Enyaq", "pris": None, "kilometerstand": 50000, "deal_label": "", "regresjon_avvik_pct": None, "batteri_kapasitet_kwh": None},
            {"merke": "Skoda", "modell": "Enyaq", "pris": 400000, "kilometerstand": 50000, "deal_label": "", "regresjon_avvik_pct": None, "batteri_kapasitet_kwh": None},
        ]
    )

    tables = build_price_vs_km_by_brand(df)

    assert len(tables["Skoda"]) == 1


def test_build_price_vs_km_by_drivetrain_splits_4x4_and_2wd_across_brands():
    tables = build_price_vs_km_by_drivetrain(_active_df())

    assert set(tables.keys()) == {"4x4", "2-hjulsdrift"}
    assert set(tables["4x4"]["Merke"]) == {"Skoda", "Volkswagen"}
    assert set(tables["2-hjulsdrift"]["Merke"]) == {"Skoda", "Volkswagen"}
    assert list(tables["4x4"].columns) == ["Kilometerstand", "Pris", "Merke", "Modell", "Batteri kWh"]


def test_build_price_vs_km_by_drivetrain_empty_input():
    assert build_price_vs_km_by_drivetrain(pd.DataFrame()) == {}


def test_build_model_drivetrain_comparison_splits_by_drivetrain():
    table = build_model_drivetrain_comparison(_active_df(), [("Skoda", "Enyaq"), ("Volkswagen", "ID.4")])

    # ID.4 GTX matcher "ID.4" som delstreng og skal telles med sammen med ID.4
    assert set(table["Merke"]) == {"Skoda", "Volkswagen"}
    assert set(table["Hjuldrift"]) <= {"4x4", "2-hjulsdrift"}
    vw_4x4 = table[(table["Merke"] == "Volkswagen") & (table["Hjuldrift"] == "4x4")]
    assert vw_4x4["Antall"].iloc[0] == 1  # kun ID.4 GTX er 4x4


def test_build_model_drivetrain_comparison_empty_input():
    result = build_model_drivetrain_comparison(pd.DataFrame(), [("Skoda", "Enyaq")])
    assert result.empty
