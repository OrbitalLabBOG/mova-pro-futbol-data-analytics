#!/usr/bin/env python3
"""Read-only FPL probe: one CDP evaluation per bounded stage, no account writes."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import select
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
        self.read_timeout_reconciliations = 0
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
        try:
            raw = self.command(["eval","--stdin"],script=script)
        except ProbeFailed as exc:
            # One fresh observation after a known CDP timeout is safe only for
            # these pure DOM reads. Never repeat opening, closing, GET or Save.
            if (str(exc)=="FPL_PROBE_CDP_TIMEOUT" and name in {"page_gate","sheet_state","sheet_closed"}
                    and self.read_timeout_reconciliations < 1):
                self.read_timeout_reconciliations += 1
                try:
                    raw = self.command(["eval","--stdin"],script=script)
                except ProbeFailed as retry_error:
                    retry_error.stage = name
                    raise
            else:
                exc.stage = name
                raise
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

class NativeBrowser(Browser):
    """One pinned CDP session for the existing fixed stages, never a writer."""
    def __init__(self, *args, popen=subprocess.Popen, **kwargs):
        super().__init__(*args, **kwargs)
        self.process = None
        self.closed = False
        self.popen = popen
        self.port = args[1]

    def stage(self, name: str, expected: dict) -> dict:
        self.last_stage = name
        if self.closed:
            raise ProbeFailed("FPL_PROBE_CDP_FAILED")
        remaining = self.deadline - self.clock() - 4
        cap = min(CALL_SECONDS, math.floor(remaining))
        if cap < 1:
            raise ProbeFailed("FPL_PROBE_CLOCK_EXPIRED")
        if self.process is None:
            self.process = self.popen([*self.prefix,"timeout","--signal=TERM","--kill-after=3s",
                f"{math.floor(remaining)}s","node","/opt/mova/pick-team-cdp-session.mjs",
                str(self.team_id),str(self.port)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, bufsize=1)
        try:
            self.process.stdin.write(json.dumps({"stage":name,"expected":expected,"cap_ms":cap*1000})+"\n")
            self.process.stdin.flush()
            if not select.select([self.process.stdout],[],[],min(cap+4,remaining))[0]:
                self.close()
                raise ProbeFailed("FPL_PROBE_CDP_TIMEOUT")
            raw = self.process.stdout.readline(1048577)
            if len(raw) > 1048576 or not raw.endswith("\n"):
                raise ProbeFailed("FPL_PROBE_RESPONSE_INVALID")
            response = json.loads(raw)
            if response.get("ok") is not True:
                allowed = {"FPL_AUTH_REQUIRED","FPL_PRIVATE_API_ERROR","FPL_BOOTSTRAP_API_ERROR",
                    "FPL_PICK_TEAM_PAGE_REQUIRED","FPL_AUTH_OR_ORIGIN_REQUIRED","FPL_STARTER_INDEX_INVALID",
                    "FPL_PLAYER_CONTROLS_CHANGED","FPL_CAPTAIN_CHECKBOX_MISSING",
                    "FPL_PLAYER_SHEET_CLOSE_MISSING_OR_AMBIGUOUS","FPL_PLAYER_SHEET_DID_NOT_CLOSE",
                    "FPL_TEAM_CHANGED_DURING_PROBE","FPL_PROBE_STAGE_INVALID","FPL_PROBE_CDP_TIMEOUT",
                    "FPL_PROBE_CDP_FAILED","FPL_PROBE_NAVIGATION_CONTEXT_LOST","FPL_PROBE_TARGET_AMBIGUOUS",
                    "FPL_PROBE_DIALOG_BLOCKED","FPL_PROBE_CLOCK_EXPIRED","FPL_PROBE_RESPONSE_INVALID"}
                code = response.get("error_code")
                raise ProbeFailed(code if isinstance(code,str) and code in allowed else "FPL_PROBE_CDP_FAILED")
            payload = response.get("payload")
            if not isinstance(payload,dict):
                raise ProbeFailed("FPL_PROBE_RESPONSE_INVALID")
            return payload
        except (OSError,ValueError,TypeError,AttributeError):
            raise ProbeFailed("FPL_PROBE_RESPONSE_INVALID") from None
        except ProbeFailed as exc:
            exc.stage = name
            raise

    def close(self):
        self.closed = True
        if self.process is None:
            return
        process, self.process = self.process, None
        try:
            process.stdin.close()
            process.wait(timeout=1)
        except (OSError,subprocess.TimeoutExpired):
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
        finally:
            process.stdout.close()

def starter_sheet(browser: Browser, expected: dict) -> dict:
    if browser.stage("open_sheet",expected).get("opened") is not True:
        raise ProbeFailed("FPL_PLAYER_CONTROLS_CHANGED")
    primary_error = None
    try:
        deadline = min(browser.deadline - 4, browser.clock()+10)
        while browser.clock() < deadline:
            response = browser.stage("sheet_state",expected)
            if response.get("available") is True:
                return {key:value for key,value in response.items() if key != "available"}
            browser.sleep(min(.25,max(0,deadline-browser.clock())))
        raise ProbeFailed("FPL_CAPTAIN_CHECKBOX_MISSING")
    except ProbeFailed as exc:
        primary_error = exc
        raise
    finally:
        try:
            if browser.stage("close_sheet",{}).get("close_requested") is not True:
                raise ProbeFailed("FPL_PLAYER_SHEET_CLOSE_MISSING_OR_AMBIGUOUS")
            deadline = min(browser.deadline - 4,browser.clock()+5)
            while browser.clock() < deadline:
                if browser.stage("sheet_closed",{}).get("closed") is True:
                    break
                browser.sleep(min(.25,max(0,deadline-browser.clock())))
            else:
                raise ProbeFailed("FPL_PLAYER_SHEET_DID_NOT_CLOSE")
        except ProbeFailed:
            if primary_error is None:
                raise

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
        starter = starter_sheet(browser, {"index":index,"element":row["element"],"web_name":row["web_name"]})
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
        browser = NativeBrowser(args.team_id,args.cdp_port)
        browser.navigate()
        payload = probe(browser,args.team_id)
    except (ProbeFailed,KeyError,TypeError,ValueError) as exc:
        code = str(exc) if isinstance(exc,ProbeFailed) else "FPL_PROBE_RESPONSE_INVALID"
        failed_stage = getattr(exc,"stage",browser.last_stage)
        diagnostic = None
        if failed_stage == "page_gate":
            try:
                diagnostic = browser.stage("diagnose",{})
            except ProbeFailed:
                pass
        print(json.dumps({"schema":"mova-browser-probe-error-v1","status":"fail","error_code":code,
                          "stage":failed_stage,"page":diagnostic}))
        return 1
    finally:
        if "browser" in locals():
            browser.close()
    print(json.dumps(payload,ensure_ascii=False))
    return 0 if payload["status"] == "pass" else 1

if __name__ == "__main__":
    raise SystemExit(main())
