# Cross Trigger Matrix

Configurable crossbar that routes cross-trigger pulses between CT_Dst sources and CT_Src sinks in OCAH.

## Documentation

Authoritative description and register maps: `hw/ip/cross_trigger/cross_trigger_matrix/doc/` (published in the TRM under DTP).

## Location

- RTL: `hw/ip/cross_trigger/cross_trigger_matrix/rtl/`
- Registers: `hw/ip/cross_trigger/cross_trigger_matrix/regs/`

## Verification

Block-level bench on the unified DV flow: `dv/README.md`
(`python3 tools/dv/run_dv.py --dut cross_trigger_matrix`). DTP-level scenarios live under `hw/sys/dtp/dv/`.
