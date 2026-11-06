# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CLINT tick rate and reset, and PLIC and MTIMECMP retention across a cool reset.

Sources: hw/sys/smc/doc/interrupts.adoc (CLINT: "The timer resets to 0 and advances on the
cluster's periodic tick, once per 1000 CPU-cluster cbus cycles", "The compare registers have no
reset"; Interrupt Control: "The PLIC priority, enable and threshold registers are not reset by
hardware"), hw/sys/smc/regs/blocks/clint/clint.rdl, hw/sys/smc/regs/blocks/plic/plic.rdl,
hw/sys/smc/doc/clk_rst.adoc (cool reset).

The CPU cluster runs on clk_smc_i, so one cbus cycle is one clk_smc_i rise and the tick period
is measured in rises of that clock. The cool reset pin lowers the warm reset the cluster's
uncore reset follows; MSIP and MTIME, which clint.rdl gives a reset, read 0 under it, and that
is the positive control for the registers that keep their written words.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_reset_item import SmcResetItem, SmcResetOp

from .smc_addr_map import REGION_SIZE_RESET, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_reset_seq_base import SmcResetSeqBase

CORES = 4
TICK_RISES = 1000
TICKS_MEASURED = 4
TICK_BOUND_RISES = TICK_RISES * (TICKS_MEASURED + 2)
BRACKET_RISES = 2500
RESET_HOLD_SAMPLES = 4
PENDING_RISE_BOUND = 64
REGION_SIZE_256M = 0x1000_0000
COOL_ASSERT_BOUND_REF = 400
COOL_RECOVER_BOUND_REF = 4000
MTIME_LOAD_VALUE = 0x0000_0001_0000_0000
MTIMECMP_PATTERN = 0xC0DE_0000_0000_0A00
PRIORITY_SOURCES = {1: 5, 336: 3}
ENABLE_WORDS = {(0, 0): 0x5A5A_5A5A, (7, 10): 0x0001_2345}
THRESHOLDS = {0: 6, 7: 2}
REGION_SIZE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
MTIME_ADDR = smc_addr("SMC_TOP_SMC_CLUSTER_CLINT_MTIME_BASE_ADDR")
PLIC = "SMC_TOP_SMC_CLUSTER_PLIC_"
CONTEXT_NAMES = tuple(f"CORE{n}_{kind}" for kind in ("MEIP", "SEIP") for n in range(4))
STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8")
CHK_ORDER = (
    ("CHK-CLINT-MTIME-TICK-1000", "S3"),
    ("CHK-CLINT-MTIME-RESET-ZERO", "S5"),
    ("CHK-CLINT-MTIMECMP-RETAIN", "S6"),
    ("CHK-PLIC-REGS-RETAIN-WARM", "S7"),
    ("CHK-TIMEOUT-PATHS", "S8"),
)


def _msip_addr(core: int) -> int:
    return smc_indexed_addr("SMC_TOP_SMC_CLUSTER_CLINT_MSIP_BASE_ADDR", core)


def _mtimecmp_addr(core: int) -> int:
    return smc_indexed_addr("SMC_TOP_SMC_CLUSTER_CLINT_MTIMECMP_BASE_ADDR", core)


def _priority_addr(source: int) -> int:
    return smc_indexed_addr(PLIC + "PRIORITY_BASE_ADDR", source)


def _enable_addr(ctx: int, word: int) -> int:
    return smc_indexed_addr(PLIC + f"{CONTEXT_NAMES[ctx]}_ENABLE_BASE_ADDR", word)


def _threshold_addr(ctx: int) -> int:
    return smc_addr(PLIC + f"{CONTEXT_NAMES[ctx]}_THRESHOLD_BASE_ADDR")


class smc_clint_plic_reset_retention_test_seq(SmcResetSeqBase, SmcCsrSeq):
    """Measure the MTIME tick, then pull a cool reset through written CLINT and PLIC words."""

    ASSERT_BOUND_REF_CYCLES = COOL_ASSERT_BOUND_REF
    RELEASE_BOUND_REF_CYCLES = COOL_RECOVER_BOUND_REF

    def __init__(self, name: str = "smc_clint_plic_reset_retention_test_seq") -> None:
        super().__init__(name)
        self.dispatch_reset = None
        self.chk_seen: set[str] = set()
        self._stamps: list[tuple[str, int]] = []
        self._chk_order: list[tuple[str, int]] = []
        self._waits: list[str] = []
        self._rises = 0

    async def _dispatch_reset_item(self, item: SmcResetItem) -> None:
        await self.dispatch_reset(item)

    def _stamp(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_order.append((chk_id, len(self._stamps)))
        self.chk_seen.add(chk_id)

    @staticmethod
    def _probe(name: str) -> int:
        sig = getattr(cocotb.top, name)
        assert sig.value.is_resolvable, f"{name} is X/Z: {sig.value}"
        return int(sig.value)

    async def _count_rises(self) -> None:
        clk = cocotb.top.clk_smc_i
        while True:
            await RisingEdge(clk)
            self._rises += 1

    async def _await_level(self, signal: str, want: int, bound: int, label: str) -> None:
        dut = cocotb.top
        sig = getattr(dut, signal)
        last: int | None = None
        for n in range(bound):
            value = sig.value
            last = int(value) if value.is_resolvable else None
            if last == want:
                self._waits.append(f"{label}: bound={bound} clk_ref_i edges matched at {n}")
                return
            await RisingEdge(dut.clk_ref_i)
        raise AssertionError(
            f"{label}: {signal} never reached {want} within {bound} clk_ref_i edges "
            f"(last={'X/Z' if last is None else last})"
        )

    async def _tick_periods(self) -> list[int]:
        """Rises between consecutive increments of tb_clint_mtime, TICKS_MEASURED of them."""
        clk = cocotb.top.clk_smc_i
        prev = self._probe("tb_clint_mtime")
        changes: list[int] = []
        for n in range(1, TICK_BOUND_RISES + 1):
            await RisingEdge(clk)
            now = self._probe("tb_clint_mtime")
            if now != prev:
                assert now == prev + 1, (
                    f"CHK-CLINT-MTIME-TICK-1000: tb_clint_mtime stepped 0x{prev:x} -> 0x{now:x} "
                    f"at rise {n}, expected +1"
                )
                changes.append(n)
                prev = now
                if len(changes) == TICKS_MEASURED + 1:
                    break
        assert len(changes) == TICKS_MEASURED + 1, (
            f"CHK-CLINT-MTIME-TICK-1000: tb_clint_mtime changed {len(changes)} times in "
            f"{TICK_BOUND_RISES} rises, expected {TICKS_MEASURED + 1}"
        )
        self._waits.append(
            f"mtime_ticks: bound={TICK_BOUND_RISES} rises, last change at rise {changes[-1]}"
        )
        return [b - a for a, b in zip(changes, changes[1:])]

    async def _read(self, name: str, addr: int, length: int = 4) -> tuple[int, int, int]:
        """Read and return (value, rises before the access, rises after it)."""
        before = self._rises
        value = await self.csr_read(name, addr, length=length)
        return value, before, self._rises

    async def _write_rb(self, name: str, addr: int, data: int, length: int = 4) -> None:
        await self.csr_write(name, addr, data, length=length)
        await self.csr_read(f"{name}_RB", addr, expected=data, length=length)

    async def _widen(self, tag: str) -> None:
        await self._write_rb(f"REGION_SIZE_256M_{tag}", REGION_SIZE, REGION_SIZE_256M)

    async def body(self) -> None:
        dut = cocotb.top
        for sig in (
            "tb_clint_mtime",
            "tb_clint_mtimecmp0",
            "tb_clint_mtimecmp1",
            "tb_clint_msip",
            "tb_plic_priority_low",
            "tb_plic_enables0_w0",
            "tb_plic_threshold0",
            "tb_plic_pending_low",
            "tb_ext_interrupt_0_i",
            "tb_rst_warm_smc_clk_n",
            "rst_primary_smc_clk_no",
        ):
            assert hasattr(dut, sig), f"{sig} not exported"
        pin = dut.tb_ext_interrupt_0_i
        pin.value = 0
        counter = cocotb.start_soon(self._count_rises())

        # S1
        await self.wait_fuse_sense_done()
        self._stamp("S1")

        # S2
        await self._widen("PRE")
        saved_msip = [await self.csr_read(f"MSIP{n}_SAVE", _msip_addr(n)) for n in range(CORES)]
        saved_cmp = [
            await self.csr_read(f"MTIMECMP{n}_SAVE", _mtimecmp_addr(n), length=8)
            for n in range(CORES)
        ]
        saved_prio = {
            k: await self.csr_read(f"PRIORITY{k}_SAVE", _priority_addr(k)) for k in PRIORITY_SOURCES
        }
        saved_en = {
            (c, w): await self.csr_read(f"ENABLE{c}_{w}_SAVE", _enable_addr(c, w))
            for c, w in ENABLE_WORDS
        }
        saved_th = {
            c: await self.csr_read(f"THRESHOLD{c}_SAVE", _threshold_addr(c)) for c in THRESHOLDS
        }
        self._stamp("S2")

        # S3
        periods = await self._tick_periods()
        assert all(p == TICK_RISES for p in periods), (
            f"CHK-CLINT-MTIME-TICK-1000: rises between tb_clint_mtime increments {periods}, "
            f"expected {TICK_RISES} each"
        )
        r0, c0, c0_done = await self._read("MTIME_BRACKET_0", MTIME_ADDR, 8)
        await ClockCycles(dut.clk_smc_i, BRACKET_RISES)
        r1, c1, c1_done = await self._read("MTIME_BRACKET_1", MTIME_ADDR, 8)
        latency = max(c0_done - c0, c1_done - c1)
        delta_rises = c1_done - c0_done
        delta_reads = r1 - r0
        tolerance = TICK_RISES + latency
        assert abs(delta_reads * TICK_RISES - delta_rises) <= tolerance, (
            f"CHK-CLINT-MTIME-TICK-1000: MTIME reads 0x{r0:x} -> 0x{r1:x} (+{delta_reads}) over "
            f"{delta_rises} clk_smc_i rises, expected {delta_rises / TICK_RISES:.2f} +- "
            f"{tolerance / TICK_RISES:.2f} (read latency {latency} rises)"
        )
        self._stamp("S3")
        self._chk(
            "CHK-CLINT-MTIME-TICK-1000",
            f"tb_clint_mtime incremented by one every {periods} clk_smc_i rises "
            f"({TICKS_MEASURED} consecutive ticks, cbus = clk_smc_i); MTIME read 0x{r0:x} then "
            f"0x{r1:x}, +{delta_reads} ticks over {delta_rises} rises between the two read "
            f"completions, expected {delta_rises / TICK_RISES:.2f} within "
            f"{tolerance / TICK_RISES:.2f} (read latency {latency} rises)",
        )

        # S4
        await self._write_rb("MSIP0_ONE", _msip_addr(0), 1)
        assert self._probe("tb_clint_msip") & 1 == 1, "tb_clint_msip bit 0 not set"
        patterns = [MTIMECMP_PATTERN | n for n in range(CORES)]
        for n in range(CORES):
            await self._write_rb(f"MTIMECMP{n}_PATTERN", _mtimecmp_addr(n), patterns[n], 8)
        for k, value in PRIORITY_SOURCES.items():
            await self._write_rb(f"PRIORITY{k}_PATTERN", _priority_addr(k), value)
        for (c, w), value in ENABLE_WORDS.items():
            await self._write_rb(f"ENABLE{c}_{w}_PATTERN", _enable_addr(c, w), value)
        for c, value in THRESHOLDS.items():
            await self._write_rb(f"THRESHOLD{c}_PATTERN", _threshold_addr(c), value)
        await self.csr_write("MTIME_LOAD", MTIME_ADDR, MTIME_LOAD_VALUE, length=8)
        loaded = await self.csr_read("MTIME_LOADED", MTIME_ADDR, length=8)
        assert loaded >= MTIME_LOAD_VALUE, (
            f"MTIME read 0x{loaded:x} after loading 0x{MTIME_LOAD_VALUE:x}"
        )
        pin.value = 1
        for pend_rise in range(1, PENDING_RISE_BOUND + 1):
            await RisingEdge(dut.clk_smc_i)
            if self._probe("tb_plic_pending_low") & 1:
                break
        else:
            raise AssertionError(
                f"PLIC source 1 did not pend within {PENDING_RISE_BOUND} rises of input 0 high"
            )
        self._waits.append(
            f"source1_pending: bound={PENDING_RISE_BOUND} rises matched at {pend_rise}"
        )
        self._stamp("S4")

        # S5
        await self._send(SmcResetOp.COOL_RST_LO, item_name="cool_rst_lo")
        await self._await_level("rst_primary_smc_clk_no", 0, COOL_ASSERT_BOUND_REF, "COOL_ASSERT")
        await self._await_level(
            "tb_rst_warm_smc_clk_n", 0, COOL_ASSERT_BOUND_REF, "COOL_ASSERT_WARM"
        )
        in_reset = []
        for _ in range(RESET_HOLD_SAMPLES):
            await RisingEdge(dut.clk_smc_i)
            in_reset.append(
                (
                    self._probe("tb_clint_mtime"),
                    self._probe("tb_clint_msip"),
                    self._probe("tb_clint_mtimecmp0"),
                    self._probe("tb_clint_mtimecmp1"),
                    self._probe("tb_plic_threshold0"),
                    self._probe("tb_plic_enables0_w0"),
                    self._probe("tb_plic_priority_low") & 1,
                    self._probe("tb_plic_pending_low") & 1,
                )
            )
        pin.value = 0
        bad = [s for s in in_reset if s[0] != 0 or s[1] != 0]
        assert not bad, (
            f"CHK-CLINT-MTIME-RESET-ZERO: with tb_rst_warm_smc_clk_n low tb_clint_mtime and "
            f"tb_clint_msip read {[(hex(s[0]), s[1]) for s in bad]}, expected 0 and 0 after loading "
            f"MTIME 0x{MTIME_LOAD_VALUE:x} and MSIP[0] 1"
        )
        held = (
            patterns[0],
            patterns[1],
            THRESHOLDS[0],
            (ENABLE_WORDS[(0, 0)] >> 1) & 0x7F,
            PRIORITY_SOURCES[1] & 1,
            0,
        )
        kept = [s[2:] == held for s in in_reset]
        assert all(kept), (
            f"CHK-PLIC-REGS-RETAIN-WARM: probes under the warm reset {in_reset[-1][2:]}, expected "
            f"mtimecmp0/1, threshold0, enables0_w0 bits 7:1, priority[1] bit 0, pending[1] = {held}"
        )
        await self._send(SmcResetOp.COOL_RST_HI, item_name="cool_rst_hi")
        await self._await_level("rst_primary_smc_clk_no", 1, COOL_RECOVER_BOUND_REF, "COOL_RELEASE")
        await self._await_level(
            "tb_rst_warm_smc_clk_n", 1, COOL_RECOVER_BOUND_REF, "COOL_RELEASE_WARM"
        )
        release_rises = self._rises
        pending_after = self._probe("tb_plic_pending_low") & 1
        assert pending_after == 0, (
            f"CHK-PLIC-REGS-RETAIN-WARM: PLIC source 1 pending {pending_after} after the release "
            "with input 0 low, expected the reset to have cleared it"
        )
        await self.wait_fuse_sense_done()
        await self._widen("POST")
        mtime_after, _, after_rises = await self._read("MTIME_AFTER_RESET", MTIME_ADDR, 8)
        ceiling = (after_rises - release_rises) // TICK_RISES + 1
        assert mtime_after <= ceiling, (
            f"CHK-CLINT-MTIME-RESET-ZERO: MTIME read 0x{mtime_after:x} {after_rises - release_rises} "
            f"rises after the warm release, expected at most {ceiling} (loaded 0x{MTIME_LOAD_VALUE:x} "
            f"before the cool reset)"
        )
        self._stamp("S5")
        self._chk(
            "CHK-CLINT-MTIME-RESET-ZERO",
            f"MTIME loaded with 0x{MTIME_LOAD_VALUE:x} (read 0x{loaded:x}) and MSIP[0] set before "
            f"the cool reset; under the warm reset tb_clint_mtime read "
            f"{[hex(s[0]) for s in in_reset]} and tb_clint_msip {[s[1] for s in in_reset]} at "
            f"{RESET_HOLD_SAMPLES} rises; MTIME read 0x{mtime_after:x} over SEP_IN "
            f"{after_rises - release_rises} rises after the release, ceiling {ceiling}",
        )

        # S6
        msip0 = await self.csr_read("MSIP0_AFTER_RESET", _msip_addr(0))
        assert msip0 == 0, (
            f"CHK-CLINT-MTIMECMP-RETAIN: MSIP[0] read 0x{msip0:x} after the cool reset, expected "
            "the clint.rdl reset 0 (positive control)"
        )
        cmp_after = [
            await self.csr_read(f"MTIMECMP{n}_AFTER_RESET", _mtimecmp_addr(n), length=8)
            for n in range(CORES)
        ]
        assert cmp_after == patterns, (
            f"CHK-CLINT-MTIMECMP-RETAIN: MTIMECMP read {[hex(v) for v in cmp_after]} after the "
            f"cool reset, expected the written {[hex(v) for v in patterns]}"
        )
        self._stamp("S6")
        self._chk(
            "CHK-CLINT-MTIMECMP-RETAIN",
            f"MTIMECMP[0..3] read {[hex(v) for v in cmp_after]} after the cool reset, the words "
            f"written before it; the probes held {[hex(s[2]) for s in in_reset]} and "
            f"{[hex(s[3]) for s in in_reset]} under the warm reset; MSIP[0] read 0x{msip0:x} "
            "(reset by the same reset), MTIME reset to 0",
        )

        # S7
        prio_after = {
            k: await self.csr_read(f"PRIORITY{k}_AFTER_RESET", _priority_addr(k))
            for k in PRIORITY_SOURCES
        }
        en_after = {
            (c, w): await self.csr_read(f"ENABLE{c}_{w}_AFTER_RESET", _enable_addr(c, w))
            for c, w in ENABLE_WORDS
        }
        th_after = {
            c: await self.csr_read(f"THRESHOLD{c}_AFTER_RESET", _threshold_addr(c))
            for c in THRESHOLDS
        }
        assert (prio_after, en_after, th_after) == (PRIORITY_SOURCES, ENABLE_WORDS, THRESHOLDS), (
            f"CHK-PLIC-REGS-RETAIN-WARM: after the cool reset PRIORITY {prio_after} ENABLE "
            f"{ {k: hex(v) for k, v in en_after.items()} } THRESHOLD {th_after}, expected the "
            f"written {PRIORITY_SOURCES} { {k: hex(v) for k, v in ENABLE_WORDS.items()} } "
            f"{THRESHOLDS}"
        )
        self._stamp("S7")
        self._chk(
            "CHK-PLIC-REGS-RETAIN-WARM",
            f"PRIORITY {prio_after}, ENABLE { {k: hex(v) for k, v in en_after.items()} } and "
            f"THRESHOLD {th_after} read the words written before the cool reset; probes under the "
            f"warm reset threshold0={in_reset[-1][4]} enables0_w0=0x{in_reset[-1][5]:x} "
            f"priority[1] bit0={in_reset[-1][6]}; the PLIC pending bit of source 1, set by input 0 "
            f"at rise {pend_rise} before the reset, read {[s[7] for s in in_reset]} under it and "
            f"{pending_after} after the release; MSIP[0] 0x{msip0:x} and MTIME 0x{mtime_after:x} "
            "reset beside them (positive controls in the PLIC and CLINT domains)",
        )

        # S8
        for n in range(CORES):
            await self._write_rb(f"MSIP{n}_RESTORE", _msip_addr(n), saved_msip[n])
            await self._write_rb(f"MTIMECMP{n}_RESTORE", _mtimecmp_addr(n), saved_cmp[n], 8)
        for k, value in saved_prio.items():
            await self._write_rb(f"PRIORITY{k}_RESTORE", _priority_addr(k), value)
        for (c, w), value in saved_en.items():
            await self._write_rb(f"ENABLE{c}_{w}_RESTORE", _enable_addr(c, w), value)
        for c, value in saved_th.items():
            await self._write_rb(f"THRESHOLD{c}_RESTORE", _threshold_addr(c), value)
        await self._write_rb("REGION_SIZE_RESTORE", REGION_SIZE, REGION_SIZE_RESET)
        counter.cancel()
        self._stamp("S8")
        self.assert_all_reachable(self.accesses, "CLINT and PLIC")
        self._chk(
            "CHK-TIMEOUT-PATHS",
            f"fuse sense wait bound 200000 clk_smc_i rises twice (AssertionError on expiry); "
            f"{len(self._waits)} bounded waits: {'; '.join(self._waits)}; SEP_IN accesses "
            f"x{self.accesses} bound={self.cfg.axi_timeout_ns} ns allow_timeout False",
        )
        self._fence()

    def _fence(self) -> None:
        steps = tuple(s for s, _ in self._stamps)
        assert steps == STEPS, f"step order {steps}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing {times}"
        order = [c for c, _ in self._chk_order]
        assert order == [c for c, _ in CHK_ORDER], f"checker order {order}"
        for chk_id, n_stamps in self._chk_order:
            step = dict(CHK_ORDER)[chk_id]
            assert n_stamps == STEPS.index(step) + 1, f"{chk_id} printed before {step}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence BRINGUP<SAVED<TICK_MEASURED<WRITTEN<COOL_RESET<"
            "MTIMECMP_READ<PLIC_READ<RESTORED; checker lines %s; stamps %s",
            ",".join(order),
            ",".join(f"{s}={t}ps" for s, t in self._stamps),
        )
        self.chk_seen.add("CHK-NONVAC")
