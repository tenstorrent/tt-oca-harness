# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C Register Reset-Value Sweep

Reads the reset/configured values of real config & status registers and
confirms they are readable with defined (non-X) values after reset.

Excludes:
  - FIFO/data ports (COMMAND/RESPONSE/TX_DATA/RX_DATA/IBI) — reading these
    pops the queue / returns X when empty; they are not reset-valued registers.
  - DAT/DCT memory (0x400+) — external SRAM, X until written.
"""

import cocotb
from i3c_test_base import CTRL_BASE, make_env

# (offset, name) for registers with a defined reset/config value (no FIFO ports)
CONFIG_REGS = [
    (0x000, "HCI_VERSION"),
    (0x004, "HC_CONTROL"),
    (0x008, "HC_CAPABILITIES"),
    (0x098, "QUEUE_THLD_CTRL"),
    (0x09C, "DATA_BUFFER_THLD_CTRL"),
    (0x0A4, "PIO_INTR_STATUS_ENABLE"),
    (0x0A8, "PIO_INTR_SIGNAL_ENABLE"),
    (0x0AC, "PIO_CONTROL"),
    (0x184, "STBY_CR_CONTROL"),
    (0x188, "STBY_CR_DEVICE_ADDR"),
    (0x1C4, "TTI_CONTROL"),
    (0x1D4, "TTI_INTERRUPT_ENABLE"),
]


@cocotb.test(timeout_time=2000, timeout_unit="us")
async def test_reg_reset_value_full(dut):
    """Sweep defined config/status registers; confirm readable, non-X."""
    tb, helper, ctrl, tgt = await make_env(dut)

    for off, name in CONFIG_REGS:
        val = await helper.read(CTRL_BASE + off)
        tb.log.info(f"{name} @ 0x{off:03X} = 0x{val:08X}")
        # helper.read raises on X; reaching here means a resolved (non-X) value.
        assert val is not None, f"{name} @ 0x{off:03X} read failed"

    tb.log.info("Register reset-value sweep complete")
