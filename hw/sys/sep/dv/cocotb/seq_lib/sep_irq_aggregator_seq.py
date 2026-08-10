# SPDX-License-Identifier: Apache-2.0
"""CSRNG/EDN interrupt-injection driver for the IP->aggregator (E10) test.

Drives each IP's INTR_ENABLE/INTR_TEST/INTR_STATE over the SEP AXI agent to
inject a real interrupt via the standard OpenTitan INTR_TEST register and W1C-clear
it, mirroring OCAH sep_irq_ip_to_aggregator_test_seq. The aggregated
sep_internal_interrupts bit is observed by the test through the tb_top
sep_internal_interrupts_probe_o mirror (the OSS analog of OCAH's sep_irq_probe_if).

OpenTitan interrupt-register layout (per IP base):
  INTR_STATE  @ +0x00  RW1C  -- set by hardware / INTR_TEST; write-1-to-clear
  INTR_ENABLE @ +0x04  RW    -- gates the IP intr_o = INTR_STATE & INTR_ENABLE
  INTR_TEST   @ +0x08  WO    -- write 1 to a bit to set the matching INTR_STATE bit
CSRNG/EDN bases (hw/sys/sep/rtl/sep_crypto_pkg.sv) and the per-source aggregator-bit map
(hw/sys/sep/rtl/sep.sv sep_internal_interrupts assembly). 32-bit AXI beats
(size=2) via the sep_crypto TL-UL bridge, like the AES/OTBN drivers.
"""

from __future__ import annotations

from dataclasses import dataclass

from seq_lib.sep_axi_reg_driver import SepAxiRegDriver

# CSRNG/EDN stay literal: the generated top-level export has no symbol for either
# aperture (see the note in sep_esrc_bringup_seq.py). Convert once the register flow
# exports them.
CSRNG_BASE = 0x1091_5000
EDN_BASE = 0x1091_5800

INTR_STATE = 0x00
INTR_ENABLE = 0x04
INTR_TEST = 0x08


@dataclass(frozen=True)
class IrqSrc:
    """One interrupt source: its IP base, the bit in that IP's INTR_* registers,
    and the bit it drives in sep_internal_interrupts."""
    name: str
    base: int
    test_bit: int
    agg_idx: int


# OCAH sep_irq_ip_to_aggregator_test_seq sources -> sep.sv aggregator bits.
IRQ_TABLE = (
    IrqSrc("csrng_cmd_req_done", CSRNG_BASE, 0, 23),
    IrqSrc("csrng_entropy_req",  CSRNG_BASE, 1, 24),
    IrqSrc("csrng_hw_inst_exc",  CSRNG_BASE, 2, 25),
    IrqSrc("csrng_fatal_err",    CSRNG_BASE, 3, 26),
    IrqSrc("edn_cmd_req_done",   EDN_BASE,   0, 27),
    IrqSrc("edn_fatal_err",      EDN_BASE,   1, 28),
)


class SepIrqIp(SepAxiRegDriver):
    """Drives CSRNG/EDN interrupt CSRs over the SEP AXI agent. The test owns one."""

    _DRIVER_TAG = "IRQ"

    async def enable(self, src: IrqSrc) -> None:
        """Enable only this source's interrupt (INTR_ENABLE = 1<<bit)."""
        await self._wr(src.base + INTR_ENABLE, 1 << src.test_bit)

    async def inject(self, src: IrqSrc) -> None:
        """Assert the interrupt via INTR_TEST (sets the INTR_STATE bit)."""
        await self._wr(src.base + INTR_TEST, 1 << src.test_bit)

    async def stop_inject(self, src: IrqSrc) -> None:
        """Stop driving INTR_TEST (WO; does not itself clear INTR_STATE)."""
        await self._wr(src.base + INTR_TEST, 0)

    async def clear_state(self, src: IrqSrc) -> None:
        """W1C the INTR_STATE bit (the real deassert path)."""
        await self._wr(src.base + INTR_STATE, 1 << src.test_bit)

    async def read_state_bit(self, src: IrqSrc) -> int:
        return (await self._rd(src.base + INTR_STATE) >> src.test_bit) & 1
