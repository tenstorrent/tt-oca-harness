# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP PyUVM environment package.

The JTAG, bridge-port (AXI responders and monitors), XTRIG and
downstream-STAP agents, the primary-TAP scan builder, the per-feature
reference models and the plain models behind them, the scoreboard, and the
opt-in shared AXI scoreboard.
"""

from .dtp_axi_agent import DtpAxiAgent
from .dtp_bypass_ref_model import DtpBypassRefModel
from .dtp_env import DtpEnv
from .dtp_env_cfg import DtpEnvCfg
from .dtp_expected_item import DtpExpectedItem
from .dtp_idcode_ref_model import DtpIdcodeRefModel
from .dtp_ijtag_sib_model import DtpIjtagSibModel
from .dtp_ir_decode_ref_model import DtpIrDecodeRefModel
from .dtp_jtag2axi_model import DtpJtag2AxiModel
from .dtp_jtag2axi_req_ref_model import DtpJtag2AxiReqRefModel
from .dtp_jtag2axi_status_item import DtpJtag2AxiStatusItem
from .dtp_jtag2axi_status_ref_model import DtpJtag2AxiStatusRefModel
from .dtp_jtag_agent import DtpJtagAgent, DtpJtagDriver
from .dtp_jtag_ir_model import DtpJtagIrModel
from .dtp_jtag_item import DtpJtagItem, DtpJtagOp
from .dtp_jtag_scan_builder import DtpJtagScanBuilder
from .dtp_scoreboard import DtpScoreboard
from .dtp_stap_3dcr_model import DtpStap3dcrModel
from .dtp_stap_ds_state import DtpStapDsState
from .dtp_tap_device import dtp_tap_device
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
from .dtp_xtrig_csr_model import DtpXtrigCsrModel
from .dtp_xtrig_csr_ref_model import DtpXtrigCsrRefModel
from .dtp_xtrig_ctm_model import DtpXtrigCtmModel
from .dtp_xtrig_ctp_shadow import DtpXtrigCtpShadow
from .dtp_xtrig_decode_ref_model import DtpXtrigDecodeRefModel

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
    "DtpXtrigCsrModel",
    "DtpXtrigCtmModel",
    "DtpXtrigCtpShadow",
    "DtpIjtagSibModel",
    "DtpStap3dcrModel",
    "DtpStapDsState",
    "DtpXtrigCsrRefModel",
    "DtpXtrigDecodeRefModel",
    "DtpJtag2AxiModel",
    "DtpJtag2AxiStatusItem",
    "DtpJtag2AxiReqRefModel",
    "DtpJtag2AxiStatusRefModel",
    "DtpJtagItem",
    "DtpJtagOp",
    "dtp_tap_device",
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
