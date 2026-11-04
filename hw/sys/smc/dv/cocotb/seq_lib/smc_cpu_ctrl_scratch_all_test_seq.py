# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smc_cpu_ctrl_scratch_all_test: CPU_CTRL SCRATCH[0..15] full sweep.

Sources: hw/sys/smc/regs/blocks/cpu_ctrl/cpu_ctrl.rdl, doc/programmer/src/smc-programming.adoc.
"""

from __future__ import annotations

import os
import random

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

FUSE_SENSE_MAX_CYCLES = 200_000
SCRATCH_COUNT = 16
# Each entry is an 8-byte slot whose 32-bit `data` field sits at offset 0.
SCRATCH_STRIDE = 8
WIDTH_PATTERNS = (0xFFFF_FFFF, 0x0000_0001, 0x8000_0000)
PROBE_SIZES = (1, 2, 4, 8)
AXI_RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}
STEP_ORDER = ("S1", "S2", "S3", "S4", "S5", "S6")
FENCE_TERMS = {
    "S1": "BRINGUP_DONE",
    "S2": "ENTRIES_SAVED",
    "S3": "UNIQUE_PATTERNS_COMPARED",
    "S4": "WALKING_ENTRY_COMPARED",
    "S5": "WIDTH_PATTERNS_COMPARED",
    "S6": "ENTRIES_RESTORED",
}
CHK_STEP = {
    "CHK-SCRATCH-UNIQUE": "S6",
    "CHK-SCRATCH-WALK": "S4",
    "CHK-SCRATCH-BITS": "S6",
}
CHK_ORDER = tuple(CHK_STEP)


def draw_patterns(rng: random.Random) -> list[int]:
    """Sixteen distinct non-zero 32-bit words."""
    return rng.sample(range(1, 1 << 32), SCRATCH_COUNT)


def draw_probes(rng: random.Random) -> list[tuple[int, int]]:
    """Sixteen (byte offset, AxSIZE) read-backs inside the 128-byte array, aligned, not crossing."""
    probes = []
    for _ in range(SCRATCH_COUNT):
        length = rng.choice(PROBE_SIZES)
        offset = rng.randrange(0, SCRATCH_COUNT * SCRATCH_STRIDE - length + 1, length)
        probes.append((offset, length))
    return probes


class smc_cpu_ctrl_scratch_all_test_seq(SmcCsrSeq):
    """Sweep SCRATCH[0..15] over SEP_IN and restore every entry."""

    def __init__(self, name: str = "smc_cpu_ctrl_scratch_all_test_seq") -> None:
        super().__init__(name)
        self.seed = int(os.environ.get("RANDOM_SEED", "1"), 0)
        self.chk_seen: set[str] = set()
        self._stamps: list[tuple[str, int]] = []
        self._chk_order: list[tuple[str, int]] = []
        self._waits: list[tuple[str, str, str]] = []
        self._last_access = "none"
        self._accesses = 0

    def _stamp(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_order.append((chk_id, len(self._stamps)))
        self.chk_seen.add(chk_id)

    async def _rd(self, name: str, addr: int, expected: int) -> int:
        data = await self.csr_read(name, addr, expected=expected)
        self._accesses += 1
        self._last_access = f"rd {name}@0x{addr:08x} rdata=0x{data:08x} resp=OKAY"
        assert data == expected, (
            f"{name}@0x{addr:08x}: read 0x{data:08x}, expected 0x{expected:08x}"
        )
        return data

    async def _rd_any(self, name: str, addr: int) -> int:
        data = await self.csr_read(name, addr)
        self._accesses += 1
        self._last_access = f"rd {name}@0x{addr:08x} rdata=0x{data:08x} resp=OKAY"
        return data

    async def _wr(self, name: str, addr: int, data: int) -> None:
        await self.csr_write(name, addr, data)
        self._accesses += 1
        self._last_access = f"wr {name}@0x{addr:08x} wdata=0x{data:08x} resp=OKAY"

    async def _probe(self, base: int, offset: int, length: int, patterns: list[int]) -> str:
        """One drawn read-back: a 4-byte probe of a `data` word is compared, an 8-byte probe
        compares its low word (`data`; the upper word of an entry has no field in cpu_ctrl.rdl),
        the rest printed."""
        addr = base + offset
        entry, lane = divmod(offset, SCRATCH_STRIDE)
        if length == 4 and lane == 0:
            await self._rd(f"PROBE_0x{offset:02x}", addr, patterns[entry])
            return f"+0x{offset:02x} len=4 OKAY 0x{patterns[entry]:08x} cmp=pattern"
        item = SmcSysAxiItem(f"rd_PROBE_0x{offset:02x}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = length
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self._accesses += 1
        assert not item.timed_out and item.resp_code is not None, (
            f"probe +0x{offset:x}: no response"
        )
        resp = AXI_RESP_NAME.get(item.resp_code, str(item.resp_code))
        self._last_access = (
            f"rd PROBE+0x{offset:02x} len={length} rdata=0x{item.rdata:x} resp={resp}"
        )
        if length == 8 and lane == 0:
            low = item.rdata & 0xFFFF_FFFF
            assert resp == "OKAY" and low == patterns[entry], (
                f"probe +0x{offset:02x} len=8: {resp} 0x{item.rdata:x}, low word 0x{low:08x}, "
                f"expected the data word 0x{patterns[entry]:08x} of entry {entry}"
            )
            return f"+0x{offset:02x} len=8 {resp} 0x{item.rdata:x} cmp=low word"
        return f"+0x{offset:02x} len={length} {resp} 0x{item.rdata:x} cmp=printed"

    async def body(self) -> None:
        dut = cocotb.top
        assert hasattr(dut, "tb_fuse_sense_done"), "tb_fuse_sense_done not exported"
        axi_bound = self.cfg.axi_timeout_ns
        addrs = [
            smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", i)
            for i in range(SCRATCH_COUNT)
        ]
        assert len(set(addrs)) == SCRATCH_COUNT, "SCRATCH addresses are not distinct"
        assert all(a == addrs[0] + SCRATCH_STRIDE * i for i, a in enumerate(addrs)), (
            f"SCRATCH entries are not {SCRATCH_STRIDE} bytes apart: {[hex(a) for a in addrs]}"
        )
        idxs = range(SCRATCH_COUNT)
        rng = random.Random(self.seed)
        unique = draw_patterns(rng)
        walk = draw_patterns(rng)
        probes = draw_probes(rng)
        cocotb.log.info(
            "RAND-SEED: %d; RAND-DRAW: unique patterns %s; walk patterns %s; probes %s",
            self.seed,
            ",".join(f"0x{v:08x}" for v in unique),
            ",".join(f"0x{v:08x}" for v in walk),
            ",".join(f"+0x{o:02x}/{ln}" for o, ln in probes),
        )

        # S1
        await self.wait_fuse_sense_done(FUSE_SENSE_MAX_CYCLES)
        sense = int(dut.tb_fuse_sense_done.value)
        assert sense == 1, "tb_fuse_sense_done low after the wait returned"
        self._waits.append(
            (
                "fuse_sense_done",
                f"{FUSE_SENSE_MAX_CYCLES}cyc(enforced-by=seq_lib/smc_base_test_seq.py)",
                f"tb_fuse_sense_done={sense}",
            )
        )
        self._stamp("S1")

        # S2
        saved = [await self._rd_any(f"SCRATCH{i}_SAVE", addrs[i]) for i in idxs]
        self._stamp("S2")

        # S3
        for i in idxs:
            await self._wr(f"SCRATCH{i}_UNIQUE", addrs[i], unique[i])
        fwd = [await self._rd(f"SCRATCH{i}_UNIQUE_RB", addrs[i], unique[i]) for i in idxs]
        rev = [
            await self._rd(f"SCRATCH{i}_UNIQUE_RB_REV", addrs[i], unique[i]) for i in reversed(idxs)
        ]
        assert len(set(fwd)) == SCRATCH_COUNT, f"aliased unique patterns {fwd}"
        probe_lines = [await self._probe(addrs[0], o, ln, unique) for o, ln in probes]
        self._stamp("S3")

        # S4
        for i in idxs:
            await self._wr(f"SCRATCH{i}_ZERO", addrs[i], 0)
        for k in idxs:
            await self._wr(f"SCRATCH{k}_WALK", addrs[k], walk[k])
            for i in idxs:
                want = walk[k] if i == k else 0
                await self._rd(f"SCRATCH{i}_WALK{k}_RB", addrs[i], want)
            await self._wr(f"SCRATCH{k}_WALK_ZERO", addrs[k], 0)
        self._stamp("S4")

        # S5
        for pat in WIDTH_PATTERNS:
            for i in idxs:
                await self._wr(f"SCRATCH{i}_WIDTH", addrs[i], pat)
            for i in idxs:
                await self._rd(f"SCRATCH{i}_WIDTH_0x{pat:08x}_RB", addrs[i], pat)
        self._stamp("S5")

        # S6
        for i in idxs:
            await self._wr(f"SCRATCH{i}_RESTORE", addrs[i], saved[i])
        for i in idxs:
            await self._rd(f"SCRATCH{i}_RESTORE_RB", addrs[i], saved[i])
        self._waits.append(("sep_in_access", f"{axi_bound}ns", self._last_access))
        self._stamp("S6")

        self._chk(
            "CHK-SCRATCH-UNIQUE",
            f"{SCRATCH_COUNT} entries read their own drawn pattern in order and reverse "
            f"({len(set(fwd))} distinct, reverse matches {rev[::-1] == fwd}); {len(probes)} "
            f"drawn read-backs (a 4-byte probe of a data word and the low word of an 8-byte "
            f"probe compared, the rest printed): "
            + "; ".join(probe_lines)
            + "; restore returned saved words "
            + ",".join(f"0x{v:08x}" for v in saved)
            + f"; drawn=seed {self.seed} unique "
            + ",".join(f"0x{v:08x}" for v in unique)
            + " probes "
            + ",".join(f"+0x{o:02x}/{ln}" for o, ln in probes),
        )
        self._chk(
            "CHK-SCRATCH-WALK",
            f"k=0..15 wrote its drawn walk pattern to entry k alone: entry k held it and the 15 "
            f"idle entries read the 0 written before the walk (240 compares); drawn=seed "
            f"{self.seed} walk " + ",".join(f"0x{v:08x}" for v in walk),
        )
        self._chk(
            "CHK-SCRATCH-BITS",
            "all 16 entries read back "
            + ",".join(f"0x{p:08x}" for p in WIDTH_PATTERNS)
            + " exactly when written; SCRATCH entry usage by bench "
            "and firmware not specified, measured, all 16 entries swept and restored",
        )

        expected = SCRATCH_COUNT * (
            1 + 3 + 1 + (1 + SCRATCH_COUNT + 1) + 2 * len(WIDTH_PATTERNS) + 2
        ) + len(probes)
        assert self._accesses == expected, f"access count {self._accesses}, expected {expected}"
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s",
            len(self._waits),
            " ".join(f"{n}={b} last={s}" for n, b, s in self._waits),
        )
        self._chk_order.append(("CHK-TIMEOUT-PATHS", len(self._stamps)))
        self.chk_seen.add("CHK-TIMEOUT-PATHS")
        self._fence()

    def _fence(self) -> None:
        steps = [s for s, _ in self._stamps]
        assert tuple(steps) == STEP_ORDER, f"step order {steps}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing {times}"
        order = [c for c, _ in self._chk_order]
        assert tuple(order[: len(CHK_ORDER)]) == CHK_ORDER, f"checker order {order}"
        for chk_id, n_stamps in self._chk_order:
            step = CHK_STEP.get(chk_id)
            if step:
                assert n_stamps >= STEP_ORDER.index(step) + 1, f"{chk_id} printed before {step}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(FENCE_TERMS[s] for s in steps),
            ",".join(order),
            ",".join(f"{s}={t}ps" for s, t in self._stamps),
        )
        self.chk_seen.add("CHK-NONVAC")
