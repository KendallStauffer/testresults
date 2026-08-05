#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

PAYMENT_QUESTION = "Would you like to pay by card with me now, or pay at the store when you arrive?"


def scan(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    occurrences = []
    for idx, line in enumerate(lines, start=1):
        if "stop and wait" in line.lower():
            occurrences.append({"line": idx, "text": line.strip()})

    payment_line = next((i for i, line in enumerate(lines, start=1) if PAYMENT_QUESTION in line), None)
    nearby = []
    if payment_line:
        start = max(1, payment_line - 1)
        end = min(len(lines), payment_line + 3)
        nearby = [{"line": i, "text": lines[i - 1].strip()} for i in range(start, end + 1)]

    payment_leak_risk = bool(payment_line and any(
        "stop and wait" in row["text"].lower() for row in nearby
    ))

    spoken_force_risks = []
    for idx, line in enumerate(lines, start=1):
        lower = line.lower()
        if "say exactly" in lower and "stop and wait" in lower:
            spoken_force_risks.append({"line": idx, "text": line.strip()})

    return {
        "ok": not payment_leak_risk and not spoken_force_risks,
        "file": str(path),
        "payment_question_found": payment_line is not None,
        "payment_question_line": payment_line,
        "payment_nearby_lines": nearby,
        "payment_stop_and_wait_leak_risk": payment_leak_risk,
        "all_stop_and_wait_occurrences": occurrences,
        "force_message_stop_and_wait_risks": spoken_force_risks,
        "note": (
            "This is a static prompt-contract check. It does not replace a live phone call. "
            "It fails when the exact payment question is adjacent to literal 'Stop and wait' text, "
            "the pattern spoken in call 7333101092."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--js", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = scan(args.js)
    text = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
