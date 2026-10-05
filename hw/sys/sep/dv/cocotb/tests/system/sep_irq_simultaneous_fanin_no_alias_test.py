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

    Every source alone and every subset of two or more of the cross-IP sources
    (SepIrqFaninCfg) is walked on every run, so no combination depends on the seed.
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
        self.cfg_irq = SepIrqFaninCfg()
        self.logger.info("fan-in config: %s", self.cfg_irq.summary())
        await self.bring_up_no_cpu()
        self.irq = SepIrqIp(self)

        # Start from a known-clear region (clear EVERY possible source, so the
        # baseline is clean whatever the walk drives).
        for src in FANIN_SOURCES:
            await self._drive(src, on=False)
        clear_ok, vec = await self._poll_region(0)
        assert clear_ok, f"[8:33] not clear at baseline (vec=0x{vec:010x})"

        # CHK-NONVAC: each source alone lights EXACTLY its one known bit in [8:33]
        # (proves the per-bit index and that the simultaneous map below is not
        # trivially/stuck passing), then clears.
        for base in self.cfg_irq.baselines:
            await self._drive(base, on=True)
            one_bit = 1 << base.agg_idx
            ok, vec = await self._poll_region(one_bit)
            assert ok, (
                f"baseline {base.name}: [8:33]=0x{vec & REGION_MASK:010x}, "
                f"expected only bit[{base.agg_idx}]"
            )
            await self._drive(base, on=False)
            assert (await self._poll_region(0))[0], f"baseline {base.name} did not clear"
        self.logger.info(
            "CHK-NONVAC PASS: each of %d single sources lit exactly its own bit %s and cleared",
            len(self.cfg_irq.baselines),
            [f"{b.name}[{b.agg_idx}]" for b in self.cfg_irq.baselines],
        )

        four_state = cocotb.SIM_NAME.lower() not in ("verilator",)
        for sources in self.cfg_irq.subsets:
            await self._walk_subset(sources)
        walked = [[s.agg_idx for s in sub] for sub in self.cfg_irq.subsets]
        self.logger.info(
            "CHK-FANIN-MAP PASS: all %d subsets asserted together lit exactly their own "
            "bits, and each source's INTR_STATE read 1: %s",
            len(walked),
            walked,
        )
        if four_state:
            self.logger.info(
                "CHK-ANTI-ALIAS PASS: for all %d subsets [%d:%d] was fully resolved (no "
                "floating leg) and equal to the driven set",
                len(walked),
                REGION_LO,
                REGION_HI,
            )
        else:
            self.logger.info(
                "CHK-ANTI-ALIAS PASS: for all %d subsets [%d:%d] equalled the driven set "
                "(X/Z resolution claimed only on a four-state simulator)",
                len(walked),
                REGION_LO,
                REGION_HI,
            )
        self.logger.info(
            "CHK-CLEAR PASS: after each of the %d subsets every driven source "
            "W1C-cleared and [8:33] read 0",
            len(walked),
        )

    async def _walk_subset(self, sources) -> None:
        """Assert ``sources`` together, grade the packing, then clear them."""
        names = [s.name for s in sources]
        # CHK-FANIN-MAP: the [8:33] region must equal EXACTLY the driven bits
        # (1:1 source->bit packing).
        for src in sources:
            await self._drive(src, on=True)
        want = driven_mask(sources)
        ok, vec = await self._poll_region(want)
        assert ok, (
            f"CHK-FANIN-MAP {names}: [8:33]=0x{vec & REGION_MASK:010x}, expected "
            f"0x{want:010x} (bits {[s.agg_idx for s in sources]})"
        )
        # Per-source evidence is the INTR_STATE read: it addresses the IP's own
        # register rather than the aggregate, whose driven bits the exact-equality
        # poll above already pins.
        for src in sources:
            assert await self.irq.read_state_bit(src) == 1, (
                f"CHK-FANIN-MAP {names}: {src.name} INTR_STATE bit not set"
            )
        # CHK-ANTI-ALIAS: a fresh sample that names this step if a leg is
        # UNDRIVEN: the whole region must be resolved and equal the driven set.
        raw_region = await self._assert_region_resolved(f"simultaneous fan-in {names}")
        assert raw_region == (want & REGION_MASK), (
            f"CHK-ANTI-ALIAS {names}: raw [{REGION_LO}:{REGION_HI}]=0x{raw_region:010x}, "
            f"expected 0x{want & REGION_MASK:010x} -- a non-driven bit is aliasing"
        )
        # CHK-CLEAR: W1C every driven source's INTR_STATE -> the region returns to 0
        # and each IP's INTR_STATE bit reads 0 (RW1C deassert path).
        for src in sources:
            await self._drive(src, on=False)
        ok, vec = await self._poll_region(0)
        assert ok, f"CHK-CLEAR {names}: [8:33] not clear after W1C (vec=0x{vec:010x})"
        # This leg's passing value is zero, so re-sample and require the region to
        # be resolved: a leg that stopped being driven must not read as cleared.
        cleared = await self._assert_region_resolved(f"after W1C {names}")
        assert cleared == 0, (
            f"CHK-CLEAR {names}: [8:33] resolved to 0x{cleared:010x} after W1C, expected 0"
        )
        for src in sources:
            assert await self.irq.read_state_bit(src) == 0, (
                f"CHK-CLEAR {names}: {src.name} INTR_STATE bit not cleared by W1C"
            )
        self.logger.info(
            "fan-in subset %s -> bits %s: map, anti-alias and clear held",
            names,
            [s.agg_idx for s in sources],
        )
