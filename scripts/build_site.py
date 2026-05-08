#!/usr/bin/env python3
"""Single entrypoint to refresh data and regenerate the static site."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from common import ROOT_DIR, ensure_dirs


SCRIPTS = [
    "pipeline_national.py",
    "fresh_data.py",
    "render_site.py",
]


def main() -> None:
    ensure_dirs()
    scripts_dir = Path(__file__).resolve().parent
    for script in SCRIPTS:
        print(f"\n=== Running {script} ===")
        subprocess.run([sys.executable, str(scripts_dir / script)], cwd=ROOT_DIR, check=True)


if __name__ == "__main__":
    main()
