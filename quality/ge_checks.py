"""Tâche 2 - Tests de qualité (Great Expectations 1.x) sur weather_clean.csv.

Usage (depuis la racine du projet, environnement .venv actif) :
    python quality\\ge_checks.py
    python quality\\ge_checks.py chemin\\vers\\weather_clean.csv

Sorties :
    - tableau réussi / échoué dans la console
    - quality\\ge_report.json  (lu plus tard par Prometheus / Alertmanager)
    - code de sortie 1 si une règle BLOQUANTE échoue, 0 sinon
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import great_expectations as gx
import great_expectations.expectations as gxe

# ----------------------------------------------------------------- paramètres
DEFAULT_PATH = Path("data") / "processed" / "weather_clean.csv"
OUT_DIR = Path("quality")
REPORT_FILE = OUT_DIR / "ge_report.json"

EXPECTED_STATIONS = 20          # 20 fichiers dans data/raw lors de l'exploration
ACTIVE_DAYS = 30                # une station est "active" si sa dernière date a <= 30 jours
MIN_ACTIVE_STATIONS = 2         # 2 stations actives observées
MAX_FRESHNESS_DAYS = 30         # retard maximal du dataset
MAX_STUCK_DAYS = 15             # série max de TMAX identiques (observé : 10)
MIN_ROWS_RATIO = 0.99           # le volume ne doit pas baisser de plus de 1 % entre 2 runs

BLOCKING, WARNING = "bloquante", "avertissement"


# ------------------------------------------------------- calculs préparatoires
def longest_run(series: pd.Series) -> int:
    s = series.dropna()
    if s.empty:
        return 0
    return int((s.groupby((s != s.shift()).cumsum()).size()).max())


def build_summary(df: pd.DataFrame, previous_rows) -> dict:
    """Indicateurs de niveau 'dataset' (une seule valeur chacun)."""
    today = pd.Timestamp.now().normalize()
    last_by_station = df.groupby("station")["date"].max()
    stuck = max(
        (longest_run(g["TMAX"]) for _, g in df.sort_values("date").groupby("station")),
        default=0,
    )
    return {
        "retard_dataset_jours": int((today - df["date"].max()).days),
        "nb_stations": int(df["station"].nunique()),
        "nb_stations_actives": int(((today - last_by_station).dt.days <= ACTIVE_DAYS).sum()),
        "serie_max_tmax_identique": int(stuck),
        "ratio_lignes_vs_run_precedent": (
            round(len(df) / previous_rows, 4) if previous_rows else 1.0
        ),
    }


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    # Colonnes dérivées : permettent d'utiliser des règles simples et robustes.
    df["amplitude_jour"] = df["TMAX"] - df["TMIN"]          # NaN si l'une des deux manque
    df["age_jours"] = (pd.Timestamp.now().normalize() - df["date"]).dt.days  # < 0 => date future
    return df


# ------------------------------------------------------------------- les règles
# (id, description, gravité, expectation)
def row_rules():
    return [
        ("R01", "Pas de doublon (station, date)", BLOCKING,
         gxe.ExpectCompoundColumnsToBeUnique(column_list=["station", "date"])),
        ("R02", "Date valide (non vide)", BLOCKING,
         gxe.ExpectColumnValuesToNotBeNull(column="date")),
        ("R03", "Date pas dans le futur", BLOCKING,
         gxe.ExpectColumnValuesToBeBetween(column="age_jours", min_value=0)),
        ("R04", "TMAX entre -10 et 55 °C", BLOCKING,
         gxe.ExpectColumnValuesToBeBetween(column="TMAX", min_value=-10, max_value=55)),
        ("R05", "TMIN entre -20 et 40 °C", BLOCKING,
         gxe.ExpectColumnValuesToBeBetween(column="TMIN", min_value=-20, max_value=40)),
        ("R06", "PRCP entre 0 et 300 mm", BLOCKING,
         gxe.ExpectColumnValuesToBeBetween(column="PRCP", min_value=0, max_value=300)),
        ("R07", "TMAX >= TMIN (amplitude >= 0)", BLOCKING,
         gxe.ExpectColumnValuesToBeBetween(column="amplitude_jour", min_value=0)),
        ("R08", "Amplitude journalière <= 40 °C", WARNING,
         gxe.ExpectColumnValuesToBeBetween(column="amplitude_jour", max_value=40)),
        ("R09", "TMAX : au plus 25 % de vides", WARNING,
         gxe.ExpectColumnValuesToNotBeNull(column="TMAX", mostly=0.75)),
        ("R10", "TMIN : au plus 30 % de vides", WARNING,
         gxe.ExpectColumnValuesToNotBeNull(column="TMIN", mostly=0.70)),
        ("R11", "PRCP : au plus 35 % de vides", WARNING,
         gxe.ExpectColumnValuesToNotBeNull(column="PRCP", mostly=0.65)),
    ]


def summary_rules():
    return [
        ("R12", f"Retard du dataset <= {MAX_FRESHNESS_DAYS} jours", WARNING,
         gxe.ExpectColumnValuesToBeBetween(column="retard_dataset_jours", max_value=MAX_FRESHNESS_DAYS),
         "retard_dataset_jours"),
        ("R13", f"Nombre de stations = {EXPECTED_STATIONS}", WARNING,
         gxe.ExpectColumnValuesToBeBetween(column="nb_stations",
                                           min_value=EXPECTED_STATIONS, max_value=EXPECTED_STATIONS),
         "nb_stations"),
        ("R14", f"Au moins {MIN_ACTIVE_STATIONS} stations actives", WARNING,
         gxe.ExpectColumnValuesToBeBetween(column="nb_stations_actives", min_value=MIN_ACTIVE_STATIONS),
         "nb_stations_actives"),
        ("R15", f"Capteur bloqué : série TMAX identique <= {MAX_STUCK_DAYS} jours", WARNING,
         gxe.ExpectColumnValuesToBeBetween(column="serie_max_tmax_identique", max_value=MAX_STUCK_DAYS),
         "serie_max_tmax_identique"),
        ("R16", f"Volume >= {int(MIN_ROWS_RATIO * 100)} % du run précédent", WARNING,
         gxe.ExpectColumnValuesToBeBetween(column="ratio_lignes_vs_run_precedent", min_value=MIN_ROWS_RATIO),
         "ratio_lignes_vs_run_precedent"),
    ]


# ---------------------------------------------------------- exécution via GE
def make_validator(context, name: str, frame: pd.DataFrame):
    source = context.data_sources.add_pandas(f"src_{name}")
    asset = source.add_dataframe_asset(name=f"asset_{name}")
    batch_def = asset.add_batch_definition_whole_dataframe(f"batch_{name}")
    return batch_def.get_batch(batch_parameters={"dataframe": frame})


def run_rule(batch, expectation):
    res = batch.validate(expectation)
    detail = res.result or {}
    return bool(res.success), {
        "lignes_testees": detail.get("element_count"),
        "violations": detail.get("unexpected_count"),
        "violations_%": detail.get("unexpected_percent"),
    }


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PATH
    OUT_DIR.mkdir(exist_ok=True)

    # Le rapport de référence (ge_report.json) n'est écrit que pour les vraies données.
    # Une copie abîmée (data\\faulty\\...) écrit son propre rapport : la référence reste intacte.
    report_file = REPORT_FILE if path == DEFAULT_PATH else OUT_DIR / f"ge_report_{path.stem}.json"

    previous_rows = None
    if REPORT_FILE.exists():
        try:
            previous_rows = json.loads(REPORT_FILE.read_text(encoding="utf-8")).get("lignes")
        except (OSError, ValueError):
            previous_rows = None

    df = prepare(pd.read_csv(path, low_memory=False))
    summary = build_summary(df, previous_rows)

    context = gx.get_context(mode="ephemeral")
    batch_rows = make_validator(context, "lignes", df)
    batch_sum = make_validator(context, "resume", pd.DataFrame([summary]))

    results = []
    for rid, desc, severity, exp in row_rules():
        ok, obs = run_rule(batch_rows, exp)
        results.append({"id": rid, "regle": desc, "gravite": severity, "reussie": ok, "observe": obs})
    for rid, desc, severity, exp, key in summary_rules():
        ok, _ = run_rule(batch_sum, exp)
        results.append({"id": rid, "regle": desc, "gravite": severity, "reussie": ok,
                        "observe": {"valeur": summary[key]}})

    blocking_failed = sum(1 for r in results if not r["reussie"] and r["gravite"] == BLOCKING)
    warning_failed = sum(1 for r in results if not r["reussie"] and r["gravite"] == WARNING)

    report = {
        "date_controle": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fichier": str(path),
        "lignes": int(len(df)),
        "regles_total": len(results),
        "regles_reussies": sum(r["reussie"] for r in results),
        "bloquantes_echouees": blocking_failed,
        "avertissements_echoues": warning_failed,
        "resume": summary,
        "resultats": results,
    }
    report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nContrôle qualité : {path}  ({len(df):,} lignes)\n")
    for r in results:
        mark = "OK    " if r["reussie"] else ("ECHEC " if r["gravite"] == BLOCKING else "ALERTE")
        print(f"[{mark}] {r['id']}  {r['regle']:<58} {r['observe']}")
    print(f"\nRègles réussies : {report['regles_reussies']}/{report['regles_total']}  |  "
          f"bloquantes échouées : {blocking_failed}  |  avertissements : {warning_failed}")
    print(f"Rapport : {report_file}")
    sys.exit(1 if blocking_failed else 0)


if __name__ == "__main__":
    main()