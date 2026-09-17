# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Real LCC / feat_ctrl ungating for SMU (no Force, no placeholder).

Under ``smu #(.SEP(0))`` there is no LCC in the DUT: ``gen_no_sep`` ties
``sep_dbg_disable`` to ``'0``, so nothing is disabled and JTAG2AXI is open.
With SEP=1 the gate follows the LCC's ``dbg_disable_o``, which the eFuse sense
derives (soc_debug/ap_debug, and fuse_test for OTP), the same path as SEP DV.
"""

from __future__ import annotations

from typing import Optional

_FEAT_CTRL_PATHS = (
    "u_dut.sep_feat_ctrl",
    "u_dut.u_smu.sep_feat_ctrl",
)

# sep_efuse_map_lc_disable_reg_t packed bit positions (LSB = sep_debug).
_BIT_SEP_DEBUG = 0
_BIT_SOC_DEBUG = 1
_BIT_AP_DEBUG = 2
_BIT_FUSE_TEST = 32


def _resolve(dut, path: str):
    node = dut
    for part in path.split("."):
        if not hasattr(node, part):
            return None
        node = getattr(node, part)
    return node


def read_feat_ctrl_word(dut) -> Optional[int]:
    """Return packed feat_ctrl if visible; None if SEP=0 / missing."""
    for path in _FEAT_CTRL_PATHS:
        handle = _resolve(dut, path)
        if handle is None:
            continue
        try:
            return int(handle.value)
        except Exception:  # noqa: BLE001
            continue
    return None


def jtag2axi_ungated_from_lcc(dut) -> bool:
    """True when LCC-driven feat_ctrl opens fabric JTAG2AXI (soc & ap debug)."""
    word = read_feat_ctrl_word(dut)
    if word is None:
        return False
    soc = (word >> _BIT_SOC_DEBUG) & 1
    ap = (word >> _BIT_AP_DEBUG) & 1
    return bool(soc and ap)


def otp_jtag2axi_ungated_from_lcc(dut) -> bool:
    """True when LCC opens OTP JTAG2AXI (fuse_test & soc & ap)."""
    word = read_feat_ctrl_word(dut)
    if word is None:
        return False
    fuse = (word >> _BIT_FUSE_TEST) & 1
    soc = (word >> _BIT_SOC_DEBUG) & 1
    ap = (word >> _BIT_AP_DEBUG) & 1
    return bool(fuse and soc and ap)


def require_jtag2axi_via_lcc(dut, logger=None) -> None:
    """Assert fabric JTAG2AXI is ungated by real LCC feat_ctrl (no Force)."""
    if jtag2axi_ungated_from_lcc(dut):
        if logger is not None:
            logger.info(
                "JTAG2AXI ungated via LCC feat_ctrl=0x%x",
                read_feat_ctrl_word(dut) or 0,
            )
        return
    word = read_feat_ctrl_word(dut)
    raise AssertionError(
        "JTAG2AXI still gated: need real LCC feat_ctrl with soc_debug & "
        f"ap_debug (observed feat_ctrl={word!r}). SEP=0 ties sep_feat_ctrl='0'; "
        "run under SEP=1 with an eFuse image that leaves debug open (TEST_DEV) "
        "or demotes into it."
    )


def require_otp_jtag2axi_via_lcc(dut, logger=None) -> None:
    """Assert OTP JTAG2AXI is ungated by real LCC feat_ctrl (no Force)."""
    if otp_jtag2axi_ungated_from_lcc(dut):
        if logger is not None:
            logger.info(
                "OTP JTAG2AXI ungated via LCC feat_ctrl=0x%x",
                read_feat_ctrl_word(dut) or 0,
            )
        return
    word = read_feat_ctrl_word(dut)
    raise AssertionError(
        "OTP JTAG2AXI still gated: need real LCC feat_ctrl with fuse_test & "
        f"soc_debug & ap_debug (observed feat_ctrl={word!r}). Force disabled."
    )
