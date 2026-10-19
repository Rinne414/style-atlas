#!/bin/sh
# The style-atlas command line, using this folder's own Python: ./style-atlas-cli.sh --help
dir="$(cd "$(dirname "$0")" && pwd)"
if [ ! -f "$dir/python/style-atlas-env.json" ]; then
  echo "Run ./style-atlas.sh once first, so it can install what the program needs."
  exit 1
fi
PYTHONPATH="$dir/app" exec "$dir/python/bin/python3" -m styleatlas "$@"
