# Contributing

Thanks for helping. Three kinds of contribution are especially welcome:

1. **A new device**: one YAML file transcribed from the vendor's documentation.
2. **A hardware verification**: you read a map's registers from a real device and they matched.
3. **A correction**: a wrong address, type, unit or byte order, with the source or the reading that shows it.

## Add a device

1. Create `devices/<vendor>/<model>.yaml`, lower case and hyphenated, for example
   `devices/eastron/sdm630-modbus.yaml`. Copying an existing file is the quickest start.
2. List at least one source under `sources`: the title, publisher, version and an `https://` link to the vendor's
   register document. Maps without a public source can't be accepted.
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

## Verify a device

Read a few registers from a real device, compare them with what the display or the vendor software shows, then add
an entry:

```yaml
verified:
  - by: your-github-name
    date: 2026-10-31
    firmware: "1.03"          # if the device reports one
    registers: [voltage_l1_n, active_power_total, import_active_energy]   # or [all]
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
