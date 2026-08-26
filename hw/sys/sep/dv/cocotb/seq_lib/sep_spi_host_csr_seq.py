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

from sep_reg_meta import sym

from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq

# --- register offsets (SEP spi_controller @ 0x10B0_0000; NUM_CS=1) ----------
SPI_BASE = sym("SPI_CONTROLLER_REG_MAP_BASE_ADDR")
INTR_STATUS = SPI_BASE + 0x00   # W1C: ERROR, SPI_EVENT
INTR_ENABLE = SPI_BASE + 0x04   # RW
INTR_TEST = SPI_BASE + 0x08     # WO (write-1 sets INTR_STATUS)
CTRL = SPI_BASE + 0x10          # RW
STATUS = SPI_BASE + 0x14        # RO
CFG = SPI_BASE + 0x18           # RW (single CONFIGOPTS)
CSID = SPI_BASE + 0x1C          # RW
CMD = SPI_BASE + 0x20           # WO (write strobes a command)
RXDATA = SPI_BASE + 0x24        # RO (reading empty -> UNDERFLOW)
TXDATA = SPI_BASE + 0x28        # WO (pushes TX FIFO)
ERROR_ENABLE = SPI_BASE + 0x2C  # RW
ERROR_STATUS = SPI_BASE + 0x30  # W1C
EVENT_ENABLE = SPI_BASE + 0x34  # RW

# --- field masks (from the generated spi_controller_reg.h) ------------------
CTRL_RX_WM = 0x0000_00FF
CTRL_TX_WM = 0x0000_FF00
# NOTE: the CTRL/STATUS bit values below are FIELD MASKS, not addresses -- several
# coincidentally resemble SEP apertures (CTRL_OUTPUT_EN/ST_TXFULL == 0x2000_0000, the
# retired SPI-mux aperture; ST_TXEMPTY == 0x1000_0000, the SEP SRAM base). Do not
# "derive" them from the register map.
CTRL_OUTPUT_EN = 0x2000_0000
CTRL_SW_RST = 0x4000_0000
CTRL_SPIEN = 0x8000_0000

ST_TXQD = 0x0000_00FF
ST_RXQD = 0x0000_FF00
ST_CMDQD = 0x000F_0000
ST_RXWM = 0x0010_0000
ST_BYTEORDER = 0x0040_0000
ST_RXEMPTY = 0x0100_0000
ST_RXFULL = 0x0200_0000
ST_TXWM = 0x0400_0000
ST_TXEMPTY = 0x1000_0000
ST_TXFULL = 0x2000_0000
ST_ACTIVE = 0x4000_0000
ST_READY = 0x8000_0000

CFG_RW_MASK = 0xEFFF_FFFF        # CLKDIV|CSN*|FULLCYC|CPHA|CPOL (bit28 reserved)
# CTRL writable for the readback walk -- exclude SW_RST so the walk never holds
# the core in reset; SPIEN/enable is covered by its own directed facet.
CTRL_RW_MASK = CTRL_RX_WM | CTRL_TX_WM | CTRL_OUTPUT_EN | CTRL_SPIEN  # 0xA000_FFFF
INTR_RW_MASK = 0x0000_0011       # ERROR(0x1), SPI_EVENT(0x10)
ERR_EN_MASK = 0x0001_1111        # CMDBUSY/OVERFLOW/UNDERFLOW/CMDINVAL/CSIDINVAL
EVT_EN_MASK = 0x0011_1111        # RXFULL/TXEMPTY/RXWM/TXWM/READY/IDLE

# INTR / ERROR_STATUS bits
INTR_ERROR = 0x1
INTR_SPI_EVENT = 0x10
ERR_CMDBUSY = 0x0000_0001
ERR_OVERFLOW = 0x0000_0010
ERR_UNDERFLOW = 0x0000_0100
ERR_CMDINVAL = 0x0000_1000
ERR_CSIDINVAL = 0x0001_0000
ERR_ACCESSINVAL = 0x0010_0000
CMD_FIFO_DEPTH = 4

# spi_controller TX FIFO depth (spi_controller_data_fifos.sv TxDepth) -- writing
# beyond it with the core disabled drives ERROR_STATUS.OVERFLOW.
TX_FIFO_DEPTH = 72

# CMD fields
CMD_DIR_RX = 1 << 12
CMD_DIR_TX = 2 << 12
CMD_SPEED_RESERVED = 3 << 10     # SPEED=2'b11 -> CMDINVAL (test_speed/dir_inval)

# --- documented reset values (golden for CHK-RESET) -------------------------
RESET_VALUES = {
    "INTR_STATUS": (INTR_STATUS, 0x0000_0000),
    "INTR_ENABLE": (INTR_ENABLE, 0x0000_0000),
    "CTRL": (CTRL, 0x0000_007F),         # RX_WATERMARK reset 0x7F
    "CFG": (CFG, 0x0000_0000),
    "CSID": (CSID, 0x0000_0000),
    "ERROR_ENABLE": (ERROR_ENABLE, 0x0001_1111),
    "ERROR_STATUS": (ERROR_STATUS, 0x0000_0000),
    "EVENT_ENABLE": (EVENT_ENABLE, 0x0000_0000),
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
        return (f"seed={self.seed} tx_wm={self.tx_watermark} "
                f"tx_fill={self.tx_fill_words} rw[{regs}]")


class SepSpiHost:
    """Thin AXI read/write helpers for the OT SPI host CSRs (no_cpu splice)."""

    def __init__(self, test) -> None:
        self.test = test

    async def wr(self, addr: int, data: int, *, length: int = 4,
                 size: int | None = None,
                 allow_unverified_write_resp: bool = False) -> None:
        seq = SepAxiAccessSeq(f"spi_wr_0x{addr:08x}", op=SepAxiOp.WRITE,
                              addr=addr, wdata=data, length=length, size=size,
                              allow_unverified_write_resp=allow_unverified_write_resp)
        await self.test.start_seq(seq)
        if not seq.resp_ok and not allow_unverified_write_resp:
            raise AssertionError(f"SPI CSR write @0x{addr:08x} not OKAY")

    async def rd(self, addr: int) -> int:
        seq = SepAxiAccessSeq(f"spi_rd_0x{addr:08x}", op=SepAxiOp.READ,
                              addr=addr, length=4)
        await self.test.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(f"SPI CSR read @0x{addr:08x} not OKAY")
        return seq.rdata
