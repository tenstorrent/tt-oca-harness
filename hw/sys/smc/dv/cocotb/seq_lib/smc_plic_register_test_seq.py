# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC_CPU_CTRL_025 / smc_plic_register_test: PLIC register map behaviour over SEP_IN.

Scenarios: CPUCTRL-PLICREG.S1 (PRIORITY), S2 (PENDING), S3 (ENABLE), S4 (THRESHOLD), S5 (CLAIM).
Sources: hw/sys/smc/regs/blocks/plic/plic.rdl, hw/sys/smc/doc/interrupts.adoc,
hw/sys/smc/doc/memmap.adoc, hw/sys/smc/doc/fabric.adoc (REGION_SIZE).
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import REGION_SIZE_RESET, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

OKAY = 0
FUSE_SENSE_MAX_CYCLES = 200_000
REGION_SIZE_256M = 0x1000_0000
ALL_ONES_32 = 0xFFFF_FFFF
REGION_SIZE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
PLIC = "SMC_TOP_SMC_CLUSTER_PLIC_"
CONTEXT_NAMES = tuple(f"CORE{n}_{kind}" for kind in ("MEIP", "SEIP") for n in range(4))
PENDING_WORDS = 11
PLIC_SOURCES = 336
PRIORITY_SOURCES = (1, 2, 328, 329, 332, 333, 336)
PRIORITY_PROBED = (1, 2)
PENDING_CHECKED = (0, 10)
ENABLE_CONTEXTS = (0, 3, 4, 7)
ENABLE_WORDS = (0, 10)
CLAIM_CONTEXTS = tuple(range(8))
STEP_ORDER = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S7R")
FENCE_TERMS = {
    "S1": "BRINGUP_DONE",
    "S2": "REGION_SIZE_WIDENED",
    "S3": "PRIORITY_COMPARED",
    "S4": "PENDING_COMPARED",
    "S5": "ENABLE_COMPARED",
    "S6": "THRESHOLD_COMPARED",
    "S7": "CLAIM_COMPARED",
    "S7R": "REGION_SIZE_RESTORED",
}
CHK_ORDER = (
    ("CHK-PLICREG-PRIORITY", "S3"),
    ("CHK-PLICREG-PENDING", "S4"),
    ("CHK-PLICREG-ENABLE", "S5"),
    ("CHK-PLICREG-THRESHOLD", "S6"),
    ("CHK-PLICREG-CLAIM", "S7"),
    ("CHK-TIMEOUT-PATHS", "S7R"),
)


def _priority_addr(k: int) -> int:
    return smc_indexed_addr(PLIC + "PRIORITY_BASE_ADDR", k)


def _pending_addr(word: int) -> int:
    return smc_indexed_addr(PLIC + "PENDING_BASE_ADDR", word)


def _enable_addr(ctx: int, word: int) -> int:
    return smc_indexed_addr(PLIC + f"{CONTEXT_NAMES[ctx]}_ENABLE_BASE_ADDR", word)


def _threshold_addr(ctx: int) -> int:
    return smc_addr(PLIC + f"{CONTEXT_NAMES[ctx]}_THRESHOLD_BASE_ADDR")


def _claim_addr(ctx: int) -> int:
    return smc_addr(PLIC + f"{CONTEXT_NAMES[ctx]}_CLAIM_COMPLETE_BASE_ADDR")


def _enable_mask(word: int) -> int:
    """Bits of an ENABLE word that carry source IDs 1..PLIC_SOURCES (ID 0 is no interrupt)."""
    mask = 0
    for bit in range(32):
        source = 32 * word + bit
        if 1 <= source <= PLIC_SOURCES:
            mask |= 1 << bit
    return mask


def _enable_pattern(ctx: int, word: int) -> int:
    raw = 0xA5C3_0000 ^ (ctx << 20) ^ (word << 12) ^ (ctx * 0x0101) ^ 0x5A5A
    return raw & _enable_mask(word)


class smc_plic_register_test_seq(SmcCsrSeq):
    """Drive the PLIC registers over SEP_IN and compare them with the exported PLIC probes."""

    def __init__(self, name: str = "smc_plic_register_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: set[str] = set()
        self._stamps: list[tuple[str, int]] = []
        self._chk_order: list[tuple[str, int]] = []
        self._waits: list[tuple[str, str, str]] = []
        self._last_access = "none"

    def _stamp(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_order.append((chk_id, len(self._stamps)))
        self.chk_seen.add(chk_id)

    @staticmethod
    def _probe(name: str) -> tuple[int, int]:
        sig = getattr(cocotb.top, name)
        assert sig.value.is_resolvable, f"{name} is X/Z: {sig.value}"
        return int(sig.value), len(sig.value)

    async def _read(self, name: str, addr: int, length: int = 4) -> int:
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = length
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self._last_access = f"{name}@0x{addr:08x} resp={item.resp_code} rdata=0x{item.rdata:x}"
        assert item.resp_code == OKAY, f"read not OKAY: {self._last_access}"
        return item.rdata

    async def _write(self, name: str, addr: int, data: int, length: int = 4) -> None:
        await self.csr_write(name, addr, data, length=length)
        self._last_access = f"{name}@0x{addr:08x} wdata=0x{data:x} written"

    async def _read_expect(self, name: str, addr: int, expected: int) -> None:
        got = await self._read(name, addr)
        assert got == expected, f"{name}@0x{addr:08x} read 0x{got:x} expected 0x{expected:x}"

    async def body(self) -> None:
        dut = cocotb.top
        for sig in (
            "tb_plic_priority_low",
            "tb_plic_pending_low",
            "tb_plic_enables0_w0",
            "tb_plic_threshold0",
            "tb_plic_claim0",
        ):
            assert hasattr(dut, sig), f"{sig} not exported"
        axi_bound = self.cfg.axi_timeout_ns

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
        await self._write("REGION_SIZE_256M", REGION_SIZE, REGION_SIZE_256M)
        await self._read_expect("REGION_SIZE_256M_RB", REGION_SIZE, REGION_SIZE_256M)
        self._stamp("S2")

        # S3
        saved_prio = {}
        probe_notes = []
        for k in PRIORITY_SOURCES:
            addr = _priority_addr(k)
            saved_prio[k] = await self._read(f"PRIORITY{k}_SAVE", addr)
            for value in range(8):
                await self._write(f"PRIORITY{k}_{value}", addr, value)
                await self._read_expect(f"PRIORITY{k}_{value}_RB", addr, value)
                if k in PRIORITY_PROBED:
                    probe, width = self._probe("tb_plic_priority_low")
                    got = (probe >> (k - 1)) & 0x1
                    assert got == value & 1, (
                        f"tb_plic_priority_low=0x{probe:x} ({width} bits) field {k} = {got}, "
                        f"PRIORITY[{k}] read {value}"
                    )
                    probe_notes.append(f"{k}:{value}->0x{probe:x}")
            await self._write(f"PRIORITY{k}_RESTORE", addr, saved_prio[k])
            await self._read_expect(f"PRIORITY{k}_RESTORE_RB", addr, saved_prio[k])
        self._stamp("S3")
        self._chk(
            "CHK-PLICREG-PRIORITY",
            f"PRIORITY[k] for k={list(PRIORITY_SOURCES)} read back every value 0..7, "
            f"tb_plic_priority_low bit (k-1) = PRIORITY[k] bit 0 agreed for "
            f"k={list(PRIORITY_PROBED)} "
            f"({len(probe_notes)} samples); reset values open (SF-021) saved="
            f"{ {k: hex(v) for k, v in saved_prio.items()} }",
        )

        # S4
        before = {}
        after = {}
        for w in PENDING_CHECKED:
            before[w] = await self._read(f"PENDING{w}_BEFORE", _pending_addr(w))
            await self._write(f"PENDING{w}_ONES", _pending_addr(w), ALL_ONES_32)
            after[w] = await self._read(f"PENDING{w}_AFTER", _pending_addr(w))
            assert after[w] == before[w], (
                f"PENDING[{w}] changed on write: before 0x{before[w]:x} after 0x{after[w]:x}"
            )
        probe, width = self._probe("tb_plic_pending_low")
        assert (after[0] >> 1) & ((1 << width) - 1) == probe, (
            f"PENDING[0] 0x{after[0]:x} disagrees with tb_plic_pending_low 0x{probe:x} "
            f"({width} bits)"
        )
        self._stamp("S4")
        self._chk(
            "CHK-PLICREG-PENDING",
            f"PENDING[0] before 0x{before[0]:x} after 0x{after[0]:x}, PENDING[10] before "
            f"0x{before[10]:x} after 0x{after[10]:x} unchanged by a write of 0x{ALL_ONES_32:x}; "
            f"tb_plic_pending_low=0x{probe:x} ({width} bits, bit n = source n + 1) equals "
            "(PENDING[0] >> 1) low bits; "
            "reset and live content open (SF-021)",
        )

        # S5
        saved_en = {}
        expected_en = {}
        for ctx in ENABLE_CONTEXTS:
            for w in ENABLE_WORDS:
                addr = _enable_addr(ctx, w)
                saved_en[(ctx, w)] = await self._read(f"ENABLE{ctx}_{w}_SAVE", addr)
                expected_en[(ctx, w)] = _enable_pattern(ctx, w)
        assert len(set(expected_en.values())) == len(expected_en), "patterns not distinct"
        for (ctx, w), pattern in expected_en.items():
            await self._write(f"ENABLE{ctx}_{w}_PATTERN", _enable_addr(ctx, w), pattern)
        for (ctx, w), pattern in expected_en.items():
            await self._read_expect(f"ENABLE{ctx}_{w}_RB", _enable_addr(ctx, w), pattern)
        probe, width = self._probe("tb_plic_enables0_w0")
        expected_probe = (expected_en[(0, 0)] >> 1) & ((1 << width) - 1)
        assert probe == expected_probe, (
            f"tb_plic_enables0_w0=0x{probe:x} ({width} bits, bit n = source n + 1) expected "
            f"0x{expected_probe:x} from ENABLE word 0 0x{expected_en[(0, 0)]:x}"
        )
        for (ctx, w), value in saved_en.items():
            await self._write(f"ENABLE{ctx}_{w}_RESTORE", _enable_addr(ctx, w), value)
            await self._read_expect(f"ENABLE{ctx}_{w}_RESTORE_RB", _enable_addr(ctx, w), value)
        self._stamp("S5")
        self._chk(
            "CHK-PLICREG-ENABLE",
            f"eight distinct patterns {[hex(v) for v in expected_en.values()]} over the source-ID "
            f"bits (masks word0=0x{_enable_mask(0):x} word10=0x{_enable_mask(10):x}) for contexts "
            f"{list(ENABLE_CONTEXTS)} words {list(ENABLE_WORDS)} read back without aliasing; "
            f"tb_plic_enables0_w0=0x{probe:x} ({width} bits, bit n = source n + 1) equals ENABLE "
            "word 0 >> 1 for context 0; sources limited to IDs 1..336 (interrupts.adoc, plic.rdl)",
        )

        # S6
        saved_th = {}
        for ctx in ENABLE_CONTEXTS:
            saved_th[ctx] = await self._read(f"THRESHOLD{ctx}_SAVE", _threshold_addr(ctx))
        th_samples = 0
        for ctx in ENABLE_CONTEXTS:
            for value in range(8):
                await self._write(f"THRESHOLD{ctx}_{value}", _threshold_addr(ctx), value)
                await self._read_expect(f"THRESHOLD{ctx}_{value}_RB", _threshold_addr(ctx), value)
                for other in ENABLE_CONTEXTS:
                    if other != ctx:
                        await self._read_expect(
                            f"THRESHOLD{other}_UNCHANGED", _threshold_addr(other), saved_th[other]
                        )
                if ctx == 0:
                    probe, width = self._probe("tb_plic_threshold0")
                    assert probe == value, (
                        f"tb_plic_threshold0=0x{probe:x} ({width} bits) expected {value}"
                    )
                    th_samples += 1
            await self._write(f"THRESHOLD{ctx}_RESTORE", _threshold_addr(ctx), saved_th[ctx])
            await self._read_expect(
                f"THRESHOLD{ctx}_RESTORE_RB", _threshold_addr(ctx), saved_th[ctx]
            )
        self._stamp("S6")
        self._chk(
            "CHK-PLICREG-THRESHOLD",
            f"THRESHOLD of contexts {list(ENABLE_CONTEXTS)} read back each value 0..7 with the "
            f"other three unchanged, tb_plic_threshold0 agreed for context 0 ({th_samples} "
            f"samples); reset values open (SF-021) saved="
            f"{ {c: hex(v) for c, v in saved_th.items()} }",
        )

        # S7
        pending = [
            await self._read(f"PENDING{w}_IDLE", _pending_addr(w)) for w in range(PENDING_WORDS)
        ]
        probe, width = self._probe("tb_plic_pending_low")
        assert not any(pending) and probe == 0, (
            f"a source is pending: PENDING={[hex(p) for p in pending]} "
            f"tb_plic_pending_low=0x{probe:x}; last access {self._last_access}"
        )
        claims = []
        for ctx in CLAIM_CONTEXTS:
            claims.append(await self._read(f"CLAIM{ctx}", _claim_addr(ctx)))
        assert all(c == 0 for c in claims), f"claim returned an ID: {[hex(c) for c in claims]}"
        claim0, claim_width = self._probe("tb_plic_claim0")
        assert claim0 == 0, f"tb_plic_claim0=0x{claim0:x} ({claim_width} bits) expected 0"
        self._stamp("S7")
        self._chk(
            "CHK-PLICREG-CLAIM",
            f"with PENDING[0..10] all 0 and tb_plic_pending_low=0x{probe:x}, CLAIM_COMPLETE of "
            f"contexts 0..7 read {[hex(c) for c in claims]}, tb_plic_claim0=0x{claim0:x} "
            f"({claim_width} bits); the 0x0 read is reset-equal under 2-state Verilator",
        )

        # S7R
        await self._write("REGION_SIZE_RESTORE", REGION_SIZE, REGION_SIZE_RESET)
        await self._read_expect("REGION_SIZE_RESTORE_RB", REGION_SIZE, REGION_SIZE_RESET)
        self._waits.append(("sep_in_access", f"{axi_bound}ns", self._last_access))
        self._stamp("S7R")

        self.assert_all_reachable(self.accesses, "PLIC")
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
        assert order == [c for c, _ in CHK_ORDER], f"checker order {order}"
        for chk_id, n_stamps in self._chk_order:
            step = dict(CHK_ORDER)[chk_id]
            assert n_stamps == STEP_ORDER.index(step) + 1, f"{chk_id} printed before {step}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(FENCE_TERMS[s] for s in steps),
            ",".join(order),
            ",".join(f"{s}={t}ps" for s, t in self._stamps),
        )
        self.chk_seen.add("CHK-NONVAC")
