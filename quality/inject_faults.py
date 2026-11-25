"""Tâche 2 (suite) - Injection de défauts pour prouver que les règles détectent les problèmes.

Le fichier de Fatima n'est JAMAIS modifié : chaque défaut est écrit dans une COPIE
rangée dans data\\faulty\\weather_<defaut>.csv

Usage (racine du projet, .venv actif) :
    python quality\\inject_faults.py --liste             # voir les défauts disponibles
    python quality\\inject_faults.py --defaut doublons    # créer UNE copie abîmée
    python quality\\inject_faults.py --tous               # créer toutes les copies
    python quality\\inject_faults.py --verifier           # créer + contrôler + dire si c'est détecté
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SOURCE = Path("data") / "processed" / "weather_clean.csv"
OUT_DIR = Path("data") / "faulty"
CHECKER = Path("quality") / "ge_checks.py"
QUALITY_DIR = Path("quality")
SEED = 42


# --------------------------------------------------------------------- défauts
def doublons(df, rng):
    """50 lignes dupliquées (ex. : un téléchargement fait deux fois)."""
    return pd.concat([df, df.sample(50, random_state=SEED)], ignore_index=True)


def temperature_aberrante(df, rng):
    """20 valeurs TMAX à 99 °C (ex. : un capteur qui déraille)."""
    idx = rng.choice(df.index[df["TMAX"].notna()], 20, replace=False)
    df.loc[idx, "TMAX"] = 99.0
    return df


def tmax_inferieur_tmin(df, rng):
    """30 lignes où TMAX et TMIN sont inversées (ex. : erreur d'inversion)."""
    ok = df.index[df["TMAX"].notna() & df["TMIN"].notna() & (df["TMAX"] > df["TMIN"])]
    idx = rng.choice(ok, 30, replace=False)
    df.loc[idx, ["TMAX", "TMIN"]] = df.loc[idx, ["TMIN", "TMAX"]].values
    return df


def date_future(df, rng):
    """10 lignes datées en 2030 (ex. : horloge mal réglée)."""
    idx = rng.choice(df.index, 10, replace=False)
    df.loc[idx, "date"] = pd.Timestamp("2030-01-01") + pd.to_timedelta(np.arange(10), "D")
    return df


def tmin_vides(df, rng):
    """TMIN vide sur 50 % des lignes (ex. : un capteur en panne)."""
    extra = int((0.50 - df["TMIN"].isna().mean()) * len(df))
    idx = rng.choice(df.index[df["TMIN"].notna()], max(extra, 0), replace=False)
    df.loc[idx, "TMIN"] = np.nan
    return df


def capteur_bloque(df, rng):
    """30 relevés consécutifs avec TMAX = 25.0 (ex. : un capteur bloqué)."""
    station = df["station"].value_counts().idxmax()
    g = df[df["station"] == station].sort_values("date")
    idx = g.index[len(g) // 2: len(g) // 2 + 30]
    df.loc[idx, "TMAX"] = 25.0
    df.loc[idx[df.loc[idx, "TMIN"] > 25.0], "TMIN"] = np.nan  # garde TMAX >= TMIN
    return df


def station_supprimee(df, rng):
    """Toutes les lignes d'une station supprimées (ex. : une station qui n'émet plus)."""
    last = df.groupby("station")["date"].max()
    inactive = last[last < pd.Timestamp.now() - pd.Timedelta(days=30)].index
    pool = df[df["station"].isin(inactive)] if len(inactive) else df
    station = pool["station"].value_counts().idxmax()
    return df[df["station"] != station].copy()


def volume_baisse(df, rng):
    """10 % des lignes supprimées au hasard (ex. : un chargement incomplet)."""
    return df.drop(rng.choice(df.index, int(0.10 * len(df)), replace=False))


# nom : (fonction, règle qui doit réagir, description courte)
FAULTS = {
    "doublons": (doublons, "R01", "lignes dupliquées"),
    "temperature_aberrante": (temperature_aberrante, "R04", "TMAX = 99 °C"),
    "tmax_inferieur_tmin": (tmax_inferieur_tmin, "R07", "TMAX < TMIN"),
    "date_future": (date_future, "R03", "dates en 2030"),
    "tmin_vides": (tmin_vides, "R10", "50 % de TMIN vides"),
    "capteur_bloque": (capteur_bloque, "R15", "30 jours de TMAX identiques"),
    "station_supprimee": (station_supprimee, "R13", "une station en moins"),
    "volume_baisse": (volume_baisse, "R16", "10 % de lignes en moins"),
}


# ------------------------------------------------------------------- utilitaires
def load_source():
    if not SOURCE.exists():
        sys.exit(f"Fichier introuvable : {SOURCE}. Lancez d'abord le DAG, depuis la racine du projet.")
    df = pd.read_csv(SOURCE, low_memory=False)
    df["date"] = pd.to_datetime(df["date"])
    return df


def create(name):
    func, rule, desc = FAULTS[name]
    df = func(load_source(), np.random.default_rng(SEED))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"weather_{name}.csv"
    df.to_csv(path, index=False, date_format="%Y-%m-%d")
    print(f"  cree : {path}   ({desc}, doit déclencher {rule})")
    return path


def run_checker(path=None):
    cmd = [sys.executable, str(CHECKER)] + ([str(path)] if path else [])
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env)


def verify():
    print("1) Contrôle de référence sur les vraies données (sert de base à la règle R16)...")
    base = run_checker()
    if base.returncode not in (0, 1):
        sys.exit("ge_checks.py a échoué :\n" + base.stderr[-1500:])
    print("2) Création et contrôle de chaque copie abîmée...\n")
    rows, all_ok = [], True
    for name, (_, rule, desc) in FAULTS.items():
        path = create(name)
        proc = run_checker(path)
        report_file = QUALITY_DIR / f"ge_report_{path.stem}.json"
        if not report_file.exists():
            rows.append((name, rule, "ERREUR", proc.stderr[-200:].strip()))
            all_ok = False
            continue
        res = {r["id"]: r for r in json.loads(report_file.read_text(encoding="utf-8"))["resultats"]}
        detected = not res[rule]["reussie"]
        all_ok &= detected
        rows.append((name, rule, "DETECTE" if detected else "NON DETECTE", desc))
    print("\n" + "=" * 78)
    print(f"{'Défaut injecté':<24}{'Règle':<8}{'Résultat':<14}Description")
    print("=" * 78)
    for r in rows:
        print(f"{r[0]:<24}{r[1]:<8}{r[2]:<14}{r[3]}")
    print("=" * 78)
    print("Tous les défauts sont détectés." if all_ok else "Au moins un défaut n'est pas détecté : voir ci-dessus.")
    sys.exit(0 if all_ok else 1)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--liste", action="store_true", help="afficher les défauts disponibles")
    p.add_argument("--defaut", choices=FAULTS, help="créer une seule copie abîmée")
    p.add_argument("--tous", action="store_true", help="créer toutes les copies abîmées")
    p.add_argument("--verifier", action="store_true", help="créer, contrôler et vérifier la détection")
    a = p.parse_args()

    if a.liste:
        for n, (_, rule, desc) in FAULTS.items():
            print(f"  {n:<24}{rule:<6}{desc}")
    elif a.defaut:
        create(a.defaut)
    elif a.tous:
        for n in FAULTS:
            create(n)
    elif a.verifier:
        verify()
    else:
        p.print_help()


if __name__ == "__main__":
    main()