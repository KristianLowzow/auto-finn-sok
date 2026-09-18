import pandas as pd

from src.models import Listing
from src.scoring import (
    LABEL_DYRT,
    LABEL_GODT_KJOP,
    LABEL_IKKE_NOK_DATA,
    ARLIG_KJORELENGDE_KM,
    LEVETID_AAR,
    LEVETID_KM,
    compute_brand_regression_deviation,
    compute_score,
    drivetrain_category,
    evaluate_deal,
    kr_per_remaining_km,
    remaining_km,
)

REFERENCE_YEAR = 2024


def _cohort(prices, years=None, kms=None, ranges=None, start_id=1):
    n = len(prices)
    years = years or [2019] * n
    kms = kms or [50000] * n
    data = {
        "finn_id": [str(start_id + i) for i in range(n)],
        "pris": prices,
        "aarsmodell": years,
        "kilometerstand": kms,
    }
    if ranges is not None:
        data["rekkevidde_wltp"] = ranges
    return pd.DataFrame(data)


def test_remaining_km_capped_by_age():
    # 17 år gammel, lite kjørt -- alder (18 år) blir flaskehalsen, ikke km
    km = remaining_km(aarsmodell=REFERENCE_YEAR - 17, kilometerstand=10000, reference_year=REFERENCE_YEAR)
    assert km == 1 * ARLIG_KJORELENGDE_KM


def test_remaining_km_capped_by_odometer():
    # Ny bil, men allerede kjørt nesten til grensen -- km blir flaskehalsen
    km = remaining_km(aarsmodell=REFERENCE_YEAR, kilometerstand=LEVETID_KM - 14000, reference_year=REFERENCE_YEAR)
    assert km == 14000


def test_remaining_km_never_negative_past_end_of_life():
    km = remaining_km(aarsmodell=REFERENCE_YEAR - 25, kilometerstand=300000, reference_year=REFERENCE_YEAR)
    assert km == 0


def test_kr_per_remaining_km_divides_price_by_remaining_km():
    value, km_igjen = kr_per_remaining_km(pris=100000, aarsmodell=REFERENCE_YEAR - 10, kilometerstand=100000, reference_year=REFERENCE_YEAR)
    assert km_igjen == (LEVETID_AAR - 10) * ARLIG_KJORELENGDE_KM
    assert value == 100000 / km_igjen


def test_kr_per_remaining_km_none_when_car_is_past_end_of_life():
    value, km_igjen = kr_per_remaining_km(pris=50000, aarsmodell=REFERENCE_YEAR - 25, kilometerstand=300000, reference_year=REFERENCE_YEAR)
    assert km_igjen == 0
    assert value is None


def test_drivetrain_category():
    assert drivetrain_category("Firehjulsdrift") == "4x4"
    assert drivetrain_category("Bakhjulsdrift") == "2-hjulsdrift"
    assert drivetrain_category("Forhjulsdrift") == "2-hjulsdrift"
    assert drivetrain_category("") is None
    assert drivetrain_category(None) is None


def test_too_few_comparables_gives_no_score():
    listing = Listing(finn_id="999", url="u", pris=200000, aarsmodell=2019, kilometerstand=50000)
    cohort = _cohort([190000, 210000])  # kun 2, under standard min på 5

    result = compute_score(listing, cohort, min_cohort=5, reference_year=REFERENCE_YEAR)

    assert result.score is None
    assert result.label == LABEL_IKKE_NOK_DATA
    assert result.cohort_size == 2


def test_percentile_method_ranks_cheap_car_as_good_deal():
    # Alle biler samme år/km, så rangeringen på kr/gjenværende km følger rå pris
    listing = Listing(finn_id="999", url="u", pris=100000, aarsmodell=2019, kilometerstand=50000)
    cohort = _cohort([150000, 160000, 170000, 180000, 190000, 200000], years=[2019] * 6, kms=[50000] * 6)

    result = compute_score(listing, cohort, min_cohort=5, reference_year=REFERENCE_YEAR)

    assert result.method == "restverdi"
    assert result.score == 100.0  # billigst i kohorten
    assert result.label == LABEL_GODT_KJOP


def test_percentile_method_ranks_expensive_car_as_bad_deal():
    listing = Listing(finn_id="999", url="u", pris=300000, aarsmodell=2019, kilometerstand=50000)
    cohort = _cohort([150000, 160000, 170000, 180000, 190000, 200000], years=[2019] * 6, kms=[50000] * 6)

    result = compute_score(listing, cohort, min_cohort=5, reference_year=REFERENCE_YEAR)

    assert result.score == 0.0  # dyrest i kohorten
    assert result.label == LABEL_DYRT


def test_score_rewards_low_mileage_relative_to_cohort_via_remaining_value():
    # Samme pris og år (1 år gammel, godt innenfor aldersgrensen på 18 år) som
    # kohorten, men lavere kilometerstand -- gir mer gjenværende km og dermed
    # lavere (bedre) kr/gjenværende km, selv om selve prisen er identisk.
    listing = Listing(finn_id="999", url="u", pris=200000, aarsmodell=REFERENCE_YEAR - 1, kilometerstand=30000)
    cohort = _cohort(
        [200000] * 6,
        years=[REFERENCE_YEAR - 1] * 6,
        kms=[40000, 50000, 60000, 70000, 80000, 90000],
    )

    result = compute_score(listing, cohort, min_cohort=5, reference_year=REFERENCE_YEAR)

    assert result.score == 100.0
    assert result.label == LABEL_GODT_KJOP


def test_listing_excluded_from_its_own_cohort():
    cohort = _cohort([150000, 160000, 170000, 180000, 190000], start_id=1)
    listing = Listing(finn_id="1", url="u", pris=150000, aarsmodell=2019, kilometerstand=50000)

    result = compute_score(listing, cohort, min_cohort=5, reference_year=REFERENCE_YEAR)

    # kohorten uten seg selv er 4 biler, under min_cohort=5
    assert result.cohort_size == 4
    assert result.label == LABEL_IKKE_NOK_DATA


def test_evaluate_deal_flags_exceptional_petrol_car_on_remaining_value_and_km():
    listing = Listing(finn_id="999", url="u", pris=100000, aarsmodell=2019, kilometerstand=10000, drivstoff="Bensin")
    cohort = _cohort(
        [150000, 160000, 170000, 180000, 190000, 200000],
        years=[2019] * 6,
        kms=[80000, 85000, 90000, 95000, 100000, 105000],
    )

    is_exceptional, km_pct, range_pct = evaluate_deal(listing, cohort, min_cohort=5, exceptional_terskel=80, reference_year=REFERENCE_YEAR)

    assert is_exceptional is True
    assert km_pct == 100.0
    assert range_pct is None  # rekkevidde skal ikke kreves for bensinbil


def test_evaluate_deal_rejects_car_with_average_remaining_value():
    # 1 år gammel (godt innenfor aldersgrensen, så gjenværende km = 260 000 -
    # km for alle), med kr/gjenværende km midt på treet i kohorten -- skal
    # IKKE regnes som fremragende selv om den ikke er dyrest i kroner.
    listing = Listing(finn_id="999", url="u", pris=146250, aarsmodell=REFERENCE_YEAR - 1, kilometerstand=65000, drivstoff="Bensin")
    cohort = _cohort(
        [105000, 120000, 133000, 144000, 153000, 160000],
        years=[REFERENCE_YEAR - 1] * 6,
        kms=[50000, 60000, 70000, 80000, 90000, 100000],
    )

    is_exceptional, km_pct, range_pct = evaluate_deal(listing, cohort, min_cohort=5, exceptional_terskel=80, reference_year=REFERENCE_YEAR)

    assert is_exceptional is False


def test_evaluate_deal_requires_high_range_for_electric_car():
    listing = Listing(finn_id="999", url="u", pris=100000, aarsmodell=2019, kilometerstand=10000, rekkevidde_wltp=300, drivstoff="El")
    cohort = _cohort(
        [150000, 160000, 170000, 180000, 190000, 200000],
        years=[2019] * 6,
        kms=[80000, 85000, 90000, 95000, 100000, 105000],
        ranges=[350, 360, 370, 380, 390, 400],  # alle har lenger rekkevidde enn kandidaten
    )

    is_exceptional, km_pct, range_pct = evaluate_deal(listing, cohort, min_cohort=5, exceptional_terskel=80, reference_year=REFERENCE_YEAR)

    assert is_exceptional is False
    assert range_pct == 0.0  # kortest rekkevidde i kohorten


def test_evaluate_deal_passes_electric_car_with_high_range_too():
    listing = Listing(finn_id="999", url="u", pris=100000, aarsmodell=2019, kilometerstand=10000, rekkevidde_wltp=500, drivstoff="El")
    cohort = _cohort(
        [150000, 160000, 170000, 180000, 190000, 200000],
        years=[2019] * 6,
        kms=[80000, 85000, 90000, 95000, 100000, 105000],
        ranges=[350, 360, 370, 380, 390, 400],
    )

    is_exceptional, km_pct, range_pct = evaluate_deal(listing, cohort, min_cohort=5, exceptional_terskel=80, reference_year=REFERENCE_YEAR)

    assert is_exceptional is True
    assert range_pct == 100.0


def test_evaluate_deal_too_few_comparables_is_never_exceptional():
    listing = Listing(finn_id="999", url="u", pris=50000, aarsmodell=2019, kilometerstand=1000, drivstoff="Bensin")
    cohort = _cohort([150000, 160000])  # kun 2

    is_exceptional, km_pct, range_pct = evaluate_deal(listing, cohort, min_cohort=5, exceptional_terskel=80, reference_year=REFERENCE_YEAR)

    assert is_exceptional is False


def _brand_cohort(n=10, base_price=500000, price_per_km=-2.0, price_per_range_km=300.0):
    # Lager en kohort med en kjent, eksakt lineær sammenheng mellom pris og
    # år/km/rekkevidde, slik at vi vet nøyaktig hva regresjonen bør predikere.
    years = [2021] * n
    kms = [i * 5000 for i in range(n)]
    ranges = [450 + i * 5 for i in range(n)]  # alle over 400
    prices = [base_price + price_per_km * km + price_per_range_km * rng for km, rng in zip(kms, ranges)]
    return pd.DataFrame(
        {
            "finn_id": [str(100 + i) for i in range(n)],
            "merke": ["Skoda"] * n,
            "pris": prices,
            "aarsmodell": years,
            "kilometerstand": kms,
            "rekkevidde_wltp": ranges,
        }
    )


def test_brand_regression_flags_car_priced_far_below_the_line():
    cohort = _brand_cohort()
    # Samme år/km/rekkevidde-nivå som midt i kohorten, men mye billigere
    listing = Listing(finn_id="999", url="u", merke="Skoda", drivstoff="El", pris=300000, aarsmodell=2021, kilometerstand=25000, rekkevidde_wltp=475)

    deviation_pct, n = compute_brand_regression_deviation(listing, cohort, min_cohort=5, min_rekkevidde=400)

    assert n == 10
    assert deviation_pct < -20  # godt under regresjonslinja


def test_brand_regression_flags_car_priced_far_above_the_line():
    cohort = _brand_cohort()
    listing = Listing(finn_id="999", url="u", merke="Skoda", drivstoff="El", pris=900000, aarsmodell=2021, kilometerstand=25000, rekkevidde_wltp=475)

    deviation_pct, n = compute_brand_regression_deviation(listing, cohort, min_cohort=5, min_rekkevidde=400)

    assert deviation_pct > 20


def test_brand_regression_excludes_cars_below_range_threshold():
    cohort = _brand_cohort()
    listing = Listing(finn_id="999", url="u", merke="Skoda", drivstoff="El", pris=300000, aarsmodell=2021, kilometerstand=25000, rekkevidde_wltp=350)

    deviation_pct, n = compute_brand_regression_deviation(listing, cohort, min_cohort=5, min_rekkevidde=400)

    assert deviation_pct is None


def test_brand_regression_skips_non_electric_cars():
    cohort = _brand_cohort()
    listing = Listing(finn_id="999", url="u", merke="Skoda", drivstoff="Bensin", pris=300000, aarsmodell=2021, kilometerstand=25000, rekkevidde_wltp=475)

    deviation_pct, n = compute_brand_regression_deviation(listing, cohort, min_cohort=5, min_rekkevidde=400)

    assert deviation_pct is None


def test_brand_regression_pools_across_models_within_the_brand():
    # To "modeller" av samme merke i samme kohort -- funksjonen bryr seg kun
    # om merke, ikke modell, siden rekkevidde skal forklare prisforskjellen.
    cohort = _brand_cohort()
    cohort["modell"] = ["Enyaq"] * 5 + ["Enyaq Coupe"] * 5
    listing = Listing(finn_id="999", url="u", merke="Skoda", modell="Enyaq Coupe", drivstoff="El", pris=300000, aarsmodell=2021, kilometerstand=25000, rekkevidde_wltp=475)

    deviation_pct, n = compute_brand_regression_deviation(listing, cohort, min_cohort=5, min_rekkevidde=400)

    assert n == 10  # begge modellene telles med
