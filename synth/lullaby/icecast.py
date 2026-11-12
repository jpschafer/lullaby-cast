"""Reads Icecast's public status JSON: is our mount live, how many listeners."""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.request
from urllib.parse import urlparse

log = logging.getLogger(__name__)


def mount_status(host, port, mount, timeout=5.0):
    """Return the listener count on `mount`, or None if it has no live source.
    Raises OSError/ValueError if Icecast can't be reached or parsed."""
    url = f"http://{host}:{port}/status-json.xsl"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        stats = json.load(resp)["icestats"]
    sources = stats.get("source", [])
    if isinstance(sources, dict):  # Icecast returns a bare object for one source
        sources = [sources]
    for source in sources:
        if urlparse(source.get("listenurl", "")).path == mount:
            return int(source.get("listeners", 0))
    return None


class ListenerWatch:
    """Polls Icecast in a background thread. `active` is true while someone is
    listening, and for `grace_seconds` after the last one leaves (so a Cast
    reconnect doesn't end the session)."""

    def __init__(self, host, port, mount, poll_seconds=2.0, grace_seconds=20.0):
        self.host, self.port, self.mount = host, port, mount
        self.poll_seconds = poll_seconds
        self.grace_seconds = grace_seconds
        self.listeners = 0
        self._last_heard = None
        self._reachable = None
        threading.Thread(target=self._run, name="listener-watch", daemon=True).start()

    @property
    def active(self) -> bool:
        return self._last_heard is not None and time.monotonic() - self._last_heard <= self.grace_seconds

    def _run(self) -> None:
        while True:
            try:
                count = mount_status(self.host, self.port, self.mount, timeout=self.poll_seconds) or 0
                if self._reachable is False:
                    log.info("Icecast status reachable again")
                self._reachable = True
            except (OSError, ValueError, KeyError) as e:
                if self._reachable is not False:
                    log.error("cannot read Icecast status (%s); treating as no listeners", e)
                self._reachable = False
                count = 0
            if count != self.listeners:
                log.info("listeners on %s: %d -> %d", self.mount, self.listeners, count)
            self.listeners = count
            if count > 0:
                self._last_heard = time.monotonic()
            time.sleep(self.poll_seconds)
