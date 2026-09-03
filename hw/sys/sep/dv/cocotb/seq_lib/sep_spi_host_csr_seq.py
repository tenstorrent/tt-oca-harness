# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OpenTitan SPI-host control-plane CSR map + config/driver for SPI host CSR/IRQ breadth
(``sep_spi_ot_host_csr_irq_rand_test``).

`[RAND-REP]` rep: ``SepSpiHostCfg`` is the single source of truth for the
randomized-but-legal register values walked by the test; the golden is the
documented reset values + RW/W1C/RO field semantics (this file), taken from the
SEP-integrated ``spi_controller`` reg block (NUM_CS=1, native AXI4-Lite @
0x10B0_0000 -- NOT the raw OpenTitan TL-UL map; the offsets/field bits below are
the modified module's, which is why CSID/CMD/ERROR_* sit one slot lower than the
upstream OT spi_host and the field bits are byte-spread). Driven over the CPU-LSU
AXI splice (no_cpu), so no firmware. Pure control plane -- no flash BFM.
"""

from __future__ import annotations

from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from sep_reg_meta import SPI_CONTROLLER, sym

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq

SPI_BASE = sym("SPI_CONTROLLER_REG_MAP_BASE_ADDR")
INTR_STATUS = SPI_CONTROLLER.addr("INTR_STATUS")
INTR_ENABLE = SPI_CONTROLLER.addr("INTR_ENABLE")
INTR_TEST = SPI_CONTROLLER.addr("INTR_TEST")
CTRL = SPI_CONTROLLER.addr("CTRL")
STATUS = SPI_CONTROLLER.addr("STATUS")
CFG = SPI_CONTROLLER.addr("CFG")
CSID = SPI_CONTROLLER.addr("CSID")
CMD = SPI_CONTROLLER.addr("CMD")
RXDATA = SPI_CONTROLLER.addr("RXDATA")
TXDATA = SPI_CONTROLLER.addr("TXDATA")
ERROR_ENABLE = SPI_CONTROLLER.addr("ERROR_ENABLE")
ERROR_STATUS = SPI_CONTROLLER.addr("ERROR_STATUS")
EVENT_ENABLE = SPI_CONTROLLER.addr("EVENT_ENABLE")

CTRL_RX_WM = SPI_CONTROLLER.field_mask("CTRL", "rx_watermark")
CTRL_TX_WM = SPI_CONTROLLER.field_mask("CTRL", "tx_watermark")
CTRL_OUTPUT_EN = SPI_CONTROLLER.field_mask("CTRL", "output_en")
CTRL_SW_RST = SPI_CONTROLLER.field_mask("CTRL", "sw_rst")
CTRL_SPIEN = SPI_CONTROLLER.field_mask("CTRL", "spien")

ST_TXQD = SPI_CONTROLLER.field_mask("STATUS", "txqd")
ST_RXQD = SPI_CONTROLLER.field_mask("STATUS", "rxqd")
ST_CMDQD = SPI_CONTROLLER.field_mask("STATUS", "cmdqd")
ST_RXWM = SPI_CONTROLLER.field_mask("STATUS", "rxwm")
ST_BYTEORDER = SPI_CONTROLLER.field_mask("STATUS", "byteorder")
ST_RXEMPTY = SPI_CONTROLLER.field_mask("STATUS", "rxempty")
ST_RXFULL = SPI_CONTROLLER.field_mask("STATUS", "rxfull")
ST_TXWM = SPI_CONTROLLER.field_mask("STATUS", "txwm")
ST_TXEMPTY = SPI_CONTROLLER.field_mask("STATUS", "txempty")
ST_TXFULL = SPI_CONTROLLER.field_mask("STATUS", "txfull")
ST_ACTIVE = SPI_CONTROLLER.field_mask("STATUS", "active")
ST_READY = SPI_CONTROLLER.field_mask("STATUS", "ready")

CFG_RW_MASK = SPI_CONTROLLER.mask32("CFG")
# CTRL writable for the readback walk -- exclude SW_RST so the walk never holds
# the core in reset; SPIEN/enable is covered by its own directed facet.
CTRL_RW_MASK = CTRL_RX_WM | CTRL_TX_WM | CTRL_OUTPUT_EN | CTRL_SPIEN
INTR_RW_MASK = SPI_CONTROLLER.mask32("INTR_ENABLE")
ERR_EN_MASK = SPI_CONTROLLER.mask32("ERROR_ENABLE")
EVT_EN_MASK = SPI_CONTROLLER.mask32("EVENT_ENABLE")

INTR_ERROR = SPI_CONTROLLER.field_mask("INTR_STATUS", "error")
INTR_SPI_EVENT = SPI_CONTROLLER.field_mask("INTR_STATUS", "spi_event")
ERR_CMDBUSY = SPI_CONTROLLER.field_mask("ERROR_STATUS", "cmdbusy")
ERR_OVERFLOW = SPI_CONTROLLER.field_mask("ERROR_STATUS", "overflow")
ERR_UNDERFLOW = SPI_CONTROLLER.field_mask("ERROR_STATUS", "underflow")
ERR_CMDINVAL = SPI_CONTROLLER.field_mask("ERROR_STATUS", "cmdinval")
ERR_CSIDINVAL = SPI_CONTROLLER.field_mask("ERROR_STATUS", "csidinval")
ERR_ACCESSINVAL = SPI_CONTROLLER.field_mask("ERROR_STATUS", "accessinval")
CMD_FIFO_DEPTH = 4

# spi_controller TX FIFO depth (spi_controller_data_fifos.sv TxDepth) -- writing
# beyond it with the core disabled drives ERROR_STATUS.OVERFLOW.
TX_FIFO_DEPTH = 72

# CMD fields
CMD_DIR_RX = 1 << 12
CMD_DIR_TX = 2 << 12
CMD_SPEED_RESERVED = 3 << 10  # SPEED=2'b11 -> CMDINVAL (test_speed/dir_inval)

# --- documented reset values (golden for CHK-RESET) -------------------------
RESET_VALUES = {
    "INTR_STATUS": (INTR_STATUS, SPI_CONTROLLER.reset32("INTR_STATUS")),
    "INTR_ENABLE": (INTR_ENABLE, SPI_CONTROLLER.reset32("INTR_ENABLE")),
    "CTRL": (CTRL, SPI_CONTROLLER.reset32("CTRL")),
    "CFG": (CFG, SPI_CONTROLLER.reset32("CFG")),
    "CSID": (CSID, SPI_CONTROLLER.reset32("CSID")),
    "ERROR_ENABLE": (ERROR_ENABLE, SPI_CONTROLLER.reset32("ERROR_ENABLE")),
    "ERROR_STATUS": (ERROR_STATUS, SPI_CONTROLLER.reset32("ERROR_STATUS")),
    "EVENT_ENABLE": (EVENT_ENABLE, SPI_CONTROLLER.reset32("EVENT_ENABLE")),
}


class SepSpiHostCfg:
    """Seed-randomized but legal control-plane values + facet knobs."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        # RW readback walk: (name, addr, writable_mask, random_value).
        self.rw_regs = [
            ("CTRL", CTRL, CTRL_RW_MASK, rng.getrandbits(32) & CTRL_RW_MASK),
            ("CFG", CFG, CFG_RW_MASK, rng.getrandbits(32) & CFG_RW_MASK),
            ("CSID", CSID, 0xFFFF_FFFF, rng.getrandbits(32)),
            ("INTR_ENABLE", INTR_ENABLE, INTR_RW_MASK, rng.getrandbits(8) & INTR_RW_MASK),
            ("ERROR_ENABLE", ERROR_ENABLE, ERR_EN_MASK, rng.getrandbits(32) & ERR_EN_MASK),
            ("EVENT_ENABLE", EVENT_ENABLE, EVT_EN_MASK, rng.getrandbits(32) & EVT_EN_MASK),
        ]
        rng.shuffle(self.rw_regs)
        # Watermark facet: a TX_WATERMARK threshold in a range a small fill can cross.
        self.tx_watermark = rng.randrange(2, 9)
        self.tx_fill_words = self.tx_watermark + rng.randrange(2, 5)
        # CHK-NONVAC pattern (nonzero) written to CFG.
        self.nonvac_cfg = (rng.getrandbits(32) & CFG_RW_MASK) | 0x1

    def summary(self) -> str:
        regs = " ".join(f"{n}=0x{v:08x}" for n, _, _, v in self.rw_regs)
        return f"seed={self.seed} tx_wm={self.tx_watermark} tx_fill={self.tx_fill_words} rw[{regs}]"


class SepSpiHost:
    """Thin AXI read/write helpers for the OT SPI host CSRs (no_cpu splice)."""

    def __init__(self, test) -> None:
        self.test = test

    async def wr(
        self,
        addr: int,
        data: int,
        *,
        length: int = 4,
        size: int | None = None,
        allow_unverified_write_resp: bool = False,
    ) -> None:
        seq = SepAxiAccessSeq(
            f"spi_wr_0x{addr:08x}",
            op=SepAxiOp.WRITE,
            addr=addr,
            wdata=data,
            length=length,
            size=size,
            allow_unverified_write_resp=allow_unverified_write_resp,
        )
        await self.test.start_seq(seq)
        if not seq.resp_ok and not allow_unverified_write_resp:
            raise AssertionError(f"SPI CSR write @0x{addr:08x} not OKAY")

    async def rd(self, addr: int) -> int:
        seq = SepAxiAccessSeq(f"spi_rd_0x{addr:08x}", op=SepAxiOp.READ, addr=addr, length=4)
        await self.test.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(f"SPI CSR read @0x{addr:08x} not OKAY")
        return seq.rdata
