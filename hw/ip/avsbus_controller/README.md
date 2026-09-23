<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
-->

# AVSBus Controller

AVSBus (Adaptive Voltage Scaling Bus) 1.3.1 controller. Bridges an AXI4-Lite
register interface to the two-wire AVSBus protocol, driving voltage rails on a
single AVS target for dynamic voltage scaling.

## Documentation

Authoritative description and register maps: `hw/ip/avsbus_controller/doc/` (published in the TRM).

## Location

- RTL: `hw/ip/avsbus_controller/rtl/`
- Registers: `hw/ip/avsbus_controller/regs/`

## Verification

No dedicated block TB in this tree; covered by SMC DV.
