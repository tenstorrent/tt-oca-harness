# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Production boot ROM observability contract, mirrored from the ROM's headers.

Every constant here has exactly one authority in the free tree, cited at its
definition. These are read-only views of the ROM's own contract: if the ROM
changes an encoding, this file is wrong and the tests that use it must fail.

Sources:
  * POST code layout / phase + error encodings
        hw/sys/smc/bootrom/prod/lib/include/smc_post_code.h
  * scratch register indices used for SIM observability
        hw/sys/smc/bootrom/prod/lib/include/smc_scratchpad.h
  * scratch register addresses
        hw/sys/smc/regs/gen/py/smc_reg.py (generated from the RDL)
  * OCCP status message layout and SMC status codes
        hw/sys/smc/bootrom/prod/lib/include/smc_status.h
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import NamedTuple

# Generated PeakRDL map (hw/sys/smc/regs/gen/py/smc_reg.py), same hookup as
# smc_cpu_vip_utils.
_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    SMC_CPU_CTRL_SCRATCH_1__REG_ADDR,
)


class BitField(NamedTuple):
    """An inclusive [hi:lo] bit field."""

    hi: int
    lo: int

    @property
    def mask(self) -> int:
        return ((1 << (self.hi - self.lo + 1)) - 1) << self.lo

    def get(self, word: int) -> int:
        return (word & self.mask) >> self.lo


# --------------------------------------------------------------------------
# Scratch registers the ROM uses for SIM observability
# (smc_scratchpad.h: SMC_SCRATCH_SIM_PASS_FAIL=0, SIM_POST_CODE=1,
#  SIM_VIRT_CONSOLE=2). Index 0 is `CPU_CTRL_SCRATCH_0` in smc_cpu_vip_utils.
# --------------------------------------------------------------------------
SCRATCH_POST_CODE = SMC_CPU_CTRL_SCRATCH_1__REG_ADDR


# --------------------------------------------------------------------------
# POST code bit fields (smc_post_code.h "POST Code Bitfield Definitions")
# --------------------------------------------------------------------------
POST_CODE_BOOT_PHASE = BitField(31, 28)
POST_CODE_OCCP_STATE = BitField(27, 24)
POST_CODE_INTERFACE = BitField(23, 20)
POST_CODE_ERROR = BitField(19, 16)

# Boot Phase Definitions (bits 31:28)
POST_CODE_BOOT_PHASE_INIT = 0x0
POST_CODE_BOOT_PHASE_STRAP_FUSE = 0x1
POST_CODE_BOOT_PHASE_SRAM_SETUP = 0x2
POST_CODE_BOOT_PHASE_IFACE_CONFIG = 0x3
POST_CODE_BOOT_PHASE_OCCP_READY = 0x4
POST_CODE_BOOT_PHASE_OCCP_PROC = 0x5
POST_CODE_BOOT_PHASE_BOOT_COMPLETE = 0x6
POST_CODE_BOOT_PHASE_ERROR = 0x7

POST_CODE_BOOT_PHASE_NAMES = {
    POST_CODE_BOOT_PHASE_INIT: "INIT",
    POST_CODE_BOOT_PHASE_STRAP_FUSE: "STRAP_FUSE",
    POST_CODE_BOOT_PHASE_SRAM_SETUP: "SRAM_SETUP",
    POST_CODE_BOOT_PHASE_IFACE_CONFIG: "IFACE_CONFIG",
    POST_CODE_BOOT_PHASE_OCCP_READY: "OCCP_READY",
    POST_CODE_BOOT_PHASE_OCCP_PROC: "OCCP_PROC",
    POST_CODE_BOOT_PHASE_BOOT_COMPLETE: "BOOT_COMPLETE",
    POST_CODE_BOOT_PHASE_ERROR: "ERROR",
}

# OCCP State Definitions (bits 27:24)
POST_CODE_OCCP_STATE_IDLE = 0x0
POST_CODE_OCCP_STATE_CMD_RECEIVED = 0x1
POST_CODE_OCCP_STATE_PROCESSING = 0x2
POST_CODE_OCCP_STATE_RESP_READY = 0x3
POST_CODE_OCCP_STATE_COMPLETE = 0x4
POST_CODE_OCCP_STATE_ERROR = 0x5

POST_CODE_OCCP_STATE_NAMES = {
    POST_CODE_OCCP_STATE_IDLE: "IDLE",
    POST_CODE_OCCP_STATE_CMD_RECEIVED: "CMD_RECEIVED",
    POST_CODE_OCCP_STATE_PROCESSING: "PROCESSING",
    POST_CODE_OCCP_STATE_RESP_READY: "RESP_READY",
    POST_CODE_OCCP_STATE_COMPLETE: "COMPLETE",
    POST_CODE_OCCP_STATE_ERROR: "ERROR",
}

# Interface Status Definitions (bits 23:20)
POST_CODE_IFACE_NONE = 0x0
POST_CODE_IFACE_I3C0 = 0x1
POST_CODE_IFACE_I3C1 = 0x2
POST_CODE_IFACE_I3C3 = 0x4
POST_CODE_IFACE_I2C0 = 0x5
POST_CODE_IFACE_I2C1 = 0x6

POST_CODE_IFACE_NAMES = {
    POST_CODE_IFACE_NONE: "NONE",
    POST_CODE_IFACE_I3C0: "I3C0",
    POST_CODE_IFACE_I3C1: "I3C1",
    POST_CODE_IFACE_I3C3: "I3C3",
    POST_CODE_IFACE_I2C0: "I2C0",
    POST_CODE_IFACE_I2C1: "I2C1",
}

# Error Code Definitions (bits 19:16)
POST_CODE_ERROR_NONE = 0x0
POST_CODE_ERROR_SRAM = 0x1
POST_CODE_ERROR_INTERFACE = 0x2
POST_CODE_ERROR_COMMAND = 0x3
POST_CODE_ERROR_ACCESS = 0x4
POST_CODE_ERROR_INVALID_SEC_MODE = 0x5

POST_CODE_ERROR_NAMES = {
    POST_CODE_ERROR_NONE: "NONE",
    POST_CODE_ERROR_SRAM: "SRAM",
    POST_CODE_ERROR_INTERFACE: "INTERFACE",
    POST_CODE_ERROR_COMMAND: "COMMAND",
    POST_CODE_ERROR_ACCESS: "ACCESS",
    POST_CODE_ERROR_INVALID_SEC_MODE: "INVALID_SEC_MODE",
}


def post_code_boot_phase(word: int) -> int:
    return POST_CODE_BOOT_PHASE.get(word)


def post_code_occp_state(word: int) -> int:
    return POST_CODE_OCCP_STATE.get(word)


def post_code_interface(word: int) -> int:
    return POST_CODE_INTERFACE.get(word)


def post_code_error(word: int) -> int:
    return POST_CODE_ERROR.get(word)


def describe_post_code(word: int) -> str:
    """Human-readable POST code, for log lines and assertion messages."""
    return (
        f"{word:#010x} "
        f"phase={POST_CODE_BOOT_PHASE_NAMES.get(post_code_boot_phase(word), '?')} "
        f"occp={POST_CODE_OCCP_STATE_NAMES.get(post_code_occp_state(word), '?')} "
        f"iface={POST_CODE_IFACE_NAMES.get(post_code_interface(word), '?')} "
        f"err={POST_CODE_ERROR_NAMES.get(post_code_error(word), '?')}"
    )
