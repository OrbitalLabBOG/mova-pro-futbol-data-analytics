#!/usr/bin/env python3
"""Validate the R3 host contract without exposing an execution entrypoint."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mova_fpl.ops.browser_driver import DriverPlanBlocked, compile_r3_driver_plan


def emit(event: str, **detail: object) -> None:
    print(json.dumps({"event": event, **detail}, ensure_ascii=False), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ui-plan", required=True)
    parser.add_argument(
        "--validate-contract-only", action="store_true", required=True,
        help="compila el contrato; nunca inicia browser ni ejecuta clicks",
    )
    args = parser.parse_args()
    try:
        ui_plan = json.loads(Path(args.ui_plan).read_text(encoding="utf-8"))
        driver_plan = compile_r3_driver_plan(ui_plan)
    except (OSError, ValueError, TypeError, KeyError, DriverPlanBlocked) as exc:
        emit("browser_r3_contract_blocked", error_code=getattr(exc, "code", type(exc).__name__),
             error_detail=str(exc)[:500])
        return 2
    print(json.dumps(driver_plan, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
