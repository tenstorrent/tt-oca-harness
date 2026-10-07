# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM default register read test over the real SEP_IN AXI port.

Access-port identity: the sweep runs on
``env.sys_axi_agent``, whose driver declares ``bus_prefix = "s_axi"`` /
``bus_name = "SEP_IN AXI"`` (``env/smc_sys_axi_agent.py``), and ``tb_top.sv``
wires the top-level ``s_axi_*`` pins into ``smc.sep_axi_in_req_i``. This is NOT
the SYS_IN ingress port -- that one is ``env.sys_in_axi_agent``, which this test
never starts -- so this run gives no SYS_IN decode coverage.
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_default_reg_rd_test_seq import smc_default_reg_rd_test_seq
from smc_base_test import smc_base_test

# Value-compare floor, measured by an INDEPENDENT observer.
# The scoreboard increments `sys_axi_value_checks_seen` once per SEP_IN AXI read
# that carried an expectation AND passed its `got == exp` compare
# (`env/smc_scoreboard.py`), so this floors the number of DUT-sensitive compares
# that actually happened -- which `min_csr_accesses` below does not, because that
# one counts reads. Literal: a floor derived from the catalog or from
# the sequence's own counter shrinks together with the thing it is guarding.
EXPECTED_VALUE_COMPARES = 6


@pyuvm.test()
class smc_default_reg_rd_test(smc_base_test):
    """Run a compact OSS-safe default-register read sweep."""

    required_evidence = (
        "CHK-DEFAULT-REG-SWEEP",
        "CHK-DEFAULT-REG-VALUE",
        "CHK-DEFAULT-REG-VALUE-COMPARE-FLOOR",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_default_reg_rd_test_seq("default_reg_rd_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        value_compares = self.env.scoreboard.sys_axi_value_checks_seen
        assert value_compares >= EXPECTED_VALUE_COMPARES, (
            f"scoreboard booked only {value_compares} SEP_IN AXI value compares, "
            f"expected at least {EXPECTED_VALUE_COMPARES}: the exact-value "
            f"compare is this testcase's entire DUT-sensitive proof, so a run "
            f"that compared fewer values FAILS rather than passing on read "
            f"count alone"
        )
        cocotb.log.info(
            "CHK-DEFAULT-REG-VALUE-COMPARE-FLOOR: scoreboard "
            "sys_axi_value_checks_seen=%d >= %d (independent observer, not the "
            "sequence's own counter and not derived from the CSR catalog)",
            value_compares,
            EXPECTED_VALUE_COMPARES,
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            csr_accesses=seq.reads,
            # Directed stimulus floor on the number of READS (not value
            # compares -- that floor is EXPECTED_VALUE_COMPARES above): the 6
            # READABLE_REGS catalog entries the sweep reads. Literal here, not
            # read from `len(READABLE_REGS)` or `seq.reads`: a floor that shrinks
            # with the table or the counter cannot catch a sweep that silently
            # stops short.
            min_csr_accesses=6,
            proxy=False,
            details=(
                f"Field-aware catalog default RO/RW-read CSR sweep over SEP_IN "
                f"AXI: {seq.reads} reads, all {value_compares} of them "
                f"exact-value compared against the generated register map "
                f"(floor {EXPECTED_VALUE_COMPARES}, measured by the scoreboard)"
            ),
        )
