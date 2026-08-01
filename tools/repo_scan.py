# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
# ─── How to run ───
# python3 tools/repo_scan.py --profile public-generic --root .

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

from repo_scan_cli import main


if __name__ == "__main__":
    raise SystemExit(main())
