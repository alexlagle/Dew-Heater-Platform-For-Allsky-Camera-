"""Thread-safe controller state helpers."""

from __future__ import annotations

import threading
from datetime import datetime


class ControllerState:
    """Tracks relay mode, manual overrides, and forced-run timers."""

    def __init__(self):
        self._lock = threading.Lock()
        self.mode = "auto"
        self.manual_on = False
        self.relay_on = False
        self.weather: dict | None = None
        self.auto_run_until: datetime | None = None
        self.auto_cooldown_until: datetime | None = None

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "mode": self.mode,
                "manual_on": self.manual_on,
                "relay_on": self.relay_on,
                "weather": self.weather,
                "auto_run_until": self.auto_run_until.isoformat() if self.auto_run_until else None,
                "auto_cooldown_until": (
                    self.auto_cooldown_until.isoformat() if self.auto_cooldown_until else None
                ),
            }

    def set_mode(self, mode: str, manual_on: bool | None = None):
        with self._lock:
            self.mode = mode
            if manual_on is not None:
                self.manual_on = manual_on

    def set_manual_on(self, manual_on: bool):
        with self._lock:
            self.manual_on = manual_on

    def update_relay(self, relay_on: bool):
        with self._lock:
            self.relay_on = relay_on

    def update_weather(self, weather: dict | None):
        with self._lock:
            self.weather = weather

    def start_forced_run(self, run_until: datetime, cooldown_until: datetime):
        with self._lock:
            self.auto_run_until = run_until
            self.auto_cooldown_until = cooldown_until

    def clear_forced_run(self):
        with self._lock:
            self.auto_run_until = None

    def clear_cooldown(self):
        with self._lock:
            self.auto_cooldown_until = None

    def get_timers(self) -> tuple[datetime | None, datetime | None]:
        with self._lock:
            return self.auto_run_until, self.auto_cooldown_until
