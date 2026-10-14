# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Manager-side channel skew and ready timing on SEP_IN, SYS_IN and JTAG.

Spec sources: fabric.adoc Topology and Configuration Parameters, scratch.rdl SCRATCH sw=rw.

Every port takes the same traffic shapes against SCRATCH_COLD and the SPM, each read back
through the port that wrote it. A clocked watch per port counts handshakes and stalls, so
the stimulus is shown to have reached the bus.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp
from ocah_axi_vip import AxiTimingProfile

from ._one_shot import _OneShot
from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import (
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    PASS_ALL_CONFIG,
)

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    FILTER_CTRL_END_ADDR_REG_DEFAULT,
    FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
    FILTER_CTRL_START_ADDR_REG_DEFAULT,
)

FUSE_WAIT_BOUND_SMC_CYCLES = 200_000
AXI_TIMEOUT_NS = 50_000
# Bound, in clk_smc_i rises, of each wait of the r_hold pulse driver.
HOLD_WAIT_BOUND_CYCLES = 2000
HOLD_CYCLES = 8
RESP_OKAY = 0
PASS_ALL_END = 0x00FF_FFFF_FFFF_FFFF

SPM_BASE = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR")
W0 = SPM_BASE + 0x7_0000
SCRATCH_SYMBOL = "SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR"
SCRATCH_COUNT = 8

SKEW = 4
QUEUE_W_DELAY = 16
B_HOLD = 64
R_HOLD = 32
BURST_BEATS = 8
READ_BEATS = 4
GROUP_WORDS = 8
RANDOM_MAX_DELAY = 8

PORTS = ("SEP_IN", "SYS_IN", "JTAG")
_PREFIX = {"SEP_IN": "s_axi", "SYS_IN": "sys_axi", "JTAG": "jtag_axi"}
_BUS_NAME = {"SEP_IN": "SEP_IN AXI", "SYS_IN": "SYS_IN AXI", "JTAG": "JTAG AXI"}
_R_HOLD_KNOB = {"SEP_IN": "tb_sep_axi_r_hold", "SYS_IN": "tb_sys_axi_r_hold"}
_R_RAW_VALID = {"SEP_IN": "tb_sep_axi_r_raw_valid", "SYS_IN": "tb_sys_axi_r_raw_valid"}

STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10")
CHECKERS = (
    ("CHK-CTP-W-FIRST", "S3"),
    ("CHK-CTP-AW-FIRST", "S5"),
    ("CHK-CTP-AW-QUEUE", "S6"),
    ("CHK-CTP-BREADY-PORTS", "S7"),
    ("CHK-CTP-RREADY-BEATS", "S8"),
    ("CHK-CTP-RANDOM-STALLS", "S9"),
)

# Accesses per port: SEP_IN also carries the setup and teardown register writes.
SEP_IN_SETUP_ACCESSES = 3
SEP_IN_TEARDOWN_ACCESSES = SCRATCH_COUNT + 3
PER_PORT_ACCESSES = {
    "SEP_IN": 2 + 2 + 2 + 2 + 8 + 16 + 1 + 56,
    "SYS_IN": 2 + 2 + 16 + 1 + 56,
    "JTAG": 2 + 2 + 16 + 1 + 56,
}


def scratch(index: int) -> int:
    return smc_indexed_addr(SCRATCH_SYMBOL, index)


def burst_beat(prefix: int, index: int) -> int:
    return (prefix << 56) | (index << 32) | 0xC0DE_0000 | index


def burst_word(prefix: int) -> int:
    """The whole burst, first beat in the low bytes."""
    return sum(burst_beat(prefix, i) << (64 * i) for i in range(BURST_BEATS))


def group_word(tag: int, port_index: int, index: int) -> int:
    """Distinct 8-byte word per tag, port and index."""
    return (tag << 56) | (port_index << 48) | (index << 32) | 0xC0DE_0000 | (tag << 8) | index


class _Window:
    """Handshake record of one port between two `begin()` calls."""

    def __init__(self, start_cycle: int, stalls: dict[str, int]) -> None:
        self.start_cycle = start_cycle
        self.stall_base = dict(stalls)
        self.aw_first: int | None = None
        self.w_first: int | None = None
        self.aw_hs = 0
        self.w_hs = 0
        self.b_hs = 0
        self.aw_before_first_w: int | None = None
        self.r_last: list[int] = []


class _PortWatch:
    """Observer of one port's five channels, sampled at the falling edge.

    Where the bench gates R (SEP_IN, SYS_IN) an R stall cycle is the DUT's raw R valid high
    without a handshake, since the gate hides RVALID from the manager while it holds.

    Every drive that can gate a handshake settles by the falling edge, so a sample with
    VALID and READY high is a handshake at the next rising edge.
    """

    CHANNELS = ("aw", "w", "ar", "b", "r")

    def __init__(
        self, dut, prefix: str, track_filter: bool = False, raw_r_valid: str | None = None
    ) -> None:
        self.dut = dut
        self.prefix = prefix
        self.raw_r_valid = raw_r_valid
        self.track_filter = track_filter
        self.stop = False
        self.cycle = 0
        self.unresolved = 0
        self.stalls = {name: 0 for name in self.CHANNELS}
        self.filter_seen = {"write_hit": 0, "read_hit": 0, "isolate_write": 0, "isolate_read": 0}
        self.win = _Window(0, self.stalls)

    def begin(self) -> _Window:
        self.win = _Window(self.cycle, self.stalls)
        return self.win

    def stalled(self, win: _Window, channel: str) -> int:
        return self.stalls[channel] - win.stall_base[channel]

    def _read(self, name: str) -> int | None:
        value = getattr(self.dut, name).value
        if not value.is_resolvable:
            self.unresolved += 1
            return None
        return int(value)

    async def run(self) -> None:
        while not self.stop:
            await FallingEdge(self.dut.clk_smc_i)
            await ReadOnly()
            self.cycle += 1
            win = self.win
            state = {}
            for channel in self.CHANNELS:
                valid = self._read(f"{self.prefix}_{channel}valid")
                ready = self._read(f"{self.prefix}_{channel}ready")
                state[channel] = (valid, ready)
                if channel == "r" and self.raw_r_valid is not None:
                    raw = self._read(self.raw_r_valid)
                    if raw == 1 and (valid, ready) != (1, 1):
                        self.stalls[channel] += 1
                elif valid == 1 and ready == 0:
                    self.stalls[channel] += 1
            if state["aw"][0] == 1 and win.aw_first is None:
                win.aw_first = self.cycle
            if state["w"][0] == 1 and win.w_first is None:
                win.w_first = self.cycle
            if state["w"] == (1, 1) and win.w_hs == 0:
                win.aw_before_first_w = win.aw_hs
            if state["aw"] == (1, 1):
                win.aw_hs += 1
            if state["w"] == (1, 1):
                win.w_hs += 1
            if state["b"] == (1, 1):
                win.b_hs += 1
            if state["r"] == (1, 1):
                win.r_last.append(self._read(f"{self.prefix}_rlast"))
            if self.track_filter:
                for name in self.filter_seen:
                    seen = self._read(f"tb_inb_{name}")
                    if seen:
                        self.filter_seen[name] |= seen


def _item(
    label: str,
    op: SmcSysAxiOp,
    addr: int,
    *,
    length: int = 4,
    beats: int = 1,
    wdata: int = 0,
    expected: int | None = None,
    timing: AxiTimingProfile | None = None,
) -> SmcSysAxiItem:
    item = SmcSysAxiItem(f"{op.value}_{label}")
    item.op = op
    item.addr = addr
    item.length = length
    item.beats = beats
    item.wdata = wdata
    item.expected = expected
    item.timing = timing
    return item


class smc_axi_channel_timing_ports_test_seq(SmcCsrSeq):
    """Skew, hold and randomly stall the channels of the three inbound ports."""

    def __init__(self, name: str = "smc_axi_channel_timing_ports_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self.fuse_state = "not waited"
        self.read_checks = 0
        self.watches: dict[str, _PortWatch] = {}
        self.hold_waits: dict[str, str] = {}
        self.seed = 0
        self.drawn: list[str] = []

    # -- bookkeeping -----------------------------------------------------

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    def _sequencer(self, port: str):
        agents = {
            "SEP_IN": self.env.sys_axi_agent,
            "SYS_IN": self.env.sys_in_axi_agent,
            "JTAG": self.env.jtag_axi_agent,
        }
        return agents[port].sequencer

    # -- primitives ------------------------------------------------------

    @staticmethod
    def _check_done(port: str, item: SmcSysAxiItem) -> None:
        assert not item.timed_out, f"{port} {item.get_name()} @ 0x{item.addr:x} timed out"
        assert item.resp_code == RESP_OKAY, (
            f"{port} {item.get_name()} @ 0x{item.addr:x}: response {item.resp_code}, want OKAY"
        )
        if item.op is SmcSysAxiOp.READ and item.expected is not None:
            mask = (1 << (8 * item.transfer_bytes)) - 1
            assert item.rdata & mask == item.expected & mask, (
                f"{port} {item.get_name()} @ 0x{item.addr:x}: read 0x{item.rdata & mask:x}, "
                f"want 0x{item.expected & mask:x}"
            )

    def _count(self, item: SmcSysAxiItem) -> None:
        self.accesses += 1
        if item.op is SmcSysAxiOp.READ and item.expected is not None:
            self.read_checks += 1

    async def _issue(self, port: str, item: SmcSysAxiItem) -> SmcSysAxiItem:
        if port == "SEP_IN":
            await self.start_item(item)
            await self.finish_item(item)
        else:
            await _OneShot(item, f"{port}_{item.get_name()}_os").start(self._sequencer(port))
        self._count(item)
        self._check_done(port, item)
        return item

    async def _issue_group(
        self,
        port: str,
        name: str,
        items: list[SmcSysAxiItem],
        timing: AxiTimingProfile | None = None,
    ) -> None:
        group = SmcSysAxiGroupItem(f"{port}_{name}", items, timing=timing)
        if port == "SEP_IN":
            await self.start_item(group)
            await self.finish_item(group)
        else:
            await _OneShot(group, f"{port}_{name}_os").start(self._sequencer(port))
        for item in items:
            self._count(item)
            self._check_done(port, item)

    async def _write(self, port, label, addr, data, *, length=4, beats=1, timing=None):
        return await self._issue(
            port,
            _item(
                label,
                SmcSysAxiOp.WRITE,
                addr,
                length=length,
                beats=beats,
                wdata=data,
                timing=timing,
            ),
        )

    async def _read(self, port, label, addr, expected, *, length=4, beats=1, timing=None):
        return await self._issue(
            port,
            _item(
                label,
                SmcSysAxiOp.READ,
                addr,
                length=length,
                beats=beats,
                expected=expected,
                timing=timing,
            ),
        )

    @staticmethod
    def _lead(win: _Window) -> str:
        assert win.aw_first is not None and win.w_first is not None, "no AW or W observed"
        return f"aw_valid-w_valid={win.aw_first - win.w_first}"

    # -- r_hold pulses ---------------------------------------------------

    async def _pulse_r_hold(self, port: str, beats: int) -> None:
        """Hold R off for HOLD_CYCLES cycles once each beat is visible at the DUT.

        Samples are the settled state after each clk_smc_i rise; the hold is driven on the
        falling edge, so it lands before the handshake the sampled state would complete.
        """
        dut = cocotb.top
        clk = dut.clk_smc_i
        hold = getattr(dut, _R_HOLD_KNOB[port])
        raw = getattr(dut, _R_RAW_VALID[port])
        prefix = _PREFIX[port]
        rvalid = getattr(dut, f"{prefix}_rvalid")
        rready = getattr(dut, f"{prefix}_rready")
        waited = []
        try:
            for beat in range(beats):
                for valid_wait in range(HOLD_WAIT_BOUND_CYCLES):
                    await RisingEdge(clk)
                    await ReadOnly()
                    assert raw.value.is_resolvable, f"{_R_RAW_VALID[port]} is X/Z"
                    if int(raw.value) == 1:
                        break
                else:
                    raise AssertionError(
                        f"{port} beat {beat}: raw R valid never seen within "
                        f"{HOLD_WAIT_BOUND_CYCLES} cycles"
                    )
                await FallingEdge(clk)
                hold.value = 1
                await ClockCycles(clk, HOLD_CYCLES)
                hold.value = 0
                for accept_wait in range(HOLD_WAIT_BOUND_CYCLES):
                    await ReadOnly()
                    assert rvalid.value.is_resolvable and rready.value.is_resolvable, (
                        f"{port} rvalid/rready is X/Z"
                    )
                    if int(rvalid.value) == 1 and int(rready.value) == 1:
                        break
                    await RisingEdge(clk)
                else:
                    raise AssertionError(
                        f"{port} beat {beat}: R never accepted within "
                        f"{HOLD_WAIT_BOUND_CYCLES} cycles after the hold"
                    )
                waited.append(f"{valid_wait}+{accept_wait}")
        finally:
            await FallingEdge(clk)
            hold.value = 0
            self.hold_waits[port] = f"beats={len(waited)} wait(valid+accept)={','.join(waited)}"

    # -- steps -----------------------------------------------------------

    async def _step_setup(self) -> None:
        await self.wait_fuse_sense_done(FUSE_WAIT_BOUND_SMC_CYCLES)
        dut = cocotb.top
        states = []
        for name in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"):
            sig = getattr(dut, name)
            assert sig.value.is_resolvable, f"{name} is X/Z after the wait"
            states.append(f"{name}={int(sig.value)}")
        self.fuse_state = ",".join(states)
        await self.csr_write("INBOUND0_START_PASS_ALL", INBOUND0_START, 0x0, length=8)
        await self.csr_write("INBOUND0_END_PASS_ALL", INBOUND0_END, PASS_ALL_END, length=8)
        await self.csr_write(
            "INBOUND0_FILTER_CONFIG_PASS_ALL", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG, length=8
        )
        for port in PORTS:
            self.watches[port] = _PortWatch(
                dut,
                _PREFIX[port],
                track_filter=port == "SYS_IN",
                raw_r_valid=_R_RAW_VALID.get(port),
            )
            cocotb.start_soon(self.watches[port].run())

    async def _scratch_skew(self, label: str, base: int, tag: int, timing_of) -> list[str]:
        notes = []
        for k, port in enumerate(PORTS):
            watch = self.watches[port]
            win = watch.begin()
            word = tag + k
            await self._write(port, f"{label}{k}", scratch(base + k), word, timing=timing_of)
            notes.append(f"{port} {self._lead(win)} wr=OKAY")
            await self._read(port, f"{label}{k}_RB", scratch(base + k), word)
        return notes

    async def _burst_skew(self, label: str, offset: int, prefix: int, timing) -> str:
        watch = self.watches["SEP_IN"]
        win = watch.begin()
        word = burst_word(prefix)
        await self._write(
            "SEP_IN", label, W0 + offset, word, length=8, beats=BURST_BEATS, timing=timing
        )
        lead = self._lead(win)
        await self._read("SEP_IN", f"{label}_RB", W0 + offset, word, length=8, beats=BURST_BEATS)
        return f"SEP_IN {BURST_BEATS}-beat burst {lead} wr=OKAY rd={BURST_BEATS} beats in order"

    async def _step_queue(self) -> str:
        watch = self.watches["SEP_IN"]
        win = watch.begin()
        words = [0xC0DE_3000 + i for i in range(4, 8)]
        items = [
            _item(f"QUEUE_WR{i}", SmcSysAxiOp.WRITE, scratch(i), wdata=0xC0DE_3000 + i)
            for i in range(4, 8)
        ]
        await self._issue_group(
            "SEP_IN", "queue_wr", items, AxiTimingProfile(w_delay=QUEUE_W_DELAY)
        )
        for i in range(4, 8):
            await self._read("SEP_IN", f"QUEUE_RB{i}", scratch(i), words[i - 4])
        assert win.aw_before_first_w is not None, "no W handshake observed on SEP_IN"
        assert win.aw_before_first_w >= 2, (
            f"{win.aw_before_first_w} AW handshake(s) before the first W, want >= 2"
        )
        return (
            f"{win.aw_before_first_w} AW handshakes before the first W handshake "
            f"(aw_hs={win.aw_hs} w_hs={win.w_hs}), 4 writes OKAY, SCRATCH_COLD(4..7) read "
            f"{','.join(f'0x{w:08X}' for w in words)}"
        )

    async def _step_bready(self) -> str:
        notes = []
        for k, port in enumerate(PORTS):
            watch = self.watches[port]
            win = watch.begin()
            base = W0 + 0x1000 * (k + 1)
            words = [group_word(0xC7, k, i) for i in range(GROUP_WORDS)]
            items = [
                _item(f"BHOLD{k}_{i}", SmcSysAxiOp.WRITE, base + 8 * i, length=8, wdata=words[i])
                for i in range(GROUP_WORDS)
            ]
            await self._issue_group(
                port, "bready_hold", items, AxiTimingProfile(b_ready_delay=B_HOLD)
            )
            for i in range(GROUP_WORDS):
                await self._read(port, f"BHOLD{k}_RB{i}", base + 8 * i, words[i], length=8)
            b_stall = watch.stalled(win, "b")
            assert win.b_hs >= GROUP_WORDS, f"{port}: {win.b_hs} B handshakes for 8 writes"
            assert b_stall >= 1, f"{port}: no b-channel stall cycle under the BREADY hold"
            notes.append(f"{port} 8 writes OKAY b_hs={win.b_hs} b_stall={b_stall}")
        return "; ".join(notes) + "; every word read back equals the word written"

    async def _step_rready(self) -> str:
        notes = []
        for k, port in enumerate(PORTS):
            watch = self.watches[port]
            base = W0 + 0x1000 * (k + 1)
            words = [group_word(0xC7, k, i) for i in range(READ_BEATS)]
            expected = sum(w << (64 * i) for i, w in enumerate(words))
            win = watch.begin()
            pulse = None
            if port in _R_HOLD_KNOB:
                pulse = cocotb.start_soon(self._pulse_r_hold(port, READ_BEATS))
            await self._read(
                port,
                f"RHOLD{k}",
                base,
                expected,
                length=8,
                beats=READ_BEATS,
                timing=AxiTimingProfile(r_ready_delay=R_HOLD),
            )
            if pulse is not None:
                await pulse
            r_stall = watch.stalled(win, "r")
            want_last = [0] * (READ_BEATS - 1) + [1]
            assert win.r_last == want_last, f"{port}: RLAST pattern {win.r_last}, want {want_last}"
            assert r_stall >= 1, f"{port}: no r-channel stall cycle under the RREADY hold"
            hold = f" r_hold pulses {self.hold_waits[port]}" if pulse is not None else " no r_hold"
            notes.append(
                f"{port} {READ_BEATS} beats in order rlast={win.r_last} r_stall={r_stall}{hold}"
            )
        return "; ".join(notes)

    async def _step_random(self, rng: random.Random) -> str:
        notes = []
        drawn_aw = drawn_w = drawn_ar = 0
        for k, port in enumerate(PORTS):
            watch = self.watches[port]
            win = watch.begin()
            base = W0 + 0x1000 * (k + 1) + 0x800
            read_base = base + 0x40
            seeds = [group_word(0xC9, k, i) for i in range(GROUP_WORDS)]
            for i in range(GROUP_WORDS):
                await self._write(port, f"SEED{k}_{i}", read_base + 8 * i, seeds[i], length=8)
            for leg, lead in (("A", "aw"), ("B", "w")):
                tag = 0xCA if leg == "A" else 0xCB
                delay = rng.randint(1, RANDOM_MAX_DELAY)
                ar_delay = rng.randint(0, RANDOM_MAX_DELAY)
                timing = AxiTimingProfile(ar_delay=ar_delay, **{f"{lead}_delay": delay})
                drawn_aw += delay if lead == "aw" else 0
                drawn_w += delay if lead == "w" else 0
                drawn_ar += ar_delay
                self.drawn.append(f"{port}.{leg}:{lead}={delay},ar={ar_delay}")
                words = [group_word(tag, k, i) for i in range(GROUP_WORDS)]
                items = [
                    _item(
                        f"RND{k}{leg}_WR{i}",
                        SmcSysAxiOp.WRITE,
                        base + 8 * i,
                        length=8,
                        wdata=words[i],
                    )
                    for i in range(GROUP_WORDS)
                ] + [
                    _item(
                        f"RND{k}{leg}_RD{i}",
                        SmcSysAxiOp.READ,
                        read_base + 8 * i,
                        length=8,
                        expected=seeds[i],
                    )
                    for i in range(GROUP_WORDS)
                ]
                await self._issue_group(port, f"random{leg}", items, timing)
                for i in range(GROUP_WORDS):
                    await self._read(port, f"RND{k}{leg}_RB{i}", base + 8 * i, words[i], length=8)
            notes.append(f"{port} 16 accesses x2 groups OKAY, aw_hs={win.aw_hs}")
        assert drawn_aw > 0 and drawn_w > 0 and drawn_ar > 0, (
            f"a channel was never delayed: aw={drawn_aw} w={drawn_w} ar={drawn_ar}"
        )
        return (
            "; ".join(notes) + f"; every read returned the word of its own address; seed "
            f"{self.seed}; delays {' '.join(self.drawn)}"
        )

    async def _step_teardown(self) -> None:
        for i in range(SCRATCH_COUNT):
            await self.csr_write(f"SCRATCH_COLD_{i}_RESTORE", scratch(i), 0)
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

    # -- body ------------------------------------------------------------

    async def body(self) -> None:
        self.seed = int(cocotb.RANDOM_SEED)
        rng = random.Random(self.seed)
        cocotb.log.info("CTP random seed %d", self.seed)

        await self._step_setup()
        self._mark_step("S1")

        aw_lag = AxiTimingProfile(aw_delay=SKEW)
        w_lag = AxiTimingProfile(w_delay=SKEW)
        w_first = await self._scratch_skew("WFIRST", 0, 0xC0DE_1000, aw_lag)
        self._mark_step("S2")
        burst_w = await self._burst_skew("WFIRST_BURST", 0, 0xC2, aw_lag)
        self._mark_step("S3")
        self._log_chk(
            "CHK-CTP-W-FIRST",
            f"W presented {SKEW} cycles ahead of AW: " + "; ".join(w_first) + f"; {burst_w}; "
            "ordinary reads returned 0xC0DE_1000+k",
        )

        aw_first = await self._scratch_skew("AWFIRST", 3, 0xC0DE_2000, w_lag)
        self._mark_step("S4")
        burst_a = await self._burst_skew("AWFIRST_BURST", 0x400, 0xC3, w_lag)
        self._mark_step("S5")
        self._log_chk(
            "CHK-CTP-AW-FIRST",
            f"AW presented {SKEW} cycles ahead of W: " + "; ".join(aw_first) + f"; {burst_a}; "
            "ordinary reads returned 0xC0DE_2000+k",
        )

        queue = await self._step_queue()
        self._mark_step("S6")
        self._log_chk("CHK-CTP-AW-QUEUE", queue)

        bready = await self._step_bready()
        self._mark_step("S7")
        self._log_chk("CHK-CTP-BREADY-PORTS", f"BREADY held {B_HOLD} cycles: {bready}")

        rready = await self._step_rready()
        self._mark_step("S8")
        self._log_chk("CHK-CTP-RREADY-BEATS", f"RREADY held {R_HOLD} cycles: {rready}")

        random_text = await self._step_random(rng)
        self._mark_step("S9")
        self._log_chk("CHK-CTP-RANDOM-STALLS", random_text)

        await self._step_teardown()
        self._mark_step("S10")

        for watch in self.watches.values():
            watch.stop = True
        await ClockCycles(cocotb.top.clk_smc_i, 2)
        for port, watch in self.watches.items():
            assert watch.unresolved == 0, f"{port}: {watch.unresolved} X/Z probe samples"

    # -- evidence --------------------------------------------------------

    def check_scoreboard(self) -> str:
        sb = self.env.scoreboard
        per_bus = {}
        for port in PORTS:
            done = sb.axi_accesses_by_bus.get(_BUS_NAME[port], 0)
            want = PER_PORT_ACCESSES[port] + (
                SEP_IN_SETUP_ACCESSES + SEP_IN_TEARDOWN_ACCESSES if port == "SEP_IN" else 0
            )
            assert done == want, f"{port}: scoreboard completed {done} accesses, want {want}"
            per_bus[port] = done
        assert sb.sys_axi_value_checks_seen >= self.read_checks, (
            f"scoreboard booked {sb.sys_axi_value_checks_seen} exact-value compares for "
            f"{self.read_checks} reads with an expectation"
        )
        return (
            f"scoreboard accesses {per_bus} value_checks={sb.sys_axi_value_checks_seen} "
            f">= {self.read_checks} expected reads"
        )

    def log_timeout_paths(self) -> None:
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: wait_fuse_sense_done sub-waits tb_fuse_sense_done, "
            "tb_fuse_reset_n, tb_rst_warm_smc_clk_n each bounded %d clk_smc_i rises, last "
            "observed %s; r_hold pulse driver waits (raw R valid, R accept) each bounded %d "
            "clk_smc_i rises per beat, last observed %s; port watch stop wait 2 clk_smc_i "
            "rises, watch tasks %s; %d AXI accesses each bounded by the driver timeout %d ns "
            "(allow_timeout False), all answered; no other wait",
            FUSE_WAIT_BOUND_SMC_CYCLES,
            self.fuse_state,
            HOLD_WAIT_BOUND_CYCLES,
            self.hold_waits,
            {port: f"unresolved={w.unresolved}" for port, w in self.watches.items()},
            self.accesses,
            AXI_TIMEOUT_NS,
        )

    def nonvac_fence(self, floor: int) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == STEPS, f"step ids {ids}, want {STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"step stamps not increasing: {times}"
        chk_ids = tuple(c for c, _ in self._chk_marks)
        want = tuple(c for c, _ in CHECKERS)
        assert chk_ids == want, f"checker lines {chk_ids}, want {want}"
        stamp_of = dict(self._stamps)
        for (chk_id, when), (_cid, step) in zip(self._chk_marks, CHECKERS):
            assert when >= stamp_of[step], f"{chk_id} printed before its step {step} stamp"
        assert self.accesses >= floor, f"{self.accesses} accesses, floor {floor}"
        booked = self.check_scoreboard()
        cocotb.log.info(
            "CHK-NONVAC: ordered fence S1<S2<S3<S4<S5<S6<S7<S8<S9<S10; checker lines %s; "
            "accesses %d >= floor %d; %s; stamps %s",
            ",".join(chk_ids),
            self.accesses,
            floor,
            booked,
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
