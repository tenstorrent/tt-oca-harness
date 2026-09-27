# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CSRNG/EDN interrupt-injection and TL-UL bus-error driver for the aggregator test.

Drives each IP's INTR_ENABLE/INTR_TEST/INTR_STATE over the SEP AXI agent to
inject a real interrupt via the standard OpenTitan INTR_TEST register and W1C-clear
it, mirroring reference sep_irq_ip_to_aggregator_test_seq. The aggregated
sep_internal_interrupts bit is observed by the test through the tb_top
sep_internal_interrupts_probe_o mirror.

Also issues one in-window unmapped 32-bit read through the Secure DMA adapter
and one through each of the HMAC, KMAC and OTBN adapters. Those complete
SLVERR and latch DMA_BUS_ERR_STATUS / PERIPH_BUS_ERR_STATUS, which drive
aggregator bits [40] and [42]. A dead-space beat past an adapter window is
DECERR and never sets err_o, so the probes stay inside each routed extent.
AES, CSRNG, EDN and WDT windows are packed to the last register; an unmapped
beat there is past the rule and DECERRs. Their PERIPH_BUS_ERR_STATUS bits are
unreachable here, which is why periph_holes() names three blocks and not seven.

OpenTitan interrupt-register layout (per IP base):
  INTR_STATE  @ +0x00  Event: RW1C; Status: RO
  INTR_ENABLE @ +0x04  RW    -- gates the IP intr_o = INTR_STATE & INTR_ENABLE
  INTR_TEST   @ +0x08  WO    -- Event: sets INTR_STATE; Status: held until written 0
CSRNG/EDN bases from the generated register map. Aggregator bit =
documented PIC source ID minus 1 (`hw/sys/sep/doc/interrupts.adoc`; PIC
IDs are 1-based). 32-bit AXI beats (size=2) via the sep_crypto TL-UL
bridge, like the AES/OTBN drivers.
"""

from __future__ import annotations

from dataclasses import dataclass

from env.sep_axi_agent import SepAxiOp
from env.sep_spec_tables import pic
from sep_reg_meta import CSRNG, EDN, HMAC, KMAC, OTBN, SEP_CPU_CTRL, RegBlock, sym

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver

CSRNG_BASE = sym("CSRNG_REG_MAP_BASE_ADDR")
EDN_BASE = sym("EDN_REG_MAP_BASE_ADDR")
HMAC_BASE = HMAC.addr("INTR_STATE")
SECURE_DMA = RegBlock("SECURE_DMA")
DMA_BASE = SECURE_DMA.addr("INTR_STATE")

INTR_STATE = sym("CSRNG_INTR_STATE_REG_ADDR") - CSRNG_BASE
INTR_ENABLE = sym("CSRNG_INTR_ENABLE_REG_ADDR") - CSRNG_BASE
INTR_TEST = sym("CSRNG_INTR_TEST_REG_ADDR") - CSRNG_BASE

RESP_SLVERR = 2
RESP_DECERR = 3

# PIC source IDs from hw/sys/sep/doc/interrupts.adoc (1-based).
# sep_internal_interrupts[N] feeds PIC source N+1.
PIC_HMAC_DONE = pic("HMAC done")
PIC_HMAC_ERR = pic("HMAC error")
PIC_KMAC_DONE = pic("KMAC done")
PIC_DMA_DONE = pic("DMA transfer done")
PIC_DMA_CHUNK = pic("DMA chunk done")
PIC_DMA_ERROR = pic("DMA error")
PIC_CSRNG_CMD_REQ_DONE = pic("CSRNG command request done")
PIC_CSRNG_ENTROPY_REQ = pic("CSRNG entropy request")
PIC_CSRNG_HW_INST_EXC = pic("CSRNG HW instance exception")
PIC_CSRNG_FATAL_ERR = pic("CSRNG fatal error")
PIC_EDN_CMD_REQ_DONE = pic("EDN command request done")
PIC_EDN_FATAL_ERR = pic("EDN fatal error")
PIC_DMA_REG_PATH = pic("DMA register-path bus error")
PIC_DMA_HOST_PATH = pic("DMA host-path integrity/bus fault")
PIC_PERIPH_OR = pic("Peripheral register-bridge fault")


def agg_from_pic(pic_source: int) -> int:
    """Aggregator bit for a documented 1-based PIC source."""
    return pic_source - 1


IRQ_DMA_REG_PATH = agg_from_pic(PIC_DMA_REG_PATH)
IRQ_DMA_HOST_PATH = agg_from_pic(PIC_DMA_HOST_PATH)
IRQ_PERIPH_OR = agg_from_pic(PIC_PERIPH_OR)

DMA_STATUS_ADDR = SEP_CPU_CTRL.addr("DMA_BUS_ERR_STATUS")
DMA_CLEAR_ADDR = SEP_CPU_CTRL.addr("DMA_BUS_ERR_CLEAR")
PERIPH_STATUS_ADDR = SEP_CPU_CTRL.addr("PERIPH_BUS_ERR_STATUS")
PERIPH_CLEAR_ADDR = SEP_CPU_CTRL.addr("PERIPH_BUS_ERR_CLEAR")
DMA_REG_PATH_BIT = SEP_CPU_CTRL.field_mask("DMA_BUS_ERR_STATUS", "reg_path_err")
DMA_HOST_PATH_BIT = SEP_CPU_CTRL.field_mask("DMA_BUS_ERR_STATUS", "host_path_err")
DMA_CLR_BIT = SEP_CPU_CTRL.field_mask("DMA_BUS_ERR_CLEAR", "clr")
PERIPH_HMAC_BIT = SEP_CPU_CTRL.field_mask("PERIPH_BUS_ERR_STATUS", "hmac")
PERIPH_HMAC_CLR = SEP_CPU_CTRL.field_mask("PERIPH_BUS_ERR_CLEAR", "hmac")
PERIPH_KMAC_BIT = SEP_CPU_CTRL.field_mask("PERIPH_BUS_ERR_STATUS", "kmac")
PERIPH_KMAC_CLR = SEP_CPU_CTRL.field_mask("PERIPH_BUS_ERR_CLEAR", "kmac")
PERIPH_OTBN_BIT = SEP_CPU_CTRL.field_mask("PERIPH_BUS_ERR_STATUS", "otbn")
PERIPH_OTBN_CLR = SEP_CPU_CTRL.field_mask("PERIPH_BUS_ERR_CLEAR", "otbn")


def dma_reg_unmapped_addr() -> int:
    """First unused word inside the Secure DMA xbar window.

    The window is the register extent (not the 4 kB spec aperture). An access
    past that extent DECERRs in the xbar and never reaches ``err_o``. The gap
    between the last ``INTR_SRC_ADDR`` word and the first ``INTR_SRC_WR_VAL``
    word is still routed to the DMA TL-UL adapter, which returns SLVERR.
    """
    after_src = sym("SECURE_DMA_INTR_SRC_ADDR_0_10__REG_ADDR") + 4
    wr_val = sym("SECURE_DMA_INTR_SRC_WR_VAL_0_0__REG_ADDR")
    if after_src >= wr_val:
        raise RuntimeError(f"DMA INTR_SRC gap closed: 0x{after_src:08x} >= 0x{wr_val:08x}")
    return after_src


def hmac_reg_unmapped_addr() -> int:
    """First unused word between the HMAC CSRs and the message FIFO.

    HMAC's crypto-demux window is the 8 kB export size. The CSR block ends at
    ``MSG_LENGTH_UPPER``; the FIFO starts at ``HMAC_MSG_FIFO_MEM``. A word in
    between is still routed to the HMAC TL-UL adapter.
    """
    after_csr = HMAC.addr("MSG_LENGTH_UPPER") + 4
    fifo = sym("HMAC_MSG_FIFO_MEM_BASE_ADDR")
    if after_csr >= fifo:
        raise RuntimeError(f"HMAC CSR/FIFO gap closed: 0x{after_csr:08x} >= 0x{fifo:08x}")
    return after_csr


def kmac_reg_unmapped_addr() -> int:
    """First unused word between the KMAC CSRs and the STATE window.

    KMAC's demux rule is the 4 kB export. The CSR block ends at ``ERR_CODE``;
    STATE starts at ``KMAC_STATE_MEM``. A word in between is still routed to
    the KMAC TL-UL adapter.
    """
    after_csr = KMAC.addr("ERR_CODE") + 4
    state = sym("KMAC_STATE_MEM_BASE_ADDR")
    if after_csr >= state:
        raise RuntimeError(f"KMAC CSR/STATE gap closed: 0x{after_csr:08x} >= 0x{state:08x}")
    return after_csr


@dataclass(frozen=True)
class PeriphHole:
    """One in-window adapter hole and the STATUS/CLEAR bits it must raise."""

    name: str
    addr: int
    status_bit: int
    clear_bit: int


def hmac_misaligned_addr() -> int:
    """A misaligned offset inside a mapped HMAC register.

    ``CFG`` is a live 32-bit register, so byte offset +2 lies inside the HMAC
    extent but is not word-aligned.
    """
    return HMAC.addr("CFG") + 2


def periph_holes() -> tuple[PeriphHole, ...]:
    """HMAC / KMAC / OTBN holes that still reach an adapter ``err_o``."""
    return (
        PeriphHole("hmac", hmac_reg_unmapped_addr(), PERIPH_HMAC_BIT, PERIPH_HMAC_CLR),
        PeriphHole("kmac", kmac_reg_unmapped_addr(), PERIPH_KMAC_BIT, PERIPH_KMAC_CLR),
        PeriphHole("otbn", otbn_reg_unmapped_addr(), PERIPH_OTBN_BIT, PERIPH_OTBN_CLR),
    )


def otbn_reg_unmapped_addr() -> int:
    """First unused word between the OTBN CSRs and IMEM.

    OTBN's demux rule is the 48 kB export (CSR + IMEM + DMEM). The CSR block
    ends at ``LOAD_CHECKSUM``; IMEM starts at ``OTBN_IMEM_MEM``. A word in
    between is still routed to the OTBN TL-UL adapter.
    """
    after_csr = OTBN.addr("LOAD_CHECKSUM") + 4
    imem = sym("OTBN_IMEM_MEM_BASE_ADDR")
    if after_csr >= imem:
        raise RuntimeError(f"OTBN CSR/IMEM gap closed: 0x{after_csr:08x} >= 0x{imem:08x}")
    return after_csr


@dataclass(frozen=True)
class IrqSrc:
    """One interrupt source: its IP base, the bit in that IP's INTR_* registers,
    and the bit it drives in sep_internal_interrupts.

    kind is ``event`` (W1C INTR_STATE deasserts) or ``status`` (INTR_STATE is
    read-only; writing INTR_TEST=0 is the deassert path).
    """

    name: str
    base: int
    test_bit: int
    agg_idx: int
    kind: str = "event"


# CSRNG/EDN Event sources plus HMAC error (Event) and DMA done/chunk/error
# (Status). agg_idx is PIC source − 1 from interrupts.adoc. HMAC/KMAC
# fifo_empty Status bits are idle-true and are not in this table.
IRQ_TABLE = (
    IrqSrc(
        "csrng_cmd_req_done",
        CSRNG_BASE,
        CSRNG.fields("INTR_STATE")["CS_CMD_REQ_DONE"]["bp"],
        agg_from_pic(PIC_CSRNG_CMD_REQ_DONE),
    ),
    IrqSrc(
        "csrng_entropy_req",
        CSRNG_BASE,
        CSRNG.fields("INTR_STATE")["CS_ENTROPY_REQ"]["bp"],
        agg_from_pic(PIC_CSRNG_ENTROPY_REQ),
    ),
    IrqSrc(
        "csrng_hw_inst_exc",
        CSRNG_BASE,
        CSRNG.fields("INTR_STATE")["CS_HW_INST_EXC"]["bp"],
        agg_from_pic(PIC_CSRNG_HW_INST_EXC),
    ),
    IrqSrc(
        "csrng_fatal_err",
        CSRNG_BASE,
        CSRNG.fields("INTR_STATE")["CS_FATAL_ERR"]["bp"],
        agg_from_pic(PIC_CSRNG_FATAL_ERR),
    ),
    IrqSrc(
        "edn_cmd_req_done",
        EDN_BASE,
        EDN.fields("INTR_STATE")["EDN_CMD_REQ_DONE"]["bp"],
        agg_from_pic(PIC_EDN_CMD_REQ_DONE),
    ),
    IrqSrc(
        "edn_fatal_err",
        EDN_BASE,
        EDN.fields("INTR_STATE")["EDN_FATAL_ERR"]["bp"],
        agg_from_pic(PIC_EDN_FATAL_ERR),
    ),
    IrqSrc(
        "hmac_err",
        HMAC_BASE,
        HMAC.field_lsb("INTR_STATE", "hmac_err"),
        agg_from_pic(PIC_HMAC_ERR),
    ),
    IrqSrc(
        "dma_done",
        DMA_BASE,
        SECURE_DMA.field_lsb("INTR_STATE", "dma_done"),
        agg_from_pic(PIC_DMA_DONE),
        "status",
    ),
    IrqSrc(
        "dma_chunk_done",
        DMA_BASE,
        SECURE_DMA.field_lsb("INTR_STATE", "dma_chunk_done"),
        agg_from_pic(PIC_DMA_CHUNK),
        "status",
    ),
    IrqSrc(
        "dma_error",
        DMA_BASE,
        SECURE_DMA.field_lsb("INTR_STATE", "dma_error"),
        agg_from_pic(PIC_DMA_ERROR),
        "status",
    ),
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

    async def read32(self, addr: int) -> int:
        return await self._rd(addr)

    async def write32(self, addr: int, data: int) -> None:
        await self._wr(addr, data)

    async def write_expect_slverr(self, addr: int, data: int) -> None:
        """One full-width 32-bit write that must complete BRESP=SLVERR."""
        seq = SepAxiAccessSeq(
            f"{self._DRIVER_TAG.lower()}_wr_slverr",
            op=SepAxiOp.WRITE,
            addr=addr,
            wdata=data,
            size=self._AXI_SIZE,
            expect_error=True,
        )
        await self.test.start_seq(seq)
        if seq.resp_code != RESP_SLVERR:
            raise AssertionError(
                f"{self._DRIVER_TAG} write @0x{addr:08x} resp={seq.resp_code}, "
                f"expected SLVERR (2); DECERR means the xbar refused before the adapter"
            )

    async def read_expect_slverr(self, addr: int) -> int:
        """One 32-bit read that must complete SLVERR (through-adapter, not DECERR)."""
        seq = SepAxiAccessSeq(
            f"{self._DRIVER_TAG.lower()}_rd_slverr",
            op=SepAxiOp.READ,
            addr=addr,
            size=self._AXI_SIZE,
            expect_error=True,
        )
        await self.test.start_seq(seq)
        if seq.resp_code != RESP_SLVERR:
            raise AssertionError(
                f"{self._DRIVER_TAG} read @0x{addr:08x} resp={seq.resp_code}, "
                f"expected SLVERR (2); DECERR means the xbar refused before the adapter"
            )
        return seq.rdata
