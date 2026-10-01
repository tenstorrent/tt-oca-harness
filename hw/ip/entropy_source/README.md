# Entropy Source

Ring-oscillator TRNG used by the SEP.

## Documentation

Authoritative description and register maps: `hw/ip/entropy_source/doc/` (published in the SEP TRM).

## Location

- RTL: `hw/ip/entropy_source/rtl/`
- Registers: `hw/ip/entropy_source/regs/`

## Verification

The IP-level cocotb suite uses the unified native DV runner. See
`dv/README.md`, or run:

```bash
python3 tools/dv/run_dv.py --dut entropy_source
python3 tools/dv/run_dv.py --dut entropy_source --items all
```
