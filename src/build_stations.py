"""Construit le catalogue des stations marocaines depuis ghcnd-stations.txt.

Usage depuis la racine du projet :
    python src/build_stations.py
    python src/build_stations.py chemin/vers/ghcnd-stations.txt

Le fichier stations_morocco.json est écrit à la racine du projet.
"""
import json
import sys
from pathlib import Path
from typing import Iterable

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_FILE = BASE_DIR / "stations_morocco.json"
DEFAULT_SOURCE = BASE_DIR / "ghcnd-stations.txt"


def parse_stations(lines: Iterable[str], country_prefix: str = "MO") -> dict[str, str]:
    """Parse les colonnes fixes du catalogue NOAA (ID: 1-11, NAME: 42-71)."""
    stations: dict[str, str] = {}

    for line_number, line in enumerate(lines, start=1):
        if len(line) < 71:
            continue

        station_id = line[0:11].strip()
        if not station_id.startswith(country_prefix):
            continue

        station_name = line[41:71].strip()
        if not station_id or not station_name:
            continue

        # Conserver le nom fourni par NOAA sans le transformer avec .title().
        stations[station_id] = station_name

    return stations


def main() -> int:
    source = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else DEFAULT_SOURCE
    if not source.is_absolute():
        source = (Path.cwd() / source).resolve()

    if not source.is_file():
        raise FileNotFoundError(
            f"Catalogue NOAA introuvable : {source}\n"
            "Télécharge ghcnd-stations.txt depuis le répertoire GHCN-Daily de NOAA "
            "ou indique son chemin en argument."
        )

    with source.open("r", encoding="ascii", errors="replace") as file:
        stations = parse_stations(file)

    if not stations:
        raise ValueError(
            f"Aucune station avec le préfixe 'MO' trouvée dans {source}. "
            "Vérifie que le fichier fourni est bien ghcnd-stations.txt."
        )

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = OUTPUT_FILE.with_suffix(".json.tmp")
    temporary_file.write_text(
        json.dumps(stations, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_file.replace(OUTPUT_FILE)

    print(f"{len(stations)} stations marocaines écrites dans {OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
