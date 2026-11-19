
"""ETL des données météorologiques NOAA GHCN-Daily.

Extraction : lecture des fichiers CSV.GZ NOAA.
Transformation : filtrage, nettoyage, conversion et validation.
Chargement : écriture du dataset nettoyé en CSV.
"""

import logging
from pathlib import Path

import pandas as pd

from config import RAW_DIR, PROCESSED_DIR

logger = logging.getLogger(__name__)

# Structure officielle des lignes GHCN-Daily.
COLUMNS = [
    "station",
    "date",
    "element",
    "value",
    "m_flag",
    "q_flag",
    "s_flag",
    "obs_time",
]

# Éléments météorologiques utilisés.
ELEMENTS = ["TMAX", "TMIN", "PRCP", "SNOW"]

# Valeurs limites après conversion des unités NOAA.
VALID_RANGES = {
    "TMAX": (-90, 60),
    "TMIN": (-90, 60),
    "PRCP": (0, 2000),
    "SNOW": (0, 5000),
}

OUTPUT_FILE = PROCESSED_DIR / "weather_clean.csv"


def extract() -> pd.DataFrame:
    """Lit et rassemble les fichiers NOAA téléchargés."""

    files = sorted(RAW_DIR.glob("*.csv.gz"))

    if not files:
        raise FileNotFoundError(
            f"Aucun fichier NOAA trouvé dans {RAW_DIR}"
        )

    dataframes = []

    for file_path in files:
        logger.info("Lecture du fichier : %s", file_path.name)

        df = pd.read_csv(
            file_path,
            compression="gzip",
            header=None,
            names=COLUMNS,
            dtype=str,
        )

        dataframes.append(df)

    raw = pd.concat(dataframes, ignore_index=True)

    logger.info("%s observations extraites", len(raw))

    return raw


def transform(raw: pd.DataFrame):
    """Nettoie et transforme les observations météorologiques."""

    stats = {
        "input_rows": int(len(raw)),
        "invalid_dates": 0,
        "invalid_elements": 0,
        "quality_rejected": 0,
        "missing_values": 0,
        "out_of_range": 0,
        "duplicates": 0,
        "invalid_temperature_pairs": 0,
        "output_rows": 0,
    }

    df = raw.copy()

    # 1. Normalisation des champs textuels.
    for column in COLUMNS:
        df[column] = df[column].fillna("").astype(str).str.strip()

    # 2. Conserver uniquement les éléments sélectionnés.
    before = len(df)
    df = df[df["element"].isin(ELEMENTS)].copy()
    stats["invalid_elements"] = int(before - len(df))

    # 3. Vérifier les dates.
    df["date"] = pd.to_datetime(
        df["date"],
        format="%Y%m%d",
        errors="coerce",
    )

    before = len(df)
    df = df.dropna(subset=["date"])
    stats["invalid_dates"] = int(before - len(df))

    # 4. Rejeter les observations ayant un indicateur qualité NOAA.
    before = len(df)
    df = df[df["q_flag"] == ""].copy()
    stats["quality_rejected"] = int(before - len(df))

    # 5. Convertir les valeurs numériques.
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    before = len(df)
    df = df.dropna(subset=["value"])
    stats["missing_values"] = int(before - len(df))

    # -9999 est le code NOAA pour une valeur manquante.
    before = len(df)
    df = df[df["value"] != -9999].copy()
    stats["missing_values"] += int(before - len(df))

    # 6. Conversion des unités.
    # TMAX, TMIN et PRCP sont exprimés en dixièmes
    # de degré Celsius ou de millimètre dans les fichiers NOAA.
    mask = df["element"].isin(["TMAX", "TMIN", "PRCP"])
    df.loc[mask, "value"] = df.loc[mask, "value"] / 10.0

    # SNOW est conservé en millimètres.

    # 7. Contrôle des valeurs aberrantes.
    valid = pd.Series(True, index=df.index)

    for element, (minimum, maximum) in VALID_RANGES.items():
        element_mask = df["element"] == element

        valid.loc[element_mask] = (
            df.loc[element_mask, "value"].between(minimum, maximum)
        )

    stats["out_of_range"] = int((~valid).sum())
    df = df[valid].copy()

    # 8. Identifier les précipitations à l'état de trace.
    # M_FLAG = T indique une observation de trace.
    df["trace"] = (
        (df["element"] == "PRCP") &
        (df["m_flag"] == "T")
    )

    # Une précipitation de trace est représentée par 0 mm
    # avec un indicateur PRCP_TRACE = True.
    df.loc[df["trace"], "value"] = 0.0

    # 9. Éliminer les doublons.
    duplicate_columns = ["station", "date", "element"]

    stats["duplicates"] = int(
        df.duplicated(subset=duplicate_columns).sum()
    )

    df = df.drop_duplicates(
        subset=duplicate_columns,
        keep="first",
    )

    # 10. Transformer le format long en format large.
    values = df.pivot(
        index=["station", "date"],
        columns="element",
        values="value",
    )

    values.columns.name = None
    values = values.reset_index()

    # Indicateur des précipitations de trace.
    trace_df = (
        df[df["element"] == "PRCP"]
        .groupby(["station", "date"])["trace"]
        .any()
        .rename("PRCP_TRACE")
        .reset_index()
    )

    clean = values.merge(
        trace_df,
        on=["station", "date"],
        how="left",
    )

    clean["PRCP_TRACE"] = (
        clean["PRCP_TRACE"].fillna(False).astype(bool)
    )

    # Ajouter les colonnes absentes si un élément n'est pas disponible.
    for element in ELEMENTS:
        if element not in clean.columns:
            clean[element] = pd.NA

    # 11. Vérifier la cohérence entre températures.
    invalid_pairs = (
        clean["TMAX"].notna()
        & clean["TMIN"].notna()
        & (clean["TMAX"] < clean["TMIN"])
    )

    stats["invalid_temperature_pairs"] = int(invalid_pairs.sum())

    clean = clean[~invalid_pairs].copy()

    # 12. Organiser les colonnes.
    clean = clean[
        [
            "station",
            "date",
            "TMAX",
            "TMIN",
            "PRCP",
            "PRCP_TRACE",
            "SNOW",
        ]
    ]

    clean = clean.sort_values(
        ["station", "date"]
    ).reset_index(drop=True)

    stats["output_rows"] = int(len(clean))

    if clean.empty:
        raise ValueError(
            "Le dataset est vide après le nettoyage."
        )

    return clean, stats


def load(clean: pd.DataFrame) -> Path:
    """Enregistre le dataset nettoyé."""

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    clean.to_csv(
        OUTPUT_FILE,
        index=False,
        date_format="%Y-%m-%d",
    )

    logger.info(
        "Dataset chargé : %s (%s lignes)",
        OUTPUT_FILE,
        len(clean),
    )

    return OUTPUT_FILE


def main():
    """Exécution complète de l'ETL en mode autonome."""

    logging.basicConfig(level=logging.INFO)

    raw = extract()
    clean, stats = transform(raw)
    output = load(clean)

    logger.info("Statistiques ETL : %s", stats)
    logger.info("Fichier final : %s", output)


if __name__ == "__main__":
    main()
