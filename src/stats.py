"""Aggregerer data til de faste tabellene Statistikk-fanens grafer leser fra."""

import pandas as pd


def _iso_week(date_series):
    dates = pd.to_datetime(date_series, errors="coerce")
    return dates.dt.strftime("%G-U%V")


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


def build_price_vs_km_by_brand(active_df):
    """Én tabell per merke (Kilometerstand, Pris, Modell, Vurdering,
    Regresjonsavvik %) -- grunnlag for ett punktdiagram per bilmerke.
    Returnerer en dict {merke: DataFrame}, kun for merker med data."""
    if active_df.empty:
        return {}
    subset = active_df.dropna(subset=["pris", "kilometerstand"])
    result = {}
    for brand in sorted(subset["merke"].dropna().unique()):
        brand_df = subset[subset["merke"] == brand][
            ["kilometerstand", "pris", "modell", "deal_label", "regresjon_avvik_pct"]
        ].sort_values("kilometerstand")
        if brand_df.empty:
            continue
        result[brand] = brand_df.rename(
            columns={
                "kilometerstand": "Kilometerstand",
                "pris": "Pris",
                "modell": "Modell",
                "deal_label": "Vurdering",
                "regresjon_avvik_pct": "Regresjonsavvik %",
            }
        )
    return result


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
