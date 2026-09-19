"""Aggregerer data til de faste tabellene Statistikk-fanens grafer leser fra."""

import pandas as pd

from src.scoring import drivetrain_category


def _iso_week(date_series):
    dates = pd.to_datetime(date_series, errors="coerce")
    return dates.dt.strftime("%G-U%V")


def _battery_bucket(kwh):
    if pd.isna(kwh):
        return "Ukjent"
    return f"{int(round(kwh))} kWh"


def build_price_trend(active_df, history_df):
    """Snittpris per merke/modell/uke, basert på når annonsen først ble sett."""
    frames = []
    if not active_df.empty:
        frames.append(active_df[["merke", "modell", "pris", "forste_gang_sett"]])
    if not history_df.empty:
        frames.append(history_df[["merke", "modell", "pris", "forste_gang_sett"]])
    if not frames:
        return pd.DataFrame(columns=["Uke", "Merke", "Modell", "Snittpris", "Antall"])

    combined = pd.concat(frames, ignore_index=True).dropna(subset=["pris"])
    combined["Uke"] = _iso_week(combined["forste_gang_sett"])
    grouped = (
        combined.groupby(["Uke", "merke", "modell"])["pris"]
        .agg(["mean", "count"])
        .reset_index()
        .rename(columns={"merke": "Merke", "modell": "Modell", "mean": "Snittpris", "count": "Antall"})
    )
    grouped["Snittpris"] = grouped["Snittpris"].round(0)
    return grouped.sort_values(["Uke", "Merke", "Modell"])


# Google Sheets sin bubbleChart-type (som ville gitt farge=kategori OG
# størrelse=batteri-kWh i ett og samme diagram) viste seg å avvises av Sheets
# API-en ("ChartData.sourceRange must be set") uansett hvor minimal
# forespørselen var -- ser ut som en kjent svakhet i APIet, ikke en feil i
# forespørselen vår (bekreftet ved at identiske sourceRange-er fungerer fint
# med basicChart). Løsningen under bruker i stedet det ekte, veldokumenterte
# trikset for fargekodede scatter-plott med rene Sheets-diagram: verdien som
# plottes pivoteres til én kolonne PER kategori (delt Kilometerstand-akse) --
# Sheets fargelegger automatisk hver kolonne som egen serie. Kolonner som
# starter med disse prefiksene plukkes opp som egne serier av
# sheets_client.apply_grouped_scatter_charts.
PRICE_SERIES_PREFIX = "Pris ("
REMAINING_VALUE_SERIES_PREFIX = "Kr per gjenværende km ("

# Merk: Google Sheets-diagram har ingen støtte for å klikke på et enkeltpunkt
# og hoppe til en URL -- det finnes rett og slett ikke i deres chart-API.
# "Link"-kolonnen under er kompromisset: samme tabell som diagrammet leser
# fra får en klikkbar Finn-URL per rad (Sheets autolinker URL-tekst), så du
# kan slå opp annonsen fra tabellen rett under/ved siden av diagrammet.


def build_price_vs_km_by_brand(active_df):
    """Én tabell per merke -- Kilometerstand, Modell, Vurdering,
    Regresjonsavvik %, Batteristørrelse, Link (til Finn-annonsen), og én
    "Pris (<batteristørrelse>)"-kolonne per batteristørrelse i merket
    (grunnlag for et fargekodet scatter-diagram per bilmerke). Returnerer en
    dict {merke: DataFrame}, kun for merker med data."""
    if active_df.empty:
        return {}
    subset = active_df.dropna(subset=["pris", "kilometerstand"]).copy()
    subset["Batteristørrelse"] = subset["batteri_kapasitet_kwh"].apply(_battery_bucket)
    result = {}
    for brand in sorted(subset["merke"].dropna().unique()):
        brand_df = subset[subset["merke"] == brand].sort_values("kilometerstand")
        if brand_df.empty:
            continue
        table = brand_df[["kilometerstand", "modell", "deal_label", "regresjon_avvik_pct", "Batteristørrelse", "url"]].rename(
            columns={
                "kilometerstand": "Kilometerstand",
                "modell": "Modell",
                "deal_label": "Vurdering",
                "regresjon_avvik_pct": "Regresjonsavvik %",
                "url": "Link",
            }
        )
        for bucket in sorted(brand_df["Batteristørrelse"].unique()):
            table[f"{PRICE_SERIES_PREFIX}{bucket})"] = brand_df["pris"].where(brand_df["Batteristørrelse"] == bucket)
        result[brand] = table
    return result


def _pivot_value_by_brand_per_drivetrain(active_df, value_col, series_prefix, extra_cols=()):
    """Delt hjelpefunksjon for build_price_vs_km_by_drivetrain og
    build_remaining_value_vs_km_by_drivetrain -- begge har identisk oppsett
    (gruppert på hjuldrift, pivotert på merke), bare med ulik verdikolonne."""
    if active_df.empty:
        return {}
    subset = active_df.dropna(subset=[value_col, "kilometerstand"]).copy()
    subset["Hjuldrift"] = subset["hjuldrift"].apply(drivetrain_category)
    subset = subset.dropna(subset=["Hjuldrift"])
    result = {}
    for category in ("4x4", "2-hjulsdrift"):
        cat_df = subset[subset["Hjuldrift"] == category].sort_values("kilometerstand")
        if cat_df.empty:
            continue
        table = cat_df[["kilometerstand", "merke", "modell", "url", *extra_cols]].rename(
            columns={"kilometerstand": "Kilometerstand", "merke": "Merke", "modell": "Modell", "url": "Link"}
        )
        for brand in sorted(cat_df["merke"].dropna().unique()):
            table[f"{series_prefix}{brand})"] = cat_df[value_col].where(cat_df["merke"] == brand)
        result[category] = table
    return result


def build_price_vs_km_by_drivetrain(active_df):
    """To tabeller ("4x4" og "2-hjulsdrift"), med ALLE merker/modeller samlet
    -- Kilometerstand, Modell, Link, Batteri kWh, og én "Pris (<merke>)"-
    kolonne per merke (grunnlag for et fargekodet scatter-diagram som lar deg
    sammenligne 4x4-biler mot hverandre og 2-hjulsdrevne biler mot hverandre,
    uavhengig av merke). Returnerer dict {kategori: DataFrame}, kun for
    kategorier med data."""
    tables = _pivot_value_by_brand_per_drivetrain(
        active_df, value_col="pris", series_prefix=PRICE_SERIES_PREFIX, extra_cols=["batteri_kapasitet_kwh"]
    )
    return {k: df.rename(columns={"batteri_kapasitet_kwh": "Batteri kWh"}) for k, df in tables.items()}


def build_remaining_value_vs_km_by_drivetrain(active_df):
    """Samme oppsett som build_price_vs_km_by_drivetrain, men med
    "kr per gjenværende km" (se scoring.kr_per_remaining_km) som verdi i
    stedet for rå pris -- to tabeller ("4x4"/"2-hjulsdrift") med én
    "Kr per gjenværende km (<merke>)"-kolonne per merke, grunnlag for et
    fargekodet scatter-diagram (farge=merke) per hjuldrift-kategori."""
    return _pivot_value_by_brand_per_drivetrain(
        active_df, value_col="kr_per_gjenvaerende_km", series_prefix=REMAINING_VALUE_SERIES_PREFIX
    )


def build_model_drivetrain_comparison(active_df, model_pairs):
    """Sammenligner utvalgte merke/modell-par (f.eks. Škoda Enyaq mot VW ID.4)
    brutt ned på hjuldrift-kategori (4x4/2-hjulsdrift), slik at bakhjulsdrift
    kan ses mot bakhjulsdrift og 4x4 mot 4x4. model_pairs: liste av
    (merke, modell-delstreng) -- modell matches som "inneholder", slik at
    varianter som "Enyaq Coupe" også tas med."""
    cols = ["Merke", "Modell", "Hjuldrift", "Antall", "Snitt årsmodell", "Snitt km", "Snittpris", "Snitt kr per gjenværende km"]
    if active_df.empty:
        return pd.DataFrame(columns=cols)

    df = active_df.dropna(subset=["pris"]).copy()
    df["Hjuldrift"] = df["hjuldrift"].apply(drivetrain_category)
    df = df.dropna(subset=["Hjuldrift"])

    mask = pd.Series(False, index=df.index)
    for merke, modell in model_pairs:
        mask |= (df["merke"].str.lower() == merke.lower()) & df["modell"].str.contains(modell, case=False, na=False)
    df = df[mask]
    if df.empty:
        return pd.DataFrame(columns=cols)

    agg_kwargs = {
        "Antall": ("pris", "size"),
        "Snitt årsmodell": ("aarsmodell", "mean"),
        "Snitt km": ("kilometerstand", "mean"),
        "Snittpris": ("pris", "mean"),
        "Snitt kr per gjenværende km": ("kr_per_gjenvaerende_km", "mean"),
    }
    grouped = (
        df.groupby(["merke", "modell", "Hjuldrift"])
        .agg(**agg_kwargs)
        .reset_index()
        .rename(columns={"merke": "Merke", "modell": "Modell"})
    )
    for col in ("Snitt årsmodell", "Snitt km", "Snittpris"):
        grouped[col] = grouped[col].round(0)
    grouped["Snitt kr per gjenværende km"] = grouped["Snitt kr per gjenværende km"].round(2)
    return grouped[cols].sort_values(["Merke", "Modell", "Hjuldrift"])


def build_price_by_year(active_df, history_df):
    """Snittpris per merke/modell/årsmodell -- grunnlag for en depresierings-
    kurve per modell (X=Årsmodell, Y=Snittpris, én serie per Merke+Modell)."""
    cols = ["Merke", "Modell", "Årsmodell", "Snittpris", "Antall"]
    frames = []
    if not active_df.empty:
        frames.append(active_df[["merke", "modell", "aarsmodell", "pris"]])
    if not history_df.empty:
        frames.append(history_df[["merke", "modell", "aarsmodell", "pris"]])
    if not frames:
        return pd.DataFrame(columns=cols)

    combined = pd.concat(frames, ignore_index=True).dropna(subset=["pris", "aarsmodell"])
    if combined.empty:
        return pd.DataFrame(columns=cols)

    grouped = (
        combined.groupby(["merke", "modell", "aarsmodell"])["pris"]
        .agg(["mean", "count"])
        .reset_index()
        .rename(columns={"merke": "Merke", "modell": "Modell", "aarsmodell": "Årsmodell", "mean": "Snittpris", "count": "Antall"})
    )
    grouped["Snittpris"] = grouped["Snittpris"].round(0)
    return grouped.sort_values(["Merke", "Modell", "Årsmodell"])


def build_new_removed_counts(active_df, history_df):
    new_counts = pd.DataFrame(columns=["Uke", "Merke", "Modell", "Nye", "Fjernet"])
    frames = []
    if not active_df.empty:
        new_part = active_df[["merke", "modell", "forste_gang_sett"]].copy()
        new_part["Uke"] = _iso_week(new_part["forste_gang_sett"])
        new_grouped = new_part.groupby(["Uke", "merke", "modell"]).size().reset_index(name="Nye")
        frames.append(new_grouped)
    if not history_df.empty and "fjernet_dato" in history_df.columns:
        removed_part = history_df[["merke", "modell", "fjernet_dato"]].copy()
        removed_part["Uke"] = _iso_week(removed_part["fjernet_dato"])
        removed_grouped = removed_part.groupby(["Uke", "merke", "modell"]).size().reset_index(name="Fjernet")
        frames.append(removed_grouped)
    if not frames:
        return new_counts

    merged = frames[0]
    for frame in frames[1:]:
        merged = merged.merge(frame, on=["Uke", "merke", "modell"], how="outer")
    merged = merged.fillna(0)
    for col in ("Nye", "Fjernet"):
        if col not in merged.columns:
            merged[col] = 0
    return merged.rename(columns={"merke": "Merke", "modell": "Modell"}).sort_values(["Uke", "Merke", "Modell"])


def build_score_distribution(active_df):
    buckets = ["Godt kjøp", "Gjennomsnittlig", "Dyrt", "Ikke nok data"]
    if active_df.empty or "deal_label" not in active_df.columns:
        counts = pd.Series(0, index=buckets)
    else:
        counts = active_df["deal_label"].replace("", "Ikke nok data").value_counts().reindex(buckets, fill_value=0)
    return pd.DataFrame({"Vurdering": counts.index, "Antall": counts.values})
