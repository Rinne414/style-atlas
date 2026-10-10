"""`python -m styleatlas ...` runs the style-atlas command (for when Python's Scripts folder is
not on PATH)."""

import sys

from styleatlas.cli import main

sys.exit(main())
