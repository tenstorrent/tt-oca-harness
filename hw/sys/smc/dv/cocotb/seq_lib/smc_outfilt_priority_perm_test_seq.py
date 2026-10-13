# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Outbound filter default pass, allow entries, lowest-hit priority and per-channel permission.

Contract SMC_FILTER_17, anchor smc_outfilt_priority_perm_test.
Allocated scenarios: OUTFILT-PRIORITY-PERM.S1 to S5, OUTFILT-DEFAULT-PASS.S1 and S3.
Spec sources: axi_filter index.adoc (Match Then Permit), fabric.adoc (Outbound Filtering),
filter_ctrl.rdl FILTER_CONFIG read_allowed and write_allowed.

The first leg drives JTAG traffic before any filter register is written and sees the default
pass. Outbound entries are then programmed over SEP_IN and JTAG reads and writes show that an
allow entry is not an allowlist, that the lowest matching entry decides, that each channel obeys
its own permission bit and that a read and a write at one address select different entries. A
denied access answers DECERR, keeps the SYS_OUT word and raises no SYS_OUT beat; a permitted one
answers OKAY, lands or returns the seeded word and presents the driven AxPROT and AxCACHE. Every
entry used is written back to its reset words at the end.
"""

from __future__ import annotations

import os
import random

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import _REPO, reg_field_encode, smc_indexed_addr
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
_SENTINEL = 0x5A5A_5A5A_5A5A_5A5A
_WORD = 8
_FUSE_BOUND = 200_000
_AXI_TIMEOUT_NS = 50_000
_ENTRIES = (0, 1, 2, 3, 4, 5, 6, 7, 8, 14, 15)
_PAIRS = ((0, 1), (7, 8), (14, 15))
_OFFSETS = (0x000, 0x400, 0x800)
_DRIVEN_PROT = 0b110
_DRIVEN_CACHE = 0b0011
_JTAG_COUNT = 19
_SEP_COUNT = 160


def _config(**fields: int) -> int:
    return reg_field_encode(_FILTER_H, "FILTER_CTRL", "FILTER_CONFIG", **fields)


DENY_B1 = _config(entry_enabled=1, allow_burst=1)
PERMIT_B1 = _config(read_allowed=1, write_allowed=1, entry_enabled=1, allow_burst=1)
RDONLY_B1 = _config(read_allowed=1, entry_enabled=1, allow_burst=1)
WRONLY_B1 = _config(write_allowed=1, entry_enabled=1, allow_burst=1)
DENY_NS1_B1 = _config(entry_enabled=1, allow_ns=1, allow_burst=1)
DISABLED = 0
assert (DENY_B1, PERMIT_B1, RDONLY_B1, WRONLY_B1, DENY_NS1_B1) == (
    0x0100_0010, 0x0100_0013, 0x0100_0011, 0x0100_0012, 0x0100_0110,
)  # fmt: skip

STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
FENCE_TERMS = (
    ("RESET_PASS", "S1"),
    ("ALLOW_ENTRY_LEG", "S2"),
    ("PRIORITY_LEGS", "S3"),
    ("CHANNEL_LEGS", "S5"),
    ("PAIR_LEGS", "S6"),
    ("CLEANED", "S7"),
)
CHECKERS = (
    ("CHK-OUT-DEFAULT-PASS-RESET", "S1"),
    ("CHK-OUT-ALLOW-NOT-ALLOWLIST", "S2"),
    ("CHK-OUT-PRIO-DENY-OVER-PERMIT", "S3"),
    ("CHK-OUT-PRIO-PERMIT-OVER-DENY", "S3"),
    ("CHK-OUT-PER-CHANNEL", "S4"),
    ("CHK-OUT-RD-WR-DIFF-ENTRY", "S5"),
    ("CHK-OUT-PRIO-PAIRS", "S6"),
)


def _outbound(reg: str, entry: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_{reg}_BASE_ADDR", entry)


class smc_outfilt_priority_perm_test_seq(SmcCsrSeq):
    """Program outbound entries over SEP_IN and probe them with JTAG reads and writes."""

    def __init__(self, name: str = "smc_outfilt_priority_perm_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: dict[str, str] = {}
        self.jtag_accesses = 0
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: dict[str, list] = {}
        self._beats = {"awvalid": 0, "wvalid": 0, "arvalid": 0}
        self._events: list[tuple[str, int, int, int, int]] = []
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
            for kind in ("aw", "ar"):
                names = (f"{kind}valid", f"{kind}ready", f"{kind}prot", f"{kind}cache")
                vals = []
                for name in names:
                    sig = getattr(ifc, name)
                    assert sig.value.is_resolvable, f"u_output_axi_if.{name} is X/Z ({sig.value})"
                    vals.append(int(sig.value))
                tb_addr = getattr(top, f"tb_output_axi_{kind}addr")
                assert tb_addr.value.is_resolvable, f"tb_output_axi_{kind}addr is X/Z"
                if vals[0] and vals[1]:
                    self._events.append((kind, int(tb_addr.value), vals[2], vals[3], 0))

    async def _program(self, label: str, entry: int, span: tuple[int, int], config: int) -> None:
        """Write the configuration, then the range, and read the configuration back."""
        await self._set_config(f"{label}_CFG", entry, config)
        await self.csr_write(f"{label}_START", _outbound("START_ADDR", entry), span[0], _WORD)
        await self.csr_write(f"{label}_END", _outbound("END_ADDR", entry), span[1], _WORD)
        await self._read_config(f"{label}_CFG_RB", entry, config)

    async def _set_config(self, label: str, entry: int, config: int) -> None:
        await self.csr_write(label, _outbound("FILTER_CONFIG", entry), config, _WORD)

    async def _read_config(self, label: str, entry: int, config: int) -> int:
        return await self.csr_read(
            label,
            _outbound("FILTER_CONFIG", entry),
            expected=config | self._resets["FILTER_CONFIG"],
            length=_WORD,
        )

    async def _swap(self, label: str, first: tuple[int, int], second: tuple[int, int]) -> None:
        for entry, config in (first, second):
            await self._set_config(f"{label}_E{entry}", entry, config)
        for entry, config in (first, second):
            await self._read_config(f"{label}_E{entry}_RB", entry, config)

    async def _disable(self, label: str, *entries: int) -> None:
        for entry in entries:
            await self._set_config(f"{label}_E{entry}_OFF", entry, DISABLED)

    async def _hold_reads(self, reads0: int, label: str) -> None:
        top = cocotb.top
        for cycle in range(1, BLOCKED_WRITE_HOLD_CYCLES + 1):
            await ClockCycles(top.clk_smc_i, 1)
            sig = top.tb_output_axi_read_count
            assert sig.value.is_resolvable, f"{label}: tb_output_axi_read_count is X/Z"
            assert int(sig.value) == reads0, (
                f"{label}: tb_output_axi_read_count advanced to {int(sig.value)} (was {reads0}) "
                f"{cycle} cycles after a read the filter must refuse"
            )

    async def _probe(
        self,
        op: SmcSysAxiOp,
        addr: int,
        denied: bool,
        prot: int = 0,
        seed: int = _SENTINEL,
    ) -> dict:
        """One JTAG access; a refusal is DECERR with the seed kept, a pass lands or returns it."""
        responder = self.cfg.sys_out_mem
        is_write = op is SmcSysAxiOp.WRITE
        self._probe_no += 1
        word = 0xC0DE_0000_0000_0000 | (self._probe_no << 40) | (addr & 0xFFFF_FFFF)
        responder.write_int(addr, seed, _WORD)
        writes0, reads0 = output_responder_counts()
        beats0, events0 = dict(self._beats), len(self._events)
        item = SmcSysAxiItem(f"jtag_{op.value}_0x{addr:x}_p{prot}")
        item.op, item.addr, item.length, item.prot = op, addr, _WORD, prot
        if is_write:
            item.wdata = word
        want = RESP_DECERR if denied else RESP_OKAY
        if denied:
            item.allow_error = item.expect_error = True
            item.expected_resp = RESP_DECERR
        await _OneShot(item, f"{item.get_name()}_os").start(self.env.jtag_axi_agent.sequencer)
        self.jtag_accesses += 1
        assert item.resp_code == want, (
            f"JTAG {op.value} at 0x{addr:x} prot {prot} answered resp {item.resp_code}, want "
            f"{want} ({'a deny entry decides it' if denied else 'no deny entry decides it'})"
        )
        if denied and is_write:
            self._wait("hold_output_write_count", f"{BLOCKED_WRITE_HOLD_CYCLES} clk_smc_i", writes0)
            await hold_output_responder_writes(expected_writes=writes0, label=f"write 0x{addr:x}")
        elif denied:
            self._wait("hold_output_read_count", f"{BLOCKED_WRITE_HOLD_CYCLES} clk_smc_i", reads0)
            await self._hold_reads(reads0, f"read 0x{addr:x}")
        else:
            await check_output_responder_delta(
                start_writes=writes0,
                start_reads=reads0,
                write_delta=int(is_write),
                read_delta=int(not is_write),
                last_addr=addr if is_write else None,
                last_wdata=word if is_write else None,
            )
        writes1, reads1 = output_responder_counts()
        self._wait(
            "output_responder_obs",
            f"{RESPONDER_OBS_TIMEOUT_CYCLES} clk_smc_i",
            f"write_count={writes1} read_count={reads1}",
        )
        seen = {n: self._beats[n] - beats0[n] for n in self._beats}
        kind = "aw" if is_write else "ar"
        events = [e for e in self._events[events0:] if e[0] == kind]
        held = responder.read_int(addr, _WORD)
        info = {"item": item, "word": word, "events": events, "seen": seen, "seed": seed}
        if denied:
            assert held == seed, f"denied {op.value} at 0x{addr:x} left SYS_OUT 0x{held:x}"
            assert not self._events[events0:], f"denied {op.value} at 0x{addr:x} raised {events}"
            assert seen == {"awvalid": 0, "wvalid": 0, "arvalid": 0}, f"denied valids {seen}"
            assert (writes1, reads1) == (writes0, reads0), "denied access moved a counter"
            info["text"] = (
                f"0x{addr:x} {op.value} p{prot}=DECERR kept(0x{held:x},wr+0,rd+0,valids0,"
                f"rdata=0x{item.rdata:x})"
            )
            return info
        if is_write:
            assert held == word, f"write at 0x{addr:x} left SYS_OUT 0x{held:x}, want 0x{word:x}"
            assert seen["awvalid"] > 0 and seen["wvalid"] > 0, f"no SYS_OUT AW/W {seen}"
            assert (writes1 - writes0, reads1 - reads0) == (1, 0), "write moved counters oddly"
        else:
            assert item.rdata == seed, f"read at 0x{addr:x} gave 0x{item.rdata:x}, want 0x{seed:x}"
            assert seen["arvalid"] > 0, f"no SYS_OUT AR {seen}"
            assert (writes1 - writes0, reads1 - reads0) == (0, 1), "read moved counters oddly"
        assert len(events) == 1, f"{op.value} at 0x{addr:x}: {len(events)} handshakes {events}"
        assert events[0][1] == addr, f"{kind}addr 0x{events[0][1]:x}, want 0x{addr:x}"
        assert events[0][2] == prot, f"{kind}prot {events[0][2]}, want {prot}"
        assert events[0][3] == _DRIVEN_CACHE, f"{kind}cache {events[0][3]}, want 3"
        data = word if is_write else item.rdata
        info["text"] = (
            f"0x{addr:x} {op.value} p{prot}=OKAY {'landed' if is_write else 'returned'}"
            f"(0x{data:x},{kind}addr0x{events[0][1]:x},{kind}prot{events[0][2]},"
            f"{kind}cache{events[0][3]},wr+{writes1 - writes0},rd+{reads1 - reads0})"
        )
        return info

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
        write, read = SmcSysAxiOp.WRITE, SmcSysAxiOp.READ

        # S1
        for entry in _ENTRIES:
            got = await self.csr_read(
                f"OB{entry}_CFG_RESET", _outbound("FILTER_CONFIG", entry), length=_WORD
            )
            assert got == self._resets["FILTER_CONFIG"], f"entry {entry} reads 0x{got:x} at start"
        read_seed = 0x7777_8888_9999_AAAA
        w1 = await self._probe(write, 0x0200_0100, False, prot=_DRIVEN_PROT)
        r1 = await self._probe(read, 0x0200_0108, False, prot=_DRIVEN_PROT, seed=read_seed)
        self._mark_step("S1")
        self._log_chk(
            "CHK-OUT-DEFAULT-PASS-RESET",
            f"no filter register written, entries enabled 0: {w1['text']} {r1['text']}",
        )

        # S2
        await self._program("S2A", 1, (0x0200_2000, 0x0200_2FFF), PERMIT_B1)
        await self._program("S2B", 2, (0x0200_3000, 0x0200_3FFF), DENY_B1)
        a = await self._probe(write, 0x0200_2100, False)
        b = await self._probe(write, 0x0200_5100, False)
        c = await self._probe(write, 0x0200_3100, True)
        await self._disable("S2", 1, 2)
        self._mark_step("S2")
        self._log_chk(
            "CHK-OUT-ALLOW-NOT-ALLOWLIST",
            f"entry 1 permit 0x{PERMIT_B1:x} over 0x2000..0x2fff, entry 2 deny 0x{DENY_B1:x} over "
            f"0x3000..0x3fff: {a['text']} {b['text']} {c['text']}",
        )

        # S3
        span = (0x0200_6000, 0x0200_6FFF)
        await self._program("S3A", 3, span, DENY_B1)
        await self._program("S3B", 4, span, PERMIT_B1)
        deny = await self._probe(write, 0x0200_6100, True)
        await self._swap("S3", (3, PERMIT_B1), (4, DENY_B1))
        permit = await self._probe(write, 0x0200_6108, False)
        await self._disable("S3", 3, 4)
        self._mark_step("S3")
        self._log_chk(
            "CHK-OUT-PRIO-DENY-OVER-PERMIT",
            f"entry 3 deny 0x{DENY_B1:x} over entry 4 permit 0x{PERMIT_B1:x}: {deny['text']}",
        )
        self._log_chk(
            "CHK-OUT-PRIO-PERMIT-OVER-DENY",
            f"entry 3 permit 0x{PERMIT_B1:x} over entry 4 deny 0x{DENY_B1:x}: {permit['text']}",
        )

        # S4
        ro_seed = 0xFEED_0000_7100_0001
        await self._program("S4A", 5, (0x0200_7000, 0x0200_7FFF), RDONLY_B1)
        ro_w = await self._probe(write, 0x0200_7100, True, seed=ro_seed)
        ro_r = await self._probe(read, 0x0200_7100, False, seed=ro_seed)
        await self._set_config("S4B_CFG", 5, WRONLY_B1)
        await self._read_config("S4B_CFG_RB", 5, WRONLY_B1)
        wo_w = await self._probe(write, 0x0200_7108, False)
        wo_r = await self._probe(read, 0x0200_7108, True, seed=ro_seed ^ 0xFF)
        await self._disable("S4", 5)
        self._mark_step("S4")
        self._log_chk(
            "CHK-OUT-PER-CHANNEL",
            f"RDONLY_B1 0x{RDONLY_B1:x}: {ro_w['text']} {ro_r['text']}; WRONLY_B1 "
            f"0x{WRONLY_B1:x}: {wo_w['text']} {wo_r['text']}",
        )

        # S5
        span = (0x0200_8000, 0x0200_8FFF)
        await self._program("S5A", 6, span, DENY_NS1_B1)
        await self._program("S5B", 7, span, PERMIT_B1)
        nr = await self._probe(read, 0x0200_8100, True, prot=0b010)
        nw = await self._probe(write, 0x0200_8100, False, prot=0)
        await self._disable("S5", 6, 7)
        self._mark_step("S5")
        self._log_chk(
            "CHK-OUT-RD-WR-DIFF-ENTRY",
            f"entry 6 deny 0x{DENY_NS1_B1:x}, entry 7 permit 0x{PERMIT_B1:x} over 0x8000..0x8fff: "
            f"{nr['text']} {nw['text']}",
        )

        # S6
        seed = int(os.environ.get("RANDOM_SEED", "1"), 0)
        rng = random.Random(seed ^ 0x0F17_0001)
        pair_cells = []
        for index, (low, high) in enumerate(_PAIRS):
            base = 0x0201_0000 + 0x1_0000 * index
            offset, channel = rng.choice(_OFFSETS), rng.choice((read, write))
            probe = base + 0x1000 + offset + 0x10
            lo_span, hi_span = (base, base + 0x1FFF), (base + 0x1000, base + 0x2FFF)
            pair_seed = 0xBEEF_0000_0000_0000 | (index << 32) | offset
            await self._program(f"S6P{index}L", low, lo_span, DENY_B1)
            await self._program(f"S6P{index}H", high, hi_span, PERMIT_B1)
            first = await self._probe(channel, probe, True, seed=pair_seed)
            await self._swap(f"S6P{index}", (low, PERMIT_B1), (high, DENY_B1))
            second = await self._probe(channel, probe, False, seed=pair_seed)
            await self._disable(f"S6P{index}", low, high)
            pair_cells.append(
                f"pair({low},{high}) {channel.value} offset 0x{offset:x} A=0x{base:x}: "
                f"low deny {first['text']}; low permit {second['text']}"
            )
        self._mark_step("S6")
        self._log_chk(
            "CHK-OUT-PRIO-PAIRS",
            f"seed {seed}, draws visited all {len(_PAIRS)} pairs: {' | '.join(pair_cells)}",
        )

        # S7
        for entry in _ENTRIES:
            await self._set_config(f"OB{entry}_CFG_RESTORE", entry, DISABLED)
            for reg in ("START_ADDR", "END_ADDR"):
                await self.csr_write(
                    f"OB{entry}_{reg}_RESTORE", _outbound(reg, entry), self._resets[reg], _WORD
                )
        restored = []
        for entry in _ENTRIES:
            for reg in ("FILTER_CONFIG", "START_ADDR", "END_ADDR"):
                got = await self.csr_read(
                    f"OB{entry}_{reg}_RESTORE_RB",
                    _outbound(reg, entry),
                    expected=self._resets[reg],
                    length=_WORD,
                )
                restored.append(f"OB{entry}.{reg}=0x{got:x}")
        self._mark_step("S7")
        watcher.cancel()
        self._finish(restored)

    def _finish(self, restored: list[str]) -> None:
        assert self.accesses == _SEP_COUNT, f"{self.accesses} SEP_IN accesses, want {_SEP_COUNT}"
        assert self.jtag_accesses == _JTAG_COUNT, f"{self.jtag_accesses} JTAG accesses"
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
            "and %d JTAG accesses; restored %s",
            " < ".join(terms),
            ",".join(seen),
            ",".join(f"{s}={t}" for s, t in self._stamps),
            self.accesses,
            self.jtag_accesses,
            " ".join(restored),
        )
        self.chk_seen["CHK-NONVAC"] = "ordered"
