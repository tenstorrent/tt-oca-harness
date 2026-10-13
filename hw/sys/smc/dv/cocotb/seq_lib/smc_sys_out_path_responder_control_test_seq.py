# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG-to-SYS_OUT path with responder control: route, split channels, recovery, stall.

Contract XBAR_018, anchor smc_sys_out_path_responder_control_test.
Allocated scenarios: XBAR-JTAG-OUTBOUND.S1, XBAR-JTAG-OUTBOUND.S2, XBAR-OUT-WSPLIT.S1,
XBAR-OUT-WSPLIT.S2, XBAR-OUT-WSPLIT.S3, XBAR-OUT-RESP-READ.S4, XBAR-OUT-RESP-WRITE.S4,
XBAR-CONCURRENT.S4.
Spec sources: fabric.adoc Fabric Topology, Alias Remapping, Outbound Traffic Flow;
smc-programming.adoc Address Map ext_out statement.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import REGION_SIZE_RESET, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import (
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    PASS_ALL_CONFIG,
    RESP_DECERR,
    RESP_OKAY,
    RESP_SLVERR,
    jtag_axi_read,
    jtag_axi_write,
)

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    FILTER_CTRL_END_ADDR_REG_DEFAULT,
    FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
    FILTER_CTRL_START_ADDR_REG_DEFAULT,
)

REGION_SIZE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
SCRATCH_COLD_0 = smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 0)
# Contract value of REGION_SIZE (16 MiB); the generated reset must agree.
REGION_SIZE_EXPECTED = 0x0100_0000
assert REGION_SIZE_RESET == REGION_SIZE_EXPECTED
INBOUND_PASS_ALL_END = 0x00FF_FFFF_FFFF_FFFF

OUT_ADDR = 0x0200_0000
OUT_ALT_ADDR = 0x0200_0008
OUT_STROBE_ADDR = 0x0200_0010
# Address classes of S2: below both windows, between them, above both, and a 56-bit address.
ROUTE_CASES = (
    ("BELOW", 0x0200_0000, 0x1111_2222_3333_0001),
    ("BETWEEN", 0x8000_1000, 0x2222_3333_4444_0002),
    ("ABOVE", 0xD000_0000, 0x3333_4444_5555_0003),
    ("WIDE56", 0x0000_0123_4567_8000, 0x4444_5555_6666_0004),
)
STROBE_DATA = 0xFFFF_FFFF_FFFF_FFFF
STROBE_MASK = 0x0F
SEED_WORD = 0x5EED_0A0B_0C0D_0E0F
READ_SEED_PLAIN = 0x5EED_1111_2222_3333
SCRATCH_PATTERN = 0x5A5A_C0DE

SILENT_WINDOW_CYCLES = 200
STALL_CYCLES = 40
# Bounds in clk_smc_i cycles; TB ceilings, not latency claims.
REQUEST_WAIT_CYCLES = 2000
RELEASE_WAIT_CYCLES = 2000
FUSE_SENSE_CYCLES = 200_000
ACCESS_TIMEOUT_NS = 50_000
# Literal stimulus floors: JTAG 26, SYS_IN 1, SEP_IN 12.
ACCESS_FLOOR = 39
JTAG_ACCESSES = 26
SYS_IN_ACCESSES = 1
SEP_IN_ACCESSES = 12

_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9")
_TERMS = (
    "SETUP",
    "ROUTE",
    "SILENT",
    "AW_FIRST",
    "W_FIRST",
    "SAME_CYCLE",
    "READ_RECOVERY",
    "WRITE_RECOVERY",
    "STALL_LOCAL",
)
_CHECKERS = (
    "CHK-JTAG-OUTBOUND-ROUTE",
    "CHK-JTAG-OUTBOUND-SILENT",
    "CHK-WSPLIT-AW-FIRST",
    "CHK-WSPLIT-W-FIRST",
    "CHK-WSPLIT-SAME-CYCLE",
    "CHK-OUT-READ-RECOVERY",
    "CHK-OUT-WRITE-RECOVERY",
    "CHK-STALLED-OUTBOUND-LOCAL-ANSWERED",
)
_CHECKER_STEPS = ("S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9")


class _HandshakeWatch:
    """Samples the SYS_OUT and JTAG handshakes once per clk_smc_i cycle."""

    _PROBES = (
        "tb_output_axi_awvalid",
        "tb_output_axi_awready",
        "tb_output_axi_wvalid",
        "tb_output_axi_wready",
        "tb_output_axi_bvalid",
        "tb_output_axi_bready",
        "tb_output_axi_arvalid",
        "tb_output_axi_arready",
        "jtag_axi_rvalid",
        "jtag_axi_bvalid",
        "jtag_axi_awvalid",
        "jtag_axi_wvalid",
    )

    def __init__(self) -> None:
        self.dut = cocotb.top
        self.stop = False
        self.cycle = 0
        self.unresolved = 0
        self.events: list[tuple[str, int, int]] = []
        self.stalls = {"aw": 0, "w": 0}

    def _val(self, name: str) -> int:
        value = getattr(self.dut, name).value
        if not value.is_resolvable:
            self.unresolved += 1
            return 0
        return int(value)

    def first(self, kind: str, after: int) -> tuple[int, int] | None:
        for ev_kind, cyc, val in self.events:
            if ev_kind == kind and cyc > after:
                return cyc, val
        return None

    def count(self, kind: str, after: int, upto: int | None = None) -> int:
        return sum(
            1 for k, c, _ in self.events if k == kind and c > after and (upto is None or c <= upto)
        )

    async def run(self) -> None:
        dut = self.dut
        while not self.stop:
            await RisingEdge(dut.clk_smc_i)
            await ReadOnly()
            self.cycle += 1
            s = {name: self._val(name) for name in self._PROBES}
            aw = s["tb_output_axi_awvalid"] and s["tb_output_axi_awready"]
            w = s["tb_output_axi_wvalid"] and s["tb_output_axi_wready"]
            if s["tb_output_axi_awvalid"] and not s["tb_output_axi_awready"]:
                self.stalls["aw"] += 1
            if s["tb_output_axi_wvalid"] and not s["tb_output_axi_wready"]:
                self.stalls["w"] += 1
            for kind, key in (("jawv", "jtag_axi_awvalid"), ("jwv", "jtag_axi_wvalid")):
                if s[key]:
                    self.events.append((kind, self.cycle, 0))
            if s["tb_output_axi_awvalid"]:
                self.events.append(("awv", self.cycle, 0))
            if s["tb_output_axi_wvalid"]:
                self.events.append(("wv", self.cycle, 0))
            if aw:
                self.events.append(("aw", self.cycle, self._val("tb_output_axi_awaddr")))
            if w:
                self.events.append(("w", self.cycle, self._val("tb_output_axi_wdata")))
            if aw and w:
                self.events.append(("both", self.cycle, 0))
            if s["tb_output_axi_bvalid"] and s["tb_output_axi_bready"]:
                self.events.append(("b", self.cycle, self._val("tb_output_axi_bresp")))
            if s["tb_output_axi_arvalid"] and s["tb_output_axi_arready"]:
                self.events.append(("ar", self.cycle, self._val("tb_output_axi_araddr")))
            if s["jtag_axi_rvalid"]:
                self.events.append(("jr", self.cycle, 0))
            if s["jtag_axi_bvalid"]:
                self.events.append(("jb", self.cycle, 0))


class smc_sys_out_path_responder_control_test_seq(SmcCsrSeq):
    """Drive JTAG, SEP_IN and SYS_IN accesses against the SYS_OUT responder knobs."""

    def __init__(self, name: str = "smc_sys_out_path_responder_control_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: dict[str, list] = {}
        self.watch: _HandshakeWatch | None = None
        self.jtag_done = 0
        self.sys_in_done = 0
        self.stage = "init"

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    def _wait_state(self, name: str, bound: str, last: str) -> None:
        self._waits[name] = [bound, last]

    def _assert_clean_watch(self, label: str) -> None:
        assert self.watch.unresolved == 0, (
            f"{label}: {self.watch.unresolved} X/Z handshake samples on the SYS_OUT/JTAG probes"
        )

    @staticmethod
    def _sample(name: str) -> int:
        sig = getattr(cocotb.top, name)
        assert sig.value.is_resolvable, f"{name} is X/Z ({sig.value})"
        return int(sig.value)

    async def _await_task(self, task, name: str, bound: int):
        """Wait up to ``bound`` clk_smc_i cycles for a started access to finish."""
        last = "pending"
        for n in range(1, bound + 1):
            if task.done():
                self._wait_state(name, f"{bound}clk_smc_i", f"done after {n - 1} cycles")
                return task.result()
            await RisingEdge(cocotb.top.clk_smc_i)
            last = f"pending at cycle {n}"
        self._wait_state(name, f"{bound}clk_smc_i", f"EXPIRED {last}")
        raise AssertionError(
            f"{name}: access not complete within {bound} clk_smc_i cycles ({last})"
        )

    async def _await_event(self, kind: str, after: int, name: str, bound: int) -> int:
        """Wait up to ``bound`` cycles for the first ``kind`` handshake after cycle ``after``."""
        for n in range(1, bound + 1):
            hit = self.watch.first(kind, after)
            if hit is not None:
                self._wait_state(
                    name, f"{bound}clk_smc_i", f"{kind} handshake at +{hit[0] - after}"
                )
                return hit[0]
            await RisingEdge(cocotb.top.clk_smc_i)
        self._wait_state(name, f"{bound}clk_smc_i", f"EXPIRED no {kind} handshake")
        raise AssertionError(f"{name}: no {kind} handshake on SYS_OUT within {bound} cycles")

    async def _jtag_write_strobed(self, addr: int, data: int, wstrb: int) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"jtag_output_write_strobed_0x{addr:x}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = 8
        item.wdata = data
        item.wstrb = wstrb
        item.expected_resp = RESP_OKAY
        await _OneShot(item, "jtag_strobed_os").start(self.env.jtag_axi_agent.sequencer)
        return item

    async def _sys_in_read(self, label: str, addr: int, expected: int) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"sys_in_{label}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.expected = expected
        item.expected_resp = RESP_OKAY
        await _OneShot(item, f"sys_in_{label}_os").start(self.env.sys_in_axi_agent.sequencer)
        return item

    async def _route(self, mem) -> None:
        w = self.watch
        for label, addr, data in ROUTE_CASES:
            start = w.cycle
            wr = await jtag_axi_write(self, addr, data, expected_resp=RESP_OKAY)
            assert wr.resp_code == RESP_OKAY, f"{label} write resp {wr.resp_code}"
            aw, wd = w.first("aw", start), w.first("w", start)
            assert aw is not None and wd is not None, f"{label}: no AW/W handshake on SYS_OUT"
            assert w.count("aw", start) == 1 and w.count("w", start) == 1, label
            assert aw[1] == addr, f"{label}: awaddr 0x{aw[1]:x} != issued 0x{addr:x}"
            assert wd[1] == data, f"{label}: wdata 0x{wd[1]:x} != issued 0x{data:x}"
            held = mem.read64(addr)
            assert held == data, f"{label}: SYS_OUT memory 0x{held:x} != 0x{data:x}"
            start = w.cycle
            rd = await jtag_axi_read(self, addr, expected=data, expected_resp=RESP_OKAY)
            assert rd.resp_code == RESP_OKAY and rd.rdata == data, f"{label} read 0x{rd.rdata:x}"
            ar = w.first("ar", start)
            assert ar is not None and w.count("ar", start) == 1, f"{label}: no single AR"
            assert ar[1] == addr, f"{label}: araddr 0x{ar[1]:x} != issued 0x{addr:x}"
        mem.write64(OUT_STROBE_ADDR, 0)
        await self._jtag_write_strobed(OUT_STROBE_ADDR, STROBE_DATA, STROBE_MASK)
        low = mem.read_int(OUT_STROBE_ADDR, 4)
        high = mem.read_int(OUT_STROBE_ADDR + 4, 4)
        assert low == 0xFFFF_FFFF, f"strobed lower word 0x{low:x}, want 0xFFFFFFFF"
        assert high == 0, f"wstrb 0x0F wrote upper bytes: 0x{high:x}"
        self._assert_clean_watch("S2")
        self._mark_step("S2")
        cases = ", ".join(f"{lbl}=0x{a:x}" for lbl, a, _ in ROUTE_CASES)
        self._log_chk(
            "CHK-JTAG-OUTBOUND-ROUTE",
            f"awaddr/araddr/wdata equal the issued values for {cases}; reads OKAY with the "
            f"written words; wstrb 0x0F write left bytes 4-7 = 0x{high:08x} (bytes 0-3 "
            f"0x{low:08x}) in the SYS_OUT memory",
        )

    async def _silent(self, mem) -> None:
        w = self.watch
        dut = cocotb.top
        mem.write64(OUT_ADDR, SEED_WORD)
        dut.tb_output_axi_resp_hold.value = 1
        start = w.cycle
        task = cocotb.start_soon(jtag_axi_read(self, OUT_ADDR, allow_error=True))
        ar_cycle = await self._await_event(
            "ar", start, "S3_request_on_SYS_OUT", REQUEST_WAIT_CYCLES
        )
        last_rvalid = 0
        for n in range(1, SILENT_WINDOW_CYCLES + 1):
            await RisingEdge(dut.clk_smc_i)
            last_rvalid = self._sample("jtag_axi_rvalid")
            assert last_rvalid == 0, f"jtag_axi_rvalid=1 at hold cycle {n}/{SILENT_WINDOW_CYCLES}"
            assert self._sample("jtag_axi_bvalid") == 0, f"jtag_axi_bvalid=1 at hold cycle {n}"
        self._wait_state(
            "S3_silence_window",
            f"{SILENT_WINDOW_CYCLES}clk_smc_i",
            f"jtag_axi_rvalid={last_rvalid}",
        )
        assert not task.done(), "the stalled JTAG read completed during the hold"
        assert w.count("jr", ar_cycle) == 0, "jtag_axi_rvalid pulsed during the hold"
        dut.tb_output_axi_resp_hold.value = 0
        item = await self._await_task(task, "S3_release_response", RELEASE_WAIT_CYCLES)
        self._assert_clean_watch("S3")
        self._mark_step("S3")
        self._log_chk(
            "CHK-JTAG-OUTBOUND-SILENT",
            f"jtag_axi_rvalid stayed 0 for {SILENT_WINDOW_CYCLES} cycles of "
            f"tb_output_axi_resp_hold after the AR handshake; after release the response arrived "
            f"(OBSERVE-ONLY, SF-003 "
            f"open): resp_code={item.resp_code} rdata=0x{item.rdata:x} seeded=0x{SEED_WORD:x}",
        )

    async def _split_write(self, mem, channel: str, data: int):
        w = self.watch
        mem.enable_backpressure(channels=[channel], stall_cycles=STALL_CYCLES)
        stalled_before = w.stalls[channel]
        start = w.cycle
        try:
            if channel == "aw":
                mem.arm_w_before_aw()
            wr = await jtag_axi_write(self, OUT_ADDR, data, expected_resp=RESP_OKAY)
        finally:
            mem.disable_backpressure()
        aw, wd, b = w.first("aw", start), w.first("w", start), w.first("b", start)
        assert aw is not None and wd is not None and b is not None, (aw, wd, b)
        stalls = w.stalls[channel] - stalled_before
        assert stalls > 0, f"the {channel} backpressure never reached the bus"
        assert wr.resp_code == RESP_OKAY, f"bresp {wr.resp_code}"
        held = mem.read64(OUT_ADDR)
        assert held == data, f"SYS_OUT memory 0x{held:x} != 0x{data:x}"
        return aw[0] - start, wd[0] - start, b[0] - start, stalls

    async def _aw_first(self, mem) -> None:
        aw, wd, b, stalls = await self._split_write(mem, "w", 0x6161_0000_0000_0005)
        assert aw < wd, f"W handshake (+{wd}) not after AW handshake (+{aw})"
        assert b > wd, f"B handshake (+{b}) not after the W handshake (+{wd})"
        self._assert_clean_watch("S4")
        self._mark_step("S4")
        self._log_chk(
            "CHK-WSPLIT-AW-FIRST",
            f"W stalled {STALL_CYCLES}-cycle windows ({stalls} wvalid&!wready cycles): AW "
            f"handshake at +{aw}, W at +{wd}, B at +{b} cycles, bresp OKAY, stored word matches",
        )

    async def _w_first(self, mem) -> None:
        aw, wd, b, stalls = await self._split_write(mem, "aw", 0x6262_0000_0000_0006)
        assert wd < aw, f"AW handshake (+{aw}) not after W handshake (+{wd})"
        assert b > aw, f"B handshake (+{b}) not after the AW handshake (+{aw})"
        self._assert_clean_watch("S5")
        self._mark_step("S5")
        self._log_chk(
            "CHK-WSPLIT-W-FIRST",
            f"AW stalled {STALL_CYCLES}-cycle windows ({stalls} awvalid&!awready cycles): W "
            f"handshake at +{wd}, AW at +{aw}, B at +{b} cycles, bresp OKAY, stored word matches",
        )

    async def _same_cycle(self, mem) -> None:
        w = self.watch
        mem.disable_backpressure()
        mem.clear_response_delay()
        start = w.cycle
        data = 0x6363_0000_0000_0007
        wr = await jtag_axi_write(self, OUT_ADDR, data, expected_resp=RESP_OKAY)
        assert wr.resp_code == RESP_OKAY, f"bresp {wr.resp_code}"
        both = w.count("both", start)
        assert mem.read64(OUT_ADDR) == data
        self._assert_clean_watch("S6")
        self._mark_step("S6")
        marks = {k: w.first(k, start) for k in ("jawv", "jwv", "awv", "wv", "aw", "w")}
        at = {k: (None if v is None else v[0] - start) for k, v in marks.items()}
        self._log_chk(
            "CHK-WSPLIT-SAME-CYCLE",
            f"both_handshake_cycles={both} (OBSERVE-ONLY, SF-004 open: AW/W independence at "
            f"output_axi is not stated; no compare on the count); bresp OKAY, stored word "
            f"matches; first-valid cycle offsets jtag_awvalid=+{at['jawv']} jtag_wvalid="
            f"+{at['jwv']} sys_out_awvalid=+{at['awv']} sys_out_wvalid=+{at['wv']}; handshakes "
            f"aw=+{at['aw']} w=+{at['w']}",
        )

    async def _read_recovery(self, mem, mon) -> None:
        mon.allow_slverr = True
        mon.allow_decerr = True
        mem.write64(OUT_ALT_ADDR, READ_SEED_PLAIN)
        notes = []
        plain = 0

        async def plain_read(label: str) -> None:
            nonlocal plain
            rd = await jtag_axi_read(
                self, OUT_ALT_ADDR, expected=READ_SEED_PLAIN, expected_resp=RESP_OKAY
            )
            assert rd.resp_code == RESP_OKAY and rd.rdata == READ_SEED_PLAIN, (
                f"{label}: plain read resp={rd.resp_code} rdata=0x{rd.rdata:x}"
            )
            plain += 1

        for label, code, tally in (
            ("SLVERR", RESP_SLVERR, "r_slverr"),
            ("DECERR", RESP_DECERR, "r_decerr"),
        ):
            before = mon.snapshot()
            mem.inject_error(OUT_ALT_ADDR, code, read=True, write=False)
            item = await jtag_axi_read(self, OUT_ALT_ADDR, allow_error=True)
            after = mon.snapshot()
            assert after[tally] == before[tally] + 1, f"{label} read: wire tally {before}->{after}"
            notes.append(f"{label} read: manager resp_code={item.resp_code} rdata=0x{item.rdata:x}")
            await plain_read(f"after {label}")
        await plain_read("OKAY read")
        await plain_read("after OKAY read")
        self._assert_clean_watch("S7")
        self._mark_step("S7")
        self._log_chk(
            "CHK-OUT-READ-RECOVERY",
            f"{plain} plain reads returned OKAY with 0x{READ_SEED_PLAIN:x} after SLVERR, DECERR "
            f"and OKAY reads; injected codes seen once each on the SYS_OUT wire; manager side "
            f"(OBSERVE-ONLY, SF-003 open): {'; '.join(notes)}",
        )

    async def _write_recovery(self, mem, mon) -> None:
        words = iter(0x7000_0000_0000_0010 + 0x0101_0000_0000_0000 * i for i in range(1, 10))
        notes = []
        plain = 0

        async def plain_write(label: str) -> None:
            nonlocal plain
            data = next(words)
            wr = await jtag_axi_write(self, OUT_ALT_ADDR, data, expected_resp=RESP_OKAY)
            assert wr.resp_code == RESP_OKAY, f"{label}: plain write resp {wr.resp_code}"
            held = mem.read64(OUT_ALT_ADDR)
            assert held == data, f"{label}: SYS_OUT memory 0x{held:x} != 0x{data:x}"
            plain += 1

        for label, code, tally in (
            ("SLVERR", RESP_SLVERR, "b_slverr"),
            ("DECERR", RESP_DECERR, "b_decerr"),
        ):
            before = mon.snapshot()
            mem.inject_error(OUT_ALT_ADDR, code, read=False, write=True)
            item = await jtag_axi_write(self, OUT_ALT_ADDR, next(words), allow_error=True)
            after = mon.snapshot()
            assert after[tally] == before[tally] + 1, f"{label} write: wire tally {before}->{after}"
            notes.append(f"{label} write: manager resp_code={item.resp_code}")
            await plain_write(f"after {label}")
        await plain_write("OKAY write")
        await plain_write("after OKAY write")
        mon.allow_slverr = False
        mon.allow_decerr = False
        self._assert_clean_watch("S8")
        self._mark_step("S8")
        self._log_chk(
            "CHK-OUT-WRITE-RECOVERY",
            f"{plain} plain writes returned OKAY and the SYS_OUT memory held each word after "
            f"SLVERR, DECERR and OKAY writes; injected codes seen once each on the SYS_OUT wire; "
            f"manager side (OBSERVE-ONLY, SF-003 open): {'; '.join(notes)}",
        )

    async def _stall_local(self, mem) -> None:
        w = self.watch
        dut = cocotb.top
        await self.csr_write("INBOUND0_START_PASS_ALL", INBOUND0_START, 0, length=8)
        await self.csr_write("INBOUND0_END_PASS_ALL", INBOUND0_END, INBOUND_PASS_ALL_END, length=8)
        await self.csr_write(
            "INBOUND0_CONFIG_PASS_ALL", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG, length=8
        )
        await self.csr_read(
            "INBOUND0_CONFIG_PASS_ALL_RB",
            INBOUND0_FILTER_CONFIG,
            expected=PASS_ALL_CONFIG,
            length=8,
        )
        mem.write64(OUT_ADDR, SEED_WORD)
        dut.tb_output_axi_resp_hold.value = 1
        start = w.cycle
        task = cocotb.start_soon(jtag_axi_read(self, OUT_ADDR, allow_error=True))
        await self._await_event("ar", start, "S9_request_on_SYS_OUT", REQUEST_WAIT_CYCLES)
        t0 = int(get_sim_time("ps"))
        sys_rs = await self._sys_in_read("REGION_SIZE", REGION_SIZE, REGION_SIZE_EXPECTED)
        t1 = int(get_sim_time("ps"))
        sep_rs = await self.csr_read("SEP_REGION_SIZE", REGION_SIZE, REGION_SIZE_EXPECTED)
        await self.csr_write("SEP_SCRATCH_WR", SCRATCH_COLD_0, SCRATCH_PATTERN)
        sep_sc = await self.csr_read("SEP_SCRATCH_RD", SCRATCH_COLD_0, SCRATCH_PATTERN)
        t2 = int(get_sim_time("ps"))
        assert not task.done(), "the stalled JTAG read completed while the local accesses ran"
        dut.tb_output_axi_resp_hold.value = 0
        item = await self._await_task(task, "S9_release_response", RELEASE_WAIT_CYCLES)
        assert sys_rs.resp_code == RESP_OKAY and sys_rs.rdata == REGION_SIZE_EXPECTED
        assert sep_rs == REGION_SIZE_EXPECTED and sep_sc == SCRATCH_PATTERN
        self._wait_state(
            "S9_local_accesses",
            f"{ACCESS_TIMEOUT_NS}ns",
            f"SYS_IN read {t1 - t0}ps, SEP_IN {t2 - t1}ps",
        )
        await self.csr_write("SEP_SCRATCH_RESTORE", SCRATCH_COLD_0, 0)
        await self.csr_write(
            "INBOUND0_CONFIG_RESTORE",
            INBOUND0_FILTER_CONFIG,
            FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
            length=8,
        )
        await self.csr_write(
            "INBOUND0_START_RESTORE", INBOUND0_START, FILTER_CTRL_START_ADDR_REG_DEFAULT, length=8
        )
        await self.csr_write(
            "INBOUND0_END_RESTORE", INBOUND0_END, FILTER_CTRL_END_ADDR_REG_DEFAULT, length=8
        )
        await self.csr_read(
            "INBOUND0_CONFIG_RESTORE_RB",
            INBOUND0_FILTER_CONFIG,
            expected=FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
            length=8,
        )
        self._assert_clean_watch("S9")
        self._mark_step("S9")
        self._log_chk(
            "CHK-STALLED-OUTBOUND-LOCAL-ANSWERED",
            f"while the JTAG read was held by tb_output_axi_resp_hold: SYS_IN REGION_SIZE "
            f"0x{sys_rs.rdata:08x} OKAY in {t1 - t0} ps, SEP_IN REGION_SIZE 0x{sep_rs:08x} and "
            f"SCRATCH_COLD[0] 0x{sep_sc:x} answered by {t2 - t1} ps (guard {ACCESS_TIMEOUT_NS} "
            f"ns); JTAG read still pending, then completed after release (OBSERVE-ONLY, SF-003 "
            f"open): resp_code={item.resp_code} rdata=0x{item.rdata:x}",
        )

    async def body(self) -> None:
        sb = self.env.scoreboard
        base = dict(sb.axi_accesses_by_bus)
        mem = self.cfg.sys_out_mem
        mon = self.env.output_axi_monitor
        assert mem is not None, "SYS_OUT responder not bound"
        self.stage = "fuse_sense"
        await self.wait_fuse_sense_done()
        for sub in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"):
            self._wait_state(f"fuse_{sub}", f"{FUSE_SENSE_CYCLES}clk_smc_i", "released")
        self.watch = _HandshakeWatch()
        cocotb.start_soon(self.watch.run())
        dut = cocotb.top
        try:
            writes0 = self._sample("tb_output_axi_write_count")
            reads0 = self._sample("tb_output_axi_read_count")
            await ClockCycles(dut.clk_smc_i, 1)
            self._mark_step("S1")
            for stage, fn in (
                ("S2", lambda: self._route(mem)),
                ("S3", lambda: self._silent(mem)),
                ("S4", lambda: self._aw_first(mem)),
                ("S5", lambda: self._w_first(mem)),
                ("S6", lambda: self._same_cycle(mem)),
                ("S7", lambda: self._read_recovery(mem, mon)),
                ("S8", lambda: self._write_recovery(mem, mon)),
                ("S9", lambda: self._stall_local(mem)),
            ):
                self.stage = stage
                await fn()
        finally:
            dut.tb_output_axi_resp_hold.value = 0
            mem.disable_backpressure()
            mon.allow_slverr = False
            mon.allow_decerr = False
            self.watch.stop = True
            await RisingEdge(dut.clk_smc_i)
        writes1 = self._sample("tb_output_axi_write_count")
        reads1 = self._sample("tb_output_axi_read_count")
        done = {
            k: sb.axi_accesses_by_bus.get(k, 0) - base.get(k, 0)
            for k in ("JTAG AXI", "SYS_IN AXI", "SEP_IN AXI")
        }
        self.jtag_done, self.sys_in_done = done["JTAG AXI"], done["SYS_IN AXI"]
        assert done["JTAG AXI"] == JTAG_ACCESSES, f"JTAG accesses {done}"
        assert done["SYS_IN AXI"] == SYS_IN_ACCESSES, f"SYS_IN accesses {done}"
        assert done["SEP_IN AXI"] == SEP_IN_ACCESSES == self.accesses, f"SEP_IN {done}"
        total = sum(done.values())
        assert total >= ACCESS_FLOOR, f"{total} accesses, floor {ACCESS_FLOOR}"
        self._timeout_paths()
        self._nonvac_fence(total, writes1 - writes0, reads1 - reads0)

    def _timeout_paths(self) -> None:
        waits = [f"{name} bound={bound} last={last}" for name, (bound, last) in self._waits.items()]
        waits.append(
            f"axi_access bound={ACCESS_TIMEOUT_NS}ns allow_timeout=False last=all "
            f"{self.jtag_done + self.sys_in_done + self.accesses} accesses answered"
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits, each raises AssertionError with the last state "
            "on expiry: %s",
            len(waits),
            "; ".join(waits),
        )

    def _nonvac_fence(self, total: int, writes: int, reads: int) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        chk_ids = tuple(c for c, _ in self._chk_marks)
        assert chk_ids == _CHECKERS, f"checker lines {chk_ids}, want {_CHECKERS}"
        stamp_of = dict(self._stamps)
        for (chk_id, when), step in zip(self._chk_marks, _CHECKER_STEPS):
            assert when >= stamp_of[step], f"{chk_id} printed before its step {step} stamp"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s; accesses %d >= floor %d "
            "(JTAG %d, SYS_IN %d, SEP_IN %d); SYS_OUT responder counted %d writes and %d reads",
            " < ".join(_TERMS),
            ",".join(chk_ids),
            ",".join(f"{s}={t}" for s, t in self._stamps),
            total,
            ACCESS_FLOOR,
            self.jtag_done,
            self.sys_in_done,
            self.accesses,
            writes,
            reads,
        )
