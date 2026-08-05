# PMD Live Menu / Agent-Facing Catalog / Compiler Test Folder

Version: `2026-08-04-live-menu-parity-test-folder-v1`

This is the missing test folder for items 10-12. It changes no live app files.

## What it tests

### Live menu parity

The full parity run verifies the current menu snapshot against:

- what the agent-facing `get_ordering_catalog` returns;
- the compiler's private current name-to-ID mappings;
- item-specific options;
- pizza sizes, crust compatibility, toppings, styles, instructions, specialties and recipes;
- beverages and valid sizes;
- subs, wings, salads, sides/appetizers and desserts;
- current coupon-plan names/private mappings;
- representative compile round trips;
- `dropped_selections: []` and `accepted_cart` on successful compiles.

The parity test is read-only. It calls no price endpoint and no submit endpoint.

### Stop-and-wait prompt scan

The included current lab JS is scanned for the exact prompt-leak pattern seen in call `7333101092`: the exact payment question adjacent to literal `Stop and wait` text.

This scan should fail on the current JS because that leak has not been patched yet. It is included so the narrow prompt fix can be tested before the next phone call.

## Folder placement

Copy this entire folder into the full PizzaMan Dan backend repository. It can be placed anywhere, but the easiest layout is:

```text
<full app root>/PMD_LiveMenuParity_TestFolder_2026-08-04/
```

The full app root must contain:

```text
app/services/grok_cart_builder.py
```

The tester locates that root automatically. If it does not, set:

```text
PMD_APP_ROOT=/path/to/full/app/root
```

## Run locally

Install the small web-test dependencies:

```bash
pip install -r requirements.txt
```

Start the test UI:

```bash
uvicorn main:app --host 0.0.0.0 --port 10000
```

Open the browser and use these buttons:

1. `Run Store 1 Pickup Full` for the current lab.
2. `Run Store 21 Pickup Full` and `Run Store 21 Delivery Full` for production-store cache parity.
3. `Run Stop-and-Wait Prompt Scan` before the next phone test.

## Environment

The parity script imports the real application code and therefore uses the same Redis/oneSystem environment variables as the backend.

Optional tester variables:

```text
TESTER_ACCESS_TOKEN=
PMD_APP_ROOT=
TESTER_TIMEOUT_SECONDS=900
```

## Pass criteria

A full parity run passes only when:

- `failed` is zero;
- all agent-visible names/options have compiler mappings;
- the same current snapshot is used;
- representative compile round trips succeed;
- every successful compile has `dropped_selections: []`;
- `accepted_cart` is returned.

The prompt scan passes only after the payment-question leak pattern is removed. A live phone call remains required to prove Grok does not speak internal instructions.

## Full compiler release gate added

This complete folder now includes `main.py` with a visible **Run Full Compiler Test** button. No patcher is required.

New files placed beside `main.py`:

```text
compiler_gate_routes.py
pmd_compiler_release_gate.py
selftest_release_gate.py
compiler_gate_runs/.gitkeep
```

The button opens `/compiler-gate`. The gate dynamically discovers the current catalog and coupon plans, generates exhaustive compile-only cases, and writes complete reports under `compiler_gate_runs/`.

Required environment for the compiler gate:

```text
PIZZA_BACKEND_URL=https://pizza-ai-backend.onrender.com
PMD_BACKEND_API_KEY=<same backend key already used by the tester or Voximplant>
PIZZA_BACKEND_API_KEY_HEADER=x-pmd-backend-key
TESTER_TIMEOUT_SECONDS=3600
```

The compiler gate calls only catalog, coupon-plan, private audit, and compile-only endpoints. It does not price, submit, tokenize payment, transfer, or write to oneSystem.

Strict outcomes:

- `PASS`: all mandatory generated cases pass with complete proof.
- `FAIL`: at least one compiler contract fails.
- `INCOMPLETE`: full coverage or private mapping proof was unavailable.
- `ERROR`: setup, authentication, connection, or execution failed.
