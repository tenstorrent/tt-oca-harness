# System Timer OCTS (Open Chiplet Time Synchronization)

64-bit multi-chiplet time-synchronization timer.

## Documentation

Authoritative description and register maps: `hw/ip/system_timer_octs/doc/` (published in the TRM).

## Location

- RTL: `hw/ip/system_timer_octs/rtl/`
- Registers: `hw/ip/system_timer_octs/regs/`

## Verification

Block-level bench on the unified DV flow: `dv/README.md`
(`python3 tools/dv/run_dv.py --dut system_timer_octs`). SMC-level scenarios live under `hw/sys/smc/dv/`.
