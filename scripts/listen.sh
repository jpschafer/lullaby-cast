#!/bin/sh
# Play the Icecast mount on this machine.
#   scripts/listen.sh                  # http://localhost:<port><mount> from .env
#   scripts/listen.sh 192.168.1.10     # the stream on your Unraid box
#   scripts/listen.sh http://host:8000/lullaby.mp3
set -eu
cd "$(dirname "$0")/.."

PORT=8000
MOUNT=/lullaby.mp3
if [ -f .env ]; then
  PORT=$(sed -n 's/^ICECAST_PORT=//p' .env | tail -1); PORT=${PORT:-8000}
  MOUNT=$(sed -n 's/^ICECAST_MOUNT=//p' .env | tail -1); MOUNT=${MOUNT:-/lullaby.mp3}
fi

case "${1:-localhost}" in
  http://*|https://*) URL=$1 ;;
  *) URL="http://${1:-localhost}:${PORT}${MOUNT}" ;;
esac

echo "Listening to $URL"
# The stream never ends, so curl always times out; only the status code matters.
CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "$URL" 2>/dev/null || true)
if [ "$CODE" != "200" ]; then
  echo "WARNING: $URL did not answer. Is the stack up? Try: docker compose logs -f" >&2
fi

VLC=/Applications/VLC.app/Contents/MacOS/VLC
if command -v ffplay >/dev/null; then
  exec ffplay -hide_banner -nodisp -autoexit "$URL"
elif command -v mpv >/dev/null; then
  exec mpv --no-video "$URL"
elif [ -x "$VLC" ]; then
  exec "$VLC" "$URL"
elif command -v vlc >/dev/null; then
  exec vlc "$URL"
elif command -v open >/dev/null; then
  echo "No ffplay/mpv/VLC found; opening in your default browser."
  exec open "$URL"
else
  echo "No player found. Open $URL in VLC or a browser." >&2
  exit 1
fi
