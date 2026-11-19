"""Configuration centrale du pipeline météo NOAA GHCN-Daily."""
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

# Ce fichier est prévu dans src/ : la racine du projet est son dossier parent.
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"

RAW_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

STATIONS_FILE = BASE_DIR / "stations_morocco.json"

# Utilisé uniquement tant que le catalogue complet n'a pas encore été généré.
DEFAULT_STATIONS = {
    "MOM00060135": "SALE",
    "MOE00147754": "AL HOCEIMA",
}


def _load_stations() -> dict[str, str]:
    if not STATIONS_FILE.is_file():
        log.warning(
            "Catalogue %s absent : utilisation de DEFAULT_STATIONS. "
            "Lance src/build_stations.py pour charger toutes les stations.",
            STATIONS_FILE,
        )
        return DEFAULT_STATIONS.copy()

    try:
        data = json.loads(STATIONS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Impossible de lire le catalogue des stations : {STATIONS_FILE}"
        ) from exc

    if not isinstance(data, dict) or not data:
        raise ValueError("stations_morocco.json doit contenir un dictionnaire non vide.")

    invalid = [
        station_id for station_id, name in data.items()
        if not isinstance(station_id, str)
        or len(station_id) != 11
        or not station_id.startswith("MO")
        or not isinstance(name, str)
        or not name.strip()
    ]
    if invalid:
        raise ValueError(
            "Identifiants ou noms de stations invalides dans stations_morocco.json : "
            + ", ".join(map(str, invalid[:10]))
        )

    return {station_id: name.strip() for station_id, name in data.items()}


STATIONS = _load_stations()

# Association manuelle station NOAA -> ville normalisée.
# Les stations absentes de ce dictionnaire conservent leur nom NOAA dans la colonne city.
CITIES = {
    "MO000060156": "Casablanca",
    "MOM00060155": "Casablanca",
    "MOW00013019": "Casablanca",
    "MO000060195": "Midelt",
    "MO000060265": "Ouarzazate",
    "MOE00147752": "Tanger",
    "MOE00147753": "Tanger",
    "MOE00147754": "Al Hoceima",
    "MOE00147755": "Oujda",
    "MOE00147756": "Tetouan",
    "MOM00060318": "Tetouan",
    "MOM00060135": "Sale",
    "MOM00060150": "Meknes",
    "MOM00060220": "Essaouira",
    "MOM00060230": "Marrakech",
    "MOW00013017": "Kenitra",
    "MOW00013020": "Sidi Slimane",
    "MOW00013022": "Ben Slimane",
    "MOW00013023": "Benguerir",
}

NOAA_URL = (
    "https://www.ncei.noaa.gov/pub/data/ghcn/daily/"
    "by_station/{station}.csv.gz"
)

ELEMENTS = ("TMAX", "TMIN", "PRCP", "SNOW")

# Bornes appliquées après conversion en °C et mm.
VALID_RANGES = {
    "tmax_c": (-60.0, 60.0),
    "tmin_c": (-70.0, 50.0),
    "prcp_mm": (0.0, 1000.0),
    "snow_mm": (0.0, 2000.0),
}
