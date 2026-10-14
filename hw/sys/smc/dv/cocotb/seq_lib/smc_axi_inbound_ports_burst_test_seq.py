# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Full-width and INCR burst traffic on the three inbound AXI ports.

Spec sources: fabric.adoc Interfaces / AXI Interface Widths and Topology, scratch.rdl SCRATCH.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import PASS_ALL_CONFIG

BURST_FIXED = 0
BURST_INCR = 1
BURST_WRAP = 2
RESP_OKAY = 0
_RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR", None: "none"}

FUSE_SENSE_MAX_SMC_CYCLES = 200_000
AXI_GUARD_NS = 50_000

_INB = "SMC_TOP_SMC_INBOUND_FILTER_CTRL_{}_BASE_ADDR"
_OUTB = "SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_{}_BASE_ADDR"
INBOUND0_START = smc_indexed_addr(_INB.format("START_ADDR"), 0)
INBOUND0_END = smc_indexed_addr(_INB.format("END_ADDR"), 0)
INBOUND0_CONFIG = smc_indexed_addr(_INB.format("FILTER_CONFIG"), 0)
OUTBOUND1_CONFIG = smc_indexed_addr(_OUTB.format("FILTER_CONFIG"), 1)
OUTBOUND1_START = smc_indexed_addr(_OUTB.format("START_ADDR"), 1)
INBOUND_PASS_ALL_END = 0x00FF_FFFF_FFFF_FFFF
INBOUND_CONFIG_RESET = 0x3000
INBOUND_START_RESET = 0x0
INBOUND_END_RESET = 0x7

CHIP_CONFIG = tuple(
    (name, smc_addr(f"SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_{name}_BASE_ADDR"))
    for name in ("VERSION_LO", "VERSION_HI", "CHIP_ID", "LC_STATE")
)


def scratch_cold(index: int) -> int:
    return smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", index)


def scratch_word(index: int) -> int:
    return 0xC0DE_0100 + index


SPM = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR")
W0 = SPM + 0x4_0000
LONG_BASE = SPM + 0x5_0000
BEAT_BYTES = 8
BURST_LENGTHS = (2, 4, 16)
BURST_OFFSETS = {2: 0x100, 4: 0x200, 16: 0x400}
LONG_BEATS = 256

# (port key, window, single word, beat prefix)
PORTS = (
    ("SEP", W0, 0x0123_4567_89AB_CDEF, 0xB0),
    ("SYS", W0 + 0x1000, 0xFEDC_BA98_7654_3210, 0xB1),
    ("JTAG", W0 + 0x2000, 0xA5A5_5A5A_C3C3_3C3C, 0xB2),
)
PREFIX = {"SEP": "s_axi", "SYS": "sys_axi", "JTAG": "jtag_axi"}
BUS_NAME = {"SEP": "SEP_IN AXI", "SYS": "SYS_IN AXI", "JTAG": "JTAG AXI"}


def burst_beat(prefix: int, n: int, i: int) -> int:
    return (prefix << 56) | (n << 40) | (i << 32) | 0xC0DE_0000 | i


def burst_payload(prefix: int, n: int) -> int:
    return sum(burst_beat(prefix, n, i) << (64 * i) for i in range(n))


def long_beat(i: int) -> int:
    return (0xB3 << 56) | (i << 32) | 0xC0DE_0000 | i


LONG_PAYLOAD = sum(long_beat(i) << (64 * i) for i in range(LONG_BEATS))

# Accesses per port: one word write and read, then per burst a write, two single reads and a
# burst read.
PORT_WINDOW_ACCESSES = 2 + 4 * len(BURST_LENGTHS)
SEP_SETUP_ACCESSES = 3 + 4 + len(CHIP_CONFIG)
SEP_TEARDOWN_ACCESSES = 3 + 4
EXPECTED_ACCESSES = {
    "SEP": SEP_SETUP_ACCESSES + PORT_WINDOW_ACCESSES + 2 + 2 + 1 + 4 + SEP_TEARDOWN_ACCESSES,
    "SYS": PORT_WINDOW_ACCESSES,
    "JTAG": PORT_WINDOW_ACCESSES,
}

STEP_IDS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9")
CHECKERS = (
    ("CHK-IPB-WIDTH-ROUNDTRIP", "S4"),
    ("CHK-IPB-INCR-MEMORY", "S4"),
    ("CHK-IPB-INCR-256", "S5"),
    ("CHK-IPB-INCR-REG-OBS", "S7"),
    ("CHK-IPB-REJECT-READ-OBS", "S8"),
    ("CHK-IPB-REJECT-RECOVERY", "S8"),
)


def _beats(value: int, n: int, width: int = BEAT_BYTES) -> list[int]:
    mask = (1 << (8 * width)) - 1
    return [(value >> (8 * width * i)) & mask for i in range(n)]


class _PortWatch:
    """Records the beat count of every R burst of one port and, on SYS_IN, the filter probes."""

    def __init__(self, prefix: str, filter_probes: bool) -> None:
        self.dut = cocotb.top
        self.prefix = prefix
        self.filter_probes = filter_probes
        self.stop = False
        self.beats = 0
        self.bursts: list[int] = []
        self.write_hit_cycles = 0
        self.read_hit_cycles = 0
        self.isolate_cycles = 0
        self.errors: list[str] = []

    def _sample(self, name: str) -> int | None:
        value = getattr(self.dut, name).value
        if not value.is_resolvable:
            self.errors.append(f"{name} is X/Z ({value})")
            return None
        return int(value)

    async def run(self) -> None:
        while not self.stop:
            await RisingEdge(self.dut.clk_smc_i)
            await ReadOnly()
            valid = self._sample(f"{self.prefix}_rvalid")
            ready = self._sample(f"{self.prefix}_rready")
            if valid == 1 and ready == 1:
                self.beats += 1
                if self._sample(f"{self.prefix}_rlast") == 1:
                    self.bursts.append(self.beats)
                    self.beats = 0
            if self.filter_probes:
                self.write_hit_cycles += bool(self._sample("tb_inb_write_hit"))
                self.read_hit_cycles += bool(self._sample("tb_inb_read_hit"))
                self.isolate_cycles += bool(
                    self._sample("tb_inb_isolate_write") or self._sample("tb_inb_isolate_read")
                )


class smc_axi_inbound_ports_burst_test_seq(SmcCsrSeq):
    """Round trips and INCR bursts on SEP_IN, SYS_IN and JTAG, plus register-island bursts."""

    def __init__(self, name: str = "smc_axi_inbound_ports_burst_test_seq") -> None:
        super().__init__(name)
        self.port_accesses = {"SEP": 0, "SYS": 0, "JTAG": 0}
        self.stamps: list[tuple[str, int]] = []
        self.chk_marks: list[tuple[str, int]] = []
        self.axi_last = "none"
        self.watches: dict[str, _PortWatch] = {}

    def _mark_step(self, step_id: str) -> None:
        self.stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self.chk_marks.append((chk_id, int(get_sim_time("ps"))))

    async def _axi(
        self,
        port: str,
        label: str,
        op: SmcSysAxiOp,
        addr: int,
        *,
        length: int = BEAT_BYTES,
        beats: int = 1,
        burst: int = BURST_INCR,
        wdata: int = 0,
        wstrb: int | None = None,
        expected: int | None = None,
        allow_error: bool = False,
    ) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"{port.lower()}_{label}")
        item.op = op
        item.addr = addr
        item.length = length
        item.beats = beats
        item.burst = burst
        item.wdata = wdata
        item.wstrb = wstrb
        item.expected = expected
        item.allow_error = allow_error
        if port == "SEP":
            await self.start_item(item)
            await self.finish_item(item)
            self.accesses += 1
        else:
            agent = self.env.sys_in_axi_agent if port == "SYS" else self.env.jtag_axi_agent
            await _OneShot(item, f"{port.lower()}_{label}_os").start(agent.sequencer)
        self.port_accesses[port] += 1
        self.axi_last = f"{port} {label} @0x{addr:x} resp={_RESP_NAME.get(item.resp_code)}"
        return item

    async def _okay_write(self, port: str, label: str, addr: int, data: int, **kw) -> None:
        item = await self._axi(port, label, SmcSysAxiOp.WRITE, addr, wdata=data, **kw)
        assert item.resp_code == RESP_OKAY, f"{self.axi_last}: write not OKAY"

    async def _okay_read(
        self,
        port: str,
        label: str,
        addr: int,
        expected: int,
        length: int = BEAT_BYTES,
        beats: int = 1,
    ) -> int:
        item = await self._axi(
            port, label, SmcSysAxiOp.READ, addr, length=length, beats=beats, expected=expected
        )
        assert item.resp_code == RESP_OKAY, f"{self.axi_last}: read not OKAY"
        assert item.rdata == expected, (
            f"{self.axi_last}: read 0x{item.rdata:x}, want 0x{expected:x}"
        )
        return item.rdata

    async def _read_burst(self, port: str, label: str, addr: int, expected: int, n: int) -> None:
        watch = self.watches[port]
        before = len(watch.bursts)
        await self._okay_read(port, label, addr, expected, beats=n)
        assert watch.bursts[before:] == [n], (
            f"{self.axi_last}: R bursts observed {watch.bursts[before:]}, want one of {n} beats "
            f"with RLAST on beat {n}"
        )

    async def _window(self, port: str, window: int, word: int, prefix: int) -> dict:
        await self._okay_write(port, "word_wr", window, word, wstrb=0xFF)
        got = await self._okay_read(port, "word_rd", window, word)
        out = {"word": got, "bursts": {}}
        for n in BURST_LENGTHS:
            base = window + BURST_OFFSETS[n]
            payload = burst_payload(prefix, n)
            await self._okay_write(port, f"incr{n}_wr", base, payload, beats=n)
            first = await self._okay_read(port, f"incr{n}_first", base, burst_beat(prefix, n, 0))
            last = await self._okay_read(
                port, f"incr{n}_last", base + (n - 1) * BEAT_BYTES, burst_beat(prefix, n, n - 1)
            )
            await self._read_burst(port, f"incr{n}_rd", base, payload, n)
            out["bursts"][n] = (first, last)
        return out

    def _probe_rdata(self, label: str, item: SmcSysAxiItem, n: int, width: int) -> str:
        assert item.resp_code is not None and item.rdata is not None, (
            f"{self.axi_last}: read returned no response data"
        )
        beats = ",".join(f"0x{b:0{2 * width}x}" for b in _beats(item.rdata, n, width))
        return f"{label} resp={_RESP_NAME.get(item.resp_code)} beats=[{beats}]"

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done(FUSE_SENSE_MAX_SMC_CYCLES)
        fuse_state = (
            f"tb_fuse_sense_done={int(dut.tb_fuse_sense_done.value)} "
            f"tb_fuse_reset_n={int(dut.tb_fuse_reset_n.value)} "
            f"tb_rst_warm_smc_clk_n={int(dut.tb_rst_warm_smc_clk_n.value)}"
        )
        self.watches = {
            "SEP": _PortWatch("s_axi", False),
            "SYS": _PortWatch("sys_axi", True),
            "JTAG": _PortWatch("jtag_axi", False),
        }
        tasks = [cocotb.start_soon(w.run()) for w in self.watches.values()]
        monitor = self.env.axi_monitor

        # S1
        await self._okay_write("SEP", "inb_start", INBOUND0_START, 0x0)
        await self._okay_write("SEP", "inb_end", INBOUND0_END, INBOUND_PASS_ALL_END)
        await self._okay_write("SEP", "inb_config", INBOUND0_CONFIG, PASS_ALL_CONFIG)
        for i in range(4):
            await self._okay_write(
                "SEP", f"scratch{i}_wr", scratch_cold(i), scratch_word(i), length=4
            )
        chip = []
        for name, addr in CHIP_CONFIG:
            item = await self._axi("SEP", f"chip_{name}", SmcSysAxiOp.READ, addr, length=4)
            assert item.resp_code == RESP_OKAY, f"{self.axi_last}: CHIP_CONFIG read not OKAY"
            chip.append(f"{name}=0x{item.rdata:08x}")
        self._mark_step("S1")
        cocotb.log.info("IPB setup: CHIP_CONFIG read-only words %s", " ".join(chip))

        # S2 - S4
        windows = {}
        for step, (port, window, word, prefix) in zip(("S2", "S3", "S4"), PORTS):
            windows[port] = await self._window(port, window, word, prefix)
            self._mark_step(step)
        sys_watch = self.watches["SYS"]
        assert not sys_watch.errors, f"SYS_IN probes unresolved: {sys_watch.errors[:3]}"
        self._log_chk(
            "CHK-IPB-WIDTH-ROUNDTRIP",
            " ".join(
                f"{p}: 8-byte wstrb 0xFF write OKAY, read 0x{windows[p]['word']:016x} OKAY"
                for p, *_ in PORTS
            )
            + f"; SYS_IN inbound filter write_hit cycles={sys_watch.write_hit_cycles}"
            f" read_hit cycles={sys_watch.read_hit_cycles}"
            f" isolate cycles={sys_watch.isolate_cycles}",
        )
        self._log_chk(
            "CHK-IPB-INCR-MEMORY",
            " ".join(
                f"{p}: "
                + ",".join(
                    f"n={n} first=0x{first:016x} last=0x{last:016x}"
                    for n, (first, last) in windows[p]["bursts"].items()
                )
                + " whole-burst reads in order with RLAST on the last beat"
                for p, *_ in PORTS
            ),
        )

        # S5
        await self._okay_write("SEP", "incr256_wr", LONG_BASE, LONG_PAYLOAD, beats=LONG_BEATS)
        await self._read_burst("SEP", "incr256_rd", LONG_BASE, LONG_PAYLOAD, LONG_BEATS)
        self._mark_step("S5")
        self._log_chk(
            "CHK-IPB-INCR-256",
            f"AxLEN=255 INCR write at 0x{LONG_BASE:x} then 256-beat read returned all {LONG_BEATS}"
            f" beats equal in order, first=0x{long_beat(0):016x} last="
            f"0x{long_beat(LONG_BEATS - 1):016x}, OKAY, RLAST on beat {LONG_BEATS}",
        )

        # S6
        for addr in (scratch_cold(0), OUTBOUND1_CONFIG, OUTBOUND1_START):
            monitor.expected_decerr_addrs.add(addr)
        s6a = await self._axi(
            "SEP",
            "incr4x4_scratch",
            SmcSysAxiOp.READ,
            scratch_cold(0),
            length=4,
            beats=4,
            allow_error=True,
        )
        s6b = await self._axi(
            "SEP",
            "incr3x8_filter",
            SmcSysAxiOp.READ,
            OUTBOUND1_CONFIG,
            beats=3,
            allow_error=True,
        )
        s6_text = (
            self._probe_rdata("4x4B@SCRATCH_COLD(0)", s6a, 4, 4)
            + " "
            + self._probe_rdata("3x8B@OUTBOUND_FILTER_CONFIG(1)", s6b, 3, 8)
        )
        self._mark_step("S6")

        # S7
        past_extent = OUTBOUND1_CONFIG + 3 * BEAT_BYTES
        monitor.expected_decerr_addrs.add(past_extent)
        s7 = await self._axi(
            "SEP",
            "incr4x8_crossing",
            SmcSysAxiOp.READ,
            OUTBOUND1_CONFIG,
            beats=4,
            allow_error=True,
        )
        s7_text = self._probe_rdata("4x8B@OUTBOUND_FILTER_CONFIG(1)", s7, 4, 8)
        self._mark_step("S7")
        self._log_chk(
            "CHK-IPB-INCR-REG-OBS",
            f"observe-only, nothing asserted on codes or beats, all three reads completed within"
            f" {AXI_GUARD_NS} ns: {s6_text} {s7_text} past_extent=0x{past_extent:x}",
        )

        # S8
        reject = {}
        control = {}
        for label, burst, addr in (
            ("fixed", BURST_FIXED, OUTBOUND1_START),
            ("wrap", BURST_WRAP, OUTBOUND1_CONFIG),
        ):
            item = await self._axi(
                "SEP",
                f"{label}_rd",
                SmcSysAxiOp.READ,
                addr,
                beats=4,
                burst=burst,
                allow_error=True,
            )
            reject[label] = self._probe_rdata(f"{label.upper()} 4x8B@0x{addr:x}", item, 4, 8)
            ctl = await self._axi(
                "SEP",
                f"{label}_control",
                SmcSysAxiOp.READ,
                scratch_cold(3),
                length=4,
                expected=scratch_word(3),
            )
            control[label] = ctl
            assert ctl.resp_code == RESP_OKAY and ctl.rdata == scratch_word(3), (
                f"{self.axi_last}: control read 0x{ctl.rdata:x}, want 0x{scratch_word(3):x} OKAY"
            )
        self._mark_step("S8")
        self._log_chk(
            "CHK-IPB-REJECT-READ-OBS",
            f"observe-only, nothing asserted, both bursts completed within {AXI_GUARD_NS} ns: "
            f"{reject['fixed']} {reject['wrap']}",
        )
        self._log_chk(
            "CHK-IPB-REJECT-RECOVERY",
            f"SCRATCH_COLD(3) read 0x{control['fixed'].rdata:08x} OKAY after the FIXED read and "
            f"0x{control['wrap'].rdata:08x} OKAY after the WRAP read",
        )

        # S9
        await self._okay_write("SEP", "inb_config_restore", INBOUND0_CONFIG, INBOUND_CONFIG_RESET)
        await self._okay_write("SEP", "inb_start_restore", INBOUND0_START, INBOUND_START_RESET)
        await self._okay_write("SEP", "inb_end_restore", INBOUND0_END, INBOUND_END_RESET)
        for i in range(4):
            await self._okay_write("SEP", f"scratch{i}_restore", scratch_cold(i), 0, length=4)
        self._mark_step("S9")

        for watch in self.watches.values():
            watch.stop = True
        for task in tasks:
            await task
        for port, watch in self.watches.items():
            assert not watch.errors, f"{port} R-channel probes unresolved: {watch.errors[:3]}"
            assert watch.beats == 0, f"{port}: {watch.beats} R beats left without RLAST"

        self.assert_all_reachable(EXPECTED_ACCESSES["SEP"], "SEP_IN burst traffic")
        by_bus = self.env.scoreboard.axi_accesses_by_bus
        for port, expect in EXPECTED_ACCESSES.items():
            assert self.port_accesses[port] == expect, (
                f"{port}: issued {self.port_accesses[port]} accesses, expected {expect}"
            )
            measured = by_bus.get(BUS_NAME[port], 0)
            assert measured == expect, (
                f"scoreboard booked {measured} {BUS_NAME[port]} accesses, expected {expect}"
            )
        self._nonvac_fence(fuse_state)

    def _nonvac_fence(self, fuse_state: str) -> None:
        ids = tuple(s for s, _ in self.stamps)
        assert ids == STEP_IDS, f"step ids {ids}, want {STEP_IDS}"
        times = [t for _, t in self.stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"step stamps not increasing: {times}"
        assert tuple(c for c, _ in self.chk_marks) == tuple(c for c, _ in CHECKERS), (
            f"checker lines {[c for c, _ in self.chk_marks]}"
        )
        stamp_of = dict(self.stamps)
        marks = [t for _, t in self.chk_marks]
        assert marks == sorted(marks), f"checker lines out of order: {marks}"
        for (chk_id, when), (_, step) in zip(self.chk_marks, CHECKERS):
            assert when >= stamp_of[step], f"{chk_id} printed before its step {step} stamp"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s; accesses %s",
            "<".join(STEP_IDS),
            ",".join(c for c, _ in self.chk_marks),
            ",".join(f"{s}={t}" for s, t in self.stamps),
            ",".join(f"{p}={n}" for p, n in self.port_accesses.items()),
        )
        total = sum(self.port_accesses.values())
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: bounded waits: wait_fuse_sense_done.tb_fuse_sense_done bound="
            "%d clk_smc_i; wait_fuse_sense_done.tb_fuse_reset_n bound=%d clk_smc_i; "
            "wait_fuse_sense_done.tb_rst_warm_smc_clk_n bound=%d clk_smc_i (last state %s); "
            "AXI accesses %d (SEP_IN %d, SYS_IN %d, JTAG %d) each bound=%d ns allow_timeout=False "
            "(last access %s); R-channel watch tasks joined after one clk_smc_i edge each; "
            "no responder polls, no other waits",
            FUSE_SENSE_MAX_SMC_CYCLES,
            FUSE_SENSE_MAX_SMC_CYCLES,
            FUSE_SENSE_MAX_SMC_CYCLES,
            fuse_state,
            total,
            self.port_accesses["SEP"],
            self.port_accesses["SYS"],
            self.port_accesses["JTAG"],
            AXI_GUARD_NS,
            self.axi_last,
        )
