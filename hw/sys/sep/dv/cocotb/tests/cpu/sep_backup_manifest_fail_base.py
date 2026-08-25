# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared scenario for the primary-fails / backup-also-fails testcases.

Three testcases differ only in what is wrong with the BACKUP manifest, so the
failover sequencing, evidence collection and terminal checks live here once.
Subclasses supply the backup defect and the verdict it must produce.

Both halves of the stimulus matter: the primary's ``manifest_identifier`` is
corrupted as well, because a testcase that only corrupted the backup would boot
happily from the valid primary, never read the backup, and pass while proving
nothing. The ordering assertions are what make the failover part of the result
rather than an assumption.

This ROM runs the manifest loop and the crypto chain as two separate stages
(``rom_main.c:324-346``): ``rom_manifest_boot`` checks each slot's structure, hash
and usage constraints, and only after a slot passes does
``manifest_crypto_validate`` check security_version, key selection and the
signature. So a backup with a cryptographic defect legitimately prints
``MANIFEST_OK`` first and then fails with ``CRYPTO_FAIL=`` -- which is why
``MANIFEST_OK`` is not in the forbidden list.

``SepBootScoreboard`` is not used: it requires ``fw_done`` and ``fw_pass``, and the
expected outcome here is ``fw_done`` with ``fw_pass == 0``.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from sep_reg_meta import sym

import cocotb
from cocotb.triggers import RisingEdge

from sep_base_test import sep_base_test
from env import sep_manifest_mutate as mm
from env.sep_rom_console import rom_console_task, log_scratch_cold

_SEP_ROOT = str(Path(__file__).resolve().parents[4])
_FW_DIR = os.path.join(_SEP_ROOT, "bootrom", "prod", "build_ot")
_SECURE_FLASH_IMAGE = os.path.join(_SEP_ROOT, "bootrom", "prod", "build", "secure_boot.bin")
_ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")

# manifest.h:294-320
MANIFEST_ERR_BAD_MAGIC = 0x0003_0002
MANIFEST_ERR_SIG_FAILED = 0x0003_000C
MANIFEST_ERR_VERSION_ROLLBACK = 0x0003_0014

# Slot identity is asserted on MANIFEST_SRC=, never on the MANIFEST_PRIMARY /
# MANIFEST_BACKUP label: the ROM derives the label from the retry counter but the
# offset from the (possibly rotated) slot index (manifest_load.c:541-544,567),
# so under rotate_update the label and the slot disagree. The offset cannot lie.
_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"

# Must never appear: the ROM handed off to BL1, i.e. it booted a manifest it was
# supposed to reject.
_BOOT_PROGRESS_MARKERS = ("PRE_JUMP", "BL1_COPIED", "BL1_JUMP=")
# Must never appear: secure boot was skipped, so the crypto verdict under test
# was never reached.
_SBOOT_OFF = "SBOOT_OFF"

_MAX_RUN_CYCLES = 24_000_000
_PROGRESS_EVERY = 200_000


class sep_backup_manifest_fail_base(sep_base_test):
    """Corrupt the primary, plant a defect in the backup, require a terminal fail."""

    build_env = False
    rom_build_dir = _FW_DIR
    flash_image = _SECURE_FLASH_IMAGE

    # --- subclass contract -------------------------------------------------
    # Console marker the backup's defect must produce.
    backup_defect_marker: str = ""
    # ROM error code the run must terminate on.
    expected_error: int = 0
    # Committed OTP preload this scenario needs.
    efuse_preload: Path | None = None
    # Extra markers that must not appear, on top of the shared list.
    extra_forbidden: tuple[str, ...] = ()

    def corrupt_backup(self, buf: bytearray) -> None:
        raise NotImplementedError

    def check_efuse(self, image) -> None:
        """Subclass hook for the fuse preconditions its defect depends on."""

    # --- scenario ----------------------------------------------------------
    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        # Primary: break the magic so the slot is rejected by
        # validate_manifest_header, which runs before the hash check -- a
        # deterministic BAD_MAGIC rather than a verdict that depends on check
        # order. This is the failover trigger, not the defect under test.
        mm.set_identifier(buf, "primary")
        self.logger.info("CHK-STIMULUS-PRIMARY: %s", mm.describe(buf, "primary"))
        # Backup: the defect this testcase is actually about.
        self.corrupt_backup(buf)
        self.logger.info("CHK-STIMULUS-BACKUP: %s", mm.describe(buf, "backup"))
        return buf

    async def run_scenario(self) -> None:
        dut = cocotb.top
        from ocah_spi_vip import OcahSpiFlash

        assert self.backup_defect_marker, "subclass must set backup_defect_marker"
        assert self.expected_error, "subclass must set expected_error"
        assert self.efuse_preload and os.path.isfile(self.efuse_preload), (
            f"eFuse preload missing: {self.efuse_preload}"
        )

        image = self.select_efuse_image(default_preload=self.efuse_preload)
        lc = image.lc_raw()
        assert lc == 0x1, (
            f"LC_STATE raw is 0x{lc:x}, expected 0x1 (PROD): secure boot must be "
            f"enforced or the crypto verdict under test is never reached"
        )
        assert image.field_int("SBOOT_DIS") & 0x1 == 0, (
            "SBOOT_DIS is set, which disables the entire crypto chain"
        )
        self.check_efuse(image)
        self.write_efuse_image(image)
        self.logger.info("CHK-STIMULUS-EFUSE: LC raw=0x%x, BL1_VERSION=0x%x, PUBK_REVOKE=0x%x",
                         lc, image.field_int("BL1_VERSION"),
                         image.field_int("CHIPLET_PUBK_REVOKE"))

        console: list[str] = []
        cocotb.start_soon(rom_console_task(self.logger, sink=console))

        for src, dst in (
            (os.path.join(self.rom_build_dir, "boot_rom.itcm.hex"), "sep_itcm.hex"),
            (os.path.join(self.rom_build_dir, "boot_rom.dtcm.hex"), "sep_dtcm.hex"),
        ):
            if not os.path.isfile(src):
                raise FileNotFoundError(f"ROM image not found: {src}")
            shutil.copyfile(src, os.path.join(os.getcwd(), dst))

        async def _load_tcm() -> None:
            dut.tcm_load_i.value = 1
            await RisingEdge(dut.clk_i)
            await RisingEdge(dut.clk_i)
            dut.tcm_load_i.value = 0

        with open(self.flash_image, "rb") as fh:
            img = bytearray(fh.read())
        flash = OcahSpiFlash(
            dut.spi_cs_n_o, dut.spi_sck_o, mosi=dut.spi_mosi_o, miso=dut.spi_miso_i,
            name="sep_backup_fail_flash",
        )
        flash.preload(bytes(self.mutate_flash_image(img)))
        await flash.start()

        status_seq: list[int] = []
        last_status = None
        fw_done = False
        fw_pass = 0
        retired = 0
        last_log = 0
        try:
            await self.bring_up_cpu_boot(
                _ROM_BASE >> 1, pre_reset_hook=_load_tcm, run_pulse_cycles=40,
            )
            for cycle in range(_MAX_RUN_CYCLES):
                await RisingEdge(dut.clk_i)
                status = (self.rd(dut.scratch_cold_probe_o) >> 32) & 0xFFFF_FFFF
                if status != last_status:
                    last_status = status
                    status_seq.append(status)
                if self.rd(dut.cpu_trace_valid_o):
                    retired += 1
                if self.rd(dut.fw_done_o):
                    fw_done = True
                    fw_pass = self.rd(dut.fw_pass_o)
                    self.logger.info("ROM signalled completion at cycle %d", cycle)
                    break
                if cycle - last_log >= _PROGRESS_EVERY:
                    last_log = cycle
                    self.logger.info("failover poll cyc=%d status=0x%08x retired=%d lines=%d",
                                     cycle, status, retired, len(console))
        finally:
            await flash.stop()
            log_scratch_cold(self.logger)

        self._check(console, status_seq, fw_done, fw_pass, retired)

    # --- checks ------------------------------------------------------------
    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        log = self.logger
        status_hex = [hex(v) for v in status_seq]
        log.info("cold_scratch[1] sequence: %s", status_hex)
        log.info("ROM console: %s", console)

        def index_of(marker: str) -> int:
            """First console line index containing marker, or -1."""
            for i, line in enumerate(console):
                if marker in line:
                    return i
            return -1

        # Guard the guards: a dark console makes every marker check vacuous.
        assert retired, "core retired no instructions; the ROM never ran"
        assert console, (
            "ROM console is empty, so no marker check below means anything (the "
            "virt console is DEBUG-build only -- check the ROM build)"
        )

        primary_err = f"MANIFEST_ERR=0x{MANIFEST_ERR_BAD_MAGIC:08x}"
        i_primary = index_of(_PRIMARY_SRC)
        i_primary_err = index_of(primary_err)
        i_backup = index_of(_BACKUP_SRC)
        i_defect = index_of(self.backup_defect_marker)
        crypto_fail = f"CRYPTO_FAIL=0x{self.expected_error:08x}"
        i_crypto = index_of(crypto_fail)

        # CHK-PRIMARY: the primary slot was attempted and rejected for the reason
        # the stimulus planted. Without this the run could be a backup-only boot.
        assert i_primary >= 0, (
            f"ROM never read the primary slot ({_PRIMARY_SRC}). Console: {console}"
        )
        assert i_primary_err >= 0, (
            f"primary was not rejected as BAD_MAGIC ({primary_err}); the failover "
            f"trigger did not work, so the backup defect may never have been "
            f"reached. Console: {console}"
        )
        log.info("CHK-FAILOVER-PRIMARY: primary read at %s and rejected with %s",
                 _PRIMARY_SRC, primary_err)

        # CHK-FAILOVER: the backup slot was read, and read AFTER the primary was
        # rejected. Ordering is the substance of a failover test; two markers in
        # any order would also be satisfied by a ROM that read the backup first.
        assert i_backup >= 0, (
            f"ROM never fell over to the backup slot ({_BACKUP_SRC}). Console: {console}"
        )
        assert i_primary < i_backup, (
            f"backup slot was read before the primary was rejected (primary at line "
            f"{i_primary}, backup at line {i_backup}): this is not a failover"
        )
        assert i_primary_err < i_backup, (
            f"primary rejection ({primary_err}, line {i_primary_err}) did not precede "
            f"the backup read (line {i_backup})"
        )
        log.info("CHK-FAILOVER-BACKUP: backup read at %s, after the primary rejection",
                 _BACKUP_SRC)

        # CHK-SECURE-RAN: the crypto chain executed. If secure boot had been
        # skipped, the backup's cryptographic defect would be irrelevant and the
        # terminal error below would have a different cause.
        assert not any(_SBOOT_OFF in line for line in console), (
            f"ROM printed {_SBOOT_OFF}: secure boot was skipped, so the backup "
            f"defect under test was never evaluated. Console: {console}"
        )
        log.info("CHK-SECURE-RAN: %s absent, crypto chain was entered", _SBOOT_OFF)

        # CHK-DEFECT: the backup was rejected for the planted reason, and after
        # the backup slot was read.
        assert i_defect >= 0, (
            f"ROM never printed {self.backup_defect_marker}: the backup was not "
            f"rejected for the reason this testcase plants. Console: {console}"
        )
        assert i_backup < i_defect, (
            f"{self.backup_defect_marker} appeared at line {i_defect}, before the "
            f"backup slot was read at line {i_backup}: it cannot be the backup's verdict"
        )
        log.info("CHK-BACKUP-DEFECT: %s observed after the backup read",
                 self.backup_defect_marker)

        # CHK-TERMINAL: the exact error code, on the console and in the status
        # word, plus a mailbox FAIL. The status word is the independent half: the
        # console marker says which check complained, the encoded status says what
        # the ROM converged on.
        assert i_crypto >= 0, (
            f"ROM never printed {crypto_fail}; the terminal error code is not the "
            f"one this defect should produce. Console: {console}"
        )
        expected_status = 0x0F01_0000 | (self.expected_error & 0xFFFF)
        assert expected_status in status_seq, (
            f"cold_scratch[1] never held 0x{expected_status:08x} "
            f"(STATUS_ENCODE(ERROR, 0x{self.expected_error & 0xFFFF:04x})); "
            f"observed {status_hex}"
        )
        assert fw_done, (
            f"ROM never signalled completion within {_MAX_RUN_CYCLES} cycles; a "
            f"rejected manifest must converge on a mailbox FAIL. "
            f"cold_scratch[1]: {status_hex}"
        )
        assert not fw_pass, (
            "ROM signalled PASS: it booted an image it was supposed to reject"
        )
        log.info("CHK-TERMINAL: %s, cold_scratch[1]=0x%08x, mailbox FAIL (fw_pass=0)",
                 crypto_fail, expected_status)

        # CHK-NO-BOOT: nothing downstream of the rejection ran.
        for marker in _BOOT_PROGRESS_MARKERS + tuple(self.extra_forbidden):
            assert not any(marker in line for line in console), (
                f"ROM printed {marker}, which sits past the rejection: it continued "
                f"booting a manifest it had already failed. Console: {console}"
            )
        log.info("CHK-NO-BOOT: none of %s reached",
                 ", ".join(_BOOT_PROGRESS_MARKERS + tuple(self.extra_forbidden)))
