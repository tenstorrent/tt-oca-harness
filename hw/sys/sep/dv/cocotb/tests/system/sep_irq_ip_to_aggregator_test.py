# SPDX-License-Identifier: Apache-2.0
"""IP-interrupt -> sep_internal_interrupts aggregator.

reference ref: sep_irq_ip_to_aggregator_test (+ _seq, extends sep_irq_connectivity_
test_seq). no_cpu: with the CPU held off, the host injects each CSRNG/EDN
interrupt via its real INTR_TEST register and proves it propagates to the mapped
bit of the sep_internal_interrupts aggregate vector that feeds the VeeR PIC --
exercising the IP `intr_o` -> aggregator wiring (sep.sv:451-461), not merely that
the IP raised its own status bit.

The aggregate vector has no frontdoor CSR mirror and the PIC is on the CPU bus
(unreachable with the CPU held off), so the test observes it through the tb_top
`sep_internal_interrupts_probe_o` (observation-only XMR mirror, signed off; the
OSS analog of the reference suite's sep_irq_probe_if wire-tap of sep_interrupts[idx]). The IP-
local INTR_STATE RW1C contract is checked frontdoor over AXI.

Per source (CSRNG cmd_req_done/entropy_req/hw_inst_exc/fatal_err -> bits 23..26;
EDN cmd_req_done/fatal_err -> bits 27..28), the full reference suite 3-phase check:
  CHK-BASE  clear INTR_TEST + W1C INTR_STATE -> aggregate bit reads 0
            (non-vacuity: a stuck-high aggregate bit fails here).
  CHK-SET   INTR_ENABLE + INTR_TEST -> aggregate bit reads 1 AND INTR_STATE bit 1
            (proves INTR_TEST -> intr_o -> sep_internal_interrupts[idx]); a stuck-
            low / mis-wired aggregate bit fails here.
  CHK-ISO   while this source is asserted, the OTHER 5 mapped bits stay 0
            (one-hot aggregation -- catches an OR-network smear; stronger than
            reference suite, which checks one source at a time).
  CHK-CLR   W1C INTR_STATE -> aggregate bit returns 0 AND INTR_STATE bit 0
            (RW1C deassert path).

INTR_TEST sets INTR_STATE regardless of IP functional state, so no entropy bring-
up is needed: +skip_fuse_sense, no_cpu.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
import pyuvm

from sep_base_test import sep_base_test
from seq_lib.sep_irq_aggregator_seq import SepIrqIp, IRQ_TABLE


@pyuvm.test()
class sep_irq_ip_to_aggregator_test(sep_base_test):
    """CSRNG/EDN INTR_TEST -> sep_internal_interrupts aggregator (no_cpu)."""

    async def _sample_agg(self) -> int:
        """Sample the whole aggregate vector once (one clock edge + ReadOnly).

        Returns the 32-bit probe value so callers can test any number of bits from
        a single settled sample -- never await ReadOnly more than once per timestep.
        """
        await RisingEdge(cocotb.top.clk_i)
        await ReadOnly()
        return self.rd(cocotb.top.sep_internal_interrupts_probe_o)

    async def _poll_agg(self, idx: int, expect: int, *, timeout: int = 200) -> tuple[bool, int]:
        sample = 0
        for _ in range(timeout):
            sample = await self._sample_agg()
            if ((sample >> idx) & 1) == expect:
                return True, sample
        return False, sample

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        self.irq = SepIrqIp(self)

        for src in IRQ_TABLE:
            # CHK-BASE: drive to a known-clear state and prove the aggregate bit is
            # low (a stuck-high bit would fail here -> the SET check is non-vacuous).
            await self.irq.stop_inject(src)
            await self.irq.clear_state(src)
            base_ok, base_vec = await self._poll_agg(src.agg_idx, 0)
            assert base_ok, (
                f"{src.name}: sep_internal_interrupts[{src.agg_idx}] not low at baseline"
            )
            self.logger.info(
                "STEP %s: INTR_TEST + INTR_STATE pre-cleared; aggregate bit[%d] "
                "baseline-low confirmed (vec=0x%08x)", src.name, src.agg_idx, base_vec,
            )

            # CHK-SET: enable then inject via INTR_TEST; the mapped aggregate bit must
            # go high and the IP's own INTR_STATE bit must set.
            await self.irq.enable(src)
            await self.irq.inject(src)
            self.logger.info(
                "STEP %s: interrupt enabled and INTR_TEST bit %d injected",
                src.name, src.test_bit,
            )
            set_ok, _ = await self._poll_agg(src.agg_idx, 1)
            assert set_ok, (
                f"{src.name}: INTR_TEST did not propagate to "
                f"sep_internal_interrupts[{src.agg_idx}]"
            )
            assert await self.irq.read_state_bit(src) == 1, (
                f"{src.name}: INTR_STATE bit not set after INTR_TEST"
            )

            # CHK-ISO: from a single fresh sample (injection still active), only this
            # source's bit is set among the mapped sources -- one-hot aggregation,
            # catching an OR-network smear.
            iso = await self._sample_agg()
            assert (iso >> src.agg_idx) & 1, (
                f"{src.name}: aggregate bit[{src.agg_idx}] dropped before isolation check"
            )
            for other in IRQ_TABLE:
                if other.agg_idx == src.agg_idx:
                    continue
                assert ((iso >> other.agg_idx) & 1) == 0, (
                    f"{src.name} asserted but sep_internal_interrupts[{other.agg_idx}] "
                    f"({other.name}) is also set -- aggregator smear (vec=0x{iso:08x})"
                )

            # CHK-CLR: W1C INTR_STATE -> aggregate bit returns low and INTR_STATE clears.
            await self.irq.stop_inject(src)
            await self.irq.clear_state(src)
            clr_ok, _ = await self._poll_agg(src.agg_idx, 0)
            assert clr_ok, (
                f"{src.name}: sep_internal_interrupts[{src.agg_idx}] stuck after W1C clear"
            )
            assert await self.irq.read_state_bit(src) == 0, (
                f"{src.name}: INTR_STATE bit not cleared by W1C"
            )
            self.logger.info(
                "%s PASS: INTR_TEST -> sep_internal_interrupts[%d] 0->1->0 + "
                "INTR_STATE RW1C + isolation (vec=0x%08x)",
                src.name, src.agg_idx, iso)

        self.logger.info(
            "CHK-AGG PASS: all %d CSRNG/EDN IRQs propagate to the aggregator, "
            "one-hot, with RW1C clear", len(IRQ_TABLE))
