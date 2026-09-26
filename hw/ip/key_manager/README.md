# Key Manager

SEP key-derivation and sideload block.

## Documentation

Authoritative description and register maps: `hw/ip/key_manager/doc/` (published in the SEP TRM).

## Location

- RTL: `hw/ip/key_manager/rtl/`
- Registers: `hw/ip/key_manager/regs/`
- Application ROM firmware: `hw/ip/key_manager/approm/prod/` (see its `README.md`)

## Verification

The SEP subsystem testbench (`hw/sys/sep/dv/`) boots the application ROM and
exercises the Key Manager through the SEP mailbox. The block-level
firmware-driven testbench lives in the proprietary `nonfree` companion.
