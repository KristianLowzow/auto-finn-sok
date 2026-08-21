import pandas as pd

from src.models import Listing
from src.scoring import LABEL_DYRT, LABEL_GODT_KJOP, LABEL_IKKE_NOK_DATA, compute_score


def _cohort(prices, years=None, kms=None, start_id=1):
    n = len(prices)
    years = years or [2019] * n
    kms = kms or [50000] * n
    return pd.DataFrame(
        {
            "finn_id": [str(start_id + i) for i in range(n)],
            "pris": prices,
            "aarsmodell": years,
            "kilometerstand": kms,
        }
    )


def test_too_few_comparables_gives_no_score():
    listing = Listing(finn_id="999", url="u", pris=200000, aarsmodell=2019, kilometerstand=50000)
    cohort = _cohort([190000, 210000])  # kun 2, under standard min på 5

    result = compute_score(listing, cohort, min_cohort=5, regression_cohort=15)

    assert result.score is None
    assert result.label == LABEL_IKKE_NOK_DATA
    assert result.cohort_size == 2


def test_percentile_method_ranks_cheap_car_as_good_deal():
    listing = Listing(finn_id="999", url="u", pris=100000, aarsmodell=2019, kilometerstand=50000)
    cohort = _cohort([150000, 160000, 170000, 180000, 190000, 200000])  # 6 biler, under regresjonsgrense

    result = compute_score(listing, cohort, min_cohort=5, regression_cohort=15)

    assert result.method == "persentil"
    assert result.score == 100.0  # billigst i kohorten
    assert result.label == LABEL_GODT_KJOP


def test_percentile_method_ranks_expensive_car_as_bad_deal():
    listing = Listing(finn_id="999", url="u", pris=300000, aarsmodell=2019, kilometerstand=50000)
    cohort = _cohort([150000, 160000, 170000, 180000, 190000, 200000])

    result = compute_score(listing, cohort, min_cohort=5, regression_cohort=15)

    assert result.score == 0.0  # dyrest i kohorten
    assert result.label == LABEL_DYRT


def test_regression_method_rewards_low_mileage_relative_to_year():
    # 20 biler: pris synker jevnt med kilometerstand for samme år
    prices = [300000 - 2 * km for km in range(0, 20000, 1000)]
    kms = list(range(0, 20000, 1000))
    cohort = _cohort(prices, years=[2020] * 20, kms=kms)

    # denne bilen er mye billigere enn det km-nivået skulle tilsi
    cheap_listing = Listing(finn_id="999", url="u", pris=200000, aarsmodell=2020, kilometerstand=10000)
    result = compute_score(cheap_listing, cohort, min_cohort=5, regression_cohort=15)

    assert result.method == "regresjon"
    assert result.score > 50


def test_listing_excluded_from_its_own_cohort():
    cohort = _cohort([150000, 160000, 170000, 180000, 190000], start_id=1)
    listing = Listing(finn_id="1", url="u", pris=150000, aarsmodell=2019, kilometerstand=50000)

    result = compute_score(listing, cohort, min_cohort=5, regression_cohort=15)

    # kohorten uten seg selv er 4 biler, under min_cohort=5
    assert result.cohort_size == 4
    assert result.label == LABEL_IKKE_NOK_DATA
