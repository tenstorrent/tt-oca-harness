# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CPU_CTRL MUTEX[0..3] hold, release values, independence and liveness.

Sources: hw/sys/smc/regs/blocks/cpu_ctrl/cpu_ctrl.rdl (MUTEX, MUTEX[4]), generated cpu_ctrl.h.
"""

from __future__ import annotations

import os
import random

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp
from ocah_axi_vip import AxiTimingProfile

from .smc_addr_map import cpu_ctrl_u32, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

NUM_MUTEX = 4
MUTEX_ADDR = [smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_MUTEX_BASE_ADDR", n) for n in range(NUM_MUTEX)]
MUTEX_BM = cpu_ctrl_u32("CPU_CTRL__MUTEX__MUTEX_bm")
MUTEX_FREE = cpu_ctrl_u32("CPU_CTRL__MUTEX__MUTEX_reset")

READ_BYTES = 4
WRITE_BYTES = 8
FURTHER_READS = 3
STALL_CYCLES = 32
B2B_AXI_ID = 5
FUSE_SENSE_MAX_CYCLES = 200_000

FENCE = (
    "BRINGUP_DONE",
    "HELD_READS_COMPARED",
    "RELEASE_VALUES_COMPARED",
    "INDEPENDENCE_COMPARED",
    "BACK_TO_BACK_COMPARED",
    "STALLED_RESPONSE_COMPARED",
)
FENCE_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6")
FENCE_CHECKERS = (
    None,
    "CHK-MUTEX-HELD-READS",
    "CHK-MUTEX-RELEASE-VALUES",
    "CHK-MUTEX-INDEP",
    "CHK-MUTEX-BACK2BACK",
    "CHK-MUTEX-RSTALL",
)


class smc_cpu_ctrl_mutex_all_test_seq(SmcCsrSeq):
    """MUTEX[0..3] held reads, release by any value, independence, b2b and stalled R."""

    def __init__(self, name: str = "smc_cpu_ctrl_mutex_all_test_seq") -> None:
        super().__init__(name)
        self.stamps: list[tuple[str, int]] = []
        self.chk_order: list[tuple[str, str]] = []
        self.waits: list[tuple[str, str, str]] = []
        self.last_state = "no access yet"

    def _stamp(self, step: str) -> None:
        self.stamps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str, *args) -> None:
        cocotb.log.info("%s: " + text, chk_id, *args)
        self.chk_order.append((step, chk_id))

    async def _rd(self, tag: str, n: int) -> int:
        """Read MUTEX[n] and return bit 0 of the delivered data."""
        data = await self.csr_read(tag, MUTEX_ADDR[n], length=READ_BYTES)
        self.last_state = f"{tag} MUTEX[{n}] rdata=0x{data:x}"
        return data & MUTEX_BM

    async def _wr(self, tag: str, n: int, value: int) -> None:
        await self.csr_write(tag, MUTEX_ADDR[n], value, length=WRITE_BYTES)
        self.last_state = f"{tag} MUTEX[{n}] wdata=0x{value:x}"

    def _expect(self, tag: str, got: int, exp: int) -> None:
        assert got == exp, (
            f"{tag}: MUTEX bit 0 = {got}, expected {exp} (last access: {self.last_state})"
        )

    async def body(self) -> None:
        bound_ns = self.cfg.axi_timeout_ns
        await self.wait_fuse_sense_done(FUSE_SENSE_MAX_CYCLES)
        self._stamp("S1")
        self.waits.append(
            (
                "fuse_sense_done",
                f"{FUSE_SENSE_MAX_CYCLES}cyc(enforced-by=seq_lib/smc_base_test_seq.py)",
                "assert in wait_fuse_sense_done",
            )
        )
        self.last_state = "bring-up done"

        # S2: held reads
        held_log = []
        for n in range(NUM_MUTEX):
            self._expect(f"S2 acquire n={n}", await self._rd(f"S2_ACQ{n}", n), 1)
            further = [await self._rd(f"S2_HELD{n}_{k}", n) for k in range(FURTHER_READS)]
            for k, bit in enumerate(further):
                self._expect(f"S2 held read {k} n={n}", bit, 0)
            held_log.append(f"{n}:1,{''.join(str(b) for b in further)}")
        self._stamp("S2")
        self._chk(
            "S2",
            "CHK-MUTEX-HELD-READS",
            "acquire bit0=1 then %d further reads bit0=0 per instance [%s]",
            FURTHER_READS,
            " ".join(held_log),
        )

        # S3: release by any written value. All four are held after S2.
        rng = random.Random(int(os.environ.get("RANDOM_SEED", "1"), 0))
        seeded = rng.getrandbits(64)
        values = (0x0, 0x1, 0xFFFF_FFFF_FFFF_FFFF, seeded)
        rel_log = []
        for n in range(NUM_MUTEX):
            for value in values:
                if value != values[0]:
                    self._expect(
                        f"S3 re-acquire n={n} v=0x{value:x}", await self._rd("S3_REACQ", n), 1
                    )
                self._expect(f"S3 held n={n}", await self._rd("S3_PRE", n), 0)
                await self._wr("S3_REL", n, value)
                self._expect(f"S3 after write 0x{value:x} n={n}", await self._rd("S3_POST", n), 1)
                await self._wr("S3_RELEASE0", n, 0)
            rel_log.append(str(n))
        self._stamp("S3")
        self._chk(
            "S3",
            "CHK-MUTEX-RELEASE-VALUES",
            "writes 0x0 0x1 0xffffffffffffffff 0x%x each released, next read bit0=1, "
            "instances [%s]",
            seeded,
            " ".join(rel_log),
        )

        # S4: independence
        indep_log = []
        for n in range(NUM_MUTEX):
            self._expect(f"S4 acquire n={n}", await self._rd("S4_ACQ", n), 1)
            for m in range(NUM_MUTEX):
                if m != n:
                    self._expect(f"S4 other m={m} while n={n} held", await self._rd("S4_OTH", m), 1)
            self._expect(f"S4 own n={n} still held", await self._rd("S4_OWN", n), 0)
            for m in range(NUM_MUTEX):
                await self._wr("S4_REL", m, 0)
            indep_log.append(f"{n}:others=1,own=0")
        self._stamp("S4")
        self._chk(
            "S4",
            "CHK-MUTEX-INDEP",
            "held n: other three bit0=1, own bit0=0 [%s]",
            " ".join(indep_log),
        )

        # S5: back-to-back reads under one ID
        b2b_log = []
        for n in range(NUM_MUTEX):
            items = []
            for k in range(2):
                item = SmcSysAxiItem(f"b2b_rd{n}_{k}")
                item.op = SmcSysAxiOp.READ
                item.addr = MUTEX_ADDR[n]
                item.length = READ_BYTES
                item.axi_id = B2B_AXI_ID
                items.append(item)
            group = SmcSysAxiGroupItem(f"b2b_{n}", items)
            await self.start_item(group)
            await self.finish_item(group)
            self.accesses += 2
            bits = [it.rdata & MUTEX_BM for it in items]
            self.last_state = f"b2b MUTEX[{n}] rdata=0x{items[0].rdata:x},0x{items[1].rdata:x}"
            assert bits == [1, 0], (
                f"S5 n={n}: back-to-back bit0 = {bits}, expected [1, 0] ({self.last_state})"
            )
            await self._wr("S5_REL", n, 0)
            b2b_log.append(f"{n}:{bits[0]},{bits[1]}")
        self._stamp("S5")
        self._chk(
            "S5",
            "CHK-MUTEX-BACK2BACK",
            "id=%d two reads bit0 first,second [%s] within %dns bound",
            B2B_AXI_ID,
            " ".join(b2b_log),
            bound_ns,
        )

        # S6: response held off
        stall_log = []
        for n in range(NUM_MUTEX):
            item = SmcSysAxiItem(f"stall_rd{n}")
            item.op = SmcSysAxiOp.READ
            item.addr = MUTEX_ADDR[n]
            item.length = READ_BYTES
            item.timing = AxiTimingProfile(r_ready_delay=STALL_CYCLES)
            await self.start_item(item)
            await self.finish_item(item)
            self.accesses += 1
            delivered = item.rdata & MUTEX_BM
            self.last_state = f"stalled MUTEX[{n}] rdata=0x{item.rdata:x}"
            self._expect(f"S6 delivered n={n}", delivered, 1)
            later = await self._rd("S6_LATER", n)
            self._expect(f"S6 later n={n}", later, 0)
            await self._wr("S6_REL", n, 0)
            stall_log.append(f"{n}:{delivered},{later}")
        self._stamp("S6")
        self._chk(
            "S6",
            "CHK-MUTEX-RSTALL",
            "r_ready_delay=%d cycles delivered bit0, later bit0 [%s]",
            STALL_CYCLES,
            " ".join(stall_log),
        )

        # Release state check: every mutex is free again.
        for n in range(NUM_MUTEX):
            self._expect(f"final free n={n}", await self._rd("FINAL", n), 1)
            await self._wr("FINAL_REL", n, 0)

        self._fence()
        self._timeout_paths(bound_ns)

    def _fence(self) -> None:
        steps = [s for s, _ in self.stamps]
        assert steps == list(FENCE_STEPS), f"step stamps {steps}, expected {list(FENCE_STEPS)}"
        times = [t for _, t in self.stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        expected_chk = [c for c in FENCE_CHECKERS if c]
        assert [c for _, c in self.chk_order] == expected_chk, (
            f"checker lines {[c for _, c in self.chk_order]}, expected {expected_chk}"
        )
        stamp_of = dict(self.stamps)
        for step, chk_id in self.chk_order:
            assert stamp_of[step] >= times[0], f"{chk_id} printed before bring-up"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(FENCE),
            ", ".join(expected_chk),
            ", ".join(f"{s}={t}" for s, t in self.stamps),
        )

    def _timeout_paths(self, bound_ns: int) -> None:
        self.waits.append(
            (
                "sep_in_axi_access",
                f"{bound_ns}ns",
                "driver raises on no-response",
            )
        )
        waits = self.waits
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s",
            len(self.waits),
            " ".join(f"{n}={b} fail-on-expiry={e} last={self.last_state}" for n, b, e in waits),
        )
