# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smc_cpu_ctrl_dummy_rom_test: DUMMY_ROM, DUMMY_ROM_NULL and RESET_VECTOR storage.

Sources: hw/sys/smc/regs/blocks/cpu_ctrl/cpu_ctrl.rdl, hw/sys/smc/regs/gen/c/smc_addr.h,
hw/sys/smc/regs/gen/adoc/blocks/cpu_ctrl.adoc.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

WORD_BYTES = 8
ROM_WORDS = 4
NULL_WORDS = 4
RV_WORDS = 4
OKAY = 0
FUSE_SENSE_MAX_CYCLES = 200_000
EXPECTED_LINE = (
    0x0145_0513_0000_0517,
    0xFFF0_0693_3055_1073,
    0x1050_0073_3046_B073,
    0x0000_0000_FFDF_F06F,
    0,
    0,
    0,
    0,
)
RV_RESET = 0xC004_0000
RV_MASK = (1 << 56) - 1
NULL_RESET = 0
FULL_MASK = (1 << 64) - 1
RV_PATTERNS = (RV_MASK, 0, *(1 << b for b in range(56)))
NULL_PATTERNS = (FULL_MASK, 0, *(1 << b for b in range(64)))
CORE_RESET_MASK = 0xF
UNCORE_RESET = 1 << 8
DEBUG_RESET = 1 << 24
STEP_ORDER = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
FENCE_TERMS = {
    "S1": "FUSE-SENSE",
    "S2": "RESET-VALUES",
    "S3": "EXISTING-LEGS",
    "S4": "CORES-HELD",
    "S5": "VECTOR-PATTERNS",
    "S6": "NULL-PATTERNS",
    "S7": "RESTORED",
}
EXISTING_LEG_ORDER = ("LINE_READ_COMPARED", "PATTERNS_COMPARED", "WORDS_RESTORED")
# Each checker prints after the stamp of this step and before the next stamp.
CHK_AFTER = {
    "CHK-CPU-RV-RESET": "S2",
    "CHK-CPU-NULL-RESET": "S2",
    "CHK-DROM-LINE": "S2",
    "CHK-DROM-RW": "S2",
    "CHK-CPU-CORES-HELD": "S4",
    "CHK-CPU-RV-PATTERN": "S5",
    "CHK-CPU-NULL-PATTERN": "S6",
    "CHK-CPU-RESTORE": "S7",
}
CHK_ORDER = tuple(CHK_AFTER)
S2_ACCESSES = RV_WORDS + NULL_WORDS
S3_ACCESSES = (ROM_WORDS + NULL_WORDS) * 6
S4_ACCESSES = 3
S5_ACCESSES = RV_WORDS * len(RV_PATTERNS) * 2
S6_ACCESSES = NULL_WORDS * len(NULL_PATTERNS) * 2
S7_ACCESSES = (RV_WORDS + NULL_WORDS) * 2 + 2
TOTAL_ACCESSES = S2_ACCESSES + S3_ACCESSES + S4_ACCESSES + S5_ACCESSES + S6_ACCESSES + S7_ACCESSES


def _word_addr(index: int) -> int:
    if index < ROM_WORDS:
        return smc_addr(f"SMC_TOP_SMC_CPU_CTRL_DUMMY_ROM_{index}_BASE_ADDR")
    return smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_DUMMY_ROM_NULL_BASE_ADDR", index - ROM_WORDS)


def _word_name(index: int) -> str:
    if index < ROM_WORDS:
        return f"DUMMY_ROM_{index}"
    return f"DUMMY_ROM_NULL[{index - ROM_WORDS}]"


def _rv_addr(index: int) -> int:
    return smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_RESET_VECTOR_BASE_ADDR", index)


def _null_addr(index: int) -> int:
    return smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_DUMMY_ROM_NULL_BASE_ADDR", index)


def _reset_ctrl_addr() -> int:
    return smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_CTRL_BASE_ADDR")


def _pattern(index: int) -> int:
    return 0x5A5A_0000_0000_0000 | (index << 32) | 0x1111_1111


def _upper(value: int) -> str:
    return f"0x{value >> 56:02x}"


class smc_cpu_ctrl_dummy_rom_test_seq(SmcCsrSeq):
    """Check the dummy boot-ROM words, then walk RESET_VECTOR and DUMMY_ROM_NULL with the cores held."""

    def __init__(self, name: str = "smc_cpu_ctrl_dummy_rom_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: set[str] = set()
        self._stamps: list[tuple[str, int, int]] = []
        self._leg_stamps: list[tuple[str, int]] = []
        self._chk_order: list[tuple[str, int]] = []
        self._waits: list[tuple[str, str, str]] = []
        self._last_access = "none"
        self._last_resp = OKAY
        self._s1_probe_samples = 0

    def _stamp(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps")), self.accesses))

    def _leg_stamp(self, term: str) -> None:
        self._leg_stamps.append((term, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_order.append((chk_id, len(self._stamps)))
        self.chk_seen.add(chk_id)

    async def _rd(self, name: str, addr: int) -> int:
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = WORD_BYTES
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self._last_resp = item.resp_code
        self._last_access = f"read {name}@0x{addr:08x} resp={item.resp_code} rdata=0x{item.rdata:x}"
        assert item.resp_code == OKAY, f"CPU_CTRL read not OKAY: {self._last_access}"
        return item.rdata

    async def _wr(self, name: str, addr: int, data: int) -> None:
        item = SmcSysAxiItem(f"wr_{name}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = WORD_BYTES
        item.wdata = data
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self._last_resp = item.resp_code
        self._last_access = f"write {name}@0x{addr:08x} resp={item.resp_code} wdata=0x{data:x}"
        assert item.resp_code == OKAY, f"CPU_CTRL write not OKAY: {self._last_access}"

    async def _read(self, index: int) -> int:
        return await self._rd(_word_name(index), _word_addr(index))

    async def _write(self, index: int, data: int) -> None:
        await self._wr(_word_name(index), _word_addr(index), data)

    async def _expect(self, index: int, expected: int, what: str) -> None:
        got = await self._read(index)
        assert got == expected, (
            f"{what} {_word_name(index)}@0x{_word_addr(index):08x}: expected 0x{expected:x}, "
            f"got 0x{got:x}; last access {self._last_access}"
        )

    async def body(self) -> None:
        axi_bound = self.cfg.axi_timeout_ns

        # S1
        await self.wait_fuse_sense_done(FUSE_SENSE_MAX_CYCLES)
        sense = int(cocotb.top.tb_fuse_sense_done.value)
        self._s1_probe_samples += 1
        assert sense == 1, "tb_fuse_sense_done low after the wait returned"
        self._waits.append(
            (
                "fuse_sense_done",
                f"{FUSE_SENSE_MAX_CYCLES}cyc(enforced-by=seq_lib/smc_base_test_seq.py,"
                "on-expiry=AssertionError)",
                f"tb_fuse_sense_done={sense}",
            )
        )
        self._stamp("S1")

        await self._reset_values()

        await self._existing_legs()
        self._stamp("S3")

        reset_ctrl = await self._hold_cores()
        await self._vector_patterns()
        await self._null_patterns()
        await self._restore(reset_ctrl, axi_bound)

        self.assert_all_reachable(TOTAL_ACCESSES, "CPU_CTRL")
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s; no expiry",
            len(self._waits),
            " ".join(f"{n}={b} last={s}" for n, b, s in self._waits),
        )
        self._chk_order.append(("CHK-TIMEOUT-PATHS", len(self._stamps)))
        self.chk_seen.add("CHK-TIMEOUT-PATHS")
        self._fence()

    async def _reset_values(self) -> None:
        rv_seen = []
        for index in range(RV_WORDS):
            name = f"RESET_VECTOR[{index}]"
            got = await self._rd(name, _rv_addr(index))
            assert got & RV_MASK == RV_RESET, (
                f"reset {name}@0x{_rv_addr(index):08x}: expected vector[55:0]=0x{RV_RESET:x}, "
                f"got 0x{got & RV_MASK:x}; last access {self._last_access}"
            )
            rv_seen.append(f"{name}=0x{got:x}(rresp={self._last_resp},[63:56]={_upper(got)})")
        null_seen = []
        for index in range(NULL_WORDS):
            name = f"DUMMY_ROM_NULL[{index}]"
            got = await self._rd(name, _null_addr(index))
            assert got == NULL_RESET, (
                f"reset {name}@0x{_null_addr(index):08x}: expected 0x{NULL_RESET:x}, "
                f"got 0x{got:x}; last access {self._last_access}"
            )
            null_seen.append(f"{name}=0x{got:x}(rresp={self._last_resp})")
        self._stamp("S2")
        self._chk(
            "CHK-CPU-RV-RESET",
            f"{RV_WORDS} first reads vector[55:0]=0x{RV_RESET:x} RRESP OKAY: "
            + " ".join(rv_seen)
            + " ([63:56] logged, not compared: LINKED-ISSUE SF-001)",
        )
        self._chk(
            "CHK-CPU-NULL-RESET",
            f"{NULL_WORDS} reads before any write equal 0x0 RRESP OKAY: " + " ".join(null_seen),
        )

    async def _existing_legs(self) -> None:
        count = ROM_WORDS + NULL_WORDS
        assert len(EXPECTED_LINE) == count

        original = []
        for index in range(count):
            word = await self._read(index)
            assert word == EXPECTED_LINE[index], (
                f"line {_word_name(index)}@0x{_word_addr(index):08x}: expected "
                f"0x{EXPECTED_LINE[index]:x}, got 0x{word:x}; last access {self._last_access}"
            )
            original.append(word)
        self._leg_stamp("LINE_READ_COMPARED")
        self._chk(
            "CHK-DROM-LINE",
            f"{count} consecutive 64-bit words from 0x{_word_addr(0):08x} compared: "
            + " ".join(f"{_word_name(i)}=0x{w:x}" for i, w in enumerate(original))
            + " (the four zero words are reset values; X/Z not observable under Verilator)",
        )

        for index in range(count):
            await self._write(index, _pattern(index))
        for index in range(count):
            await self._expect(index, _pattern(index), "pattern in-order")
        for index in reversed(range(count)):
            await self._expect(index, _pattern(index), "pattern reverse-order")
        self._leg_stamp("PATTERNS_COMPARED")

        for index in range(count):
            await self._write(index, original[index])
        for index in range(count):
            await self._expect(index, original[index], "restore")
        self._leg_stamp("WORDS_RESTORED")
        self._chk(
            "CHK-DROM-RW",
            f"{count} registers each read back own pattern in order and reverse order "
            + ",".join(f"0x{_pattern(i):x}" for i in range(count))
            + "; restore returned the S2 words (sw=rw per cpu_ctrl.rdl)",
        )

    async def _hold_cores(self) -> int:
        addr = _reset_ctrl_addr()
        before = await self._rd("RESET_CTRL", addr)
        held = before & ~CORE_RESET_MASK
        await self._wr("RESET_CTRL", addr, held)
        bresp = self._last_resp
        after = await self._rd("RESET_CTRL", addr)
        rresp = self._last_resp
        keep = UNCORE_RESET | DEBUG_RESET
        assert after & CORE_RESET_MASK == 0, (
            f"RESET_CTRL core resets [3:0]=0x{after & CORE_RESET_MASK:x} after writing 0x{held:x}; "
            f"last access {self._last_access}"
        )
        assert after & keep == before & keep, (
            f"RESET_CTRL [8]/[24] read 0x{after & keep:x}, expected 0x{before & keep:x} "
            f"(value before the write 0x{before:x}); last access {self._last_access}"
        )
        self._stamp("S4")
        self._chk(
            "CHK-CPU-CORES-HELD",
            f"RESET_CTRL read 0x{before:x}, wrote 0x{held:x} (BRESP {bresp}), read back "
            f"0x{after:x} (RRESP {rresp}): [3:0]=0x0, [8]={(after >> 8) & 1} and "
            f"[24]={(after >> 24) & 1} equal the value read",
        )
        return before

    async def _vector_patterns(self) -> None:
        uppers: set[int] = set()
        checked = 0
        for index in range(RV_WORDS):
            name = f"RESET_VECTOR[{index}]"
            addr = _rv_addr(index)
            for word in RV_PATTERNS:
                await self._wr(name, addr, word)
                got = await self._rd(name, addr)
                assert got & RV_MASK == word & RV_MASK, (
                    f"pattern {name}@0x{addr:08x}: wrote 0x{word:x}, vector[55:0] read "
                    f"0x{got & RV_MASK:x}; last access {self._last_access}"
                )
                uppers.add(got >> 56)
                checked += 1
        assert checked == RV_WORDS * len(RV_PATTERNS)
        self._stamp("S5")
        self._chk(
            "CHK-CPU-RV-PATTERN",
            f"cores held; {checked} readbacks of RESET_VECTOR[0..3] equal the written [55:0] "
            f"(0x{RV_MASK:x}, 0x0, 1<<b b=0..55) BRESP/RRESP OKAY; [63:56] observed "
            + ",".join(f"0x{u:02x}" for u in sorted(uppers))
            + " (logged, not compared: LINKED-ISSUE SF-001)",
        )

    async def _null_patterns(self) -> None:
        checked = 0
        for index in range(NULL_WORDS):
            name = f"DUMMY_ROM_NULL[{index}]"
            addr = _null_addr(index)
            for word in NULL_PATTERNS:
                await self._wr(name, addr, word)
                got = await self._rd(name, addr)
                assert got == word, (
                    f"pattern {name}@0x{addr:08x}: wrote 0x{word:x}, read 0x{got:x}; "
                    f"last access {self._last_access}"
                )
                checked += 1
        assert checked == NULL_WORDS * len(NULL_PATTERNS)
        self._stamp("S6")
        self._chk(
            "CHK-CPU-NULL-PATTERN",
            f"cores held; {checked} readbacks of DUMMY_ROM_NULL[0..3] equal the 64-bit word "
            f"written (0x{FULL_MASK:x}, 0x0, 1<<b b=0..63) BRESP/RRESP OKAY",
        )

    async def _restore(self, reset_ctrl: int, axi_bound: int) -> None:
        for index in range(RV_WORDS):
            await self._wr(f"RESET_VECTOR[{index}]", _rv_addr(index), RV_RESET)
        for index in range(NULL_WORDS):
            await self._wr(f"DUMMY_ROM_NULL[{index}]", _null_addr(index), NULL_RESET)
        seen = []
        for index in range(RV_WORDS):
            name = f"RESET_VECTOR[{index}]"
            got = await self._rd(name, _rv_addr(index))
            assert got & RV_MASK == RV_RESET, (
                f"restore {name}: vector[55:0] read 0x{got & RV_MASK:x}, expected "
                f"0x{RV_RESET:x}; last access {self._last_access}"
            )
            seen.append(f"{name}=0x{got:x}")
        for index in range(NULL_WORDS):
            name = f"DUMMY_ROM_NULL[{index}]"
            got = await self._rd(name, _null_addr(index))
            assert got == NULL_RESET, (
                f"restore {name}: read 0x{got:x}, expected 0x{NULL_RESET:x}; "
                f"last access {self._last_access}"
            )
            seen.append(f"{name}=0x{got:x}")
        addr = _reset_ctrl_addr()
        await self._wr("RESET_CTRL", addr, reset_ctrl)
        got = await self._rd("RESET_CTRL", addr)
        assert got == reset_ctrl, (
            f"restore RESET_CTRL: read 0x{got:x}, expected the S4 value 0x{reset_ctrl:x}; "
            f"last access {self._last_access}"
        )
        self._waits.append(
            (
                "sep_in_access",
                f"{axi_bound}ns(enforced-by=env/smc_sys_axi_agent.py,on-expiry=AssertionError)",
                self._last_access,
            )
        )
        self._stamp("S7")
        self._chk(
            "CHK-CPU-RESTORE",
            "before RESET_CTRL write-back: "
            + " ".join(seen)
            + f"; then RESET_CTRL read 0x{got:x} = S4 value 0x{reset_ctrl:x}",
        )

    def _fence(self) -> None:
        steps = [s for s, _, _ in self._stamps]
        assert tuple(steps) == STEP_ORDER, f"step order {steps}"
        times = [t for _, t, _ in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing {times}"
        counts = [self._s1_probe_samples] + [
            b - a for (_, _, a), (_, _, b) in zip(self._stamps, self._stamps[1:])
        ]
        assert all(c > 0 for c in counts), f"a fence term has no access: {counts}"
        legs = [n for n, _ in self._leg_stamps]
        assert tuple(legs) == EXISTING_LEG_ORDER, f"existing-leg order {legs}"
        leg_times = [t for _, t in self._leg_stamps]
        assert times[1] < leg_times[0] and leg_times[-1] <= times[2], (
            f"existing legs {leg_times} outside S2..S3 {times[1]}..{times[2]}"
        )
        assert all(b > a for a, b in zip(leg_times, leg_times[1:])), (
            f"existing-leg stamps not increasing {leg_times}"
        )
        order = [c for c, _ in self._chk_order]
        assert tuple(order[: len(CHK_ORDER)]) == CHK_ORDER, f"checker order {order}"
        for chk_id, n_stamps in self._chk_order:
            step = CHK_AFTER.get(chk_id)
            if step:
                assert n_stamps == STEP_ORDER.index(step) + 1, (
                    f"{chk_id} printed outside the step after {step}"
                )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; existing legs %s; checker lines %s; stamps %s",
            " < ".join(FENCE_TERMS[s] for s in steps),
            " < ".join(f"{n}={t}ps" for n, t in self._leg_stamps),
            ",".join(order),
            ",".join(
                f"{FENCE_TERMS[s]}={t}ps/{c}{'probe' if s == 'S1' else 'acc'}"
                for (s, t, _), c in zip(self._stamps, counts)
            ),
        )
        self.chk_seen.add("CHK-NONVAC")
