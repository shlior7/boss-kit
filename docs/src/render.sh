#!/bin/sh
# Renders docs/src/shots.html into docs/*.png. Needs Google Chrome and ImageMagick.
set -e
cd "$(dirname "$0")"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
for shot in main peek; do
  "$CHROME" --headless --hide-scrollbars --force-device-scale-factor=2 --window-size=1300,1000 \
    --screenshot="$PWD/$shot.raw.png" "file://$PWD/shots.html#$shot" 2>/dev/null
  magick "$shot.raw.png" -fuzz 2% -trim -bordercolor '#0f1012' -border 40 +repage "../boss-deck-$shot.png"
  rm "$shot.raw.png"
done
