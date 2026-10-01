# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared scenario for the primary-fails / backup-also-fails testcases.

Several testcases differ only in what is wrong with the BACKUP manifest, so the
failover sequencing, evidence collection and terminal checks live here once.
Subclasses supply the backup defect and the verdict it must produce.

Both halves of the stimulus matter: the primary's ``manifest_identifier`` is
corrupted as well, because a testcase that only corrupted the backup would boot
happily from the valid primary, never read the backup, and pass while proving
nothing. The ordering assertions are what make the failover part of the result
rather than an assumption. A subclass whose scenario is "both slots carry the
same defect" replaces that trigger through :meth:`corrupt_primary` and
``primary_expected_error``, and then owns :meth:`check_defect_attribution`
because the defect marker no longer identifies a slot on its own.

This ROM runs the manifest loop and the crypto chain as two separate stages
(``rom_main.c`` then ``oca_boot.c``): ``rom_manifest_boot`` checks each slot's structure, hash
and usage constraints, and only after a slot passes does
the crypto stage checks security_version, key selection and the
signature. So a backup with a cryptographic defect legitimately prints
``MANIFEST_OK`` first and then fails with ``MANIFEST_ERR=`` -- which is why
``MANIFEST_OK`` is not in the forbidden list.

``SepBootScoreboard`` is not used: it requires ``fw_done`` and ``fw_pass``, and the
expected outcome here is ``fw_done`` with ``fw_pass == 0``.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import cocotb
from cocotb.triggers import RisingEdge
from env import sep_manifest_mutate as mm
from env.sep_esrc_noise import esrc_noise_task
from env.sep_rom_console import log_scratch_cold, rom_console_task
from env.sep_verdict import decode_verdict
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_SEP_ROOT = str(Path(__file__).resolve().parents[4])
_FW_DIR = os.path.join(_SEP_ROOT, "bootrom", "prod", "build_ot")
_SECURE_FLASH_IMAGE = os.path.join(_SEP_ROOT, "bootrom", "prod", "build", "oca_secure_boot.bin")
_ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")

# oca_layout.h / constants.py
# Rejection codes the ROM prints as MANIFEST_ERR=<code>, derived from the
# validator's result enum rather than copied: the enum renumbers as the library
# grows, and a stale value fails a test for the wrong reason while still reading
# as the planted defect.
MANIFEST_ERR_BAD_MAGIC = mm.boot_err("OCA_FAIL_MAGIC")
MANIFEST_ERR_SIG_FAILED = mm.boot_err("OCA_FAIL_SIGNATURE")
MANIFEST_ERR_VERSION_ROLLBACK = mm.boot_err("OCA_FAIL_SECURITY_VERSION")
MANIFEST_ERR_KEY_REVOKED = mm.boot_err("OCA_FAIL_ROOT_KEY_REVOKED")
# Every refusal from plat_is_key_authorized() carries this one code -- slot
# reserved, selector ambiguous or empty, slot unprovisioned, algorithm or encoding
# unsupported, digest mismatch. The code means "this key is not authorized"; the
# console marker beside it is what says which arm refused, so a member pins the
# code here and the reason through its defect marker.
# MANIFEST_ERR_KEY_HASH_MISMATCH below is the same value under the narrower name
# the digest-mismatch members use.
MANIFEST_ERR_KEY_UNAUTHORIZED = mm.boot_err("OCA_FAIL_ROOT_KEY_UNAUTHORIZED")
# A signature/public-key size or algorithm field that disagrees with itself is
# refused structurally, before key selection runs, so this arm prints no PUBK_*
# marker at all.
MANIFEST_ERR_SIG_TYPE_INVALID = mm.boot_err("OCA_FAIL_CRYPTO_FIELD_SIZE")
# Secure boot is in force and the manifest names no signature class to verify
# with. Reached through any input the precedence consults, most often a device
# whose lifecycle enforces secure boot handed a validly unsigned manifest.
MANIFEST_ERR_SIG_CLASS_CONTROL = mm.boot_err("OCA_FAIL_SIGNATURE_CLASS_CONTROL")
MANIFEST_ERR_KEY_HASH_MISMATCH = mm.boot_err("OCA_FAIL_ROOT_KEY_UNAUTHORIZED")

# Slot identity is asserted on MANIFEST_SRC=, never on the MANIFEST_PRIMARY /
# MANIFEST_BACKUP label: the ROM derives the label from the retry counter but the
# offset from the (possibly rotated) slot index (oca_boot.c),
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
# How long to watch after the terminal verdict before believing the ROM halted. The
# same order of magnitude as sep_firmware_mbist_fail_test's quiescence window,
# and ~30x the longest gap between consecutive console lines in a passing run of
# these testcases, so a ROM that merely paused would still be caught.
_QUIESCE_CYCLES = 20_000


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
    # Raw LC_STATE that preload must carry. PROD, unless the scenario is another
    # lifecycle posture that enforces secure boot.
    expected_lc_raw: int = 0x1
    # Extra markers that must not appear, on top of the shared list.
    extra_forbidden: tuple[str, ...] = ()
    # ROM error code the PRIMARY slot must be rejected with. Only the "both slots
    # carry the same defect" testcase changes this; every other member wants the
    # deterministic BAD_MAGIC trigger corrupt_primary() plants.
    primary_expected_error: int = MANIFEST_ERR_BAD_MAGIC

    def corrupt_primary(self, buf: bytearray) -> None:
        """Make the primary slot fail, so the backup is reached at all.

        Default is the magic word, rejected by ``oca_peek_manifest`` before
        any hash or crypto work, so the failover trigger cannot interact with the
        defect under test. A subclass overrides this only when the primary's defect
        is itself part of the scenario, and must set ``primary_expected_error`` to
        match.
        """
        mm.break_magic(buf, "primary")

    def corrupt_backup(self, buf: bytearray) -> None:
        raise NotImplementedError

    def check_efuse(self, image) -> None:
        """Subclass hook for the fuse preconditions its defect depends on."""

    # --- scenario ----------------------------------------------------------
    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        # Primary: the failover trigger. By default a broken magic word, rejected
        # by oca_peek_manifest before the hash check -- a deterministic
        # BAD_MAGIC rather than a verdict that depends on check order, and not the
        # defect under test. See corrupt_primary().
        self.corrupt_primary(buf)
        self.logger.info("CHK-STIMULUS-PRIMARY: %s", mm.describe(buf, "primary"))
        # Backup: the defect this testcase is actually about.
        self.corrupt_backup(buf)
        self.logger.info("CHK-STIMULUS-BACKUP: %s", mm.describe(buf, "backup"))
        return buf

    async def run_scenario(self) -> None:
        dut = cocotb.top
        from ocah_spi_vip import OcahSpiFlash

        # +esrc_noise_force only FORCES the decorrelator inputs from
        # esrc_noise_ext_i; it generates nothing, and sep_base_test leaves that
        # port at 0. Without a driver the repetition health test trips and the ROM
        # refuses to boot on a dead entropy source, so every member of this family
        # dies at ESRC_HEALTH_FAIL before reaching the verdict it exists to check.
        # sep_rom_ot_dma_boot_test starts this for the families that descend from
        # it; this base descends straight from sep_base_test, so it starts its own.
        cocotb.start_soon(esrc_noise_task(dut, logger=self.logger))

        assert self.backup_defect_marker, "subclass must set backup_defect_marker"
        assert self.expected_error, "subclass must set expected_error"
        assert self.efuse_preload and os.path.isfile(self.efuse_preload), (
            f"eFuse preload missing: {self.efuse_preload}"
        )

        image = self.select_efuse_image(default_preload=self.efuse_preload)
        lc = image.lc_raw()
        assert lc == self.expected_lc_raw, (
            f"LC_STATE raw is 0x{lc:x}, expected 0x{self.expected_lc_raw:x}: secure "
            f"boot must be enforced or the crypto verdict under test is never reached"
        )
        assert image.field_int("SBOOT_DIS") & 0x1 == 0, (
            "SBOOT_DIS is set, which disables the entire crypto chain"
        )
        self.check_efuse(image)
        self.write_efuse_image(image)
        self.logger.info(
            "CHK-STIMULUS-EFUSE PASS: LC raw=0x%x, BL1_VERSION=0x%x, PUBK_REVOKE=0x%x",
            lc,
            image.field_int("BL1_VERSION"),
            image.field_int("CHIPLET_PUBK_REVOKE"),
        )

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
            dut.spi_cs_n_o,
            dut.spi_sck_o,
            mosi=dut.spi_mosi_o,
            miso=dut.spi_miso_i,
            name="sep_backup_fail_flash",
        )
        # Published for subclasses that check the DEVICE side of the failover.
        # `MANIFEST_SRC=` only says which address the ROM intended to read; the
        # BFM's transaction record says which address the device actually served
        # and in what order, and the successful half of boot_flash_reinit()
        # (oca_boot.c) prints nothing at all. Two attribute stores, read
        # by nobody else -- no existing subclass references either name, so this
        # cannot change any established behaviour.
        self._flash = flash
        self._image_len = len(img)
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
                _ROM_BASE >> 1,
                pre_reset_hook=_load_tcm,
                run_pulse_cycles=40,
            )
            for cycle in range(_MAX_RUN_CYCLES):
                await RisingEdge(dut.clk_i)
                probe = self.rd(dut.scratch_cold_probe_o)
                status = (probe >> 32) & 0xFFFF_FFFF
                if status != last_status:
                    last_status = status
                    status_seq.append(status)
                if self.rd(dut.cpu_trace_valid_o):
                    retired += 1
                # Completion comes from the verdict word in cold_scratch[0]
                # (dv/docs/rom_verdict_scratch0_migration.md).
                verdict = decode_verdict(probe)
                if verdict is not None:
                    fw_done = True
                    fw_pass = verdict[1]
                    self.logger.info(
                        "CHK-VERDICT: ROM signalled completion at cycle %d via "
                        "cold_scratch[0], pass=%d",
                        cycle,
                        fw_pass,
                    )
                    break
                if cycle - last_log >= _PROGRESS_EVERY:
                    last_log = cycle
                    self.logger.info(
                        "failover poll cyc=%d status=0x%08x retired=%d lines=%d",
                        cycle,
                        status,
                        retired,
                        len(console),
                    )

            # Did it actually STOP? The procedures for these testcases say the ROM
            # hangs after the terminal error, and the verdict alone does not say
            # that: rom_err_fail() writes cold_scratch[1] (the code) and
            # cold_scratch[0] (the FAIL verdict), and only THEN enters
            # `for(;;) wfi`. A ROM that reported the failure and carried on booting
            # would write that verdict at exactly the same instant, so without this
            # window "terminal" rests on the ROM's noreturn attribute rather than
            # on an observation.
            #
            # Three things must hold in the window, and none of them depends on
            # where the spin loop happens to sit: the status word must not move on,
            # the console must not produce a new line, and no boot-progress marker
            # may appear. Instruction retirement is deliberately NOT used as the
            # signal -- the wfi loop keeps retiring, so volume proves nothing.
            if fw_done:
                post_status_moved = False
                console_len_at_done = len(console)
                for _ in range(_QUIESCE_CYCLES):
                    await RisingEdge(dut.clk_i)
                    probe = self.rd(dut.scratch_cold_probe_o)
                    if ((probe >> 32) & 0xFFFF_FFFF) != last_status:
                        post_status_moved = True
                        break
                post_console = console[console_len_at_done:]
        finally:
            await flash.stop()
            log_scratch_cold(self.logger)

        self._check(console, status_seq, fw_done, fw_pass, retired)
        if fw_done:
            self._check_quiesced(post_status_moved, post_console, last_status)

    # --- checks ------------------------------------------------------------
    def _check_quiesced(self, post_status_moved, post_console, terminal_status) -> None:
        """CHK-HANG: the ROM stopped, rather than reporting and continuing."""
        # The window now opens at the cold_scratch[0] verdict write rather than at
        # the mailbox FAIL that follows it, so it starts a few cycles EARLIER and
        # covers strictly more of the post-error interval. Same check, slightly
        # wider reach.
        assert not post_status_moved, (
            f"cold_scratch[1] moved on from 0x{terminal_status:08x} within "
            f"{_QUIESCE_CYCLES} cycles of the terminal verdict: the ROM reported "
            f"the terminal error and then kept running"
        )
        assert not post_console, (
            f"ROM printed {post_console} after the terminal verdict; a terminal "
            f"error path ends in `for(;;) wfi` and produces no further output"
        )
        self.logger.info(
            "CHK-HANG: cold_scratch[1] held 0x%08x and the console stayed silent "
            "for %d cycles after the terminal verdict",
            terminal_status,
            _QUIESCE_CYCLES,
        )

    def check_defect_attribution(self, console, i_backup: int) -> None:
        """Prove ``backup_defect_marker`` is the BACKUP's verdict, not the primary's.

        The default holds for every scenario whose primary fails structurally: the
        marker can only have come from the backup, so its first occurrence must
        follow the backup read. A scenario that plants the SAME defect in both
        slots sees the marker twice and must override this -- the first occurrence
        is then legitimately the primary's, and accepting it here would let a run
        that never evaluated the backup at all look identical.
        """
        i_defect = next(
            (i for i, line in enumerate(console) if self.backup_defect_marker in line),
            -1,
        )
        assert i_defect >= 0, (
            f"ROM never printed {self.backup_defect_marker}: the backup was not "
            f"rejected for the reason this testcase plants. Console: {console}"
        )
        assert i_backup < i_defect, (
            f"{self.backup_defect_marker} appeared at line {i_defect}, before the "
            f"backup slot was read at line {i_backup}: it cannot be the backup's verdict"
        )
        self.logger.info(
            "CHK-BACKUP-DEFECT: %s observed after the backup read", self.backup_defect_marker
        )

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

        primary_err = f"MANIFEST_ERR=0x{self.primary_expected_error:08x}"
        i_primary = index_of(_PRIMARY_SRC)
        i_primary_err = index_of(primary_err)
        i_backup = index_of(_BACKUP_SRC)
        crypto_fail = f"MANIFEST_ERR=0x{self.expected_error:08x}"
        i_crypto = index_of(crypto_fail)

        # CHK-PRIMARY: the primary slot was attempted and rejected for the reason
        # the stimulus planted. Without this the run could be a backup-only boot.
        assert i_primary >= 0, (
            f"ROM never read the primary slot ({_PRIMARY_SRC}). Console: {console}"
        )
        assert i_primary_err >= 0, (
            f"primary was not rejected with {primary_err}; the failover trigger "
            f"did not work, so the backup defect may never have been reached. "
            f"Console: {console}"
        )
        log.info(
            "CHK-FAILOVER-PRIMARY: primary read at %s and rejected with %s",
            _PRIMARY_SRC,
            primary_err,
        )

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
        log.info("CHK-FAILOVER-BACKUP: backup read at %s, after the primary rejection", _BACKUP_SRC)

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
        self.check_defect_attribution(console, i_backup)

        # CHK-TERMINAL: the exact error code, on the console and in the status
        # word, plus a mailbox FAIL. The status word is the independent half: the
        # console marker says which check complained, the encoded status says what
        # the ROM converged on.
        assert i_crypto >= 0, (
            f"ROM never printed {crypto_fail}; the terminal error code is not the "
            f"one this defect should produce. Console: {console}"
        )
        # The console code and the status word live in different spaces: the console
        # carries OCA_BOOT_ERR_BASE | oca_result_t, the ring carries
        # STATUS_ENCODE(type, SEP_MSG_*). status_for_result() in oca_boot.c is the only
        # bridge, so the expectation goes through it rather than masking the console
        # code -- for most codes the two differ, and asserting the masked half is
        # asserting on a word the ROM never writes.
        sep_msg = mm.rom_status_for_result(self.expected_error)
        expected_status = 0x0F01_0000 | sep_msg
        assert expected_status in status_seq, (
            f"cold_scratch[1] never held 0x{expected_status:08x} "
            f"(STATUS_ENCODE(ERROR, SEP_MSG 0x{sep_msg:04x}), which is what "
            f"status_for_result() maps MANIFEST_ERR=0x{self.expected_error:08x} to); "
            f"observed {status_hex}"
        )
        assert fw_done, (
            f"ROM never signalled completion within {_MAX_RUN_CYCLES} cycles; a "
            f"rejected manifest must converge on a mailbox FAIL. "
            f"cold_scratch[1]: {status_hex}"
        )
        assert not fw_pass, "ROM signalled PASS: it booted an image it was supposed to reject"
        log.info(
            "CHK-TERMINAL PASS: %s, cold_scratch[1]=0x%08x, mailbox FAIL (fw_pass=0)",
            crypto_fail,
            expected_status,
        )

        # CHK-NO-BOOT: nothing downstream of the rejection ran.
        for marker in _BOOT_PROGRESS_MARKERS + tuple(self.extra_forbidden):
            assert not any(marker in line for line in console), (
                f"ROM printed {marker}, which sits past the rejection: it continued "
                f"booting a manifest it had already failed. Console: {console}"
            )
        log.info(
            "CHK-NO-BOOT: none of %s reached",
            ", ".join(_BOOT_PROGRESS_MARKERS + tuple(self.extra_forbidden)),
        )
