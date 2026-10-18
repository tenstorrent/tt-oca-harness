# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Outbound filter entries match AxPROT[1], burst admission and a wildcard source ID.

Spec sources: axi_filter index.adoc (Match Then Permit), fabric.adoc (Non-Secure Bit Filtering,
AXI Protection Bit Encoding), filter_ctrl.rdl FILTER_CONFIG, output_remap.rdl.

Outbound entries 1..3 are programmed over SEP_IN and JTAG writes follow with chosen AxPROT, burst
length and window addresses. A deny entry that matches answers DECERR, leaves the SYS_OUT words at
their sentinel and raises no AW or W beat at SYS_OUT; a write no entry matches answers OKAY, lands
and presents the driven AxPROT and AxLEN at the AW handshake. Every entry and remap region is
written back to its reset word at the end.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import _REPO, reg_field_encode, reg_reset_word, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import (
    BLOCKED_WRITE_HOLD_CYCLES,
    RESP_DECERR,
    RESP_OKAY,
    RESPONDER_OBS_TIMEOUT_CYCLES,
    check_output_responder_delta,
    hold_output_responder_writes,
    output_responder_counts,
)
from .smc_rdl_regmap import rdl_contract

_FILTER_H = _REPO / "hw" / "ip" / "axi_filter" / "regs" / "gen" / "c" / "filter_ctrl.h"
_REMAP_H = _REPO / "hw" / "ip" / "output_remap" / "regs" / "gen" / "c" / "output_remap.h"
_REMAP_RESET = reg_reset_word(_REMAP_H, "OUTPUT_REMAP", "OUTPUT_REMAP_REGION__REGION_ATTRS")
_SENTINEL = 0x5A5A_5A5A_5A5A_5A5A
_WORD = 8
_FUSE_BOUND = 200_000
_AXI_TIMEOUT_NS = 50_000
_SEP_FLOOR = 90
_JTAG_COUNT = 25
_ENTRIES = (1, 2, 3)


def _config(**fields: int) -> int:
    return reg_field_encode(_FILTER_H, "FILTER_CTRL", "FILTER_CONFIG", **fields)


DENY_NS0_B1 = _config(entry_enabled=1, allow_burst=1)
DENY_NS1_B1 = _config(entry_enabled=1, allow_ns=1, allow_burst=1)
PERMIT_NS0_B1 = _config(read_allowed=1, write_allowed=1, entry_enabled=1, allow_burst=1)
DENY_B0 = _config(entry_enabled=1)
DENY_B1 = DENY_NS0_B1
DENY_B1_GRP7 = _config(entry_enabled=1, allow_burst=1, group_id=7)
DISABLED = 0

_NS_RANGE = (0x0200_4000, 0x0200_4FFF)
_B0_RANGE = (0x0200_6000, 0x0200_6007)
_B1_RANGE = (0x0200_7000, 0x0200_7FFF)
_B1_NARROW = (0x0200_7000, 0x0200_7007)
_WILD = (
    (0x0200_A000, 0x0200_AFFF),
    (0x0240_0000, 0x0240_0FFF),
    (0x0260_0000, 0x0260_0FFF),
)
_GRP_RANGE = (0x0200_B000, 0x0200_BFFF)
_MMODE_ATTRS = 0x8000_0000_0240_0000
_XVISOR_ATTRS = 0x8000_0000_0260_0000
_REMAPS = (("MMODE0", "MMODE", _MMODE_ATTRS), ("XVISOR0", "XVISOR", _XVISOR_ATTRS))
_MMODE_WINDOW = 0xC100_0100
_XVISOR_WINDOW = 0xC180_0100
_MMODE_LAND = 0x0240_0100
_XVISOR_LAND = 0x0260_0100

# (address, prot, beats, denied)
_NS0_LEGS = ((0x0200_4800, 0, 1, True), (0x0200_4808, 2, 1, False))
_NS1_LEGS = ((0x0200_4810, 2, 1, True), (0x0200_4818, 0, 1, False))
_FALL_LEGS = ((0x0200_4820, 2, 1, True), (0x0200_4828, 0, 1, False))
_PROT_LEGS = tuple((0x0200_4830 + 8 * p, p, 1, not p & 2) for p in range(8))
_B0_LEGS = ((0x0200_6000, 0, 1, True), (0x0200_6000, 0, 2, False))
_B1_LEGS = ((0x0200_7000, 0, 1, True), (0x0200_7100, 0, 2, True))
_B_FALL_LEGS = ((0x0200_7000, 0, 2, True),)
_GRP_LEGS = ((0x0200_B800, 0, 1, True),)
_ALL_SEEDS = tuple(
    addr + 8 * beat
    for legs in (
        _NS0_LEGS, _NS1_LEGS, _FALL_LEGS, _PROT_LEGS, _B0_LEGS, _B1_LEGS, _B_FALL_LEGS, _GRP_LEGS
    )
    for addr, _prot, beats, _denied in legs
    for beat in range(beats)
) + (0x0200_A800, _MMODE_LAND, _XVISOR_LAND)  # fmt: skip

STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9")
FENCE_TERMS = (
    ("NS_LEGS", "S3"),
    ("PROT_BITS", "S4"),
    ("BURST_LEGS", "S6"),
    ("WILDCARD_PATHS", "S7"),
    ("GROUP_ID", "S8"),
    ("RESTORED", "S9"),
)
CHECKERS = (
    ("CHK-OUT-NS0-EQUALITY", "S2"),
    ("CHK-OUT-NS1-EQUALITY", "S2"),
    ("CHK-OUT-NS-FALLTHROUGH", "S3"),
    ("CHK-OUT-PROT-BITS-IGNORED", "S4"),
    ("CHK-OUT-BURST0-SINGLE-ONLY", "S5"),
    ("CHK-OUT-BURST1-BOTH", "S5"),
    ("CHK-OUT-BURST-FALLTHROUGH", "S6"),
    ("CHK-OUT-SRCID-WILDCARD", "S7"),
    ("CHK-OUT-GROUPID-INERT", "S8"),
)


def _outbound(reg: str, entry: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_{reg}_BASE_ADDR", entry)


def _remap_attrs(bank: str) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_{bank}_REMAP_REGION_REGION_ATTRS_BASE_ADDR", 0)


class smc_outfilt_attr_match_test_seq(SmcCsrSeq):
    """Program outbound entries 1..3 and probe them with JTAG writes."""

    def __init__(self, name: str = "smc_outfilt_attr_match_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: dict[str, str] = {}
        self.jtag_accesses = 0
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: dict[str, list] = {}
        self._beats = {"awvalid": 0, "wvalid": 0, "arvalid": 0}
        self._aw_events: list[tuple[int, int, int]] = []
        self._resets: dict[str, int] = {}
        self._probe_no = 0

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))
        self.chk_seen[chk_id] = "printed"

    def _wait(self, name: str, bound: str, last: object) -> None:
        self._waits[name] = [bound, last]

    async def _watch_output(self) -> None:
        top = cocotb.top
        ifc = top.u_output_axi_if
        while True:
            await RisingEdge(top.clk_smc_i)
            await ReadOnly()
            for name in self._beats:
                sig = getattr(top, f"tb_output_axi_{name}")
                assert sig.value.is_resolvable, f"tb_output_axi_{name} is X/Z ({sig.value})"
                self._beats[name] += int(sig.value)
            vals = []
            for name in ("awvalid", "awready", "awaddr", "awprot", "awlen"):
                sig = getattr(ifc, name)
                assert sig.value.is_resolvable, f"u_output_axi_if.{name} is X/Z ({sig.value})"
                vals.append(int(sig.value))
            if vals[0] and vals[1]:
                self._aw_events.append((vals[2], vals[3], vals[4]))

    async def _program(self, label: str, entry: int, span: tuple[int, int], config: int) -> None:
        """Disable `entry`, write its range and configuration, and read the configuration back."""
        start, end = span
        await self.csr_write(f"{label}_OFF", _outbound("FILTER_CONFIG", entry), DISABLED, _WORD)
        await self.csr_write(f"{label}_START", _outbound("START_ADDR", entry), start, _WORD)
        await self.csr_write(f"{label}_END", _outbound("END_ADDR", entry), end, _WORD)
        await self.csr_write(f"{label}_CFG", _outbound("FILTER_CONFIG", entry), config, _WORD)
        await self.csr_read(
            f"{label}_CFG_RB",
            _outbound("FILTER_CONFIG", entry),
            expected=config | self._resets["FILTER_CONFIG"],
            length=_WORD,
        )

    async def _disable(self, label: str, entry: int) -> None:
        await self.csr_write(f"{label}_OFF", _outbound("FILTER_CONFIG", entry), DISABLED, _WORD)

    async def _probe(
        self, addr: int, prot: int, beats: int, denied: bool, land: int | None = None
    ) -> str:
        """One JTAG write; a match is DECERR with the sentinels kept, a miss lands every beat."""
        responder = self.cfg.sys_out_mem
        land = addr if land is None else land
        self._probe_no += 1
        word = 0
        for beat in range(beats):
            part = 0xC0DE_0000_0000_0000 | (self._probe_no << 40) | (beat << 32) | (addr & 0xFFFF)
            word |= part << (64 * beat)
            responder.write_int(land + 8 * beat, _SENTINEL, _WORD)
        writes0, reads0 = output_responder_counts()
        beats0, events0 = dict(self._beats), len(self._aw_events)
        item = SmcSysAxiItem(f"jtag_attr_0x{addr:x}_p{prot}_b{beats}")
        item.op, item.addr, item.length, item.beats = SmcSysAxiOp.WRITE, addr, _WORD, beats
        item.prot, item.wdata = prot, word
        want = RESP_DECERR if denied else RESP_OKAY
        if denied:
            item.allow_error = item.expect_error = True
            item.expected_resp = RESP_DECERR
        await _OneShot(item, f"{item.get_name()}_os").start(self.env.jtag_axi_agent.sequencer)
        self.jtag_accesses += 1
        assert item.resp_code == want, (
            f"JTAG write at 0x{addr:x} prot {prot} beats {beats} answered resp {item.resp_code}, "
            f"want {want} ({'a deny entry matches it' if denied else 'no entry matches it'})"
        )
        if denied:
            self._wait("hold_output_write_count", f"{BLOCKED_WRITE_HOLD_CYCLES} clk_smc_i", writes0)
            await hold_output_responder_writes(expected_writes=writes0, label=f"write 0x{addr:x}")
        else:
            await check_output_responder_delta(
                start_writes=writes0,
                start_reads=reads0,
                write_delta=1,
                read_delta=0,
                last_addr=land,
                last_wdata=word >> (64 * (beats - 1)),
            )
        writes1, reads1 = output_responder_counts()
        self._wait(
            "output_responder_obs", f"{RESPONDER_OBS_TIMEOUT_CYCLES} clk_smc_i",
            f"write_count={writes1}",
        )  # fmt: skip
        seen = {n: self._beats[n] - beats0[n] for n in self._beats}
        events = self._aw_events[events0:]
        if denied:
            for beat in range(beats):
                held = responder.read_int(land + 8 * beat, _WORD)
                assert held == _SENTINEL, f"denied write at 0x{land:x} left SYS_OUT 0x{held:x}"
            assert seen["awvalid"] == 0 and seen["wvalid"] == 0 and not events, (
                f"denied write at 0x{addr:x} raised SYS_OUT valids {seen} aw {events}"
            )
            return f"0x{addr:x} p{prot} b{beats}=DECERR kept(wr+{writes1 - writes0},aw0,w0)"
        for beat in range(beats):
            got = responder.read_int(land + 8 * beat, _WORD)
            exp = (word >> (64 * beat)) & ((1 << 64) - 1)
            assert got == exp, f"beat {beat} at 0x{land:x} left SYS_OUT 0x{got:x}, want 0x{exp:x}"
        assert seen["awvalid"] > 0 and seen["wvalid"] > 0, f"no SYS_OUT valids {seen}"
        assert events == [(land, prot, beats - 1)], (
            f"AW handshakes (addr, prot, len) {events}, want [(0x{land:x}, {prot}, {beats - 1})]"
        )
        return (
            f"0x{addr:x} p{prot} b{beats}=OKAY landed(wr+{writes1 - writes0},rd+{reads1 - reads0},"
            f"awprot{events[0][1]},awlen{events[0][2]})"
        )

    async def _legs(self, legs: tuple) -> str:
        return " ".join([await self._probe(a, p, b, d) for a, p, b, d in legs])

    async def body(self) -> None:
        responder = self.cfg.sys_out_mem
        assert responder is not None, "SYS_OUT responder not bound"
        top = cocotb.top
        await self.wait_fuse_sense_done()
        for sig in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"):
            state = getattr(top, sig).value
            assert state.is_resolvable, f"{sig} is X/Z after wait_fuse_sense_done"
            self._wait(f"wait_fuse_sense_done.{sig}", f"{_FUSE_BOUND} clk_smc_i", f"{sig}={state}")
        self._wait("jtag_axi_access", f"{_AXI_TIMEOUT_NS}ns", "none")
        self._wait("sep_in_axi_access", f"{_AXI_TIMEOUT_NS}ns", "none")
        for reg in ("FILTER_CONFIG", "START_ADDR", "END_ADDR"):
            self._resets[reg] = rdl_contract(f"smc_outbound_filter_ctrl/{reg}").reset_word
        watcher = cocotb.start_soon(self._watch_output())

        # S1
        for entry in _ENTRIES:
            got = await self.csr_read(
                f"OB{entry}_CFG_RESET", _outbound("FILTER_CONFIG", entry), length=_WORD
            )
            assert got == self._resets["FILTER_CONFIG"], f"entry {entry} reads 0x{got:x} at start"
            assert not got & DENY_B0, f"entry {entry} is enabled at start (0x{got:x})"
        for addr in _ALL_SEEDS:
            responder.write_int(addr, _SENTINEL, _WORD)
        for addr in _ALL_SEEDS:
            assert responder.read_int(addr, _WORD) == _SENTINEL, f"sentinel at 0x{addr:x}"
        self._mark_step("S1")

        # S2
        await self._program("S2A", 1, _NS_RANGE, DENY_NS0_B1)
        ns0 = await self._legs(_NS0_LEGS)
        await self._program("S2B", 1, _NS_RANGE, DENY_NS1_B1)
        ns1 = await self._legs(_NS1_LEGS)
        self._mark_step("S2")
        self._log_chk(
            "CHK-OUT-NS0-EQUALITY",
            f"allow_ns 0 deny 0x{DENY_NS0_B1:x} over 0x{_NS_RANGE[0]:x}..0x{_NS_RANGE[1]:x}: {ns0}",
        )
        self._log_chk(
            "CHK-OUT-NS1-EQUALITY",
            f"allow_ns 1 deny 0x{DENY_NS1_B1:x} over 0x{_NS_RANGE[0]:x}..0x{_NS_RANGE[1]:x}: {ns1}",
        )

        # S3
        await self._program("S3A", 1, _NS_RANGE, PERMIT_NS0_B1)
        await self._program("S3B", 2, _NS_RANGE, DENY_NS1_B1)
        fall = await self._legs(_FALL_LEGS)
        self._mark_step("S3")
        self._log_chk(
            "CHK-OUT-NS-FALLTHROUGH",
            f"entry 1 permit 0x{PERMIT_NS0_B1:x}, entry 2 deny 0x{DENY_NS1_B1:x}: {fall}",
        )

        # S4
        await self._program("S4A", 1, _NS_RANGE, DENY_NS0_B1)
        await self._disable("S4B", 2)
        prot = await self._legs(_PROT_LEGS)
        self._mark_step("S4")
        self._log_chk(
            "CHK-OUT-PROT-BITS-IGNORED",
            f"allow_ns 0 deny, entry 2 disabled: AxPROT[1]=0 -> DECERR and AxPROT[1]=1 -> OKAY "
            f"for prot 0..7: {prot}",
        )

        # S5
        await self._program("S5A", 1, _B0_RANGE, DENY_B0)
        b0 = await self._legs(_B0_LEGS)
        await self._program("S5B", 1, _B1_RANGE, DENY_B1)
        b1 = await self._legs(_B1_LEGS)
        self._mark_step("S5")
        self._log_chk(
            "CHK-OUT-BURST0-SINGLE-ONLY",
            f"allow_burst 0 over 0x{_B0_RANGE[0]:x}..0x{_B0_RANGE[1]:x}: {b0}",
        )
        self._log_chk(
            "CHK-OUT-BURST1-BOTH",
            f"allow_burst 1 over 0x{_B1_RANGE[0]:x}..0x{_B1_RANGE[1]:x}: {b1}",
        )

        # S6
        await self._program("S6A", 1, _B1_NARROW, DENY_B0)
        await self._program("S6B", 2, _B1_RANGE, DENY_B1)
        bfall = await self._legs(_B_FALL_LEGS)
        self._mark_step("S6")
        self._log_chk(
            "CHK-OUT-BURST-FALLTHROUGH",
            f"entry 1 allow_burst 0 over 0x{_B1_NARROW[0]:x}..0x{_B1_NARROW[1]:x}, entry 2 "
            f"allow_burst 1 over 0x{_B1_RANGE[0]:x}..0x{_B1_RANGE[1]:x}: {bfall}",
        )

        # S7
        for label, bank, value in _REMAPS:
            attrs = _remap_attrs(bank)
            await self.csr_read(f"{label}_ATTRS_RESET", attrs, expected=_REMAP_RESET, length=_WORD)
            await self.csr_write(f"{label}_ATTRS", attrs, value, _WORD)
            await self.csr_read(f"{label}_ATTRS_RB", attrs, expected=value, length=_WORD)
        control = [
            await self._probe(_MMODE_WINDOW, 0, 1, False, land=_MMODE_LAND),
            await self._probe(_XVISOR_WINDOW, 0, 1, False, land=_XVISOR_LAND),
        ]
        for entry, span in zip(_ENTRIES, _WILD):
            await self._program(f"S7_E{entry}", entry, span, DENY_B1)
        wild = [
            await self._probe(0x0200_A800, 0, 1, True),
            await self._probe(_MMODE_WINDOW, 0, 1, True, land=_MMODE_LAND),
            await self._probe(_XVISOR_WINDOW, 0, 1, True, land=_XVISOR_LAND),
        ]
        for addr in (0x0200_A800, _MMODE_LAND, _XVISOR_LAND):
            assert responder.read_int(addr, _WORD) == _SENTINEL, f"sentinel at 0x{addr:x} changed"
        self._mark_step("S7")
        self._log_chk(
            "CHK-OUT-SRCID-WILDCARD",
            f"M-mode and Xvisor window writes land with the deny entries disabled: "
            f"{' '.join(control)}; src_id 0 deny entries 1..3 over direct, M-mode window and "
            f"Xvisor window: {' '.join(wild)}",
        )

        # S8
        await self._program("S8", 1, _GRP_RANGE, DENY_B1_GRP7)
        grp = await self._legs(_GRP_LEGS)
        self._mark_step("S8")
        self._log_chk(
            "CHK-OUT-GROUPID-INERT",
            f"group_id 7 deny 0x{DENY_B1_GRP7:x} over 0x{_GRP_RANGE[0]:x}..0x{_GRP_RANGE[1]:x}: "
            f"{grp}",
        )

        # S9
        restored = []
        for entry in _ENTRIES:
            for reg in ("FILTER_CONFIG", "START_ADDR", "END_ADDR"):
                addr = _outbound(reg, entry)
                word = DISABLED if reg == "FILTER_CONFIG" else self._resets[reg]
                await self.csr_write(f"OB{entry}_{reg}_RESTORE", addr, word, _WORD)
                got = await self.csr_read(
                    f"OB{entry}_{reg}_RESTORE_RB", addr, expected=self._resets[reg], length=_WORD
                )
                restored.append(f"OB{entry}.{reg}=0x{got:x}")
        for label, bank, _value in _REMAPS:
            attrs = _remap_attrs(bank)
            await self.csr_write(f"{label}_ATTRS_RESTORE", attrs, _REMAP_RESET, _WORD)
            got = await self.csr_read(
                f"{label}_ATTRS_RESTORE_RB", attrs, expected=_REMAP_RESET, length=_WORD
            )
            restored.append(f"{label}.ATTRS=0x{got:x}")
        self._mark_step("S9")
        watcher.cancel()
        self._finish(restored)

    def _finish(self, restored: list[str]) -> None:
        assert self.accesses >= _SEP_FLOOR, f"{self.accesses} SEP_IN accesses, floor {_SEP_FLOOR}"
        assert self.jtag_accesses == _JTAG_COUNT, f"{self.jtag_accesses} JTAG writes"
        waits = " ".join(f"{n}={b} last={s}" for n, (b, s) in self._waits.items())
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s; expiry raises AssertionError",
            len(self._waits),
            waits,
        )
        self.chk_seen["CHK-TIMEOUT-PATHS"] = "printed"
        steps = tuple(s for s, _ in self._stamps)
        assert steps == STEPS, f"step order {steps}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing {times}"
        seen = [c for c, _ in self._chk_marks]
        assert seen == [c for c, _ in CHECKERS], f"checker lines out of order {seen}"
        stamp_of = dict(self._stamps)
        for (chk_id, when), (_c, step) in zip(self._chk_marks, CHECKERS):
            assert when >= stamp_of[step], f"{chk_id} printed before step {step}"
        terms = [t for t, _ in FENCE_TERMS]
        fence_times = [stamp_of[s] for _, s in FENCE_TERMS]
        assert all(b > a for a, b in zip(fence_times, fence_times[1:])), "fence terms out of order"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s; %d SEP_IN accesses "
            "(floor %d) and %d JTAG writes; restored %s",
            " < ".join(terms),
            ",".join(seen),
            ",".join(f"{s}={t}" for s, t in self._stamps),
            self.accesses,
            _SEP_FLOOR,
            self.jtag_accesses,
            " ".join(restored),
        )
        self.chk_seen["CHK-NONVAC"] = "ordered"
