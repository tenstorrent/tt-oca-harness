# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Two downstream AXI-Lite manager ports carrying traffic at the same time.

SMC drives three independent downstream AXI-Lite manager ports out of the local
fabric -- ``axil_dtp_csr_req_o``, ``smc_external_req_o`` and
``efuse_bank_ctrl_req_o`` (``tb_top.sv:1429-1437`` lift each one's request-side
valid as its activity probe). They are separate ports on separate branches, so
a request to one is not serialised behind a request to another, and each answer
comes from its own window.

Accesses to two of the windows are issued as one outstanding group, alternating
between them, and the two answers are different in both response code and data:

* the eFuse shim window is a real register, EFUSE_BANK_INIT_TIME, which must
  return its generated reset value with OKAY;
* the mandatory external window is terminated by the reference integration's
  AXI-Lite error slave, which must answer DECERR with zero data (the same
  expectation ``smc_external_window_pad_ctrl_decode_test`` makes of it).

Crossing the two routes therefore fails on the response code and on the data,
not only on a count. The cycles in which two activity probes were high together
are counted as well, so a run in which the group was serialised after all --
and never actually presented the concurrency this sequence is named for --
fails instead of passing.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_efuse_vip_utils import EFUSE_BANK_INIT_TIME_RESET, EFUSE_SHIM_CTRL_WINDOW

# One external-window control block; any of them reaches the same manager
# port, and this one carries no side effects.
EXTERNAL_WINDOW = smc_addr("SMC_TOP_SMC_EXTERNAL_SUPPLEMENTARY_GPIO_POC_PBIAS_CTRL_BASE_ADDR")
AXI_RESP_DECERR = 3
# The reference integration terminates the adopter window with an error slave
# that answers with zero data.
TERMINATOR_RDATA = 0

# Alternating pairs in the outstanding group. Deep enough that the two ports
# overlap even when each answers in a couple of cycles.
CONCURRENCY_PASSES = 16
EXPECTED_ACCESSES = 2 * CONCURRENCY_PASSES
# Only the eFuse half carries a scoreboard value compare: an error response
# returns before the data compare, so the external half is compared here.
MIN_VALUE_CHECKS = CONCURRENCY_PASSES


class _AxilActivityWatch:
    """Counts cycles in which more than one downstream manager port was active."""

    _PROBES = (
        "tb_axil_dtp_csr_active",
        "tb_axil_external_active",
        "tb_axil_efuse_bank_active",
    )

    def __init__(self, dut) -> None:
        self.dut = dut
        self.stop = False
        self.active = dict.fromkeys(self._PROBES, 0)
        self.concurrent = 0

    async def run(self) -> None:
        while not self.stop:
            await RisingEdge(self.dut.clk_smc_i)
            await ReadOnly()
            high = 0
            for probe in self._PROBES:
                value = getattr(self.dut, probe).value
                if value.is_resolvable and int(value):
                    self.active[probe] += 1
                    high += 1
            if high >= 2:
                self.concurrent += 1


class smc_axil_downstream_concurrency_test_seq(SmcCsrSeq):
    """Interleave eFuse-bank and external-window accesses in one group."""

    def __init__(self, name: str = "smc_axil_downstream_concurrency_test_seq") -> None:
        super().__init__(name)
        self.value_checks: int | None = None
        self.concurrent_cycles: int | None = None
        self.active_cycles: dict[str, int] | None = None

    def _read(
        self,
        label: str,
        addr: int,
        *,
        expected: int | None = None,
        expected_resp: int | None = None,
    ) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"rd_{label}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.expected = expected
        if expected_resp is not None and expected_resp > 1:
            item.allow_error = True
            item.expect_error = True
            item.expected_resp = expected_resp
        return item

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        dut = cocotb.top
        # The SEP_IN monitor flags any DECERR it was not told to expect and
        # attributes a beat to the last address it saw accepted, which cannot
        # name the transaction while two reads are outstanding. Both addresses
        # of this group are registered for that reason; the per-access verdict
        # comes from the scoreboard, which holds each item to its own
        # `expected_resp` and would fail an eFuse read answered DECERR.
        self.env.axi_monitor.expected_decerr_addrs.update({EXTERNAL_WINDOW, EFUSE_SHIM_CTRL_WINDOW})

        watch = _AxilActivityWatch(dut)
        watcher = cocotb.start_soon(watch.run())

        efuse_reads = []
        external_reads = []
        members: list[SmcSysAxiItem] = []
        for index in range(CONCURRENCY_PASSES):
            efuse = self._read(
                f"EFUSE_SHIM_CTRL_{index}",
                EFUSE_SHIM_CTRL_WINDOW,
                expected=EFUSE_BANK_INIT_TIME_RESET,
            )
            external = self._read(
                f"EXTERNAL_WINDOW_{index}", EXTERNAL_WINDOW, expected_resp=AXI_RESP_DECERR
            )
            efuse_reads.append(efuse)
            external_reads.append(external)
            members.extend((efuse, external))

        group = SmcSysAxiGroupItem("axil_downstream_group", members)
        await self.start_item(group)
        await self.finish_item(group)
        self.accesses += len(members)

        watch.stop = True
        await RisingEdge(dut.clk_smc_i)
        await watcher
        self.concurrent_cycles = watch.concurrent
        self.active_cycles = dict(watch.active)

        for index, item in enumerate(external_reads):
            assert item.rdata == TERMINATOR_RDATA, (
                f"external-window read {index} answered DECERR carrying data "
                f"0x{item.rdata:08x} instead of the terminator's zero data, so "
                f"another responder answered it"
            )
        for index, item in enumerate(efuse_reads):
            assert item.resp_code == 0, (
                f"eFuse-bank read {index} answered resp={item.resp_code}; the "
                f"window is a real register and must answer OKAY even while the "
                f"external port is busy"
            )

        self.assert_all_reachable(EXPECTED_ACCESSES, "AXI-Lite downstream concurrency")
        self.value_checks = self.env.scoreboard.sys_axi_value_checks_seen

        assert self.concurrent_cycles > 0, (
            "no cycle had two downstream AXI-Lite manager ports active at once, "
            "so the concurrency this sequence is built on never reached the "
            f"fabric (per-probe active cycles {self.active_cycles})"
        )
        cocotb.log.info(
            "CHK-AXIL-DOWNSTREAM-CONCURRENCY: %d outstanding accesses alternating between the "
            "eFuse-shim window 0x%08x (OKAY, 0x%08x) and the external window 0x%08x (DECERR, 0x0) "
            "kept two downstream manager ports active together for %d cycle(s); per-probe active "
            "cycles %s",
            EXPECTED_ACCESSES,
            EFUSE_SHIM_CTRL_WINDOW,
            EFUSE_BANK_INIT_TIME_RESET,
            EXTERNAL_WINDOW,
            self.concurrent_cycles,
            self.active_cycles,
        )
