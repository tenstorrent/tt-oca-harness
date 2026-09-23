# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Per-filter field sweep.

Each filter entry exposes three CSR fields: FILTER_CONFIG, START_ADDR,
END_ADDR. This test reads every field of entries 0-3 in both directions
(inbound + outbound), addressing and expecting via the generated PeakRDL map.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb

from .smc_csr_seq_utils import SmcCsrSeq

# Generated PeakRDL map (hw/sys/smc/regs/gen/py/smc_reg.py).
_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

import smc_reg as _smc_reg  # noqa: E402
from smc_reg import (  # noqa: E402
    FILTER_CTRL_END_ADDR_REG_DEFAULT,
    FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
    FILTER_CTRL_START_ADDR_REG_DEFAULT,
)

# RDL-traceable reset constants (filter_ctrl.rdl -> FILTER_CONFIG = 0x3000,
# START_ADDR = 0, END_ADDR = 0x7). Each read verifies field decode AND the
# full 64-bit spec reset content (AxSIZE=3 / length=8).
_FIELDS = (
    ("FILTER_CONFIG", FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT),
    ("START_ADDR", FILTER_CTRL_START_ADDR_REG_DEFAULT),
    ("END_ADDR", FILTER_CTRL_END_ADDR_REG_DEFAULT),
)

_ENTRY_COUNT = 4
_DIRS = ("INBOUND", "OUTBOUND")


def _filter_reg_addr(direction: str, entry: int, field: str) -> int:
    return getattr(_smc_reg, f"SMC_{direction}_FILTER_CTRL_{entry}__{field}_REG_ADDR")


class smc_filter_field_sweep_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        sb = self.env.scoreboard
        value_checks_before = sb.sys_axi_value_checks_seen
        for direction in _DIRS:
            for i in range(_ENTRY_COUNT):
                for field, exp in _FIELDS:
                    addr = _filter_reg_addr(direction, i, field)
                    await self.csr_read(
                        f"{direction}_FILTER_{i}_{field}",
                        addr,
                        expected=exp,
                        length=8,
                    )
        expected = len(_DIRS) * _ENTRY_COUNT * len(_FIELDS)
        self.assert_all_reachable(expected, "FILTER_FIELD_SWEEP")
        value_checks = sb.sys_axi_value_checks_seen - value_checks_before
        assert value_checks == expected, (
            f"FILTER_FIELD_SWEEP: the scoreboard booked {value_checks} exact-value "
            f"compares for {expected} reads that each carry an expected word"
        )
        cocotb.log.info(
            "CHK-FILTER-FIELD-RESET-SWEEP: %d filter CSR reads (%d fields x %d entries x "
            "%d directions, 64-bit) each matched its RDL reset word in a scoreboard "
            "value compare (%s); %d value compares booked",
            expected,
            len(_FIELDS),
            _ENTRY_COUNT,
            len(_DIRS),
            ", ".join(f"{field}=0x{exp:x}" for field, exp in _FIELDS),
            value_checks,
        )
