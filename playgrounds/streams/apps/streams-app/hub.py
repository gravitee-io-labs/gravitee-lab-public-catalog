"""A small broadcaster: the webhook deliveries fan out to every page that listens."""
import queue
import threading
from collections import deque


class Hub:
    def __init__(self, backlog: int) -> None:
        self._lock = threading.Lock()
        self._listeners: set[queue.Queue] = set()
        self._recent: deque = deque(maxlen=backlog)

    def publish(self, event: dict) -> None:
        with self._lock:
            self._recent.append(event)
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener.put_nowait(event)
            except queue.Full:                 # a page that reads nothing loses events, the others do not wait for it
                pass

    def subscribe(self) -> queue.Queue:
        listener: queue.Queue = queue.Queue(maxsize=1000)
        with self._lock:
            self._listeners.add(listener)
        return listener

    def unsubscribe(self, listener: queue.Queue) -> None:
        with self._lock:
            self._listeners.discard(listener)

    def recent(self) -> list[dict]:
        with self._lock:
            return list(self._recent)
