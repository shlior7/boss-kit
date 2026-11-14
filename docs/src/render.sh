#!/bin/sh
# Renders docs/src/shots.html into docs/*.png. Needs Chrome or Chromium (or CHROME=/path) and ImageMagick.
set -e
cd "$(dirname "$0")"
MAC_CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
[ -x "$MAC_CHROME" ] || MAC_CHROME=""
CHROME="${CHROME:-${MAC_CHROME:-$(command -v google-chrome || command -v chromium || command -v chromium-browser)}}"
[ -n "$CHROME" ] || { echo "render.sh: no Chrome found; set CHROME=/path/to/chrome" >&2; exit 1; }
for shot in main peek worker; do
  "$CHROME" --headless --hide-scrollbars --force-device-scale-factor=2 --window-size=1300,1000 \
    --screenshot="$PWD/$shot.raw.png" "file://$PWD/shots.html#$shot" 2>/dev/null
  magick "$shot.raw.png" -fuzz 2% -trim -bordercolor '#0f1012' -border 40 +repage "../boss-deck-$shot.png"
  rm "$shot.raw.png"
done
