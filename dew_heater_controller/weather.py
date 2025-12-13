"""Ambient weather + astronomy helpers sourced from external APIs."""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime
from typing import Any

import requests

from .config import (
    AMBIENT_API_URL,
    AMBIENT_CACHE_SECONDS,
    AMBIENT_LAT,
    AMBIENT_LON,
    AMBIENT_LOCATION_NAME,
    SEVENTIMER_GRAPH_URL,
    SEVENTIMER_URL,
)

LOGGER = logging.getLogger("dew_heater.weather")


class AmbientWeatherFetcher:
    """Fetch and cache ambient weather readings from an external API."""

    def __init__(self):
        self._last_weather: dict | None = None
        self._last_fetch = 0.0

    def get_dew_point(self) -> float | None:
        weather = self.get_weather()
        return None if weather is None else weather.get("dew_point_c")

    def get_weather(self) -> dict | None:
        now = time.monotonic()
        if self._last_weather is not None and (now - self._last_fetch) < AMBIENT_CACHE_SECONDS:
            return self._last_weather
        try:
            weather = self._fetch()
        except Exception as exc:
            LOGGER.warning("Ambient weather fetch failed: %s", exc)
            return self._last_weather
        self._last_weather = weather
        self._last_fetch = now
        return weather

    def _fetch(self) -> dict | None:
        if not AMBIENT_LAT or not AMBIENT_LON:
            raise RuntimeError("AMBIENT_LAT/LON not configured")
        params = {
            "latitude": AMBIENT_LAT,
            "longitude": AMBIENT_LON,
            "current": "temperature_2m,dew_point_2m,relative_humidity_2m,cloud_cover,weather_code",
            "daily": "temperature_2m_max,temperature_2m_min,sunrise,sunset",
            "timezone": "auto",
        }
        response = requests.get(AMBIENT_API_URL, params=params, timeout=10)
        response.raise_for_status()
        payload = response.json()
        current = payload.get("current") or {}
        daily = payload.get("daily") or {}
        try:
            phase_fraction = estimate_moon_phase(datetime.now())
            moon_phase_name, moon_illum_pct = describe_moon_phase(phase_fraction)
            astro_weather = fetch_7timer()
            sunrise_list = daily.get("sunrise") or []
            sunset_list = daily.get("sunset") or []
            sunrise_iso = sunrise_list[0] if sunrise_list else None
            sunset_iso = sunset_list[0] if sunset_list else None

            weather = {
                "temperature_c": float(current.get("temperature_2m")),
                "dew_point_c": float(current.get("dew_point_2m")),
                "humidity_pct": float(current.get("relative_humidity_2m")),
                "cloud_cover_pct": float(current.get("cloud_cover")),
                "temp_max_c": float(daily.get("temperature_2m_max")[0]),
                "temp_min_c": float(daily.get("temperature_2m_min")[0]),
                "timestamp": datetime.now().isoformat(),
                "location": AMBIENT_LOCATION_NAME,
                "summary": describe_weather(current.get("weather_code"), current.get("cloud_cover")),
                "moon_phase_name": moon_phase_name,
                "moon_illumination_pct": moon_illum_pct,
                "sunrise": sunrise_iso,
                "sunset": sunset_iso,
            }
            if astro_weather:
                weather.update(astro_weather)
        except (TypeError, ValueError, KeyError, IndexError):
            raise RuntimeError("Ambient API returned incomplete data")
        return weather


def fetch_7timer() -> dict | None:
    """Pull 7timer astronomy forecast."""
    if not AMBIENT_LAT or not AMBIENT_LON:
        return None
    params = {
        "lon": AMBIENT_LON,
        "lat": AMBIENT_LAT,
        "product": "astro",
        "output": "json",
    }
    try:
        response = requests.get(SEVENTIMER_URL, params=params, timeout=10)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        LOGGER.warning("7timer fetch failed: %s", exc)
        return None
    series = payload.get("dataseries")
    if not series:
        return None
    first = series[0]

    def describe_index(value: int | None) -> str | None:
        if value is None:
            return None
        mapping = {
            1: "Excellent",
            2: "Good",
            3: "Average",
            4: "Below average",
            5: "Poor",
            6: "Poor",
            7: "Very poor",
            8: "Very poor",
        }
        desc = mapping.get(int(value))
        return f"{desc} (level {value})" if desc else f"Level {value}"

    seeing_desc = describe_index(first.get("seeing"))
    transparency_desc = describe_index(first.get("transparency"))
    prec_type = first.get("prec_type") or "none"
    prec_amount = first.get("prec_amount")
    precip_desc = "None"
    if prec_type and prec_type != "none":
        chance_map = {1: 20, 2: 40, 3: 60, 4: 80}
        percent = chance_map.get(int(prec_amount) if prec_amount is not None else None, 50)
        precip_desc = f"{prec_type.title()} (~{percent}% chance)"
    return {
        "seeing_quality": seeing_desc,
        "transparency_quality": transparency_desc,
        "precipitation_chance": precip_desc,
    }


def describe_weather(code: Any, cloud_cover: Any) -> str:
    """Translate numeric codes into friendly summary strings."""
    code = int(code) if code is not None else None
    if code is None:
        if cloud_cover is not None:
            cc = float(cloud_cover)
            if cc < 25:
                return "Clear"
            if cc < 60:
                return "Partly cloudy"
            return "Overcast"
        return "Fair"
    conditions = {
        0: "Clear sky",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Depositing rime fog",
        51: "Light drizzle",
        53: "Drizzle",
        55: "Dense drizzle",
        56: "Freezing drizzle",
        57: "Dense freezing drizzle",
        61: "Slight rain",
        63: "Rain",
        65: "Heavy rain",
        66: "Freezing rain",
        67: "Heavy freezing rain",
        71: "Slight snow",
        73: "Snow",
        75: "Heavy snow",
        77: "Snow grains",
        80: "Rain showers",
        81: "Rain showers",
        82: "Violent rain showers",
        85: "Snow showers",
        86: "Heavy snow showers",
        95: "Thunderstorm",
        96: "Thunderstorm with hail",
        99: "Heavy hailstorm",
    }
    return conditions.get(code, "Fair")


def estimate_moon_phase(target: datetime) -> float:
    base = datetime(2000, 1, 6, 18, 14)  # known new moon
    synodic_days = 29.53058867
    diff_days = (target - base).total_seconds() / 86400.0
    return (diff_days % synodic_days) / synodic_days


def describe_moon_phase(value: float | None) -> tuple[str | None, float | None]:
    if value is None:
        return None, None
    phase = max(0.0, min(1.0, float(value)))
    illumination = (1 - math.cos(2 * math.pi * phase)) / 2 * 100
    if phase < 0.0625 or phase >= 0.9375:
        label = "New Moon"
    elif phase < 0.1875:
        label = "Waxing Crescent"
    elif phase < 0.3125:
        label = "First Quarter"
    elif phase < 0.4375:
        label = "Waxing Gibbous"
    elif phase < 0.5625:
        label = "Full Moon"
    elif phase < 0.6875:
        label = "Waning Gibbous"
    elif phase < 0.8125:
        label = "Last Quarter"
    else:
        label = "Waning Crescent"
    return label, illumination


def build_7timer_graph_url() -> str:
    """Helper for the dashboard to embed the latest astro chart."""
    params = {
        "lon": AMBIENT_LON,
        "lat": AMBIENT_LAT,
        "ac": 0,
        "lang": "en",
        "unit": 0,
        "output": "internal",
        "tzshift": 0,
        "cache": int(time.time()),
    }
    query = "&".join(f"{key}={value}" for key, value in params.items())
    return f"{SEVENTIMER_GRAPH_URL}?{query}"
