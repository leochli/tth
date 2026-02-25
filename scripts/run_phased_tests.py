#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run_phase(script: str, allow_skip: bool = False) -> None:
    root = Path(__file__).resolve().parents[1]
    cmd = [str(root / ".venv" / "bin" / "python"), str(root / "scripts" / script)]
    print(f"\n=== running {script} ===")
    proc = subprocess.run(cmd, cwd=root)
    if proc.returncode == 0:
        print(f"=== {script} PASS ===")
        return
    if allow_skip and proc.returncode == 2:
        print(f"=== {script} SKIPPED ===")
        return
    raise SystemExit(proc.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run phased standalone tests for TTH."
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Include live OpenAI validation phase (requires OPENAI_API_KEY).",
    )
    args = parser.parse_args()

    run_phase("phase_01_unit.py")
    run_phase("phase_02_offline_smoke.py")
    run_phase("phase_03_offline_multiturn.py")
    if args.live:
        run_phase("phase_04_live_openai.py", allow_skip=True)

    print("\nAll requested phases completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
