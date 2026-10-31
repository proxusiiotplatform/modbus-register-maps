#!/usr/bin/env python3
"""Convert a Schneider Electric PowerLogic register list (XLS/XLSX) into a device map.

    python3 tools/importers/schneider_powerlogic.py <register-list.xls[x]> <header.yaml> <out.yaml>

header.yaml holds everything above `registers:` (vendor, model, sources...). The importer keeps
the measurement, setup, status and I/O registers and leaves out the command buffer, alarm
configuration, file and HMI areas, which are only usable through the meter's command interface.

Schneider numbers registers from 1, so address = register - 1 (the same offset mbmd's iEM3000
driver and other working PM5000 clients use).

Needs xlrd==2.0.1 for .xls and openpyxl==3.1.5 for .xlsx.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SKIP_CATEGORIES = {"Command Interface", "Alarms", "Files", "HMI", "Diagnostics"}
SUPPORTED = {"Y", "O"}  # Y standard, O option; P (private) and R are left out
TYPES = {
    "INT16U": "uint16", "INT16": "int16", "INT32U": "uint32", "INT32": "int32",
    "INT64": "int64", "FLOAT32": "float32", "4Q_FP_PF": "float32",
}
UNITS = {"---": None, "": None, "None": None}


def rows(path: Path):
    if path.suffix.lower() == ".xls":
        import xlrd
        sheet = xlrd.open_workbook(str(path)).sheet_by_name("Register List")
        return [["" if c is None else c for c in sheet.row_values(r)] for r in range(sheet.nrows)]
    import openpyxl
    sheet = openpyxl.load_workbook(str(path), read_only=True, data_only=True)["Register List"]
    return [["" if c is None else c for c in row] for row in sheet.iter_rows(values_only=True)]


def text(value) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def snake(value: str) -> str:
    value = value.replace("+", " plus ").replace("%", " pct ").replace("&", " and ")
    value = re.sub(r"(?<=[a-z0-9])-(?=[a-z0-9])", "_", value.lower())
    value = re.sub(r"[^a-z0-9]+", "_", value).strip("_")
    return ("r_" + value if value[:1].isdigit() else value)[:64].rstrip("_")


def q(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def convert(source: Path) -> tuple[list[str], list[dict], dict]:
    table = rows(source)
    header = [text(c) for c in table[0]]
    col = {name: header.index(name) for name in ("Description", "Register", "Units", "Data Type", "Access")}
    col["Size"] = next(i for i, h in enumerate(header) if h.startswith("Size"))
    first_model = header.index("Description") + 1
    model_cols = []
    for i in range(first_model, len(header)):
        if not re.match(r"^PM\d", header[i]):
            break
        model_cols.append(i)
    variants = [header[i].replace("_", "/") for i in model_cols]

    registers, seen_addr, keys = [], set(), set()
    stats = {"skipped_category": 0, "skipped_unsupported": 0, "skipped_command_only": 0, "duplicate_address": 0}
    category = sub1 = sub2 = ""
    for row in table[1:]:
        row = list(row) + [""] * (len(header) - len(row))
        if text(row[0]):
            category, sub1, sub2 = text(row[0]), "", ""
        if text(row[1]):
            sub1, sub2 = text(row[1]), ""
        if text(row[2]):
            sub2 = text(row[2])
        name, reg, dtype = text(row[col["Description"]]), text(row[col["Register"]]), text(row[col["Data Type"]])
        if not name or not reg or dtype in ("", "---"):
            continue
        if category in SKIP_CATEGORIES:
            stats["skipped_category"] += 1
            continue
        flags = [text(row[i]) for i in model_cols]
        valid = [v for v, f in zip(variants, flags) if f in SUPPORTED]
        if not valid:
            stats["skipped_unsupported"] += 1
            continue
        access_raw = text(row[col["Access"]])
        if access_raw in ("WC", "---", ""):
            stats["skipped_command_only"] += 1
            continue
        address = int(float(reg)) - 1
        size = int(float(text(row[col["Size"]]) or 1))
        if ("holding", address) in seen_addr:
            stats["duplicate_address"] += 1
            continue
        seen_addr.add(("holding", address))

        notes = []
        if dtype in TYPES and TYPES[dtype] in ("uint16", "int16") and size > 1:
            typ = "raw"
            notes.append(f"{size} consecutive {dtype} values.")
        elif dtype in TYPES:
            typ = TYPES[dtype]
        elif dtype == "UTF8":
            typ = "string"
        elif dtype == "BITMAP":
            typ = "bitfield16" if size == 1 else "bitfield"
        else:
            typ = "raw"
            notes.append(f"Schneider {dtype} encoding.")
        if dtype == "4Q_FP_PF":
            notes.append("Four-quadrant power factor encoding (4Q_FP_PF): the value range also gives the quadrant.")
        if access_raw == "RWC":
            access = "r"
            notes.append("Change it through the meter's setup commands; writing the register directly is refused.")
        else:
            access = {"R": "r", "RW": "rw"}[access_raw]

        group = snake(sub1 or category)
        key = snake(name)
        if key in keys:
            key = snake(f"{sub2 or sub1} {name}")
        if key in keys:
            key = f"{snake(name)}_{address}"
        keys.add(key)

        item = {"key": key, "name": name, "group": group, "table": "holding", "address": address, "type": typ}
        if typ in ("string", "bitfield", "raw"):
            item["length"] = size
        unit = UNITS.get(text(row[col["Units"]]), text(row[col["Units"]]))
        if unit:
            item["unit"] = unit
        item["access"] = access
        if len(valid) < len(variants):
            item["applies_to"] = valid
        if notes:
            item["notes"] = " ".join(notes)
        registers.append(item)
    return variants, registers, stats


def emit(item: dict) -> str:
    parts = []
    for k, v in item.items():
        if isinstance(v, list):
            parts.append(f"{k}: [{', '.join(q(x) for x in v)}]")
        elif isinstance(v, int):
            parts.append(f"{k}: {v}")
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
    variants, registers, stats = convert(source)
    head = header.read_text(encoding="utf-8").rstrip("\n")
    body = "\n".join(emit(r) for r in registers)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"{head}\nvariants: [{', '.join(q(v) for v in variants)}]{kept_verified(out)}\nregisters:\n{body}\n", encoding="utf-8")
    print(f"{out}: {len(registers)} registers, variants {variants}, {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
