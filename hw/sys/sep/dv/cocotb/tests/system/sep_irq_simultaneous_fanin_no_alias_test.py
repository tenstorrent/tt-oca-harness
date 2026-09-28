# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Simultaneous multi-source interrupt fan-in + anti-alias.

With the CPU held off, the host asserts SEVERAL IP interrupts at once (HMAC done,
KMAC done, CSRNG cmd_req_done, EDN cmd_req_done -> sep_internal_interrupts bits
17/20/23/27, per hw/sys/sep/doc/interrupts.adoc) via each IP's real INTR_TEST
register, then reads the aggregate vector (tb_top sep_internal_interrupts_probe_o,
the observation-only mirror) and proves the OR-packing assembled EXACTLY those bits
-- a 1:1 source->bit map with no non-driven neighbor in [8:33] aliasing.
X/Z resolution of that region is graded only on a four-state simulator. A packing
that truncates a multi-bit source or aliases a neighbour is the defect class this
leaf targets in the crypto/KM region.

reference ref: sep_irq_extended_connectivity_test.
The reference suite asserts connectivity one source at a time; this
test asserts a cross-IP set SIMULTANEOUSLY and proves no aggregator smear. Distinct
from the single-source-at-a-time aggregator check (sep_irq_ip_to_aggregator_test)
and from the CPU PIC/ISR delivery path. CPU-ISR delivery of the simultaneous set and
the full 32-source cross-product are not covered here.

no_cpu + +skip_fuse_sense: INTR_TEST sets INTR_STATE regardless of IP functional
state, so no entropy/fuse bring-up is needed.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ReadOnly, RisingEdge
from sep_base_test import sep_base_test
from seq_lib.sep_irq_aggregator_seq import SepIrqIp
from seq_lib.sep_irq_fanin_seq import (
    FANIN_SOURCES,
    REGION_HI,
    REGION_LO,
    REGION_MASK,
    SepIrqFaninCfg,
    driven_mask,
)


@pyuvm.test()
class sep_irq_simultaneous_fanin_no_alias_test(sep_base_test):
    """Several IP IRQs asserted at once -> exact 1:1 aggregator packing, no alias.

    RANDOMIZED: which subset (>=2) of the cross-IP sources is asserted simultaneously,
    and the non-vacuity baseline source, vary per seed (SepIrqFaninCfg). The full
    [8:33] anti-alias contract is identical for every subset.
    """

    async def _sample_agg(self) -> int:
        """Sample the [8:33] region of the aggregate once (one clock edge + ReadOnly).

        self.rd() raises on an X/Z bit inside REGION_MASK, so a zero here is a
        driven zero. Bits outside the region are not read and return as 0.
        """
        await RisingEdge(cocotb.top.clk_i)
        await ReadOnly()
        return self.rd(cocotb.top.sep_internal_interrupts_probe_o, mask=REGION_MASK)

    async def _assert_region_resolved(self, where: str) -> int:
        """Sample the probe once more and require every [8:33] bit to be 0 or 1.

        Names the check point in the failure message, so an undriven aggregator
        leg is reported against the step where it was seen. Returns the region
        value.
        """
        await RisingEdge(cocotb.top.clk_i)
        await ReadOnly()
        try:
            vec = self.rd_known(cocotb.top.sep_internal_interrupts_probe_o, REGION_MASK)
        except AssertionError as exc:
            raise AssertionError(f"[{where}] aggregator leg not driven: {exc}") from exc
        return vec & REGION_MASK

    async def _poll_region(self, expect_bits: int, *, timeout: int = 400) -> tuple[bool, int]:
        """Poll until the [8:33] region of the aggregate equals exactly expect_bits."""
        sample = 0
        for _ in range(timeout):
            sample = await self._sample_agg()
            if (sample & REGION_MASK) == (expect_bits & REGION_MASK):
                return True, sample
        return False, sample

    async def _drive(self, src, *, on: bool) -> None:
        if on:
            await self.irq.enable(src)
            await self.irq.inject(src)
        else:
            await self.irq.stop_inject(src)
            await self.irq.clear_state(src)

    async def run_scenario(self) -> None:
        self.cfg_irq = SepIrqFaninCfg(self.random_seed())
        self.logger.info("fan-in config: %s", self.cfg_irq.summary())
        await self.bring_up_no_cpu()
        self.irq = SepIrqIp(self)

        # Start from a known-clear region (clear EVERY possible source, not just the
        # seeded subset, so the baseline is clean regardless of the subset).
        for src in FANIN_SOURCES:
            await self._drive(src, on=False)
        clear_ok, vec = await self._poll_region(0)
        assert clear_ok, f"[8:33] not clear at baseline (vec=0x{vec:010x})"

        # CHK-NONVAC: a single source lights EXACTLY its one known bit in [8:33]
        # (proves the per-bit index and that the simultaneous map below is not
        # trivially/stuck passing). Then clear it.
        base = self.cfg_irq.baseline
        await self._drive(base, on=True)
        one_bit = 1 << base.agg_idx
        ok, vec = await self._poll_region(one_bit)
        assert ok, (
            f"baseline {base.name}: [8:33]=0x{vec & REGION_MASK:010x}, "
            f"expected only bit[{base.agg_idx}]"
        )
        self.logger.info(
            "CHK-NONVAC PASS: single source %s lights exactly bit[%d]",
            base.name,
            base.agg_idx,
        )
        await self._drive(base, on=False)
        assert (await self._poll_region(0))[0], "baseline source did not clear"

        # CHK-FANIN-MAP: assert the seeded subset simultaneously; the [8:33] region
        # must equal EXACTLY the driven bits (1:1 source->bit packing).
        sources = self.cfg_irq.sources
        for src in sources:
            await self._drive(src, on=True)
        want = driven_mask(sources)
        ok, vec = await self._poll_region(want)
        assert ok, (
            f"simultaneous fan-in: [8:33]=0x{vec & REGION_MASK:010x}, expected "
            f"0x{want:010x} (bits {[s.agg_idx for s in sources]})"
        )
        # Per-source evidence is the INTR_STATE read: it addresses the IP's own
        # register rather than the aggregate, whose driven bits the exact-equality
        # poll above already pins.
        for src in sources:
            assert await self.irq.read_state_bit(src) == 1, f"{src.name}: INTR_STATE bit not set"
        self.logger.info(
            "CHK-FANIN-MAP PASS: %d sources asserted together -> exactly bits %s "
            "(vec[8:33]=0x%010x)",
            len(sources),
            [s.agg_idx for s in sources],
            vec & REGION_MASK,
        )

        # CHK-ANTI-ALIAS: the set of driven bits is already pinned by the
        # exact-equality poll above, which a smear onto a neighbour breaks. This step
        # adds a fresh sample that names this step if a leg is UNDRIVEN:
        # the whole region must be resolved and equal exactly the driven set.
        raw_region = await self._assert_region_resolved("simultaneous fan-in")
        assert raw_region == (want & REGION_MASK), (
            f"raw [{REGION_LO}:{REGION_HI}]=0x{raw_region:010x}, expected "
            f"0x{want & REGION_MASK:010x} -- a non-driven bit is aliasing"
        )
        four_state = cocotb.SIM_NAME.lower() not in ("verilator",)
        if four_state:
            self.logger.info(
                "CHK-ANTI-ALIAS PASS: [%d:%d] fully resolved (no floating leg) and "
                "equal to the driven set 0x%010x",
                REGION_LO,
                REGION_HI,
                raw_region,
            )
        else:
            self.logger.info(
                "CHK-ANTI-ALIAS PASS: [%d:%d] equals the driven set 0x%010x "
                "(X/Z resolution claimed only on a four-state simulator)",
                REGION_LO,
                REGION_HI,
                raw_region,
            )

        # CHK-CLEAR: W1C every driven source's INTR_STATE -> the region returns to 0
        # and each IP's INTR_STATE bit reads 0 (RW1C deassert path).
        for src in sources:
            await self._drive(src, on=False)
        ok, vec = await self._poll_region(0)
        assert ok, f"[8:33] not clear after W1C (vec=0x{vec:010x})"
        # This leg's passing value is zero, so re-sample and require the region to
        # be resolved: a leg that stopped being driven must not read as cleared.
        cleared = await self._assert_region_resolved("after W1C")
        assert cleared == 0, f"[8:33] resolved to 0x{cleared:010x} after W1C, expected 0"
        for src in sources:
            assert await self.irq.read_state_bit(src) == 0, (
                f"{src.name}: INTR_STATE bit not cleared by W1C"
            )
        self.logger.info(
            "CHK-CLEAR PASS: all %d driven sources W1C-cleared -> [8:33]=0", len(sources)
        )
