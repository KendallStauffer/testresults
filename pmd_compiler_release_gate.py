#!/usr/bin/env python3
"""PizzaMan Dan compiler release gate.

Purpose
-------
Prove the complete *declared compiler contract for one current menu snapshot*:

1. Every customer-facing item and selectable value exposed by the live tools is
   exercised directly against /grok-tool/compile-order-list.
2. Positive cases must compile with no missing question, no tool error, and an
   order_json result.
3. Negative required-choice cases must fail for the intentionally omitted
   choice and must not blame an unrelated choice.
4. Distinct exposed choices must produce distinct canonical compiler output.
5. Every case is deterministic across repeated calls.
6. Multi-row carts are invariant to input-row ordering.
7. The exact 2026-08-04 coupon-148 calzone/dip/salad regression is mandatory.
8. A fixed catalog snapshot is required for the entire run.
9. When /grok-tool/audit-menu-snapshot is available, exact private ID mappings
   are checked too. Without it, the run is reported as INCOMPLETE rather than a
   release PASS.

Safety
------
This program calls only read-only catalog/coupon/audit endpoints and the
compile-only endpoint. It never calls price, submit, payment, tokenization,
customer writes, address writes, or oneSystem directly.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import html
import json
import os
import random
import re
import sys
import time
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

try:
    import httpx
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Missing dependency: pip install 'httpx>=0.27,<1'") from exc

VERSION = "pmd-compiler-current-contract-release-gate-2026-08-04-v1"
DEFAULT_CATEGORIES = (
    "pizza",
    "calzone",
    "wings",
    "subs",
    "salads",
    "sides_appetizers",
    "desserts",
    "beverages",
)
DEFAULT_KNOWN_COUPONS = (91, 146, 147, 148, 149, 150, 151, 152, 999)
OPTION_ONLY_CHOICE_TYPES = {
    "calzone_dip",
    "salad_dressing",
    "wing_sauce",
    "pizza_topping",
    "dressing",
    "sauce",
}
LOGICAL_FAILURE_KEYS = (
    "error",
    "detail",
    "message",
    "error_code",
    "first_missing_question",
    "missing_questions",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def slug(value: Any) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "")).strip("_").lower()
    return text[:100] or "unnamed"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()



def int_or_none(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except Exception:
        return None

def deep_get(value: Any, *keys: str) -> Any:
    cur = value
    for key in keys:
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(key)
    return cur


def first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set, frozenset)):
        return list(value)
    return [value]


def unique_strings(values: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, Mapping):
            text = str(first_present(value.get("name"), value.get("display_name"), value.get("item_name"), value.get("label")) or "").strip()
        else:
            text = str(value or "").strip()
        key = norm(text)
        # Customer-safe tools must expose names, never raw oneSystem IDs. Do
        # not turn an unexpected numeric value into a fake customer choice.
        if re.fullmatch(r"[+-]?\d+", text):
            continue
        if text and key and key not in seen:
            seen.add(key)
            out.append(text)
    return out


def iter_dicts(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_dicts(child)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, child in value.items():
            if norm(key) in {
                "api key",
                "authorization",
                "account",
                "card number",
                "token",
                "payment token",
            }:
                out[key] = "[REDACTED]"
            else:
                out[key] = redact(child)
        return out
    if isinstance(value, list):
        return [redact(child) for child in value]
    return value


def compiler_output(response: Mapping[str, Any]) -> dict[str, Any] | None:
    raw = response.get("order_json")
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None
    return raw if isinstance(raw, dict) else None


def canonical_order(response: Mapping[str, Any]) -> dict[str, Any] | None:
    order = compiler_output(response)
    if not order:
        return None
    out = deepcopy(order)
    # Line numbers are assigned by output ordering and do not represent a
    # semantic cart difference. Remove them before determinism/reorder checks.
    for section in ("pizzas", "menu_items", "beverages", "coupons"):
        rows = out.get(section)
        if not isinstance(rows, list):
            continue
        cleaned = []
        for row in rows:
            if isinstance(row, dict):
                row = dict(row)
                row.pop("line", None)
                row.pop("package", None)
                for list_key in ("topping_ids", "modifier_ids", "instruction_ids", "pizza_instructions"):
                    if isinstance(row.get(list_key), list):
                        row[list_key] = sorted(row[list_key], key=lambda x: str(x))
            cleaned.append(row)
        out[section] = sorted(cleaned, key=canonical_json)
    return out


def order_fingerprint(response: Mapping[str, Any]) -> str | None:
    order = canonical_order(response)
    return sha256_json(order) if order is not None else None


def response_failure_text(response: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in LOGICAL_FAILURE_KEYS:
        value = response.get(key)
        if value not in (None, "", [], {}):
            parts.append(f"{key}={value}")
    return " | ".join(parts)[:4000]


def snapshots_in(value: Any) -> set[str]:
    found: set[str] = set()
    for row in iter_dicts(value):
        snap = row.get("catalog_snapshot") or row.get("snapshot_id")
        if snap:
            found.add(str(snap))
    return found


def versions_in(value: Any) -> set[str]:
    found: set[str] = set()
    for row in iter_dicts(value):
        for key in ("catalog_version", "compiler_version", "audit_version", "version"):
            v = row.get(key)
            if v and isinstance(v, (str, int, float)):
                found.add(str(v))
    return found


def contains_id_at(order: Mapping[str, Any], path_kind: str, expected_id: int) -> bool:
    expected_id = int(expected_id)
    if path_kind == "pizza_size":
        return any(int_or_none(row.get("size_id")) == expected_id for row in as_list(order.get("pizzas")) if isinstance(row, dict))
    if path_kind == "pizza_crust":
        return any(int_or_none(row.get("type_id")) == expected_id for row in as_list(order.get("pizzas")) if isinstance(row, dict))
    if path_kind == "pizza_combo":
        return any(int_or_none(row.get("combo_id")) == expected_id for row in as_list(order.get("pizzas")) if isinstance(row, dict))
    if path_kind == "pizza_topping":
        return any(expected_id in {int(x) for x in as_list(row.get("topping_ids")) if str(x).lstrip("-").isdigit()} for row in as_list(order.get("pizzas")) if isinstance(row, dict))
    if path_kind == "pizza_instruction":
        return any(expected_id in {int(x) for x in as_list(first_present(row.get("pizza_instructions"), row.get("instruction_ids"))) if str(x).lstrip("-").isdigit()} for row in as_list(order.get("pizzas")) if isinstance(row, dict))
    if path_kind == "menu_item":
        return any(int_or_none(row.get("id")) == expected_id for row in as_list(order.get("menu_items")) if isinstance(row, dict))
    if path_kind == "modifier":
        return any(expected_id in {int(x) for x in as_list(row.get("modifier_ids")) if str(x).lstrip("-").isdigit()} for row in as_list(order.get("menu_items")) if isinstance(row, dict))
    if path_kind == "beverage_type":
        return any(int_or_none(row.get("beverage_type_id")) == expected_id for row in as_list(order.get("beverages")) if isinstance(row, dict))
    if path_kind == "beverage_size":
        return any(int_or_none(row.get("beverage_size_id")) == expected_id for row in as_list(order.get("beverages")) if isinstance(row, dict))
    if path_kind == "coupon":
        return any(int_or_none(row.get("id")) == expected_id for row in as_list(order.get("coupons")) if isinstance(row, dict))
    if path_kind == "pizza_quantity":
        return sum(int(row.get("quantity") or 1) for row in as_list(order.get("pizzas")) if isinstance(row, dict)) == expected_id
    if path_kind == "menu_item_quantity":
        return sum(int(row.get("quantity") or 1) for row in as_list(order.get("menu_items")) if isinstance(row, dict)) == expected_id
    if path_kind == "beverage_quantity":
        return sum(int(row.get("quantity") or 1) for row in as_list(order.get("beverages")) if isinstance(row, dict)) == expected_id
    if path_kind == "coupon_count":
        return sum(1 for row in as_list(order.get("coupons")) if isinstance(row, dict)) == expected_id
    return False


@dataclass(frozen=True)
class ExpectedProbe:
    source: str
    name: str
    path_kind: str
    expected_id: int | None = None


@dataclass
class TestCase:
    name: str
    group: str
    payload: dict[str, Any]
    expected_ok: bool = True
    expected_missing_contains: list[str] = field(default_factory=list)
    forbidden_missing_contains: list[str] = field(default_factory=list)
    probes: list[ExpectedProbe] = field(default_factory=list)
    coverage_tokens: set[str] = field(default_factory=set)
    distinct_family: str | None = None
    distinct_value: str | None = None
    reorder_check: bool = False
    notes: str = ""


@dataclass
class CaseResult:
    case: str
    group: str
    passed: bool
    mandatory: bool
    http_status: int | None
    compile_ok: bool | None
    fingerprint: str | None
    snapshot: str | None
    elapsed_ms: int
    failures: list[str]
    notes: str
    payload: dict[str, Any]
    response: dict[str, Any]
    repeat_fingerprints: list[str | None] = field(default_factory=list)


@dataclass
class GateSummary:
    version: str
    started_at: str
    finished_at: str
    store_number: int
    order_type: str
    catalog_snapshot: str | None
    catalog_versions: list[str]
    compiler_versions: list[str]
    audit_available: bool
    audit_exact_mapping_enabled: bool
    tests_total: int
    tests_passed: int
    tests_failed: int
    mandatory_failed: int
    coverage_expected: int
    coverage_tested: int
    coverage_missing: list[str]
    duplicate_output_collisions: int
    status: str
    exit_code: int
    safety: dict[str, Any]


class BackendClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        header_name: str,
        *,
        timeout: float,
        transport_retries: int,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.header_name = header_name
        self.transport_retries = max(0, transport_retries)
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={header_name: api_key, "content-type": "application/json"},
            timeout=httpx.Timeout(timeout, connect=min(timeout, 30.0)),
            follow_redirects=True,
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def post(self, path: str, payload: Mapping[str, Any]) -> tuple[int | None, dict[str, Any], int]:
        last_error = ""
        for attempt in range(self.transport_retries + 1):
            started = time.monotonic()
            try:
                response = await self.client.post(path, json=dict(payload))
                elapsed_ms = int((time.monotonic() - started) * 1000)
                try:
                    data = response.json()
                except Exception:
                    data = {"ok": False, "non_json_response": response.text[:4000]}
                if not isinstance(data, dict):
                    data = {"ok": False, "unexpected_json": data}
                if response.status_code in {429, 500, 502, 503, 504} and attempt < self.transport_retries:
                    await asyncio.sleep(min(2 ** attempt, 5))
                    continue
                return response.status_code, data, elapsed_ms
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                elapsed_ms = int((time.monotonic() - started) * 1000)
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < self.transport_retries:
                    await asyncio.sleep(min(2 ** attempt, 5))
                    continue
                return None, {"ok": False, "transport_error": last_error}, elapsed_ms
        return None, {"ok": False, "transport_error": last_error or "unknown transport error"}, 0


class SnapshotGuard:
    def __init__(self) -> None:
        self.snapshot: str | None = None
        self.mismatches: list[str] = []
        self.versions: set[str] = set()

    def observe(self, source: str, response: Mapping[str, Any]) -> None:
        self.versions.update(versions_in(response))
        snaps = snapshots_in(response)
        if not snaps:
            return
        if len(snaps) > 1:
            self.mismatches.append(f"{source}: response contained multiple snapshots {sorted(snaps)}")
        for snap in snaps:
            if self.snapshot is None:
                self.snapshot = snap
            elif self.snapshot != snap:
                self.mismatches.append(f"{source}: snapshot changed from {self.snapshot} to {snap}")


class AuditMappings:
    def __init__(self, audit_response: Mapping[str, Any] | None) -> None:
        self.available = bool(audit_response and audit_response.get("ok") is True)
        self.response = dict(audit_response or {})
        self.mappings: dict[str, dict[str, int]] = {}
        self.identifier_sets: dict[str, set[int]] = {}
        self.fixed_ids: dict[str, int | None] = {}
        if not self.available:
            return
        raw = deep_get(self.response, "compiler", "mappings") or {}
        if isinstance(raw, dict):
            for map_name, entries in raw.items():
                if not isinstance(entries, dict):
                    continue
                clean: dict[str, int] = {}
                for key, value in entries.items():
                    try:
                        clean[norm(key)] = int(value)
                    except Exception:
                        continue
                self.mappings[str(map_name)] = clean
        raw_sets = deep_get(self.response, "compiler", "identifier_sets") or {}
        if isinstance(raw_sets, dict):
            for set_name, entries in raw_sets.items():
                clean_set: set[int] = set()
                for value in as_list(entries):
                    try:
                        clean_set.add(int(value))
                    except Exception:
                        continue
                self.identifier_sets[str(set_name)] = clean_set
        raw_fixed = deep_get(self.response, "compiler", "fixed_ids") or {}
        if isinstance(raw_fixed, dict):
            for key, value in raw_fixed.items():
                try:
                    self.fixed_ids[str(key)] = int(value) if value is not None else None
                except Exception:
                    self.fixed_ids[str(key)] = None

    def resolve(self, map_names: Sequence[str], name: str) -> int | None:
        key = norm(name)
        variants = [key]
        for prefix in ("w ", "with "):
            if key.startswith(prefix):
                variants.append(key[len(prefix):])
        for suffix in (" pizza", " calzone"):
            if key.endswith(suffix):
                variants.append(key[:-len(suffix)].strip())
        # A current specialty may be exposed as either Pizza or Calzone while
        # sharing one private combo mapping. Try both customer-facing suffixes.
        if key.endswith(" pizza"):
            variants.append(key[:-6].strip() + " calzone")
        if key.endswith(" calzone"):
            variants.append(key[:-8].strip() + " pizza")
        for map_name in map_names:
            mapping = self.mappings.get(map_name, {})
            for variant in variants:
                value = mapping.get(variant)
                if value is not None:
                    return value
        return None

    def in_set(self, set_name: str, value: int | None) -> bool:
        return value is not None and int(value) in self.identifier_sets.get(set_name, set())

    def fixed(self, name: str) -> int | None:
        return self.fixed_ids.get(name)


class Coverage:
    def __init__(self) -> None:
        self.expected: set[str] = set()
        self.tested: set[str] = set()

    def expect(self, token: str) -> None:
        self.expected.add(token)

    def mark_case(self, case: TestCase) -> None:
        self.tested.update(case.coverage_tokens)

    @property
    def missing(self) -> list[str]:
        return sorted(self.expected - self.tested)


def unwrap_catalog(response: Mapping[str, Any]) -> dict[str, Any]:
    # Some generations return category data at the top; others put a category
    # object inside items. Preserve all top-level metadata while preferring the
    # nested category object for lists.
    result = dict(response)
    nested = response.get("items")
    if isinstance(nested, dict):
        merged = dict(response)
        merged.update(nested)
        return merged
    return result


def rows_from(payload: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if isinstance(value, list):
        return [dict(row) for row in value if isinstance(row, dict)]
    return []


def names_from(payload: Mapping[str, Any], *keys: str) -> list[str]:
    values: list[Any] = []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, dict):
            values.extend(value.values())
        else:
            values.extend(as_list(value))
    return unique_strings(values)


def item_name(row: Mapping[str, Any]) -> str:
    return str(first_present(row.get("name"), row.get("display_name"), row.get("item_name"), row.get("raw_name")) or "").strip()


def row_options(row: Mapping[str, Any]) -> list[str]:
    return unique_strings(first_present(row.get("options"), row.get("option_names"), row.get("choices")) or [])


def add_case(cases: list[TestCase], coverage: Coverage, case: TestCase) -> None:
    # No case is allowed to send private IDs.
    forbidden_key_pattern = re.compile(r"(^|_)(id|ids)$", re.I)
    for row in iter_dicts(case.payload):
        for key in row:
            if forbidden_key_pattern.search(str(key)) and key not in {"store_number"}:
                raise ValueError(f"Case {case.name} attempts to send private field {key}")
    cases.append(case)
    coverage.mark_case(case)


def base_payload(args: argparse.Namespace, items: list[dict[str, Any]], *, coupon_numbers: list[int] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "store_number": args.store_number,
        "order_type": args.order_type,
        "phone": args.phone,
        "customer_name": args.customer_name,
        "items": items,
    }
    if coupon_numbers:
        payload["coupon_numbers"] = [int(x) for x in coupon_numbers]
    return payload


def probe(mapping: AuditMappings, source: str, name: str, map_names: Sequence[str], path_kind: str) -> ExpectedProbe:
    return ExpectedProbe(source=source, name=name, path_kind=path_kind, expected_id=mapping.resolve(map_names, name))


def valid_crusts_by_size(pizza: Mapping[str, Any]) -> dict[str, list[str]]:
    raw = pizza.get("crusts_by_size") or pizza.get("allowed_crusts_by_size") or {}
    out: dict[str, list[str]] = {}
    if isinstance(raw, dict):
        for size_name, values in raw.items():
            names = unique_strings(values if isinstance(values, list) else as_list(values))
            if names:
                out[str(size_name)] = names
    if not out:
        sizes = names_from(pizza, "sizes")
        crusts = names_from(pizza, "crusts")
        for size in sizes:
            out[size] = crusts
    return out


def first_size_crust(pizza: Mapping[str, Any]) -> tuple[str | None, str | None]:
    by_size = valid_crusts_by_size(pizza)
    for size, crusts in by_size.items():
        if crusts:
            return size, crusts[0]
    return None, None


def pizza_build_name(pizza: Mapping[str, Any]) -> str:
    candidates = names_from(pizza, "items")
    for name in candidates:
        if "build your own" in norm(name):
            return name
    return "Build Your Own Pizza"


def specialty_names(pizza: Mapping[str, Any]) -> list[str]:
    return names_from(pizza, "specialty_pizzas", "specialties")


def generate_pizza_cases(
    args: argparse.Namespace,
    pizza: Mapping[str, Any],
    mapping: AuditMappings,
    coverage: Coverage,
) -> list[TestCase]:
    cases: list[TestCase] = []
    build_name = pizza_build_name(pizza)
    by_size = valid_crusts_by_size(pizza)
    toppings = names_from(pizza, "toppings")
    sauces = names_from(pizza, "sauces", "pizza_sauces")
    styles = names_from(pizza, "cheese_and_sauce_style")
    instructions = names_from(pizza, "pizza_instructions", "instructions")
    specialty_rows = rows_from(pizza, "specialty_pizzas") or rows_from(pizza, "specialties")
    specialties = [item_name(row) for row in specialty_rows if item_name(row)]

    def anchor_topping_for_size(size: str) -> str | None:
        if "slice" in norm(size):
            return next((x for x in toppings if "pepperoni" in norm(x)), toppings[0] if toppings else None)
        return next((x for x in toppings if norm(x) not in {norm(s) for s in sauces}), toppings[0] if toppings else None)

    # Every declared size/crust pair must compile. A Build Your Own pizza needs
    # a real topping (or an explicit plain-cheese combo), so the gate supplies a
    # valid live topping rather than accidentally testing an incomplete cart.
    for size, crusts in by_size.items():
        coverage.expect(f"pizza:size:{norm(size)}")
        anchor = anchor_topping_for_size(size)
        for crust in crusts:
            coverage.expect(f"pizza:crust_for_size:{norm(size)}:{norm(crust)}")
            row: dict[str, Any] = {"category": "pizza", "item_name": build_name, "size": size, "crust": crust}
            if anchor:
                row["whole_toppings"] = [anchor]
            else:
                row["item_name"] = "Ultimate 4-Cheese"
            case = TestCase(
                name=f"pizza_size_crust__{slug(size)}__{slug(crust)}",
                group="pizza.size_crust",
                payload=base_payload(args, [row]),
                probes=[
                    probe(mapping, "SIZE_BY_NAME", size, ("SIZE_BY_NAME",), "pizza_size"),
                    probe(mapping, "CRUST_BY_NAME", crust, ("CRUST_BY_NAME",), "pizza_crust"),
                ],
                coverage_tokens={
                    f"pizza:size:{norm(size)}",
                    f"pizza:crust_for_size:{norm(size)}:{norm(crust)}",
                },
                distinct_family=f"pizza:crust:{norm(size)}",
                distinct_value=crust,
            )
            add_case(cases, coverage, case)

    base_size, base_crust = first_size_crust(pizza)
    base_anchor = anchor_topping_for_size(base_size or "")
    if base_size and base_crust:
        for topping in toppings:
            coverage.expect(f"pizza:topping:{norm(topping)}")
            row = {
                "category": "pizza",
                "item_name": build_name,
                "size": base_size,
                "crust": base_crust,
                "whole_toppings": [topping],
            }
            add_case(cases, coverage, TestCase(
                name=f"pizza_topping__{slug(topping)}",
                group="pizza.topping",
                payload=base_payload(args, [row]),
                probes=[probe(mapping, "PIZZA_TOPPING_BY_NAME", topping, ("PIZZA_TOPPING_BY_NAME", "TOPPING_BY_NAME"), "pizza_topping")],
                coverage_tokens={f"pizza:topping:{norm(topping)}"},
                distinct_family="pizza:toppings",
                distinct_value=topping,
            ))

        for sauce in sauces:
            coverage.expect(f"pizza:sauce:{norm(sauce)}")
            row = {
                "category": "pizza",
                "item_name": build_name,
                "size": base_size,
                "crust": base_crust,
                "sauce": sauce,
            }
            if base_anchor:
                row["whole_toppings"] = [base_anchor]
            add_case(cases, coverage, TestCase(
                name=f"pizza_sauce__{slug(sauce)}",
                group="pizza.sauce",
                payload=base_payload(args, [row]),
                probes=[probe(mapping, "PIZZA_SAUCE_CHOICE_BY_NAME", sauce, ("PIZZA_SAUCE_CHOICE_BY_NAME", "SAUCE_BY_NAME", "PIZZA_TOPPING_BY_NAME"), "pizza_topping")],
                coverage_tokens={f"pizza:sauce:{norm(sauce)}"},
                distinct_family="pizza:sauces",
                distinct_value=sauce,
            ))

        for style in styles:
            coverage.expect(f"pizza:style:{norm(style)}")
            row = {
                "category": "pizza",
                "item_name": build_name,
                "size": base_size,
                "crust": base_crust,
                "option_names": [style],
            }
            if base_anchor:
                row["whole_toppings"] = [base_anchor]
            add_case(cases, coverage, TestCase(
                name=f"pizza_style__{slug(style)}",
                group="pizza.style",
                payload=base_payload(args, [row]),
                probes=[probe(mapping, "SAUCE_ADJUSTMENT_BY_NAME", style, ("SAUCE_ADJUSTMENT_BY_NAME", "TOPPING_BY_NAME"), "pizza_topping")],
                coverage_tokens={f"pizza:style:{norm(style)}"},
                distinct_family="pizza:styles",
                distinct_value=style,
            ))

        for instruction in instructions:
            coverage.expect(f"pizza:instruction:{norm(instruction)}")
            row = {
                "category": "pizza",
                "item_name": build_name,
                "size": base_size,
                "crust": base_crust,
                "instructions": [instruction],
            }
            if base_anchor:
                row["whole_toppings"] = [base_anchor]
            add_case(cases, coverage, TestCase(
                name=f"pizza_instruction__{slug(instruction)}",
                group="pizza.instruction",
                payload=base_payload(args, [row]),
                probes=[probe(mapping, "INSTRUCTION_BY_NAME", instruction, ("INSTRUCTION_BY_NAME",), "pizza_instruction")],
                coverage_tokens={f"pizza:instruction:{norm(instruction)}"},
                distinct_family="pizza:instructions",
                distinct_value=instruction,
            ))

        # Specialty sizes may be narrower than the category-wide size list.
        # Respect any row-level live size declaration; never manufacture an
        # invalid specialty/size pair.
        for specialty_row in specialty_rows:
            specialty = item_name(specialty_row)
            if not specialty:
                continue
            coverage.expect(f"pizza:specialty:{norm(specialty)}")
            declared_sizes = unique_strings(first_present(
                specialty_row.get("sizes"),
                specialty_row.get("available_sizes"),
                specialty_row.get("size_names"),
            ) or [])
            allowed_size_keys = [
                size for size in by_size
                if not declared_sizes or norm(size) in {norm(x) for x in declared_sizes}
            ]
            if not allowed_size_keys:
                allowed_size_keys = list(by_size)
            for size in allowed_size_keys:
                for crust in by_size.get(size, []):
                    row = {"category": "pizza", "item_name": specialty, "size": size, "crust": crust}
                    add_case(cases, coverage, TestCase(
                        name=f"pizza_specialty__{slug(specialty)}__{slug(size)}__{slug(crust)}",
                        group="pizza.specialty",
                        payload=base_payload(args, [row]),
                        probes=[
                            probe(mapping, "SPECIALTY_BY_NAME", specialty, ("SPECIALTY_BY_NAME",), "pizza_combo"),
                            probe(mapping, "SIZE_BY_NAME", size, ("SIZE_BY_NAME",), "pizza_size"),
                            probe(mapping, "CRUST_BY_NAME", crust, ("CRUST_BY_NAME",), "pizza_crust"),
                        ],
                        coverage_tokens={f"pizza:specialty:{norm(specialty)}"},
                        distinct_family=f"pizza:specialty:{norm(size)}:{norm(crust)}",
                        distinct_value=specialty,
                    ))

            # Exercise every explicit specialty removal the live recipe exposes.
            included = unique_strings(first_present(
                specialty_row.get("included_toppings"),
                specialty_row.get("toppings"),
                specialty_row.get("recipe"),
            ) or [])
            for removed in included:
                token = f"pizza:specialty_remove:{norm(specialty)}:{norm(removed)}"
                coverage.expect(token)
                add_case(cases, coverage, TestCase(
                    name=f"pizza_specialty_remove__{slug(specialty)}__{slug(removed)}",
                    group="pizza.specialty_remove",
                    payload=base_payload(args, [{
                        "category": "pizza",
                        "item_name": specialty,
                        "size": base_size,
                        "crust": base_crust,
                        "remove_toppings": [removed],
                    }]),
                    probes=[probe(mapping, "SPECIALTY_BY_NAME", specialty, ("SPECIALTY_BY_NAME",), "pizza_combo")],
                    coverage_tokens={token},
                    distinct_family=f"pizza:specialty_remove:{norm(specialty)}",
                    distinct_value=removed,
                ))

        # Every topping is tested through the add_toppings field on a specialty,
        # which is a separate compiler path from Build Your Own whole_toppings.
        if specialty_rows:
            specialty = item_name(specialty_rows[0])
            for topping in toppings:
                token = f"pizza:specialty_add:{norm(topping)}"
                coverage.expect(token)
                add_case(cases, coverage, TestCase(
                    name=f"pizza_specialty_add__{slug(topping)}",
                    group="pizza.specialty_add",
                    payload=base_payload(args, [{
                        "category": "pizza",
                        "item_name": specialty,
                        "size": base_size,
                        "crust": base_crust,
                        "add_toppings": [topping],
                    }]),
                    probes=[
                        probe(mapping, "SPECIALTY_BY_NAME", specialty, ("SPECIALTY_BY_NAME",), "pizza_combo"),
                        probe(mapping, "PIZZA_TOPPING_BY_NAME", topping, ("PIZZA_TOPPING_BY_NAME", "TOPPING_BY_NAME"), "pizza_topping"),
                    ],
                    coverage_tokens={token},
                    distinct_family=f"pizza:specialty_add:{norm(specialty)}",
                    distinct_value=topping,
                ))

        # Metamorphic half-and-half coverage: every topping must survive on the
        # first half and the second half at least once.
        if toppings:
            anchor = toppings[0]
            for topping in toppings:
                coverage.expect(f"pizza:first_half:{norm(topping)}")
                coverage.expect(f"pizza:second_half:{norm(topping)}")
                row = {
                    "category": "pizza",
                    "item_name": build_name,
                    "size": base_size,
                    "crust": base_crust,
                    "first_half_toppings": [topping],
                    "second_half_toppings": [anchor if norm(anchor) != norm(topping) else (toppings[1] if len(toppings) > 1 else topping)],
                }
                add_case(cases, coverage, TestCase(
                    name=f"pizza_half__{slug(topping)}",
                    group="pizza.half",
                    payload=base_payload(args, [row]),
                    coverage_tokens={f"pizza:first_half:{norm(topping)}", f"pizza:second_half:{norm(topping)}"},
                    distinct_family="pizza:half",
                    distinct_value=topping,
                ))

        # Quantity preservation is a separate compiler contract. Use one valid
        # Build Your Own configuration and require an aggregate quantity of 2.
        qty_row: dict[str, Any] = {
            "category": "pizza",
            "item_name": build_name,
            "size": base_size,
            "crust": base_crust,
            "quantity": 2,
        }
        if base_anchor:
            qty_row["whole_toppings"] = [base_anchor]
        add_case(cases, coverage, TestCase(
            name="pizza_quantity_two_preserved",
            group="pizza.quantity",
            payload=base_payload(args, [qty_row]),
            probes=[ExpectedProbe("quantity", "2", "pizza_quantity", 2)],
            notes="Quantity 2 must not collapse to one line/one item",
        ))

        # Unknown names must be rejected rather than silently dropped.
        add_case(cases, coverage, TestCase(
            name="pizza_unknown_topping_rejected",
            group="pizza.negative_unknown",
            payload=base_payload(args, [{
                "category": "pizza",
                "item_name": build_name,
                "size": base_size,
                "crust": base_crust,
                "whole_toppings": ["__RELEASE_GATE_UNKNOWN_TOPPING__"],
            }]),
            expected_ok=False,
            notes="A made-up topping may never be ignored while returning ok:true",
        ))

    return cases

def all_standard_options(payload: Mapping[str, Any], category: str) -> list[str]:
    keys_by_category = {
        "salads": ("dressings", "options"),
        "wings": ("wing_sauces", "options"),
        "calzone": ("dips", "calzone_dips", "options"),
        "subs": ("common_options", "pizza_burger_options", "options"),
        "sides_appetizers": ("options",),
        "desserts": ("options",),
    }
    return names_from(payload, *keys_by_category.get(category, ("options",)))


def generate_standard_cases(
    args: argparse.Namespace,
    category: str,
    payload: Mapping[str, Any],
    mapping: AuditMappings,
    coverage: Coverage,
) -> list[TestCase]:
    cases: list[TestCase] = []
    item_rows = rows_from(payload, "items")
    global_options = all_standard_options(payload, category)
    instructions = names_from(payload, "wing_instructions") if category == "wings" else []

    map_names_by_category = {
        "wings": ("WING_ITEM_BY_NAME",),
        "subs": ("SUB_ITEM_BY_NAME",),
        "salads": ("SALAD_ITEM_BY_NAME",),
        "sides_appetizers": ("SIDE_ITEM_BY_NAME",),
        "desserts": ("DESSERT_BY_NAME",),
    }
    option_map_names = {
        "calzone": ("CALZONE_DIP_EXACT_BY_NAME", "SIDE_ITEM_BY_NAME"),
        "wings": ("WING_SAUCE_BY_NAME",),
        "subs": ("SUB_OPTION_BY_NAME",),
        "salads": ("DRESSING_BY_NAME",),
        "sides_appetizers": ("SIDE_OPTION_BY_NAME", "SIDE_OF_OPTION_BY_NAME", "SIDE_OF_DRESSING_OPTION_BY_NAME"),
        "desserts": ("SIDE_OPTION_BY_NAME",),
    }

    def options_for(row: Mapping[str, Any], name: str) -> list[str]:
        direct = row_options(row)
        if direct:
            return direct
        if category in {"calzone", "wings"}:
            return global_options
        if category == "subs":
            if "pizza burger" in norm(name):
                return names_from(payload, "pizza_burger_options") or names_from(payload, "common_options")
            return names_from(payload, "common_options")
        if category == "salads":
            item_id = mapping.resolve(("SALAD_ITEM_BY_NAME",), name)
            if mapping.in_set("SALAD_ITEM_IDS_REQUIRING_DRESSING", item_id):
                return names_from(payload, "dressings", "options")
        # Side/dessert options must be attached to the exact item by the live
        # catalog. A category-wide list is not assumed to apply to every row.
        return []

    def requires_option(row: Mapping[str, Any], name: str, options: list[str]) -> bool:
        if category in {"calzone", "wings"}:
            return True
        if category == "salads":
            item_id = mapping.resolve(("SALAD_ITEM_BY_NAME",), name)
            return bool(options) and (
                bool(row_options(row))
                or mapping.in_set("SALAD_ITEM_IDS_REQUIRING_DRESSING", item_id)
                or bool(row.get("requires"))
            )
        if category == "sides_appetizers":
            key = norm(name)
            return bool(options) and (
                bool(row.get("requires"))
                or bool(row.get("option_required"))
                or "wedge" in key
                or "side of dressing" in key
                or "side of sauce" in key
            )
        return False

    def item_probes(name: str) -> list[ExpectedProbe]:
        if category == "calzone":
            probes: list[ExpectedProbe] = []
            combo_id = mapping.resolve(("SPECIALTY_BY_NAME",), name)
            if combo_id is not None:
                probes.append(ExpectedProbe("SPECIALTY_BY_NAME", name, "pizza_combo", combo_id))
            calzone_size = mapping.fixed("calzone_size_id")
            calzone_crust = mapping.fixed("calzone_crust_id")
            if calzone_size is not None:
                probes.append(ExpectedProbe("calzone_size_id", name, "pizza_size", calzone_size))
            if calzone_crust is not None:
                probes.append(ExpectedProbe("calzone_crust_id", name, "pizza_crust", calzone_crust))
            return probes
        return [probe(mapping, "item", name, map_names_by_category.get(category, ()), "menu_item")]

    def option_probe(option: str) -> ExpectedProbe:
        if category == "calzone":
            return probe(mapping, "CALZONE_DIP_EXACT_BY_NAME", option, option_map_names[category], "menu_item")
        return probe(mapping, "option", option, option_map_names.get(category, ()), "modifier")

    first_valid_item: dict[str, Any] | None = None
    first_valid_name = ""
    first_quantity_kind = "menu_item_quantity"

    for row in item_rows:
        name = item_name(row)
        if not name:
            continue
        coverage.expect(f"{category}:item:{norm(name)}")
        options = options_for(row, name)
        needs_option = requires_option(row, name, options)

        if not needs_option:
            item = {"category": category, "item_name": name}
            add_case(cases, coverage, TestCase(
                name=f"{slug(category)}_item__{slug(name)}__default",
                group=f"{category}.item",
                payload=base_payload(args, [item]),
                probes=item_probes(name),
                coverage_tokens={f"{category}:item:{norm(name)}"},
                distinct_family=f"{category}:items",
                distinct_value=name,
            ))
            if first_valid_item is None:
                first_valid_item = deepcopy(item)
                first_valid_name = name
                first_quantity_kind = "pizza_quantity" if category == "calzone" else "menu_item_quantity"

        for option in options:
            coverage.expect(f"{category}:option:{norm(name)}:{norm(option)}")
            item = {"category": category, "item_name": name, "option_names": [option]}
            add_case(cases, coverage, TestCase(
                name=f"{slug(category)}_item__{slug(name)}__option__{slug(option)}",
                group=f"{category}.option",
                payload=base_payload(args, [item]),
                probes=item_probes(name) + [option_probe(option)],
                coverage_tokens={f"{category}:item:{norm(name)}", f"{category}:option:{norm(name)}:{norm(option)}"},
                distinct_family=f"{category}:options:{norm(name)}",
                distinct_value=option,
            ))
            if first_valid_item is None:
                first_valid_item = deepcopy(item)
                first_valid_name = name
                first_quantity_kind = "pizza_quantity" if category == "calzone" else "menu_item_quantity"

        if needs_option:
            if not options:
                # A required-choice item with no exposed choices is itself a
                # contract failure; make it visible instead of skipping it.
                add_case(cases, coverage, TestCase(
                    name=f"{slug(category)}_item__{slug(name)}__required_options_not_exposed",
                    group=f"{category}.catalog_contract",
                    payload=base_payload(args, [{"category": category, "item_name": name}]),
                    expected_ok=False,
                    expected_missing_contains=["__choices_not_exposed__"],
                    notes="Live catalog declared a required option but exposed no customer-facing choices",
                ))
            else:
                expected_word = {
                    "calzone": "dip",
                    "wings": "sauce",
                    "salads": "dressing",
                    "sides_appetizers": "choice",
                }[category]
                add_case(cases, coverage, TestCase(
                    name=f"{slug(category)}_item__{slug(name)}__missing_required_{expected_word}",
                    group=f"{category}.negative",
                    payload=base_payload(args, [{"category": category, "item_name": name}]),
                    expected_ok=False,
                    expected_missing_contains=[expected_word],
                    notes="Negative required-choice guard",
                ))

        if category == "wings" and instructions:
            anchor_options = options
            if anchor_options:
                for instruction in instructions:
                    coverage.expect(f"wings:instruction:{norm(name)}:{norm(instruction)}")
                    item = {
                        "category": category,
                        "item_name": name,
                        "option_names": [anchor_options[0]],
                        "instructions": [instruction],
                    }
                    add_case(cases, coverage, TestCase(
                        name=f"wings_item__{slug(name)}__instruction__{slug(instruction)}",
                        group="wings.instruction",
                        payload=base_payload(args, [item]),
                        probes=item_probes(name) + [
                            option_probe(anchor_options[0]),
                            probe(mapping, "WING_INSTRUCTION_BY_NAME", instruction, ("WING_INSTRUCTION_BY_NAME",), "modifier"),
                        ],
                        coverage_tokens={f"wings:instruction:{norm(name)}:{norm(instruction)}"},
                        distinct_family=f"wings:instructions:{norm(name)}",
                        distinct_value=instruction,
                    ))

    if first_valid_item is not None:
        quantity_item = deepcopy(first_valid_item)
        quantity_item["quantity"] = 2
        add_case(cases, coverage, TestCase(
            name=f"{slug(category)}_quantity_two_preserved",
            group=f"{category}.quantity",
            payload=base_payload(args, [quantity_item]),
            probes=[ExpectedProbe("quantity", "2", first_quantity_kind, 2)],
            notes=f"Quantity 2 for {first_valid_name} must not collapse",
        ))

        unknown_option_item = deepcopy(first_valid_item)
        unknown_option_item["option_names"] = ["__RELEASE_GATE_UNKNOWN_OPTION__"]
        add_case(cases, coverage, TestCase(
            name=f"{slug(category)}_unknown_option_rejected",
            group=f"{category}.negative_unknown",
            payload=base_payload(args, [unknown_option_item]),
            expected_ok=False,
            notes="A made-up option may never be ignored while returning ok:true",
        ))

    add_case(cases, coverage, TestCase(
        name=f"{slug(category)}_unknown_item_rejected",
        group=f"{category}.negative_unknown",
        payload=base_payload(args, [{"category": category, "item_name": "__RELEASE_GATE_UNKNOWN_ITEM__"}]),
        expected_ok=False,
        notes="A made-up item may never be ignored while returning ok:true",
    ))

    return cases

def beverage_sizes_for_item(payload: Mapping[str, Any], row: Mapping[str, Any]) -> list[str]:
    direct = unique_strings(first_present(row.get("sizes"), row.get("size_names"), row.get("allowed_sizes")) or [])
    if direct:
        return direct
    by_item = payload.get("sizes_by_item") or payload.get("sizes_by_type") or {}
    if isinstance(by_item, dict):
        for key in (item_name(row), norm(item_name(row)), str(row.get("name") or "")):
            if key in by_item:
                names = unique_strings(as_list(by_item[key]))
                if names:
                    return names
    return names_from(payload, "sizes", "beverage_sizes")


def generate_beverage_cases(
    args: argparse.Namespace,
    payload: Mapping[str, Any],
    mapping: AuditMappings,
    coverage: Coverage,
) -> list[TestCase]:
    cases: list[TestCase] = []
    first_valid: dict[str, Any] | None = None
    for row in rows_from(payload, "items"):
        name = item_name(row)
        if not name:
            continue
        coverage.expect(f"beverages:item:{norm(name)}")
        sizes = beverage_sizes_for_item(payload, row)
        if not sizes:
            item = {"category": "beverages", "item_name": name}
            add_case(cases, coverage, TestCase(
                name=f"beverage__{slug(name)}__default",
                group="beverages.item",
                payload=base_payload(args, [item]),
                probes=[probe(mapping, "BEV_TYPE_BY_NAME", name, ("BEV_TYPE_BY_NAME",), "beverage_type")],
                coverage_tokens={f"beverages:item:{norm(name)}"},
                distinct_family="beverages:items",
                distinct_value=name,
            ))
            if first_valid is None:
                first_valid = deepcopy(item)
            continue
        for size in sizes:
            coverage.expect(f"beverages:size:{norm(name)}:{norm(size)}")
            item = {"category": "beverages", "item_name": name, "size": size}
            add_case(cases, coverage, TestCase(
                name=f"beverage__{slug(name)}__size__{slug(size)}",
                group="beverages.size",
                payload=base_payload(args, [item]),
                probes=[
                    probe(mapping, "BEV_TYPE_BY_NAME", name, ("BEV_TYPE_BY_NAME",), "beverage_type"),
                    probe(mapping, "BEV_SIZE_BY_NAME", size, ("BEV_SIZE_BY_NAME",), "beverage_size"),
                ],
                coverage_tokens={f"beverages:item:{norm(name)}", f"beverages:size:{norm(name)}:{norm(size)}"},
                distinct_family=f"beverages:sizes:{norm(name)}",
                distinct_value=size,
            ))
            if first_valid is None:
                first_valid = deepcopy(item)

    if first_valid is not None:
        quantity_item = deepcopy(first_valid)
        quantity_item["quantity"] = 2
        add_case(cases, coverage, TestCase(
            name="beverages_quantity_two_preserved",
            group="beverages.quantity",
            payload=base_payload(args, [quantity_item]),
            probes=[ExpectedProbe("quantity", "2", "beverage_quantity", 2)],
            notes="Beverage quantity 2 must not collapse",
        ))
        unknown_size = deepcopy(first_valid)
        unknown_size["size"] = "__RELEASE_GATE_UNKNOWN_SIZE__"
        add_case(cases, coverage, TestCase(
            name="beverages_unknown_size_rejected",
            group="beverages.negative_unknown",
            payload=base_payload(args, [unknown_size]),
            expected_ok=False,
            notes="A made-up beverage size may never be silently ignored",
        ))

    add_case(cases, coverage, TestCase(
        name="beverages_unknown_item_rejected",
        group="beverages.negative_unknown",
        payload=base_payload(args, [{"category": "beverages", "item_name": "__RELEASE_GATE_UNKNOWN_ITEM__", "size": "CAN"}]),
        expected_ok=False,
        notes="A made-up beverage may never be silently ignored",
    ))
    return cases

def available_coupon_numbers(response: Mapping[str, Any]) -> set[int]:
    found: set[int] = set()
    for row in iter_dicts(response):
        raw = first_present(row.get("coupon_number"), row.get("number"))
        try:
            number = int(raw)
        except Exception:
            continue
        available = first_present(row.get("currently_available"), row.get("available"), True)
        if available is not False:
            found.add(number)
    return found


def coupon_plan_from_response(response: Mapping[str, Any], number: int) -> dict[str, Any] | None:
    for row in iter_dicts(response):
        try:
            row_number = int(first_present(row.get("coupon_number"), row.get("number")))
        except Exception:
            continue
        if row_number == int(number) and isinstance(row.get("required_choices"), list):
            return dict(row)
    return None


def choice_rows(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in as_list(plan.get("required_choices")) if isinstance(row, dict) and row.get("choice_type")]


def dependent_rows(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in as_list(plan.get("dependent_required_choices")) if isinstance(row, dict)]


def choice_values(row: Mapping[str, Any]) -> list[str]:
    return unique_strings(first_present(row.get("choices"), row.get("items"), row.get("values")) or [])


def is_option_only_choice(row: Mapping[str, Any]) -> bool:
    ct = norm(row.get("choice_type")).replace(" ", "_")
    send_as = norm(row.get("send_as"))
    return (
        ct in OPTION_ONLY_CHOICE_TYPES
        or bool(row.get("required_after_choice"))
        or "option names" in send_as
        or (isinstance(row.get("component_template"), dict) and "option_names" in row["component_template"] and "item_name" not in row["component_template"])
    )


def normalized_choice_type(value: Any) -> str:
    return norm(value).replace(" ", "_")


def build_coupon_baseline(number: int, plan: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str], list[str]]:
    choices = choice_rows(plan)
    selected: dict[str, str] = {}
    rows: list[dict[str, Any]] = []
    errors: list[str] = []

    # First create item-bearing components. required_choices are required by
    # default even when an older plan omitted an explicit minimum. A minimum
    # above one (notably coupon 999 pizza_choice) creates that many separate
    # component rows; it is never collapsed into quantity 2.
    for choice in choices:
        ct = normalized_choice_type(choice.get("choice_type"))
        values = choice_values(choice)
        minimum_raw = choice.get("minimum")
        minimum = int(minimum_raw) if minimum_raw is not None else 1
        required = choice.get("optional") is not True and minimum > 0
        if not values:
            if required and not choice.get("fixed"):
                errors.append(f"required choice {ct} has no choices")
            continue
        selected[ct] = values[0]
        if is_option_only_choice(choice):
            continue
        for index in range(max(1, minimum)):
            selected_value = values[index] if index < len(values) else values[0]
            rows.append({
                "category": "coupon_component",
                "coupon_number": number,
                "choice_type": ct,
                "item_name": selected_value,
                **({"quantity": 1} if int(number) == 999 and ct == "pizza_choice" else {}),
            })

    # Attach option-only required choices to the declared parent component.
    for choice in choices:
        ct = normalized_choice_type(choice.get("choice_type"))
        if not is_option_only_choice(choice):
            continue
        values = choice_values(choice)
        if not values:
            continue
        value = values[0]
        parent = normalized_choice_type(choice.get("required_after_choice") or deep_get(choice, "requires_followup_choice", "after_choice"))
        target = next((row for row in rows if normalized_choice_type(row.get("choice_type")) == parent), None)
        if target is None:
            # Only fixed-parent option components may be sent separately.
            target = {
                "category": "coupon_component",
                "coupon_number": number,
                "choice_type": ct,
                "option_names": [],
            }
            rows.append(target)
        target.setdefault("option_names", []).append(value)

    # Apply item-dependent options (for example w/ Bleu Cheese on Antipasto).
    for dep in dependent_rows(plan):
        parent_name = str(dep.get("when_selected_item_name") or "").strip()
        values = unique_strings(dep.get("choices") or [])
        if not parent_name or not values:
            continue
        target = next((row for row in rows if norm(row.get("item_name")) == norm(parent_name)), None)
        if target is not None:
            # Replace a generic dressing attached above with the exact
            # item-dependent customer-facing spelling.
            label = norm(dep.get("label"))
            if "dressing" in label:
                target["option_names"] = [values[0]]
            else:
                target.setdefault("option_names", []).append(values[0])

    return rows, selected, errors


def replace_coupon_choice(
    baseline: list[dict[str, Any]],
    choice: Mapping[str, Any],
    value: str,
    plan: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows = deepcopy(baseline)
    ct = normalized_choice_type(choice.get("choice_type"))
    if not is_option_only_choice(choice):
        target = next((row for row in rows if normalized_choice_type(row.get("choice_type")) == ct), None)
        if target is None:
            rows.append({"category": "coupon_component", "coupon_number": int(plan.get("coupon_number")), "choice_type": ct, "item_name": value})
        else:
            target["item_name"] = value
        # Reapply matching dependent options for this newly selected item.
        for dep in dependent_rows(plan):
            if norm(dep.get("when_selected_item_name")) == norm(value):
                dep_values = unique_strings(dep.get("choices") or [])
                if dep_values:
                    target = next((row for row in rows if normalized_choice_type(row.get("choice_type")) == ct and norm(row.get("item_name")) == norm(value)), None)
                    if target is not None:
                        target["option_names"] = [dep_values[0]]
        return rows

    parent = normalized_choice_type(choice.get("required_after_choice") or deep_get(choice, "requires_followup_choice", "after_choice"))
    target = next((row for row in rows if normalized_choice_type(row.get("choice_type")) == parent), None)
    if target is None:
        target = next((row for row in rows if normalized_choice_type(row.get("choice_type")) == ct), None)
    if target is None:
        rows.append({
            "category": "coupon_component",
            "coupon_number": int(plan.get("coupon_number")),
            "choice_type": ct,
            "option_names": [value],
        })
    else:
        target["option_names"] = [value]
    return rows


def remove_coupon_choice(baseline: list[dict[str, Any]], choice: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = deepcopy(baseline)
    ct = normalized_choice_type(choice.get("choice_type"))
    if not is_option_only_choice(choice):
        return [row for row in rows if normalized_choice_type(row.get("choice_type")) != ct]
    parent = normalized_choice_type(choice.get("required_after_choice") or deep_get(choice, "requires_followup_choice", "after_choice"))
    for row in rows:
        if normalized_choice_type(row.get("choice_type")) in {parent, ct}:
            row.pop("option_names", None)
    return rows


def probes_for_coupon_rows(number: int, rows: Sequence[Mapping[str, Any]], mapping: AuditMappings) -> list[ExpectedProbe]:
    probes: list[ExpectedProbe] = [ExpectedProbe("coupon_number", str(number), "coupon", int(number))]

    def add_if_resolved(source: str, name: str, map_names: Sequence[str], path_kind: str) -> None:
        value = mapping.resolve(map_names, name)
        if value is not None:
            probes.append(ExpectedProbe(source, name, path_kind, value))

    for row in rows:
        ct = normalized_choice_type(row.get("choice_type"))
        name = str(row.get("item_name") or "").strip()
        if name:
            if ct in {"pizza", "pizza_choice", "calzone"} or " pizza" in norm(name) or " calzone" in norm(name):
                add_if_resolved("SPECIALTY_BY_NAME", name, ("SPECIALTY_BY_NAME",), "pizza_combo")
            elif ct == "salad":
                add_if_resolved("SALAD_ITEM_BY_NAME", name, ("SALAD_ITEM_BY_NAME",), "menu_item")
            elif ct in {"drink", "beverage"}:
                add_if_resolved("BEV_TYPE_BY_NAME", name, ("BEV_TYPE_BY_NAME", "SIDE_ITEM_BY_NAME"), "menu_item")
            elif ct in {"half_sub", "sub"}:
                add_if_resolved("SUB_ITEM_BY_NAME", name, ("SUB_ITEM_BY_NAME",), "menu_item")
            elif ct in {"wing", "wings", "wing_choice"}:
                add_if_resolved("WING_ITEM_BY_NAME", name, ("WING_ITEM_BY_NAME",), "menu_item")
            elif ct in {"appetizer", "side", "menu"}:
                add_if_resolved("coupon_menu_item", name, ("SIDE_ITEM_BY_NAME", "DESSERT_BY_NAME", "SUB_ITEM_BY_NAME", "WING_ITEM_BY_NAME", "SALAD_ITEM_BY_NAME"), "menu_item")
            else:
                # Fixed semantic choices such as CHEESE/PEPPERONI in coupon 151
                # may not be direct menu names. Probe only when a live mapping
                # exists; compile success and distinct-output checks still apply.
                add_if_resolved("coupon_item", name, ("SIDE_ITEM_BY_NAME", "DESSERT_BY_NAME", "SUB_ITEM_BY_NAME", "WING_ITEM_BY_NAME", "SALAD_ITEM_BY_NAME", "BEV_TYPE_BY_NAME"), "menu_item")

        for option in unique_strings(row.get("option_names") or []):
            if ct in {"calzone", "calzone_dip"} or " dip" in norm(option):
                dip_id = mapping.resolve(("CALZONE_DIP_EXACT_BY_NAME", "SIDE_ITEM_BY_NAME"), option)
                if dip_id is not None:
                    probes.append(ExpectedProbe("CALZONE_DIP_EXACT_BY_NAME", option, "menu_item", dip_id))
                elif ct == "calzone":
                    add_if_resolved("PIZZA_TOPPING_BY_NAME", option, ("PIZZA_TOPPING_BY_NAME", "TOPPING_BY_NAME"), "pizza_topping")
            elif ct in {"salad", "salad_dressing", "dressing"}:
                add_if_resolved("DRESSING_BY_NAME", option, ("DRESSING_BY_NAME",), "modifier")
            elif ct in {"wing", "wings", "wing_sauce", "wing_choice"}:
                value = mapping.resolve(("WING_SAUCE_BY_NAME",), option)
                if value is not None:
                    probes.append(ExpectedProbe("WING_SAUCE_BY_NAME", option, "modifier", value))
                else:
                    add_if_resolved("WING_INSTRUCTION_BY_NAME", option, ("WING_INSTRUCTION_BY_NAME",), "modifier")
            elif ct in {"sub", "half_sub"}:
                add_if_resolved("SUB_OPTION_BY_NAME", option, ("SUB_OPTION_BY_NAME",), "modifier")
            elif ct in {"pizza", "pizza_choice", "pizza_topping"}:
                add_if_resolved("PIZZA_TOPPING_BY_NAME", option, ("PIZZA_TOPPING_BY_NAME", "TOPPING_BY_NAME"), "pizza_topping")
            else:
                add_if_resolved("coupon_option", option, ("DRESSING_BY_NAME", "WING_SAUCE_BY_NAME", "SUB_OPTION_BY_NAME", "SIDE_OPTION_BY_NAME", "CALZONE_DIP_EXACT_BY_NAME"), "modifier")
    return probes


def generate_coupon_cases(
    args: argparse.Namespace,
    number: int,
    plan: Mapping[str, Any],
    mapping: AuditMappings,
    coverage: Coverage,
) -> list[TestCase]:
    cases: list[TestCase] = []
    plan = dict(plan)
    plan["coupon_number"] = int(number)
    baseline, _, errors = build_coupon_baseline(number, plan)
    if errors:
        add_case(cases, coverage, TestCase(
            name=f"coupon_{number}__plan_contract_invalid",
            group="coupon.plan",
            payload=base_payload(args, [{"category": "coupon_component", "coupon_number": number, "choice_type": "invalid", "item_name": "invalid"}], coupon_numbers=[number]),
            expected_ok=False,
            expected_missing_contains=["never-match-plan-contract-error"],
            notes="; ".join(errors),
        ))
        return cases

    coverage.expect(f"coupon:{number}:plan")
    if baseline:
        add_case(cases, coverage, TestCase(
            name=f"coupon_{number}__baseline_complete",
            group="coupon.baseline",
            payload=base_payload(args, baseline, coupon_numbers=[number]),
            probes=probes_for_coupon_rows(number, baseline, mapping),
            coverage_tokens={f"coupon:{number}:plan"},
            distinct_family="coupons:baseline",
            distinct_value=str(number),
            reorder_check=len(baseline) > 1,
        ))

    for choice in choice_rows(plan):
        ct = normalized_choice_type(choice.get("choice_type"))
        values = choice_values(choice)
        for value in values:
            token = f"coupon:{number}:choice:{ct}:{norm(value)}"
            coverage.expect(token)
            rows = replace_coupon_choice(baseline, choice, value, plan)
            add_case(cases, coverage, TestCase(
                name=f"coupon_{number}__{slug(ct)}__{slug(value)}",
                group="coupon.choice",
                payload=base_payload(args, rows, coupon_numbers=[number]),
                probes=probes_for_coupon_rows(number, rows, mapping),
                coverage_tokens={f"coupon:{number}:plan", token},
                distinct_family=f"coupon:{number}:{ct}",
                distinct_value=value,
                reorder_check=len(rows) > 1,
            ))
        minimum_raw = choice.get("minimum")
        minimum = int(minimum_raw) if minimum_raw is not None else 1
        required = choice.get("optional") is not True and (
            minimum > 0
            or bool(choice.get("required_after_choice"))
            or bool(choice.get("required_before_pricing"))
            or bool(choice.get("required_before_next_choice"))
        )
        if required:
            rows = remove_coupon_choice(baseline, choice)
            expected_word = {
                "calzone_dip": "dip",
                "salad_dressing": "dressing",
                "wing_sauce": "sauce",
                "pizza_topping": "topping",
                "pizza_choice": "pizza",
                "half_sub": "sub",
            }.get(ct, ct.split("_")[-1] if ct else "choice")
            add_case(cases, coverage, TestCase(
                name=f"coupon_{number}__missing__{slug(ct)}",
                group="coupon.negative",
                payload=base_payload(args, rows, coupon_numbers=[number]),
                expected_ok=False,
                expected_missing_contains=[expected_word],
                notes="Omitted exactly one required coupon choice",
            ))

    # Every item-dependent option spelling is tested, not only the generic
    # required-choice spelling. This is what catches w/ Bleu Cheese parity.
    for dep in dependent_rows(plan):
        parent_name = str(dep.get("when_selected_item_name") or "").strip()
        values = unique_strings(dep.get("choices") or [])
        if not parent_name:
            continue
        for value in values:
            token = f"coupon:{number}:dependent:{norm(parent_name)}:{norm(value)}"
            coverage.expect(token)
            rows = deepcopy(baseline)
            target = next((row for row in rows if norm(row.get("item_name")) == norm(parent_name)), None)
            if target is None:
                # Replace the first plausible salad/menu component with this
                # exact parent item so every dependent contract is reachable.
                target = next((row for row in rows if normalized_choice_type(row.get("choice_type")) in {"salad", "menu", "appetizer"}), None)
                if target is not None:
                    target["item_name"] = parent_name
            if target is not None:
                target["option_names"] = [value]
                add_case(cases, coverage, TestCase(
                    name=f"coupon_{number}__dependent__{slug(parent_name)}__{slug(value)}",
                    group="coupon.dependent",
                    payload=base_payload(args, rows, coupon_numbers=[number]),
                    probes=probes_for_coupon_rows(number, rows, mapping),
                    coverage_tokens={f"coupon:{number}:plan", token},
                    distinct_family=f"coupon:{number}:dependent:{norm(parent_name)}",
                    distinct_value=value,
                    reorder_check=len(rows) > 1,
                ))

    if baseline:
        # Top-level coupon_numbers is the coupon-line authority. Row-level
        # ownership alone must never be accepted as a complete coupon cart.
        add_case(cases, coverage, TestCase(
            name=f"coupon_{number}__missing_top_level_coupon_number",
            group="coupon.negative_contract",
            payload=base_payload(args, deepcopy(baseline)),
            expected_ok=False,
            expected_missing_contains=["coupon"],
            notes="coupon_component ownership may not replace top-level coupon_numbers",
        ))

        # The compiler must reject an unknown value instead of silently using
        # the baseline or dropping the bad component.
        unknown_rows = deepcopy(baseline)
        target = next((row for row in unknown_rows if row.get("item_name")), None)
        if target is not None:
            target["item_name"] = "__RELEASE_GATE_UNKNOWN_COUPON_CHOICE__"
        else:
            target = next((row for row in unknown_rows if row.get("option_names")), None)
            if target is not None:
                target["option_names"] = ["__RELEASE_GATE_UNKNOWN_COUPON_OPTION__"]
        if target is not None:
            add_case(cases, coverage, TestCase(
                name=f"coupon_{number}__unknown_choice_rejected",
                group="coupon.negative_unknown",
                payload=base_payload(args, unknown_rows, coupon_numbers=[number]),
                expected_ok=False,
                notes="Unknown coupon choices may never be silently dropped",
            ))

    # Normal coupon repeat quantity. Coupon 999 is a special multi-pizza deal,
    # so it appears only once at top level.
    if number != 999 and baseline:
        doubled = deepcopy(baseline) + deepcopy(baseline)
        add_case(cases, coverage, TestCase(
            name=f"coupon_{number}__two_instances",
            group="coupon.repeat",
            payload=base_payload(args, doubled, coupon_numbers=[number, number]),
            probes=probes_for_coupon_rows(number, doubled, mapping) + [ExpectedProbe("coupon_count", "2", "coupon_count", 2)],
            reorder_check=True,
            notes="Two normal coupon instances must remain two instances",
        ))

    return cases


def exact_regression_148(args: argparse.Namespace, mapping: AuditMappings) -> list[TestCase]:
    correct_rows = [
        {
            "category": "coupon_component",
            "item_name": "Bar-B-Que Chicken Calzone",
            "choice_type": "calzone",
            "coupon_number": 148,
            "option_names": ["Marinara Dip"],
        },
        {
            "category": "coupon_component",
            "item_name": "Antipasto Salad",
            "choice_type": "salad",
            "coupon_number": 148,
            "option_names": ["w/ Bleu Cheese"],
        },
        {
            "category": "coupon_component",
            "item_name": "Can / Coke",
            "choice_type": "drink",
            "coupon_number": 148,
        },
    ]
    separate_rows = [
        {"category": "coupon_component", "item_name": "Bar-B-Que Chicken Calzone", "choice_type": "calzone", "coupon_number": 148},
        {"category": "coupon_component", "item_name": "Antipasto Salad", "choice_type": "salad", "coupon_number": 148},
        {"category": "coupon_component", "item_name": "Can / Coke", "choice_type": "drink", "coupon_number": 148},
        {"category": "coupon_component", "item_name": "Marinara Dip", "choice_type": "calzone_dip", "coupon_number": 148, "option_names": ["Marinara Dip"]},
        {"category": "coupon_component", "item_name": "w/ Bleu Cheese", "choice_type": "salad_dressing", "coupon_number": 148, "option_names": ["w/ Bleu Cheese"]},
    ]
    return [
        TestCase(
            name="REGRESSION_2026_08_04_coupon148_correct_attached_shape",
            group="regression.148",
            payload=base_payload(args, correct_rows, coupon_numbers=[148]),
            probes=probes_for_coupon_rows(148, correct_rows, mapping),
            reorder_check=True,
            notes="Mandatory exact final payload from the failed live call. Must compile without asking for dip or dressing.",
        ),
        TestCase(
            name="REGRESSION_2026_08_04_coupon148_separate_option_rows_contract",
            group="regression.148.shape",
            payload=base_payload(args, separate_rows, coupon_numbers=[148]),
            expected_ok=False,
            expected_missing_contains=[],
            forbidden_missing_contains=["which dip", "which dressing"],
            notes=(
                "This shape must either compile or return retry_without_asking_customer. "
                "It must never re-question the customer for already supplied choices."
            ),
        ),
    ]


def generate_interaction_cases(args: argparse.Namespace, existing: Sequence[TestCase]) -> list[TestCase]:
    """Generate pairwise/all-category, duplicate-row, and mixed-coupon carts.

    Exhaustive single-item coverage is not enough: many historic failures were
    ownership or cart-rebuild defects that appeared only when two categories or
    two coupons shared one complete cart.
    """
    out: list[TestCase] = []
    category_order = ["pizza", "calzone", "wings", "subs", "salads", "sides_appetizers", "desserts", "beverages"]
    anchors: dict[str, TestCase] = {}
    for category in category_order:
        candidates = [
            case for case in existing
            if case.expected_ok
            and case.group.startswith(category + ".")
            and ".negative" not in case.group
            and ".quantity" not in case.group
            and not case.payload.get("coupon_numbers")
            and len(case.payload.get("items") or []) == 1
        ]
        if candidates:
            anchors[category] = candidates[0]

    # Every category pair plus one complete all-category cart.
    cats = [c for c in category_order if c in anchors]
    for i, left in enumerate(cats):
        for right in cats[i + 1:]:
            a, b = anchors[left], anchors[right]
            out.append(TestCase(
                name=f"interaction__{slug(left)}__{slug(right)}",
                group="interaction.category_pair",
                payload=base_payload(args, deepcopy(a.payload["items"]) + deepcopy(b.payload["items"])),
                probes=deepcopy(a.probes) + deepcopy(b.probes),
                reorder_check=True,
                notes="Pairwise complete-cart interaction; neither category may overwrite or drop the other",
            ))
    if len(cats) >= 2:
        all_items: list[dict[str, Any]] = []
        probes: list[ExpectedProbe] = []
        for category in cats:
            all_items.extend(deepcopy(anchors[category].payload["items"]))
            probes.extend(deepcopy(anchors[category].probes))
        out.append(TestCase(
            name="interaction__all_categories_one_cart",
            group="interaction.all_categories",
            payload=base_payload(args, all_items),
            probes=probes,
            reorder_check=True,
            notes="One valid item from every current category in the same stateless compile",
        ))

    # Two identical real rows must remain a quantity of two; duplicate repair
    # may not erase a genuine repeated order.
    quantity_kind = {
        "pizza": "pizza_quantity",
        "calzone": "pizza_quantity",
        "beverages": "beverage_quantity",
    }
    for category, anchor in anchors.items():
        out.append(TestCase(
            name=f"duplicate_real_rows__{slug(category)}__two",
            group="interaction.duplicate_real_rows",
            payload=base_payload(args, deepcopy(anchor.payload["items"]) + deepcopy(anchor.payload["items"])),
            probes=deepcopy(anchor.probes) + [ExpectedProbe("duplicate_real_rows", category, quantity_kind.get(category, "menu_item_quantity"), 2)],
            reorder_check=True,
            notes="Two identical rows are a real order, not a duplicate to delete",
        ))

    coupon_anchors = [
        case for case in existing
        if case.expected_ok and case.group == "coupon.baseline" and case.payload.get("coupon_numbers")
    ]
    # Every pair of supported coupon plans must coexist when the compiler plan
    # allows mixed package coupons. This is a compiler ownership test only; it
    # does not price or enforce marketing discount policy.
    for i, left in enumerate(coupon_anchors):
        for right in coupon_anchors[i + 1:]:
            left_numbers = [int(x) for x in left.payload.get("coupon_numbers") or []]
            right_numbers = [int(x) for x in right.payload.get("coupon_numbers") or []]
            numbers = left_numbers + right_numbers
            out.append(TestCase(
                name=f"mixed_coupons__{'_'.join(map(str, left_numbers))}__{'_'.join(map(str, right_numbers))}",
                group="interaction.mixed_coupons",
                payload=base_payload(
                    args,
                    deepcopy(left.payload["items"]) + deepcopy(right.payload["items"]),
                    coupon_numbers=numbers,
                ),
                probes=deepcopy(left.probes) + deepcopy(right.probes),
                reorder_check=True,
                notes="Mixed coupon component ownership must remain separated",
            ))

    # Coupon plus ordinary same-family item catches the exact class of package
    # ownership bugs that previously merged or dropped standalone food.
    for coupon in coupon_anchors:
        numbers = [int(x) for x in coupon.payload.get("coupon_numbers") or []]
        choice_types = {normalized_choice_type(row.get("choice_type")) for row in coupon.payload.get("items") or []}
        if choice_types & {"pizza", "pizza_choice", "calzone"}:
            ordinary_category = "pizza"
        elif choice_types & {"half_sub", "sub", "main"} and "subs" in anchors:
            ordinary_category = "subs"
        elif choice_types & {"wing", "wings", "wing_choice"}:
            ordinary_category = "wings"
        else:
            ordinary_category = "sides_appetizers" if "sides_appetizers" in anchors else (cats[0] if cats else "")
        ordinary = anchors.get(ordinary_category)
        if ordinary is None:
            continue
        out.append(TestCase(
            name=f"coupon_plus_ordinary__{'_'.join(map(str, numbers))}__{slug(ordinary_category)}",
            group="interaction.coupon_plus_ordinary",
            payload=base_payload(
                args,
                deepcopy(coupon.payload["items"]) + deepcopy(ordinary.payload["items"]),
                coupon_numbers=numbers,
            ),
            probes=deepcopy(coupon.probes) + deepcopy(ordinary.probes),
            reorder_check=True,
            notes="Coupon components and an ordinary same-family item must not merge or swap ownership",
        ))

    return out


def is_special_structural_retry(case: TestCase, response: Mapping[str, Any]) -> bool:
    return (
        case.name.endswith("separate_option_rows_contract")
        and response.get("ok") is not True
        and response.get("retry_without_asking_customer") is True
        and not response.get("first_missing_question")
        and not response.get("missing_questions")
    )


def validate_probe(probe: ExpectedProbe, order: Mapping[str, Any], audit_enabled: bool) -> str | None:
    if probe.expected_id is None:
        if audit_enabled:
            return f"Audit mapping missing: {probe.source} has no ID for {probe.name!r}"
        return None
    if not contains_id_at(order, probe.path_kind, probe.expected_id):
        return f"Expected {probe.path_kind} ID {probe.expected_id} for {probe.name!r} was not present"
    return None


async def run_case(
    client: BackendClient,
    case: TestCase,
    snapshot_guard: SnapshotGuard,
    audit_enabled: bool,
    determinism_runs: int,
) -> CaseResult:
    failures: list[str] = []
    statuses: list[int | None] = []
    responses: list[dict[str, Any]] = []
    elapsed_total = 0
    fingerprints: list[str | None] = []

    for run_index in range(max(1, determinism_runs)):
        status, response, elapsed = await client.post("/grok-tool/compile-order-list", case.payload)
        elapsed_total += elapsed
        statuses.append(status)
        responses.append(response)
        snapshot_guard.observe(f"case:{case.name}:run{run_index + 1}", response)
        fingerprints.append(order_fingerprint(response))

    response = responses[0]
    status = statuses[0]
    special_retry = is_special_structural_retry(case, response)
    compile_ok = response.get("ok") is True

    if status != 200:
        failures.append(f"HTTP status was {status}, expected 200")

    if case.expected_ok:
        if not compile_ok:
            failures.append(f"Expected ok:true; got {response_failure_text(response) or response}")
        order = compiler_output(response)
        if compile_ok and not isinstance(order, dict):
            failures.append("ok:true response did not contain object order_json")
        if compile_ok and isinstance(order, dict):
            for p in case.probes:
                issue = validate_probe(p, order, audit_enabled)
                if issue:
                    failures.append(issue)
    else:
        if special_retry:
            pass
        elif compile_ok and case.name.endswith("separate_option_rows_contract"):
            # The compiler may normalize this legacy shape directly. That is
            # acceptable because no customer choice was lost or re-asked.
            pass
        elif compile_ok:
            failures.append("Expected a controlled negative/structural result, but compiler returned ok:true")
        else:
            missing_text = " ".join(
                [str(response.get("first_missing_question") or "")]
                + [str(x) for x in as_list(response.get("missing_questions"))]
                + [str(response.get("message") or "")]
            ).lower()
            for required in case.expected_missing_contains:
                if required.lower() not in missing_text:
                    failures.append(f"Negative result did not mention expected missing concept {required!r}: {missing_text[:1000]}")
            for forbidden in case.forbidden_missing_contains:
                if forbidden.lower() in missing_text:
                    failures.append(f"Structural retry incorrectly re-questioned customer with {forbidden!r}: {missing_text[:1000]}")
            if case.name.endswith("separate_option_rows_contract") and not special_retry:
                # This legacy shape may compile; otherwise the only acceptable
                # failure is an internal silent structural retry.
                failures.append("Separate option-row shape neither compiled nor returned retry_without_asking_customer:true")

    # Determinism applies to the entire compiler response semantics, not just
    # ok:true cases. For failures, compare the canonical response after removing
    # volatile-looking metadata.
    if len(responses) > 1:
        if compile_ok:
            if len(set(fingerprints)) != 1:
                failures.append(f"Non-deterministic order_json across repeats: {fingerprints}")
        else:
            normalized_failures = []
            for r in responses:
                copy = dict(r)
                for volatile in ("elapsed_ms", "request_id", "trace_id", "timestamp"):
                    copy.pop(volatile, None)
                normalized_failures.append(canonical_json(copy))
            if len(set(normalized_failures)) != 1:
                failures.append("Non-deterministic failure response across repeats")

    # Multi-row input order must not change semantic output.
    if case.reorder_check and len(case.payload.get("items") or []) > 1:
        shuffled_payload = deepcopy(case.payload)
        shuffled_payload["items"] = list(reversed(shuffled_payload["items"]))
        status2, response2, elapsed2 = await client.post("/grok-tool/compile-order-list", shuffled_payload)
        elapsed_total += elapsed2
        snapshot_guard.observe(f"case:{case.name}:reordered", response2)
        if status2 != 200:
            failures.append(f"Reordered input returned HTTP {status2}")
        elif compile_ok and response2.get("ok") is True:
            if order_fingerprint(response2) != fingerprints[0]:
                failures.append("Reordering complete cart rows changed semantic order_json")
        elif compile_ok != (response2.get("ok") is True):
            failures.append("Reordering complete cart rows changed compiler success/failure outcome")

    snapshot = next(iter(snapshots_in(response)), None)
    return CaseResult(
        case=case.name,
        group=case.group,
        passed=not failures,
        mandatory=True,
        http_status=status,
        compile_ok=compile_ok,
        fingerprint=fingerprints[0],
        snapshot=snapshot,
        elapsed_ms=elapsed_total,
        failures=failures,
        notes=case.notes,
        payload=redact(case.payload),
        response=redact(response),
        repeat_fingerprints=fingerprints,
    )


def find_distinct_collisions(cases: Sequence[TestCase], results: Sequence[CaseResult]) -> list[dict[str, Any]]:
    by_case = {row.case: row for row in results}
    families: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for case in cases:
        if not case.distinct_family or case.distinct_value is None:
            continue
        result = by_case.get(case.name)
        if not result or not result.passed or not result.compile_ok or not result.fingerprint:
            continue
        families[case.distinct_family].append((case.name, case.distinct_value, result.fingerprint))
    collisions: list[dict[str, Any]] = []
    for family, rows in families.items():
        by_fingerprint: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for case_name, value, fingerprint in rows:
            by_fingerprint[fingerprint].append((case_name, value))
        for fingerprint, same in by_fingerprint.items():
            distinct_values = {norm(value) for _, value in same}
            if len(distinct_values) > 1:
                collisions.append({
                    "family": family,
                    "fingerprint": fingerprint,
                    "cases": [{"case": case_name, "value": value} for case_name, value in same],
                    "failure": "Distinct exposed customer choices produced identical compiler output",
                })
    return collisions


def write_reports(
    output_dir: Path,
    summary: GateSummary,
    cases: Sequence[TestCase],
    results: Sequence[CaseResult],
    collisions: Sequence[Mapping[str, Any]],
    catalog_evidence: Mapping[str, Any],
    coupon_evidence: Mapping[str, Any],
    audit_evidence: Mapping[str, Any] | None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "summary": asdict(summary),
        "definition_of_100_percent_today": {
            "covered": [
                "all customer-facing values returned by the current category tools",
                "all required and dependent choices returned by every discovered coupon plan",
                "all valid pizza size/crust combinations declared by crusts_by_size",
                "all current toppings, sauces, styles, instructions, specialty pizzas, calzone dips, wing sauces/instructions, salad dressings, sub options, side options, dessert options, and beverage sizes that the tools expose",
                "strict negative required-choice behavior",
                "determinism, row-order invariance, repeat quantity, output uniqueness, and the exact 2026-08-04 coupon-148 regression",
                "exact private ID assertions when the authenticated audit endpoint is available",
            ],
            "not_claimed": [
                "mathematical proof for arbitrary future source code or future menu snapshots",
                "voice-model interpretation, prompt behavior, pricing, payment, submission, transfer, or oneSystem availability",
            ],
        },
        "collisions": list(collisions),
        "results": [asdict(row) for row in results],
    }
    (output_dir / "compiler_gate_report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    failures = [asdict(row) for row in results if not row.passed]
    (output_dir / "compiler_gate_failures.json").write_text(json.dumps({"summary": asdict(summary), "collisions": list(collisions), "failures": failures}, indent=2, default=str), encoding="utf-8")
    (output_dir / "catalog_evidence.json").write_text(json.dumps(redact(catalog_evidence), indent=2, default=str), encoding="utf-8")
    (output_dir / "coupon_evidence.json").write_text(json.dumps(redact(coupon_evidence), indent=2, default=str), encoding="utf-8")
    if audit_evidence is not None:
        (output_dir / "audit_private_mapping_evidence.json").write_text(json.dumps(redact(audit_evidence), indent=2, default=str), encoding="utf-8")

    with (output_dir / "compiler_gate_cases.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=[
            "case", "group", "passed", "http_status", "compile_ok", "fingerprint", "snapshot", "elapsed_ms", "failures", "notes"
        ])
        writer.writeheader()
        for row in results:
            writer.writerow({
                "case": row.case,
                "group": row.group,
                "passed": row.passed,
                "http_status": row.http_status,
                "compile_ok": row.compile_ok,
                "fingerprint": row.fingerprint,
                "snapshot": row.snapshot,
                "elapsed_ms": row.elapsed_ms,
                "failures": " | ".join(row.failures),
                "notes": row.notes,
            })

    status_class = "pass" if summary.status == "PASS" else ("incomplete" if summary.status == "INCOMPLETE" else "fail")
    result_rows = "\n".join(
        "<tr class='%s'><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            "pass" if row.passed else "fail",
            html.escape(row.case),
            html.escape(row.group),
            "PASS" if row.passed else "FAIL",
            html.escape(" | ".join(row.failures) or row.notes),
        )
        for row in results
    )
    collision_html = "".join(f"<li>{html.escape(canonical_json(row))}</li>" for row in collisions) or "<li>None</li>"
    doc = f"""<!doctype html>
<html><head><meta charset='utf-8'><title>PMD Compiler Release Gate</title>
<style>
body{{font-family:Arial,sans-serif;margin:24px;max-width:1400px}} .pass{{background:#e7f7e7}} .fail{{background:#ffe1e1}} .incomplete{{background:#fff4cc}} table{{border-collapse:collapse;width:100%}} th,td{{border:1px solid #aaa;padding:6px;vertical-align:top}} code{{background:#eee;padding:2px 4px}}
</style></head><body>
<h1>PMD Compiler Release Gate</h1>
<h2 class='{status_class}'>Status: {html.escape(summary.status)}</h2>
<p><b>Store/order type:</b> {summary.store_number} / {html.escape(summary.order_type)}</p>
<p><b>Snapshot:</b> <code>{html.escape(summary.catalog_snapshot or 'missing')}</code></p>
<p><b>Tests:</b> {summary.tests_passed} passed / {summary.tests_failed} failed / {summary.tests_total} total</p>
<p><b>Coverage:</b> {summary.coverage_tested} / {summary.coverage_expected}; missing {len(summary.coverage_missing)}</p>
<p><b>Private mapping audit:</b> {'available' if summary.audit_available else 'NOT AVAILABLE — release proof is incomplete'}</p>
<h3>Distinct-output collisions</h3><ul>{collision_html}</ul>
<h3>Cases</h3><table><thead><tr><th>Case</th><th>Group</th><th>Status</th><th>Details</th></tr></thead><tbody>{result_rows}</tbody></table>
</body></html>"""
    (output_dir / "compiler_gate_report.html").write_text(doc, encoding="utf-8")

    manifest = {
        "version": VERSION,
        "generated_at": utc_now(),
        "summary": asdict(summary),
        "files": {},
    }
    for path in sorted(output_dir.iterdir()):
        if path.is_file() and path.name != "compiler_gate_manifest.json":
            manifest["files"][path.name] = {
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
    (output_dir / "compiler_gate_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


async def collect_catalogs(
    client: BackendClient,
    args: argparse.Namespace,
    snapshot_guard: SnapshotGuard,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    for category in args.categories:
        status, response, elapsed = await client.post("/grok-tool/get-ordering-catalog", {
            "store_number": args.store_number,
            "order_type": args.order_type,
            "category": category,
        })
        snapshot_guard.observe(f"catalog:{category}", response)
        evidence[category] = {"http_status": status, "elapsed_ms": elapsed, "response": response}
        if status != 200 or response.get("ok") is not True:
            raise RuntimeError(f"Catalog {category} failed: HTTP {status}: {response_failure_text(response) or response}")
    return evidence


async def collect_coupon_plans(
    client: BackendClient,
    args: argparse.Namespace,
    snapshot_guard: SnapshotGuard,
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    evidence: dict[str, Any] = {"lists": {}, "plans": {}}
    numbers: set[int] = set(args.coupon_numbers)
    for query in args.coupon_queries:
        status, response, elapsed = await client.post("/grok-tool/get-coupon-plan", {
            "store_number": args.store_number,
            "order_type": args.order_type,
            "query": query,
        })
        snapshot_guard.observe(f"coupon-list:{query}", response)
        evidence["lists"][query] = {"http_status": status, "elapsed_ms": elapsed, "response": response}
        if status == 200 and response.get("ok") is True:
            numbers.update(available_coupon_numbers(response))

    plans: dict[int, dict[str, Any]] = {}
    for number in sorted(numbers):
        status, response, elapsed = await client.post("/grok-tool/get-coupon-plan", {
            "store_number": args.store_number,
            "order_type": args.order_type,
            "coupon_number": number,
        })
        snapshot_guard.observe(f"coupon-plan:{number}", response)
        evidence["plans"][str(number)] = {"http_status": status, "elapsed_ms": elapsed, "response": response}
        if status == 200 and response.get("ok") is True:
            plan = coupon_plan_from_response(response, number)
            if plan:
                availability = plan.get("availability") if isinstance(plan.get("availability"), dict) else {}
                if availability.get("currently_available") is False and not args.include_unavailable_coupons:
                    continue
                plans[number] = plan
    return plans, evidence


async def collect_audit(
    client: BackendClient,
    args: argparse.Namespace,
    snapshot_guard: SnapshotGuard,
) -> tuple[dict[str, Any] | None, str | None]:
    status, response, _ = await client.post("/grok-tool/audit-menu-snapshot", {
        "store_number": args.store_number,
        "order_type": args.order_type,
        "include_raw_cache": False,
        "include_derived_payloads": False,
    })
    if status == 404:
        return None, "audit endpoint returned 404"
    snapshot_guard.observe("audit-menu-snapshot", response)
    if status != 200 or response.get("ok") is not True:
        return None, f"audit endpoint failed: HTTP {status}: {response_failure_text(response) or response}"
    return response, None


async def async_main(args: argparse.Namespace) -> int:
    started_at = utc_now()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    client = BackendClient(
        args.base_url,
        args.api_key,
        args.api_key_header,
        timeout=args.timeout,
        transport_retries=args.transport_retries,
    )
    snapshot_guard = SnapshotGuard()
    try:
        audit_response, audit_error = await collect_audit(client, args, snapshot_guard)
        mappings = AuditMappings(audit_response)
        catalog_evidence = await collect_catalogs(client, args, snapshot_guard)
        coupon_plans, coupon_evidence = await collect_coupon_plans(client, args, snapshot_guard)

        coverage = Coverage()
        cases: list[TestCase] = []
        catalogs = {category: unwrap_catalog(row["response"]) for category, row in catalog_evidence.items()}

        if "pizza" in catalogs:
            for case in generate_pizza_cases(args, catalogs["pizza"], mappings, coverage):
                cases.append(case)
        for category in ("calzone", "wings", "subs", "salads", "sides_appetizers", "desserts"):
            if category in catalogs:
                for case in generate_standard_cases(args, category, catalogs[category], mappings, coverage):
                    cases.append(case)
        if "beverages" in catalogs:
            for case in generate_beverage_cases(args, catalogs["beverages"], mappings, coverage):
                cases.append(case)

        for number, plan in sorted(coupon_plans.items()):
            for case in generate_coupon_cases(args, number, plan, mappings, coverage):
                cases.append(case)

        # Exact regression cases are mandatory even when coupon 148 is absent
        # from a list response, because this is the defect that triggered the
        # release gate.
        for case in exact_regression_148(args, mappings):
            add_case(cases, coverage, case)

        for case in generate_interaction_cases(args, cases):
            add_case(cases, coverage, case)

        # Deduplicate exact payload/case names defensively while preserving all
        # coverage tokens.
        unique_cases: list[TestCase] = []
        seen_names: set[str] = set()
        seen_payloads: set[tuple[str, str]] = set()
        for case in cases:
            key = (case.group, canonical_json(case.payload))
            if case.name in seen_names:
                raise RuntimeError(f"Duplicate test case name: {case.name}")
            seen_names.add(case.name)
            # Keep same payload if it asserts a different contract (negative vs
            # positive), otherwise avoid wasting thousands of identical calls.
            identity = (key[0], key[1] + f"|{case.expected_ok}|{case.expected_missing_contains}|{case.forbidden_missing_contains}")
            if identity in seen_payloads:
                continue
            seen_payloads.add(identity)
            unique_cases.append(case)
        cases = unique_cases

        if args.max_cases and len(cases) > args.max_cases:
            raise RuntimeError(
                f"Generated {len(cases)} cases, exceeding --max-cases={args.max_cases}. "
                "Raise the limit; the release gate will not silently sample."
            )

        # Snapshot must already be known before compilation. The audit endpoint
        # is preferred, but catalog/compile responses may also expose it.
        results: list[CaseResult] = []
        semaphore = asyncio.Semaphore(max(1, args.concurrency))

        async def guarded(case: TestCase) -> CaseResult:
            async with semaphore:
                return await run_case(
                    client,
                    case,
                    snapshot_guard,
                    mappings.available,
                    args.determinism_runs,
                )

        # Execute in stable batches to avoid overloading the production backend.
        for start in range(0, len(cases), args.batch_size):
            batch = cases[start:start + args.batch_size]
            batch_results = await asyncio.gather(*(guarded(case) for case in batch))
            results.extend(batch_results)
            completed = len(results)
            failed = sum(1 for row in results if not row.passed)
            print(f"[{completed}/{len(cases)}] completed; failures={failed}", flush=True)
            if args.stop_after_failures and failed >= args.stop_after_failures:
                print(f"Stopping after {failed} failures by explicit --stop-after-failures setting", flush=True)
                break

        collisions = find_distinct_collisions(cases[:len(results)], results)
        coverage_missing = coverage.missing
        test_failures = sum(1 for row in results if not row.passed)
        mandatory_failed = test_failures + len(collisions)

        incomplete_reasons: list[str] = []
        if not mappings.available:
            incomplete_reasons.append(audit_error or "authenticated private mapping audit unavailable")
        if snapshot_guard.snapshot is None:
            incomplete_reasons.append("no catalog_snapshot was returned; the test cannot prove one atomic menu snapshot")
        if snapshot_guard.mismatches:
            incomplete_reasons.extend(snapshot_guard.mismatches)
        if coverage_missing:
            incomplete_reasons.append(f"{len(coverage_missing)} declared coverage tokens were not exercised")
        if len(results) != len(cases):
            incomplete_reasons.append(f"only {len(results)} of {len(cases)} generated cases were executed")

        if mandatory_failed:
            status = "FAIL"
            exit_code = 1
        elif incomplete_reasons:
            status = "INCOMPLETE"
            exit_code = 2
        else:
            status = "PASS"
            exit_code = 0

        compiler_versions = sorted({
            str(row.response.get("compiler_version"))
            for row in results
            if row.response.get("compiler_version")
        })
        summary = GateSummary(
            version=VERSION,
            started_at=started_at,
            finished_at=utc_now(),
            store_number=args.store_number,
            order_type=args.order_type,
            catalog_snapshot=snapshot_guard.snapshot,
            catalog_versions=sorted(snapshot_guard.versions),
            compiler_versions=compiler_versions,
            audit_available=mappings.available,
            audit_exact_mapping_enabled=mappings.available,
            tests_total=len(results),
            tests_passed=sum(1 for row in results if row.passed),
            tests_failed=test_failures,
            mandatory_failed=mandatory_failed,
            coverage_expected=len(coverage.expected),
            coverage_tested=len(coverage.expected & coverage.tested),
            coverage_missing=coverage_missing,
            duplicate_output_collisions=len(collisions),
            status=status,
            exit_code=exit_code,
            safety={
                "compile_only": True,
                "price_called": False,
                "submit_called": False,
                "payment_called": False,
                "direct_onesystem_called": False,
                "direct_redis_called": False,
                "incomplete_reasons": incomplete_reasons,
            },
        )
        write_reports(
            output_dir,
            summary,
            cases[:len(results)],
            results,
            collisions,
            catalog_evidence,
            coupon_evidence,
            audit_response,
        )
        print(json.dumps(asdict(summary), indent=2), flush=True)
        return exit_code
    finally:
        await client.close()


def parse_csv_ints(value: str) -> tuple[int, ...]:
    out: list[int] = []
    for part in str(value or "").split(","):
        part = part.strip()
        if not part:
            continue
        out.append(int(part))
    return tuple(out)


def parse_csv_strings(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in str(value or "").split(",") if part.strip())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Strict current-snapshot compiler release gate. No price, submit, payment, or writes.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--base-url", default=os.getenv("PIZZA_BACKEND_URL", "https://pizza-ai-backend.onrender.com"))
    parser.add_argument("--api-key", default=os.getenv("PMD_BACKEND_API_KEY") or os.getenv("PIZZA_BACKEND_API_KEY") or "")
    parser.add_argument("--api-key-header", default=os.getenv("PIZZA_BACKEND_API_KEY_HEADER", "x-pmd-backend-key"))
    parser.add_argument("--store-number", type=int, default=1)
    parser.add_argument("--order-type", choices=("P", "D"), default="P")
    parser.add_argument("--phone", default="440-898-3900")
    parser.add_argument("--customer-name", default="Compiler Release Gate")
    parser.add_argument("--categories", type=parse_csv_strings, default=DEFAULT_CATEGORIES)
    parser.add_argument("--coupon-numbers", type=parse_csv_ints, default=DEFAULT_KNOWN_COUPONS)
    parser.add_argument("--coupon-queries", type=parse_csv_strings, default=("current specials", "lunch specials"))
    parser.add_argument(
        "--include-unavailable-coupons",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Compiler coverage includes supported plans even when a time-window makes them unavailable to callers",
    )
    parser.add_argument("--output-dir", default="compiler_gate_results")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--transport-retries", type=int, default=2)
    parser.add_argument("--determinism-runs", type=int, default=2)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--max-cases", type=int, default=10000)
    parser.add_argument("--stop-after-failures", type=int, default=0, help="0 means run every generated case")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not args.api_key:
        parser.error("Backend API key is required via --api-key, PMD_BACKEND_API_KEY, or PIZZA_BACKEND_API_KEY")
    if args.determinism_runs < 2:
        parser.error("--determinism-runs must be at least 2 for a release proof")
    if args.stop_after_failures < 0:
        parser.error("--stop-after-failures cannot be negative")
    random.seed(20260804)
    try:
        return asyncio.run(async_main(args))
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"FATAL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
