#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("gate", HERE / "pmd_compiler_release_gate.py")
assert SPEC and SPEC.loader
G = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = G
SPEC.loader.exec_module(G)


def args():
    return SimpleNamespace(
        store_number=1,
        order_type="P",
        phone="440-898-3900",
        customer_name="Self Test",
    )


AUDIT = {
    "ok": True,
    "catalog_snapshot": "fixture-snapshot",
    "compiler": {
        "identifier_sets": {"SALAD_ITEM_IDS_REQUIRING_DRESSING": [37, 38]},
        "fixed_ids": {"calzone_size_id": 7, "calzone_crust_id": 4},
        "mappings": {
            "SIZE_BY_NAME": {"medium": 3, "large": 4},
            "CRUST_BY_NAME": {"thin crust": 1, "pan style": 2},
            "PIZZA_TOPPING_BY_NAME": {"pepperoni": 18, "mushrooms": 24, "red sauce": 1},
            "SPECIALTY_BY_NAME": {"the meatsa pizza": 6, "bar-b-que chicken calzone": 5},
            "INSTRUCTION_BY_NAME": {"square cut": 201},
            "SALAD_ITEM_BY_NAME": {"antipasto salad": 38, "garden salad": 37},
            "DRESSING_BY_NAME": {"w/ bleu cheese": 135, "w/ ranch": 132, "bleu cheese": 135, "ranch": 132},
            "CALZONE_DIP_EXACT_BY_NAME": {"marinara dip": 92, "ranch dip": 91},
            "WING_ITEM_BY_NAME": {"(12) traditional wings": 60},
            "WING_SAUCE_BY_NAME": {"bbq sauce": 210},
            "WING_INSTRUCTION_BY_NAME": {"all drums": 211},
            "SUB_ITEM_BY_NAME": {"dan's italian sub": 660},
            "SUB_OPTION_BY_NAME": {"no provolone": 301},
            "SIDE_ITEM_BY_NAME": {"regular wedge": 51},
            "SIDE_OPTION_BY_NAME": {"with ranch": 162},
            "DESSERT_BY_NAME": {"pizza cookie": 70},
            "BEV_TYPE_BY_NAME": {"coke": 304},
            "BEV_SIZE_BY_NAME": {"can": 1},
        }
    },
}

PIZZA = {
    "ok": True,
    "catalog_snapshot": "fixture-snapshot",
    "items": [{"name": "Build Your Own Pizza"}],
    "sizes": [{"name": "Medium"}, {"name": "Large"}],
    "crusts_by_size": {
        "Medium": [{"name": "Thin Crust"}, {"name": "Pan Style"}],
        "Large": [{"name": "Thin Crust"}],
    },
    "toppings": [{"name": "Pepperoni"}, {"name": "Mushrooms"}],
    "sauces": [{"name": "Red Sauce"}],
    "pizza_instructions": [{"name": "Square Cut"}],
    "specialty_pizzas": [{"name": "The Meatsa Pizza"}],
}

SALADS = {
    "ok": True,
    "items": [{"name": "Antipasto Salad"}, {"name": "Garden Salad"}],
    "dressings": [{"name": "w/ Ranch"}, {"name": "w/ Bleu Cheese"}],
}

BEVERAGES = {
    "ok": True,
    "items": [{"name": "Coke", "sizes": [{"name": "CAN"}]}],
}

COUPON_148 = {
    "coupon_number": 148,
    "required_choices": [
        {"choice_type": "calzone", "minimum": 1, "choices": ["Bar-B-Que Chicken Calzone"]},
        {"choice_type": "calzone_dip", "minimum": 1, "choices": ["Marinara Dip", "Ranch Dip"], "required_after_choice": "calzone", "send_as": "option_names on the selected calzone coupon_component"},
        {"choice_type": "salad", "minimum": 1, "choices": ["Antipasto Salad", "Garden Salad"]},
        {"choice_type": "salad_dressing", "minimum": 1, "choices": ["Bleu Cheese", "Ranch"], "required_after_choice": "salad", "send_as": "option_names on the selected salad coupon_component"},
        {"choice_type": "drink", "minimum": 1, "choices": ["Can / Coke"]},
    ],
    "dependent_required_choices": [
        {"when_selected_item_name": "Antipasto Salad", "label": "dressing", "choices": ["w/ Bleu Cheese", "w/ Ranch"]},
        {"when_selected_item_name": "Garden Salad", "label": "dressing", "choices": ["w/ Ranch", "w/ Bleu Cheese"]},
    ],
}


class FakeClient:
    async def post(self, path, payload):
        assert path == "/grok-tool/compile-order-list"
        items = payload["items"]
        # Exact regression succeeds and returns a stable private cart.
        if payload.get("coupon_numbers") == [148]:
            calzone = next((x for x in items if x.get("choice_type") == "calzone"), None)
            salad = next((x for x in items if x.get("choice_type") == "salad"), None)
            drink = next((x for x in items if x.get("choice_type") == "drink"), None)
            if calzone and salad and drink and calzone.get("option_names") and salad.get("option_names"):
                return 200, {
                    "ok": True,
                    "catalog_snapshot": "fixture-snapshot",
                    "order_json": {
                        "pizzas": [{"size_id": 7, "type_id": 4, "combo_id": 5}],
                        "menu_items": [
                            {"id": 92},
                            {"id": 38, "modifier_ids": [135]},
                            {"id": 304},
                        ],
                        "coupons": [{"id": 148}],
                    },
                }, 1
            return 200, {
                "ok": False,
                "catalog_snapshot": "fixture-snapshot",
                "first_missing_question": "Which dip for the calzone?",
                "missing_questions": ["Which dip for the calzone?"],
            }, 1
        return 200, {
            "ok": True,
            "catalog_snapshot": "fixture-snapshot",
            "order_json": {"menu_items": [{"id": 1}], "pizzas": [], "beverages": [], "coupons": []},
        }, 1


async def main():
    a = args()
    mapping = G.AuditMappings(AUDIT)
    coverage = G.Coverage()

    pizza_cases = G.generate_pizza_cases(a, PIZZA, mapping, coverage)
    assert any(c.group == "pizza.size_crust" for c in pizza_cases)
    assert any(c.group == "pizza.topping" for c in pizza_cases)
    assert any(c.group == "pizza.specialty" for c in pizza_cases)

    salad_cases = G.generate_standard_cases(a, "salads", SALADS, mapping, coverage)
    assert any(c.expected_ok is False for c in salad_cases)
    assert any("bleu" in c.name for c in salad_cases)

    beverage_cases = G.generate_beverage_cases(a, BEVERAGES, mapping, coverage)
    assert beverage_cases and beverage_cases[0].payload["items"][0]["size"] == "CAN"

    coupon_cases = G.generate_coupon_cases(a, 148, COUPON_148, mapping, coverage)
    dependent = [c for c in coupon_cases if c.group == "coupon.dependent"]
    assert dependent
    exact = [c for c in dependent if "antipasto" in c.name and "bleu" in c.name]
    assert exact
    exact_row = next(x for x in exact[0].payload["items"] if x.get("choice_type") == "salad")
    assert exact_row["option_names"] == ["w/ Bleu Cheese"]

    regression = G.exact_regression_148(a, mapping)[0]
    result = await G.run_case(FakeClient(), regression, G.SnapshotGuard(), False, 2)
    assert result.passed, result.failures

    # Verify the legacy separate-row regression does not silently pass in the
    # fake compiler; this proves the special contract path is being checked.
    legacy = G.exact_regression_148(a, mapping)[1]
    result2 = await G.run_case(FakeClient(), legacy, G.SnapshotGuard(), False, 2)
    assert not result2.passed

    print(json.dumps({
        "ok": True,
        "pizza_cases": len(pizza_cases),
        "salad_cases": len(salad_cases),
        "beverage_cases": len(beverage_cases),
        "coupon_cases": len(coupon_cases),
        "coverage_expected": len(coverage.expected),
        "coverage_tested": len(coverage.tested),
        "exact_regression_passed": result.passed,
        "legacy_contract_detected": not result2.passed,
    }, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
