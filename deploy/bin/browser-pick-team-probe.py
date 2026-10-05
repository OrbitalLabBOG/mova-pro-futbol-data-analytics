#!/usr/bin/env python3
"""Read-only FPL probe: one CDP evaluation per bounded stage, no account writes."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import subprocess
import time

CONTRACT = "fpl-pick-team-a11y-2026.10.1"
BUDGET_SECONDS = 90
CALL_SECONDS = 25

class ProbeFailed(RuntimeError):
    pass

class Browser:
    def __init__(self, team_id: int, port: int, *, clock=time.monotonic, run=subprocess.run, sleep=time.sleep):
        self.clock, self.run, self.team_id, self.sleep = clock, run, team_id, sleep
        self.deadline = clock() + BUDGET_SECONDS
        self.last_stage = "initializing"
        self.prefix = ["docker","compose","--profile","browser","exec","-T","browser"]
        self.args = ["agent-browser","--session","mova-fpl","--cdp",str(port)]
        self.template = (Path(__file__).resolve().parents[1] / "browser/pick-team-dom-probe.js").read_text()

    def command(self, args: list[str], *, script: str | None = None) -> str:
        remaining = self.deadline - self.clock() - 4
        if remaining <= 0:
            raise ProbeFailed("FPL_PROBE_CLOCK_EXPIRED")
        cap = min(CALL_SECONDS, math.floor(remaining))
        if cap < 1:
            raise ProbeFailed("FPL_PROBE_CLOCK_EXPIRED")
        try:
            result = self.run([*self.prefix,"timeout","--signal=TERM","--kill-after=3s",f"{cap}s",
                              *self.args,*args], input=script, text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=cap+4, check=True)
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr or ""
            if exc.returncode in {124,137} or "CDP command timed out" in stderr:
                raise ProbeFailed("FPL_PROBE_CDP_TIMEOUT") from None
            if "Inspected target navigated or closed" in stderr:
                raise ProbeFailed("FPL_PROBE_NAVIGATION_CONTEXT_LOST") from None
            code = re.search(r"\bFPL_[A-Z_]+\b", stderr)
            known = {"FPL_AUTH_REQUIRED","FPL_PRIVATE_API_ERROR","FPL_BOOTSTRAP_API_ERROR",
                     "FPL_PICK_TEAM_PAGE_REQUIRED","FPL_AUTH_OR_ORIGIN_REQUIRED",
                     "FPL_STARTER_INDEX_INVALID","FPL_PLAYER_CONTROLS_CHANGED",
                     "FPL_CAPTAIN_CHECKBOX_MISSING","FPL_PLAYER_SHEET_CLOSE_MISSING_OR_AMBIGUOUS",
                     "FPL_PLAYER_SHEET_DID_NOT_CLOSE","FPL_TEAM_CHANGED_DURING_PROBE"}
            raise ProbeFailed(code.group() if code and code.group() in known else "FPL_PROBE_CDP_FAILED") from None
        except subprocess.TimeoutExpired:
            raise ProbeFailed("FPL_PROBE_CDP_TIMEOUT") from None
        return result.stdout

    def stage(self, name: str, expected: dict) -> dict:
        self.last_stage = name
        script = (self.template.replace("__MOVA_TEAM_ID__", str(self.team_id))
                  .replace("__MOVA_PROBE_STAGE__", json.dumps(name))
                  .replace("__MOVA_PROBE_EXPECTED__", json.dumps(expected,ensure_ascii=True)))
        raw = self.command(["eval","--stdin"],script=script)
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            raise ProbeFailed("FPL_PROBE_RESPONSE_INVALID") from None
        if not isinstance(payload,dict):
            raise ProbeFailed("FPL_PROBE_RESPONSE_INVALID")
        return payload

    def navigate(self) -> None:
        try:
            self.stage("navigate",{})
        except ProbeFailed as exc:
            if str(exc) != "FPL_PROBE_NAVIGATION_CONTEXT_LOST":
                raise
        # Navigation request/response is never proof: require fresh page controls.
        # A cold SPA can take longer than CDP's evaluation timeout. Poll fresh
        # short evaluations; never hold one Runtime.evaluate open for page load.
        # Preserve 40 seconds of the unchanged total clock for the actual probe.
        page_deadline = self.deadline - 40
        while self.clock() < page_deadline:
            try:
                if self.stage("page_gate", {}).get("ready") is True:
                    return
            except ProbeFailed as exc:
                if str(exc) != "FPL_PROBE_NAVIGATION_CONTEXT_LOST":
                    raise
            self.sleep(min(1, max(0, page_deadline - self.clock())))
        raise ProbeFailed("FPL_PROBE_PAGE_READINESS_TIMEOUT")

def probe(browser: Browser, team_id: int) -> dict:
    base = browser.stage("base", {})
    checks = base["checks"]
    if set(checks) != {"signed_in","fifteen_api_picks","fifteen_player_controls",
                       "fifteen_switch_controls","positional_order_matches"}:
        raise ProbeFailed("FPL_PICK_TEAM_BASE_INVALID")
    if not all(type(v) is bool and v for v in checks.values()):
        raise ProbeFailed("FPL_PICK_TEAM_BASE_UNPROVEN")
    slots, signature = base["slots"], base["signature"]
    if (len(slots) != 15 or len(signature) != 15
            or len({row["element"] for row in slots}) != 15
            or [row["position"] for row in slots] != list(range(1,16))
            or any(type(row["element"]) is not int or row["element"] < 1
                   or not isinstance(row["web_name"],str) or not 0 < len(row["web_name"]) <= 80
                   for row in slots)
            or any(not isinstance(sig,list) or len(sig)!=4
                   or sig[:2] != [row["element"],row["position"]]
                   or type(sig[2]) is not bool or type(sig[3]) is not bool
                   for sig,row in zip(signature,slots))):
        raise ProbeFailed("FPL_PICK_TEAM_BASE_INVALID")
    starters = []
    for index,row in enumerate(slots[:11]):
        starter = browser.stage("starter", {"index":index,"element":row["element"],"web_name":row["web_name"]})
        if (starter.get("position") != index+1 or starter.get("element") != row["element"]
                or starter.get("player_button_index") != index
                or not all(type(starter.get(k)) is bool for k in
                           ("captain_checkbox","vice_captain_checkbox","captain_checked","vice_captain_checked"))):
            raise ProbeFailed("FPL_STARTER_RESPONSE_INVALID")
        starters.append(starter)
    if browser.stage("verify", {"signature":signature,"slots":slots}).get("unchanged") is not True:
        raise ProbeFailed("FPL_TEAM_CHANGED_DURING_PROBE")
    captain = {"eleven_starter_sheets":len(starters)==11,
               "semantic_checkboxes":all(r["captain_checkbox"] and r["vice_captain_checkbox"] for r in starters),
               "one_captain":sum(r["captain_checked"] for r in starters)==1,
               "one_vice_captain":sum(r["vice_captain_checked"] for r in starters)==1,
               "captain_matches_api":all(r["captain_checked"]==bool(signature[i][2]) for i,r in enumerate(starters)),
               "vice_captain_matches_api":all(r["vice_captain_checked"]==bool(signature[i][3]) for i,r in enumerate(starters))}
    checks["captain_controls"] = all(captain.values())
    return {"schema":"mova-browser-dom-probe-v1","contract_version":CONTRACT,
            "observed_at":datetime.now(timezone.utc).isoformat(),"team_id":team_id,
            "status":"pass" if all(checks.values()) else "fail", "checks":checks,"slots":slots,
            "captain_controls":{"status":"pass" if checks["captain_controls"] else "fail",
                                "selector_strategy":"player_button_index_then_accessible_checkbox",
                                "checks":captain,"starters":starters}}

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--team-id",type=int,required=True)
    parser.add_argument("--cdp-port",type=int,default=9222)
    args = parser.parse_args()
    if args.team_id < 1 or not 1 <= args.cdp_port <= 65535:
        parser.error("positive team ID and valid CDP port required")
    try:
        browser = Browser(args.team_id,args.cdp_port)
        browser.navigate()
        payload = probe(browser,args.team_id)
    except (ProbeFailed,KeyError,TypeError,ValueError) as exc:
        code = str(exc) if isinstance(exc,ProbeFailed) else "FPL_PROBE_RESPONSE_INVALID"
        failed_stage = browser.last_stage
        diagnostic = None
        if failed_stage == "page_gate":
            try:
                diagnostic = browser.stage("diagnose",{})
            except ProbeFailed:
                pass
        print(json.dumps({"schema":"mova-browser-probe-error-v1","status":"fail","error_code":code,
                          "stage":failed_stage,"page":diagnostic}))
        return 1
    print(json.dumps(payload,ensure_ascii=False))
    return 0 if payload["status"] == "pass" else 1

if __name__ == "__main__":
    raise SystemExit(main())
