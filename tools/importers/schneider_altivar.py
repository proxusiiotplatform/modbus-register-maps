#!/usr/bin/env python3
"""Convert a Schneider Electric Altivar "communication parameters" workbook (XLSX) into a device map.

    python3 tools/importers/schneider_altivar.py <CommunicationParameters.xlsx> <header.yaml> <out.yaml>

The workbook's "Logic address" is the Modbus address sent on the wire: the ATV320 Modbus manual
(NVE41308) reads logic addresses 3102-3105 with start address 0C1E hex. Every parameter is one
16-bit holding register. Enumerated parameters get their values from the Enumerations sheet.

Needs openpyxl==3.1.5.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import openpyxl

TYPES = {"UINT": "uint16", "INT": "int16", "WORD": "uint16", "UDINT": "uint32", "DINT": "int32"}
ACCESS = {"R": "r", "R/W": "rw", "R/WS": "rw"}


def text(value) -> str:
    return "" if value is None else str(value).strip()


def snake(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return ("p_" + value if value[:1].isdigit() else value)[:64].rstrip("_")


def q(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def label(display: str) -> str:
    """'[Not done] (TAB)' -> 'Not done (TAB)'."""
    return re.sub(r"\s+", " ", display.replace("[", "").replace("]", "")).strip()


def enumerations(book) -> dict[str, dict[str, str]]:
    lists: dict[str, dict[str, str]] = {}
    current = None
    for row in list(book["Enumerations"].iter_rows(values_only=True))[1:]:
        if text(row[0]):
            current = lists.setdefault(text(row[0]), {})
        if current is not None and text(row[1]) and text(row[2]):
            current[text(row[1])] = label(text(row[2]))
    return lists


def convert(source: Path) -> tuple[list[dict], dict]:
    book = openpyxl.load_workbook(str(source), read_only=True, data_only=True)
    enums = enumerations(book)
    table = list(book["Parameters"].iter_rows(values_only=True))
    header = [text(c) for c in table[0]]
    col = {name: header.index(name) for name in
           ("Code", "Name", "Logic address", "Link", "Category", "Access", "Type", "Units")}
    registers, seen, keys = [], set(), set()
    stats = {"no_address": 0, "unknown_type": 0, "duplicate_address": 0}
    for row in table[1:]:
        code, name = text(row[col["Code"]]), text(row[col["Name"]])
        match = re.search(r"=\s*(\d+)", text(row[col["Logic address"]]))
        if not code or not match:
            stats["no_address"] += 1
            continue
        address = int(match.group(1))
        if address in seen:
            stats["duplicate_address"] += 1
            continue
        type_raw = text(row[col["Type"]])
        base = type_raw.split(" ")[0]
        if base not in TYPES:
            stats["unknown_type"] += 1
            continue
        seen.add(address)

        key = snake(code)
        if key in keys:
            key = f"{key}_{address}"
        keys.add(key)
        item: dict = {"key": key, "name": name or code, "group": snake(text(row[col["Category"]]) or "parameters"),
                      "table": "holding", "address": address,
                      "type": "bitfield16" if "BitString" in type_raw else TYPES[base]}
        unit_raw = text(row[col["Units"]])
        notes = [f"Parameter code {code}."]
        m = re.match(r"^([0-9.]+)\s*(.*)$", unit_raw)
        if m:
            scale, unit = float(m.group(1)), m.group(2).strip()
            if scale != 1:
                item["scale"] = scale
            if unit:
                item["unit"] = unit
        elif unit_raw and unit_raw != "-":
            notes.append("Unit and scale depend on other settings; see the programming manual.")
        access = text(row[col["Access"]])
        item["access"] = ACCESS.get(access, "r")
        if access == "R/WS":
            notes.append("Writable only while the drive is not running.")
        values = enums.get(text(row[col["Link"]])) if "Enumeration" in type_raw else None
        if values:
            item["values"] = values
            notes.append("Not every listed value is valid for this parameter; see the programming manual.")
        item["notes"] = " ".join(notes)
        registers.append(item)
    return registers, stats


def emit(item: dict) -> str:
    parts = []
    for k, v in item.items():
        if isinstance(v, dict):
            parts.append(f"{k}: {{{', '.join(f'{q(a)}: {q(b)}' for a, b in v.items())}}}")
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            parts.append(f"{k}: {v:g}" if isinstance(v, float) else f"{k}: {v}")
        else:
            parts.append(f"{k}: {q(v) if k in ('name', 'unit', 'notes') else v}")
    return "  - {" + ", ".join(parts) + "}"


def kept_verified(out: Path) -> str:
    """The verified block of an existing map, so regenerating a map never drops hardware verifications."""
    previous = out.read_text(encoding="utf-8") if out.exists() else ""
    if "\nverified:\n" not in previous:
        return ""
    return previous[previous.index("\nverified:\n"):previous.index("\nregisters:\n")]


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(__doc__)
        return 2
    source, header, out = map(Path, argv[1:])
    registers, stats = convert(source)
    head = header.read_text(encoding="utf-8").rstrip("\n")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"{head}{kept_verified(out)}\nregisters:\n" + "\n".join(emit(r) for r in registers) + "\n", encoding="utf-8")
    print(f"{out}: {len(registers)} registers, {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
