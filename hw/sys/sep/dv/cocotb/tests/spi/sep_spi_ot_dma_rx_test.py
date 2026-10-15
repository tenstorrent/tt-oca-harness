# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SPI flash data reaches SRAM through the RX FIFO and the Secure DMA at each lane width.

The spi_ot_dma_rx firmware arms the Secure DMA in hardware-handshake mode (SRC = SPI RXDATA
fixed, DST = SRAM incrementing) and issues a SPI flash read; each RX FIFO watermark crossing
raises ``lsio_trigger`` and the DMA drains a chunk to SRAM. One boot runs three reads, one
per lane width: x1 (0x03), x2 (0x3B or 0xBB) and x4 (0x6B or 0xEB). The seed draws the
order, the x2 and x4 opcodes, a distinct flash sector per read and the 64 data bytes of each
read. Byte 0 of each read is its index and byte 1 is byte 0 XOR 0xA5, so every pattern holds
two byte values and no two reads start alike; neither is 0xFF, the erased flash byte.

The leaf preloads each read range into the flash model and patches the reads into the
firmware's g_spi2_params block (``SPI2_PARAM_MAGIC``). The flash model sits on all four data
lanes (``mode="quad_io"``, ``dq_out`` = ``spi_sd_o``, ``dq_in`` = ``spi_sd_i``) and the
testlist passes ``+sep_spi_four_lane``.

Checks:
  CHK-DATAPATH (firmware): every DMA-written SRAM word of a read equals the staged word;
    one PASS line per read with its opcode, width and byte count. The leaf requires exactly
    one line per staged read, in order.
  CHK-RW1C (firmware): the DMA done status holds after the poll and clears on
    write-one-to-clear; the verdict line names it.
  CHK-SPI-SB-RX: per read, the seeded bytes equal the flash record's ``data_out`` and the
    monitor's wire decode at the read's lane width.

Run mode: cpu with +skip_fuse_sense.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import cocotb
import pyuvm
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_dtcm_param_patch import patch_param_block
from env.sep_seeded_rng import SepSeededRng
from env.sep_spi_lane_responder import spi_lane_fcov
from env.sep_spi_scoreboard import SepSpiScoreboard
from env.sep_spi_wire_monitor import SepSpiWireMonitor
from ocah_spi_vip import OcahSpiFlash
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "spi_ot_dma_rx_test")
_ITCM_HEX = os.path.join(_FW_DIR, "spi_ot_dma_rx_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "spi_ot_dma_rx_test.dtcm.hex")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
_MAX_RUN_CYCLES = 3_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
_VERDICT_PREFIX = "PASS: SPI RX FIFO -> DMA -> SRAM"
_BANNER = "SEP SPI OT DMA RX test"
_TEST = "sep_spi_ot_dma_rx_test"

# Mirrors of the firmware (spi_ot_dma_rx_test.c): RX_SIZE bytes per read, the
# g_spi2_params magic.
_RX_SIZE = 64
_PARAM_MAGIC = 0x5A11D0A5
_SECTOR_SIZE = 4096
_PAGE_SIZE = 256
_FLASH_SECTORS = 4096  # 16 MiB flash model
# Read opcodes per lane width (fw/drivers/sep_spi.h SEP_SPI_OP_*).
_READ_OPCODES = {1: (0x03,), 2: (0x3B, 0xBB), 4: (0x6B, 0xEB)}
_FW_LINE = re.compile(
    r"CHK-DATAPATH PASS: op=0x([0-9a-f]{8}) width=x(\d) words=0x([0-9a-f]{8}) "
    r"bytes=0x([0-9a-f]{8})"
)

# Scratch-mutation hooks (None/False in the committed leaf). MUT_PATTERN_SEED
# stages expected patterns drawn from another seed while the flash keeps this
# seed's patterns. MUT_FLIP_X4 flips one flash byte of the x4 read range before
# the firmware starts.
MUT_PATTERN_SEED: int | None = None
MUT_FLIP_X4 = False


@dataclass(frozen=True)
class SepSpiDmaRxRead:
    """One staged read: opcode, lane width, flash address and its 64 bytes."""

    idx: int
    opcode: int
    lanes: int
    addr: int
    data: bytes

    def words(self) -> list[int]:
        """The bytes as RXDATA words, the first byte received in bits 7:0 (ByteOrder 1)."""
        return [int.from_bytes(self.data[i : i + 4], "little") for i in range(0, _RX_SIZE, 4)]


def _pattern(rng: SepSeededRng, idx: int) -> bytes:
    """64 seeded bytes; byte 0 is ``idx`` and byte 1 is ``idx ^ 0xA5`` (two values)."""
    data = bytearray(rng.getrandbits(8) for _ in range(_RX_SIZE))
    data[0] = idx
    data[1] = idx ^ 0xA5
    return bytes(data)


@dataclass(frozen=True)
class SepSpiDmaRxCfg:
    """The seeded reads of one run, in firmware order."""

    seed: int
    reads: tuple[SepSpiDmaRxRead, ...]

    @classmethod
    def from_seed(cls, seed: int, pattern_seed: int | None = None) -> "SepSpiDmaRxCfg":
        rng = SepSeededRng(seed)
        widths = [1, 2, 4]
        rng.shuffle(widths)
        sectors = rng.sample(range(_FLASH_SECTORS), len(widths))
        reads = []
        for idx, (lanes, sector) in enumerate(zip(widths, sectors)):
            opcode = rng.choice(_READ_OPCODES[lanes])
            page = rng.randrange(0, _SECTOR_SIZE // _PAGE_SIZE)
            data = _pattern(rng, idx)
            reads.append(
                SepSpiDmaRxRead(idx, opcode, lanes, sector * _SECTOR_SIZE + page * _PAGE_SIZE, data)
            )
        if pattern_seed is not None:
            other = SepSeededRng(pattern_seed)
            reads = [
                SepSpiDmaRxRead(r.idx, r.opcode, r.lanes, r.addr, _pattern(other, r.idx))
                for r in reads
            ]
        return cls(seed=seed, reads=tuple(reads))

    def param_words(self) -> list[int]:
        words = [_PARAM_MAGIC, len(self.reads)]
        for read in self.reads:
            words += [read.opcode, read.addr] + read.words()
        return words


@pyuvm.test()
class sep_spi_ot_dma_rx_test(sep_base_test):
    """Each read's SRAM words, flash record and wire bytes equal its seeded pattern."""

    build_env = False
    required_evidence = ("CHK-DATAPATH", "CHK-RW1C", "CHK-SPI-SB-RX")

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    def _stage_dtcm(self, cfg: SepSpiDmaRxCfg) -> str:
        patched = os.path.join(os.getcwd(), "sep_dtcm_spi2.hex")
        patch_param_block(_DTCM_HEX, patched, _PARAM_MAGIC, cfg.param_words())
        for read in cfg.reads:
            self.logger.info(
                "SPI DMA-RX read[%d] seed=%d op=0x%02x width=x%d addr=0x%06x bytes=%d data=%s",
                read.idx,
                cfg.seed,
                read.opcode,
                read.lanes,
                read.addr,
                len(read.data),
                read.data.hex(),
            )
        return patched

    async def run_scenario(self) -> None:
        dut = cocotb.top
        if "sep_spi_four_lane" not in cocotb.plusargs:
            raise AssertionError(
                "sep_spi_ot_dma_rx_test needs +sep_spi_four_lane: the flash model answers "
                "on spi_sd_i, which the host reads only with that plusarg"
            )
        seed = self.random_seed()
        cfg = SepSpiDmaRxCfg.from_seed(seed)
        staged = (
            cfg if MUT_PATTERN_SEED is None else SepSpiDmaRxCfg.from_seed(seed, MUT_PATTERN_SEED)
        )
        flash = OcahSpiFlash(
            dut.spi_cs_n_o,
            dut.spi_sck_o,
            dq_out=dut.spi_sd_o,
            dq_in=dut.spi_sd_i,
            mode="quad_io",
            name="sep_spi_rx_flash",
        )
        for read in cfg.reads:
            flash.write_memory(read.addr, read.data)
            if MUT_FLIP_X4 and read.lanes == 4:
                flash.write_memory(read.addr, bytes([read.data[0] ^ 0x01]))
                self.logger.info("MUTATION flipped flash byte 0x%06x of the x4 read", read.addr)
        dtcm_hex = self._stage_dtcm(staged)
        wire = await SepSpiWireMonitor(dut).start()
        sb = SepSpiScoreboard(wire, flash, self.logger, seed=seed)
        await flash.start()
        try:
            # Override the boot scoreboard's expected banner here (after its own
            # build_phase, which resets it to the hello_world default).
            self.sb.expected_line = _BANNER
            await self.boot_firmware(
                self.sb,
                _ITCM_HEX,
                dtcm_hex,
                rst_vec=_ICCM_BASE >> 1,
                max_run_cycles=_MAX_RUN_CYCLES,
                no_boot_cycles=_NO_BOOT_CYCLES,
                progress_every=_PROGRESS_EVERY,
            )
            self._firmware_check(staged)
            for read in staged.reads:
                sb.expect_rx(
                    read.opcode,
                    read.data,
                    source="fw:CHK-DATAPATH",
                    label=f"read[{read.idx}] width=x{read.lanes}",
                )
        finally:
            await flash.stop()
        await wire.finish(self.logger, seed=seed, flash=flash)
        sb.finish()
        # FCOV records only after every check above passed.
        for read in staged.reads:
            await spi_lane_fcov(_TEST, "data", lanes=read.lanes, rx=True)

    def _firmware_check(self, cfg: SepSpiDmaRxCfg) -> None:
        """The verdict line and one CHK-DATAPATH PASS line per staged read, in order."""
        console = self.sb.console_text()
        verdict = next(
            (ln for ln in console.splitlines() if ln.startswith(_VERDICT_PREFIX)),
            "",
        )
        assert verdict, (
            f"firmware console has no {_VERDICT_PREFIX!r} verdict line, so the "
            f"SRAM words and the write-one-to-clear were not both checked. "
            f"Console was:\n{console}"
        )
        # One line, two contracts: each record names the token that carries it,
        # so dropping either half of the firmware check fails here.
        for token, what in (
            ("(seeded pattern at each staged width)", "the seeded words in the DMA-written SRAM"),
            (
                "RW1C verified",
                "the DMA done status holding after the poll and clearing on write-one-to-clear",
            ),
        ):
            assert token in verdict, (
                f"firmware verdict line has no {token!r}, so {what} was not "
                f"checked. Line was: {verdict!r}"
            )
        seen = [
            (int(op, 16), int(width), int(words, 16), int(nbytes, 16))
            for op, width, words, nbytes in _FW_LINE.findall(console)
        ]
        want = [(r.opcode, r.lanes, _RX_SIZE // 4, _RX_SIZE) for r in cfg.reads]
        if seen != want:
            raise AssertionError(
                f"CHK-DATAPATH FAIL seed={cfg.seed}: firmware PASS lines {seen} != staged "
                f"reads {want}. Console was:\n{console}"
            )
        for read in cfg.reads:
            self.logger.info(
                "CHK-DATAPATH PASS seed=%d read[%d] op=0x%02x width=x%d bytes=%d "
                "(firmware SRAM word compare)",
                cfg.seed,
                read.idx,
                read.opcode,
                read.lanes,
                _RX_SIZE,
            )
        self.logger.info(
            "CHK-RW1C PASS: firmware reported the DMA done status holding after the poll "
            "and clearing on write-one-to-clear"
        )
