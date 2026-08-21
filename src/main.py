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
    for col in ("pris", "kilometerstand", "rekkevidde_wltp", "aarsmodell", "deal_score"):
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
        result = scoring.compute_score(listing, cohort, overrides["MinKohort"], overrides["RegresjonKohort"])
        listing.deal_score = result.score
        listing.deal_label = result.label

        is_exceptional, km_percentile, range_percentile = scoring.evaluate_deal(
            listing, cohort, overrides["MinKohort"], overrides["GodtKjopTerskel"]
        )
        listing.fremragende_kjop = is_exceptional
        scored.append((listing, result, km_percentile, range_percentile))
    return scored


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

        updated_active_df = pd.DataFrame([l.to_row() for l in all_listings], columns=Listing.columns())
        stat_tables = {
            "Prisutvikling per uke": stats.build_price_trend(active_df, history_df),
            "Prisutvikling per årsmodell": stats.build_price_by_year(updated_active_df, history_df),
            "Pris vs. kilometerstand (aktive)": stats.build_price_vs_km(updated_active_df),
            "Nye/fjernet per uke": stats.build_new_removed_counts(active_df, history_df),
            "Fordeling av vurdering": stats.build_score_distribution(updated_active_df),
        }
        sheets_client.write_stats_tables(spreadsheet, stat_tables)

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
