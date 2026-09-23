# UART 16550

Industry-standard UART used by the SMC for console and logging.

## Documentation

Authoritative description and register maps: `hw/ip/uart/uart_16550/doc/` (published in the TRM).

## Location

- RTL: `hw/ip/uart/uart_16550/rtl/`
- Registers: `hw/ip/uart/uart_16550/regs/`

## Verification

Block-level bench on the unified DV flow: `dv/README.md`
(`python3 tools/dv/run_dv.py --dut uart_16550`). SMC-level scenarios live under `hw/sys/smc/dv/`.
