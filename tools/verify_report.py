#!/usr/bin/env python3
"""Check a hardware verification report and record it in the device map.

    python3 tools/verify_report.py <issue-body.md> --by <github-login> --report-url <issue-url> \
        [--apply] [--summary summary.md]

The report is the JSON block that proxus-mcp's verify_device_map tool puts in a verification issue. The level is
recomputed from the evidence and the lower of claimed and computed wins:

    L1  at least 90% of the checked registers answered
    L2  L1, and every automatic check passed (at least one ran)
    L3  L2, and a person matched at least two values with the device's display (within 3%)

Outcome (printed and written as `outcome=` to $GITHUB_OUTPUT): verified (with --apply the map gains a verified
entry), problem (the device refused many registers: a map correction is needed), stale (the map changed since the
report), duplicate, or invalid.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parent))
import maps  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REPORT_SCHEMA = ROOT / "schema" / "verification-report.schema.json"
LEVELS = ["L0", "L1", "L2", "L3"]


def extract(body: str) -> dict:
    """The report from an issue body: the first fenced JSON block, or the first {...} object."""
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", body, re.S)
    text = match.group(1) if match else body[body.find("{"): body.rfind("}") + 1]
    if not text:
        raise ValueError("no JSON report found in the issue")
    return json.loads(text)


def tolerance_ok(shown: str, read: str) -> bool:
    shown_value, read_value = float(shown.replace(",", ".")), float(read)
    decimals = len(shown.replace(",", ".").partition(".")[2])
    allowed = max(0.03 * abs(shown_value), 0.5 * 10 ** -decimals)
    return abs(read_value - shown_value) <= allowed


def computed_level(report: dict) -> tuple[str, list[str]]:
    reasons = []
    regs = report["registers"]
    ratio = regs["read"] / regs["checked"]
    if ratio < 0.9:
        reasons.append(f"only {regs['read']} of {regs['checked']} registers answered")
        return "L0", reasons
    checks = report["checks"]
    failed = [c["name"] for c in checks if not c["passed"]]
    if not checks or failed:
        reasons.append("failed checks: " + ", ".join(failed) if failed else "no automatic check could run")
        return "L1", reasons
    confirmed = report.get("confirmed", [])
    matching = [c for c in confirmed if tolerance_ok(c["device_shows"], c["read"])]
    if len(matching) < 2:
        reasons.append(f"{len(matching)} value(s) matched the display; L3 needs 2")
        return "L2", reasons
    return "L3", reasons


def evaluate(report: dict) -> tuple[str, dict | None, Path | None, list[str]]:
    """Returns outcome, the verified entry to add, the map file and the notes for the summary."""
    validator = jsonschema.Draft202012Validator(json.loads(REPORT_SCHEMA.read_text(encoding="utf-8")))
    errors = [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}" for e in validator.iter_errors(report)]
    if errors:
        return "invalid", None, None, errors

    vendor, model = report["map"].split("/")
    path = maps.DEVICES / vendor / f"{model}.yaml"
    if not path.exists():
        return "invalid", None, None, [f"no map {report['map']} in this repository"]
    doc = maps.load(path)
    keys = {r["key"] for r in doc["registers"]}
    unknown = sorted({k for k in report["registers"]["unreadable"] + [c["key"] for c in report.get("confirmed", [])]
                      + [c["key"] for c in report["checks"] if "key" in c] if k not in keys})
    if unknown:
        return "invalid", None, path, [f"keys not in the map: {', '.join(unknown)}"]
    if report["map_sha256"] != maps.content_sha256(doc):
        return "stale", None, path, ["the report was made against an earlier version of this map's registers"]
    try:
        reported = date.fromisoformat(report["date"])
    except ValueError:
        return "invalid", None, path, ["date is not a valid date"]
    if reported > date.today():
        return "invalid", None, path, ["date is in the future"]

    level, notes = computed_level(report)
    if LEVELS.index(level) > LEVELS.index(report["level"]):
        level = report["level"]
    if level == "L0":
        return "problem", None, path, notes

    entry: dict = {"date": report["date"], "level": level}
    device = report.get("device", {})
    for field in ("model", "firmware"):
        if device.get(field):
            entry[field] = device[field]
    entry["tool"] = report["tool"]
    confirmed = [c["key"] for c in report.get("confirmed", []) if tolerance_ok(c["device_shows"], c["read"])]
    entry["registers"] = confirmed if level == "L3" else ["all"]
    if report["registers"]["unreadable"]:
        entry["unreadable"] = report["registers"]["unreadable"]
    if report["registers"]["unreadable_count"]:
        notes.append(f"{report['registers']['unreadable_count']} register(s) refused by the device")
    return "verified", entry, path, notes


def render(entry: dict, by: str, url: str) -> str:
    def q(value: str) -> str:
        return json.dumps(value, ensure_ascii=False)

    lines = [f"  - by: {by}", f"    date: {entry['date']}", f"    level: {entry['level']}"]
    for field in ("model", "firmware", "tool"):
        if field in entry:
            lines.append(f"    {field}: {q(entry[field])}")
    lines.append(f"    report: {url}")
    lines.append(f"    registers: [{', '.join(entry['registers'])}]")
    if entry.get("unreadable"):
        lines.append(f"    unreadable: [{', '.join(entry['unreadable'])}]")
    return "\n".join(lines) + "\n"


def insert(path: Path, block: str) -> None:
    text = path.read_text(encoding="utf-8")
    marker = "\nregisters:\n"
    # The verified list sits right above registers; a new entry goes at its end.
    index = text.index(marker)
    prefix = "\n" if "\nverified:\n" in text else "\nverified:\n"
    text = text[:index] + prefix + block.rstrip("\n") + text[index:]
    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("body")
    parser.add_argument("--by", required=True)
    parser.add_argument("--report-url", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--summary")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", args.by) or not re.fullmatch(r"https://github\.com/[\w.-]+/[\w.-]+/issues/\d+", args.report_url):
        print("invalid --by or --report-url")
        return 2

    try:
        report = extract(Path(args.body).read_text(encoding="utf-8"))
        outcome, entry, path, notes = evaluate(report)
    except (ValueError, KeyError, TypeError) as error:
        outcome, entry, path, notes = "invalid", None, None, [f"could not read the report: {error}"]

    if outcome == "verified" and path is not None:
        existing = maps.load(path).get("verified", [])
        if any(e["by"].lstrip("@").lower() == args.by.lower() and e["level"] == entry["level"]
               and e.get("firmware") == entry.get("firmware") for e in existing):
            outcome, notes = "duplicate", notes + [f"@{args.by} already recorded {entry['level']} for this firmware"]

    lines = [f"**Outcome: {outcome}**", ""]
    if entry:
        lines += [f"- Level: {entry['level']}", f"- Model / firmware: {entry.get('model', '?')} / {entry.get('firmware', '?')}"]
    lines += [f"- {n}" for n in notes]
    summary = "\n".join(lines) + "\n"
    print(summary)
    if args.summary:
        Path(args.summary).write_text(summary, encoding="utf-8")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"outcome={outcome}\n")
            if path is not None:
                f.write(f"map_file={path.relative_to(ROOT).as_posix()}\n")

    if outcome == "verified" and args.apply:
        insert(path, render(entry, args.by, args.report_url))
        if maps.validate() != 0:
            print("the map no longer validates after adding the entry")
            return 1
    return 0 if outcome in ("verified", "problem", "stale", "duplicate") else 1


if __name__ == "__main__":
    sys.exit(main())
