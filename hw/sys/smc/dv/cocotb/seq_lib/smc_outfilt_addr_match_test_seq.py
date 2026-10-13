# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Outbound filter entry 1 matches by address range, enable and 56-bit address.

Contract SMC_FILTER_15, anchor smc_outfilt_addr_match_test.
Allocated scenarios: OUTFILT-ADDR-MATCH.S1 to S5, FILTER-RANGE-GRANULE.S3.
Spec sources: axi_filter index.adoc (Match Then Permit, Address Range Granule), fabric.adoc
(Filtering and Protection), filter_ctrl.rdl FILTER_CONFIG.

Outbound entry 1 is programmed over SEP_IN, one case at a time, and JTAG writes at addresses
around its range follow. Entry 1 denies reads and writes (`read_allowed` and `write_allowed`
clear), so a match is a DECERR that leaves the SYS_OUT word at its sentinel and the SYS_OUT write
counter unchanged; a miss is an OKAY that lands the word and advances the counter by one. Every
case disables the entry again, and the cleanup writes the entry's reset words back.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import _REPO, reg_field_encode, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import (
    RESP_DECERR,
    RESP_OKAY,
    check_output_responder_delta,
    hold_output_responder_writes,
    jtag_axi_write,
    output_responder_counts,
)
from .smc_rdl_regmap import rdl_contract

_FILTER_H = _REPO / "hw" / "ip" / "axi_filter" / "regs" / "gen" / "c" / "filter_ctrl.h"
_ENTRY = 1
_SENTINEL = 0x5A5A_5A5A_5A5A_5A5A
_WORD = 8
_FUSE_BOUND = 200_000
_AXI_TIMEOUT_NS = 50_000
_HOLD_CYCLES = 64
_OBS_CYCLES = 200
_SEP_FLOOR = 52
_JTAG_FLOOR = 26


def _config(**fields: int) -> int:
    return reg_field_encode(_FILTER_H, "FILTER_CTRL", "FILTER_CONFIG", **fields)


DENY_B1 = _config(entry_enabled=1, allow_burst=1)
DENY_B0 = _config(entry_enabled=1)
DISABLED_B1 = _config(allow_burst=1)
DISABLED = 0

_C1 = (0x0200_4000, 0x0200_4FFF, DENY_B1)
_C2 = (0x0200_6040, 0x0200_6047, DENY_B0)
# (address, denied)
_C1_PROBES = ((0x0200_4800, True), (0x0200_3FF8, False), (0x0200_5000, False))
_C2_PROBES = ((0x0200_6040, True), (0x0200_6038, False), (0x0200_6048, False))
_C3 = (0x0200_4000, 0x0200_4FFF, DISABLED_B1)
_C3_PROBES = ((0x0200_4800, False),)
_C4 = (0x00AB_0200_4000, 0x00AB_0200_4FFF, DENY_B1)
_C4_PROBES = ((0x00AB_0200_4800, True), (0x0000_0200_4800, False), (0x00CD_0200_4800, False))
_C5 = (0x0200_8000, 0x0200_BFFF, DENY_B1)
_C5_PROBES = (
    (0x0200_8000, True),
    (0x0200_9FF8, True),
    (0x0200_BFF8, True),
    (0x0200_7FF8, False),
    (0x0200_C000, False),
)
_C6A = (0x0200_C008, 0x0200_C008, DENY_B0)
_C6A_PROBES = ((0x0200_C008, True), (0x0200_C000, False), (0x0200_C010, False))
_C6B = (0x0200_D123, 0x0200_D123, DENY_B1)
_C6B_PROBES = (
    (0x0200_D000, True),
    (0x0200_DFF8, True),
    (0x0200_CFF8, False),
    (0x0200_E000, False),
)
_C7_START, _C7_END = 0x0200_0FFF, 0x0200_1000
_C7_PROBES = (
    (0x0200_0000, True),
    (0x0200_1FF8, True),
    (0x01FF_FFF8, False),
    (0x0200_2000, False),
)
_ALL_PROBES = (
    _C1_PROBES + _C2_PROBES + _C3_PROBES + _C4_PROBES + _C5_PROBES
    + _C6A_PROBES + _C6B_PROBES + _C7_PROBES
)  # fmt: skip

FENCE_ORDER = ("SENTINELS_SEEDED", "C1_C2", "C3", "C4", "C5", "C6", "C7", "CLEANED")
CHK_ORDER = (
    ("CHK-OUT-ADDR-GRANULE", "C1_C2"),
    ("CHK-OUT-DISABLED-NO-MATCH", "C3"),
    ("CHK-OUT-HIGH-ADDRESS-BITS", "C4"),
    ("CHK-OUT-SPAN-WHOLE", "C5"),
    ("CHK-OUT-START-EQ-END", "C6"),
    ("CHK-GRANULE-MULTI-ADMIT", "C7"),
)


def _outbound(reg: str, entry: int = _ENTRY) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_{reg}_BASE_ADDR", entry)


class smc_outfilt_addr_match_test_seq(SmcCsrSeq):
    """Reprogram outbound entry 1 per case and probe it with JTAG writes."""

    def __init__(self, name: str = "smc_outfilt_addr_match_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: dict[str, str] = {}
        self.jtag_accesses = 0
        self._fence: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: dict[str, list] = {}
        self._beats = {"awvalid": 0, "wvalid": 0, "arvalid": 0}
        self._resets: dict[str, int] = {}
        self._probe_no = 0

    def _stamp(self, term: str) -> None:
        self._fence.append((term, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, len(self._fence)))
        self.chk_seen[chk_id] = "printed"

    def _wait(self, name: str, bound: str, last: object) -> None:
        self._waits[name] = [bound, last]

    async def _watch_beats(self) -> None:
        top = cocotb.top
        while True:
            await RisingEdge(top.clk_smc_i)
            for name in self._beats:
                sig = getattr(top, f"tb_output_axi_{name}")
                assert sig.value.is_resolvable, f"tb_output_axi_{name} is X/Z ({sig.value})"
                self._beats[name] += int(sig.value)

    async def _program(self, label: str, start: int, end: int, config: int) -> None:
        """Disable entry 1, write its range and configuration and read the configuration back."""
        await self.csr_write(f"{label}_OFF", _outbound("FILTER_CONFIG"), DISABLED, length=_WORD)
        await self.csr_write(f"{label}_START", _outbound("START_ADDR"), start, length=_WORD)
        await self.csr_write(f"{label}_END", _outbound("END_ADDR"), end, length=_WORD)
        await self._enable(label, config)

    async def _enable(self, label: str, config: int) -> None:
        reads_back = config | self._resets["FILTER_CONFIG"]
        await self.csr_write(f"{label}_CFG", _outbound("FILTER_CONFIG"), config, length=_WORD)
        await self.csr_read(
            f"{label}_CFG_RB", _outbound("FILTER_CONFIG"), expected=reads_back, length=_WORD
        )

    async def _probe(self, addr: int, denied: bool) -> str:
        """One JTAG write at `addr`; a match is DECERR with the sentinel kept, a miss lands."""
        responder = self.cfg.sys_out_mem
        self._probe_no += 1
        word = 0xC0DE_0000_0000_0000 | (self._probe_no << 40) | (addr & 0xFFFF_FFFF)
        responder.write_int(addr, _SENTINEL, _WORD)
        writes0, reads0 = output_responder_counts()
        beats0 = dict(self._beats)
        item = await jtag_axi_write(
            self,
            addr,
            word,
            expect_error=denied,
            expected_resp=RESP_DECERR if denied else RESP_OKAY,
        )
        self.jtag_accesses += 1
        want = RESP_DECERR if denied else RESP_OKAY
        assert item.resp_code == want, (
            f"JTAG write at 0x{addr:x} answered resp {item.resp_code}, want {want} "
            f"({'a deny entry matches it' if denied else 'no entry matches it'})"
        )
        if denied:
            self._wait("hold_output_write_count", f"{_HOLD_CYCLES} clk_smc_i", writes0)
            await hold_output_responder_writes(
                expected_writes=writes0, label=f"write 0x{addr:x}", hold_cycles=_HOLD_CYCLES
            )
        else:
            await check_output_responder_delta(
                start_writes=writes0,
                start_reads=reads0,
                write_delta=1,
                read_delta=0,
                last_addr=addr,
                last_wdata=word,
            )
        writes1, reads1 = output_responder_counts()
        self._wait("output_responder_obs", f"{_OBS_CYCLES} clk_smc_i", f"write_count={writes1}")
        held = responder.read_int(addr, _WORD)
        beats = {n: self._beats[n] - beats0[n] for n in self._beats}
        if denied:
            assert held == _SENTINEL, f"denied write at 0x{addr:x} changed SYS_OUT to 0x{held:x}"
            assert beats["awvalid"] == 0 and beats["wvalid"] == 0, (
                f"denied write at 0x{addr:x} raised SYS_OUT valids {beats}"
            )
        else:
            assert held == word, f"write at 0x{addr:x} left SYS_OUT 0x{held:x}, want 0x{word:x}"
            assert beats["awvalid"] > 0 and beats["wvalid"] > 0, (
                f"write at 0x{addr:x} raised no SYS_OUT valids {beats}"
            )
        return (
            f"0x{addr:x}={'DECERR kept' if denied else 'OKAY landed'}(resp{item.resp_code},"
            f"wr+{writes1 - writes0},rd+{reads1 - reads0},aw{beats['awvalid']},"
            f"w{beats['wvalid']},ar{beats['arvalid']})"
        )

    async def _case(self, label: str, entry: tuple, probes: tuple) -> list[str]:
        start, end, config = entry
        await self._program(label, start, end, config)
        out = [await self._probe(addr, denied) for addr, denied in probes]
        await self.csr_write(f"{label}_OFF_END", _outbound("FILTER_CONFIG"), DISABLED, length=_WORD)
        return out

    async def _restore(self) -> list[str]:
        parts = []
        for reg in ("FILTER_CONFIG", "START_ADDR", "END_ADDR"):
            addr = _outbound(reg)
            word = DISABLED if reg == "FILTER_CONFIG" else self._resets[reg]
            await self.csr_write(f"{reg}_RESTORE", addr, word, length=_WORD)
            got = await self.csr_read(
                f"{reg}_RESTORE_RB", addr, expected=self._resets[reg], length=_WORD
            )
            parts.append(f"{reg}=0x{got:x}")
        return parts

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
        watcher = cocotb.start_soon(self._watch_beats())

        for entry in (0, _ENTRY):
            for reg in ("FILTER_CONFIG", "START_ADDR", "END_ADDR"):
                got = await self.csr_read(
                    f"OB{entry}_{reg}_RESET", _outbound(reg, entry), length=_WORD
                )
                assert got == self._resets[reg], f"entry {entry} {reg} reads 0x{got:x} at start"
                if reg == "FILTER_CONFIG":
                    assert not got & DENY_B0, f"entry {entry} is enabled at start (0x{got:x})"
        for addr, _denied in _ALL_PROBES:
            responder.write_int(addr, _SENTINEL, _WORD)
        for addr, _denied in _ALL_PROBES:
            assert responder.read_int(addr, _WORD) == _SENTINEL, f"sentinel at 0x{addr:x}"
        self._stamp("SENTINELS_SEEDED")

        c1 = await self._case("C1", _C1, _C1_PROBES)
        c2 = await self._case("C2", _C2, _C2_PROBES)
        self._stamp("C1_C2")
        self._chk(
            "CHK-OUT-ADDR-GRANULE",
            f"allow_burst 1 over 0x{_C1[0]:x}..0x{_C1[1]:x}: {' '.join(c1)}; allow_burst 0 over "
            f"0x{_C2[0]:x}..0x{_C2[1]:x}: {' '.join(c2)}",
        )

        c3 = await self._case("C3", _C3, _C3_PROBES)
        self._stamp("C3")
        self._chk(
            "CHK-OUT-DISABLED-NO-MATCH",
            f"entry_enabled clear over 0x{_C3[0]:x}..0x{_C3[1]:x}: {' '.join(c3)}",
        )

        c4 = await self._case("C4", _C4, _C4_PROBES)
        self._stamp("C4")
        self._chk(
            "CHK-OUT-HIGH-ADDRESS-BITS",
            f"deny over 0x{_C4[0]:x}..0x{_C4[1]:x}: {' '.join(c4)}",
        )

        c5 = await self._case("C5", _C5, _C5_PROBES)
        self._stamp("C5")
        self._chk(
            "CHK-OUT-SPAN-WHOLE",
            f"deny over 0x{_C5[0]:x}..0x{_C5[1]:x}: {' '.join(c5)}",
        )

        c6a = await self._case("C6A", _C6A, _C6A_PROBES)
        c6b = await self._case("C6B", _C6B, _C6B_PROBES)
        self._stamp("C6")
        self._chk(
            "CHK-OUT-START-EQ-END",
            f"START=END=0x{_C6A[0]:x} (8-byte granule): {' '.join(c6a)}; START=END=0x{_C6B[0]:x} "
            f"(4 KiB granule): {' '.join(c6b)}",
        )

        await self.csr_write("C7_OFF", _outbound("FILTER_CONFIG"), DISABLED, length=_WORD)
        await self.csr_write("C7_CFG_OFF", _outbound("FILTER_CONFIG"), DISABLED_B1, length=_WORD)
        await self.csr_write("C7_START", _outbound("START_ADDR"), _C7_START, length=_WORD)
        await self.csr_write("C7_END", _outbound("END_ADDR"), _C7_END, length=_WORD)
        start_rb = await self.csr_read("C7_START_RB", _outbound("START_ADDR"), length=_WORD)
        end_rb = await self.csr_read("C7_END_RB", _outbound("END_ADDR"), length=_WORD)
        assert (start_rb, end_rb) == (_C7_START, _C7_END), (
            f"START/END read back 0x{start_rb:x}/0x{end_rb:x}, want 0x{_C7_START:x}/0x{_C7_END:x}"
        )
        await self._enable("C7", DENY_B1)
        c7 = [await self._probe(addr, denied) for addr, denied in _C7_PROBES]
        await self.csr_write("C7_OFF_END", _outbound("FILTER_CONFIG"), DISABLED, length=_WORD)
        self._stamp("C7")
        self._chk(
            "CHK-GRANULE-MULTI-ADMIT",
            f"START 0x{start_rb:x} END 0x{end_rb:x} read back unchanged; span "
            f"0x{_C7_START & ~0xFFF:x}..0x{(_C7_END | 0xFFF):x}: {' '.join(c7)}",
        )

        restored = await self._restore()
        self._stamp("CLEANED")
        watcher.cancel()
        self._finish(restored)

    def _finish(self, restored: list[str]) -> None:
        assert self.accesses >= _SEP_FLOOR, f"{self.accesses} SEP_IN accesses, floor {_SEP_FLOOR}"
        assert self.jtag_accesses == _JTAG_FLOOR, f"{self.jtag_accesses} JTAG writes"
        waits = " ".join(f"{n}={b} last={s}" for n, (b, s) in self._waits.items())
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s; expiry raises AssertionError",
            len(self._waits),
            waits,
        )
        self.chk_seen["CHK-TIMEOUT-PATHS"] = "printed"
        order = [t for t, _ in self._fence]
        assert order == list(FENCE_ORDER), f"fence order {order}"
        stamps = [t for _, t in self._fence]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        seen = [c for c, _ in self._chk_marks]
        assert seen == [c for c, _ in CHK_ORDER], f"checker lines out of order {seen}"
        pos = {t: i + 1 for i, t in enumerate(FENCE_ORDER)}
        for (chk_id, printed_at), (_c, term) in zip(self._chk_marks, CHK_ORDER):
            assert printed_at >= pos[term], f"{chk_id} printed before step {term}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s; %d SEP_IN accesses "
            "(floor %d) and %d JTAG writes (floor %d); restored %s",
            " < ".join(order),
            ",".join(seen),
            ",".join(map(str, stamps)),
            self.accesses,
            _SEP_FLOOR,
            self.jtag_accesses,
            _JTAG_FLOOR,
            " ".join(restored),
        )
        self.chk_seen["CHK-NONVAC"] = "ordered"
