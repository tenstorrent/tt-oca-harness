# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP bench configuration: the parameters ``tb_top`` elaborates the DUT with.

The Python copy of ``tb/dtp_dv_cfg_pkg.sv``. The cross-trigger port counts
come from the generated network address map (``cross_trigger_network_reg``:
one CTP window per external port, one CTM source register per port), which
the cross-trigger network document's parameter table states as ``NUM_CTP`` 16
and ``NUM_INT_CT`` 10; the clock-stop request count is that table's
``NUM_CLK_STOP_REQ``. The STAP count, the IC_RESET slice widths, the
instruction enables, the IDCODE fields, and the version are the bench's
choice, published by the DUT through JTAG_CAPS ("JTAG Capabilities" table,
PTAP document) and IDCODE. ``DtpTbIf.check_dv_cfg`` compares every value in
``DV_CFG_PARITY`` with the copy ``dtp_tb_if`` publishes from the
SystemVerilog package, so the two tables cannot drift apart.
"""

from __future__ import annotations

import re

import cross_trigger_network_reg as _ctn_reg

__all__ = [
    "DTP_BSR_ENABLE",
    "DTP_CLAMP_ENABLE",
    "DTP_CT_DST_LATENCY",
    "DTP_DEFAULT_IDCODE",
    "DTP_EXTEST_PULSE_ENABLE",
    "DTP_EXTEST_TRAIN_ENABLE",
    "DTP_HIGHZ_ENABLE",
    "DTP_IC_RESET_INSTR_ENABLE",
    "DTP_IDCODE_MFR_ID",
    "DTP_IDCODE_PART_NUM",
    "DTP_IDCODE_SI_REV",
    "DTP_INTEST_ENABLE",
    "DTP_INT_CT_MODE",
    "DTP_NUM_CLK_STOP_REQ",
    "DTP_NUM_CTM_PORTS",
    "DTP_NUM_EXTRA_STAPS",
    "DTP_NUM_EXT_IC_RESET",
    "DTP_NUM_SEP_IC_RESET",
    "DTP_NUM_SMC_IC_RESET",
    "DTP_NUM_XTRIG_CTP",
    "DTP_NUM_XTRIG_INT_CT",
    "DTP_OCH_VER",
    "DTP_RUNBIST_ENABLE",
    "DTP_SEP_DBG_ENABLE",
    "DTP_SMC_DBG_ENABLE",
    "DTP_STAP_IO_ENABLE",
    "DTP_TMP_ENABLE",
    "DTP_WIRE_OR_ASSERT",
    "DTP_WIRE_OR_PULL",
    "DV_CFG_PARITY",
]

_CTP_WINDOW_RE = re.compile(r"^CTP_(\d+)__REG_MAP_BASE_ADDR$")
_CTM_SOURCE_RE = re.compile(r"^CTM_CT_SRC_(\d+)__REG_FILE_BASE_ADDR$")


def _count_indexed(pattern: re.Pattern[str]) -> int:
    """Number of consecutive zero-based instances the address map names."""
    indices = {int(m.group(1)) for name in dir(_ctn_reg) if (m := pattern.match(name))}
    if indices != set(range(len(indices))):
        raise ImportError(f"{pattern.pattern}: non-contiguous instance indices {sorted(indices)}")
    return len(indices)


# Cross-trigger geometry (generated network address map).
DTP_NUM_XTRIG_CTP = _count_indexed(_CTP_WINDOW_RE)
DTP_NUM_CTM_PORTS = _count_indexed(_CTM_SOURCE_RE)
DTP_NUM_XTRIG_INT_CT = DTP_NUM_CTM_PORTS - DTP_NUM_XTRIG_CTP
DTP_NUM_CLK_STOP_REQ = 9
# Bit per internal port: 0 = pulse mode, where the acknowledge is unused.
DTP_INT_CT_MODE = 0

# Wire-OR shared-wire polarity per CONFIG.INVERT (cross_trigger_port.rdl):
# INVERT=0 is an active-low wire with a pull-up, INVERT=1 an active-high wire
# with a pull-down. A port receives a trigger when its synchronized wire moves
# from the pull level to the asserted level.
DTP_WIRE_OR_PULL = {0: 1, 1: 0}
DTP_WIRE_OR_ASSERT = {0: 0, 1: 1}
# Clock edges from the edge at which a wire-OR receive input moves to the edge
# at which the port's ct_dst is high: the two synchronizer stages and the
# registered ct_dst output.
DTP_CT_DST_LATENCY = 3

# JTAG interface unit and PTAP configuration.
DTP_NUM_EXTRA_STAPS = 1
DTP_BSR_ENABLE = 1
DTP_EXTEST_TRAIN_ENABLE = 1
DTP_EXTEST_PULSE_ENABLE = 1
DTP_INTEST_ENABLE = 1
DTP_CLAMP_ENABLE = 1
DTP_HIGHZ_ENABLE = 1
DTP_RUNBIST_ENABLE = 1
DTP_TMP_ENABLE = 1
DTP_SMC_DBG_ENABLE = 1
DTP_SEP_DBG_ENABLE = 1
DTP_STAP_IO_ENABLE = 1
# One IC_RESET override port per slice; the IC_RESET instruction is enabled
# with at least one slice.
DTP_NUM_SMC_IC_RESET = 1
DTP_NUM_SEP_IC_RESET = 1
DTP_NUM_EXT_IC_RESET = 1
DTP_IC_RESET_INSTR_ENABLE = int(
    (DTP_NUM_SMC_IC_RESET + DTP_NUM_SEP_IC_RESET + DTP_NUM_EXT_IC_RESET) > 0
)

DTP_IDCODE_MFR_ID = 0x000
DTP_IDCODE_PART_NUM = 0x0000
DTP_IDCODE_SI_REV = 0x0
DTP_OCH_VER = 0
# IEEE 1149.1 device identification: version, part number, manufacturer, and
# the fixed marker bit.
DTP_DEFAULT_IDCODE = (
    (DTP_IDCODE_SI_REV << 28) | (DTP_IDCODE_PART_NUM << 12) | (DTP_IDCODE_MFR_ID << 1) | 1
)

# dtp_tb_if member -> the value the SystemVerilog package must publish there.
DV_CFG_PARITY: dict[str, int] = {
    "cfg_num_ctp": DTP_NUM_XTRIG_CTP,
    "cfg_num_int_ct": DTP_NUM_XTRIG_INT_CT,
    "cfg_num_clk_stop_req": DTP_NUM_CLK_STOP_REQ,
    "cfg_int_ct_mode": DTP_INT_CT_MODE,
    "cfg_num_extra_staps": DTP_NUM_EXTRA_STAPS,
    "cfg_num_smc_ic_reset": DTP_NUM_SMC_IC_RESET,
    "cfg_num_sep_ic_reset": DTP_NUM_SEP_IC_RESET,
    "cfg_num_ext_ic_reset": DTP_NUM_EXT_IC_RESET,
    "cfg_och_ver": DTP_OCH_VER,
    "cfg_idcode": DTP_DEFAULT_IDCODE,
    "cfg_wire_or_pull": (DTP_WIRE_OR_PULL[1] << 1) | DTP_WIRE_OR_PULL[0],
    "cfg_wire_or_assert": (DTP_WIRE_OR_ASSERT[1] << 1) | DTP_WIRE_OR_ASSERT[0],
    "cfg_ct_dst_latency": DTP_CT_DST_LATENCY,
}
