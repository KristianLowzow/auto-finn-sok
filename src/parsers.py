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

import base64
import binascii
import json
import re
from urllib.parse import unquote

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


# --- React-appens egen annonsedata (data-props) ---
#
# Finn embedder en rikere datakilde enn nøkkelinfo-listen og schema.org:
# et data-props-attributt (base64 av en URL-prosentenkodet JSON-streng) som
# blant annet inneholder strukturert utstyrsliste, hjuldrift og rekkevidde.
# Best-effort: hvis Finn endrer formatet gir vi bare tom dict tilbake --
# feltene herfra (utstyr, hjuldrift, batteri) er tillegg, ikke kritiske felt.


def _extract_react_ad_data(soup):
    container = soup.find(attrs={"data-props": True})
    if container is None:
        return {}
    raw = container.get("data-props", "")
    try:
        decoded = base64.b64decode(raw + "==")
        text = unquote(decoded.decode("utf-8"))
        data = json.loads(text)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error):
        return {}
    return (data.get("adData") or {}).get("ad") or {}


_BATTERY_KWH_RE = re.compile(r"batterikapasitet\D{0,12}?(\d+(?:[.,]\d+)?)\s*kwh", re.IGNORECASE)


def _parse_battery_kwh(text):
    match = _BATTERY_KWH_RE.search(text or "")
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


# Finns utstyrsvokabular er IKKE så fast i praksis som navnet skulle tilsi --
# samme funksjon skrives ulikt avhengig av hvilket system annonsen kommer fra
# (f.eks. "Head up display" vs. "Head-up-display", "Oppvarmet ratt" vs.
# "Ratt oppvarmet"). Derfor matcher vi på at ALLE nøkkelord under finnes et
# sted i SAMME utstyrslinje (uavhengig av rekkefølge/tegnsetting), i stedet
# for eksakt streng-likhet.
_EQUIPMENT_FEATURE_KEYWORDS = {
    "varmepumpe": ["varmepump"],
    "head_up_display": ["head", "display"],
    "oppvarmet_ratt": ["oppvarm", "ratt"],
    "oppvarmede_seter_foran": ["oppvarm", "sete", "foran"],
    "oppvarmede_seter_bak": ["oppvarm", "sete", "bak"],
    "tradlos_mobillading": ["trådløs", "mobil"],
}


def _feature_flag(equipment_names_lower, keywords):
    """"Ukjent" når vi ikke har noen utstyrsliste å sjekke mot i det hele
    tatt (annonsen manglet data-props), ellers "Ja"/"Nei" ut fra om alle
    nøkkelordene finnes i minst én utstyrslinje."""
    if not equipment_names_lower:
        return "Ukjent"
    for name in equipment_names_lower:
        if all(keyword in name for keyword in keywords):
            return "Ja"
    return "Nei"


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

# Noen felt (f.eks. rekkevidde) har en skjult forklaringstekst limt rett inn i
# <dt>-teksten uten mellomrom (f.eks. "Rekkevidde (WLTP)WLTP er et måltall...").
# Disse matches på prefiks i stedet for eksakt likhet.
_FIELD_PREFIXES = {
    "rekkevidde": "rekkevidde_wltp",
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
        if canonical is None:
            for prefix, mapped in _FIELD_PREFIXES.items():
                if label.startswith(prefix):
                    canonical = mapped
                    break
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
    ad_data = _extract_react_ad_data(soup)

    equipment_entries = ad_data.get("equipment") or []
    equipment_names = [e.get("value", "") for e in equipment_entries if isinstance(e, dict) and e.get("value")]
    equipment_names_lower = {name.strip().lower() for name in equipment_names}

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
        "rekkevidde_wltp": _clean_int(facts.get("rekkevidde_wltp")) or ad_data.get("driving_range"),
        "pris": price,
        "drivstoff": facts.get("drivstoff", ""),
        "girkasse": facts.get("girkasse", ""),
        "karosseri": facts.get("karosseri", ""),
        "sted": _parse_location_postal_code(html),
        "selger_type": _parse_seller_type(product_ld),
        "hjuldrift": (ad_data.get("wheel_drive") or {}).get("value", ""),
        "batteri_kapasitet_kwh": _parse_battery_kwh(soup.get_text(" ")),
        "utstyrspakke": ", ".join(equipment_names),
        "varmepumpe": _feature_flag(equipment_names_lower, _EQUIPMENT_FEATURE_KEYWORDS["varmepumpe"]),
        "head_up_display": _feature_flag(equipment_names_lower, _EQUIPMENT_FEATURE_KEYWORDS["head_up_display"]),
        "oppvarmet_ratt": _feature_flag(equipment_names_lower, _EQUIPMENT_FEATURE_KEYWORDS["oppvarmet_ratt"]),
        "oppvarmede_seter_foran": _feature_flag(equipment_names_lower, _EQUIPMENT_FEATURE_KEYWORDS["oppvarmede_seter_foran"]),
        "oppvarmede_seter_bak": _feature_flag(equipment_names_lower, _EQUIPMENT_FEATURE_KEYWORDS["oppvarmede_seter_bak"]),
        "tradlos_mobillading": _feature_flag(equipment_names_lower, _EQUIPMENT_FEATURE_KEYWORDS["tradlos_mobillading"]),
    }

    if not result["finn_id"] or result["pris"] is None or not (result["merke"] or result["modell"]):
        raise SchemaDriftError(
            f"Kritiske felt mangler for annonse {result.get('finn_id') or url} "
            f"(finn_id={result['finn_id']!r}, pris={result['pris']!r}, merke={result['merke']!r}, "
            f"modell={result['modell']!r}) -- Finn har trolig endret sideoppsettet"
        )
    return result
