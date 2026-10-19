"""`python -m styleatlas ...` runs the style-atlas command (for when Python's Scripts folder is
not on PATH).

Worker processes (prepare.py) import this file again under another name; the guard keeps them
from running the command a second time, and importing the command only inside it keeps torch
out of them."""

if __name__ == "__main__":
    import sys

    from styleatlas.cli import main

    sys.exit(main())
