"""Find test names that mean the same measurement (TSH / Thyroid Stimulating Hormone / S. TSH).

The AI only PROPOSES groups. Code then checks every proposal, and the user confirms each
merge in the app before anything is renamed:
  - every name must be a test the user really has (no invented names)
  - a name can sit in one group only
  - names the built-in rules already know as different tests (Free T3 vs T3, HDL vs LDL ...)
    are never put together
  - groups the user already rejected are not offered again
  - groups whose units differ (mg/dL vs mmol/L) are flagged for extra care
"""
import json
import logging
import re

from analyze import _RULES, _iter_objects, compute_status
from llm import chat

log = logging.getLogger("lablens")
KNOWN_DISTINCT = {r[0] for r in _RULES}

SYSTEM = ("You help clean up a patient's lab test list. You decide which test names are exactly the "
          "same measurement written differently. Output JSON only.")
PROMPT = """Below are lab test names from one person's reports, with the unit each was reported in.
Group names that are THE SAME measurement: synonyms, abbreviations, spelling or wording variants,
or the same name with a prefix such as "S." or "Serum".

Return ONLY a JSON array: [{{"names": ["exact name 1", "exact name 2"], "into": "the clearest name from that list", "reason": "short reason"}}]

Rules:
- Copy names exactly as listed. Only group names that are listed.
- Only group tests that measure the exact same thing. Do NOT group related but different tests, for example:
  Free T3 vs Total T3, HDL vs LDL vs Total Cholesterol, Direct vs Total Bilirubin, Fasting vs Post-meal glucose,
  Absolute count vs percentage (Neutrophils % vs Neutrophils Absolute), Hemoglobin vs HbA1c, Urea vs Creatinine.
- A test that has no other name in the list is left out. If nothing matches, return [].

Example input:
- TSH (uIU/mL)
- Thyroid Stimulating Hormone (uIU/mL)
- Free T3 (pg/mL)
- Total T3 (ng/dL)
- Vitamin B12 (pg/mL)
- Cyanocobalamin (pg/mL)
Example output:
[{{"names":["TSH","Thyroid Stimulating Hormone"],"into":"TSH","reason":"same hormone"}},
{{"names":["Vitamin B12","Cyanocobalamin"],"into":"Vitamin B12","reason":"cyanocobalamin is vitamin B12"}}]

Test names:
{items}
"""


def _unit_key(u: str) -> str:
    return re.sub(r"[\s.]", "", (u or "").lower().replace("µ", "u").replace("μ", "u"))


def suggest_groups(tests: list[dict], dismissed: set[str]) -> list[dict]:
    """tests: [{name, unit, n}] sorted most-used first. Returns validated groups."""
    tests = tests[:150]
    if len(tests) < 2:
        return []
    info = {t["name"]: t for t in tests}
    listing = "\n".join(f"- {t['name']} ({t['unit'] or 'no unit'})" for t in tests)
    raw = chat(SYSTEM, PROMPT.format(items=listing), max_tokens=2500, temperature=0)

    used, out = set(), []
    for o in _iter_objects(raw):
        names = o.get("names")
        if not isinstance(names, list):
            continue
        names = [n for n in dict.fromkeys(str(n) for n in names) if n in info and n not in used]
        # never merge two tests the built-in rules treat as different tests
        fixed = [n for n in names if n in KNOWN_DISTINCT]
        if len(fixed) > 1:
            keep = max(fixed, key=lambda n: info[n]["n"])
            names = [n for n in names if n not in KNOWN_DISTINCT or n == keep]
        if len(names) < 2:
            continue
        key = "|".join(sorted(n.lower() for n in names))
        if key in dismissed:
            continue
        into = str(o.get("into") or "")
        if into not in names:
            into = max(names, key=lambda n: info[n]["n"])
        fixed = [n for n in names if n in KNOWN_DISTINCT]
        if fixed:
            into = fixed[0]
        units = {_unit_key(info[n]["unit"]) for n in names if info[n]["unit"]}
        used.update(names)
        out.append({"names": names, "into": into, "reason": str(o.get("reason") or "")[:160],
                    "unit_mismatch": len(units) > 1})
    return out


def apply_aliases(results: list[dict], aliases: dict) -> list[dict]:
    """Rename rows to the names this user already confirmed, then drop same-report duplicates."""
    if not aliases:
        return results
    out, seen = [], {}
    for r in results:
        name = aliases.get(r["test_name"].lower(), r["test_name"])
        if name != r["test_name"]:
            r = {**r, "test_name": name, "status": compute_status(name, r["value"], r["ref_low"], r["ref_high"])}
        if name in seen:
            i = seen[name]
            if out[i]["ref_low"] is None and out[i]["ref_high"] is None and (
                    r["ref_low"] is not None or r["ref_high"] is not None):
                out[i] = r
            continue
        seen[name] = len(out)
        out.append(r)
    return out
