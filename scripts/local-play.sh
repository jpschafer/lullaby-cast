#!/bin/sh
# Run the synth on this machine with no Docker or Icecast.
#   scripts/local-play.sh                          # live to your speakers (needs ffplay)
#   scripts/local-play.sh --wav out.wav --seconds 20 && afplay out.wav
# Any arguments go to `python -m lullaby`. Settings come from .env if present.
set -eu
cd "$(dirname "$0")/.."

if [ ! -x .venv/bin/python ]; then
  if command -v uv >/dev/null; then
    # Same Python as the container (Debian trixie).
    echo "Creating .venv with uv (Python 3.13) ..."
    uv venv -q --python 3.13 .venv
    uv pip install -q --python .venv/bin/python -r synth/requirements.txt
  else
    PY=""
    for cand in python3.13 python3.12 python3.11 python3; do
      if command -v "$cand" >/dev/null &&
         "$cand" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
        PY=$cand; break
      fi
    done
    [ -n "$PY" ] || { echo "ERROR: need uv (brew install uv) or Python 3.11+" >&2; exit 1; }
    echo "Creating .venv with $PY ..."
    "$PY" -m venv .venv
    .venv/bin/pip install -q -r synth/requirements.txt
  fi
fi

if [ -f .env ]; then
  set -a; . ./.env; set +a
fi
# Inside Docker these point at mounted folders; locally use the repo's folders.
export MIDI_DIR="${LOCAL_MIDI_DIR:-$PWD/midi}"
export SOUNDFONT="${LOCAL_SOUNDFONT:-$PWD/soundfonts/$(basename "${SOUNDFONT:-GeneralUser-GS.sf2}")}"
if [ -n "${MIDI_FILE:-}" ]; then
  export MIDI_FILE="$PWD/midi/${MIDI_FILE#/midi/}"
fi
export HEARTBEAT_PATH="${TMPDIR:-/tmp}/lullaby-heartbeat"
# No Icecast here to report listeners, so always be "in session".
export SESSION_START=always
RATE="${SAMPLE_RATE:-44100}"

cd synth
case " $* " in
  *" --wav "*) exec ../.venv/bin/python -m lullaby "$@" ;;
esac
command -v ffplay >/dev/null || { echo "ERROR: ffplay not found (brew install ffmpeg), or use --wav" >&2; exit 1; }
../.venv/bin/python -m lullaby "$@" \
  | ffplay -hide_banner -loglevel warning -nodisp -f s16le -ar "$RATE" -ch_layout stereo -i -
