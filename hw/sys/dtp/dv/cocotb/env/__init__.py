# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP OSS PyUVM environment package.

Wraps unified OCAH BFMs in a UVM hierarchy:
config -> agents (JTAG driver/sequencer + AXI memory) -> scan builder ->
reference models -> scoreboard -> env.
"""

from .dtp_axi_agent import DtpAxiAgent
from .dtp_bypass_ref_model import DtpBypassRefModel
from .dtp_env import DtpEnv
from .dtp_env_cfg import DtpEnvCfg
from .dtp_expected_item import DtpExpectedItem
from .dtp_idcode_ref_model import DtpIdcodeRefModel
from .dtp_ir_decode_ref_model import DtpIrDecodeRefModel
from .dtp_jtag_agent import DtpJtagAgent, DtpJtagDriver
from .dtp_jtag_ir_model import DtpJtagIrModel
from .dtp_jtag_item import DtpJtagItem, DtpJtagOp
from .dtp_jtag_scan_builder import DtpJtagScanBuilder
from .dtp_scoreboard import DtpScoreboard
from .dtp_tap_device import DtpTapDevice
from .dtp_tb_if import DtpTbIf
from .dtp_types import (
    DTP_IR_WIDTH,
    SMC_DBG_AXSIZE_8B,
    SMC_DBG_SINGLE_OP_LEN,
    DtpJtag2AxiOp,
    DtpJtag2AxiStatus,
    DtpJtagInstr,
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
    "DtpJtagScanBuilder",
    "DtpJtagIrModel",
    "DtpExpectedItem",
    "DtpIrDecodeRefModel",
    "DtpIdcodeRefModel",
    "DtpBypassRefModel",
    "DtpJtagItem",
    "DtpJtagOp",
    "DtpTapDevice",
    "DtpTbIf",
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
