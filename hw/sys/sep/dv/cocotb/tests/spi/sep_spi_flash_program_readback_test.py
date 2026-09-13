# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP OpenTitan SPI host flash program, erase, and readback test (PyUVM, no_cpu, randomized).

The CPU-LSU AXI master drives the OpenTitan SPI host through
``sep_spi_flash_ops_seq`` against the shared flash device: JEDEC ID, the
write-enable latch through WRITE ENABLE and WRITE DISABLE with READ STATUS
REGISTER 1 after each step, a PAGE PROGRAM without WRITE ENABLE that the
device must refuse, the protected PAGE PROGRAM of a seeded span with READ and
FAST READ readback, a second page in the neighbouring sector, a SECTOR ERASE
of the first sector, and the readback that shows the first page blank and the
neighbour intact. ``OcahSpiFlashChecker`` judges the device records against
its reference model, the host readback against what the device sent, the
device array against the model, the model against the seeded source image,
the exact opcode order, and non-vacuity, and two in-band probes prove the
checker rejects a wrong pattern and a wrong order.

Randomization: the runner seed picks the sector, the page, the span length
(4 to 64 bytes, a multiple of 4), and both payloads through ``SepSeededRng``.

Must-fail knob ``SEP_SPI_FLASH_CHECKER_NEGATIVE``: ``1`` hands the checker a
corrupted source image (``CHK-SPI-MEM-SOURCE`` fails); ``2`` skips the WRITE
ENABLE before the functional PAGE PROGRAM, so the device refuses it, the
readback stays blank (``CHK-SPI-PROGRAM-READBACK`` fails), and the erase that
follows flips no programmed byte (``CHK-SPI-NONVAC-ERASE`` fails).

no_cpu / +skip_fuse_sense (no fuse data is read).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import cocotb
import pyuvm
from env.sep_seeded_rng import SepSeededRng
from ocah_checker import OcahCheckerError
from ocah_lib import OcahKnobs
from ocah_spi_vip import PAGE_SIZE, SECTOR_SIZE, OcahSpiFlash, OcahSpiFlashChecker, OcahSpiOpcode
from sep_base_test import sep_base_test
from seq_lib.sep_spi_flash_jedec_seq import SPI_JEDEC_ID
from seq_lib.sep_spi_flash_ops_seq import SepSpiFlashOpsCfg, sep_spi_flash_ops_seq

NEGATIVE_KNOB = "SEP_SPI_FLASH_CHECKER_NEGATIVE"
NEGATIVE_PATTERN = 1
NEGATIVE_ORDER = 2
_STATUS_REG2 = 0x5A
_MAX_WORDS = 16
_SECTORS_IN_SWEEP = 32
_ERASED = 0xFF
_FLASH_SIZE = 16 * 1024 * 1024

REQUIRED_EVIDENCE = (
    "CHK-SPI-JEDEC-ID",
    "CHK-SPI-HOST-JEDEC",
    "CHK-SPI-STATUS-WEL",
    "CHK-SPI-HOST-STATUS",
    "CHK-SPI-WREN-ORDER",
    "CHK-SPI-READ-DATA",
    "CHK-SPI-HOST-READBACK",
    "CHK-SPI-CMD-ORDER",
    "CHK-SPI-MEM-GOLDEN",
    "CHK-SPI-MEM-SOURCE",
    "CHK-SPI-NONVAC-PROGRAM",
    "CHK-SPI-NONVAC-READ",
    "CHK-SPI-NONVAC-ERASE",
    "CHK-SPI-REFUSED-BLANK",
    "CHK-SPI-PROGRAM-READBACK",
    "CHK-SPI-FAST-READBACK",
    "CHK-SPI-ERASE-BLANK",
    "CHK-SPI-ERASE-NEIGHBOUR",
    "CHK-SPI-HOST-ERROR-STATUS",
    "CHK-SPI-NEG-PATTERN",
    "CHK-SPI-NEG-ORDER",
)


def _scenario(seed: int, *, skip_wren: bool) -> SepSpiFlashOpsCfg:
    """Seeded span inside one page plus the same span in the neighbouring sector."""
    rng = SepSeededRng(seed)
    sector = rng.randrange(0, _SECTORS_IN_SWEEP)
    page = rng.randrange(0, SECTOR_SIZE // PAGE_SIZE)
    nwords = rng.randrange(1, _MAX_WORDS + 1)
    offset = rng.randrange(0, (PAGE_SIZE - nwords * 4) // 4 + 1) * 4
    addr = sector * SECTOR_SIZE + page * PAGE_SIZE + offset
    data = bytearray(rng.getrandbits(8) for _ in range(nwords * 4))
    if all(value == _ERASED for value in data):
        data[0] = 0x00
    neighbour = bytes(value ^ 0xFF for value in data)
    return SepSpiFlashOpsCfg(
        addr=addr,
        data=bytes(data),
        neighbour_addr=addr ^ SECTOR_SIZE,
        neighbour_data=neighbour,
        skip_wren_before_program=skip_wren,
    )


def _corrupted(image: bytes) -> bytes:
    """``image`` with one bit of its first byte flipped."""
    return bytes([image[0] ^ 0x01]) + image[1:]


@pyuvm.test()
class sep_spi_flash_program_readback_test(sep_base_test):
    """Program, erase, and read back the flash device through the OpenTitan SPI host."""

    required_evidence = REQUIRED_EVIDENCE

    async def run_scenario(self) -> None:
        dut = cocotb.top
        negative = OcahKnobs.get_int(NEGATIVE_KNOB, 0)
        cfg = _scenario(self.random_seed(), skip_wren=negative == NEGATIVE_ORDER)
        self.logger.info(
            "SPI flash program/readback scenario (seed=%d): addr=0x%06x len=%d neighbour=0x%06x "
            "negative=%d",
            self.random_seed(),
            cfg.addr,
            cfg.length,
            cfg.neighbour_addr,
            negative,
        )
        flash = OcahSpiFlash(
            dut.spi_cs_n_o,
            dut.spi_sck_o,
            mosi=dut.spi_mosi_o,
            miso=dut.spi_miso_i,
            jedec_id=SPI_JEDEC_ID,
            flash_size=_FLASH_SIZE,
            status_reg2=_STATUS_REG2,
            name="sep_spi_flash",
        )
        checker = OcahSpiFlashChecker(
            name="sep_spi_flash_checker",
            flash=flash,
            required_ids=REQUIRED_EVIDENCE,
            logger=self.logger,
        )
        await flash.start()
        try:
            await self.bring_up_no_cpu()
            seq = sep_spi_flash_ops_seq("spi_flash_ops_seq", cfg=cfg)
            await self.start_seq(seq)
        finally:
            await flash.stop()
        self._judge(flash=flash, checker=checker, seq=seq, cfg=cfg, negative=negative)

    def _judge(
        self,
        *,
        flash: OcahSpiFlash,
        checker: OcahSpiFlashChecker,
        seq: sep_spi_flash_ops_seq,
        cfg: SepSpiFlashOpsCfg,
        negative: int,
    ) -> None:
        if negative == NEGATIVE_ORDER:
            self.logger.warning(
                "NEGATIVE VALIDATION: the functional PAGE PROGRAM ran without WRITE ENABLE; "
                "CHK-SPI-PROGRAM-READBACK must fail"
            )
        checker.replay()
        for opcode in (
            OcahSpiOpcode.JEDEC_ID,
            OcahSpiOpcode.READ_SR1,
            OcahSpiOpcode.READ,
            OcahSpiOpcode.FAST_READ,
        ):
            checker.check_host_responses(opcode, seq.responses(opcode))
        checker.check_command_order(cfg.command_order())
        checker.expect_equal(
            "CHK-SPI-REFUSED-BLANK",
            seq.blank_before,
            bytes([_ERASED] * cfg.length),
            context=f"page at 0x{cfg.addr:06x} after a PAGE PROGRAM without WRITE ENABLE",
        )
        checker.expect_equal(
            "CHK-SPI-PROGRAM-READBACK",
            seq.readback,
            cfg.data,
            context=f"READ of the programmed span at 0x{cfg.addr:06x}",
        )
        checker.expect_equal(
            "CHK-SPI-FAST-READBACK",
            seq.fast_readback,
            cfg.data,
            context=f"FAST_READ of the programmed span at 0x{cfg.addr:06x}",
        )
        checker.expect_equal(
            "CHK-SPI-ERASE-BLANK",
            seq.erased,
            bytes([_ERASED] * cfg.length),
            context=f"page at 0x{cfg.addr:06x} after SECTOR ERASE",
        )
        checker.expect_equal(
            "CHK-SPI-ERASE-NEIGHBOUR",
            seq.neighbour_after,
            cfg.neighbour_data,
            context=f"neighbour page at 0x{cfg.neighbour_addr:06x} after SECTOR ERASE",
        )
        checker.expect_equal(
            "CHK-SPI-HOST-ERROR-STATUS", seq.error_status, 0, context="OT SPI host ERROR_STATUS"
        )
        source = cfg.neighbour_data
        if negative == NEGATIVE_PATTERN:
            self.logger.warning(
                "NEGATIVE VALIDATION: the source image handed to the checker is corrupted; "
                "CHK-SPI-MEM-SOURCE must fail"
            )
            source = _corrupted(source)
        checker.check_memory(source=source, addr=cfg.neighbour_addr, context="neighbour intact")
        checker.check_nonvacuous(require_erase=True)
        self._probe_negatives(flash, checker, cfg)
        checker.finalize()

    def _probe_negatives(
        self, flash: OcahSpiFlash, checker: OcahSpiFlashChecker, cfg: SepSpiFlashOpsCfg
    ) -> None:
        """A wrong source image and a wrong opcode order must each be rejected by a probe checker."""
        records = flash.get_transactions()
        checker.expect_true(
            "CHK-SPI-NEG-PATTERN",
            self._rejects(
                flash,
                lambda probe: (
                    probe.replay(records),
                    probe.check_memory(
                        source=_corrupted(cfg.neighbour_data), addr=cfg.neighbour_addr
                    ),
                ),
            ),
            context="a wrong source image must be rejected",
        )
        expected = cfg.command_order()
        checker.expect_true(
            "CHK-SPI-NEG-ORDER",
            self._rejects(
                flash,
                lambda probe: (
                    probe.replay(records),
                    probe.check_command_order(expected[1:] + expected[:1]),
                ),
            ),
            context="a wrong expected opcode order must be rejected",
        )

    @staticmethod
    def _rejects(flash: OcahSpiFlash, action: Callable[[OcahSpiFlashChecker], object]) -> bool:
        """Run ``action`` on a fail-fast probe checker with a silent logger; True when it raised."""
        quiet = logging.getLogger("sep_spi_flash_probe")
        quiet.setLevel(logging.CRITICAL)
        probe = OcahSpiFlashChecker(name="sep_spi_flash_probe", flash=flash, logger=quiet)
        try:
            action(probe)
        except OcahCheckerError:
            return True
        return False
