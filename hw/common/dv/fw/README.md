# Shared DV Firmware Policy

This directory is a skeleton for shared DV firmware collateral only.

Keep this tree thin:

- shared toolchain rule placeholders
- tiny TB mailbox/MMIO helper headers, if they are truly subsystem-neutral
- policy notes for future DV firmware targets

Do not place subsystem firmware sources here. SMC, SEP host, and KM firmware should live beside the hardware that owns them:

- `hw/sys/smc/dv/fw/`
- `hw/sys/sep/dv/fw/host/`
- `hw/ip/km/dv/fw/`

Future DV firmware should use one external RISC-V bare-metal toolchain contract. This skeleton intentionally does not fetch a toolchain, build firmware, vendor picolibc, or generate ROM images.

Root invocation: `make dv-fw TARGET=smc|sep/host|sep/km` (omit `TARGET` for the aggregate placeholder).
