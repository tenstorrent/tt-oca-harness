# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Scratchpad bank walk over SEP_IN AXI: entry 0 and every power-of-two entry.

DV-CARD:          SMC_COV_B2_008   ANCHOR: smc_spm_bank_walk_test

The bank and entry address bits are not documented, so the walk covers every
power-of-two interleave stride from one 64-bit word to window/32. L0 holds the
32 bank bases of every stride and LP the power-of-two entries above them. LX
adds 13 entry offsets at each of 8 regions x 4 slots of the window.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import SPM_MEMORY_BASE, SPM_MEMORY_SIZE
from .smc_csr_seq_utils import SmcCsrSeq

_WORD_BYTES = 8
_BANKS = 32
# Strides s = 8 B * 2^g for g = 0..12, the last one being 1 MiB / 32 banks.
_STRIDE_LOG2S = range(13)
# Entry exponents j = 0..11-g of entry b*s + 2^j*32*s.
_ENTRY_LOG2_LIMIT = 11
# LX bases r*0x20000 + q*0x40 (r = 0..7, q = 0..3) and their entry offsets.
_LX_REGIONS = 8
_LX_REGION_BYTES = 0x2_0000
_LX_SLOTS = 4
_LX_SLOT_BYTES = 0x40
_LX_OFFSETS = (0, 8, 16, 32, 0x100, 0x200, 0x400, 0x800, 0x1000, 0x2000, 0x4000, 0x8000, 0x1_0000)

# Contract sizes of the address sets in a 1 MiB window.
L0_SIZE = 224
LP_SIZE = 1248
LX_SIZE = 241
L0_PASSES = 5
TOTAL_ACCESSES = 2 * ((L0_SIZE + LX_SIZE) * L0_PASSES + LP_SIZE)

_ZERO = 0x0000_0000_0000_0000
_ONES = 0xFFFF_FFFF_FFFF_FFFF
_ALT_A = 0xAAAA_AAAA_AAAA_AAAA
_ALT_5 = 0x5555_5555_5555_5555
_FIXED_CLASSES = (_ZERO, _ONES, _ALT_A, _ALT_5)
_CLASSES = len(_FIXED_CLASSES) + 1


def _pattern(cls: int, walk_bit: int) -> int:
    return _FIXED_CLASSES[cls] if cls < len(_FIXED_CLASSES) else 1 << (walk_bit % 64)


def l0_pattern(i: int, c: int) -> int:
    return _pattern((i + c) % _CLASSES, i + 7 * c)


def lp_pattern(i: int) -> int:
    return _pattern(i % _CLASSES, i)


def address_sets(window: int) -> tuple[list[int], list[int], dict[int, int]]:
    """L0 and LP as ascending window offsets, and LX as offset -> entry offset."""
    l0: set[int] = set()
    lp: set[int] = set()
    for g in _STRIDE_LOG2S:
        s = _WORD_BYTES << g
        for b in range(_BANKS):
            l0.add(b * s)
            for j in range(_ENTRY_LOG2_LIMIT - g + 1):
                lp.add(b * s + (1 << j) * _BANKS * s)
    in_window = {a for a in l0 if a < window}
    lp_in_window = {a for a in lp if a < window and a not in in_window}
    lx: dict[int, int] = {}
    for r in range(_LX_REGIONS):
        for q in range(_LX_SLOTS):
            for o in _LX_OFFSETS:
                a = r * _LX_REGION_BYTES + q * _LX_SLOT_BYTES + o
                if a < window and a not in in_window and a not in lp_in_window:
                    lx.setdefault(a, o)
    return sorted(in_window), sorted(lp_in_window), lx


class _WalkReadItem(SmcSysAxiItem):
    """Read item whose log text names the location that owns a wrong read word.

    The scoreboard logs every item before its `expected=` compare, so a mismatch
    is reported with the first other location of the pass written with that word.
    """

    def __init__(self, name: str, first_writer: dict[int, int]) -> None:
        super().__init__(name)
        self.first_writer = first_writer

    def __str__(self) -> str:
        text = super().__str__()
        if self.expected is None or self.rdata == self.expected or self.resp_code != 0:
            return text
        owner = self.first_writer.get(self.rdata)
        other = "none" if owner is None or owner == self.addr else f"0x{owner:x}"
        return (
            f"{text} MISMATCH addr=0x{self.addr:x} expected=0x{self.expected:x} "
            f"read=0x{self.rdata:x} first other location written with the read word: {other}"
        )


class smc_spm_bank_walk_test_seq(SmcCsrSeq):
    """Five co-resident passes over L0, then one co-resident pass over LP."""

    def __init__(self, name: str = "smc_spm_bank_walk_test_seq") -> None:
        super().__init__(name)
        self.terms: list[tuple[str, int, int, int]] = []
        self.non_okay = 0
        self.value_compares = 0
        # Window addresses of LX locations at a non-zero entry offset, and the
        # scoreboard value compares completed on them.
        self.lx_nonzero: set[int] = set()
        self.lx_nonzero_compares = 0

    async def _write(self, addr: int, data: int) -> None:
        item = SmcSysAxiItem("wr_SPM_WALK")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = _WORD_BYTES
        item.wdata = data
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self.non_okay += item.resp_code != 0

    async def _read(self, addr: int, expected: int, first_writer: dict[int, int]) -> None:
        item = _WalkReadItem("rd_SPM_WALK", first_writer)
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = _WORD_BYTES
        item.expected = expected
        compares_before = self.env.scoreboard.sys_axi_value_checks_seen
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self.non_okay += item.resp_code != 0
        if addr in self.lx_nonzero:
            self.lx_nonzero_compares += (
                self.env.scoreboard.sys_axi_value_checks_seen - compares_before
            )

    async def _term(self, name: str, ops) -> int:
        """Run one fence term; return its scoreboard value-compare count."""
        sb = self.env.scoreboard
        compares_before = sb.sys_axi_value_checks_seen
        start = int(get_sim_time("ns"))
        count = 0
        for op in ops:
            await op
            count += 1
        end = int(get_sim_time("ns"))
        self.terms.append((name, count, start, end))
        return sb.sys_axi_value_checks_seen - compares_before

    async def _write_all(self, name: str, words: list[tuple[int, int]]) -> dict[int, int]:
        first_writer: dict[int, int] = {}
        for addr, word in words:
            first_writer.setdefault(word, addr)
        await self._term(name, (self._write(a, w) for a, w in words))
        assert self.terms[-1][1] == len(words), (
            f"{name}: {self.terms[-1][1]} of {len(words)} writes"
        )
        return first_writer

    async def _read_all(
        self, name: str, words: list[tuple[int, int]], first_writer: dict[int, int]
    ) -> int:
        compares = await self._term(name, (self._read(a, w, first_writer) for a, w in words))
        assert self.terms[-1][1] == len(words), f"{name}: {self.terms[-1][1]} of {len(words)} reads"
        assert compares == len(words), (
            f"{name}: scoreboard completed {compares} value compares for {len(words)} reads"
        )
        self.value_compares += compares
        return compares

    async def body(self) -> None:
        start = int(get_sim_time("ns"))
        await self.wait_fuse_sense_done()
        self.terms.append(("SETUP", 1, start, int(get_sim_time("ns"))))

        start = int(get_sim_time("ns"))
        l0, lp, lx = address_sets(SPM_MEMORY_SIZE)
        assert (len(l0), len(lp), len(lx)) == (L0_SIZE, LP_SIZE, LX_SIZE), (
            f"window 0x{SPM_MEMORY_SIZE:x}: |L0|={len(l0)} |LP|={len(lp)} |LX|={len(lx)}, "
            f"contract |L0|={L0_SIZE} |LP|={LP_SIZE} |LX|={LX_SIZE}"
        )
        walk = sorted(set(l0) | set(lx))
        self.lx_nonzero = {SPM_MEMORY_BASE + a for a, o in lx.items() if o != 0}
        cocotb.log.info(
            "SPM-WALK address sets: window base=0x%x size=0x%x |L0|=%d |LP|=%d |LX|=%d "
            "(%d at a non-zero entry offset) |L0 u LX|=%d; accesses: L0 u LX %d passes x "
            "%d writes + %d reads, LP 1 pass x %d writes + %d reads = %d",
            SPM_MEMORY_BASE,
            SPM_MEMORY_SIZE,
            len(l0),
            len(lp),
            len(lx),
            len(self.lx_nonzero),
            len(walk),
            L0_PASSES,
            len(walk),
            len(walk),
            len(lp),
            len(lp),
            TOTAL_ACCESSES,
        )
        self.terms.append(("ADDRESS_SET", len(walk) + len(lp), start, int(get_sim_time("ns"))))

        walk_compares = 0
        for c in range(L0_PASSES):
            words = [(SPM_MEMORY_BASE + off, l0_pattern(i, c)) for i, off in enumerate(walk)]
            first_writer = await self._write_all(f"L0_LX_WRITE_ALL[{c}]", words)
            order = words if c % 2 == 0 else list(reversed(words))
            walk_compares += await self._read_all(f"L0_LX_READ_ALL[{c}]", order, first_writer)
        assert self.non_okay == 0, f"L0 u LX: {self.non_okay} non-OKAY responses"
        assert walk_compares == len(walk) * L0_PASSES
        lx_nonzero_expected = len(self.lx_nonzero) * L0_PASSES
        assert self.lx_nonzero_compares == lx_nonzero_expected, (
            f"LX non-zero offsets: {self.lx_nonzero_compares} value compares, "
            f"expected {lx_nonzero_expected}"
        )
        cocotb.log.info(
            "CHK-SPM-WALK-ENTRY0: |L0 u LX|=%d x %d passes, %d/%d readback==written, resp "
            "OKAY; which bank and entry each address selects is not stated and is not "
            "observed at SEP_IN (LINKED-ISSUE SF-016)",
            len(walk),
            L0_PASSES,
            walk_compares,
            len(walk) * L0_PASSES,
        )

        words = [(SPM_MEMORY_BASE + off, lp_pattern(i)) for i, off in enumerate(lp)]
        first_writer = await self._write_all("LP_WRITE_ALL", words)
        lp_compares = await self._read_all("LP_READ_ALL", list(reversed(words)), first_writer)
        assert self.non_okay == 0, f"LP: {self.non_okay} non-OKAY responses"
        cocotb.log.info(
            "CHK-SPM-WALK-POW2: |LP|=%d x 1 pass + LX non-zero offsets %d x %d passes, "
            "%d/%d readback==written, resp OKAY; the per-bank entry count behind the "
            "offsets is inferred (LINKED-ISSUE SF-017)",
            len(lp),
            len(self.lx_nonzero),
            L0_PASSES,
            lp_compares + self.lx_nonzero_compares,
            len(lp) + lx_nonzero_expected,
        )

        # Every read term starts after its own write term ended and compares
        # every location against its own word while all others are resident.
        rw = self.terms[2:]
        for (w_name, _wn, _ws, w_end), (r_name, _rn, r_start, _re) in zip(rw[0::2], rw[1::2]):
            assert "WRITE_ALL" in w_name and "READ_ALL" in r_name and r_start >= w_end, (
                f"{r_name} started at {r_start} ns before {w_name} ended at {w_end} ns"
            )
        cocotb.log.info(
            "CHK-SPM-WALK-CORESIDENT: L0 u LX %d passes (asc,desc,asc,desc,asc) + LP 1 pass "
            "(desc), 0 aliased reads (%d co-resident compares, each read after the last "
            "write of its pass)",
            L0_PASSES,
            self.value_compares,
        )

        self.assert_all_reachable(TOTAL_ACCESSES, "SPM_BANK_WALK")
        expected_order = ["SETUP", "ADDRESS_SET"]
        for c in range(L0_PASSES):
            expected_order += [f"L0_LX_WRITE_ALL[{c}]", f"L0_LX_READ_ALL[{c}]"]
        expected_order += ["LP_WRITE_ALL", "LP_READ_ALL"]
        assert [t[0] for t in self.terms] == expected_order, f"fence terms {self.terms}"
        for (prev, *_p, prev_end), (name, count, start, _end) in zip(self.terms, self.terms[1:]):
            assert count > 0 and start >= prev_end, f"fence term {name} after {prev}: {self.terms}"
        access_terms = sum(t[1] for t in self.terms[2:])
        assert access_terms == TOTAL_ACCESSES, f"fence accesses {access_terms}"
        cocotb.log.info(
            "CHK-NONVAC: SETUP<ADDRESS_SET<per-pass(L0_LX_WRITE_ALL<L0_LX_READ_ALL) x%d"
            "<LP_WRITE_ALL<LP_READ_ALL, %d accesses (counts and times per term: %s)",
            L0_PASSES,
            access_terms,
            "; ".join(f"{n} n={k} {s}-{e} ns" for n, k, s, e in self.terms),
        )
