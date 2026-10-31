# Contributing

Thanks for helping. Three kinds of contribution are especially welcome:

1. **A new device**: one YAML file transcribed from the vendor's documentation.
2. **A hardware verification**: you read a map's registers from a real device and they matched.
3. **A correction**: a wrong address, type, unit or byte order, with the source or the reading that shows it.

## Add a device

1. Create `devices/<vendor>/<model>.yaml`, lower case and hyphenated, for example
   `devices/eastron/sdm630-modbus.yaml`. Copying an existing file is the quickest start.
2. List at least one source under `sources`: the title, publisher, version, an `https://` link to the vendor's
   register document and the date you accessed it (`accessed`). Add the document number (`document_id`) and the
   file's SHA-256 (`sha256`) when you can, so readers can tell when the source changes. Maps without a public source
   can't be accepted.
3. Write `address` as the zero-based protocol address, the number sent on the wire:

   | The manual says | Write |
   |---|---|
   | 30001 or 300001 (input register) | `table: input`, `address: 0` |
   | 40101 (holding register) | `table: holding`, `address: 100` |
   | 0x0034 or "start address 00 34" | `address: 52` |
   | "register 1" with function code 3 | check the example frames; usually `address: 0` |

   When the manual mixes conventions, its example request frame settles it.
4. Use `byte_order` for 32-bit and 64-bit values when the device does not follow `connection.default_byte_order`:
   ABCD is big-endian, CDAB swaps the 16-bit words (common on meters).
5. If a register holds a scaled integer, give `scale`: a value of 2305 with `scale: 0.1` reads as 230.5.
6. Run the checks:

   ```bash
   pip install pyyaml==6.0.2 jsonschema==4.23.0
   python3 tools/maps.py validate
   python3 tools/maps.py catalog
   ```

   `catalog` adds your device to the table in README.md; commit that change too.

## Importers

`tools/importers/` converts machine-readable vendor files (Schneider PowerLogic and Altivar workbooks, Fronius SunSpec
maps) into maps. When a vendor publishes a new revision, rerun the importer with the header in
`tools/importers/headers/` instead of editing the generated file by hand.

## Verify a device

The easy way is [proxus-mcp](https://github.com/proxusiiotplatform/proxus-mcp): connect it to your device, ask your
AI assistant to verify the device's map, and confirm two values against the device's display when it asks. Its
`verify_device_map` tool reads the map's registers (read-only), runs plausibility checks and gives you a link that
opens a prefilled verification issue. A bot checks the report and opens a pull request that adds you to the map.

Levels:

| Level | Meaning |
|---|---|
| L1 | At least 90% of the map's registers answered |
| L2 | L1, and the automatic checks passed (frequency in range, no garbage floats, counters do not run backwards) |
| L3 | L2, and you matched at least two values with the device's display |

You can also add an entry by hand:

```yaml
verified:
  - by: your-github-name
    date: 2026-10-31
    level: L3
    firmware: "1.03"          # if the device reports one
    registers: [voltage_l1_n, active_power_total]   # the values you compared, or [all]
    notes: Modbus TCP through a USR-TCP232 gateway, unit id 1
```

## Rules

- Transcribe facts (addresses, types, units). Don't paste whole tables or text from a manual.
- One device model per file. Variants with a different map get their own file; variants with the same map go in
  `aliases`.
- Keep `key` stable once merged: other tools refer to it.
- Leave out registers the source marks as reserved or for manufacturer use.

By opening a pull request you agree that your contribution is licensed under CC BY 4.0 (maps) and Apache-2.0
(tooling), as described in the README.
