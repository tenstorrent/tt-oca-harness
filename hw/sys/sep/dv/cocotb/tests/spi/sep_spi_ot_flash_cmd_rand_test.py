# SPDX-License-Identifier: Apache-2.0
"""SEP OpenTitan-SPI flash command-breadth test (PyUVM, cpu-firmware, randomized).

SPI-subsystem Phase-2 rep SPI flash command breadth (lead of the dedicated OpenTitan-SPI sweep). A
cpu-firmware port of the reference spi_ot_flash_write_read_test +
spi_ot_flash_sector_erase_test, upgraded to a randomized representative
([RAND-REP], stronger than the directed reference suite source). Boots the VeeR EL2 core
and runs the spi_ot_flash_cmd firmware, which drives the OT SPI host (@
0x10B0_0000) against the OcahSpiFlash BFM:

    WREN -> PAGE PROGRAM -> READ + verify == pattern ->
    WREN -> SECTOR ERASE -> READ + verify == 0xFF, ERROR_STATUS == 0 throughout.

cpu-firmware mode (not no_cpu): every reference spi_ot flash test + the Phase-1
sep_spi_ot_dma_rx run the multi-command SPI flash sequence from firmware.
Distinct from `sep_spi_ot_dma_rx_test` (RX+DMA) and the JEDEC smoke.

Randomization (this test is the SINGLE source of randomness; AGENTS.md s9/s11):
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
    CHK-NO-ERROR         : OT SPI ERROR_STATUS == 0 throughout.
  cocotb golden cross-check (independent of the firmware readback):
    - exactly 10 BFM transactions in the expected opcode order (primary
      program/read, neighbour program/read, erase, primary read, neighbour
      read);
    - the PAGE PROGRAM (0x02) landed at the random addr with the random data;
    - the SECTOR ERASE wiped the page (BFM memory == 0xFF at addr afterwards)
      and left the neighbour 4 KiB sector intact.

main() returns the error count; start.S emits PASS (0xCAFEBABE) / FAIL
(0xDEADBEEF) magic, which the boot scoreboard gates on (+ banner + ICCM exec).

cpu / +skip_fuse_sense (no fuse data is read).
"""

from __future__ import annotations

import logging
import os
import random
from dataclasses import dataclass
from pathlib import Path

import cocotb
import pyuvm

from sep_base_test import sep_base_test
from env.sep_boot_scoreboard import SepBootScoreboard
from ocah_spi_vip import OcahSpiFlash

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "spi_ot_flash_cmd_test")
_ITCM_HEX = os.path.join(_FW_DIR, "spi_ot_flash_cmd_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "spi_ot_flash_cmd_test.dtcm.hex")

_ICCM_BASE = 0xC000_0000
_MAX_RUN_CYCLES = 3_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
_BANNER = "SEP SPI OT flash cmd test"

# Mirror of the firmware g_spi1_params block (spi_ot_flash_cmd_test.c).
_PARAM_MAGIC = 0x5A11C0DE
_MAX_WORDS = 16
_PAGE_SIZE = 256
_SECTOR_SIZE = 4096


def _parse_hex_cells(path: str) -> dict:
    """Parse a Verilog $readmemh-style byte image into {byte_addr: value}."""
    cells: dict = {}
    addr = 0
    with open(path) as fh:
        for line in fh:
            tok = line.strip()
            if not tok:
                continue
            if tok.startswith("@"):
                addr = int(tok[1:], 16)
                continue
            for byte in tok.split():
                cells[addr] = int(byte, 16)
                addr += 1
    return cells


def _find_magic(cells: dict, magic_le: bytes) -> int:
    """Return the byte address where the little-endian magic bytes start."""
    for base in sorted(cells):
        if all(cells.get(base + i) == magic_le[i] for i in range(len(magic_le))):
            return base
    raise RuntimeError("SPI1_PARAM_MAGIC not found in DTCM image")


def _patch_hex(src: str, dst: str, patches: dict) -> None:
    """Rewrite ``src`` to ``dst`` replacing bytes at the addresses in ``patches``,
    preserving the original @addr / 16-byte-per-line layout exactly."""
    out = []
    addr = 0
    with open(src) as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            tok = line.strip()
            if tok.startswith("@"):
                addr = int(tok[1:], 16)
                out.append(line)
                continue
            if not tok:
                out.append(line)
                continue
            new_toks = []
            for byte in tok.split():
                new_toks.append(f"{patches[addr]:02X}" if addr in patches else byte)
                addr += 1
            out.append(" ".join(new_toks))
    with open(dst, "w") as fh:
        fh.write("\n".join(out) + "\n")


@dataclass(frozen=True)
class SepSpiFlashCmdCfg:
    """Single source of truth for the SPI flash command-breadth scenario.

    The randomized page-program address + data, the firmware g_spi1_params block,
    and the golden BFM opcode order + PAGE PROGRAM expectations all derive from this
    one object (AGENTS.md s9/s11; mirrors SepSpiDmaTxCfg). Page-aligned addr so the
    program stays inside one BFM page; a varied sector exercises erase across seeds.
    """

    seed: int
    addr: int
    data: list[int]

    # BFM opcode order the firmware must drive (bare class attr, not a field):
    # WREN, PP, READ (primary); WREN, PP, READ (neighbour 4 KiB);
    # WREN, SECTOR ERASE, READ (primary); READ (neighbour after erase).
    EXPECTED_OPS = [0x06, 0x02, 0x03, 0x06, 0x02, 0x03, 0x06, 0x20, 0x03, 0x03]

    @property
    def neigh_addr(self) -> int:
        """Adjacent 4 KiB sector; matches firmware ``addr ^ 0x1000``."""
        return self.addr ^ 0x1000

    def neigh_bytes(self) -> bytes:
        """PAGE PROGRAM payload the firmware writes to the neighbour sector."""
        return b"".join((w ^ 0xFFFFFFFF).to_bytes(4, "little") for w in self.data)

    @classmethod
    def from_seed(cls, seed: int) -> "SepSpiFlashCmdCfg":
        rng = random.Random(seed)
        sector = rng.randint(0, 31)
        page = rng.randint(0, _SECTOR_SIZE // _PAGE_SIZE - 1)
        addr = sector * _SECTOR_SIZE + page * _PAGE_SIZE
        nwords = rng.randint(1, _MAX_WORDS)
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
    """Boot VeeR EL2 and run the randomized OT SPI flash command-breadth firmware."""

    build_env = False

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    def _stage_dtcm(self) -> tuple:
        """Patch the scenario into a per-run DTCM image; return (path, cfg). With
        +spi1_directed, skip patching and use the firmware's defaults (cfg=None)."""
        if "spi1_directed" in cocotb.plusargs:
            self.logger.info("SPI flash command breadth directed mode (+spi1_directed): firmware defaults")
            return _DTCM_HEX, None

        cfg = SepSpiFlashCmdCfg.from_seed(self.random_seed())
        cells = _parse_hex_cells(_DTCM_HEX)
        base = _find_magic(cells, _PARAM_MAGIC.to_bytes(4, "little"))
        patches = {}
        for k, word in enumerate(cfg.param_words()):
            for b in range(4):
                patches[base + 4 * k + b] = (word >> (8 * b)) & 0xFF
        patched = os.path.join(os.getcwd(), "sep_dtcm_spi1.hex")
        _patch_hex(_DTCM_HEX, patched, patches)
        self.logger.info(
            "SPI flash command breadth scenario (seed=%d): addr=0x%06x nwords=%d data=%s",
            cfg.seed, cfg.addr, cfg.nwords, [f"0x{w:08x}" for w in cfg.data],
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
            verbose=True,
        )
        # BFM memory inits to 0xFF (erased); the firmware programs + verifies.
        await flash.start()
        dtcm_hex, cfg = self._stage_dtcm()
        try:
            self.sb.expected_line = _BANNER
            await self.boot_firmware(
                self.sb, _ITCM_HEX, dtcm_hex,
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
            self.logger.info("SPI flash command breadth diag txn: opcode=0x%02x addr=0x%06x data_in=%s",
                             t.get("opcode", -1), t.get("addr", 0),
                             bytes(din).hex() if din else "")
        if cfg is None:  # +spi1_directed: firmware-self-checked only
            return

        opcodes = [t.get("opcode") for t in txns]
        if opcodes != cfg.EXPECTED_OPS:
            self.logger.error("SPI flash command breadth GOLDEN FAIL: opcode order %s != %s",
                              [f"0x{o:02x}" for o in opcodes],
                              [f"0x{o:02x}" for o in cfg.EXPECTED_OPS])
            raise AssertionError("SPI flash command breadth golden: unexpected BFM opcode sequence")

        pp = txns[1]
        exp_bytes = cfg.pp_bytes()
        if pp.get("addr") != cfg.addr or bytes(pp.get("data_in") or b"") != exp_bytes:
            self.logger.error(
                "SPI flash command breadth GOLDEN FAIL: PP addr=0x%06x data_in=%s vs exp addr=0x%06x data=%s",
                pp.get("addr", 0), bytes(pp.get("data_in") or b"").hex(),
                cfg.addr, exp_bytes.hex())
            raise AssertionError("SPI flash command breadth golden: PAGE PROGRAM addr/data mismatch")

        neigh_pp = txns[4]
        neigh_bytes = cfg.neigh_bytes()
        if neigh_pp.get("addr") != cfg.neigh_addr or bytes(neigh_pp.get("data_in") or b"") != neigh_bytes:
            self.logger.error(
                "SPI flash command breadth GOLDEN FAIL: neighbour PP addr=0x%06x data_in=%s vs exp addr=0x%06x data=%s",
                neigh_pp.get("addr", 0), bytes(neigh_pp.get("data_in") or b"").hex(),
                cfg.neigh_addr, neigh_bytes.hex())
            raise AssertionError("SPI flash command breadth golden: neighbour PAGE PROGRAM mismatch")

        erased = flash.read_memory(cfg.addr, cfg.nwords * 4)
        if erased != b"\xff" * (cfg.nwords * 4):
            self.logger.error("SPI flash command breadth GOLDEN FAIL: post-erase mem not 0xFF: %s",
                              erased.hex())
            raise AssertionError("SPI flash command breadth golden: sector erase did not wipe the page")
        neigh_left = flash.read_memory(cfg.neigh_addr, cfg.nwords * 4)
        if neigh_left != neigh_bytes:
            self.logger.error(
                "SPI flash command breadth GOLDEN FAIL: neighbour 0x%06x wiped or corrupted: %s vs %s",
                cfg.neigh_addr, neigh_left.hex(), neigh_bytes.hex())
            raise AssertionError("SPI flash command breadth golden: sector erase wiped the neighbour")
        self.logger.info(
            "SPI flash command breadth GOLDEN PASS: PP@0x%06x %dB landed, erase wiped it, "
            "neighbour 0x%06x intact",
            cfg.addr, cfg.nwords * 4, cfg.neigh_addr)
