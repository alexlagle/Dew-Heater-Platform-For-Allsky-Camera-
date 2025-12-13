"""CSV logging helpers for sensor readings and relay events."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path

from .config import LOG_DIR


def ensure_log_header(path: Path, header: list[str]):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(header)


def event_log_path(now: datetime) -> Path:
    return LOG_DIR / f"dew_heater_events_{now.strftime('%Y-%m-%d')}.csv"


def readings_log_path(now: datetime) -> Path:
    return LOG_DIR / f"dew_heater_readings_{now.strftime('%Y-%m-%d')}.csv"


def log_event(path: Path, timestamp: str, temp_c: float, humidity: float, dew_c: float, state_on: bool):
    ensure_log_header(path, ["timestamp_iso", "temp_c", "humidity_pct", "dew_point_c", "relay_state"])
    with path.open("a", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow([timestamp, f"{temp_c:.1f}", f"{humidity:.1f}", f"{dew_c:.1f}", "on" if state_on else "off"])


def log_reading(path: Path, timestamp: str, temp_c: float, humidity: float, dew_c: float, relay_on: bool):
    ensure_log_header(path, ["timestamp_iso", "temp_c", "humidity_pct", "dew_point_c", "relay_state"])
    with path.open("a", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow([timestamp, f"{temp_c:.1f}", f"{humidity:.1f}", f"{dew_c:.1f}", "on" if relay_on else "off"])


def load_readings_range(start_dt: datetime, end_dt: datetime) -> list[dict]:
    """Load readings from CSV logs within the inclusive [start_dt, end_dt] range."""
    records: list[dict] = []
    current_day = start_dt.date()
    end_day = end_dt.date()

    while current_day <= end_day:
        log_path = LOG_DIR / f"dew_heater_readings_{current_day.isoformat()}.csv"
        if log_path.exists():
            with log_path.open("r", newline="") as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    ts_raw = row.get("timestamp_iso")
                    if not ts_raw:
                        continue
                    try:
                        ts = datetime.fromisoformat(ts_raw)
                    except ValueError:
                        continue
                    if not (start_dt <= ts <= end_dt):
                        continue
                    try:
                        temp = float(row["temp_c"])
                        humidity = float(row["humidity_pct"])
                        dew = float(row["dew_point_c"])
                    except (ValueError, KeyError):
                        continue
                    relay_raw = (row.get("relay_state") or "").strip().lower()
                    records.append(
                        {
                            "timestamp": ts.isoformat(),
                            "temp_c": temp,
                            "humidity_pct": humidity,
                            "dew_point_c": dew,
                            "relay_on": relay_raw == "on",
                        }
                    )
        current_day += timedelta(days=1)

    records.sort(key=lambda entry: entry["timestamp"])
    return records
