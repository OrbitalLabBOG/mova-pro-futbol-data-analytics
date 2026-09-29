"""Financing evidence for retrospective closeout; never grants execution authority."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal

from mova_fpl.data.private_state import validate as validate_private

SCHEMA = "mova-closeout-financing-v1"


def digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode()).hexdigest()


def tenths(value: float) -> int:
    amount = Decimal(str(value)) * 10
    if not amount.is_finite() or amount != amount.to_integral_value() or amount < 0:
        raise ValueError("importe debe ser no negativo y exacto en décimas")
    return int(amount)


def _time(value: str) -> datetime:
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("financiación requiere timestamps con zona horaria")
    return result.astimezone(timezone.utc)


def build_financing(*, before: dict, before_source: dict, decision,
                    market_prices: dict[int, int], price_source: dict,
                    deadline_at: str, after: dict | None = None,
                    after_source: dict | None = None) -> dict:
    before, _ = validate_private(before)
    if after is not None:
        after, _ = validate_private(after, expected_team_id=before["team_id"])
    body = {
        "schema": SCHEMA, "deadline_at": deadline_at,
        "mode": "observed" if after is not None else "counterfactual",
        "before": before, "before_source": {k: before_source[k] for k in (
            "artifact_path", "manifest_sha256", "fingerprint")},
        "after": after, "after_source": ({k: after_source[k] for k in (
            "artifact_path", "manifest_sha256", "fingerprint")} if after_source else None),
        "market_prices_tenths": {str(k): v for k, v in market_prices.items()},
        "price_source": price_source,
        "decision_fingerprint": decision.fingerprint(),
        "bank_after_tenths": tenths(decision.bank_after),
        "reversion": ({"status": "pending_next_gameweek", "expected_state_sha256": digest(before)}
                      if decision.chip == "free_hit" else None),
    }
    result = {**body, "content_sha256": digest(body)}
    validate_financing(result, decision)
    return result


def validate_financing(certificate: dict, decision) -> dict:
    body = dict(certificate)
    sealed = body.pop("content_sha256", None)
    if body.get("schema") != SCHEMA or sealed != digest(body):
        raise ValueError("financiación ausente, incompatible o alterada")
    if body.get("decision_fingerprint") != decision.fingerprint():
        raise ValueError("financiación no pertenece a la decisión")
    before, quality = validate_private(body["before"])
    deadline = _time(body["deadline_at"])
    if (_time(before["observed_at"]) > deadline
            or int(before["event"]["id"]) != decision.gw
            or _time(before["event"]["deadline_time"]) != deadline):
        raise ValueError("estado inicial no pertenece al corte causal")
    source = body["before_source"]
    if (source.get("fingerprint") != quality["fingerprint"]
            or not source.get("artifact_path") or len(str(source.get("manifest_sha256", ""))) != 64):
        raise ValueError("estado inicial sin procedencia sellada")
    price_source = body["price_source"]
    if (not price_source.get("input_artifact_id") or not price_source.get("batch_id")
            or _time(price_source["cutoff_at"]) > deadline):
        raise ValueError("precios sin batch causal predeadline")
    owned = {int(p["element"]): p for p in before["picks"]}
    target = set(decision.squad_15)
    incoming, outgoing = set(decision.transfers_in), set(decision.transfers_out)
    if (len(incoming) != len(decision.transfers_in) or len(outgoing) != len(decision.transfers_out)
            or incoming != target - set(owned) or outgoing != set(owned) - target
            or len(target) != 15 or len(incoming) != len(outgoing)):
        raise ValueError("transferencias no reproducen los rosters")
    prices = body["market_prices_tenths"]
    if any(type(v) is not int or not 30 <= v <= 200 for v in prices.values()):
        raise ValueError("precios de mercado inválidos")
    if any(str(e) not in prices for e in incoming):
        raise ValueError("compra sin precio causal")
    sales = sum(int(owned[e]["selling_price"]) for e in outgoing)
    purchases = sum(prices[str(e)] for e in incoming)
    expected_bank = int(before["transfers"]["bank"]) + sales - purchases
    observed_bank = body.get("bank_after_tenths")
    if (type(observed_bank) is not int or observed_bank < 0 or observed_bank != expected_bank
            or observed_bank != tenths(decision.bank_after)):
        raise ValueError("banco no reconcilia ventas y compras")
    special = decision.chip in {"wildcard", "free_hit"}
    expected_hits = 0 if special else max(0, len(incoming) - quality["free_transfers"])
    if decision.hits != expected_hits:
        raise ValueError("hits no reconcilian libres y chip")
    after = body.get("after")
    if body.get("mode") == "observed":
        normalized, post_quality = validate_private(after, expected_team_id=before["team_id"])
        post_source = body.get("after_source") or {}
        if (post_source.get("fingerprint") != post_quality["fingerprint"]
                or not post_source.get("artifact_path")
                or len(str(post_source.get("manifest_sha256", ""))) != 64
                or _time(normalized["observed_at"]) < _time(before["observed_at"])
                or int(normalized["event"]["id"]) != decision.gw
                or _time(normalized["event"]["deadline_time"]) != deadline
                or normalized["transfers"]["bank"] != observed_bank):
            raise ValueError("estado posterior no acredita el banco/ciclo")
        if {int(p["element"]) for p in normalized["picks"]} != target:
            raise ValueError("estado posterior no acredita el roster")
        picks = normalized["picks"]
        if (set(int(p["element"]) for p in picks[:11]) != set(decision.starters)
                or tuple(int(p["element"]) for p in picks[11:]) != decision.bench_order
                or next(p["element"] for p in picks if p["is_captain"]) != decision.captain
                or next(p["element"] for p in picks if p["is_vice_captain"]) != decision.vice_captain):
            raise ValueError("estado posterior no acredita XI/capitán/banca")
        for p in normalized["picks"]:
            e = int(p["element"])
            expected_purchase = (owned[e]["purchase_price"] if e in owned else prices[str(e)])
            if int(p["purchase_price"]) != int(expected_purchase):
                raise ValueError("coste de compra posterior no reproduce la transición")
    elif body.get("mode") != "counterfactual" or after is not None or body.get("after_source"):
        raise ValueError("modo de financiación incompatible")
    reversion = body.get("reversion")
    if decision.chip == "free_hit":
        if reversion != {"status": "pending_next_gameweek", "expected_state_sha256": digest(before)}:
            raise ValueError("free hit sin contrato explícito de reversión")
    elif reversion is not None:
        raise ValueError("reversión incompatible con chip")
    return {"status": "verified_transition" if after else "verified_counterfactual",
            "bank_before_tenths": int(before["transfers"]["bank"]),
            "sales_tenths": sales, "purchases_tenths": purchases,
            "bank_after_tenths": observed_bank, "reversion": reversion}
