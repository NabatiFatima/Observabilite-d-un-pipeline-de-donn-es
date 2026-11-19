"""Télécharge les fichiers réels NOAA GHCN-Daily pour les stations configurées.

Usage depuis la racine du projet :
    python src/prepare_dataset.py
    python src/prepare_dataset.py --station MOM00060135
    python src/prepare_dataset.py --force
"""
import argparse
import gzip
import logging
import shutil
from pathlib import Path

import requests

from config import NOAA_URL, RAW_DIR, STATIONS

log = logging.getLogger("prepare_dataset")


def _validate_gzip_csv(path: Path) -> None:
    """Vérifie le format CSV à 8 champs et lit tout le flux pour contrôler le CRC gzip."""
    with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
        first_line = stream.readline()
        if not first_line:
            raise IOError(f"Le fichier NOAA est vide : {path}")
        if len(first_line.rstrip("\\r\\n").split(",")) != 8:
            raise IOError(f"Format CSV NOAA inattendu (8 champs attendus) : {path}")
        # Lire jusqu'à la fin permet aussi de détecter une archive gzip tronquée/corrompue.
        while stream.read(1024 * 1024):
            pass


def download_noaa(station: str, dest: Path, force: bool = False) -> Path:
    """Télécharge et vérifie le CSV gzip d'une station NOAA."""
    if not station.startswith("MO") or len(station) != 11:
        raise ValueError(f"Identifiant de station marocain invalide : {station}")

    if dest.exists() and dest.stat().st_size > 0 and not force:
        # Ne pas retélécharger inutilement un fichier déjà présent.
        try:
            _validate_gzip_csv(dest)
            log.info("Fichier déjà présent et gzip valide : %s", dest)
            return dest
        except (OSError, EOFError):
            log.warning("Fichier local invalide, nouveau téléchargement : %s", dest)

    url = NOAA_URL.format(station=station)
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_suffix(dest.suffix + ".part")

    try:
        with requests.get(
            url,
            stream=True,
            timeout=(15, 120),
            headers={"User-Agent": "weather-data-pipeline/1.0"},
        ) as response:
            response.raise_for_status()
            with temporary.open("wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        output.write(chunk)

        if not temporary.exists() or temporary.stat().st_size == 0:
            raise IOError(f"Réponse NOAA vide pour la station {station}")

        # Vérifier l'intégrité gzip avant de remplacer le fichier final.
        _validate_gzip_csv(temporary)

        temporary.replace(dest)
        log.info("Téléchargement terminé : %s (%.1f Ko)", dest, dest.stat().st_size / 1024)
        return dest

    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--station",
        help="Télécharger une seule station (par défaut : toutes les stations configurées).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Retélécharger même si un fichier gzip valide existe déjà.",
    )
    args = parser.parse_args()

    if args.station:
        if args.station not in STATIONS:
            parser.error(
                f"{args.station} n'est pas dans STATIONS. "
                "Génère d'abord le catalogue ou vérifie l'identifiant."
            )
        stations = [args.station]
    else:
        stations = list(STATIONS)

    failed = []
    for station in stations:
        destination = RAW_DIR / f"{station}.csv.gz"
        try:
            download_noaa(station, destination, force=args.force)
        except (requests.RequestException, OSError, ValueError) as exc:
            failed.append(station)
            log.error("Échec de téléchargement pour %s : %s", station, exc)

    succeeded = len(stations) - len(failed)
    log.info("Téléchargement terminé : %d/%d stations réussies.", succeeded, len(stations))

    if failed:
        log.error("Stations en échec : %s", ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    raise SystemExit(main())
