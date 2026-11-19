import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import pandas as pd
from etl import transform, RAW_COLS

def _raw(rows):
    return pd.DataFrame(rows, columns=RAW_COLS).astype(str).replace("nan", "")

def test_conversion_et_rejets():
    raw = _raw([
        ["S", "20200101", "TMAX", "200", "", "", "W", ""],   # 20.0 °C
        ["S", "20200101", "TMIN", "100", "", "", "W", ""],   # 10.0 °C
        ["S", "20200102", "TMAX", "-9999", "", "", "W", ""], # manquant
        ["S", "20200103", "TMAX", "250", "", "G", "W", ""],  # flag qualité
        ["S", "20200101", "TMAX", "200", "", "", "W", ""],   # doublon
        ["S", "20200104", "TMAX", "9000", "", "", "W", ""],  # aberration (900 °C)
    ])
    clean, st = transform(raw)
    assert st["rows_missing"] == 1
    assert st["rows_quality_flag"] == 1
    assert st["rows_duplicates"] == 1
    assert st["values_outliers"] == 1
    row = clean[clean["date"] == "2020-01-01"].iloc[0]
    assert row["tmax_c"] == 20.0 and row["tmin_c"] == 10.0 and row["tavg_c"] == 15.0


def test_chaine_de_taches(tmp_path, monkeypatch):
    """Plusieurs stations : extract -> transform -> load via fichiers intermédiaires."""
    import tasks, etl
    from prepare_dataset import make_synthetic
    stations = {"AAA": "Ville", "BBB": "Ville"}  # même nom, codes différents
    for st in stations:
        make_synthetic(st, tmp_path / "raw" / f"{st}.csv.gz")
    monkeypatch.setattr(etl, "STATIONS", stations)
    monkeypatch.setattr(etl, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(etl, "PROCESSED_DIR", tmp_path / "out")
    monkeypatch.setattr(tasks, "STAGING", tmp_path / "stg")
    monkeypatch.setattr(tasks, "EXTRACTED", tmp_path / "stg" / "e.csv.gz")
    monkeypatch.setattr(tasks, "TRANSFORMED", tmp_path / "stg" / "t.csv")
    monkeypatch.setattr(tasks, "STATS_FILE", tmp_path / "stg" / "s.json")
    assert tasks.task_extract() > 0
    stats = tasks.task_transform()
    assert set(stats["rows_per_station"]) == {"AAA", "BBB"}
    assert stats["rows_out"] > 4000
    assert pathlib.Path(tasks.task_load()).exists()
    out = pd.read_csv(tmp_path / "out" / "weather_clean.csv")
    assert {"station", "station_name", "city"} <= set(out.columns)


def test_parse_stations_maroc():
    from build_stations import parse_stations
    lines = [
        "MOE00147754  35.1800   -3.8500   27.0    AL HOCEIMA                                  ",
        "MOM00060135  34.0510   -6.7520   84.1    SALE                                   60135",
        "USW00094728  40.7789  -73.9692   39.6 NY NEW YORK CNTRL PK TWR                     72506",
    ]
    assert parse_stations(lines) == {"MOE00147754": "Al Hoceima", "MOM00060135": "Sale"}
