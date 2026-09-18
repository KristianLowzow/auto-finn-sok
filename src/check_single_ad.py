"""Sjekker én enkelt Finn-annonse på forespørsel (manuell trigger).

Henter annonsen, bygger sammenligningsgrunnlag fra det arket allerede vet
om samme merke+modell (Aktive Annonser + Historikk), skriver resultatet til
"Sjekk enkeltannonse"-fanen, og sender en e-post med svaret. Legger IKKE
annonsen inn i den løpende sporingen i Aktive Annonser -- dette er et
frittstående engangsoppslag.
"""

import logging
import os
import sys
from datetime import datetime, timezone

import pandas as pd

from src import notifier, scoring, sheets_client
from src.finn_client import FinnClient
from src.logging_utils import setup_logging
from src.models import Listing
from src.parsers import finn_id_from_url

logger = logging.getLogger(__name__)


def check_url(url):
    setup_logging()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat(timespec="seconds")

    finn_id = finn_id_from_url(url)
    if not finn_id:
        raise ValueError(f"Kjenner ikke igjen dette som en Finn-annonse-URL: {url}")

    client = FinnClient()
    response = client.get(url)
    from src.parsers import parse_ad_detail

    detail = parse_ad_detail(response.text, finn_id=finn_id, url=url)

    listing = Listing(
        finn_id=detail["finn_id"],
        url=detail["url"],
        merke=detail.get("merke", ""),
        modell=detail.get("modell", ""),
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

    spreadsheet = sheets_client.open_sheet()
    sheets_client.ensure_tabs(spreadsheet)
    overrides = sheets_client.read_settings_overrides(spreadsheet)
    active_df = sheets_client.read_active_listings(spreadsheet)
    history_df = sheets_client.read_history(spreadsheet)

    frames = [df for df in (active_df, history_df) if not df.empty]
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=Listing.columns())
    cohort = combined[(combined["merke"] == listing.merke) & (combined["modell"] == listing.modell)] if not combined.empty else combined

    result = scoring.compute_score(listing, cohort, overrides["MinKohort"], now.year)
    listing.deal_score = result.score
    listing.deal_label = result.label
    listing.kr_per_gjenvaerende_km, listing.gjenvaerende_km = scoring.kr_per_remaining_km(
        listing.pris, listing.aarsmodell, listing.kilometerstand, now.year
    )

    row = [now_iso, url] + listing.to_row()
    sheets_client.append_enkeltsjekk(spreadsheet, row)
    notifier.send_single_check_result(listing, result)

    logger.info(
        "Sjekket %s %s (%s): %s%s, basert på %d sammenlignbare biler",
        listing.merke,
        listing.modell,
        url,
        result.label,
        f" ({result.score}/100)" if result.score is not None else "",
        result.cohort_size,
    )
    return listing, result


if __name__ == "__main__":
    target_url = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("CHECK_URL")
    if not target_url:
        raise SystemExit("Bruk: python -m src.check_single_ad <finn-url> (eller sett CHECK_URL)")
    check_url(target_url)
