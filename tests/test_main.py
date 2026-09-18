import pandas as pd

from src.main import _score_all
from src.models import Listing

NOW = "2026-08-21T21:00:00+00:00"
OVERRIDES = {"GodtKjopTerskel": 80, "MinKohort": 5, "LookbackDager": 90, "MinRekkevidde": 400}


def _electric_listing(finn_id, pris, km, rekkevidde):
    return Listing(
        finn_id=finn_id, url=f"u{finn_id}", merke="Volkswagen", modell="ID.4 GTX", drivstoff="El",
        pris=pris, kilometerstand=km, rekkevidde_wltp=rekkevidde, aarsmodell=2022,
        forste_gang_sett=NOW, sist_sett=NOW,
    )


def test_score_all_handles_mixed_missing_range_without_crashing():
    # Regresjonstest: noen Finn-annonser mangler Rekkevidde-feltet selv om de
    # er elbiler (se tests/fixtures/ad_page_sample.html), som ga en blandet
    # int/tom-streng-kolonne og krasjet _percentile_score i produksjon.
    listings = [
        _electric_listing("1", 400000, 80000, 350),
        _electric_listing("2", 405000, 82000, None),  # mangler rekkevidde
        _electric_listing("3", 410000, 84000, 360),
        _electric_listing("4", 415000, 86000, None),  # mangler rekkevidde
        _electric_listing("5", 420000, 88000, 370),
        _electric_listing("6", 300000, 40000, 420),  # skal peke seg ut som fremragende
    ]
    history_df = pd.DataFrame(columns=Listing.columns() + ["siste_kjente_pris", "fjernet_dato", "status", "dager_til_fjernet"])

    scored = _score_all(listings, history_df, OVERRIDES, NOW)

    by_id = {listing.finn_id: (listing, result, km_pct, range_pct) for listing, result, km_pct, range_pct in scored}
    assert by_id["6"][0].fremragende_kjop is True
    assert by_id["2"][0].deal_score is not None  # fikk likevel en vurdering
    assert by_id["1"][0].kr_per_gjenvaerende_km is not None
    assert by_id["1"][0].gjenvaerende_km is not None
