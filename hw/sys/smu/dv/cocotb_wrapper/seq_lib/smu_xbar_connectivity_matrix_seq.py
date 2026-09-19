# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_xbar_connectivity_matrix_test (SMU_103).

The ext_in initiator has no route to the ext_out target: an ext_in access to an
address outside both programmed apertures has no default master port, so the
crossbar answers DECERR itself and nothing reaches the SMN egress boundary.
The apertures are read live from the DUT to pick the address. The expected
response and the expected silence at ext_out are the integrator guide's rule
(`doc/integrator/src/smu.adoc`, "SMU AXI Crossbar Address Map": "Unmatched
inbound (`ext_in`) requests return a decode error and do not reach `ext_out`";
only the SEP and SMC apertures are programmable and the `ext_out` rule is
static). The observations themselves are taken on the DUT, so the check fails
on a crossbar that routed the access or answered OKAY.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from ocah_axi_vip import RESP_DECERR, resp_name

from seq_lib.smu_axi_helpers import (
    axi_read32_resp_ids_bounded,
    axi_write32_resp_ids,
    make_smu_axi_master,
)
from seq_lib.smu_compose_helpers import sample
from seq_lib.smu_tb_pins import smc_primary_reset

ADDR_MASK = (1 << 56) - 1
CANDIDATE_ADDRS = (
    0x00FF_FFFF_FFFF_F000,
    0x0080_0000_0000_0000,
    0x0000_7FFF_FFFF_0000,
    0x0000_0000_F000_0000,
)
SETTLE_CYCLES = 32
PROBE_ARID = 0x2A
PROBE_AWID = 0x15
OUTBOUND_TAPS = (
    "smu_axi_out_write_count_o",
    "smu_axi_out_read_count_o",
    "smu_axi_out_aw_valid_seen_o",
    "smu_axi_out_w_valid_seen_o",
    "smu_axi_out_b_valid_seen_o",
    "smu_axi_out_aw_valid_cycles_o",
)


def _inside(addr: int, base: int, size: int) -> bool:
    return size != 0 and base <= addr < base + size


class smu_xbar_connectivity_matrix_seq:
    """ext_in to ext_out has no route: unmatched ext_in access decode-errors."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.log = test.logger
        self.sb = test.env.scoreboard

    def _outbound_snapshot(self) -> dict[str, int]:
        return {name: sample(getattr(self.dut, name), name) for name in OUTBOUND_TAPS}

    async def run(self) -> None:
        dut = self.dut
        sb = self.sb
        await self.test.cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, SETTLE_CYCLES)
        sb.expect_eq(
            "SEP=1 build with the crossbar elaborated",
            sample(dut.sep_enabled_o, "sep_enabled_o"),
            1,
        )

        sep_base = sample(dut.sep_global_base_o, "sep_global_base_o")
        sep_size = sample(dut.sep_region_size_o, "sep_region_size_o")
        smc_base = sample(dut.smc_global_base_o, "smc_global_base_o")
        smc_size = sample(dut.smc_region_size_o, "smc_region_size_o")
        self.log.info(
            "apertures: sep base=0x%014x size=0x%x smc base=0x%014x size=0x%x",
            sep_base,
            sep_size,
            smc_base,
            smc_size,
        )
        addr = next(
            (
                a
                for a in CANDIDATE_ADDRS
                if not _inside(a, sep_base, sep_size) and not _inside(a, smc_base, smc_size)
            ),
            None,
        )
        if addr is None:
            raise AssertionError(
                "no candidate address lies outside both apertures: "
                f"sep=[0x{sep_base:x},+0x{sep_size:x}) smc=[0x{smc_base:x},+0x{smc_size:x})"
            )
        self.log.info("unmatched ext_in probe address 0x%014x", addr & ADDR_MASK)

        master = await make_smu_axi_master(dut, dut.clk_smu_i, smc_primary_reset(dut))
        before = self._outbound_snapshot()

        rdata, rresp, arid, rid = await axi_read32_resp_ids_bounded(
            master, addr & ADDR_MASK, arid=PROBE_ARID, label="ext_in_unmatched_read"
        )
        self.log.info(
            "ext_in read: rresp=%s rdata=0x%08x arid=0x%x rid=0x%x",
            resp_name(rresp),
            rdata,
            arid,
            rid,
        )
        sb.expect_eq(
            "unmatched ext_in read answered by the crossbar with DECERR",
            rresp,
            RESP_DECERR,
            evidence="CHK-SMU-XBAR-CONN-S7",
        )
        sb.expect_eq("DECERR read carries the issued ARID", rid, PROBE_ARID)

        bresp, awid, bid = await axi_write32_resp_ids(
            master,
            addr & ADDR_MASK,
            0xA5A5_5A5A,
            awid=PROBE_AWID,
            timeout_ns=200_000,
            label="ext_in_unmatched_write",
        )
        self.log.info("ext_in write: bresp=%s awid=0x%x bid=0x%x", resp_name(bresp), awid, bid)
        sb.expect_eq(
            "unmatched ext_in write answered by the crossbar with DECERR",
            bresp,
            RESP_DECERR,
            evidence="CHK-SMU-XBAR-CONN-S7",
        )
        sb.expect_eq("DECERR write carries the issued AWID", bid, PROBE_AWID)

        await ClockCycles(dut.clk_smu_i, SETTLE_CYCLES)
        after = self._outbound_snapshot()
        self.log.info("ext_out boundary before=%s after=%s", before, after)
        sb.expect_eq(
            "no ext_in access reached the ext_out boundary",
            after,
            before,
            evidence="CHK-SMU-XBAR-CONN-S7",
        )
