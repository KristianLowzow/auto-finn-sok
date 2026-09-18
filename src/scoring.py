"""Beregner om en annonse er et godt eller dårlig kjøp.

"Godt kjøp" måles som kr per gjenværende kilometer: bilens antatte
gjenværende levetid i km (se remaining_km) delt på prisen, sammenlignet mot
andre annonser av samme merke+modell (kohorten). Lavere kr/gjenværende km er
bedre -- det betyr enten en billig bil eller en bil med mye kjørelengde
igjen (eller begge deler), i motsetning til å bare se på rå pris.

  - For få sammenligningsbiler: ingen vurdering ("Ikke nok data").
  - Ellers: kr/gjenværende km rangeres som persentil i kohorten.

Score er alltid 0-100, der høyere er et bedre kjøp.
"""

import numpy as np

from src.models import ScoreResult

LABEL_GODT_KJOP = "Godt kjøp"
LABEL_GJENNOMSNITTLIG = "Gjennomsnittlig"
LABEL_DYRT = "Dyrt"
LABEL_IKKE_NOK_DATA = "Ikke nok data"

_ELECTRIC_DRIVSTOFF = {"el", "elektrisk", "electric"}
_FIREHJUL_VERDIER = {"firehjulsdrift", "4x4", "4wd", "awd"}

# Antakelse for "godt kjøp"-formelen: bilens levetid regnes som slutt ved
# hvilket som helst av de to inntreffer først -- alder eller kilometerstand,
# gitt en antatt kjørelengde på ~14 000 km/år.
LEVETID_AAR = 18
LEVETID_KM = 260_000
ARLIG_KJORELENGDE_KM = 14_000


def _label_for_score(score):
    if score >= 70:
        return LABEL_GODT_KJOP
    if score >= 30:
        return LABEL_GJENNOMSNITTLIG
    return LABEL_DYRT


def is_electric(drivstoff):
    return (drivstoff or "").strip().lower() in _ELECTRIC_DRIVSTOFF


def drivetrain_category(hjuldrift):
    """"4x4" for firehjulsdrift, "2-hjulsdrift" for bak-/forhjulsdrift, None
    hvis ukjent (brukes til å ekskludere annonser uten data fra plottene)."""
    value = (hjuldrift or "").strip().lower()
    if not value:
        return None
    return "4x4" if value in _FIREHJUL_VERDIER else "2-hjulsdrift"


def remaining_km(aarsmodell, kilometerstand, reference_year):
    """Estimert gjenværende levetid i km: bilen antas "ferdig" ved det som
    inntreffer først av LEVETID_AAR år eller LEVETID_KM totalt, gitt
    ARLIG_KJORELENGDE_KM km/år fra nå av. Returnerer None hvis alder eller
    kilometerstand mangler, ellers >= 0."""
    if aarsmodell is None or kilometerstand is None:
        return None
    alder_aar = reference_year - aarsmodell
    gjenvarende_aar_ved_alder = LEVETID_AAR - alder_aar
    gjenvarende_aar_ved_km = (LEVETID_KM - kilometerstand) / ARLIG_KJORELENGDE_KM
    gjenvarende_aar = min(gjenvarende_aar_ved_alder, gjenvarende_aar_ved_km)
    return max(gjenvarende_aar, 0) * ARLIG_KJORELENGDE_KM


def kr_per_remaining_km(pris, aarsmodell, kilometerstand, reference_year):
    """Returnerer (kr_per_gjenvaerende_km, gjenvaerende_km). Første verdi er
    None hvis pris eller gjenværende km mangler, eller gjenværende km er 0
    (bilen regnes som ved slutten av levetiden -- udefinert kr/km)."""
    km_igjen = remaining_km(aarsmodell, kilometerstand, reference_year)
    if km_igjen is None or not km_igjen or pris is None:
        return None, km_igjen
    return pris / km_igjen, km_igjen


def add_remaining_value_columns(df, reference_year):
    """Legger kolonnene 'gjenvaerende_km' og 'kr_per_gjenvaerende_km' til en
    KOPI av df (som må ha kolonnene aarsmodell/kilometerstand/pris) -- brukt
    som sammenligningsgrunnlag i compute_score/evaluate_deal."""
    df = df.copy()
    alder_aar = reference_year - df["aarsmodell"]
    gjenvarende_aar_ved_alder = LEVETID_AAR - alder_aar
    gjenvarende_aar_ved_km = (LEVETID_KM - df["kilometerstand"]) / ARLIG_KJORELENGDE_KM
    gjenvarende_aar = np.minimum(gjenvarende_aar_ved_alder, gjenvarende_aar_ved_km).clip(lower=0)
    df["gjenvaerende_km"] = gjenvarende_aar * ARLIG_KJORELENGDE_KM
    df["kr_per_gjenvaerende_km"] = np.where(df["gjenvaerende_km"] > 0, df["pris"] / df["gjenvaerende_km"], np.nan)
    return df


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


def compute_score(listing, cohort_df, min_cohort, reference_year):
    """listing: models.Listing. cohort_df: pandas DataFrame med kolonnene
    finn_id, pris, aarsmodell, kilometerstand for sammenlignbare annonser
    (samme merke+modell, innenfor lookback-vinduet). Selve annonsen
    ekskluderes fra kohorten hvis den er med i den.

    Rangerer kr/gjenværende km (se remaining_km) som persentil i kohorten --
    lavere er bedre."""
    if listing.pris is None:
        return ScoreResult()

    cohort_df = cohort_df[cohort_df["finn_id"] != listing.finn_id]
    cohort_df = add_remaining_value_columns(cohort_df, reference_year)
    cohort_values = cohort_df["kr_per_gjenvaerende_km"].dropna()
    n = len(cohort_values)

    if n < min_cohort:
        return ScoreResult(cohort_size=n)

    listing_value, _ = kr_per_remaining_km(listing.pris, listing.aarsmodell, listing.kilometerstand, reference_year)
    score = _percentile_score(listing_value, cohort_values)
    if score is None:
        return ScoreResult(cohort_size=n)
    return ScoreResult(score=round(score, 1), label=_label_for_score(score), cohort_size=n, method="restverdi")


def evaluate_deal(listing, cohort_df, min_cohort, exceptional_terskel, reference_year):
    """Avgjør om annonsen er et "fremragende kjøp" -- skiller seg tydelig
    positivt ut på kr/gjenværende km, og (kun for elbiler) OGSÅ på
    rekkevidde. Brukes til å avgjøre om annonsen er verdt et e-postvarsel,
    som en strengere sjekk enn den generelle Deal Label.

    Returnerer (is_exceptional: bool, km_percentile: float|None,
    range_percentile: float|None) -- persentilene vises i e-postrapporten
    slik at du ser hvorfor bilen ble plukket ut.
    """
    cohort_df = cohort_df[cohort_df["finn_id"] != listing.finn_id]
    if len(cohort_df) < min_cohort or listing.pris is None:
        return False, None, None

    cohort_df = add_remaining_value_columns(cohort_df, reference_year)
    listing_value, _ = kr_per_remaining_km(listing.pris, listing.aarsmodell, listing.kilometerstand, reference_year)
    km_percentile = _percentile_score(listing.kilometerstand, cohort_df["kilometerstand"].dropna())

    value_percentile = _percentile_score(listing_value, cohort_df["kr_per_gjenvaerende_km"].dropna())
    if value_percentile is None or value_percentile < exceptional_terskel:
        return False, km_percentile, None

    if not is_electric(listing.drivstoff):
        return True, km_percentile, None

    range_cohort = cohort_df["rekkevidde_wltp"].dropna() if "rekkevidde_wltp" in cohort_df.columns else cohort_df["pris"].dropna().iloc[0:0]
    range_percentile = _percentile_score(listing.rekkevidde_wltp, range_cohort, higher_is_better=True)
    if range_percentile is None or range_percentile < exceptional_terskel:
        return False, km_percentile, range_percentile
    return True, km_percentile, range_percentile


def compute_brand_regression_deviation(listing, brand_cohort_df, min_cohort, min_rekkevidde):
    """Predikerer pris fra årsmodell + kilometerstand + rekkevidde, på tvers
    av ALLE modeller for samme MERKE (ikke bare samme modell). Fordi
    rekkevidde er med som forklaringsvariabel, er det rimelig å slå sammen
    f.eks. "ID.4" og "ID.4 GTX" i samme regresjon -- den dyrere GTX-varianten
    forklares av at den har mer rekkevidde/kraft, ikke bare av at den er en
    annen modell.

    Kun elbiler med rekkevidde over `min_rekkevidde` regnes med, både som
    kandidat og i sammenligningsgrunnlaget, slik at korte og lange rekkevidder
    ikke sammenlignes rått mot hverandre.

    Returnerer (avvik_prosent, kohort_størrelse). avvik_prosent er hvor mange
    prosent annonsens pris ligger UNDER (negativt) eller OVER (positivt)
    "merke-linja" -- godt kjøp er et stort negativt tall. None hvis bilen
    ikke er elektrisk, mangler rekkevidde, er under grensen, eller det ikke
    er nok sammenlignbare biler.
    """
    if not is_electric(listing.drivstoff) or listing.rekkevidde_wltp is None or listing.rekkevidde_wltp <= min_rekkevidde:
        return None, 0
    if listing.pris is None or listing.aarsmodell is None or listing.kilometerstand is None:
        return None, 0

    eligible = brand_cohort_df[brand_cohort_df["finn_id"] != listing.finn_id]
    if "rekkevidde_wltp" not in eligible.columns:
        return None, 0
    eligible = eligible.dropna(subset=["pris", "aarsmodell", "kilometerstand", "rekkevidde_wltp"])
    eligible = eligible[eligible["rekkevidde_wltp"] > min_rekkevidde]

    n = len(eligible)
    if n < min_cohort:
        return None, n

    x = np.column_stack(
        [
            np.ones(n),
            eligible["aarsmodell"].to_numpy(dtype=float),
            eligible["kilometerstand"].to_numpy(dtype=float),
            eligible["rekkevidde_wltp"].to_numpy(dtype=float),
        ]
    )
    y = eligible["pris"].to_numpy(dtype=float)
    try:
        coeffs, *_ = np.linalg.lstsq(x, y, rcond=None)
    except np.linalg.LinAlgError:
        return None, n

    predicted = (
        coeffs[0]
        + coeffs[1] * listing.aarsmodell
        + coeffs[2] * listing.kilometerstand
        + coeffs[3] * listing.rekkevidde_wltp
    )
    if predicted <= 0:
        return None, n

    deviation_pct = 100.0 * (listing.pris - predicted) / predicted
    return round(deviation_pct, 1), n
