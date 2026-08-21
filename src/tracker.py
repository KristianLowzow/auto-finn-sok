"""Sporer hvilke annonser som er nye, fortsatt aktive, eller forsvunnet.

En annonse arkiveres først etter å ha vært borte fra søkeresultatet i to
påfølgende kjøringer (ikke umiddelbart), for å tåle at Finns søk av og til
er ustabilt eller paginerer annerledes mellom to kjøringer.
"""

from dataclasses import replace


def diff_listings(previous_listings, current_search_results, now_iso):
    """Sammenligner forrige og nåværende søketreff for ett merke/modell.

    previous_listings: liste av models.Listing (fra Aktive Annonser)
    current_search_results: liste av dict fra scraper.search_listings

    Returnerer (new_ids, still_active, to_archive) der:
      - new_ids: sett med finn_id som må detalj-hentes
      - still_active: liste av Listing (oppdatert pris/sist_sett/mangler_siden)
        for annonser som fortsatt finnes eller er i sin første "miss"
      - to_archive: liste av Listing som skal flyttes til Historikk
    """
    previous_by_id = {listing.finn_id: listing for listing in previous_listings}
    current_by_id = {entry["finn_id"]: entry for entry in current_search_results}

    new_ids = set(current_by_id) - set(previous_by_id)
    still_ids = set(current_by_id) & set(previous_by_id)
    missing_ids = set(previous_by_id) - set(current_by_id)

    still_active = []
    for finn_id in still_ids:
        listing = previous_by_id[finn_id]
        entry = current_by_id[finn_id]
        still_active.append(
            replace(
                listing,
                pris=entry.get("pris", listing.pris),
                sist_sett=now_iso,
                mangler_siden="",
            )
        )

    to_archive = []
    for finn_id in missing_ids:
        listing = previous_by_id[finn_id]
        if listing.mangler_siden:
            to_archive.append(listing)
        else:
            still_active.append(replace(listing, mangler_siden=now_iso))

    return new_ids, still_active, to_archive
