# Fabric Generator

Generate AXI/AXI-Lite/APB interconnect fabrics from YAML configuration files.

## Quick Start

```bash
python3 gen_fabric.py <config.yaml>
```

Example:

```bash
python3 gen_fabric.py configs/example_fabric.yaml -o ./output
```

## CLI Options

| Option                | Description                            |
|-----------------------|----------------------------------------|
| `config_path`         | YAML configuration file (required)     |
| `-o, --output-dir`    | Output directory (default: `./output`) |
| `-v, --validate-only` | Validate config without generating     |
| `-d, --debug`         | Print debug information                |
| `--show-chains`       | Show protocol conversion chains        |
| `--no-color`          | Disable colored output                 |

## Configuration Reference

```yaml
name: "my_fabric"
description: "SoC interconnect"

fabric:
  xbar_protocol: "axi"        # axi | axi_lite
  max_outstanding_txns: 8
  pipeline_stages: 1
  fall_through: false
  atop: false                 # Atomic operations

protocols:
  axi64:
    protocol: "AXI4"
    data_width: 64
    addr_width: 48
    id_width: 4
    user_width: 1

  axi_lite32:
    protocol: "AXI4_LITE"
    data_width: 32
    addr_width: 32

  apb32:
    protocol: "APB4"
    data_width: 32
    addr_width: 32

inputs:
  - name: "cpu"
    protocol: "axi64"
    id_width: 4

  - name: "dma"
    protocl: "axi64"
    id_width: 4

outputs:
  - name: "sram"
    protocol: "axi64"
    address_range:
      main: { base: 0x00000000, size: 0x10000 }

  - name: "registers"
    protocol: "apb32"
    address_range:
      uart: { base: 0x40000000, size: 0x1000 }
      spi: { base: 0x40100000, size: 0x1000 }

connectivity:
  cpu: [sram, registers]
  dma: [sram]
```

## Supported Protocols

| Protocol  | Requirements        |
|-----------|---------------------|
| AXI4      | `id_width` required |
| AXI4_LITE | -                   |
| APB4      | -                   |

## Protocol Conversion

The generator automatically inserts protocol converters:

| From      | To        | Converter                      |
|-----------|-----------|--------------------------------|
| AXI4      | AXI4_LITE | `axi_to_axi_lite`              |
| AXI4_LITE | APB4      | `axi_lite_to_apb`              |
| AXI4_LITE | AXI4      | `axi_lite_to_axi` (input side) |

Data width conversion is handled automatically when widths differ.

**Conversion chain example:** AXI 64-bit → AXI 32-bit → AXI-Lite 32-bit → APB 32-bit

## Generated Output

| File            | Description                                      |
|-----------------|--------------------------------------------------|
| `<name>.sv`     | Fabric top module with crossbar and converters   |
| `<name>_pkg.sv` | Package with types, parameters, and address maps |

## Unsupported Configurations

- AXI4 inputs with `xbar_protocol: axi_lite`
- AXI4 outputs with `xbar_protocol: axi_lite`
