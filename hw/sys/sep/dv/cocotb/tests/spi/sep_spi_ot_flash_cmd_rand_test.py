# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The OT SPI host drives the exact flash command sequence, and program, erase and read land.

A cpu-firmware port of OCAH `spi_ot_flash_write_read_test` and
`spi_ot_flash_sector_erase_test`, randomized ([RAND-REP]). Boots the VeeR EL2 core
and runs the spi_ot_flash_cmd firmware, which drives the OT SPI host
(@ 0x10B0_0000) against the OcahSpiFlash BFM:

    WREN -> PAGE PROGRAM -> READ + verify == pattern ->
    WREN -> SECTOR ERASE -> READ + verify == 0xFF, ERROR_STATUS == 0 throughout,
    then the write-protect / RDSR2 breadth and the ERROR_STATUS injections.

cpu-firmware mode (not no_cpu): every OCAH spi_ot flash test and
`sep_spi_ot_dma_rx_test` run the multi-command SPI flash sequence from firmware.
Distinct from `sep_spi_ot_dma_rx_test` (RX+DMA) and `sep_spi_flash_jedec_smoke_test`.

Randomization (this test is the single source of randomness):
  The scenario -- flash address (page-aligned), word count (1..16), and the data
  words -- is generated here from the runner seed (RANDOM_SEED) and patched into
  the staged DTCM image at the firmware's SPI1_PARAM_MAGIC sentinel. The same
  compiled firmware image therefore covers every seed; running multiple seeds
  exercises different addresses/lengths/sectors/data. Pass +spi1_directed to skip
  patching and run the firmware's committed directed defaults.

Checks:
  firmware self-check (each logs a positive PASS line):
    CHK-PROGRAM/CHK-READ : WREN+PP writes the words; READ returns them.
    CHK-ERASE            : sector ERASE -> READ returns all 0xFF.
    CHK-WEL-AUTOCLR      : the erase consumed the write-enable latch (WEL clear).
    CHK-WP-PP            : the controller completes the third PAGE PROGRAM, the
                           one issued with WEL clear. WEL is state of the flash
                           device model, not of SEP: the model refuses any PAGE
                           PROGRAM while WEL is clear, whatever the controller
                           drives, so the refusal (the sector still reads 0xFF) is
                           device-model behaviour and takes no SEP feature credit.
    CHK-RDSR2            : opcode 0x35 returns the seeded SR2 while SR1 reads
                           0x02, so a 0x35 folded onto 0x05 fails, and so does a
                           receive path that returns an all-zero byte.
    CHK-NO-ERROR         : OT SPI ERROR_STATUS == 0 across all of the above.
    CHK-ERR-UNDERFLOW    : reading RXDATA with RXQD==0 latches exactly
                           ERROR_STATUS.UNDERFLOW; SW_RST + W1C releases it.
    CHK-ERR-CMDINVAL     : a COMMAND with the reserved SPEED encoding latches
                           exactly ERROR_STATUS.CMDINVAL; recovery clears it.
    CHK-ERR-CSIDINVAL    : a segment with CSID at the top of the 32-bit field
                           latches exactly ERROR_STATUS.CSIDINVAL; recovery
                           clears it.
    CHK-ERR-RECOVER      : JEDEC works again afterwards, so the host was really
                           released rather than left disabled by a stuck latch.
  cocotb golden cross-check (independent of the firmware readback):
    - exactly the BFM-visible opcode sequence (JEDEC, WREN, RDSR, WRDI, RDSR,
      primary program/read, FAST_READ, neighbour program/read, erase, primary read,
      neighbour read, post-erase RDSR, the ignored WEL-clear PP and its read,
      WREN, RDSR2, WRDI, recovery JEDEC);
    - the PAGE PROGRAM (0x02) landed at the random addr with the random data;
    - the SECTOR ERASE wiped the page (BFM memory == 0xFF at addr afterwards)
      and left the neighbour 4 KiB sector intact;
    - CHK-WP-PP/BFM: the controller delivered the third PAGE PROGRAM to the
      device, with the full address phase at the random addr. This is the part
      of CHK-WP-PP that SEP can fail.
    - device-model self-check (no SEP feature credit): the model took no payload
      from the WEL-clear PAGE PROGRAM, and its stored array at addr is still 0xFF.

main() returns the error count; fw/startup/crt0.s emits PASS (0xCAFEBABE) / FAIL
(0xDEADBEEF) magic, which the boot scoreboard gates on (+ banner + ICCM exec).

Run mode: cpu with +skip_fuse_sense (no fuse data is read).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import cocotb
import pyuvm
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_dtcm_param_patch import patch_param_block
from env.sep_seeded_rng import SepSeededRng
from ocah_spi_vip import OcahSpiFlash
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "spi_ot_flash_cmd_test")
_ITCM_HEX = os.path.join(_FW_DIR, "spi_ot_flash_cmd_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "spi_ot_flash_cmd_test.dtcm.hex")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
_MAX_RUN_CYCLES = 3_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
_BANNER = "SEP SPI OT flash cmd test"

# Mirror of the firmware g_spi1_params block (spi_ot_flash_cmd_test.c).
_PARAM_MAGIC = 0x5A11C0DE
# Status register 2 the device model is built with. Non-zero and
# distinct from the 0x02 SR1 reads with the write-enable latch set, so a decode
# that folds 0x35 onto 0x05 and an all-zero receive path both fail CHK-RDSR2.
# Must equal FLASH_SR2_SEEDED in fw/tests/spi_ot_flash_cmd_test/spi_ot_flash_cmd_test.c.
_SR2_SEED = 0x5A
_MAX_WORDS = 16
_PAGE_SIZE = 256
_SECTOR_SIZE = 4096


@dataclass(frozen=True)
class SepSpiFlashCmdCfg:
    """Single source of truth for the SPI flash command-breadth scenario.

    The randomized page-program address + data, the firmware g_spi1_params block,
    and the golden BFM opcode order + PAGE PROGRAM expectations all derive from this
    one object (mirrors SepSpiDmaTxCfg). Page-aligned addr so the
    program stays inside one BFM page; a varied sector exercises erase across seeds.
    """

    seed: int
    addr: int
    data: list[int]

    # BFM opcode order the firmware must drive (bare class attr, not a field):
    # JEDEC, WREN, RDSR, WRDI, RDSR, then WREN/PP/READ (primary), FAST_READ,
    # WREN/PP/READ (neighbour), WREN/ERASE/READ (primary), READ (neighbour),
    # then the protect/status breadth -- RDSR (post-erase WIP+WEL), the PAGE
    # PROGRAM the device model ignores because WEL is clear, its READ, WREN,
    # RDSR2, WRDI -- and finally the JEDEC that proves the host recovered from
    # the three ERROR_STATUS injections. The injections themselves put nothing on
    # the bus: the host disables its core the cycle the error latches, and the
    # firmware flushes the offending segment with CTRL.SW_RST before clearing.
    EXPECTED_OPS = [
        0x9F,
        0x06,
        0x05,
        0x04,
        0x05,
        0x06,
        0x02,
        0x03,
        0x0B,
        0x06,
        0x02,
        0x03,
        0x06,
        0x20,
        0x03,
        0x03,
        0x05,
        0x02,
        0x03,
        0x06,
        0x35,
        0x04,
        0x9F,
    ]

    # Which PAGE PROGRAM in device order is the one issued with WEL clear: the
    # functional program is first, the neighbour second, this one third.
    WP_PP_NTH = 3

    @property
    def neigh_addr(self) -> int:
        """Adjacent 4 KiB sector; matches firmware ``addr ^ 0x1000``."""
        return self.addr ^ 0x1000

    def neigh_bytes(self) -> bytes:
        """PAGE PROGRAM payload the firmware writes to the neighbour sector."""
        return b"".join((w ^ 0xFFFFFFFF).to_bytes(4, "little") for w in self.data)

    @classmethod
    def from_seed(cls, seed: int) -> "SepSpiFlashCmdCfg":
        rng = SepSeededRng(seed)
        # Sector 0 is not drawn: the flash model records address 0 for a frame
        # that ends before its address phase completes, so a draw of address 0
        # cannot tell a truncated WEL-clear PAGE PROGRAM from a complete one.
        sector = rng.randrange(1, 32)
        page = rng.randrange(0, _SECTOR_SIZE // _PAGE_SIZE)
        addr = sector * _SECTOR_SIZE + page * _PAGE_SIZE
        nwords = rng.randrange(1, _MAX_WORDS + 1)
        data = [rng.getrandbits(32) for _ in range(nwords)]
        return cls(seed=seed, addr=addr, data=list(data))

    @property
    def nwords(self) -> int:
        return len(self.data)

    def param_words(self) -> list[int]:
        """Firmware g_spi1_params block: [magic, addr, nwords, *data]."""
        return [_PARAM_MAGIC, self.addr, self.nwords] + self.data

    def pp_bytes(self) -> bytes:
        """Expected PAGE PROGRAM payload (little-endian) the BFM must observe."""
        return b"".join(w.to_bytes(4, "little") for w in self.data)


@pyuvm.test()
class sep_spi_ot_flash_cmd_rand_test(sep_base_test):
    """The BFM sees exactly EXPECTED_OPS, and the program, erase and protect results match."""

    build_env = False

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    def _stage_dtcm(self) -> tuple:
        """Patch the scenario into a per-run DTCM image; return (path, cfg). With
        +spi1_directed, skip patching and use the firmware's defaults (cfg=None)."""
        if "spi1_directed" in cocotb.plusargs:
            self.logger.info(
                "SPI flash command breadth directed mode (+spi1_directed): firmware defaults"
            )
            return _DTCM_HEX, None

        cfg = SepSpiFlashCmdCfg.from_seed(self.random_seed())
        patched = os.path.join(os.getcwd(), "sep_dtcm_spi1.hex")
        patch_param_block(_DTCM_HEX, patched, _PARAM_MAGIC, cfg.param_words())
        self.logger.info(
            "SPI flash command breadth scenario (seed=%d): addr=0x%06x nwords=%d data=%s",
            cfg.seed,
            cfg.addr,
            cfg.nwords,
            [f"0x{w:08x}" for w in cfg.data],
        )
        return patched, cfg

    async def run_scenario(self) -> None:
        dut = cocotb.top
        logging.getLogger("sep_spi1_flash").setLevel(logging.DEBUG)
        flash = OcahSpiFlash(
            dut.spi_cs_n_o,
            dut.spi_sck_o,
            mosi=dut.spi_mosi_o,
            miso=dut.spi_miso_i,
            name="sep_spi1_flash",
            # Non-zero, and distinct from the 0x02 that SR1 reads
            # with WEL set. CHK-RDSR2 in the firmware compares against this exact
            # value (FLASH_SR2_SEEDED), so a stuck-low MISO returning 0x00 fails
            # the check instead of passing it.
            status_reg2=_SR2_SEED,
            verbose=True,
        )
        # BFM memory inits to 0xFF (erased); the firmware programs + verifies.
        await flash.start()
        dtcm_hex, cfg = self._stage_dtcm()
        try:
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
            self._golden_check(flash, cfg)
        finally:
            await flash.stop()

    def _golden_check(self, flash, cfg) -> None:
        """Independent BFM-side golden: confirm the random program/erase actually
        traversed the SPI datapath (not just the firmware's own readback). All
        expectations come from the single SepSpiFlashCmdCfg object."""
        txns = flash.get_transactions()
        for t in txns:
            din = t.get("data_in") or b""
            self.logger.info(
                "SPI flash command breadth diag txn: opcode=0x%02x addr=0x%06x data_in=%s",
                t.get("opcode", -1),
                t.get("addr", 0),
                bytes(din).hex() if din else "",
            )
        if cfg is None:  # +spi1_directed: firmware-self-checked only
            return

        opcodes = [t.get("opcode") for t in txns]
        if opcodes != cfg.EXPECTED_OPS:
            self.logger.error(
                "SPI flash command breadth GOLDEN FAIL: opcode order %s != %s",
                [f"0x{o:02x}" for o in opcodes],
                [f"0x{o:02x}" for o in cfg.EXPECTED_OPS],
            )
            raise AssertionError("SPI flash command breadth golden: unexpected BFM opcode sequence")

        pp = txns[6]
        exp_bytes = cfg.pp_bytes()
        if pp.get("addr") != cfg.addr or bytes(pp.get("data_in") or b"") != exp_bytes:
            self.logger.error(
                "SPI flash command breadth GOLDEN FAIL: PP addr=0x%06x data_in=%s vs exp addr=0x%06x data=%s",
                pp.get("addr", 0),
                bytes(pp.get("data_in") or b"").hex(),
                cfg.addr,
                exp_bytes.hex(),
            )
            raise AssertionError(
                "SPI flash command breadth golden: PAGE PROGRAM addr/data mismatch"
            )

        neigh_pp = txns[10]
        neigh_bytes = cfg.neigh_bytes()
        if (
            neigh_pp.get("addr") != cfg.neigh_addr
            or bytes(neigh_pp.get("data_in") or b"") != neigh_bytes
        ):
            self.logger.error(
                "SPI flash command breadth GOLDEN FAIL: neighbour PP addr=0x%06x data_in=%s vs exp addr=0x%06x data=%s",
                neigh_pp.get("addr", 0),
                bytes(neigh_pp.get("data_in") or b"").hex(),
                cfg.neigh_addr,
                neigh_bytes.hex(),
            )
            raise AssertionError(
                "SPI flash command breadth golden: neighbour PAGE PROGRAM mismatch"
            )

        # CHK-WP-PP, the part SEP can fail: the controller delivered the
        # WEL-clear PAGE PROGRAM to the device. Locate it by position among the
        # PAGE PROGRAMs rather than by a fixed index into every transaction: an
        # added or reordered command elsewhere in the walk would silently move a
        # raw index onto a different opcode. The model decodes the address phase
        # of a refused program, and records 0 only when the controller ends the
        # frame before the address is complete, so the address compare fails on
        # a truncated or corrupted command.
        pp_txns = [t for t in txns if t.get("opcode") == 0x02]
        if len(pp_txns) < cfg.WP_PP_NTH:
            raise AssertionError(
                f"SPI flash command breadth golden: expected at least "
                f"{cfg.WP_PP_NTH} PAGE PROGRAM transaction(s) at the device, "
                f"saw {len(pp_txns)}"
            )
        wp_pp = pp_txns[cfg.WP_PP_NTH - 1]
        if wp_pp.get("addr") != cfg.addr:
            self.logger.error(
                "SPI flash command breadth GOLDEN FAIL: WEL-clear PAGE PROGRAM "
                "addr=0x%06x at the device vs exp addr=0x%06x",
                wp_pp.get("addr", 0),
                cfg.addr,
            )
            raise AssertionError(
                "SPI flash command breadth golden: the controller did not deliver the "
                "WEL-clear PAGE PROGRAM address phase"
            )

        # Device-model self-check, no SEP feature credit. WEL is state of the
        # flash device model: while WEL is clear the model drops any PAGE
        # PROGRAM, whatever the controller drives, so neither check below can
        # fail on SEP RTL. They catch a change in the model.
        wp_taken = bytes(wp_pp.get("data_in") or b"")
        if wp_taken:
            self.logger.error(
                "SPI flash command breadth MODEL SELF-CHECK FAIL: the device model "
                "accepted the WEL-clear PAGE PROGRAM, took %d payload byte(s): %s",
                len(wp_taken),
                wp_taken.hex(),
            )
            raise AssertionError(
                "SPI flash command breadth model self-check: the device model took a "
                "PAGE PROGRAM payload with WEL clear"
            )

        # Read the device model's stored array directly, after the sector erase
        # and the WEL-clear PAGE PROGRAM that followed it. The erase half of this
        # compare is SEP behaviour (CHK-ERASE); the no-landing half is the model
        # self-check above.
        erased = flash.read_memory(cfg.addr, cfg.nwords * 4)
        if erased != b"\xff" * (cfg.nwords * 4):
            self.logger.error(
                "SPI flash command breadth GOLDEN FAIL: page not 0xFF after erase + "
                "WEL-clear PAGE PROGRAM: %s",
                erased.hex(),
            )
            raise AssertionError(
                "SPI flash command breadth golden: sector erase did not wipe the page, "
                "or the device model stored the WEL-clear PAGE PROGRAM"
            )
        neigh_left = flash.read_memory(cfg.neigh_addr, cfg.nwords * 4)
        if neigh_left != neigh_bytes:
            self.logger.error(
                "SPI flash command breadth GOLDEN FAIL: neighbour 0x%06x wiped or corrupted: %s vs %s",
                cfg.neigh_addr,
                neigh_left.hex(),
                neigh_bytes.hex(),
            )
            raise AssertionError(
                "SPI flash command breadth golden: sector erase wiped the neighbour"
            )
        self.logger.info(
            "CHK-WP-PP/BFM PASS: the controller delivered PAGE PROGRAM #%d (WEL clear) "
            "to the device at addr 0x%06x; device-model self-check: the model took no "
            "payload and its array is still erased (model behaviour, no SEP credit)",
            cfg.WP_PP_NTH,
            cfg.addr,
        )
        self.logger.info(
            "SPI flash command breadth GOLDEN PASS: PP@0x%06x %dB landed, erase wiped it, "
            "neighbour 0x%06x intact, opcodes=%s",
            cfg.addr,
            cfg.nwords * 4,
            cfg.neigh_addr,
            [f"0x{o:02x}" for o in cfg.EXPECTED_OPS],
        )
        self.logger.info(
            "CHK-RAND-REP PASS: walked BFM-visible opcodes "
            "JEDEC/WREN/RDSR/RDSR2/WRDI/PP/READ/FAST/ERASE (dual/quad not walked)"
        )
