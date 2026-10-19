#!/bin/sh
# Start Style Atlas. The first time it installs what it needs (a few minutes).
cd "$(dirname "$0")" || exit 1
exec ./python/bin/python3 launch.py "$@"
