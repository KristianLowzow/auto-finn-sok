"""Tolker HTML fra Finn.no til strukturerte data.

Strategi (mest til minst robust):
  - Søkeresultater: strukturert schema.org JSON-LD ("seoStructuredData")
    embedded i søkesiden -- gir merke/modell/pris/bilde/URL per annonse.
  - Annonsedetaljer: en nøkkelinfo-liste (<dt>/<dd>-par, f.eks. "Kilometerstand")
    som er felles for Finns kjøretøyannonser, supplert med schema.org
    JSON-LD Product for pris/bilder/merke/modell.

Begge er ment for SEO (søkemotor-indeksering) og har derfor insentiv til å
holdes stabile av Finn selv -- mer robust enn å parse rå DOM/CSS-klasser,
som endres oftere. Hvis Finn endrer disse, skal vi feile høylytt
(SchemaDriftError) i stedet for å skrive feil/tomme data til arket.
"""

import json
import re

from bs4 import BeautifulSoup


class SchemaDriftError(RuntimeError):
    """Reist når forventede felt mangler -- Finn har trolig endret siden sin."""


def _extract_json_ld_blocks(soup):
    blocks = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            blocks.append(json.loads(tag.string or "{}"))
        except (json.JSONDecodeError, TypeError):
            continue
    return blocks


def finn_id_from_url(url):
    match = re.search(r"/mobility/item/(\d+)", url or "")
    return match.group(1) if match else None


def _clean_int(text):
    if text is None:
        return None
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


# --- Søkeresultater ---


def parse_search_results(html):
    """Returnerer liste av dict: finn_id, url, merke, modell, variant, pris, bilde."""
    soup = BeautifulSoup(html, "lxml")
    script = soup.find("script", id="seoStructuredData")
    if script is None or not script.string:
        raise SchemaDriftError(
            "Fant ikke seoStructuredData-blokken på søkesiden -- Finn har trolig endret oppsettet"
        )
    try:
        data = json.loads(script.string)
    except json.JSONDecodeError as exc:
        raise SchemaDriftError(f"Klarte ikke å tolke seoStructuredData som JSON: {exc}") from exc

    items = data.get("mainEntity", {}).get("itemListElement", [])
    if not items:
        return []

    results = []
    for entry in items:
        item = entry.get("item", {})
        url = item.get("url", "")
        finn_id = finn_id_from_url(url)
        if not finn_id:
            continue
        offers = item.get("offers", {}) or {}
        brand = (item.get("brand") or {}).get("name", "")
        results.append(
            {
                "finn_id": finn_id,
                "url": url,
                "merke": brand,
                "modell": item.get("model", ""),
                "variant": item.get("description", ""),
                "pris": _clean_int(str(offers.get("price", ""))),
                "bilde": item.get("image", ""),
            }
        )
    return results


def parse_total_results(html):
    """Antall totale treff for søket, brukes til å avgjøre paginering."""
    match = re.search(r'role="status">\s*([\d\s\xa0]+)\s*(?:resultater|treff)', html)
    if not match:
        return None
    return _clean_int(match.group(1))


# --- Annonsedetaljer ---

# Finn bruker litt ulike norske etiketter avhengig av kjøretøytype -- listen
# under er kjente varianter, ikke en fullstendig kontrakt. Nye/manglende
# etiketter påvirker ikke andre felt.
_FIELD_MAP = {
    "modellår": "aarsmodell",
    "årsmodell": "aarsmodell",
    "1. gang registrert": "forstegangsregistrert",
    "1.gang registrert": "forstegangsregistrert",
    "kilometerstand": "kilometerstand",
    "girkasse": "girkasse",
    "drivstoff": "drivstoff",
    "karosseri": "karosseri",
    "merke": "merke_dt",
    "modell": "modell_dt",
}


def _parse_key_facts(soup):
    facts = {}
    for dt in soup.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if dd is None:
            continue
        label = dt.get_text(strip=True).lower()
        value = dd.get_text(strip=True)
        canonical = _FIELD_MAP.get(label)
        if canonical:
            facts[canonical] = value
        facts.setdefault("_raw", {})[label] = value
    return facts


def _parse_location_postal_code(html):
    match = re.search(r"postalCode=(\d{4})", html)
    return match.group(1) if match else ""


def _parse_seller_type(product_ld):
    seller = ((product_ld or {}).get("offers", {}) or {}).get("seller", {}) or {}
    seller_type = seller.get("@type", "")
    if seller_type == "Organization":
        return "Forhandler"
    if seller_type == "Person":
        return "Privat"
    return ""


def parse_ad_detail(html, finn_id=None, url=None):
    """Returnerer dict med feltene i models.Listing (unntatt sporingsfelt)."""
    soup = BeautifulSoup(html, "lxml")
    ld_blocks = _extract_json_ld_blocks(soup)
    product_ld = next((b for b in ld_blocks if b.get("@type") == "Product"), {})

    facts = _parse_key_facts(soup)

    brand = (product_ld.get("brand") or {}).get("name") or facts.get("merke_dt", "")
    model_field = product_ld.get("model")
    if isinstance(model_field, dict):
        model_name = model_field.get("name", "")
    else:
        model_name = model_field or facts.get("modell_dt", "")

    price = None
    offers = product_ld.get("offers") or {}
    if offers.get("price") is not None:
        price = _clean_int(str(offers["price"]))

    result = {
        "finn_id": finn_id or finn_id_from_url(product_ld.get("url") or url or ""),
        "url": product_ld.get("url") or url or "",
        "merke": brand,
        "modell": model_name,
        "aarsmodell": _clean_int(facts.get("aarsmodell")),
        "kilometerstand": _clean_int(facts.get("kilometerstand")),
        "pris": price,
        "drivstoff": facts.get("drivstoff", ""),
        "girkasse": facts.get("girkasse", ""),
        "karosseri": facts.get("karosseri", ""),
        "sted": _parse_location_postal_code(html),
        "selger_type": _parse_seller_type(product_ld),
    }

    if not result["finn_id"] or result["pris"] is None or not (result["merke"] or result["modell"]):
        raise SchemaDriftError(
            f"Kritiske felt mangler for annonse {result.get('finn_id') or url} "
            f"(finn_id={result['finn_id']!r}, pris={result['pris']!r}, merke={result['merke']!r}, "
            f"modell={result['modell']!r}) -- Finn har trolig endret sideoppsettet"
        )
    return result
