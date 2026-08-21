# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP OSS PyUVM environment package.

Wraps unified OCAH BFMs in a UVM hierarchy:
config -> agents (JTAG driver/sequencer + AXI memory) -> scoreboard -> env.
"""

# Apply the cocotb teardown-noise shim as soon as the env package is imported.
from . import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()

from .dtp_env import DtpEnv
from .dtp_env_cfg import DtpEnvCfg
from .dtp_jtag_agent import DtpJtagAgent, DtpJtagDriver
from .dtp_axi_agent import DtpAxiAgent
from .dtp_scoreboard import DtpScoreboard
from .dtp_jtag_item import DtpJtagItem, DtpJtagOp
from .dtp_tap_device import DtpTapDevice
from .dtp_types import (
    DTP_IR_WIDTH,
    DtpJtag2AxiOp,
    DtpJtag2AxiStatus,
    DtpJtagInstr,
    SMC_DBG_AXSIZE_8B,
    SMC_DBG_SINGLE_OP_LEN,
    decode_idcode,
    pack_single_op,
    unpack_single_op,
)

__all__ = [
    "DtpEnv",
    "DtpEnvCfg",
    "DtpJtagAgent",
    "DtpJtagDriver",
    "DtpAxiAgent",
    "DtpScoreboard",
    "DtpJtagItem",
    "DtpJtagOp",
    "DtpTapDevice",
    "DTP_IR_WIDTH",
    "DtpJtagInstr",
    "DtpJtag2AxiOp",
    "DtpJtag2AxiStatus",
    "SMC_DBG_AXSIZE_8B",
    "SMC_DBG_SINGLE_OP_LEN",
    "decode_idcode",
    "pack_single_op",
    "unpack_single_op",
]
