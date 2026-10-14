# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Adopter window routing: eFuse SHIM range and external regions over SEP_IN.

Spec sources: memmap.adoc AXI-Lite External Window, smc_external.rdl, smc.rdl smc_external.

Every access is watched on tb_axil_efuse_bank_active and the tb_axil_external_{ar,aw}{valid,addr}
probes from the cycle before it starts until a fixed drain after it completes. The EFUSE_SHIM_SIZE
value is not pinned by the specification (owner value pending); the sequence measures the first
word at which tb_axil_efuse_bank_active stops rising and logs it, never comparing it with a
stated value.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_efuse_vip_utils import EFUSE_BANK_INIT_TIME_RESET

EXT_BASE = smc_addr("SMC_TOP_SMC_EXTERNAL_BASE_ADDR")
SUPP_BASE = smc_addr("SMC_TOP_SMC_EXTERNAL_SUPPLEMENTARY_BASE_ADDR")
STRAPS_LO = smc_addr("SMC_TOP_SMC_EXTERNAL_MANDATORY_STRAPS_STRAPS_LO_BASE_ADDR")
MANDATORY_BEYOND_SHIM_OFFSET = STRAPS_LO - EXT_BASE
# Window-top stimulus addresses (4 MiB window, extent not pinned).
WINDOW_LAST_WORD = EXT_BASE + 0x3F_FFF8
WINDOW_PAST = EXT_BASE + 0x40_0000

AXI_RESP_OKAY = 0
AXI_RESP_DECERR = 3
# Error-slave data word: the DV-owned signature SmcCsrSeq.csr_read_err_signature documents
# (hw/ip/efuse/doc/architecture.adoc states it for the eFuse error slave only).
ERR_SLAVE_DATA = SmcCsrSeq.ERR_SLAVE_SIGNATURE
ACCESS_FLOOR = 20

FUSE_SENSE_MAX_SMC_CYCLES = 200_000
AXI_TIMEOUT_NS = 50_000
DRAIN_CYCLES = 8
SCAN_LIMIT_OFFSET = 0x400
SCAN_STEP = 4

_STEPS = (
    "SETUP",
    "SHIM_BASE",
    "SHIM_LAST",
    "SHIM_PAST",
    "SUPPLEMENTARY",
    "EQUAL_OFFSETS",
    "RESPONSES",
    "WINDOW_TOP",
)
_CHECKERS = (
    ("CHK-SHIM-BASE-ROUTED", "SHIM_BASE"),
    ("CHK-SHIM-LAST-WORD-ROUTED", "SHIM_LAST"),
    ("CHK-SHIM-PAST-RANGE-NOT-EFUSE", "SHIM_PAST"),
    ("CHK-EXT-SUPPLEMENTARY-ROUTED", "SUPPLEMENTARY"),
    ("CHK-EXT-REGIONS-IDENTICAL", "EQUAL_OFFSETS"),
    ("CHK-EXT-RESPONSE-RETURN", "RESPONSES"),
    ("CHK-EXT-WINDOW-TOP", "WINDOW_TOP"),
)


class _Watch:
    """Per-access sample of the efuse and external-port probes on clk_smc_i."""

    def __init__(self, want: int) -> None:
        self.want = want & ~0x3
        self.efuse = 0
        self.ar = 0
        self.aw = 0
        self.ar_match = 0
        self.aw_match = 0
        self.task = None

    @staticmethod
    def _bit(sig, name: str) -> int:
        assert sig.value.is_resolvable, f"{name} is X/Z ({sig.value})"
        return int(sig.value)

    async def _run(self) -> None:
        dut = cocotb.top
        while True:
            await RisingEdge(dut.clk_smc_i)
            self.efuse += self._bit(dut.tb_axil_efuse_bank_active, "tb_axil_efuse_bank_active")
            for chan in ("ar", "aw"):
                if self._bit(getattr(dut, f"tb_axil_external_{chan}valid"), chan + "valid"):
                    addr = getattr(dut, f"tb_axil_external_{chan}addr").value
                    assert addr.is_resolvable, f"tb_axil_external_{chan}addr is X/Z ({addr})"
                    setattr(self, chan, getattr(self, chan) + 1)
                    # The port carries the local address or the offset from the window base.
                    if int(addr) & ~0x3 in (self.want, self.want - EXT_BASE):
                        setattr(self, chan + "_match", getattr(self, chan + "_match") + 1)

    def start(self) -> None:
        self.task = cocotb.start_soon(self._run())

    def stop(self) -> None:
        self.task.cancel()

    def text(self) -> str:
        return (
            f"efuse_cycles={self.efuse} ext_ar_cycles={self.ar} ext_ar_addr_match={self.ar_match} "
            f"ext_aw_cycles={self.aw} ext_aw_addr_match={self.aw_match}"
        )


class smc_ext_window_routing_test_seq(SmcCsrSeq):
    """Routing of the SHIM range and the external regions as seen at the consumer probes."""

    def __init__(self, name: str = "smc_ext_window_routing_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._last_access = "none"
        self._scan_words = 0
        self._probe_state = "not sampled"

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    async def _access(
        self,
        label: str,
        op: SmcSysAxiOp,
        addr: int,
        *,
        wdata: int | None = None,
        expected: int | None = None,
        expect_resp: int | None = None,
        waive_decerr: bool = False,
    ) -> tuple[SmcSysAxiItem, _Watch]:
        item = SmcSysAxiItem(f"{'rd' if op == SmcSysAxiOp.READ else 'wr'}_{label}")
        item.op = op
        item.addr = addr
        item.length = 4
        item.allow_error = True
        if op == SmcSysAxiOp.WRITE:
            item.wdata = wdata
        if expected is not None:
            item.expected = expected
        if expect_resp is not None:
            item.expect_error = expect_resp > 1
            item.expected_resp = expect_resp
        watch = _Watch(addr)
        watch.start()
        self._last_access = f"{label}@0x{addr:08x}"
        waived = waive_decerr and addr not in self.env.axi_monitor.expected_decerr_addrs
        if waived:
            self.env.axi_monitor.expected_decerr_addrs.add(addr)
        try:
            await self.start_item(item)
            await self.finish_item(item)
            await ClockCycles(cocotb.top.clk_smc_i, DRAIN_CYCLES)
        finally:
            watch.stop()
            if waived:
                self.env.axi_monitor.expected_decerr_addrs.discard(addr)
        self.accesses += 1
        assert item.resp_code is not None, f"{self._last_access}: no response code"
        assert item.rdata is not None or op == SmcSysAxiOp.WRITE, f"{label}: no read data"
        cocotb.log.info(
            "ACCESS %s %s 0x%08x resp=%d rdata=0x%08x; %s",
            label,
            "RD" if op == SmcSysAxiOp.READ else "WR",
            addr,
            item.resp_code,
            (item.rdata or 0) & 0xFFFFFFFF,
            watch.text(),
        )
        return item, watch

    def _expect_efuse(self, label: str, watch: _Watch) -> None:
        assert watch.efuse > 0, f"{label}: tb_axil_efuse_bank_active never rose ({watch.text()})"
        assert watch.ar == 0 and watch.aw == 0, (
            f"{label}: smc_external presented a request on an eFuse SHIM access ({watch.text()})"
        )

    async def _measure_shim_size(self) -> int:
        """Return the first word offset at which tb_axil_efuse_bank_active does not rise."""
        for off in range(SCAN_STEP, SCAN_LIMIT_OFFSET + SCAN_STEP, SCAN_STEP):
            item, watch = await self._access(
                f"SHIM_SCAN_{off:03X}", SmcSysAxiOp.READ, EXT_BASE + off, waive_decerr=True
            )
            self._scan_words += 1
            self._probe_state = f"scan offset 0x{off:x}: {watch.text()}"
            if watch.efuse == 0:
                return off
            assert watch.ar == 0 and watch.aw == 0, (
                f"SHIM scan offset 0x{off:x}: eFuse access also reached smc_external "
                f"({watch.text()}, resp={item.resp_code})"
            )
        raise AssertionError(
            f"tb_axil_efuse_bank_active rose for every word below offset 0x{SCAN_LIMIT_OFFSET:x}; "
            f"last state {self._probe_state}"
        )

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        for sig in (
            dut.tb_axil_efuse_bank_active,
            dut.tb_axil_external_active,
            dut.tb_axil_external_arvalid,
            dut.tb_axil_external_awvalid,
        ):
            assert sig.value.is_resolvable and int(sig.value) == 0, (
                f"{sig._name} is {sig.value} before the first window access, want idle 0"
            )
        shim_size = await self._measure_shim_size()
        assert shim_size >= 8, f"measured SHIM extent 0x{shim_size:x} leaves no last word"
        cocotb.log.info(
            "observe: first word at which tb_axil_efuse_bank_active does not rise is "
            "offset 0x%x after %d scan reads",
            shim_size,
            self._scan_words,
        )
        self._mark_step("SETUP")

        item, w = await self._access(
            "SHIM_BASE", SmcSysAxiOp.READ, EXT_BASE, expected=EFUSE_BANK_INIT_TIME_RESET
        )
        self._expect_efuse("SHIM_BASE", w)
        assert item.resp_code == AXI_RESP_OKAY, f"SHIM_BASE: resp={item.resp_code}"
        assert item.rdata & 0xFFFFFFFF == EFUSE_BANK_INIT_TIME_RESET, (
            f"SHIM_BASE: rdata 0x{item.rdata:x}, want EFUSE_BANK_INIT_TIME reset "
            f"0x{EFUSE_BANK_INIT_TIME_RESET:x}"
        )
        self._mark_step("SHIM_BASE")
        self._log_chk(
            "CHK-SHIM-BASE-ROUTED",
            f"read 0x{EXT_BASE:08x} resp={item.resp_code} rdata=0x{item.rdata & 0xFFFFFFFF:08x} "
            f"(EFUSE_BANK_INIT_TIME reset 0x{EFUSE_BANK_INIT_TIME_RESET:x}); {w.text()}",
        )

        last = EXT_BASE + shim_size - 8
        item, w = await self._access("SHIM_LAST", SmcSysAxiOp.READ, last)
        self._expect_efuse("SHIM_LAST", w)
        last4 = EXT_BASE + shim_size - 4
        item4, w4 = await self._access("SHIM_LAST4", SmcSysAxiOp.READ, last4)
        self._expect_efuse("SHIM_LAST4", w4)
        self._mark_step("SHIM_LAST")
        self._log_chk(
            "CHK-SHIM-LAST-WORD-ROUTED",
            f"read 0x{last:08x} (measured SHIM extent 0x{shim_size:x} minus 8; EFUSE_SHIM_SIZE "
            f"not pinned, owner value pending) resp={item.resp_code} "
            f"rdata=0x{item.rdata & 0xFFFFFFFF:08x}; "
            f"{w.text()}; last 4-byte word 0x{last4:08x} resp={item4.resp_code} "
            f"rdata=0x{item4.rdata & 0xFFFFFFFF:08x}; {w4.text()}",
        )

        past = EXT_BASE + shim_size
        item, w = await self._access("SHIM_PAST", SmcSysAxiOp.READ, past, waive_decerr=True)
        assert w.efuse == 0, f"SHIM_PAST: tb_axil_efuse_bank_active rose ({w.text()})"
        self._mark_step("SHIM_PAST")
        self._log_chk(
            "CHK-SHIM-PAST-RANGE-NOT-EFUSE",
            f"read 0x{past:08x} resp={item.resp_code} rdata=0x{item.rdata & 0xFFFFFFFF:08x} "
            f"external_arvalid_rose={int(w.ar > 0)}; {w.text()}; answering block unstated "
            f"(owner value pending)",
        )

        item, wr = await self._access(
            "SUPP_BASE",
            SmcSysAxiOp.READ,
            SUPP_BASE,
            expect_resp=AXI_RESP_DECERR,
            waive_decerr=True,
        )
        assert wr.ar_match > 0, f"SUPP_BASE read: no external AR with the address ({wr.text()})"
        assert item.resp_code == AXI_RESP_DECERR, f"SUPP_BASE read: resp={item.resp_code}"
        supp_rdata = item.rdata & 0xFFFFFFFF
        item, ww = await self._access(
            "SUPP_BASE",
            SmcSysAxiOp.WRITE,
            SUPP_BASE,
            wdata=0xA5A5_0001,
            expect_resp=AXI_RESP_DECERR,
            waive_decerr=True,
        )
        assert ww.aw_match > 0, f"SUPP_BASE write: no external AW with the address ({ww.text()})"
        assert item.resp_code == AXI_RESP_DECERR, f"SUPP_BASE write: resp={item.resp_code}"
        self._mark_step("SUPPLEMENTARY")
        self._log_chk(
            "CHK-EXT-SUPPLEMENTARY-ROUTED",
            f"0x{SUPP_BASE:08x} read resp=3 rdata=0x{supp_rdata:08x} ({wr.text()}); write resp=3 "
            f"({ww.text()}); efuse_cycles={wr.efuse + ww.efuse}",
        )

        regions = {}
        for name, base in (
            ("mandatory", EXT_BASE + MANDATORY_BEYOND_SHIM_OFFSET),
            ("supplementary", SUPP_BASE),
        ):
            ritem, rw = await self._access(
                f"EQ_{name}_RD", SmcSysAxiOp.READ, base + 4, waive_decerr=True
            )
            witem, ww = await self._access(
                f"EQ_{name}_WR",
                SmcSysAxiOp.WRITE,
                base + 8,
                wdata=0x5A5A_0002,
                waive_decerr=True,
            )
            assert rw.ar_match > 0, f"{name} +0x4 read not presented on smc_external ({rw.text()})"
            assert ww.aw_match > 0, f"{name} +0x8 write not presented on smc_external ({ww.text()})"
            assert rw.efuse == 0 and ww.efuse == 0, f"{name}: eFuse activity ({rw.text()})"
            regions[name] = (ritem.resp_code, witem.resp_code, rw.ar_match, ww.aw_match)
        assert regions["mandatory"][2:] == regions["supplementary"][2:], (
            f"AR/AW address-match cycles differ between regions {regions}"
        )
        self._mark_step("EQUAL_OFFSETS")
        self._log_chk(
            "CHK-EXT-REGIONS-IDENTICAL",
            f"mandatory 0x{EXT_BASE + MANDATORY_BEYOND_SHIM_OFFSET:08x} read+4 resp="
            f"{regions['mandatory'][0]} write+8 resp={regions['mandatory'][1]}; supplementary "
            f"0x{SUPP_BASE:08x} read+4 resp={regions['supplementary'][0]} write+8 resp="
            f"{regions['supplementary'][1]}; both routed to smc_external for AR and AW",
        )

        item, w = await self._access("STRAPS_LO", SmcSysAxiOp.READ, STRAPS_LO)
        assert item.resp_code == AXI_RESP_OKAY, f"strap read resp={item.resp_code}"
        assert w.ar_match > 0 and w.efuse == 0, f"strap read not at smc_external ({w.text()})"
        strap = item.rdata & 0xFFFFFFFF
        item, ws = await self._access(
            "SUPP_RET",
            SmcSysAxiOp.READ,
            SUPP_BASE,
            expect_resp=AXI_RESP_DECERR,
            waive_decerr=True,
        )
        assert item.resp_code == AXI_RESP_DECERR, f"supplementary read resp={item.resp_code}"
        assert item.rdata & 0xFFFFFFFF == ERR_SLAVE_DATA, (
            f"supplementary read data 0x{item.rdata:x}, differs from the bench-defined "
            f"error-slave signature 0x{ERR_SLAVE_DATA:08x}"
        )
        self._mark_step("RESPONSES")
        self._log_chk(
            "CHK-EXT-RESPONSE-RETURN",
            f"strap word 0x{STRAPS_LO:08x} resp=0 (OKAY) rdata=0x{strap:08x} (printed, no pinned "
            f"value) ({w.text()}); "
            f"supplementary 0x{SUPP_BASE:08x} resp=3 (DECERR) rdata=0x{ERR_SLAVE_DATA:08x} "
            f"({ws.text()}); fidelity against the port is not observable (no external-port R/B "
            f"probe in tb_top): the fallback is the response and data seen at sep_axi_in plus "
            f"the AR address match on the port; memmap.adoc fixes only the DECERR response of the "
            f"supplementary region; the data word is not a documented value: it is compared "
            f"against the bench-defined error-slave signature (csr_read_err_signature); "
            f"SLVERR not driveable "
            f"(owner value pending)",
        )

        item, wt = await self._access(
            "WINDOW_LAST", SmcSysAxiOp.READ, WINDOW_LAST_WORD, waive_decerr=True
        )
        assert wt.ar_match > 0, f"window last word not presented on smc_external ({wt.text()})"
        top_resp, top_data = item.resp_code, item.rdata & 0xFFFFFFFF
        item, wp = await self._access(
            "WINDOW_PAST", SmcSysAxiOp.READ, WINDOW_PAST, waive_decerr=True
        )
        assert wp.efuse == 0, f"past-window read reached the eFuse leg ({wp.text()})"
        self._mark_step("WINDOW_TOP")
        self._log_chk(
            "CHK-EXT-WINDOW-TOP",
            f"last word 0x{WINDOW_LAST_WORD:08x} resp={top_resp} rdata=0x{top_data:08x} "
            f"({wt.text()}); past 0x{WINDOW_PAST:08x} resp={item.resp_code} "
            f"rdata=0x{item.rdata & 0xFFFFFFFF:08x} external_request_seen={int(wp.ar > 0)} "
            f"({wp.text()}); window extent not pinned (owner value pending), "
            f"past-window response printed only",
        )

        self._timeout_paths()
        self._nonvac_fence()

    def _timeout_paths(self) -> None:
        dut = cocotb.top
        waits = (
            (
                "wait_fuse_sense_done.tb_fuse_sense_done",
                FUSE_SENSE_MAX_SMC_CYCLES,
                int(dut.tb_fuse_sense_done.value),
            ),
            (
                "wait_fuse_sense_done.tb_fuse_reset_n",
                FUSE_SENSE_MAX_SMC_CYCLES,
                int(dut.tb_fuse_reset_n.value),
            ),
            (
                "wait_fuse_sense_done.tb_rst_warm_smc_clk_n",
                FUSE_SENSE_MAX_SMC_CYCLES,
                int(dut.tb_rst_warm_smc_clk_n.value),
            ),
        )
        text = " ".join(f"{n}=bound {b} smc_cycles last={v}" for n, b, v in waits)
        text += (
            f" sep_in_axi_access=bound {AXI_TIMEOUT_NS}ns last={self._last_access}"
            f" shim_size_scan=bound {SCAN_LIMIT_OFFSET // SCAN_STEP} reads last={self._probe_state}"
            f" per_access_probe_drain=fixed {DRAIN_CYCLES} clk_smc_i cycles (no wait on a state)"
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: 6 bounded waits: %s; expiry raises AssertionError", text
        )

    def _nonvac_fence(self) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"step stamps not increasing: {times}"
        chk_ids = tuple(c for c, _ in self._chk_marks)
        assert chk_ids == tuple(c for c, _ in _CHECKERS), f"checker lines {chk_ids}"
        stamp_of = dict(self._stamps)
        for (chk_id, when), (_, step) in zip(self._chk_marks, _CHECKERS):
            assert when >= stamp_of[step], f"{chk_id} printed before its step {step} stamp"
        assert self.accesses >= ACCESS_FLOOR, (
            f"{self.accesses} SEP_IN accesses issued, literal floor {ACCESS_FLOOR}"
        )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; accesses %d >= floor %d; checker lines %s; stamps %s",
            " < ".join(ids),
            self.accesses,
            ACCESS_FLOOR,
            ",".join(chk_ids),
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
