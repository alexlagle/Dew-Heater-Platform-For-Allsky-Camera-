#!/home/allsky/.venv/bin/python
"""Dew heater controller with live web dashboard.

Features:
    * Monitors a DHT11, computes dew point, and drives the relay automatically with
      configurable offsets, hysteresis, daylight blocking, warm-up, cooldown, and
      forced-run logic triggered by ambient forecasts.
    * Logs every reading and relay transition to daily CSV files for later analysis.
    * Embedded Flask + Chart.js dashboard with selectable ranges, Fahrenheit/Celsius
      toggles, manual override controls, and live SSE updates so graphs stream in.
    * Pulls ambient weather from Open-Meteo plus 7timer astronomy forecast, moon
      phase/illumination, sunrise/sunset, and shows the latest AllSky image & astro chart.
    * JSON API exposes readings, control state, manual relay overrides, latest-image
      proxy, and astro chart URLs for other automation hooks.
"""

import json
import logging
import mimetypes
import os
import re
import threading
import time
from datetime import datetime, timedelta
from html.parser import HTMLParser
from io import BytesIO
from urllib.parse import urljoin

import RPi.GPIO as GPIO
import dht11
from flask import Flask, Response, jsonify, render_template, request, send_file, stream_with_context
import requests

from dew_heater_controller.config import (
    ALLSKY_PUBLIC_URL,
    AMBIENT_TEMP_OFFSET_C,
    DEFAULT_RANGE_HOURS,
    DHT_PIN,
    FORCE_RUN_COOLDOWN,
    FORCE_RUN_DURATION,
    FORCE_RUN_TEMP_DIFF_C,
    HYSTERESIS_C,
    IMAGES_ROOT,
    POLL_INTERVAL,
    RELAY_PIN,
    WEB_HOST,
    WEB_PORT,
)
from dew_heater_controller.live import LiveBroker
from dew_heater_controller.logs import (
    event_log_path,
    load_readings_range,
    log_event,
    log_reading,
    readings_log_path,
)
from dew_heater_controller.metrics import dew_point_c
from dew_heater_controller.state import ControllerState
from dew_heater_controller.weather import AmbientWeatherFetcher, build_7timer_graph_url

app = Flask(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
LOGGER = logging.getLogger("dew_heater")


controller_state = ControllerState()
live_broker = LiveBroker()
ambient_fetcher = AmbientWeatherFetcher()


def find_latest_image_path() -> str | None:
    """Return the most recent AllSky JPG named image-YYYYMMDDHHMMSS.jpg."""
    if not IMAGES_ROOT.exists():
        return None

    pattern = re.compile(r"^image-(\d{14})\.jpe?g$", re.IGNORECASE)
    candidates: list[tuple[datetime, Path]] = []

    def iter_candidate_folders():
        try:
            folders = [
                path
                for path in IMAGES_ROOT.iterdir()
                if path.is_dir() and path.name.isdigit()
            ]
        except FileNotFoundError:
            return []
        folders.sort(key=lambda p: p.name, reverse=True)
        return folders[:10]

    for folder in iter_candidate_folders():
        try:
            entries = list(folder.iterdir())
        except (FileNotFoundError, PermissionError):
            continue
        for entry in entries:
            if not entry.is_file():
                continue
            match = pattern.match(entry.name)
            if not match:
                continue
            ts_raw = match.group(1)
            try:
                ts = datetime.strptime(ts_raw, "%Y%m%d%H%M%S")
            except ValueError:
                continue
            candidates.append((ts, entry))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return str(candidates[0][1])


def set_relay(state_on: bool):
    """Set relay state; relay energizes on HIGH."""
    GPIO.output(RELAY_PIN, GPIO.HIGH if state_on else GPIO.LOW)
    controller_state.update_relay(state_on)


def parse_time_range() -> tuple[datetime, datetime]:
    """Parse start/end query params or fallback to hours parameter."""
    now = datetime.now()
    start_param = request.args.get("start")
    end_param = request.args.get("end")
    hours_param = request.args.get("hours", type=float)

    def parse_iso(value: str, label: str) -> datetime:
        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"Invalid {label} value; expected ISO format.") from exc

    if start_param:
        start_dt = parse_iso(start_param, "start")
    elif hours_param:
        start_dt = now - timedelta(hours=hours_param)
    else:
        start_dt = now - timedelta(hours=DEFAULT_RANGE_HOURS)

    if end_param:
        end_dt = parse_iso(end_param, "end")
    else:
        end_dt = now

    if start_dt > end_dt:
        start_dt, end_dt = end_dt, start_dt

    return start_dt, end_dt

@app.route("/")
def dashboard():
    return render_template("dashboard.html", default_range_hours=DEFAULT_RANGE_HOURS)


@app.route("/api/readings")
def api_readings():
    try:
        start_dt, end_dt = parse_time_range()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    data = load_readings_range(start_dt, end_dt)
    return jsonify(
        {
            "timestamps": [item["timestamp"] for item in data],
            "temperature_c": [item["temp_c"] for item in data],
            "humidity_pct": [item["humidity_pct"] for item in data],
            "dew_point_c": [item["dew_point_c"] for item in data],
            "relay_state": [item["relay_on"] for item in data],
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
        }
    )


@app.route("/api/control", methods=["GET", "POST"])
def api_control():
    if request.method == "GET":
        snapshot = controller_state.snapshot()
        return jsonify(snapshot)

    payload = request.get_json(silent=True) or {}
    snapshot = controller_state.snapshot()
    mode = payload.get("mode", snapshot["mode"])
    manual_on = payload.get("manual_on")

    if mode not in {"auto", "manual"}:
        return jsonify({"error": "Mode must be 'auto' or 'manual'."}), 400

    if mode == "auto":
        controller_state.set_mode("auto")
        LOGGER.info("Controller set to automatic mode via API.")
    else:
        if manual_on is None:
            manual_on = snapshot["manual_on"]
        manual_on = bool(manual_on)
        controller_state.set_mode("manual", manual_on)
        LOGGER.info("Controller manual override -> %s", "ON" if manual_on else "OFF")
        set_relay(manual_on)

    return jsonify(controller_state.snapshot())


@app.route("/api/live")
def api_live():
    q = live_broker.subscribe()

    def event_stream():
        try:
            while True:
                data = q.get()
                yield f"data: {json.dumps(data)}\n\n"
        except GeneratorExit:
            live_broker.unsubscribe(q)
        finally:
            live_broker.unsubscribe(q)

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return Response(stream_with_context(event_stream()), headers=headers, mimetype="text/event-stream")


class _FirstImageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.src = None

    def handle_starttag(self, tag, attrs):
        if self.src is not None:
            return
        if tag.lower() == "img":
            for attr, value in attrs:
                if attr.lower() == "src" and value:
                    self.src = value
                    break


def _extract_image_src(html: str, base_url: str) -> str | None:
    parser = _FirstImageParser()
    try:
        parser.feed(html)
    except Exception:
        return None
    if not parser.src:
        return None
    return urljoin(base_url, parser.src)


def _public_image_response():
    if not ALLSKY_PUBLIC_URL:
        return None
    try:
        resp = requests.get(ALLSKY_PUBLIC_URL, timeout=10)
        resp.raise_for_status()
    except Exception as exc:
        LOGGER.warning("Failed to fetch public AllSky page: %s", exc)
        return None
    content_type = (resp.headers.get("Content-Type") or "").lower()
    if content_type.startswith("image/"):
        mime = resp.headers.get("Content-Type", "image/jpeg")
        return send_file(BytesIO(resp.content), mimetype=mime)
    image_url = _extract_image_src(resp.text, ALLSKY_PUBLIC_URL)
    if not image_url:
        LOGGER.warning("No <img> tag found on AllSky public page; cannot display image.")
        return None
    try:
        img_resp = requests.get(image_url, timeout=10)
        img_resp.raise_for_status()
    except Exception as exc:
        LOGGER.warning("Failed to fetch AllSky image at %s: %s", image_url, exc)
        return None
    mime = img_resp.headers.get("Content-Type", "image/jpeg")
    return send_file(BytesIO(img_resp.content), mimetype=mime)


@app.route("/api/latest-image")
def api_latest_image():
    if ALLSKY_PUBLIC_URL:
        return jsonify(
            {
                "available": True,
                "url": f"/latest-image?cacheBust={int(time.time())}",
                "last_modified": datetime.now().isoformat(),
            }
        )
    path = find_latest_image_path()
    if not path:
        return jsonify({"available": False}), 404
    mtime = os.path.getmtime(path)
    return jsonify(
        {
            "available": True,
            "url": f"/latest-image?cache={int(mtime)}",
            "last_modified": datetime.fromtimestamp(mtime).isoformat(),
        }
    )


@app.route("/latest-image")
def latest_image_file():
    if ALLSKY_PUBLIC_URL:
        response = _public_image_response()
        if response is not None:
            return response
    path = find_latest_image_path()
    if not path:
        return "", 404
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return send_file(path, mimetype=mime)


@app.route("/api/astro-chart")
def api_astro_chart():
    url = build_7timer_graph_url()
    return jsonify({"url": url})


def sensor_loop(stop_event: threading.Event):
    """Background thread that polls the DHT11 sensor and controls the relay."""
    GPIO.cleanup()
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(RELAY_PIN, GPIO.OUT, initial=GPIO.LOW)
    controller_state.update_relay(False)
    dht_sensor = dht11.DHT11(pin=DHT_PIN)
    startup_time = datetime.now()
    last_humidity = None
    humidity_spike_pending = False

    try:
        while not stop_event.is_set():
            result = dht_sensor.read()
            if result.is_valid():
                temp_c = float(result.temperature)
                humidity = float(result.humidity)
                # DHT11 occasionally spikes humidity; ignore outliers that jump >15% in one cycle.
                if last_humidity is not None:
                    change_pct = abs(humidity - last_humidity)
                    if change_pct > 15:
                        if not humidity_spike_pending:
                            humidity_spike_pending = True
                            LOGGER.warning(
                                "Humidity spike ignored once (prev %.1f%% -> %.1f%%)",
                                last_humidity,
                                humidity,
                            )
                            if stop_event.wait(POLL_INTERVAL):
                                break
                            continue
                        LOGGER.info(
                            "Humidity change persisted; accepting new baseline %.1f%% (prev %.1f%%)",
                            humidity,
                            last_humidity,
                        )
                        humidity_spike_pending = False
                    else:
                        humidity_spike_pending = False
                else:
                    humidity_spike_pending = False
                last_humidity = humidity
                dew_c = dew_point_c(temp_c, humidity)
                timestamp = datetime.now().isoformat()
                now_dt = datetime.fromisoformat(timestamp)
                evt_path = event_log_path(now_dt)
                read_path = readings_log_path(now_dt)
                snapshot = controller_state.snapshot()
                mode = snapshot["mode"]
                relay_on = snapshot["relay_on"]
                manual_target = snapshot["manual_on"]
                weather = ambient_fetcher.get_weather()
                controller_state.update_weather(weather)
                sunrise_dt = None
                sunset_dt = None
                if weather:
                    sunrise_raw = weather.get("sunrise")
                    sunset_raw = weather.get("sunset")
                    try:
                        if sunrise_raw:
                            sunrise_dt = datetime.fromisoformat(sunrise_raw)
                        if sunset_raw:
                            sunset_dt = datetime.fromisoformat(sunset_raw)
                    except Exception:
                        sunrise_dt = None
                        sunset_dt = None
                threshold_temp = temp_c - AMBIENT_TEMP_OFFSET_C
                ambient_dew_c = weather.get("dew_point_c") if weather else None
                ambient_temp_c = weather.get("temperature_c") if weather else None
                baseline_dew = ambient_dew_c if ambient_dew_c is not None else dew_c
                should_turn_on = threshold_temp < baseline_dew
                should_turn_off = threshold_temp > (baseline_dew + HYSTERESIS_C)

                runtime = now_dt - startup_time
                auto_ready = runtime >= timedelta(minutes=15)
                run_until, cooldown_until = controller_state.get_timers()
                if run_until and now_dt >= run_until:
                    controller_state.clear_forced_run()
                    run_until = None
                if cooldown_until and now_dt >= cooldown_until:
                    controller_state.clear_cooldown()
                    cooldown_until = None

                daylight_block = False
                if sunrise_dt and sunset_dt:
                    if sunrise_dt <= now_dt <= sunset_dt:
                        # Block from 30 min after sunrise to 30 min before sunset to save power.
                        sunrise_safe = sunrise_dt + timedelta(minutes=30)
                        sunset_safe = sunset_dt - timedelta(minutes=30)
                        if sunrise_safe <= now_dt <= sunset_safe:
                            daylight_block = True
                in_forced_run = run_until is not None and now_dt < run_until
                cooldown_active = cooldown_until is not None and now_dt < cooldown_until
                can_force_run = (
                    auto_ready
                    and not daylight_block
                    and not in_forced_run
                    and not cooldown_active
                    and ambient_temp_c is not None
                    and ambient_dew_c is not None
                    and (ambient_temp_c - ambient_dew_c) <= FORCE_RUN_TEMP_DIFF_C
                )
                if can_force_run:
                    run_until = now_dt + FORCE_RUN_DURATION
                    cooldown_until = run_until + FORCE_RUN_COOLDOWN
                    controller_state.start_forced_run(run_until, cooldown_until)
                    in_forced_run = True
                    LOGGER.info(
                        "Forced run started until %s (ambient temp %.1fC, dew %.1fC)",
                        run_until.isoformat(),
                        ambient_temp_c,
                        ambient_dew_c,
                    )

                if mode == "manual":
                    # Manual mode simply mirrors the requested relay state and logs transitions.
                    if manual_target != relay_on:
                        set_relay(manual_target)
                        relay_on = manual_target
                        log_event(evt_path, timestamp, temp_c, humidity, dew_c, relay_on)
                        LOGGER.info(
                            "Manual mode -> Relay %s | Temp %.1fC Hum %.1f%% Dew %.1fC",
                            "ON" if relay_on else "OFF",
                            temp_c,
                            humidity,
                            dew_c,
                        )
                    else:
                        LOGGER.info(
                            "Manual mode holding %s | Temp %.1fC Hum %.1f%% Dew %.1fC",
                            "ON" if relay_on else "OFF",
                            temp_c,
                            humidity,
                            dew_c,
                        )
                else:
                    # Automatic control with optional predictive “forced runs” based on forecasts.
                    if in_forced_run:
                        if not relay_on:
                            set_relay(True)
                            relay_on = True
                            log_event(evt_path, timestamp, temp_c, humidity, dew_c, True)
                        LOGGER.info(
                            "Forced run active | Temp %.1fC Hum %.1f%% Dew %.1fC (runs until %s)",
                            temp_c,
                            humidity,
                            dew_c,
                            run_until.isoformat() if run_until else "soon",
                        )
                    else:
                        if should_turn_on and not relay_on:
                            if daylight_block:
                                LOGGER.info("Daylight block active; skipping auto ON")
                            elif not auto_ready:
                                warmup_remaining = max(
                                    0.0, (timedelta(minutes=15) - runtime).total_seconds() / 60.0
                                )
                                LOGGER.info(
                                    "Warm-up period active (%.1f min remaining); skipping auto ON",
                                    warmup_remaining,
                                )
                            elif cooldown_active:
                                LOGGER.info(
                                    "Cooldown active (until %s); skipping auto ON",
                                    cooldown_until.isoformat() if cooldown_until else "n/a",
                                )
                            else:
                                set_relay(True)
                                relay_on = True
                                log_event(evt_path, timestamp, temp_c, humidity, dew_c, True)
                                LOGGER.info(
                                    "Auto -> Relay ON | Temp %.1fC Hum %.1f%% Dew %.1fC (ambient %.1fC, thresh %.1fC)",
                                    temp_c,
                                    humidity,
                                    dew_c,
                                    ambient_dew_c if ambient_dew_c is not None else float("nan"),
                                    threshold_temp,
                                )
                        elif should_turn_off and relay_on:
                            set_relay(False)
                            relay_on = False
                            log_event(evt_path, timestamp, temp_c, humidity, dew_c, False)
                            LOGGER.info(
                                "Auto -> Relay OFF | Temp %.1fC Hum %.1f%% Dew %.1fC (ambient %.1fC, thresh %.1fC)",
                                temp_c,
                                humidity,
                                dew_c,
                                ambient_dew_c if ambient_dew_c is not None else float("nan"),
                                threshold_temp,
                            )
                        else:
                            LOGGER.info(
                                "Auto hold %s | Temp %.1fC Hum %.1f%% Dew %.1fC (ambient %.1fC, thresh %.1fC)",
                                "ON" if relay_on else "OFF",
                                temp_c,
                                humidity,
                                dew_c,
                                ambient_dew_c if ambient_dew_c is not None else float("nan"),
                                threshold_temp,
                            )
                # Log every reading
                log_reading(read_path, timestamp, temp_c, humidity, dew_c, relay_on)
                live_broker.publish(
                    {
                        "timestamp": timestamp,
                        "temp_c": temp_c,
                        "humidity_pct": humidity,
                        "dew_point_c": dew_c,
                        "relay_on": relay_on,
                        "weather": weather,
                        "mode": mode,
                        "manual_on": manual_target,
                    }
                )
            else:
                LOGGER.warning("DHT11 read failed; code %s", result.error_code)

            if stop_event.wait(POLL_INTERVAL):
                break
    finally:
        set_relay(False)
        GPIO.cleanup()
        LOGGER.info("Sensor loop stopped; GPIO cleaned up.")


def main():
    stop_event = threading.Event()
    sensor_thread = threading.Thread(target=sensor_loop, args=(stop_event,), daemon=True)
    sensor_thread.start()

    try:
        LOGGER.info("Web dashboard running on %s:%s", WEB_HOST, WEB_PORT)
        app.run(host=WEB_HOST, port=WEB_PORT, threaded=True, use_reloader=False)
    except KeyboardInterrupt:
        LOGGER.info("Shutdown requested; stopping threads.")
    finally:
        stop_event.set()
        sensor_thread.join()
        LOGGER.info("Exited cleanly.")


if __name__ == "__main__":
    main()
