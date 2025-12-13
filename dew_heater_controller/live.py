"""Simple in-process pub/sub broker for live streaming."""

from __future__ import annotations

import queue
import threading


class LiveBroker:
    """Allows the web layer to stream sensor updates via Server Sent Events."""

    def __init__(self):
        self._subscribers: set[queue.Queue] = set()
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=5)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: queue.Queue):
        with self._lock:
            self._subscribers.discard(q)

    def publish(self, data: dict):
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            try:
                q.put_nowait(data)
            except queue.Full:
                try:
                    q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    q.put_nowait(data)
                except queue.Full:
                    continue
