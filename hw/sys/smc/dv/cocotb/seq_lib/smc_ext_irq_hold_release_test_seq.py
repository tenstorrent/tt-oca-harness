# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_B1_005 ANCHOR: smc_ext_irq_hold_release_test
# DV-TESTCASE-CONTRACT-REVISION: 2 RECORD-SHA256: 06aaaeaac8e1c77902b9ddfdb6242e46b21d4aeec99507ee10f39385e797136a
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_COV_B1_VPLAN_DETAIL.md @ artifact_revision 6 ENV: cocotb
"""External input level hold and release walk over raw bits 0 and 2..16 of cpu_interrupts.

Spec sources: interrupts.adoc smc-interrupts-risc-v-plic (active-high, level-sensitive gateways
behind prim_sync3), interrupts.adoc cpu-interrupt-vector-map (raw bit N = PLIC ID N+1,
cpu_interrupts_o[NumExtInterrupts-1:0] = synchronised smc_ext_interrupts_i), smu-smc.adoc
interrupt-integration.

The bench drives external input 0 on tb_ext_interrupt_0_i and inputs 2..16 on
tb_ext_interrupts_hi_i; input 1 is the temperature pin (held 0, read only) and inputs 17..255 are
tied 0 (SF-039). The PLIC pending state of each external ID is read passively and only logged:
its register map, route, bound and retention are open (SF-025, SF-026, SF-027, SF-028).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

SCRATCH_COLD_WARM_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR")
# TB ceiling for a pin-to-raw-bit transition in clk_smc_i rises; not a latency claim.
WAIT_BOUND_RISES = 64
HOLD_RISES = 256
BASELINE_RISES = 16
# The external inputs pass a three-flop synchroniser (interrupts.adoc).
SYNC_FLOPS = 3
RELEASE_RISES = 64
NUM_EXT = 256
EXT_MASK = (1 << NUM_EXT) - 1
WALK = (0, *range(2, 17))
_EXTHOLD = {0: "CHK-EXTHOLD-BIT0", 2: "CHK-EXTHOLD-BIT2", 16: "CHK-EXTHOLD-BIT16"}
_CHECKERS = (
    "CHK-EXTHOLD-BIT0",
    "CHK-EXTHOLD-BIT2",
    "CHK-EXTHOLD-BIT16",
    "CHK-EXTIRQ-ASSERT",
    "CHK-EXTIRQ-ISOLATION",
    "CHK-EXTIRQ-RELEASE",
)
_TERMS = ("ASSERT", "HOLD", "RELEASE")
# The PLIC's pending_N register holds source N + 1 (tb_top.sv PLIC probe block).
_PLIC_PATH = (
    "u_dut",
    "u_smc",
    "u_smc_cpu_wrapper",
    "u_smc_cpu",
    "u_digital_top",
    "plic_domain",
    "plic",
)


class smc_ext_irq_hold_release_test_seq(SmcCsrSeq):
    """Walk inputs 0 and 2..16: hold each high for 256 rises, release it, watch the raw vector."""

    def __init__(self, name: str = "smc_ext_irq_hold_release_test_seq") -> None:
        super().__init__(name)
        self.done = False
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: list[str] = []
        self._baseline = 0
        self._plic = None
        self._iso_samples = 0

    def _mark(self, term: str) -> None:
        self._stamps.append((term, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    @staticmethod
    def _sample(label: str) -> int:
        sig = cocotb.top.tb_cpu_interrupts
        assert sig.value.is_resolvable, f"{label}: tb_cpu_interrupts is X/Z ({sig.value})"
        return int(sig.value)

    @staticmethod
    def _pins() -> tuple[int, int, int]:
        dut = cocotb.top
        vals = []
        for sig in (dut.tb_ext_interrupt_0_i, dut.tb_temp_interrupt_i, dut.tb_ext_interrupts_hi_i):
            assert sig.value.is_resolvable, f"{sig._name} is X/Z ({sig.value})"
            vals.append(int(sig.value))
        return vals[0], vals[1], vals[2]

    def _resolve_plic(self) -> str:
        node = cocotb.top
        try:
            for part in _PLIC_PATH:
                node = getattr(node, part)
        except AttributeError as exc:
            self._plic = None
            return f"unobservable ({exc})"
        self._plic = node
        return "tb_top." + ".".join(_PLIC_PATH)

    def _pending(self, src_id: int) -> str:
        """Passive read of the PLIC pending bit of source ID `src_id`; logged, never compared."""
        if self._plic is None:
            return "n/a"
        try:
            val = getattr(self._plic, f"pending_{src_id - 1}").value
        except AttributeError:
            return "n/a"
        return str(int(val)) if val.is_resolvable else str(val)

    def _other_pending(self, bit: int) -> str:
        if self._plic is None:
            return "n/a"
        ones = []
        for other in range(NUM_EXT):
            if other == bit:
                continue
            obs = self._pending(other + 1)
            if obs != "0":
                ones.append(f"ID{other + 1}={obs}")
        return ",".join(ones) if ones else "none"

    def _drive(self, bit: int, level: int, label: str) -> None:
        dut = cocotb.top
        if bit == 0:
            dut.tb_ext_interrupt_0_i.value = level
        else:
            hi = int(dut.tb_ext_interrupts_hi_i.value)
            hi = (hi | (1 << (bit - 2))) if level else (hi & ~(1 << (bit - 2)))
            dut.tb_ext_interrupts_hi_i.value = hi
        cocotb.log.info(
            "DRIVE %s: raw bit %d pin level %d (seed %s)", label, bit, level, cocotb.RANDOM_SEED
        )

    def _check_only(self, vec: int, mask: int, want: int, label: str) -> None:
        expect = self._baseline ^ (mask if want else 0)
        assert vec == expect, (
            f"{label}: tb_cpu_interrupts 0x{vec:x} want 0x{expect:x} "
            f"(baseline 0x{self._baseline:x}, XOR 0x{vec ^ self._baseline:x})"
        )
        ext = vec & EXT_MASK
        ext_want = mask if want else 0
        assert ext == ext_want, (
            f"{label}: raw external bits [255:0] 0x{ext:x} want 0x{ext_want:x} "
            f"(other external bits 0x{ext & ~mask:x})"
        )

    async def _wait_bit(self, bit: int, want: int, label: str) -> int:
        mask = 1 << bit
        last = self._sample(f"{label} entry")
        for n in range(1, WAIT_BOUND_RISES + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            last = self._sample(f"{label}[{n}]")
            assert (last ^ self._baseline) & ~mask == 0, (
                f"{label}[{n}]: a second raw bit moved: vector 0x{last:x} "
                f"baseline 0x{self._baseline:x}"
            )
            if (last >> bit) & 1 == want:
                self._waits.append(
                    f"{label}(bound {WAIT_BOUND_RISES} rises, hit at {n}, last 0x{last:x})"
                )
                return n
        raise AssertionError(
            f"{label}: raw bit {bit} did not reach {want} within {WAIT_BOUND_RISES} "
            f"clk_smc_i rises (last vector 0x{last:x}, baseline 0x{self._baseline:x})"
        )

    async def _hold(self, bit: int, want: int, rises: int, label: str) -> int:
        mask = 1 << bit
        for n in range(1, rises + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            vec = self._sample(f"{label}[{n}]")
            self._check_only(vec, mask, want, f"{label}[{n}/{rises}]")
            assert (vec >> bit) & 1 == want, f"{label}[{n}/{rises}]: raw bit {bit} left {want}"
        return rises

    async def _hold_release(self, bit: int) -> dict:
        label = f"BIT{bit}"
        self._drive(bit, 1, f"{label} hold")
        cocotb.log.info("LIFECYCLE %s set: input for raw bit %d driven 1", label, bit)
        rise = await self._wait_bit(bit, 1, f"{label}_RISE")
        assert rise >= SYNC_FLOPS, (
            f"{label}: raw bit {bit} rose after {rise} rises, before the {SYNC_FLOPS}-flop "
            "synchroniser latency"
        )
        self._mark(f"ASSERT-{bit}")
        held = await self._hold(bit, 1, HOLD_RISES, f"{label}_HOLD")
        self._iso_samples += held
        pend_hold = self._pending(bit + 1)
        other_hold = self._other_pending(bit)
        cocotb.log.info(
            "LIFECYCLE %s observed: raw bit %d read 1 after %d rises and at each of %d rises; "
            "measured pending(ID %d)=%s, other external pending=%s",
            label,
            bit,
            rise,
            held,
            bit + 1,
            pend_hold,
            other_hold,
        )
        self._mark(f"HOLD-{bit}")
        self._drive(bit, 0, f"{label} release")
        cocotb.log.info("LIFECYCLE %s cleared: input for raw bit %d driven 0", label, bit)
        fall = await self._wait_bit(bit, 0, f"{label}_FALL")
        assert fall >= SYNC_FLOPS, (
            f"{label}: raw bit {bit} fell after {fall} rises, before the {SYNC_FLOPS}-flop "
            "synchroniser latency"
        )
        await self._hold(bit, 0, RELEASE_RISES, f"{label}_RELEASED")
        pend_rel = self._pending(bit + 1)
        cocotb.log.info(
            "LIFECYCLE %s checked_cleared: raw bit %d read 0 after %d rises and vector equals "
            "baseline for %d rises; measured pending(ID %d) after release=%s",
            label,
            bit,
            fall,
            RELEASE_RISES,
            bit + 1,
            pend_rel,
        )
        self._mark(f"RELEASE-{bit}")
        return {
            "rise": rise,
            "fall": fall,
            "held": held,
            "pend_hold": pend_hold,
            "other_hold": other_hold,
            "pend_rel": pend_rel,
        }

    async def _baseline_window(self) -> None:
        self._baseline = self._sample("BASELINE")
        assert self._baseline & EXT_MASK == 0, (
            f"BASELINE: raw external bits [255:0] read 0x{self._baseline & EXT_MASK:x}, want 0"
        )
        for n in range(1, BASELINE_RISES + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            vec = self._sample(f"BASELINE[{n}]")
            assert vec == self._baseline, (
                f"BASELINE[{n}/{BASELINE_RISES}]: vector 0x{vec:x} moved from 0x{self._baseline:x}"
            )

    async def body(self) -> None:
        dut = cocotb.top
        assert hasattr(dut, "tb_ext_interrupts_hi_i"), "tb_ext_interrupts_hi_i missing"
        await self.wait_fuse_sense_done()
        pins = self._pins()
        assert pins == (0, 0, 0), f"baseline pins (ext0, temp, hi) = {pins}, want (0, 0, 0)"
        await self._baseline_window()
        plic_where = self._resolve_plic()
        self._mark("BASELINE")
        cocotb.log.info(
            "BASELINE: tb_cpu_interrupts=0x%x, raw [255:0]=0 on %d consecutive rises, pins "
            "ext0/temp/hi=%s, PLIC pending probe %s, seed %s",
            self._baseline,
            BASELINE_RISES,
            pins,
            plic_where,
            cocotb.RANDOM_SEED,
        )

        results: dict[int, dict] = {}
        for bit in WALK:
            results[bit] = await self._hold_release(bit)
            assert self._pins()[1] == 0, "the temperature pin left 0 during the walk"
            if bit in _EXTHOLD:
                r = results[bit]
                self._log_chk(
                    _EXTHOLD[bit],
                    f"raw bit {bit} rose after {r['rise']} rises (bound {WAIT_BOUND_RISES}) and "
                    f"held 1 with vector XOR baseline 0x{1 << bit:x} at {HOLD_RISES} rises; fell "
                    f"after {r['fall']} rises and vector equalled baseline 0x{self._baseline:x} "
                    f"for {RELEASE_RISES} rises",
                )

        missing = [b for b in WALK if b not in results]
        assert not missing, f"walk did not complete inputs {missing}"
        n = len(WALK)
        rises = ",".join(f"{b}:{results[b]['rise']}" for b in WALK)
        pend = ",".join(f"{b}:{results[b]['pend_hold']}" for b in WALK)
        self._log_chk(
            "CHK-EXTIRQ-ASSERT",
            f"{n}/{n} inputs {{0,2..16}}, raw bit i=1 after n rises (i:n {rises}; min "
            f"{SYNC_FLOPS}, bound {WAIT_BOUND_RISES}) and held {HOLD_RISES}/{HOLD_RISES}, "
            f"pending(ID i+1)=(i:observed {pend}) measured only, LINKED-ISSUE SF-025 SF-026 SF-028",
        )
        want_iso = n * HOLD_RISES
        assert self._iso_samples == want_iso, (
            f"isolation samples {self._iso_samples}, want {want_iso}"
        )
        other = "; ".join(f"{b}:{results[b]['other_hold']}" for b in WALK)
        self._log_chk(
            "CHK-EXTIRQ-ISOLATION",
            f"{n} walks x {HOLD_RISES} samples ({self._iso_samples} total), other raw external "
            f"bits = 0 throughout (bits 0..255 incl. temperature bit 1 and tied 17..255), other "
            f"pending=(i:observed {other}) measured only, LINKED-ISSUE SF-025",
        )
        falls = ",".join(f"{b}:{results[b]['fall']}" for b in WALK)
        rel = ",".join(f"{b}:{results[b]['pend_rel']}" for b in WALK)
        self._log_chk(
            "CHK-EXTIRQ-RELEASE",
            f"{n}/{n} raw bits 1->0 (i:n {falls}; bound {WAIT_BOUND_RISES}), baseline restored "
            f"0x{self._baseline:x} for {RELEASE_RISES} rises each, pending(ID i+1) after "
            f"release=(i:observed {rel}) measured only, LINKED-ISSUE SF-027",
        )
        await self.csr_read("SCRATCH_COLD_WARM_0", SCRATCH_COLD_WARM_0)
        self.done = True
        self._timeout_paths()
        self._nonvac_fence()

    def _timeout_paths(self) -> None:
        want = 2 * len(WALK)
        assert len(self._waits) == want, f"{len(self._waits)} bounded waits logged, want {want}"
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits, bound/last-state per wait, 0 expired; each "
            "raises AssertionError with the last vector on expiry: %s",
            len(self._waits),
            "; ".join(self._waits),
        )

    def _nonvac_fence(self) -> None:
        want = ["BASELINE"] + [f"{t}-{b}" for b in WALK for t in _TERMS]
        got = [s for s, _ in self._stamps]
        assert got == want, f"fence terms {got}, want {want}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        chk_ids = tuple(c for c, _ in self._chk_marks)
        assert chk_ids == _CHECKERS, f"checker lines {chk_ids}, want {_CHECKERS}"
        stamp_at = dict(self._stamps)
        for chk_id, when in self._chk_marks:
            bit = next((b for b, c in _EXTHOLD.items() if c == chk_id), WALK[-1])
            assert when >= stamp_at[f"RELEASE-{bit}"], f"{chk_id} printed before its step"
        cocotb.log.info(
            "CHK-NONVAC: BASELINE < ASSERT-i < HOLD-i < RELEASE-i (x%d, i in {0,2..16}), "
            "%d terms each count 1 in order; checker lines %s; stamps %s",
            len(WALK),
            len(self._stamps),
            ",".join(chk_ids),
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
