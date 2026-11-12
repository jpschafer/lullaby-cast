"""Icecast's config, rendered from the environment. The supervisor writes it
out and runs icecast2 with it in the same container as the synth."""

from __future__ import annotations

import os
import re
from pathlib import Path
from string import Template

from .config import ConfigError

TEMPLATE = Path(__file__).resolve().parent.parent / "icecast.xml.template"
CONFIG_PATH = "/tmp/icecast.xml"

# Everything below ends up inside XML (and the passwords in a URL), so
# keep each value to characters that need no escaping.
PASSWORD = re.compile(r"[A-Za-z0-9._-]+")
HOSTNAME = re.compile(r"[A-Za-z0-9.-]+")
MOUNT = re.compile(r"/[A-Za-z0-9._/-]*")


def render_config(env=None, template=TEMPLATE) -> str:
    """icecast.xml for `env`; raises ConfigError listing every problem."""
    env = os.environ if env is None else env
    values = {
        "ICECAST_HOSTNAME": env.get("ICECAST_HOSTNAME", ""),
        "ICECAST_PORT": env.get("ICECAST_PORT") or "8000",
        "ICECAST_MOUNT": env.get("ICECAST_MOUNT") or "/lullaby.mp3",
        "ICECAST_BURST_SIZE": env.get("ICECAST_BURST_SIZE") or "16384",
        "ICECAST_SOURCE_PASSWORD": env.get("ICECAST_SOURCE_PASSWORD", ""),
        "ICECAST_ADMIN_PASSWORD": env.get("ICECAST_ADMIN_PASSWORD", ""),
    }
    errors = []
    if not values["ICECAST_HOSTNAME"]:
        errors.append("ICECAST_HOSTNAME is not set (the LAN IP of the Docker host)")
    elif not HOSTNAME.fullmatch(values["ICECAST_HOSTNAME"]):
        errors.append(f"ICECAST_HOSTNAME must be an IP or host name (got {values['ICECAST_HOSTNAME']!r})")
    for name in ("ICECAST_SOURCE_PASSWORD", "ICECAST_ADMIN_PASSWORD"):
        value = values[name]
        if not value:
            errors.append(f"{name} is not set")
        elif value.startswith("change-me"):
            errors.append(f"{name} still has the example value; set a real one")
        elif not PASSWORD.fullmatch(value):
            errors.append(f"{name} may only contain letters, digits, '.', '_' and '-'")
    for name in ("ICECAST_PORT", "ICECAST_BURST_SIZE"):
        if not values[name].isdigit():
            errors.append(f"{name} must be a whole number (got {values[name]!r})")
    if not MOUNT.fullmatch(values["ICECAST_MOUNT"]):
        errors.append(f"ICECAST_MOUNT must start with '/' and use only letters, digits, "
                      f"'.', '_', '-' and '/' (got {values['ICECAST_MOUNT']!r})")
    if errors:
        raise ConfigError("invalid Icecast configuration:\n  - " + "\n  - ".join(errors))
    return Template(Path(template).read_text()).substitute(values)
