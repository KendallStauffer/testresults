#!/usr/bin/env python3
"""Verify nightly menu cache -> Grok catalog -> compiler parity.

Run from the application repository with its normal environment configured:

    python tools/test_grok_live_menu_parity.py --store-number 21 --order-type P

The test is read-only. It does not price or submit an order. It loads the same
current menu snapshot used by the agent/compiler, verifies every exposed name
and option has a private compiler mapping, and runs representative compile
round trips that must return zero dropped selections.
"""
from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from app.api.retell_tools import _get_or_build_coupon_ingredients
from app.services.grok_dynamic_menu import (
    build_live_menu_snapshot,
    customer_safe_category,
    customer_safe_item_options,
    norm,
    resolve_item_options,
)
from app.services import grok_cart_builder as cart


class Report:
    def __init__(self) -> None:
        self.checks: List[Dict[str, Any]] = []

    def check(self, name: str, passed: bool, detail: Any = "") -> None:
        self.checks.append({"name": name, "passed": bool(passed), "detail": detail})

    def fail(self, name: str, detail: Any) -> None:
        self.check(name, False, detail)

    def as_dict(self, *, store_number: int, order_type: str, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        passed = sum(1 for row in self.checks if row["passed"])
        failed = len(self.checks) - passed
        return {
            "ok": failed == 0,
            "store_number": store_number,
            "order_type": order_type,
            "catalog_version": snapshot.get("version"),
            "catalog_snapshot": snapshot.get("snapshot_id"),
            "catalog_sources": snapshot.get("sources"),
            "passed": passed,
            "failed": failed,
            "checks": self.checks,
            "note": "Read-only catalog/compiler parity test. No price or submit call was made.",
        }


def _names(rows: Iterable[Dict[str, Any]]) -> Set[str]:
    return {norm(row.get("name")) for row in rows or [] if isinstance(row, dict) and norm(row.get("name"))}


def _name_to_id(rows: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        name = norm(row.get("name"))
        try:
            row_id = int(row.get("id"))
        except Exception:
            continue
        if name:
            out[name] = row_id
    return out


def _agent_item_map(category_payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in category_payload.get("items") or []:
        if isinstance(row, dict) and norm(row.get("name")):
            out[norm(row.get("name"))] = row
    return out


def _private_item_map(snapshot: Dict[str, Any], category: str) -> Dict[str, Dict[str, Any]]:
    private = ((snapshot.get("categories") or {}).get(category) or {}).get("items") or []
    return {norm(row.get("name")): row for row in private if isinstance(row, dict) and norm(row.get("name"))}


def _base_payload(store_number: int, order_type: str) -> Dict[str, Any]:
    return {
        "store_number": store_number,
        "order_type": order_type,
        "phone": "440-555-0199",
        "customer_name": "Parity Test",
    }


def _first_regular_pizza_basis(snapshot: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    pizza = (snapshot.get("categories") or {}).get("pizza") or {}
    allowed = pizza.get("allowed_crust_ids_by_size_id") or {}
    crust_by_id = {int(row["id"]): row.get("name") for row in pizza.get("crusts") or []}
    for size in pizza.get("sizes") or []:
        name = str(size.get("name") or "")
        if norm(name) in {"calzone", "no", "slice"}:
            continue
        ids = allowed.get(str(size.get("id"))) or allowed.get(size.get("id")) or []
        if ids:
            return name, str(crust_by_id[int(ids[0])])
    return None, None


def _compile_and_check(report: Report, name: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    result = cart.compile_order_list(payload)
    report.check(name + ":compile_ok", bool(result.get("ok")), result if not result.get("ok") else "")
    if not result.get("ok"):
        return None
    report.check(name + ":same_snapshot", bool(result.get("catalog_snapshot")), result.get("catalog_snapshot"))
    report.check(name + ":no_dropped_selections", result.get("dropped_selections") == [], result.get("dropped_selections"))
    report.check(name + ":accepted_cart_returned", isinstance(result.get("accepted_cart"), dict), result.get("accepted_cart"))
    return result


def verify_pizza(report: Report, snapshot: Dict[str, Any], store_number: int, order_type: str) -> None:
    private = (snapshot.get("categories") or {}).get("pizza") or {}
    agent = customer_safe_category(store_number, order_type, "pizza")
    report.check("pizza:agent_snapshot_matches", agent.get("catalog_snapshot") == snapshot.get("snapshot_id"), {"agent": agent.get("catalog_snapshot"), "private": snapshot.get("snapshot_id")})

    sections = {
        "sizes": cart.SIZE_BY_NAME,
        "crusts": cart.CRUST_BY_NAME,
        "toppings": cart.PIZZA_TOPPING_BY_NAME,
        "cheese_and_sauce_style": cart.TOPPING_BY_NAME,
        "pizza_instructions": cart.INSTRUCTION_BY_NAME,
        "specialty_pizzas": cart.SPECIALTY_BY_NAME,
    }
    agent_names = {key: _names(agent.get(key) or []) for key in sections}
    agent_names["crusts"] = {
        norm(name)
        for names in (agent.get("crusts_by_size") or {}).values()
        for name in (names or [])
        if name
    }
    for key, compiler_map in sections.items():
        for row in private.get(key) or []:
            name = str(row.get("name") or "")
            if not name:
                continue
            # Calzone is intentionally omitted from the broad pizza browse list;
            # it is verified below through the focused current calzone contract.
            if key in {"sizes", "crusts"} and norm(name) == "calzone":
                continue
            report.check(f"pizza:{key}:visible:{name}", norm(name) in agent_names[key], sorted(agent_names[key]))
            try:
                expected_id = int(row.get("id"))
            except Exception:
                report.fail(f"pizza:{key}:id:{name}", row)
                continue
            report.check(f"pizza:{key}:compiler_map:{name}", compiler_map.get(norm(name)) == expected_id, compiler_map.get(norm(name)))


    calzone_size_names = {norm(row.get("name")) for row in private.get("sizes") or [] if norm(row.get("name")) == "calzone"}
    if calzone_size_names:
        calzone = customer_safe_item_options(store_number, order_type, "pizza", "Calzone")
        report.check("pizza:calzone:focused_lookup", bool(calzone.get("ok")), calzone)
        report.check("pizza:calzone:snapshot_matches", calzone.get("catalog_snapshot") == snapshot.get("snapshot_id"), {"agent": calzone.get("catalog_snapshot"), "private": snapshot.get("snapshot_id")})
        report.check("pizza:calzone:size_visible", calzone_size_names == _names(calzone.get("sizes") or []), {"agent": sorted(_names(calzone.get("sizes") or [])), "private": sorted(calzone_size_names)})
        calzone_private_crusts = set()
        crust_by_id = {int(row["id"]): norm(row.get("name")) for row in private.get("crusts") or [] if row.get("id") is not None}
        allowed = private.get("allowed_crust_ids_by_size_id") or {}
        for row in private.get("sizes") or []:
            if norm(row.get("name")) != "calzone" or row.get("id") is None:
                continue
            ids = allowed.get(str(int(row["id"]))) or allowed.get(int(row["id"])) or []
            calzone_private_crusts.update(crust_by_id[int(cid)] for cid in ids if int(cid) in crust_by_id)
        report.check("pizza:calzone:crust_visible", calzone_private_crusts == _names(calzone.get("crusts") or []), {"agent": sorted(_names(calzone.get("crusts") or [])), "private": sorted(calzone_private_crusts)})

    topping_by_id = {int(row["id"]): row.get("name") for row in private.get("toppings") or []}
    for specialty in private.get("specialty_pizzas") or []:
        expected = [topping_by_id[tid] for tid in specialty.get("included_topping_ids") or [] if tid in topping_by_id]
        report.check(
            f"pizza:specialty_recipe:{specialty.get('name')}",
            specialty.get("included_toppings") == expected,
            {"expected": expected, "actual": specialty.get("included_toppings")},
        )

    size_name, crust_name = _first_regular_pizza_basis(snapshot)
    if not size_name or not crust_name:
        report.fail("pizza:round_trip_basis", "No current regular pizza size/crust pair")
        return
    base = _base_payload(store_number, order_type)
    for topping in private.get("toppings") or []:
        name = str(topping.get("name") or "")
        if not name or norm(name) in {"red sauce"}:
            continue
        payload = {**base, "items": [{"category": "pizza", "item_name": "Build Your Own Pizza", "size": size_name, "crust": crust_name, "whole_toppings": [name]}]}
        result = _compile_and_check(report, f"pizza:topping_round_trip:{name}", payload)
        if result:
            compiled_ids = set(result["order_json"]["pizzas"][0].get("topping_ids") or [])
            report.check(f"pizza:topping_id_preserved:{name}", int(topping["id"]) in compiled_ids, sorted(compiled_ids))

    for style in private.get("cheese_and_sauce_style") or []:
        name = str(style.get("name") or "")
        if not name:
            continue
        payload = {**base, "items": [{"category": "pizza", "item_name": "Build Your Own Pizza", "size": size_name, "crust": crust_name, "whole_toppings": [next((row["name"] for row in private.get("toppings") or [] if norm(row.get("name")) not in {"red sauce", norm(name)}), name)], "sauce": name}]}
        _compile_and_check(report, f"pizza:style_round_trip:{name}", payload)

    for instruction in private.get("pizza_instructions") or []:
        name = str(instruction.get("name") or "")
        if not name:
            continue
        regular_topping = next((row["name"] for row in private.get("toppings") or [] if norm(row.get("name")) not in {"red sauce"} and "sauce" not in norm(row.get("name"))), None)
        if not regular_topping:
            report.fail(f"pizza:instruction_round_trip:{name}", "No regular topping available for test order")
            continue
        payload = {**base, "items": [{"category": "pizza", "item_name": "Build Your Own Pizza", "size": size_name, "crust": crust_name, "whole_toppings": [regular_topping], "instructions": [name]}]}
        _compile_and_check(report, f"pizza:instruction_round_trip:{name}", payload)

    for specialty in private.get("specialty_pizzas") or []:
        name = str(specialty.get("name") or "")
        if not name:
            continue
        payload = {**base, "items": [{"category": "pizza", "item_name": name, "size": size_name, "crust": crust_name}]}
        result = _compile_and_check(report, f"pizza:specialty_round_trip:{name}", payload)
        if result:
            combo_ids = {int(row.get("combo_id")) for row in result["order_json"]["pizzas"] if row.get("combo_id") is not None}
            report.check(f"pizza:specialty_id_preserved:{name}", int(specialty["id"]) in combo_ids, sorted(combo_ids))


def verify_beverages(report: Report, snapshot: Dict[str, Any], store_number: int, order_type: str) -> None:
    private = (snapshot.get("categories") or {}).get("beverages") or {}
    agent = customer_safe_category(store_number, order_type, "beverages")
    agent_map = _agent_item_map(agent)
    base = _base_payload(store_number, order_type)
    for row in private.get("items") or []:
        name = str(row.get("name") or "")
        report.check(f"beverage:visible:{name}", norm(name) in agent_map, sorted(agent_map))
        report.check(f"beverage:compiler_map:{name}", cart.BEV_TYPE_BY_NAME.get(norm(name)) == int(row["id"]), cart.BEV_TYPE_BY_NAME.get(norm(name)))
        agent_sizes = {norm(value) for value in (agent_map.get(norm(name), {}).get("sizes") or [])}
        private_sizes = {norm(size.get("name")) for size in row.get("sizes") or []}
        report.check(f"beverage:sizes_visible:{name}", agent_sizes == private_sizes, {"agent": sorted(agent_sizes), "private": sorted(private_sizes)})
        for size in row.get("sizes") or []:
            payload = {**base, "items": [{"category": "beverages", "item_name": name, "size": size.get("name")}]}
            _compile_and_check(report, f"beverage:round_trip:{name}:{size.get('name')}", payload)


def verify_standard_category(report: Report, snapshot: Dict[str, Any], store_number: int, order_type: str, category: str) -> None:
    private_map = _private_item_map(snapshot, category)
    agent = customer_safe_category(store_number, order_type, category)
    agent_map = _agent_item_map(agent)
    report.check(f"{category}:agent_snapshot_matches", agent.get("catalog_snapshot") == snapshot.get("snapshot_id"), {"agent": agent.get("catalog_snapshot"), "private": snapshot.get("snapshot_id")})
    report.check(f"{category}:all_items_visible", set(private_map) == set(agent_map), {"missing_from_agent": sorted(set(private_map) - set(agent_map)), "extra_in_agent": sorted(set(agent_map) - set(private_map))})

    compiler_map = (
        cart.SALAD_ITEM_BY_NAME if category == "salads"
        else cart.SIDE_ITEM_BY_NAME if category in {"sides_appetizers", "other_food"}
        else cart.DESSERT_BY_NAME if category == "desserts"
        else cart.WING_ITEM_BY_NAME if category == "wings"
        else cart.SUB_ITEM_BY_NAME if category == "subs"
        else cart.SIDE_ITEM_BY_NAME
    )
    for name_key, row in private_map.items():
        display = str(row.get("name") or "")
        report.check(f"{category}:compiler_map:{display}", compiler_map.get(name_key) == int(row["id"]), compiler_map.get(name_key))
        safe = customer_safe_item_options(store_number, order_type, category, display)
        if category == "wings":
            safe_options = {
                norm(option.get("name"))
                for key in ("wing_sauces", "wing_instructions")
                for option in safe.get(key) or []
                if isinstance(option, dict)
            }
            private_options = {
                norm(option.get("name"))
                for key in ("wing_sauces", "wing_instructions")
                for option in ((snapshot.get("categories") or {}).get("wings") or {}).get(key) or []
                if isinstance(option, dict)
            }
        else:
            safe_options = {norm(option.get("name")) for option in safe.get("options") or [] if isinstance(option, dict)}
            private_options = {norm(option.get("name")) for option in row.get("options") or [] if isinstance(option, dict)}
        report.check(f"{category}:options_visible:{display}", safe_options == private_options, {"agent": sorted(safe_options), "private": sorted(private_options)})
        for option in row.get("options") or []:
            option_name = str(option.get("name") or "")
            resolved = resolve_item_options(store_number, order_type, int(row["source_item_id"] or row["id"]), [option_name])
            report.check(
                f"{category}:option_resolves:{display}:{option_name}",
                bool(resolved.get("ok")) and int(option["id"]) in {int(x) for x in resolved.get("resolved_option_ids") or []},
                resolved,
            )

    if category == "wings":
        wings_private = (snapshot.get("categories") or {}).get("wings") or {}
        for row in wings_private.get("wing_sauces") or []:
            name = str(row.get("name") or "")
            if name:
                report.check(f"wings:sauce_compiler_map:{name}", cart.WING_SAUCE_BY_NAME.get(norm(name)) == int(row["id"]), cart.WING_SAUCE_BY_NAME.get(norm(name)))
        for row in wings_private.get("wing_instructions") or []:
            name = str(row.get("name") or "")
            if name:
                report.check(f"wings:instruction_compiler_map:{name}", cart.WING_INSTRUCTION_BY_NAME.get(norm(name)) == int(row["id"]), cart.WING_INSTRUCTION_BY_NAME.get(norm(name)))


def verify_representative_standard_round_trips(report: Report, snapshot: Dict[str, Any], store_number: int, order_type: str) -> None:
    base = _base_payload(store_number, order_type)
    for category in ("salads", "sides_appetizers", "desserts", "wings", "subs"):
        private = (snapshot.get("categories") or {}).get(category) or {}
        for row in private.get("items") or []:
            name = str(row.get("name") or "")
            if not name:
                continue
            item: Dict[str, Any] = {"category": category, "item_name": name}
            options = row.get("options") or []
            # Use one exact current option when the item has choices. This
            # exercises the item-specific private resolver without inventing a choice.
            if options:
                item["option_names"] = [options[0].get("name")]
            result = cart.compile_order_list({**base, "items": [item]})
            if not result.get("ok"):
                # Some rows are browse-only/internal or require a distinct business
                # combination. Mapping/option parity above is still mandatory; record
                # the full reason rather than silently skipping the item.
                report.fail(f"{category}:round_trip:{name}", result)
                continue
            report.check(f"{category}:round_trip:{name}", result.get("dropped_selections") == [], result.get("dropped_selections"))


def verify_coupon_choices(report: Report, snapshot: Dict[str, Any], store_number: int, order_type: str) -> None:
    try:
        payload = _get_or_build_coupon_ingredients(store_number, order_type=order_type)
    except Exception as exc:
        report.fail("coupons:load_current_plans", str(exc))
        return
    plans = payload.get("agent_coupon_plans") or {}
    report.check("coupons:plans_dict", isinstance(plans, dict), type(plans).__name__)
    all_menu_by_id: Dict[int, str] = {}
    for category in ("salads", "sides_appetizers", "desserts", "wings", "subs", "other_food"):
        for row in ((snapshot.get("categories") or {}).get(category) or {}).get("items") or []:
            all_menu_by_id[int(row["id"])] = str(row.get("name") or "")
    pizza_by_id = {int(row["id"]): str(row.get("name") or "") for row in ((snapshot.get("categories") or {}).get("pizza") or {}).get("specialty_pizzas") or []}
    beverage_by_id = {int(row["id"]): str(row.get("name") or "") for row in ((snapshot.get("categories") or {}).get("beverages") or {}).get("items") or []}

    for coupon_id, plan in plans.items():
        if not isinstance(plan, dict):
            continue
        rows: List[Dict[str, Any]] = []
        rows.extend(row for row in plan.get("fixed_items") or [] if isinstance(row, dict))
        for choice in plan.get("required_choices") or []:
            if isinstance(choice, dict):
                rows.extend(row for row in choice.get("choices") or [] if isinstance(row, dict))
        for row in rows:
            item_id = row.get("item_id")
            if item_id in (None, ""):
                continue
            try:
                item_id_int = int(item_id)
            except Exception:
                report.fail(f"coupon:{coupon_id}:numeric_private_id", row)
                continue
            ingredient_type = norm(row.get("ingredient_type") or row.get("choice_type"))
            display = str(row.get("display_name") or row.get("item_name") or row.get("name") or "")
            lookup = pizza_by_id if ingredient_type == "pizza" else beverage_by_id if ingredient_type == "beverage" else all_menu_by_id
            actual = lookup.get(item_id_int)
            report.check(
                f"coupon:{coupon_id}:choice_current:{display or item_id_int}",
                actual is not None and (not display or norm(actual) == norm(display) or norm(display) in norm(actual) or norm(actual) in norm(display)),
                {"coupon_choice": display, "current_menu": actual, "item_id": item_id_int, "ingredient_type": ingredient_type},
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store-number", type=int, required=True)
    parser.add_argument("--order-type", choices=["P", "D"], required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--skip-round-trips", action="store_true", help="Run structural parity only; still validates every name and option mapping.")
    args = parser.parse_args()

    report = Report()
    try:
        snapshot = build_live_menu_snapshot(args.store_number, args.order_type)
    except Exception as exc:
        output = {"ok": False, "error": "CURRENT_MENU_SNAPSHOT_UNAVAILABLE", "detail": str(exc)}
        text = json.dumps(output, indent=2) + "\n"
        if args.output:
            args.output.write_text(text)
        print(text, end="")
        return 1

    context = cart._live_compiler_context(snapshot)
    token = cart._LIVE_CATALOG_CONTEXT.set(context)
    try:
        verify_pizza(report, snapshot, args.store_number, args.order_type)
        verify_beverages(report, snapshot, args.store_number, args.order_type)
        for category in ("subs", "wings", "salads", "sides_appetizers", "desserts", "other_food"):
            verify_standard_category(report, snapshot, args.store_number, args.order_type, category)
        verify_coupon_choices(report, snapshot, args.store_number, args.order_type)
        if not args.skip_round_trips:
            verify_representative_standard_round_trips(report, snapshot, args.store_number, args.order_type)
    finally:
        cart._LIVE_CATALOG_CONTEXT.reset(token)

    output = report.as_dict(store_number=args.store_number, order_type=args.order_type, snapshot=snapshot)
    text = json.dumps(output, indent=2, default=str) + "\n"
    if args.output:
        args.output.write_text(text)
    print(text, end="")
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
