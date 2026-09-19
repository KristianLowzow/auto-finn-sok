"""Orkestrerer én kjøring: les innstillinger -> søk -> diff -> score -> skriv -> varsle."""

import logging
import time
from datetime import datetime, timedelta, timezone

import pandas as pd

from src import config, notifier, scoring, sheets_client, stats, scraper, tracker
from src.finn_client import BlockedError, FinnClient
from src.logging_utils import build_run_log_row, setup_logging
from src.models import Listing
from src.parsers import SchemaDriftError

logger = logging.getLogger(__name__)


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _listings_to_df(listings):
    df = pd.DataFrame([l.to_row() for l in listings], columns=Listing.columns())
    numeric_cols = (
        "pris", "kilometerstand", "rekkevidde_wltp", "aarsmodell", "deal_score", "regresjon_avvik_pct",
        "batteri_kapasitet_kwh", "gjenvaerende_km", "kr_per_gjenvaerende_km",
    )
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _days_between(iso_start, iso_now):
    try:
        start = datetime.fromisoformat(iso_start)
        now = datetime.fromisoformat(iso_now)
        return (now - start).days
    except (TypeError, ValueError):
        return ""


def _build_listing_from_detail(detail, fallback_merke, fallback_modell, now_iso):
    return Listing(
        finn_id=detail["finn_id"],
        url=detail["url"],
        merke=detail.get("merke") or fallback_merke,
        modell=detail.get("modell") or fallback_modell,
        variant=detail.get("variant", ""),
        aarsmodell=detail.get("aarsmodell"),
        kilometerstand=detail.get("kilometerstand"),
        rekkevidde_wltp=detail.get("rekkevidde_wltp"),
        pris=detail.get("pris"),
        drivstoff=detail.get("drivstoff", ""),
        girkasse=detail.get("girkasse", ""),
        karosseri=detail.get("karosseri", ""),
        sted=detail.get("sted", ""),
        selger_type=detail.get("selger_type", ""),
        hjuldrift=detail.get("hjuldrift", ""),
        batteri_kapasitet_kwh=detail.get("batteri_kapasitet_kwh"),
        utstyrspakke=detail.get("utstyrspakke", ""),
        varmepumpe=detail.get("varmepumpe", ""),
        head_up_display=detail.get("head_up_display", ""),
        oppvarmet_ratt=detail.get("oppvarmet_ratt", ""),
        oppvarmede_seter_foran=detail.get("oppvarmede_seter_foran", ""),
        oppvarmede_seter_bak=detail.get("oppvarmede_seter_bak", ""),
        tradlos_mobillading=detail.get("tradlos_mobillading", ""),
        forste_gang_sett=now_iso,
        sist_sett=now_iso,
    )


def _process_brand_model(client, spreadsheet, setting, all_active_listings, now_iso, run_stats):
    merke, modell, filters = setting["merke"], setting["modell"], setting["filters"]
    previous = [l for l in all_active_listings if l.merke == merke and l.modell == modell]

    try:
        search_results = scraper.search_listings(client, merke, modell, filters)
    except SchemaDriftError as exc:
        logger.error("Skjema-drift ved søk %s %s: %s", merke, modell, exc)
        run_stats["feil"] += 1
        run_stats["feilmeldinger"].append(str(exc))
        return previous, []

    new_ids, still_active, to_archive = tracker.diff_listings(previous, search_results, now_iso)
    entries_by_id = {e["finn_id"]: e for e in search_results}

    new_listings = []
    for finn_id in new_ids:
        if len(new_listings) >= config.MAX_NEW_DETAIL_FETCHES_PER_RUN:
            logger.info("Nådde grense for nye detaljhentinger, resten tas neste kjøring (%s %s)", merke, modell)
            break
        entry = entries_by_id[finn_id]
        try:
            detail = scraper.fetch_detail(client, finn_id, entry["url"])
        except SchemaDriftError as exc:
            logger.warning("Kunne ikke tolke annonse %s: %s", finn_id, exc)
            run_stats["feil"] += 1
            run_stats["feilmeldinger"].append(str(exc))
            continue
        new_listings.append(_build_listing_from_detail(detail, merke, modell, now_iso))

    run_stats["nye"] += len(new_listings)
    run_stats["oppdaterte"] += len(still_active)
    run_stats["fjernet"] += len(to_archive)

    archived_rows = []
    for listing in to_archive:
        dager = _days_between(listing.forste_gang_sett, now_iso)
        archived_rows.append(
            listing.to_row() + [listing.pris, now_iso, "Antatt solgt/fjernet (ikke bekreftet salgspris)", dager]
        )
    if archived_rows:
        sheets_client.append_history_rows(spreadsheet, archived_rows)

    return still_active + new_listings, new_listings


def _score_all(all_listings, history_df, overrides, now_iso):
    reference_year = datetime.fromisoformat(now_iso).year
    lookback_cutoff = datetime.now(timezone.utc) - timedelta(days=overrides["LookbackDager"])

    active_df = _listings_to_df(all_listings)
    combined_frames = [active_df]
    if not history_df.empty:
        combined_frames.append(history_df[Listing.columns()])
    combined = pd.concat(combined_frames, ignore_index=True) if combined_frames else active_df

    def in_window(value):
        try:
            return datetime.fromisoformat(value) >= lookback_cutoff
        except (TypeError, ValueError):
            return True  # ukjent dato holdes med heller enn å utelukkes feilaktig

    combined = combined[combined["forste_gang_sett"].apply(in_window)]

    scored = []
    for listing in all_listings:
        cohort = combined[(combined["merke"] == listing.merke) & (combined["modell"] == listing.modell)]
        result = scoring.compute_score(listing, cohort, overrides["MinKohort"], reference_year)
        listing.deal_score = result.score
        listing.deal_label = result.label
        listing.kr_per_gjenvaerende_km, listing.gjenvaerende_km = scoring.kr_per_remaining_km(
            listing.pris, listing.aarsmodell, listing.kilometerstand, reference_year
        )

        is_exceptional, km_percentile, range_percentile = scoring.evaluate_deal(
            listing, cohort, overrides["MinKohort"], overrides["GodtKjopTerskel"], reference_year
        )
        listing.fremragende_kjop = is_exceptional

        brand_cohort = combined[combined["merke"] == listing.merke]
        deviation_pct, _brand_cohort_size = scoring.compute_brand_regression_deviation(
            listing, brand_cohort, overrides["MinKohort"], overrides["MinRekkevidde"]
        )
        listing.regresjon_avvik_pct = deviation_pct

        scored.append((listing, result, km_percentile, range_percentile))
    return scored


def refresh_statistics(spreadsheet, active_df, history_df, updated_active_df):
    """Bygger og skriver alle tabellene/diagrammene i Statistikk-fanen.

    active_df/history_df: tilstanden FØR denne kjøringens endringer (brukt av
    ukebaserte tabeller som teller "nye" mot when en annonse først ble sett).
    updated_active_df: Aktive Annonser slik den ser ut ETTER denne kjøringen.

    Egen funksjon (i stedet for inline i run()) slik at Statistikk kan bygges
    på nytt fra det som allerede står i arket -- uten å skrape Finn.no på
    nytt -- se scripts/refresh_stats.py."""
    stat_tables = {
        "Prisutvikling per uke": stats.build_price_trend(active_df, history_df),
        "Prisutvikling per årsmodell": stats.build_price_by_year(updated_active_df, history_df),
        "Nye/fjernet per uke": stats.build_new_removed_counts(active_df, history_df),
        "Fordeling av vurdering": stats.build_score_distribution(updated_active_df),
        "Škoda Enyaq vs. VW ID.4 (per hjuldrift)": stats.build_model_drivetrain_comparison(
            updated_active_df, [("Skoda", "Enyaq"), ("Volkswagen", "ID.4")]
        ),
    }

    chart_specs = []
    for brand, brand_df in stats.build_price_vs_km_by_brand(updated_active_df).items():
        title = f"Pris vs. km — {brand}"
        stat_tables[title] = brand_df
        chart_specs.append(
            {
                "table_title": title,
                "chart_title": f"Pris vs. kilometerstand — {brand} (farge=batteristørrelse)",
                "series_prefix": stats.PRICE_SERIES_PREFIX,
                "y_axis_title": "Pris",
            }
        )

    drivetrain_titles = {"4x4": "Pris vs. km — 4x4 (alle merker)", "2-hjulsdrift": "Pris vs. km — 2-hjulsdrift (alle merker)"}
    for category, drivetrain_df in stats.build_price_vs_km_by_drivetrain(updated_active_df).items():
        title = drivetrain_titles[category]
        stat_tables[title] = drivetrain_df
        chart_specs.append(
            {
                "table_title": title,
                "chart_title": f"Pris vs. kilometerstand — {category} (alle merker, farge=merke)",
                "series_prefix": stats.PRICE_SERIES_PREFIX,
                "y_axis_title": "Pris",
            }
        )

    remaining_value_titles = {
        "4x4": "Kr per gjenværende km vs. km — 4x4 (alle merker)",
        "2-hjulsdrift": "Kr per gjenværende km vs. km — 2-hjulsdrift (alle merker)",
    }
    for category, remaining_value_df in stats.build_remaining_value_vs_km_by_drivetrain(updated_active_df).items():
        title = remaining_value_titles[category]
        stat_tables[title] = remaining_value_df
        chart_specs.append(
            {
                "table_title": title,
                "chart_title": f"Kr per gjenværende km vs. kilometerstand — {category} (alle merker, farge=merke)",
                "series_prefix": stats.REMAINING_VALUE_SERIES_PREFIX,
                "y_axis_title": "Kr per gjenværende km",
            }
        )

    layout = sheets_client.write_stats_tables(spreadsheet, stat_tables)
    sheets_client.apply_grouped_scatter_charts(spreadsheet, layout, chart_specs)


def run():
    setup_logging()
    start = time.monotonic()
    now_iso = _now_iso()
    run_stats = {"nye": 0, "oppdaterte": 0, "fjernet": 0, "feil": 0, "feilmeldinger": []}
    status = "OK"

    spreadsheet = sheets_client.open_sheet()
    sheets_client.ensure_tabs(spreadsheet)

    try:
        settings = sheets_client.read_settings(spreadsheet)
        overrides = sheets_client.read_settings_overrides(spreadsheet)
        active_df = sheets_client.read_active_listings(spreadsheet)
        history_df = sheets_client.read_history(spreadsheet)
        previous_listings = sheets_client.listings_from_df(active_df)

        if not settings:
            logger.warning("Ingen aktive merker/modeller i Merker-fanen -- ingenting å gjøre")

        client = FinnClient()
        all_listings = []
        for setting in settings:
            merged, _new_listings = _process_brand_model(client, spreadsheet, setting, previous_listings, now_iso, run_stats)
            all_listings.extend(merged)

        untouched = [
            l for l in previous_listings
            if not any(s["merke"] == l.merke and s["modell"] == l.modell for s in settings)
        ]
        all_listings.extend(untouched)

        scored = _score_all(all_listings, history_df, overrides, now_iso)

        alert_price_cap = {}
        for setting in settings:
            cap = setting.get("alert_max_price")
            alert_price_cap[(setting["merke"], setting["modell"])] = float(cap) if cap else overrides["StandardMaksPrisVarsel"]

        digest_candidates = []
        for listing, result, km_percentile, range_percentile in scored:
            if not listing.fremragende_kjop or listing.varslet or listing.pris is None:
                continue
            cap = alert_price_cap.get((listing.merke, listing.modell), overrides["StandardMaksPrisVarsel"])
            if listing.pris > cap:
                continue
            digest_candidates.append((listing, result, km_percentile, range_percentile))

        if digest_candidates:
            if notifier.send_daily_digest(digest_candidates):
                for listing, *_ in digest_candidates:
                    listing.varslet = True
            logger.info("%d fremragende kjøp funnet, digest-e-post sendt", len(digest_candidates))

        sheets_client.write_active_listings(spreadsheet, all_listings)
        sheets_client.apply_conditional_formatting(spreadsheet)

        try:
            refresh_statistics(spreadsheet, active_df, history_df, _listings_to_df(all_listings))
        except Exception as exc:
            # Statistikk/diagram er et tillegg -- en feil her skal ikke gjøre at
            # allerede skrevne Aktive Annonser/scoring regnes som en mislykket kjøring.
            logger.exception("Klarte ikke å oppdatere Statistikk-fanen/diagrammene")
            run_stats["feil"] += 1
            run_stats["feilmeldinger"].append(f"Statistikk/diagram feilet: {type(exc).__name__}: {exc}")

    except BlockedError as exc:
        logger.error("Avbryter kjøringen -- blokkert av Finn.no: %s", exc)
        status = "Feilet"
        run_stats["feil"] += 1
        run_stats["feilmeldinger"].append(str(exc))
    except Exception as exc:  # siste skanse: aldri feile stille
        logger.exception("Uventet feil under kjøring")
        status = "Feilet"
        run_stats["feil"] += 1
        run_stats["feilmeldinger"].append(f"{type(exc).__name__}: {exc}")
    finally:
        duration = time.monotonic() - start
        brands_scanned = 0
        try:
            brands_scanned = len(settings)
        except NameError:
            pass
        row = build_run_log_row(now_iso, duration, brands_scanned, run_stats, status)
        sheets_client.append_run_log(spreadsheet, row)
        logger.info("Kjøring ferdig på %.1fs, status=%s", duration, status)


if __name__ == "__main__":
    run()
