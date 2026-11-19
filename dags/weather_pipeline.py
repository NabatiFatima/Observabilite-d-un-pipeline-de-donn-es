
"""DAG Airflow du pipeline météo NOAA GHCN-Daily."""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

from tasks import (
    task_download,
    task_extract,
    task_transform,
    task_load,
)


default_args = {
    "owner": "fatima",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=2),
}


with DAG(
    dag_id="weather_pipeline",
    description="Pipeline ETL automatisé des données météo NOAA",
    start_date=datetime(2026, 11, 1),
    schedule="@daily",
    catchup=False,
    default_args=default_args,
    tags=["NOAA", "Weather", "ETL"],
) as dag:

    download = PythonOperator(
        task_id="download_noaa",
        python_callable=task_download,
    )

    extract = PythonOperator(
        task_id="extract",
        python_callable=task_extract,
    )

    transform = PythonOperator(
        task_id="transform",
        python_callable=task_transform,
    )

    load = PythonOperator(
        task_id="load",
        python_callable=task_load,
    )

    download >> extract >> transform >> load
