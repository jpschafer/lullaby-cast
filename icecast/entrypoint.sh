#!/bin/sh
# Render icecast.xml from the environment, refusing bad or default values.
set -eu

fail() { echo "icecast-entrypoint: ERROR: $*" >&2; exit 1; }

: "${ICECAST_HOSTNAME:?ICECAST_HOSTNAME is not set}"
: "${ICECAST_SOURCE_PASSWORD:?ICECAST_SOURCE_PASSWORD is not set}"
: "${ICECAST_ADMIN_PASSWORD:?ICECAST_ADMIN_PASSWORD is not set}"
ICECAST_PORT="${ICECAST_PORT:-8000}"
ICECAST_MOUNT="${ICECAST_MOUNT:-/lullaby.mp3}"
ICECAST_BURST_SIZE="${ICECAST_BURST_SIZE:-16384}"
export ICECAST_PORT ICECAST_MOUNT ICECAST_BURST_SIZE

for var in ICECAST_SOURCE_PASSWORD ICECAST_ADMIN_PASSWORD; do
  eval "val=\$$var"
  case "$val" in
    change-me*) fail "$var still has the example value; set a real one in .env" ;;
  esac
  # Passwords end up in XML and in the source URL; keep them to a safe set.
  printf '%s' "$val" | grep -Eq '^[A-Za-z0-9._-]+$' \
    || fail "$var may only contain letters, digits, '.', '_' and '-'"
done

case "$ICECAST_MOUNT" in
  /*) ;;
  *) fail "ICECAST_MOUNT must start with '/' (got '$ICECAST_MOUNT')" ;;
esac

envsubst '${ICECAST_HOSTNAME} ${ICECAST_PORT} ${ICECAST_MOUNT} ${ICECAST_BURST_SIZE} ${ICECAST_SOURCE_PASSWORD} ${ICECAST_ADMIN_PASSWORD}' \
  < /etc/icecast2/icecast.xml.template > /tmp/icecast.xml

echo "icecast-entrypoint: serving http://${ICECAST_HOSTNAME}:${ICECAST_PORT}${ICECAST_MOUNT}"
exec icecast2 -c /tmp/icecast.xml
