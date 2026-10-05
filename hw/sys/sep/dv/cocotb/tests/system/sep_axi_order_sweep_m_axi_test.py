# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Every legal AW/W ordering from the SMN inbound master lands at every swept register.

Its own module so the leaf name selects one testcase: the runner sets MODULE,
and a module holding two `@pyuvm.test()` classes runs both under each leaf
name.

m_axi reaches the same register adapters as the CPU-LSU splice, through the
inbound filter, so an adapter that mishandles a channel ordering has to be
caught from both TB-driven masters. The filter denies by default, so the walk
opens allow windows from the CPU-LSU side first.

The sixteen INBOUND_FILTER_CTRL blocks are not swept here and are counted as
skips: those CSRs gate the access in flight, so writing them mid-walk would
measure filter reprogramming rather than adapter ordering. They stay swept on
s_axi, which has no inbound filter.
"""

from __future__ import annotations

import pyuvm

# Import the parent test module, not its class. A class imported here
# registers in this module, and the runner then runs both tests under this
# leaf. seq_lib registers no tests, so its names are imported directly.
from seq_lib.sep_axi_order_sweep_seq import (
    M_AXI_ALLOW_WINDOWS,
    M_AXI_CELL_FLOOR,
    SepAxiOrderSweepCfg,
)
from seq_lib.sep_inbound_filter_rule_seq import (
    SepInboundFilter,
    SepInboundFilterCfg,
)

import tests.system.sep_axi_order_sweep_test as _s_axi


@pyuvm.test()
class sep_axi_order_sweep_m_axi_test(_s_axi.sep_axi_order_sweep_test):
    """The s_axi sweep contracts hold on the SMN inbound master.

    The inbound filter blocks by default (BLOCK_BY_DEFAULT=1 on
    u_inbound_filter, sep_system_peripherals.sv), so the CPU-LSU master
    programs coarse read+write allow windows over the swept span before the
    walk starts. The windows leave the filter rule bank itself outside every
    window, and the rule-bank registers are excluded from this walk, so the
    sweep cannot rewrite the gate it is driving through.
    """

    SWEEP_BUS = "m_axi"
    CELL_FLOOR = M_AXI_CELL_FLOOR

    async def open_sweep_path(self, cfg: SepAxiOrderSweepCfg) -> None:
        """Program the inbound-filter allow windows from the CPU-LSU side."""
        filt = SepInboundFilter(self)
        await filt.disable_all()
        for entry, (name, start, end) in enumerate(M_AXI_ALLOW_WINDOWS):
            rule = SepInboundFilterCfg(entry=entry, allow_addr=start)
            await filt.program_rule(rule, read_allowed=True, write_allowed=True, end_addr=end)
            self.logger.info(
                "inbound filter entry %d allows %s 0x%08x..0x%08x r+w", entry, name, start, end
            )
