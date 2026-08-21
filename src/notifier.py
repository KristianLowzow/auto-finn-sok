"""E-postvarsling via Gmail SMTP + app-passord."""

import logging
import smtplib
from email.mime.text import MIMEText

from src import config

logger = logging.getLogger(__name__)


def is_configured():
    return bool(config.SMTP_USER and config.SMTP_APP_PASSWORD and config.ALERT_EMAIL_TO)


def _send(subject, body):
    if not is_configured():
        logger.warning("E-postvarsling er ikke konfigurert (mangler SMTP_USER/SMTP_APP_PASSWORD/ALERT_EMAIL_TO)")
        return False

    message = MIMEText(body, "plain", "utf-8")
    message["Subject"] = subject
    message["From"] = config.SMTP_USER
    message["To"] = config.ALERT_EMAIL_TO

    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
        server.starttls()
        server.login(config.SMTP_USER, config.SMTP_APP_PASSWORD)
        server.send_message(message)
    return True


def send_daily_digest(candidates):
    """Sender ÉN samlet e-post med alle fremragende kjøp funnet i denne
    kjøringen, i stedet for én e-post per bil. candidates: liste av
    (listing, score_result, km_percentile, range_percentile)."""
    if not candidates:
        return False

    count = len(candidates)
    subject = f"{count} fremragende kjøp funnet" if count > 1 else "1 fremragende kjøp funnet"

    sections = []
    for listing, score_result, km_percentile, range_percentile in candidates:
        lines = [
            f"{listing.merke} {listing.modell} ({listing.variant})",
            f"Årsmodell: {listing.aarsmodell}   Kilometerstand: {listing.kilometerstand} km   Pris: {listing.pris} kr",
            f"Pris-persentil: {score_result.score}/100   Km-persentil: {round(km_percentile, 1) if km_percentile is not None else '-'}/100",
        ]
        if range_percentile is not None:
            lines.append(f"Rekkevidde (WLTP): {listing.rekkevidde_wltp} km   Rekkevidde-persentil: {round(range_percentile, 1)}/100")
        lines.append(listing.url)
        sections.append("\n".join(lines))

    body = f"{count} annonse(r) skiller seg tydelig positivt ut på pris, kilometerstand" \
           f"{' og rekkevidde (for elbiler)' if any(c[3] is not None for c in candidates) else ''}" \
           f" sammenlignet med lignende biler:\n\n" + "\n\n".join(sections)
    return _send(subject, body)


def send_single_check_result(listing, score_result):
    if score_result.score is None:
        subject = f"Sjekk av annonse: {listing.merke} {listing.modell} - ikke nok data"
    else:
        subject = f"Sjekk av annonse: {listing.merke} {listing.modell} - {score_result.label} ({score_result.score}/100)"
    body = (
        f"{listing.merke} {listing.modell} ({listing.variant})\n"
        f"Årsmodell: {listing.aarsmodell}\n"
        f"Kilometerstand: {listing.kilometerstand} km\n"
        f"Pris: {listing.pris} kr\n"
        f"Vurdering: {score_result.label}"
        + (f" ({score_result.score}/100)" if score_result.score is not None else "")
        + f"\nBasert på {score_result.cohort_size} sammenlignbare biler (metode: {score_result.method})\n\n"
        f"{listing.url}"
    )
    return _send(subject, body)
