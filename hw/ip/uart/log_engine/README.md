# Log Engine

DMA-based log path that feeds UART interfaces in the SMC.

## Documentation

Authoritative description and register maps: `hw/ip/uart/log_engine/doc/` (published in the TRM).

## Location

- RTL: `hw/ip/uart/log_engine/rtl/`
- Registers: `hw/ip/uart/log_engine/regs/`

## Verification

Block-level bench on the unified DV flow: `dv/README.md`
(`python3 tools/dv/run_dv.py --dut log_engine`). SMC-level scenarios live under `hw/sys/smc/dv/`.
