#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    cmd = [str(root / ".venv" / "bin" / "python"), "-m", "pytest", "tests", "-q"]
    print("[phase-01] running unit/integration tests:", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=root)
    if proc.returncode != 0:
        print(f"[phase-01] FAIL (exit={proc.returncode})")
        return proc.returncode
    print("[phase-01] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
