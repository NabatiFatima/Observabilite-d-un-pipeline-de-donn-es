"""Tâche 1 - Exploration de weather_clean.csv (Personne 2 : qualité des données).

Usage (depuis la racine du projet) :
    python quality\\explore.py
    python quality\\explore.py chemin\\vers\\weather_clean.csv

Sorties : affichage console + quality\\exploration_report.txt
          + graphiques dans quality\\figures\\ (si matplotlib est installé)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT = Path("data") / "processed" / "weather_clean.csv"
path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
OUT_DIR = Path("quality")
OUT_DIR.mkdir(exist_ok=True)
REPORT = OUT_DIR / "exploration_report.txt"

lines = []


def out(text=""):
    print(text)
    lines.append(str(text))


def title(t):
    out("\n" + "=" * 70)
    out(t)
    out("=" * 70)


df = pd.read_csv(path, low_memory=False)
df["date"] = pd.to_datetime(df["date"], errors="coerce")
num_cols = [c for c in ["TMAX", "TMIN", "PRCP", "SNOW"] if c in df.columns]

title("1. FORME GENERALE")
out(f"Fichier        : {path}")
out(f"Lignes         : {len(df):,}")
out(f"Colonnes       : {list(df.columns)}")
out(f"Stations       : {df['station'].nunique()}")
out(f"Periode        : {df['date'].min().date()} -> {df['date'].max().date()}")
out(f"Dates invalides: {df['date'].isna().sum()}")

title("2. TYPES DES COLONNES")
out(df.dtypes.to_string())

title("3. VALEURS MANQUANTES (% par colonne)")
out((df.isna().mean() * 100).round(2).to_string())

title("4. DOUBLONS")
out(f"Doublons (station, date) : {df.duplicated(['station', 'date']).sum()}")
out(f"Lignes entierement identiques : {df.duplicated().sum()}")

title("5. STATISTIQUES + PERCENTILES (pour fixer les seuils)")
desc = df[num_cols].describe(percentiles=[.001, .01, .5, .99, .999]).T
out(desc.round(2).to_string())

title("6. COHERENCE ENTRE COLONNES")
if {"TMAX", "TMIN"} <= set(df.columns):
    out(f"TMAX < TMIN : {(df.TMAX < df.TMIN).sum()}")
    amp = (df.TMAX - df.TMIN).dropna()
    out(f"Amplitude thermique jour (TMAX-TMIN) : moy={amp.mean():.1f}  "
        f"p99={amp.quantile(.99):.1f}  max={amp.max():.1f}")
if "PRCP" in df.columns:
    out(f"PRCP < 0 : {(df.PRCP < 0).sum()}")
if "PRCP_TRACE" in df.columns:
    out(f"Jours PRCP_TRACE=True : {int(df.PRCP_TRACE.astype(bool).sum())}")
if "SNOW" in df.columns:
    out(f"SNOW renseigne : {df.SNOW.notna().sum():,} lignes "
        f"({df.SNOW.notna().mean() * 100:.1f} %)")

title("7. PAR STATION : couverture, trous, vides")
rows = []
for st, g in df.groupby("station"):
    g = g.sort_values("date")
    d = g["date"]
    span = (d.max() - d.min()).days + 1
    gaps = d.diff().dt.days.dropna()
    rows.append({
        "station": st,
        "lignes": len(g),
        "debut": d.min().date(),
        "fin": d.max().date(),
        "couverture_%": round(len(g) / span * 100, 1),
        "plus_gros_trou_j": int(gaps.max()) if len(gaps) else 0,
        "TMAX_vide_%": round(g["TMAX"].isna().mean() * 100, 1),
        "TMIN_vide_%": round(g["TMIN"].isna().mean() * 100, 1),
        "PRCP_vide_%": round(g["PRCP"].isna().mean() * 100, 1),
    })
by_station = pd.DataFrame(rows)
out(by_station.to_string(index=False))

title("8. FRAICHEUR : derniere date par station")
last = by_station.sort_values("fin")[["station", "fin"]]
ref = df["date"].max()
last["retard_jours"] = (ref - pd.to_datetime(last["fin"])).dt.days
out(last.to_string(index=False))

title("9. CAPTEUR BLOQUE : plus longue serie de valeurs TMAX identiques")
stuck = []
for st, g in df.sort_values(["station", "date"]).groupby("station"):
    s = g["TMAX"].dropna()
    if s.empty:
        continue
    run = (s != s.shift()).cumsum()
    stuck.append((st, int(run.value_counts().max())))
stuck_df = pd.DataFrame(stuck, columns=["station", "serie_max_identique"])
out(stuck_df.sort_values("serie_max_identique", ascending=False)
    .head(10).to_string(index=False))

title("10. SAISONNALITE : moyenne par mois")
month = df.groupby(df["date"].dt.month)[num_cols].mean().round(1)
month.index.name = "mois"
out(month.to_string())

title("11. VOLUME : lignes par annee")
out(df.groupby(df["date"].dt.year).size().tail(15).to_string())

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig_dir = OUT_DIR / "figures"
    fig_dir.mkdir(exist_ok=True)

    for c in num_cols:
        plt.figure(figsize=(6, 3.5))
        df[c].dropna().hist(bins=60)
        plt.title(f"Distribution de {c}")
        plt.tight_layout()
        plt.savefig(fig_dir / f"hist_{c}.png", dpi=110)
        plt.close()

    plt.figure(figsize=(7, 3.5))
    month["TMAX"].plot(marker="o", label="TMAX")
    month["TMIN"].plot(marker="o", label="TMIN")
    plt.title("Saisonnalite (moyenne par mois)")
    plt.legend()
    plt.tight_layout()
    plt.savefig(fig_dir / "saisonnalite.png", dpi=110)
    plt.close()

    plt.figure(figsize=(8, 3.5))
    df.groupby(df["date"].dt.year).size().plot(kind="bar")
    plt.title("Lignes par annee")
    plt.tight_layout()
    plt.savefig(fig_dir / "volume_par_annee.png", dpi=110)
    plt.close()
    out(f"\nGraphiques enregistres dans {fig_dir}")
except ImportError:
    out("\n(matplotlib absent : pip install matplotlib pour les graphiques)")

REPORT.write_text("\n".join(lines), encoding="utf-8")
out(f"\nRapport enregistre : {REPORT}")