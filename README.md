# Modbus Register Maps

Open, machine-readable Modbus register maps for energy meters, inverters, drives and other field devices.
Each device is one YAML file with the address, data type, byte order, unit and scale of every register, and the
document it was transcribed from.

Vendor manuals bury this in PDF tables with mixed addressing conventions (30001, 0x0000, "register 1"). Here
every address is the zero-based value sent on the wire, and the 30001-style reference is derived from it, so the
two can never disagree.

## Devices

<!-- catalog:start -->
| Vendor | Model | Category | Registers | Hardware-verified |
|---|---|---|---|---|
| ABB | [B23/B24](devices/abb/b23-b24.yaml) | energy-meter | 121 | not yet |
| Eastron | [SDM120-Modbus](devices/eastron/sdm120-modbus.yaml) | energy-meter | 32 | not yet |
| Eastron | [SDM630-Modbus](devices/eastron/sdm630-modbus.yaml) | energy-meter | 97 | not yet |
| Fronius | [Primo GEN24 Plus/Symo GEN24 Plus](devices/fronius/primo-gen24-plus-symo-gen24-plus.yaml) | inverter | 224 | not yet |
| Fronius | [Primo GEN24/Symo GEN24](devices/fronius/primo-gen24-symo-gen24.yaml) | inverter | 178 | not yet |
| Fronius | [Smart Meter](devices/fronius/smart-meter.yaml) | energy-meter | 73 | not yet |
| Fronius | [Tauro ECO](devices/fronius/tauro-eco.yaml) | inverter | 168 | not yet |
| Fronius | [Tauro](devices/fronius/tauro.yaml) | inverter | 188 | not yet |
| Fronius | [Verto 3 MPPT](devices/fronius/verto-3-mppt.yaml) | inverter | 188 | not yet |
| Fronius | [Verto 4 MPPT](devices/fronius/verto-4-mppt.yaml) | inverter | 198 | not yet |
| Fronius | [Verto Plus](devices/fronius/verto-plus.yaml) | inverter | 234 | not yet |
| Schneider Electric | [ATV320](devices/schneider-electric/atv320.yaml) | vfd | 1071 | not yet |
| Schneider Electric | [ATV340](devices/schneider-electric/atv340.yaml) | vfd | 1741 | not yet |
| Schneider Electric | [ATV600](devices/schneider-electric/atv600.yaml) | vfd | 1879 | not yet |
| Schneider Electric | [ATV900](devices/schneider-electric/atv900.yaml) | vfd | 1911 | not yet |
| Schneider Electric | [PM5100/PM5300](devices/schneider-electric/pm5100-pm5300.yaml) | power-analyzer | 877 | not yet |
| Schneider Electric | [PM5500/PM5600/PM5700](devices/schneider-electric/pm5500-pm5600-pm5700.yaml) | power-analyzer | 3108 | not yet |
| Siemens | [PAC3200](devices/siemens/pac3200.yaml) | power-analyzer | 151 | not yet |
| Siemens | [PAC4200](devices/siemens/pac4200.yaml) | power-analyzer | 222 | not yet |
<!-- catalog:end -->

"Hardware-verified" means someone read the registers from a real device and recorded it under `verified`.
The other maps are transcribed from the sources they list. Have one of these devices? A verification is one of the
most useful contributions you can make.

## Format

```yaml
schema_version: 1
vendor: Eastron
model: SDM630-Modbus
category: energy-meter
summary: Three-phase DIN-rail energy meter with RS485 Modbus RTU; every value is a 32-bit float.
connection:
  interfaces: [rtu]
  default_unit_id: 1
  default_byte_order: ABCD
sources:
  - title: Eastron SDM630Modbus Smart Meter Modbus Protocol Implementation
    publisher: Eastron
    version: V1.8
    url: https://...
registers:
  - key: voltage_l1_n
    name: Phase 1 line to neutral voltage
    table: input        # coil, discrete_input, input or holding
    address: 0          # zero-based protocol address (reference 30001)
    type: float32       # bool, int16, uint16, int32, uint32, float32, int64, uint64, float64, string, bitfield16
    unit: V
    access: r
```

Optional per register: `byte_order` (ABCD, CDAB, BADC, DCBA), `scale` (engineering value = raw × scale),
`scale_factor` (key of a register holding a power-of-ten exponent, as SunSpec devices use), `length` (for `string`,
`bitfield` and `raw`),
`values` (meaning of enumerated values), `applies_to` (wiring modes), `group`, `description` and `notes`.
The full contract is [schema/device.schema.json](schema/device.schema.json).

## Use the data

`python3 tools/maps.py build` writes `dist/index.json` and one JSON file per device. Each register gains its
30001-style `reference`, `address_hex`, Modbus `function_code`, effective `byte_order` and a
`proxus_mcp_address`.

The last one plugs into [Proxus Industrial MCP Server](https://github.com/proxusiiotplatform/proxus-mcp), which
lets AI assistants such as Claude read Modbus devices. With a map at hand you can ask:

> Read ir:52 on meter-1 as float32 ABCD. It's the total active power of an Eastron SDM630.

## Contribute

Adding a device takes one YAML file and a pull request; a check runs on every pull request and explains anything
that needs fixing. See [CONTRIBUTING.md](CONTRIBUTING.md). No device of your own? Ask for one with a
[device request](../../issues/new?template=device-request.yml).

## Corrections and removal requests

Maps record facts (addresses, data types, units) in this project's own format and words, with a link to the
document they come from. Vendor documents themselves are never stored here.

Found a wrong register? Open an issue or a pull request with the source or a reading that shows it. If you represent
a manufacturer and want a map corrected, linked to a newer document or removed, open an issue or contact the
maintainers through the repository owner's GitHub profile; requests are handled within five working days.

## Licence

The maps (`devices/`) are under [CC BY 4.0](LICENSE-DATA). If you reuse them, credit
"Modbus Register Maps by Proxus contributors" with a link to this repository. The tooling and schema are under
[Apache-2.0](LICENSE).

Register maps describe how devices communicate; vendor names and model numbers belong to their owners. Always check
a map against your device's documentation before you write to a register.
