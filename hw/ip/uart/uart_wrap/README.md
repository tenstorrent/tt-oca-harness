# UART Wrapper

Multi-instance wrapper of the UART and Log Engine wrapper with a shared log-fetch port, used by the SMC.

## Documentation

Authoritative description and register maps: the embedded IPs' `doc/` directories under `hw/ip/uart/` (published in the TRM).

## Location

- RTL: `hw/ip/uart/uart_wrap/rtl/`
- Registers: `hw/ip/uart/uart_wrap/regs/`

## Verification

Block-level bench on the unified DV flow: `dv/README.md`
(`python3 tools/dv/run_dv.py --dut uart_wrap`). SMC-level scenarios live under `hw/sys/smc/dv/`.
