# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Past-extent and last-aperture-word response of the DECERR write units over SEP_IN.

Contract XBAR_017, anchor smc_past_extent_decerr_units_test.
Allocated scenarios: XBAR-DEC-WDT.S3/S4, XBAR-DEC-MAILBOX.S3/S4, XBAR-DEC-DMA-ZEROER.S3/S4,
XBAR-DEC-DFX.S3, XBAR-DEC-CPU-CTRL.S3.
Spec sources: smc.rdl ocah_past_extent_resp placements, memmap.adoc Address Space Organization.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import (
    LOCAL_BASE_RESET,
    generated_decoded_extent,
    generated_past_extent_resp,
    generated_window,
    smc_addr,
    smc_indexed_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq

AXI_RESP_DECERR = 3
PAST_EXTENT_RDATA = 0xBADCAB1E
WRITE_PATTERN = 0xA5A55A5A
FUSE_WAIT_BOUND_SMC_CYCLES = 200_000
AXI_TIMEOUT_NS = 50_000
_RESP_NAMES = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}

WDT0_CMP = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_CMP_BASE_ADDR")
MAILBOX_ERROR_FLAGS = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_ERROR_FLAGS_BASE_ADDR")
DMA_DST_ADDRESS_LO = smc_addr("SMC_TOP_DMA_CTRL_DST_ADDRESS_LO_BASE_ADDR")
ZEROER_DEST_ADDR = smc_addr("SMC_TOP_ZEROER_CTRL_DEST_ADDR_BASE_ADDR")
DFX_STATUS = smc_addr("SMC_TOP_DFX_CTRL_STATUS_SMU_BASE_ADDR")
CPU_SCRATCH_0 = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", 0)

_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6")
_CHECKERS = (
    "CHK-PAST-EXTENT-WDT",
    "CHK-PAST-EXTENT-MAILBOX",
    "CHK-PAST-EXTENT-DMA-ZEROER",
    "CHK-PAST-EXTENT-DFX",
    "CHK-PAST-EXTENT-CPU-CTRL",
)


class smc_past_extent_decerr_units_test_seq(SmcCsrSeq):
    """Probe the past-extent and last-word addresses of each DECERR unit on SEP_IN."""

    def __init__(self, name: str = "smc_past_extent_decerr_units_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self.fuse_state = "not waited"

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    async def _read_past(self, label: str, addr: int) -> int:
        item = SmcSysAxiItem(f"rd_{label}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.allow_error = True
        item.expect_error = True
        item.expected_resp = AXI_RESP_DECERR
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code == AXI_RESP_DECERR, (
            f"{label} @ 0x{addr:08x}: rresp {item.resp_code}, want DECERR (rdata 0x{item.rdata:x})"
        )
        got = item.rdata & 0xFFFF_FFFF
        assert got == PAST_EXTENT_RDATA, (
            f"{label} @ 0x{addr:08x}: rdata 0x{got:08x}, want 0x{PAST_EXTENT_RDATA:08x}"
        )
        return got

    async def _write_past(self, label: str, addr: int) -> int:
        item = SmcSysAxiItem(f"wr_{label}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = 4
        item.wdata = WRITE_PATTERN
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None, f"{label} @ 0x{addr:08x}: no bresp recorded"
        return item.resp_code

    async def _probe_unit(
        self, unit: str, tag: str, live: list[tuple[str, int]]
    ) -> tuple[str, list[str]]:
        """Probe the past-extent and last-aperture words of ``unit``.

        Every access is registered as an expected DECERR address first. ``live`` is
        the (label, address) list of registers read before and after each write.
        """
        first, last = generated_window(unit)
        window_first = LOCAL_BASE_RESET + first
        window_last = LOCAL_BASE_RESET + last
        extent = generated_decoded_extent(unit)
        assert extent % 4 == 0, f"{unit}: decoded extent 0x{extent:x} not on a 4-byte boundary"
        rresp_name, bresp_name = generated_past_extent_resp(unit)
        assert rresp_name == "DECERR", f"{unit}: RDL past-extent rresp {rresp_name}"
        past = window_first + extent
        top = window_last & ~0x3
        assert window_first < past < top, f"{unit}: past 0x{past:x} top 0x{top:x} not ordered"
        self.env.axi_monitor.expected_decerr_addrs.update((past, top))
        before = {}
        for lbl, addr in live:
            before[lbl] = await self.csr_read(f"{tag}_{lbl}_PRE", addr)
        bresps = []
        for where, addr in (("PAST", past), ("TOP", top)):
            rdata = await self._read_past(f"{tag}_{where}", addr)
            bresp = await self._write_past(f"{tag}_{where}", addr)
            for lbl, laddr in live:
                after = await self.csr_read(f"{tag}_{lbl}_POST_{where}", laddr)
                assert after == before[lbl], (
                    f"{unit} {lbl}: 0x{after:x} after write to 0x{addr:08x}, was 0x{before[lbl]:x}"
                )
            declared = 3 if bresp_name == "DECERR" else 2
            bresps.append(
                f"{where}@0x{addr:08x} rresp=DECERR rdata=0x{rdata:08X} "
                f"bresp={_RESP_NAMES.get(bresp, bresp)}(declared {bresp_name}, "
                f"match={int(bresp == declared)})"
            )
        lives = ",".join(f"{lbl}=0x{before[lbl]:X}" for lbl, _ in live)
        head = (
            f"{unit} aperture 0x{window_first:08X}..0x{window_last:08X} extent 0x{extent:X} "
            f"first-past 0x{past:08X} last-word 0x{top:08X}; live {lives} unchanged"
        )
        return head, bresps

    async def body(self) -> None:
        await self.wait_fuse_sense_done(FUSE_WAIT_BOUND_SMC_CYCLES)
        dut = cocotb.top
        states = []
        for name in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"):
            sig = getattr(dut, name)
            assert sig.value.is_resolvable, f"{name} is X/Z after the wait"
            states.append(f"{name}={int(sig.value)}")
        self.fuse_state = ",".join(states)
        self._mark_step("S1")

        head, resps = await self._probe_unit("smc_cluster_core0_wdt", "WDT", [("CMP", WDT0_CMP)])
        self._mark_step("S2")
        self._log_chk("CHK-PAST-EXTENT-WDT", f"{head}; {'; '.join(resps)}")

        head, resps = await self._probe_unit(
            "smc_mailbox", "MBOX", [("OUT0_ERROR_FLAGS", MAILBOX_ERROR_FLAGS)]
        )
        self._mark_step("S3")
        self._log_chk("CHK-PAST-EXTENT-MAILBOX", f"{head}; {'; '.join(resps)}")

        live = [("DMA_DST_ADDRESS_LO", DMA_DST_ADDRESS_LO), ("ZEROER_DEST_ADDR", ZEROER_DEST_ADDR)]
        dma_head, dma_resps = await self._probe_unit("dma_ctrl", "DMA", live)
        zer_head, zer_resps = await self._probe_unit("zeroer_ctrl", "ZEROER", live)
        self._mark_step("S4")
        self._log_chk(
            "CHK-PAST-EXTENT-DMA-ZEROER",
            f"{dma_head}; {'; '.join(dma_resps)} || {zer_head}; {'; '.join(zer_resps)}",
        )

        head, resps = await self._probe_unit("dfx_ctrl", "DFX", [("STATUS", DFX_STATUS)])
        self._mark_step("S5")
        self._log_chk("CHK-PAST-EXTENT-DFX", f"{head}; {'; '.join(resps)}")

        head, resps = await self._probe_unit("smc_cpu_ctrl", "CPU", [("SCRATCH_0", CPU_SCRATCH_0)])
        self._mark_step("S6")
        self._log_chk("CHK-PAST-EXTENT-CPU-CTRL", f"{head}; {'; '.join(resps)}")

    def log_timeout_paths(self) -> None:
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: wait_fuse_sense_done sub-waits tb_fuse_sense_done, "
            "tb_fuse_reset_n, tb_rst_warm_smc_clk_n each bounded %d clk_smc_i rises, last "
            "observed %s; %d AXI accesses each bounded by the driver timeout %d ns "
            "(allow_timeout False), all answered; no other wait",
            FUSE_WAIT_BOUND_SMC_CYCLES,
            self.fuse_state,
            self.accesses,
            AXI_TIMEOUT_NS,
        )

    def nonvac_fence(self, floor: int) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"step stamps not increasing: {times}"
        chk_ids = tuple(c for c, _ in self._chk_marks)
        assert chk_ids == _CHECKERS, f"checker lines {chk_ids}, want {_CHECKERS}"
        stamp_of = dict(self._stamps)
        for (chk_id, when), step in zip(self._chk_marks, _STEPS[1:]):
            assert when >= stamp_of[step], f"{chk_id} printed before its step {step} stamp"
        assert self.accesses >= floor, f"{self.accesses} accesses, floor {floor}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence SETUP<WDT<MAILBOX<DMA_ZEROER<DFX<CPU_CTRL; "
            "checker lines %s; accesses %d >= floor %d; stamps %s",
            ",".join(chk_ids),
            self.accesses,
            floor,
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
