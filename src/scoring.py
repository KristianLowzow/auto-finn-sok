"""Beregner om en annonse er et godt eller dårlig kjøp.

Sammenligningsgrunnlaget (kohorten) er andre annonser av samme merke+modell.
Metoden blir mer presis etter hvert som mer data samles opp:

  - For få sammenligningsbiler: ingen vurdering ("Ikke nok data").
  - Middels mange: prisen rangeres som persentil i kohorten (robust, men
    tar ikke hensyn til år/kilometerstand).
  - Mange nok: pris forklares med en enkel lineær modell på år og
    kilometerstand, og avviket fra forventet pris gir scoren.

Score er alltid 0-100, der høyere er et bedre kjøp (billigere enn ventet).
"""

import numpy as np

from src.models import ScoreResult

LABEL_GODT_KJOP = "Godt kjøp"
LABEL_GJENNOMSNITTLIG = "Gjennomsnittlig"
LABEL_DYRT = "Dyrt"
LABEL_IKKE_NOK_DATA = "Ikke nok data"

_ELECTRIC_DRIVSTOFF = {"el", "elektrisk", "electric"}


def _label_for_score(score):
    if score >= 70:
        return LABEL_GODT_KJOP
    if score >= 30:
        return LABEL_GJENNOMSNITTLIG
    return LABEL_DYRT


def is_electric(drivstoff):
    return (drivstoff or "").strip().lower() in _ELECTRIC_DRIVSTOFF


def _percentile_score(value, cohort_values, higher_is_better=False):
    """0-100, der 100 er best. higher_is_better=False (standard, brukes for
    pris/km): lavere verdi enn kohorten gir høyere score. higher_is_better=True
    (brukes for rekkevidde): høyere verdi enn kohorten gir høyere score."""
    n = len(cohort_values)
    if n == 0 or value is None:
        return None
    if higher_is_better:
        better_or_equal = int((cohort_values <= value).sum())
    else:
        better_or_equal = int((cohort_values >= value).sum())
    return 100.0 * better_or_equal / n


def _regression_score(price, year, km, cohort_df):
    rows = cohort_df.dropna(subset=["aarsmodell", "kilometerstand", "pris"])
    if len(rows) < 3 or year is None or km is None:
        return None

    x = np.column_stack([np.ones(len(rows)), rows["aarsmodell"].to_numpy(dtype=float), rows["kilometerstand"].to_numpy(dtype=float)])
    y = rows["pris"].to_numpy(dtype=float)
    try:
        coeffs, *_ = np.linalg.lstsq(x, y, rcond=None)
    except np.linalg.LinAlgError:
        return None

    predicted_all = x @ coeffs
    residuals = y - predicted_all
    std_residual = float(np.std(residuals))
    if std_residual == 0:
        return None

    predicted_price = coeffs[0] + coeffs[1] * year + coeffs[2] * km
    residual = price - predicted_price
    score = 50 - 50 * (residual / (2 * std_residual))
    return float(np.clip(score, 0, 100))


def compute_score(listing, cohort_df, min_cohort, regression_cohort):
    """listing: models.Listing. cohort_df: pandas DataFrame med kolonnene
    finn_id, pris, aarsmodell, kilometerstand for sammenlignbare annonser
    (samme merke+modell, innenfor lookback-vinduet). Selve annonsen
    ekskluderes fra kohorten hvis den er med i den."""
    if listing.pris is None:
        return ScoreResult()

    cohort_df = cohort_df[cohort_df["finn_id"] != listing.finn_id]
    n = len(cohort_df)

    if n < min_cohort:
        return ScoreResult(cohort_size=n)

    if n >= regression_cohort:
        score = _regression_score(listing.pris, listing.aarsmodell, listing.kilometerstand, cohort_df)
        if score is not None:
            return ScoreResult(score=round(score, 1), label=_label_for_score(score), cohort_size=n, method="regresjon")

    prices = cohort_df["pris"].dropna()
    score = _percentile_score(listing.pris, prices)
    if score is None:
        return ScoreResult(cohort_size=n)
    return ScoreResult(score=round(score, 1), label=_label_for_score(score), cohort_size=n, method="persentil")


def evaluate_deal(listing, cohort_df, min_cohort, exceptional_terskel):
    """Avgjør om annonsen er et "fremragende kjøp" -- skiller seg tydelig
    positivt ut på PRIS OG kilometerstand, og (kun for elbiler) OGSÅ på
    rekkevidde. Brukes til å avgjøre om annonsen er verdt et e-postvarsel,
    som en strengere sjekk enn den generelle prisbaserte Deal Label.

    Returnerer (is_exceptional: bool, km_percentile: float|None,
    range_percentile: float|None) -- persentilene vises i e-postrapporten
    slik at du ser hvorfor bilen ble plukket ut.
    """
    cohort_df = cohort_df[cohort_df["finn_id"] != listing.finn_id]
    if len(cohort_df) < min_cohort or listing.pris is None:
        return False, None, None

    price_percentile = _percentile_score(listing.pris, cohort_df["pris"].dropna())
    km_percentile = _percentile_score(listing.kilometerstand, cohort_df["kilometerstand"].dropna())

    if price_percentile is None or price_percentile < exceptional_terskel:
        return False, km_percentile, None
    if km_percentile is None or km_percentile < exceptional_terskel:
        return False, km_percentile, None

    if not is_electric(listing.drivstoff):
        return True, km_percentile, None

    range_cohort = cohort_df["rekkevidde_wltp"].dropna() if "rekkevidde_wltp" in cohort_df.columns else cohort_df["pris"].dropna().iloc[0:0]
    range_percentile = _percentile_score(listing.rekkevidde_wltp, range_cohort, higher_is_better=True)
    if range_percentile is None or range_percentile < exceptional_terskel:
        return False, km_percentile, range_percentile
    return True, km_percentile, range_percentile
