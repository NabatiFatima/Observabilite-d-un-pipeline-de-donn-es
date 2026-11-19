
"""Fonctions des tâches Airflow du pipeline météo NOAA."""

import logging
import json

import pandas as pd

from config import BASE_DIR, RAW_DIR, PROCESSED_DIR, STATIONS
from prepare_dataset import download_noaa
import etl

logger = logging.getLogger(__name__)

# Fichiers intermédiaires
STAGING_DIR = BASE_DIR / "data" / "staging"

EXTRACTED_FILE = STAGING_DIR / "extracted.csv.gz"
TRANSFORMED_FILE = STAGING_DIR / "transformed.csv"
STATS_FILE = STAGING_DIR / "stats.json"


def task_download():
    """Télécharge les données météo des stations NOAA."""

    logger.info("Début du téléchargement NOAA")

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    successful = []
    failed = []

    for station in STATIONS:
        output_file = RAW_DIR / f"{station}.csv.gz"

        try:
            download_noaa(station, output_file)

            if not output_file.exists() or output_file.stat().st_size == 0:
                raise RuntimeError("Fichier téléchargé vide ou absent")

            successful.append(station)

            logger.info("Téléchargement réussi : %s", station)

        except Exception:
            failed.append(station)
            logger.exception("Échec du téléchargement : %s", station)

    if not successful:
        raise RuntimeError("Aucune station NOAA téléchargée avec succès")

    logger.info(
        "Téléchargement terminé : %s réussies, %s échouées",
        len(successful),
        len(failed),
    )

    return {
        "successful": successful,
        "failed": failed,
    }


def task_extract():
    """Extrait les observations depuis les fichiers NOAA."""

    logger.info("Début de l'extraction")

    STAGING_DIR.mkdir(parents=True, exist_ok=True)

    raw = etl.extract()

    if raw.empty:
        raise ValueError("Aucune observation extraite")

    raw.to_csv(
        EXTRACTED_FILE,
        index=False,
        compression="gzip",
    )

    logger.info("%s observations extraites", len(raw))

    return {
        "rows_extracted": int(len(raw)),
        "file": str(EXTRACTED_FILE),
    }


def task_transform():
    """Nettoie et transforme les observations."""

    logger.info("Début de la transformation")

    if not EXTRACTED_FILE.exists():
        raise FileNotFoundError(
            f"Fichier extrait introuvable : {EXTRACTED_FILE}"
        )

    raw = pd.read_csv(
        EXTRACTED_FILE,
        compression="gzip",
        dtype=str,
    )

    clean, stats = etl.transform(raw)

    clean.to_csv(
        TRANSFORMED_FILE,
        index=False,
        date_format="%Y-%m-%d",
    )

    STATS_FILE.write_text(
        json.dumps(stats, indent=4),
        encoding="utf-8",
    )

    logger.info("Transformation terminée : %s", stats)

    return {
        "rows_transformed": int(len(clean)),
        "stats": stats,
    }


def task_load():
    """Charge le dataset nettoyé dans le fichier final."""

    logger.info("Début du chargement")

    if not TRANSFORMED_FILE.exists():
        raise FileNotFoundError(
            f"Fichier transformé introuvable : {TRANSFORMED_FILE}"
        )

    clean = pd.read_csv(
        TRANSFORMED_FILE,
        parse_dates=["date"],
    )

    if clean.empty:
        raise ValueError("Le dataset transformé est vide")

    output = etl.load(clean)

    logger.info("Chargement terminé : %s", output)

    return {
        "output_file": str(output),
        "rows_loaded": int(len(clean)),
    }
