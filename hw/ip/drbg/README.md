# DRBG

Deterministic random-bit generator used with the SEP entropy path.

## Documentation

Authoritative description: `hw/ip/drbg/doc/` (published in the SEP TRM).

## Location

- RTL: `hw/ip/drbg/rtl/`

## Verification

The DRBG is verified in the SEP testbench: the `sep_drbg_*` tests under
`hw/sys/sep/dv/cocotb/tests/`.
