"""Logg-oppsett og bygging av Kjørelogg-raden."""

import logging


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def build_run_log_row(now_iso, duration_s, brands_scanned, run_stats, status):
    return [
        now_iso,
        round(duration_s, 1),
        brands_scanned,
        run_stats.get("nye", 0),
        run_stats.get("oppdaterte", 0),
        run_stats.get("fjernet", 0),
        run_stats.get("feil", 0),
        "; ".join(run_stats.get("feilmeldinger", []))[:500],
        status,
    ]
