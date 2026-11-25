# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Walk external inputs 17..255 one at a time, then all together, at the raw cpu_interrupts bits.

Spec sources: interrupts.adoc smc-interrupts-risc-v-plic (active-high, level-sensitive gateways
behind prim_sync3), interrupts.adoc cpu-interrupt-vector-map (raw bit N = PLIC ID N+1,
cpu_interrupts_o[NumExtInterrupts-1:0] = synchronised smc_ext_interrupts_i).

The bench drives inputs 17..255 on tb_ext_interrupts_ext_i (bit 0 of the bus is raw bit 17);
inputs 0, 1 and 2..16 keep their own pins and stay 0 here. The PLIC pending state of each walked
ID is read passively and only logged; its register map, route, bound and retention are open.
"""

from __future__ import annotations

import os
import random

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

SCRATCH_COLD_WARM_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR")
# TB ceiling for a pin-to-raw-bit transition in clk_smc_i rises; not a latency claim.
WAIT_BOUND_RISES = 64
# The external inputs pass a three-flop synchroniser (interrupts.adoc).
SYNC_FLOPS = 3
HOLD_RISES = 8
BASELINE_RISES = 16
NUM_EXT = 256
EXT_MASK = (1 << NUM_EXT) - 1
FIRST_UPPER = 17
UPPER = tuple(range(FIRST_UPPER, NUM_EXT))
UPPER_MASK = sum(1 << b for b in UPPER)
LOWER_MASK = (1 << FIRST_UPPER) - 1
CHECKERS = (
    "CHK-EXTWALK-ALL-HIGH",
    "CHK-EXTWALK-ALL-LOW",
    "CHK-EXTWALK-BASELINE",
    "CHK-EXTWALK-BUS-ALIVE",
    "CHK-EXTWALK-FALL",
    "CHK-EXTWALK-ISOLATION",
    "CHK-EXTWALK-RISE",
)
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


class smc_ext_irq_upper_walk_test_seq(SmcCsrSeq):
    """Raise and lower each of inputs 17..255 alone, then all of them, and watch the raw vector."""

    def __init__(self, name: str = "smc_ext_irq_upper_walk_test_seq") -> None:
        super().__init__(name)
        self.seed = int(os.environ.get("RANDOM_SEED", "1"), 0)
        self.walk = random.Random(self.seed).sample(UPPER, len(UPPER))
        self.done = False
        self.chk_seen: list[str] = []
        self._baseline = 0
        self._plic = None
        self._rises: dict[int, int] = {}
        self._falls: dict[int, int] = {}
        self._iso_samples = 0
        self._last_upper = 0

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self.chk_seen.append(chk_id)

    @staticmethod
    def _sample(label: str) -> int:
        sig = cocotb.top.tb_cpu_interrupts
        assert sig.value.is_resolvable, f"{label}: tb_cpu_interrupts is X/Z ({sig.value})"
        return int(sig.value)

    @staticmethod
    def _ext_pin() -> int:
        sig = cocotb.top.tb_ext_interrupts_ext_i
        assert sig.value.is_resolvable, f"tb_ext_interrupts_ext_i is X/Z ({sig.value})"
        return int(sig.value)

    @staticmethod
    def _drive(upper_bits: int, label: str) -> None:
        cocotb.top.tb_ext_interrupts_ext_i.value = upper_bits >> FIRST_UPPER
        cocotb.log.info("DRIVE %s: raw bits [255:17] = 0x%x", label, upper_bits)

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

    def _pending(self, bit: int) -> str:
        """Passive read of the PLIC pending bit of raw bit `bit` (source ID bit + 1); logged only."""
        if self._plic is None:
            return "n/a"
        try:
            val = getattr(self._plic, f"pending_{bit}").value
        except AttributeError:
            return "n/a"
        return str(int(val)) if val.is_resolvable else str(val)

    def _check_vector(self, vec: int, want_upper: int, label: str) -> None:
        expect = self._baseline | want_upper
        assert vec == expect, (
            f"{label}: tb_cpu_interrupts 0x{vec:x} want 0x{expect:x} "
            f"(baseline 0x{self._baseline:x}, XOR 0x{vec ^ expect:x})"
        )

    async def _wait_upper(self, want_upper: int, label: str) -> int:
        """Rises until raw bits [255:17] read `want_upper` while every other bit holds baseline."""
        last = self._sample(f"{label} entry")
        for n in range(1, WAIT_BOUND_RISES + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            last = self._sample(f"{label}[{n}]")
            moved = (last ^ self._baseline) & ~UPPER_MASK
            assert moved == 0, (
                f"{label}[{n}]: a bit outside [255:17] moved: vector 0x{last:x} "
                f"baseline 0x{self._baseline:x} (XOR 0x{moved:x})"
            )
            changed = (last ^ self._baseline) & UPPER_MASK
            assert changed & ~(want_upper | self._last_upper) == 0, (
                f"{label}[{n}]: an undriven upper bit moved: vector 0x{last:x} "
                f"driven 0x{want_upper:x}, previous 0x{self._last_upper:x} (XOR 0x{changed:x})"
            )
            self._iso_samples += 1
            if changed == want_upper:
                self._last_upper = want_upper
                return n
        raise AssertionError(
            f"{label}: raw bits [255:17] did not reach 0x{want_upper:x} within "
            f"{WAIT_BOUND_RISES} clk_smc_i rises (last vector 0x{last:x})"
        )

    async def _hold(self, want_upper: int, rises: int, label: str) -> None:
        for n in range(1, rises + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            self._check_vector(self._sample(f"{label}[{n}]"), want_upper, f"{label}[{n}/{rises}]")
            self._iso_samples += 1

    async def _walk_one(self, bit: int) -> None:
        label = f"BIT{bit}"
        mask = 1 << bit
        self._drive(mask, f"{label} set")
        rise = await self._wait_upper(mask, f"{label}_RISE")
        assert rise >= SYNC_FLOPS, (
            f"{label}: raw bit {bit} rose after {rise} rises, before the {SYNC_FLOPS}-flop "
            "synchroniser latency"
        )
        await self._hold(mask, HOLD_RISES, f"{label}_HOLD")
        pend = self._pending(bit)
        self._drive(0, f"{label} clear")
        fall = await self._wait_upper(0, f"{label}_FALL")
        assert fall >= SYNC_FLOPS, (
            f"{label}: raw bit {bit} fell after {fall} rises, before the {SYNC_FLOPS}-flop "
            "synchroniser latency"
        )
        await self._hold(0, HOLD_RISES, f"{label}_CLEARED")
        self._rises[bit] = rise
        self._falls[bit] = fall
        cocotb.log.info(
            "LIFECYCLE %s: raw bit %d rose after %d rises, held %d, fell after %d rises, "
            "measured pending(ID %d) while high=%s",
            label,
            bit,
            rise,
            HOLD_RISES,
            fall,
            bit + 1,
            pend,
        )

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
        assert hasattr(dut, "tb_ext_interrupts_ext_i"), "tb_ext_interrupts_ext_i missing"
        await self.wait_fuse_sense_done()
        assert self._ext_pin() == 0, f"tb_ext_interrupts_ext_i reads 0x{self._ext_pin():x}, want 0"
        lower = tuple(
            int(sig.value)
            for sig in (
                dut.tb_ext_interrupt_0_i,
                dut.tb_temp_interrupt_i,
                dut.tb_ext_interrupts_hi_i,
            )
        )
        assert lower == (0, 0, 0), f"pins (ext0, temp, hi) = {lower}, want (0, 0, 0)"
        await self._baseline_window()
        plic_where = self._resolve_plic()
        self._chk(
            "CHK-EXTWALK-BASELINE",
            f"tb_cpu_interrupts=0x{self._baseline:x}, raw [255:0]=0 on {BASELINE_RISES} "
            f"consecutive rises, tb_ext_interrupts_ext_i=0, PLIC pending probe {plic_where}",
        )
        cocotb.log.info("RAND-SEED: %d; RAND-DRAW: walk order %s", self.seed, self.walk)

        for bit in self.walk:
            await self._walk_one(bit)

        slow_rise = max(self._rises.values())
        slow_fall = max(self._falls.values())
        self._chk(
            "CHK-EXTWALK-RISE",
            f"{len(self._rises)} inputs 17..255 each rose at the raw bit within "
            f"{WAIT_BOUND_RISES} rises (slowest {slow_rise}, floor {SYNC_FLOPS}); "
            f"drawn=seed {self.seed}",
        )
        self._chk(
            "CHK-EXTWALK-FALL",
            f"{len(self._falls)} inputs 17..255 each fell at the raw bit within "
            f"{WAIT_BOUND_RISES} rises (slowest {slow_fall}, floor {SYNC_FLOPS}) and held 0 "
            f"for {HOLD_RISES} rises",
        )

        self._drive(UPPER_MASK, "ALL set")
        rise = await self._wait_upper(UPPER_MASK, "ALL_RISE")
        await self._hold(UPPER_MASK, HOLD_RISES, "ALL_HOLD")
        self._chk(
            "CHK-EXTWALK-ALL-HIGH",
            f"raw bits [255:17] all 1 after {rise} rises and for {HOLD_RISES} rises with bits "
            f"[16:0] at baseline 0x{self._baseline & LOWER_MASK:x}",
        )
        self._drive(0, "ALL clear")
        fall = await self._wait_upper(0, "ALL_FALL")
        await self._hold(0, HOLD_RISES, "ALL_CLEARED")
        self._chk(
            "CHK-EXTWALK-ALL-LOW",
            f"raw bits [255:17] all 0 after {fall} rises and the vector equals baseline "
            f"0x{self._baseline:x} for {HOLD_RISES} rises",
        )
        self._chk(
            "CHK-EXTWALK-ISOLATION",
            f"{self._iso_samples} samples over the walk and the all-high leg: no bit outside the "
            "driven set left baseline",
        )
        got = await self.csr_read("SCRATCH_COLD_WARM_0", SCRATCH_COLD_WARM_0, expected=0)
        self._chk("CHK-EXTWALK-BUS-ALIVE", f"SCRATCH_COLD_WARM_0=0x{got:x} after the walk")
        self.done = True
