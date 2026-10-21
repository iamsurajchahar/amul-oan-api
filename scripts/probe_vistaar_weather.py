#!/usr/bin/env python
"""Probe the Bharat Vistaar weather (Mausamgram) path hop by hop.

**Why this exists.** When weather breaks, the farmer — and the model — only see
"Weather is temporarily unavailable". That one sentence covers a seeker that is
unreachable, a `vistaar` leg that timed out, a BV BAP that collected no
on_search (`responses: []`), a BPP that answered with a Beckn error callback,
and a catalogue the tool could not render. This script sends the tool's exact
intent (`vistaar._weather_intent`) and prints what each hop returned, so the
failing hop is named rather than guessed.

Run it from a box that can reach the seeker (the app's own network), with the
app's environment loaded.

Usage
-----
    .venv/bin/python scripts/probe_vistaar_weather.py                  # Anand, via the seeker
    .venv/bin/python scripts/probe_vistaar_weather.py --district kutch
    .venv/bin/python scripts/probe_vistaar_weather.py --direct         # also call the BV BAP directly
    .venv/bin/python scripts/probe_vistaar_weather.py --dump out.json  # keep raw bodies for a fixture
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from agents.tools import vistaar  # noqa: E402
from agents.tools.districts import DISTRICTS  # noqa: E402
from app.config import settings  # noqa: E402


async def _post(url: str, payload: dict) -> tuple[dict | None, dict]:
    """POST and describe the hop; never raises."""
    started = time.monotonic()
    report: dict = {"url": url}
    try:
        async with httpx.AsyncClient(timeout=settings.amul_network_timeout_s) as client:
            r = await client.post(url, json=payload)
        report.update(status=r.status_code, bytes=len(r.content))
        body = r.json() if r.content else None
    except Exception as exc:  # noqa: BLE001 - the point is to report it
        report["error"] = f"{type(exc).__name__}: {exc}"
        body = None
    report["elapsed_s"] = round(time.monotonic() - started, 2)
    return body, report


def _describe_on_search(on_search) -> dict:
    if not isinstance(on_search, dict):
        return {"on_search": type(on_search).__name__}
    out = {"keys": sorted(on_search), "failure": vistaar._on_search_failure(on_search)}
    try:
        items = vistaar._items(on_search)
    except Exception as exc:  # noqa: BLE001 - a malformed reply is a finding, not a crash
        out["items_error"] = f"{type(exc).__name__}: {exc}"
        return out
    out["items"] = len(items)
    if items:
        out["first_item_rendered"] = vistaar._format_items(items[:1]) or "(renders empty)"
    return out


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--district", default="anand", choices=sorted(DISTRICTS))
    parser.add_argument("--direct", action="store_true", help="also call VISTAAR_BAP_URL directly")
    parser.add_argument("--dump", type=Path, default=None, help="write raw response bodies here")
    args = parser.parse_args()

    candidate = DISTRICTS[args.district].primary
    intent = vistaar._weather_intent(candidate)
    print(f"intent ({candidate.town}): {json.dumps(intent)}\n")
    raw: dict = {}

    if vistaar.VISTAAR_SEEKER_URL:
        leg = vistaar.VISTAAR_LEG
        body, hop = await _post(f"{vistaar.VISTAAR_SEEKER_URL}/search", {"intent": intent, "legs": [leg]})
        raw["seeker"] = body
        if isinstance(body, dict):
            hop["leg"] = leg
            hop["leg_error"] = (body.get("errors") or {}).get(leg)
            hop.update(_describe_on_search((body.get("results") or {}).get(leg)))
        print("seeker:", json.dumps(hop, indent=2, ensure_ascii=False), "\n")
    else:
        print("seeker: VISTAAR_SEEKER_URL is empty — the tool calls the BV BAP directly\n")

    if args.direct or not vistaar.VISTAAR_SEEKER_URL:
        body, hop = await _post(
            f"{vistaar.VISTAAR_BAP_URL}/search",
            {"context": vistaar._context(), "message": {"intent": intent}},
        )
        raw["direct"] = body
        if isinstance(body, dict):
            hop.update(_describe_on_search(body))
        print("direct BAP:", json.dumps(hop, indent=2, ensure_ascii=False), "\n")

    # What the model would actually have been handed for this district.
    out = await vistaar.get_vistaar_weather(None, DISTRICTS[args.district].display)
    print("tool output:\n" + out)

    if args.dump:
        args.dump.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
        print(f"\nwrote {args.dump}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
