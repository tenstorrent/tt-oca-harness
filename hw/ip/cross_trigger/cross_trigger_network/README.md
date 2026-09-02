# Cross Trigger Network

DTP integration of the Cross Trigger Matrix and Cross Trigger Ports into one AXI-Lite CSR space.

## Documentation

Authoritative description and register maps: `hw/ip/cross_trigger/cross_trigger_network/doc/` (published in the TRM under DTP).

## Location

- RTL: `hw/ip/cross_trigger/cross_trigger_network/rtl/`
- Registers: CTM/CTP maps under the sibling IP `regs/` trees (CTN has no register block of its own).

## Verification

Block-level bench on the unified DV flow: `dv/README.md`
(`python3 tools/dv/run_dv.py --dut cross_trigger_network`).
