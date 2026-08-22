"""Datastrukturer som går igjen på tvers av modulene."""

from dataclasses import dataclass, field, fields


@dataclass
class Listing:
    """Én bilannonse, slik den lagres som rad i Aktive Annonser / Historikk."""

    finn_id: str
    url: str
    merke: str = ""
    modell: str = ""
    variant: str = ""
    aarsmodell: str = None
    kilometerstand: int = None
    rekkevidde_wltp: int = None  # km, kun relevant for elbiler
    pris: int = None
    drivstoff: str = ""
    girkasse: str = ""
    karosseri: str = ""
    sted: str = ""
    selger_type: str = ""  # "Privat" / "Forhandler" / ""
    forste_gang_sett: str = ""  # ISO-dato, satt av tracker
    sist_sett: str = ""  # ISO-dato, satt av tracker
    mangler_siden: str = ""  # ISO-dato, satt av tracker ved forsvunnet annonse
    deal_score: float = None
    deal_label: str = ""
    fremragende_kjop: bool = False  # skiller seg positivt ut på pris, km OG (for elbil) rekkevidde
    regresjon_avvik_pct: float = None  # % under(-)/over(+) merkets pris-regresjonslinje (år+km+rekkevidde)
    varslet: bool = False

    @staticmethod
    def columns():
        return [f.name for f in fields(Listing)]

    def to_row(self):
        return [getattr(self, c) if getattr(self, c) is not None else "" for c in self.columns()]

    @classmethod
    def from_row(cls, row, columns=None):
        columns = columns or cls.columns()
        data = {}
        for i, col in enumerate(columns):
            if col not in {f.name for f in fields(cls)}:
                continue
            value = row[i] if i < len(row) else ""
            data[col] = value if value != "" else None
        return cls(**{k: v for k, v in data.items() if v is not None or k in ("finn_id", "url")})


@dataclass
class ScoreResult:
    score: float = None
    label: str = "Ikke nok data"
    cohort_size: int = 0
    method: str = "ingen"
