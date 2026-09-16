# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
 I3C Register Reset-Value Sweep

Reads real config & status registers after reset and compares each against the
reset value published by the generated register map.

Both halves of every row — the offset AND the expected value — are resolved by
symbol from oca_i3c_wrap_reg, never hand-copied. A stale symbol raises AttributeError
at import, and a regenerated map moves offsets and reset values together.

Deliberately avoids:
  - FIFO/data ports (COMMAND/RESPONSE/TX_DATA/RX_DATA/IBI) — reading these
    pops the queue / returns X when empty; they are not reset-valued registers.
  - DAT/DCT memory (0x400+) — external SRAM, X until written.

make_env() only brings up the AXI master and waits for reset release; it runs
no controller/target configuration, so every value read here is a true
post-reset value.
"""

import os
import sys

import cocotb
from env.i3c_test_base import CTRL_BASE, make_env

# Authoritative register map (generated). Same path convention as i3c_error_sanity.py.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../regs/gen/py"))
import oca_i3c_wrap_reg as csr  # noqa: E402

# The generated map spells reset values with a parameterisation-encoding prefix.
# Naming them once keeps the rows below readable without losing the symbol trail.
_BASE = (
    "BASEREGS_PIO_OFFSET_80_EXT_OFFSET_100_DAT_TABLE_SIZE_7F_DAT_OFFSET_400"
    "_DCT_TABLE_SIZE_7F_DCT_OFFSET_800_MIPI_COMMANDS_35_"
)
_PIO = (
    "PIOREGS_CMD_FIFO_SIZE_40_RESP_FIFO_SIZE_40_IBI_FIFO_SIZE_40_TX_FIFO_SIZE_5"
    "_RX_FIFO_SIZE_5_EXT_IBI_SIZE_0_"
)
_STBY = (
    "STANDBYCONTROLLERMODEREGISTERS_PID_HI_RESET_7FFF_PID_LO_RESET_5A00A5"
    "_VIRTUAL_PID_HI_RESET_7FFF_VIRTUAL_PID_LO_RESET_5A10A5_RX_FIFO_SIZE_5"
    "_TX_FIFO_SIZE_5_IBI_FIFO_SIZE_5_"
)
_TTI = (
    "TARGETTRANSACTIONINTERFACEREGISTERS_RX_DESC_FIFO_SIZE_5_TX_DESC_FIFO_SIZE_5"
    "_RX_FIFO_SIZE_5_TX_FIFO_SIZE_5_IBI_FIFO_SIZE_5_"
)

# (log name, address symbol, reset-value symbol)
_REGS = [
    ("HCI_VERSION", "I3CBASE_HCI_VERSION_REG_ADDR", _BASE + "HCI_VERSION_REG_DEFAULT"),
    ("HC_CONTROL", "I3CBASE_HC_CONTROL_REG_ADDR", _BASE + "HC_CONTROL_REG_DEFAULT"),
    ("HC_CAPABILITIES", "I3CBASE_HC_CAPABILITIES_REG_ADDR", _BASE + "HC_CAPABILITIES_REG_DEFAULT"),
    (
        "QUEUE_THLD_CTRL",
        "PIOCONTROL_QUEUE_THLD_CTRL_REG_ADDR",
        _PIO + "QUEUE_THLD_CTRL_REG_DEFAULT",
    ),
    (
        "DATA_BUFFER_THLD_CTRL",
        "PIOCONTROL_DATA_BUFFER_THLD_CTRL_REG_ADDR",
        _PIO + "DATA_BUFFER_THLD_CTRL_REG_DEFAULT",
    ),
    (
        "PIO_INTR_STATUS_ENABLE",
        "PIOCONTROL_PIO_INTR_STATUS_ENABLE_REG_ADDR",
        _PIO + "PIO_INTR_STATUS_ENABLE_REG_DEFAULT",
    ),
    (
        "PIO_INTR_SIGNAL_ENABLE",
        "PIOCONTROL_PIO_INTR_SIGNAL_ENABLE_REG_ADDR",
        _PIO + "PIO_INTR_SIGNAL_ENABLE_REG_DEFAULT",
    ),
    ("PIO_CONTROL", "PIOCONTROL_PIO_CONTROL_REG_ADDR", _PIO + "PIO_CONTROL_REG_DEFAULT"),
    (
        "STBY_CR_CONTROL",
        "I3C_EC_STDBYCTRLMODE_STBY_CR_CONTROL_REG_ADDR",
        _STBY + "STBY_CR_CONTROL_REG_DEFAULT",
    ),
    (
        "STBY_CR_DEVICE_ADDR",
        "I3C_EC_STDBYCTRLMODE_STBY_CR_DEVICE_ADDR_REG_ADDR",
        _STBY + "STBY_CR_DEVICE_ADDR_REG_DEFAULT",
    ),
    ("TTI_CONTROL", "I3C_EC_TTI_CONTROL_REG_ADDR", _TTI + "CONTROL_REG_DEFAULT"),
    (
        "TTI_INTERRUPT_ENABLE",
        "I3C_EC_TTI_INTERRUPT_ENABLE_REG_ADDR",
        _TTI + "INTERRUPT_ENABLE_REG_DEFAULT",
    ),
]


def _resolve(rows):
    """(name, offset, reset value) per row; AttributeError names the stale symbol."""
    out = []
    for name, addr_sym, dflt_sym in rows:
        instance_addr_sym = f"I3C_CSR_0__{addr_sym}"
        for sym in (instance_addr_sym, dflt_sym):
            if not hasattr(csr, sym):
                raise AttributeError(
                    f"{name}: oca_i3c_wrap_reg has no symbol {sym!r} — the generated register "
                    f"map was regenerated and this table is stale"
                )
        out.append((name, getattr(csr, instance_addr_sym), getattr(csr, dflt_sym)))
    return out


CONFIG_REGS = _resolve(_REGS)


@cocotb.test(timeout_time=2000, timeout_unit="us")
async def test_reg_reset_value_full(dut):
    """Sweep config/status registers; each must read its generated reset value."""
    tb, helper, ctrl, tgt = await make_env(dut)

    mismatches = []
    for name, off, expected in CONFIG_REGS:
        # helper.read raises on X, so reaching the compare means a resolved value.
        val = await helper.read(CTRL_BASE + off)
        if val == expected:
            tb.log.info(f"{name} @ 0x{off:03X} = 0x{val:08X} (matches reset value)")
        else:
            tb.log.error(
                f"{name} @ 0x{off:03X} = 0x{val:08X}, expected reset value 0x{expected:08X}"
            )
            mismatches.append((name, off, val, expected))

    # Sweep the whole table before failing, so one run reports every mismatch.
    assert not mismatches, "reset-value mismatches: " + "; ".join(
        f"{n} @ 0x{o:03X} read 0x{v:08X} != 0x{e:08X}" for n, o, v, e in mismatches
    )

    tb.log.info(f"Register reset-value sweep complete: {len(CONFIG_REGS)} registers verified")
