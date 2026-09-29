# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""IP-interrupt -> sep_internal_interrupts aggregator.

reference ref: sep_irq_ip_to_aggregator_test (+ _seq, extends sep_irq_connectivity_
test_seq). no_cpu: with the CPU held off, the host injects each covered IP
interrupt via its real INTR_TEST register and proves it propagates to the mapped
bit of the sep_internal_interrupts aggregate vector that feeds the VeeR PIC --
exercising the IP `intr_o` -> aggregator wiring (sep.sv:530-578), not merely that
the IP raised its own status bit. HMAC error is Event-type (W1C). DMA done /
chunk / error are Status-type (INTR_TEST=0 deasserts). HMAC/KMAC fifo_empty
Status bits are idle-true and are not walked.

The aggregate vector has no frontdoor CSR mirror and the PIC is on the CPU bus
(unreachable with the CPU held off), so the test observes it through the tb_top
`sep_internal_interrupts_probe_o` (observation-only XMR mirror; the OSS analog of
the reference suite's sep_irq_probe_if wire-tap of sep_interrupts[idx]). The IP-
local INTR_STATE RW1C contract is checked frontdoor over AXI.

Per source (CSRNG bits 23..26, EDN bits 27..28, HMAC error bit 19, DMA done /
chunk / error bits 8..10), the 3-phase check:
  CHK-BASE  clear INTR_TEST + W1C INTR_STATE -> aggregate bit reads 0
            (non-vacuity: a stuck-high aggregate bit fails here).
  CHK-SET   INTR_ENABLE + INTR_TEST -> aggregate bit reads 1 AND INTR_STATE bit 1
            (proves INTR_TEST -> intr_o -> sep_internal_interrupts[idx]); a stuck-
            low / mis-wired aggregate bit fails here.
  CHK-ISO   while this source is asserted, the OTHER 5 mapped bits stay 0
            (one-hot aggregation -- catches an OR-network smear; stronger than
            reference suite, which checks one source at a time).
  CHK-CLR   Event: W1C INTR_STATE -> aggregate bit returns 0 AND INTR_STATE bit 0.
            Status: INTR_TEST=0 -> the same two zeros (INTR_STATE is read-only).

Then one through-adapter SLVERR on the Secure DMA register hole and one on
each HMAC / KMAC / OTBN CSR gap:
  CHK-BUSERR-BASE   both STATUS words and aggregator [40]/[42] read 0
  CHK-BUSERR-DMA    DMA hole read is SLVERR; exclusive reg_path_err; [40]=1
  CHK-BUSERR-PERIPH each hole read is SLVERR; exclusive hmac / kmac / otbn; [42]=1
  CHK-BUSERR-CLR    each matching CLEAR write returns STATUS and the PIC bit to 0

A beat past an adapter window is DECERR and never sets err_o. AES, CSRNG,
EDN and WDT windows are packed to the last register. This leaf does not
start a DMA transfer, so it does not prove host_path_err / bit 41.
Lockstep punch-through has no frontdoor on this build.

INTR_TEST sets INTR_STATE regardless of IP functional state, so no entropy bring-
up is needed: +skip_fuse_sense, no_cpu.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ReadOnly, RisingEdge
from sep_base_test import sep_base_test
from seq_lib.sep_irq_aggregator_seq import (
    DMA_CLEAR_ADDR,
    DMA_CLR_BIT,
    DMA_REG_PATH_BIT,
    DMA_STATUS_ADDR,
    IRQ_DMA_HOST_PATH,
    IRQ_DMA_REG_PATH,
    IRQ_PERIPH_OR,
    IRQ_TABLE,
    PERIPH_CLEAR_ADDR,
    PERIPH_STATUS_ADDR,
    SepIrqIp,
    dma_reg_unmapped_addr,
    periph_holes,
)


@pyuvm.test()
class sep_irq_ip_to_aggregator_test(sep_base_test):
    """CSRNG/EDN INTR_TEST -> sep_internal_interrupts aggregator (no_cpu)."""

    async def _sample_agg_known(self, mask: int) -> int:
        """Sample the vector, requiring the bits in ``mask`` to be 0 or 1.

        One clock edge + ReadOnly per call. ``rd`` raises on an X/Z bit inside
        ``mask``, so ``bit == 0`` cannot hold for a bit nothing drives -- the
        risk on bit [41], a source this leaf never raises. Only the named bits
        are required to be known; the rest of the vector may legitimately be X.
        """
        await RisingEdge(cocotb.top.clk_i)
        await ReadOnly()
        return self.rd_known(cocotb.top.sep_internal_interrupts_probe_o, mask)

    async def _poll_agg(self, idx: int, expect: int, *, timeout: int = 200) -> tuple[bool, int]:
        sample = 0
        for _ in range(timeout):
            sample = await self._sample_agg_known(1 << idx)
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
                "baseline-low confirmed (vec=0x%08x)",
                src.name,
                src.agg_idx,
                base_vec,
            )

            # CHK-SET: enable then inject via INTR_TEST; the mapped aggregate bit must
            # go high and the IP's own INTR_STATE bit must set.
            await self.irq.enable(src)
            await self.irq.inject(src)
            self.logger.info(
                "STEP %s: interrupt enabled and INTR_TEST bit %d injected",
                src.name,
                src.test_bit,
            )
            set_ok, _ = await self._poll_agg(src.agg_idx, 1)
            assert set_ok, (
                f"{src.name}: INTR_TEST did not propagate to sep_internal_interrupts[{src.agg_idx}]"
            )
            assert await self.irq.read_state_bit(src) == 1, (
                f"{src.name}: INTR_STATE bit not set after INTR_TEST"
            )

            # CHK-ISO: from a single fresh sample (injection still active), only this
            # source's bit is set among the mapped sources -- one-hot aggregation,
            # catching an OR-network smear.
            iso_mask = 0
            for mapped in IRQ_TABLE:
                iso_mask |= 1 << mapped.agg_idx
            iso = await self._sample_agg_known(iso_mask)
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

            # CHK-CLR: Event sources W1C INTR_STATE; Status sources drop INTR_TEST.
            await self.irq.stop_inject(src)
            if src.kind == "event":
                await self.irq.clear_state(src)
            clr_ok, _ = await self._poll_agg(src.agg_idx, 0)
            clr_how = "W1C clear" if src.kind == "event" else "INTR_TEST release"
            assert clr_ok, (
                f"{src.name}: sep_internal_interrupts[{src.agg_idx}] stuck after {clr_how}"
            )
            assert await self.irq.read_state_bit(src) == 0, (
                f"{src.name}: INTR_STATE bit not cleared by {clr_how}"
            )
            self.logger.info(
                "%s PASS: INTR_TEST -> sep_internal_interrupts[%d] 0->1->0 + "
                "%s + isolation (vec=0x%08x)",
                src.name,
                src.agg_idx,
                "INTR_STATE RW1C" if src.kind == "event" else "Status-type INTR_TEST release",
                iso,
            )

        self.logger.info(
            "CHK-AGG PASS: all %d HMAC/DMA/CSRNG/EDN IRQs propagate to the aggregator, "
            "one-hot, with Event W1C / Status INTR_TEST release",
            len(IRQ_TABLE),
        )
        await self._check_bus_err_paths()

    async def _agg_bit(self, idx: int) -> int:
        return (await self._sample_agg_known(1 << idx) >> idx) & 1

    async def _check_bus_err_paths(self) -> None:
        dma_hole = dma_reg_unmapped_addr()
        holes = periph_holes()

        dma_st = await self.irq.read32(DMA_STATUS_ADDR)
        periph_st = await self.irq.read32(PERIPH_STATUS_ADDR)
        assert dma_st == 0, f"DMA_BUS_ERR_STATUS=0x{dma_st:x} at baseline, expected 0"
        assert periph_st == 0, f"PERIPH_BUS_ERR_STATUS=0x{periph_st:x} at baseline, expected 0"
        assert await self._agg_bit(IRQ_DMA_REG_PATH) == 0, (
            "sep_internal_interrupts[40] high before a DMA register-path fault"
        )
        assert await self._agg_bit(IRQ_PERIPH_OR) == 0, (
            "sep_internal_interrupts[42] high before a peripheral bridge fault"
        )
        self.logger.info("CHK-BUSERR-BASE PASS: DMA/PERIPH STATUS=0; aggregator [40]/[42]=0")

        await self.irq.read_expect_slverr(dma_hole)
        dma_st = await self.irq.read32(DMA_STATUS_ADDR)
        periph_st = await self.irq.read32(PERIPH_STATUS_ADDR)
        assert dma_st == DMA_REG_PATH_BIT, (
            f"DMA_BUS_ERR_STATUS=0x{dma_st:x} after 0x{dma_hole:08x}, "
            f"expected exclusive reg_path_err=0x{DMA_REG_PATH_BIT:x}"
        )
        assert periph_st == 0, (
            f"PERIPH_BUS_ERR_STATUS=0x{periph_st:x} after the DMA hole, expected 0"
        )
        dma_ok, dma_vec = await self._poll_agg(IRQ_DMA_REG_PATH, 1)
        assert dma_ok, (
            f"sep_internal_interrupts[{IRQ_DMA_REG_PATH}] stayed 0 after "
            f"DMA register-path SLVERR (vec=0x{dma_vec:x})"
        )
        # Exclusivity, not liveness: a register-path fault must not raise the
        # host-path or peripheral-OR source. Re-sampled with the two bits
        # required to be known -- this leaf never drives [41] high (see the
        # module docstring), so an undriven or X bit would otherwise satisfy
        # "== 0" on any RTL.
        excl_mask = (1 << IRQ_DMA_HOST_PATH) | (1 << IRQ_PERIPH_OR)
        excl_vec = await self._sample_agg_known(excl_mask)
        assert ((excl_vec >> IRQ_DMA_HOST_PATH) & 1) == 0, (
            "host-path bit [41] set on a register-path fault"
        )
        assert ((excl_vec >> IRQ_PERIPH_OR) & 1) == 0, (
            "periph OR [42] set on a DMA register-path fault"
        )
        self.logger.info(
            "CHK-BUSERR-DMA PASS: 0x%08x SLVERR; STATUS=0x%x exclusive; [40]=1",
            dma_hole,
            dma_st,
        )

        # DMA_BUS_ERR_CLEAR is sw=w singlepulse and always reads 0, so its read
        # value is not a contract the DUT can fail. The clear is proven by the
        # STATUS bit and the aggregator bit going back to 0 below.
        await self.irq.write32(DMA_CLEAR_ADDR, DMA_CLR_BIT)
        dma_st = await self.irq.read32(DMA_STATUS_ADDR)
        assert dma_st == 0, f"DMA_BUS_ERR_STATUS=0x{dma_st:x} after CLEAR, expected 0"
        clr_ok, _ = await self._poll_agg(IRQ_DMA_REG_PATH, 0)
        assert clr_ok, "sep_internal_interrupts[40] stuck after DMA_BUS_ERR_CLEAR"
        self.logger.info("CHK-BUSERR-CLR PASS: DMA_BUS_ERR_CLEAR; STATUS=0; [40]=0")

        # The read leg above walks TL_GET_REQ/GET_ACK. A write to the same hole
        # walks TL_PUT_REQ/PUT_ACK/AXI_B_RESP (axi_lite_to_tlul.sv:189-220), a
        # separate FSM arm with its own opcode select, and raises the sticky
        # error from BRESP rather than RRESP.
        await self.irq.write_expect_slverr(dma_hole, 0xA5A5_1234)
        dma_st = await self.irq.read32(DMA_STATUS_ADDR)
        periph_st = await self.irq.read32(PERIPH_STATUS_ADDR)
        assert dma_st == DMA_REG_PATH_BIT, (
            f"DMA_BUS_ERR_STATUS=0x{dma_st:x} after a write to 0x{dma_hole:08x}, "
            f"expected exclusive reg_path_err=0x{DMA_REG_PATH_BIT:x}"
        )
        assert periph_st == 0, (
            f"PERIPH_BUS_ERR_STATUS=0x{periph_st:x} after the DMA write hole, expected 0"
        )
        wr_ok, wr_vec = await self._poll_agg(IRQ_DMA_REG_PATH, 1)
        assert wr_ok, (
            f"sep_internal_interrupts[{IRQ_DMA_REG_PATH}] stayed 0 after a DMA "
            f"register-path write SLVERR (vec=0x{wr_vec:x})"
        )
        excl_vec = await self._sample_agg_known(excl_mask)
        assert ((excl_vec >> IRQ_DMA_HOST_PATH) & 1) == 0, (
            "host-path bit [41] set on a register-path write fault"
        )
        assert ((excl_vec >> IRQ_PERIPH_OR) & 1) == 0, (
            "periph OR [42] set on a DMA register-path write fault"
        )
        self.logger.info(
            "CHK-BUSERR-DMA-WR PASS: write 0x%08x BRESP=SLVERR; STATUS=0x%x exclusive; [40]=1",
            dma_hole,
            dma_st,
        )

        await self.irq.write32(DMA_CLEAR_ADDR, DMA_CLR_BIT)
        dma_st = await self.irq.read32(DMA_STATUS_ADDR)
        assert dma_st == 0, (
            f"DMA_BUS_ERR_STATUS=0x{dma_st:x} after CLEAR of the write fault, expected 0"
        )
        clr_ok, _ = await self._poll_agg(IRQ_DMA_REG_PATH, 0)
        assert clr_ok, "sep_internal_interrupts[40] stuck after clearing the write fault"
        self.logger.info("CHK-BUSERR-DMA-WR-CLR PASS: STATUS=0; [40]=0")

        for hole in holes:
            await self.irq.read_expect_slverr(hole.addr)
            periph_st = await self.irq.read32(PERIPH_STATUS_ADDR)
            dma_st = await self.irq.read32(DMA_STATUS_ADDR)
            assert periph_st == hole.status_bit, (
                f"PERIPH_BUS_ERR_STATUS=0x{periph_st:x} after 0x{hole.addr:08x}, "
                f"expected exclusive {hole.name}=0x{hole.status_bit:x}"
            )
            assert dma_st == 0, (
                f"DMA_BUS_ERR_STATUS=0x{dma_st:x} after the {hole.name} hole, expected 0"
            )
            per_ok, per_vec = await self._poll_agg(IRQ_PERIPH_OR, 1)
            assert per_ok, (
                f"sep_internal_interrupts[{IRQ_PERIPH_OR}] stayed 0 after "
                f"{hole.name} adapter SLVERR (vec=0x{per_vec:x})"
            )
            excl = await self._sample_agg_known(1 << IRQ_DMA_REG_PATH)
            assert ((excl >> IRQ_DMA_REG_PATH) & 1) == 0, (
                f"DMA register-path [40] set on a {hole.name} bridge fault"
            )
            self.logger.info(
                "CHK-BUSERR-PERIPH PASS: %s 0x%08x SLVERR; STATUS=0x%x exclusive; [42]=1",
                hole.name,
                hole.addr,
                periph_st,
            )

            await self.irq.write32(PERIPH_CLEAR_ADDR, hole.clear_bit)
            periph_st = await self.irq.read32(PERIPH_STATUS_ADDR)
            assert periph_st == 0, (
                f"PERIPH_BUS_ERR_STATUS=0x{periph_st:x} after {hole.name} CLEAR, expected 0"
            )
            clr_ok, _ = await self._poll_agg(IRQ_PERIPH_OR, 0)
            assert clr_ok, (
                f"sep_internal_interrupts[42] stuck after PERIPH_BUS_ERR_CLEAR.{hole.name}"
            )
            self.logger.info(
                "CHK-BUSERR-CLR PASS: PERIPH_BUS_ERR_CLEAR.%s; STATUS=0; [42]=0",
                hole.name,
            )
