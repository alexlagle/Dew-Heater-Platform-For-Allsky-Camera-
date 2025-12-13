"""Centralized configuration for the Dew Heater controller.

This module keeps all tunable values and environment overrides in one place so
the rest of the code can import a single source of truth.  Every setting has a
brief description to make the hardware/web stack easier to reason about.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

# --- Hardware + Control -----------------------------------------------------

#: BCM pin for the DHT11 temperature/humidity sensor (physical pin 36).
DHT_PIN = int(os.environ.get("DEW_DHT_PIN", "16"))
#: BCM pin for the relay that powers the dew heater (physical pin 37).
RELAY_PIN = int(os.environ.get("DEW_RELAY_PIN", "26"))
#: Temperature delta (Celsius) between the enclosure temperature and dew point
#: that triggers the relay to turn on or off.
HYSTERESIS_C = float(os.environ.get("DEW_HYSTERESIS_C", "5.0"))
#: Filesystem directory that stores CSV log files.
LOG_DIR = Path(os.environ.get("DEW_LOG_DIR", "Temp_Humidity_Logs"))
#: Seconds between DHT11 polls.
POLL_INTERVAL = int(os.environ.get("DEW_POLL_INTERVAL", "10"))
#: Default time range shown on the dashboard charts.
DEFAULT_RANGE_HOURS = float(os.environ.get("DEW_DEFAULT_RANGE_HOURS", "6"))

# --- Web Server -------------------------------------------------------------

WEB_HOST = os.environ.get("DEW_WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.environ.get("DEW_WEB_PORT", "8080"))

# --- Ambient Weather + Astronomy -------------------------------------------

AMBIENT_LAT = os.environ.get("AMBIENT_LAT", "")
AMBIENT_LON = os.environ.get("AMBIENT_LON", "")
AMBIENT_CACHE_SECONDS = int(os.environ.get("AMBIENT_CACHE_SECONDS", "600"))
AMBIENT_TEMP_OFFSET_C = float(os.environ.get("AMBIENT_TEMP_OFFSET_C", "5.0"))
AMBIENT_API_URL = os.environ.get("AMBIENT_API_URL", "https://api.open-meteo.com/v1/forecast")
AMBIENT_LOCATION_NAME = os.environ.get("AMBIENT_LOCATION_NAME", "")

IMAGES_ROOT = Path(os.environ.get("IMAGES_ROOT", "/home/allsky/allsky/images"))
ALLSKY_PUBLIC_URL = os.environ.get("ALLSKY_PUBLIC_URL", "http://192.168.40.210/public.php")

FORCE_RUN_TEMP_DIFF_C = float(os.environ.get("FORCE_RUN_TEMP_DIFF_C", "6.0"))
FORCE_RUN_DURATION = timedelta(minutes=int(os.environ.get("FORCE_RUN_DURATION_MIN", "30")))
FORCE_RUN_COOLDOWN = timedelta(minutes=int(os.environ.get("FORCE_RUN_COOLDOWN_MIN", "60")))

SEVENTIMER_URL = os.environ.get("SEVENTIMER_URL", "http://www.7timer.info/bin/api.pl")
SEVENTIMER_GRAPH_URL = os.environ.get("SEVENTIMER_GRAPH_URL", "http://www.7timer.info/bin/astro.php")
