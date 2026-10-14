# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CPU_CTRL SEMA[0..3] signed accumulate, independence, wrap and pipelined writes.

Sources: hw/sys/smc/regs/blocks/cpu_ctrl/cpu_ctrl.rdl (SEMA, SEMA[4]), generated cpu_ctrl.h.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

NUM_SEMA = 4
SEMA_ADDR = [smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SEMA_BASE_ADDR", n) for n in range(NUM_SEMA)]
ACCESS_BYTES = 4
WORD_MASK = 0xFFFF_FFFF
PIPELINED_WRITES = 8
FUSE_SENSE_MAX_CYCLES = 200_000

FENCE = (
    "BRINGUP_DONE",
    "SEQUENCE_COMPARED",
    "INSTANCES_COMPARED",
    "NEGATIVE_MEASURED",
    "WRAP_MEASURED",
    "UPPER_BITS_MEASURED",
    "PIPELINED_COMPARED",
)
FENCE_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
FENCE_CHECKERS = (
    None,
    "CHK-SEMA-SEQ",
    "CHK-SEMA-INDEP",
    "CHK-SEMA-NEG",
    "CHK-SEMA-WRAP",
    "CHK-SEMA-UPPER",
    "CHK-SEMA-PIPELINED",
)


def _neg(value: int) -> int:
    return (-value) & WORD_MASK


class smc_cpu_ctrl_sema_test_seq(SmcCsrSeq):
    """SEMA signed accumulate; values the RDL does not state are measured and printed."""

    def __init__(self, name: str = "smc_cpu_ctrl_sema_test_seq") -> None:
        super().__init__(name)
        self.stamps: list[tuple[str, int]] = []
        self.chk_order: list[tuple[str, str, int]] = []
        self.waits: list[tuple[str, str, str]] = []
        self.last_state = "no access yet"

    def _stamp(self, step: str) -> None:
        self.stamps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str, *args) -> None:
        cocotb.log.info("%s: " + text, chk_id, *args)
        self.chk_order.append((step, chk_id, len(self.stamps)))

    async def _rd(self, tag: str, n: int, expected: int | None = None) -> int:
        data = await self.csr_read(tag, SEMA_ADDR[n], expected=expected, length=ACCESS_BYTES)
        self.last_state = f"{tag} SEMA[{n}] rdata=0x{data:x}"
        if expected is not None:
            assert data == expected, (
                f"{tag}: SEMA[{n}] read 0x{data:x}, expected 0x{expected:x} "
                f"(last access: {self.last_state})"
            )
        return data

    async def _wr(self, tag: str, n: int, value: int) -> None:
        value &= WORD_MASK
        await self.csr_write(tag, SEMA_ADDR[n], value, length=ACCESS_BYTES)
        self.last_state = f"{tag} SEMA[{n}] wdata=0x{value:x}"

    async def _rd_twice(self, tag: str, n: int) -> int:
        first = await self._rd(f"{tag}_A", n)
        second = await self._rd(f"{tag}_B", n)
        assert first == second, (
            f"{tag}: SEMA[{n}] reads disagree 0x{first:x} vs 0x{second:x} "
            f"(last access: {self.last_state})"
        )
        return first

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

        # S2: running signed sum on SEMA[0]
        sums = []
        for tag, delta, exp in (("P5", 5, 5), ("P3", 3, 8), ("M2", -2, 6)):
            await self._wr(f"S2_{tag}", 0, delta)
            sums.append(await self._rd(f"S2_{tag}_RD", 0, expected=exp))
        await self._wr("S2_M6", 0, -6)
        final = await self._rd("S2_FINAL", 0, expected=0)
        self._stamp("S2")
        self._chk(
            "S2",
            "CHK-SEMA-SEQ",
            "SEMA[0] reads %s after +5 +3 -2 and %d after -6",
            ",".join(str(s) for s in sums),
            final,
        )

        # S3: four instances
        deltas = (1, 2, 3, 4)
        for n, d in enumerate(deltas):
            await self._wr(f"S3_W{n}", n, d)
        got = [await self._rd(f"S3_R{n}", n, expected=deltas[n]) for n in range(NUM_SEMA)]
        for n, d in enumerate(deltas):
            await self._wr(f"S3_N{n}", n, -d)
        back = [await self._rd(f"S3_Z{n}", n, expected=0) for n in range(NUM_SEMA)]
        self._stamp("S3")
        self._chk(
            "S3",
            "CHK-SEMA-INDEP",
            "SEMA[0..3] read %s after +1 +2 +3 +4 and %s after the negations, addresses %s",
            got,
            back,
            ",".join(f"0x{a:x}" for a in SEMA_ADDR),
        )

        # S4: below zero
        await self._wr("S4_NEG1", 0, -1)
        neg_a = await self._rd("S4_A", 0)
        neg_b = await self._rd("S4_B", 0)
        assert neg_a == neg_b, f"S4: reads disagree 0x{neg_a:x} vs 0x{neg_b:x}"
        await self._wr("S4_RESTORE", 0, 1)
        neg_final = await self._rd("S4_FINAL", 0, expected=0)
        self._stamp("S4")
        self._chk(
            "S4",
            "CHK-SEMA-NEG",
            "SEMA[0] after -1 from 0 reads 0x%x twice (not specified, measured); restore by "
            "writing 0x1, final read 0x%x (asserted 0)",
            neg_a,
            neg_final,
        )

        # S5: 16-bit boundaries
        for tag, d in (("L1", 16383), ("L2", 16383), ("L3", 1)):
            await self._wr(f"S5_{tag}", 0, d)
        at_max = await self._rd("S5_MAX", 0, expected=0x7FFF)
        await self._wr("S5_OVER", 0, 1)
        over = await self._rd_twice("S5_OVER_RD", 0)
        await self._wr("S5_RESTORE1", 0, _neg(over))
        mid = await self._rd("S5_MID", 0)
        await self._wr("S5_MIN1", 0, -32768)
        await self._wr("S5_MIN2", 0, -1)
        under = await self._rd_twice("S5_UNDER_RD", 0)
        await self._wr("S5_RESTORE2", 0, _neg(under))
        wrap_final = await self._rd_twice("S5_FINAL", 0)
        self._stamp("S5")
        self._chk(
            "S5",
            "CHK-SEMA-WRAP",
            "SEMA[0] after +32767 reads 0x%x; after one more +1 reads 0x%x; restore read 0x%x; "
            "after -32768 and -1 reads 0x%x; final read 0x%x (0x7fff asserted, the other values "
            "not specified, measured)",
            at_max,
            over,
            mid,
            under,
            wrap_final,
        )

        # S6: bits above [15:0]
        await self._wr("S6_UPPER", 0, 0x0001_0005)
        upper = await self._rd_twice("S6_RD", 0)
        await self._wr("S6_RESTORE", 0, _neg(upper))
        upper_final = await self._rd_twice("S6_FINAL", 0)
        self._stamp("S6")
        self._chk(
            "S6",
            "CHK-SEMA-UPPER",
            "SEMA[0] after write 0x00010005 reads 0x%x twice; restore by writing 0x%x, final read "
            "0x%x (not specified, measured)",
            upper,
            _neg(upper),
            upper_final,
        )

        # S7: eight writes to SEMA[1] as one group item
        await self._rd("S7_PRE", 1, expected=0)
        items = []
        for k in range(PIPELINED_WRITES):
            item = SmcSysAxiItem(f"pipe_wr{k}")
            item.op = SmcSysAxiOp.WRITE
            item.addr = SEMA_ADDR[1]
            item.length = ACCESS_BYTES
            item.wdata = 1
            items.append(item)
        group = SmcSysAxiGroupItem("sema_pipelined", items)
        await self.start_item(group)
        await self.finish_item(group)
        self.accesses += PIPELINED_WRITES
        self.last_state = f"{PIPELINED_WRITES} grouped writes of +1 to SEMA[1] completed"
        total = await self._rd("S7_SUM", 1, expected=PIPELINED_WRITES)
        await self._wr("S7_NEG8", 1, -PIPELINED_WRITES)
        zero = await self._rd("S7_ZERO", 1, expected=0)
        self._stamp("S7")
        self._chk(
            "S7",
            "CHK-SEMA-PIPELINED",
            "%d +1 writes issued as one group item (overlap not measured) completed within the "
            "%dns bound; SEMA[1] reads %d, "
            "then %d after -%d",
            PIPELINED_WRITES,
            bound_ns,
            total,
            zero,
            PIPELINED_WRITES,
        )

        self._fence()
        self._timeout_paths(bound_ns)

    def _fence(self) -> None:
        steps = [s for s, _ in self.stamps]
        assert steps == list(FENCE_STEPS), f"step stamps {steps}, expected {list(FENCE_STEPS)}"
        times = [t for _, t in self.stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        expected_chk = [c for c in FENCE_CHECKERS if c]
        assert [c for _, c, _ in self.chk_order] == expected_chk, (
            f"checker lines {[c for _, c, _ in self.chk_order]}, expected {expected_chk}"
        )
        for step, chk_id, n_stamps in self.chk_order:
            assert n_stamps == FENCE_STEPS.index(step) + 1, (
                f"{chk_id} printed after {n_stamps} step stamps, expected "
                f"{FENCE_STEPS.index(step) + 1} for {step}"
            )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(FENCE),
            ", ".join(expected_chk),
            ", ".join(f"{s}={t}" for s, t in self.stamps),
        )

    def _timeout_paths(self, bound_ns: int) -> None:
        self.waits.append(("sep_in_axi_access", f"{bound_ns}ns", "driver raises on no-response"))
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s",
            len(self.waits),
            " ".join(
                f"{n}={b} fail-on-expiry={e} last={self.last_state}" for n, b, e in self.waits
            ),
        )
