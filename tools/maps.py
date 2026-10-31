#!/usr/bin/env python3
"""Validate the register maps, build the JSON index and keep the README catalog current.

    python3 tools/maps.py validate          # schema plus cross-field checks
    python3 tools/maps.py build [out_dir]   # dist/index.json and dist/devices/<vendor>/<model>.json
    python3 tools/maps.py catalog [--check] # rewrite (or check) the catalog table in README.md
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parent.parent
DEVICES = ROOT / "devices"
SCHEMA = ROOT / "schema" / "device.schema.json"
README = ROOT / "README.md"
CATALOG_START = "<!-- catalog:start -->"
CATALOG_END = "<!-- catalog:end -->"

REGISTER_COUNT = {
    "bool": 1, "uint16": 1, "int16": 1, "bitfield16": 1,
    "uint32": 2, "int32": 2, "float32": 2,
    "uint64": 4, "int64": 4, "float64": 4,
}
LENGTH_TYPES = ("string", "bitfield", "raw")
REFERENCE_PREFIX = {"coil": 0, "discrete_input": 1, "input": 3, "holding": 4}
PROXUS_MCP_PREFIX = {"coil": "coil", "discrete_input": "di", "input": "ir", "holding": "hr"}
FUNCTION_CODE = {"coil": 1, "discrete_input": 2, "input": 4, "holding": 3}


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def register_count(reg: dict) -> int:
    return reg["length"] if reg["type"] in LENGTH_TYPES else REGISTER_COUNT[reg["type"]]


def reference(table: str, address: int) -> str:
    """The traditional 1-based reference, e.g. input address 0 -> 30001; six digits above 9998."""
    prefix = REFERENCE_PREFIX[table]
    if address <= 9998:
        return f"{prefix}{address + 1:04d}"
    return f"{prefix}{address + 1:05d}"


class StrictLoader(yaml.SafeLoader):
    """Safe loader that rejects duplicate keys, which plain YAML silently overwrites."""


def _construct_mapping(loader, node, deep=False):
    keys = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in keys:
            raise yaml.constructor.ConstructorError(None, None, f"duplicate key {key!r}", key_node.start_mark)
        keys.add(key)
    return loader.construct_mapping(node, deep)


StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)
# Keep dates as the strings the schema describes instead of datetime.date objects.
StrictLoader.yaml_implicit_resolvers = {
    ch: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for ch, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.load(f, Loader=StrictLoader)


def device_files() -> list[Path]:
    return sorted(DEVICES.glob("*/*.yaml"))


def check_device(path: Path, doc: dict, validator: jsonschema.Draft202012Validator) -> list[str]:
    rel = path.relative_to(ROOT)
    errors = [
        f"{rel}: {'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}"
        for e in sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path))
    ]
    if errors:
        return errors

    expected = Path("devices") / slug(doc["vendor"]) / f"{slug(doc['model'])}.yaml"
    if rel != expected:
        errors.append(f"{rel}: file should be {expected} (vendor and model, lower case, hyphenated)")

    modes = set(doc.get("wiring_modes", [])) | set(doc.get("variants", []))
    keys: set[str] = set()
    spans: dict[str, list[tuple[int, int, str]]] = {}
    for reg in doc["registers"]:
        key = reg["key"]
        if key in keys:
            errors.append(f"{rel}: register key {key!r} is used twice")
        keys.add(key)
        count = register_count(reg)
        if reg["address"] + count > 65536:
            errors.append(f"{rel}: {key}: address {reg['address']} + {count} registers runs past 65535")
        spans.setdefault(reg["table"], []).append((reg["address"], reg["address"] + count, key))
        unknown = set(reg.get("applies_to", [])) - modes
        if unknown:
            errors.append(f"{rel}: {key}: applies_to names {sorted(unknown)}, not listed in wiring_modes or variants")
        if "values" in reg and reg["type"] == "string":
            errors.append(f"{rel}: {key}: a string register cannot list values")

    for table, items in spans.items():
        items.sort()
        for (start_a, end_a, key_a), (start_b, _, key_b) in zip(items, items[1:]):
            if start_b < end_a:
                errors.append(f"{rel}: {table} registers {key_a} ({start_a}) and {key_b} ({start_b}) overlap")

    for entry in doc.get("verified", []):
        missing = [k for k in entry["registers"] if k != "all" and k not in keys]
        if missing:
            errors.append(f"{rel}: verified by {entry['by']} names unknown registers {missing}")
    return errors


def validate() -> int:
    validator = jsonschema.Draft202012Validator(
        json.loads(SCHEMA.read_text(encoding="utf-8")),
        format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
    )
    errors: list[str] = []
    seen: dict[tuple[str, str], Path] = {}
    files = device_files()
    stray = [p for p in DEVICES.rglob("*") if p.is_file() and p not in files and p.name != ".gitkeep"]
    errors += [f"{p.relative_to(ROOT)}: only devices/<vendor>/<model>.yaml files belong here" for p in stray]
    docs = []
    for path in files:
        try:
            doc = load(path)
        except yaml.YAMLError as e:
            errors.append(f"{path.relative_to(ROOT)}: not valid YAML: {e}")
            continue
        if not isinstance(doc, dict):
            errors.append(f"{path.relative_to(ROOT)}: expected a mapping at the top level")
            continue
        errors += check_device(path, doc, validator)
        ident = (slug(str(doc.get("vendor", ""))), slug(str(doc.get("model", ""))))
        if ident in seen:
            errors.append(f"{path.relative_to(ROOT)}: same vendor and model as {seen[ident].relative_to(ROOT)}")
        seen[ident] = path
        docs.append((path, doc))

    for e in errors:
        print(f"error: {e}")
    total = sum(len(d.get("registers", [])) for _, d in docs)
    print(f"{len(files)} device(s), {total} register(s), {len(errors)} error(s)")
    write_summary(docs, errors)
    return 1 if errors else 0


def write_summary(docs: list[tuple[Path, dict]], errors: list[str]) -> None:
    """Job summary on GitHub Actions; needs no write permission, so it works for forks too."""
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return
    lines = ["## Register map check", ""]
    if errors:
        lines += ["Fix these before the pull request can be merged:", ""]
        lines += [f"- `{e}`" for e in errors]
    else:
        lines += ["All maps are valid.", "", "| Device | Registers | Hardware-verified |", "|---|---|---|"]
        for _, d in docs:
            lines.append(f"| {d['vendor']} {d['model']} | {len(d['registers'])} | {'yes' if d.get('verified') else 'no'} |")
    with open(target, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def enrich(doc: dict) -> dict:
    default_order = doc["connection"].get("default_byte_order", "ABCD")
    registers = []
    for reg in doc["registers"]:
        count = register_count(reg)
        item = dict(reg)
        item["count"] = count
        item["reference"] = reference(reg["table"], reg["address"])
        item["address_hex"] = f"0x{reg['address']:04X}"
        item["function_code"] = FUNCTION_CODE[reg["table"]]
        item["proxus_mcp_address"] = f"{PROXUS_MCP_PREFIX[reg['table']]}:{reg['address']}"
        if count > 1 and reg["type"] not in LENGTH_TYPES:
            item.setdefault("byte_order", default_order)
        registers.append(item)
    out = dict(doc)
    out["id"] = f"{slug(doc['vendor'])}/{slug(doc['model'])}"
    out["registers"] = registers
    return out


def build(out_dir: Path) -> int:
    if validate():
        return 1
    index = []
    for path in device_files():
        device = enrich(load(path))
        target = out_dir / "devices" / f"{device['id']}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(device, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        index.append({
            "id": device["id"],
            "vendor": device["vendor"],
            "model": device["model"],
            "aliases": device.get("aliases", []),
            "category": device["category"],
            "summary": device["summary"],
            "registers": len(device["registers"]),
            "hardware_verified": bool(device.get("verified")),
            "path": f"devices/{device['id']}.json",
        })
    (out_dir / "index.json").write_text(
        json.dumps({"schema_version": 1, "devices": index}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(index)} device(s) to {out_dir}")
    return 0


def catalog_table() -> str:
    rows = ["| Vendor | Model | Category | Registers | Hardware-verified |", "|---|---|---|---|---|"]
    for path in device_files():
        d = load(path)
        rel = path.relative_to(ROOT).as_posix()
        rows.append(f"| {d['vendor']} | [{d['model']}]({rel}) | {d['category']} | {len(d['registers'])} | "
                    f"{'yes' if d.get('verified') else 'not yet'} |")
    return "\n".join(rows)


def catalog(check: bool) -> int:
    text = README.read_text(encoding="utf-8")
    start, end = text.index(CATALOG_START) + len(CATALOG_START), text.index(CATALOG_END)
    updated = text[:start] + "\n" + catalog_table() + "\n" + text[end:]
    if updated == text:
        return 0
    if check:
        print("error: the catalog in README.md is out of date; run python3 tools/maps.py catalog")
        return 1
    README.write_text(updated, encoding="utf-8")
    print("updated the catalog in README.md")
    return 0


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else "validate"
    if command == "validate":
        return validate()
    if command == "build":
        return build(Path(argv[2]) if len(argv) > 2 else ROOT / "dist")
    if command == "catalog":
        return catalog("--check" in argv[2:])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
