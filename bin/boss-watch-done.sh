#!/bin/bash
# boss-watch-done.sh <worker> <terminal> [<branch>]: the old watcher's name, kept for bosses still on the old prompt.
# It is `boss-host watch <worker> [<branch>] --terminal <terminal>`.
exec "$(dirname "$0")/boss-host" watch "$1" ${3:+"$3"} --terminal "$2"
