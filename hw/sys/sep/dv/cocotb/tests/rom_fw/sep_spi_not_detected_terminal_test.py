# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Both manifest slots blank: the ROM must report a terminal error and hang.

Both slot spans are erased to 0xFF (see ``erase_slot()`` in ``env/sep_manifest_mutate.py``),
so the device answers at both addresses but neither holds a manifest. After both slots
fail, the ROM reports ``SEP_MSG_MANIFEST_LOAD_FAILED`` and prints ``MANIFEST_ALL_FAILED``
(``oca_boot.c``), then ``rom_err_fail()`` writes the FAIL verdict to cold_scratch[0] and
the ROM waits in ``wfi``. Both status words are required: each slot's rejection
``0x0f010006`` (``SEP_MSG_INVALID_MANIFEST_ID``) and the loop verdict ``0x0f010213``.
The ROM has no SPI-detect step, so no SPI-not-detected status is expected.

``SepBootScoreboard`` is not used: it requires ``fw_pass``. The poll loop checks
``fw_done`` with ``fw_pass == 0`` directly. Ring-invalid writes to cold_scratch[1]
(``SEP_MSG_STATUS_REPORTING_INVALID``; the environment leaves ``num_entries`` at 0) are
filtered out. ``SPI_INIT_OK`` is required and the SPI-init-failed fallback is forbidden,
so both addresses were really read.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from env import sep_manifest_mutate as mm
from env import sep_spi_slot_evidence as ev
from env.sep_efuse_image import LC_TEST_DEV, SepEfuseImage
from env.sep_rom_console import log_scratch_cold, rom_console_task
from env.sep_verdict import TEST_PASS_CODE, decode_verdict
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_SEP_ROOT = str(Path(__file__).resolve().parents[4])
_FW_DIR = os.path.join(_SEP_ROOT, "bootrom", "prod", "build")
_FLASH_IMAGE = os.path.join(_SEP_ROOT, "bootrom", "prod", "build", "oca_non_secure_boot.bin")
_ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")

# An erased slot fails the magic check, before the hash check.
MANIFEST_ERR_BAD_MAGIC = mm.boot_err("OCA_FAIL_MAGIC")
# status_values.h, errors.h -> STATUS_ENCODE(STATUS_TYPE_ERROR, x).
SEP_MSG_MANIFEST_LOAD_FAILED = 0x213
# status_for_result() maps OCA_FAIL_MAGIC to this, so a rejected slot reports the
# message id, not the low half of the error code the console prints.
SEP_MSG_INVALID_MANIFEST_ID = 0x06
# status_ring_buffer_insert() writes this to cold_scratch[1] whenever the ring
# descriptor is unusable, and the SEP DV environment leaves num_entries at 0, so
# it lands after every status and is always the last value in the register.
SEP_MSG_STATUS_REPORTING_INVALID = 0x79
_STATUS_LOOP_FAILED = 0x0F01_0000 | SEP_MSG_MANIFEST_LOAD_FAILED
_STATUS_SLOT_REJECTED = 0x0F01_0000 | SEP_MSG_INVALID_MANIFEST_ID
_STATUS_RING_INVALID = 0x0F01_0000 | SEP_MSG_STATUS_REPORTING_INVALID

_SPI_PATH = "BOOT_SPI"
_SMC_PATH = "WAIT_SMC_MANIFEST"
_SPI_INIT_OK = "SPI_INIT_OK"
_SPI_INIT_ERR = "SPI_INIT_ERR="
_SPI_INIT_FAILED_SKIP = "SPI init failed, using backup manifest"
_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"
_BAD_MAGIC_ERR = f"MANIFEST_ERR=0x{MANIFEST_ERR_BAD_MAGIC:08x}"
_ALL_FAILED = "MANIFEST_ALL_FAILED"
# Must never appear: a slot validated, so "both addresses no-detect" is false.
_MANIFEST_OK = "MANIFEST_OK"
# Must never appear: the ROM handed off despite having no valid manifest.
_BOOT_PROGRESS = ("PRE_JUMP", "BL1_COPIED", "BL1_JUMP=")

_MAX_RUN_CYCLES = 24_000_000
_PROGRESS_EVERY = 200_000
# Cycles to keep watching after the terminal verdict, to establish that the ROM
# stayed in its terminal state. The ROM's hang is `for(;;) wfi` in rom_err_fail();
# 20k cycles is ~15x the longest single ROM step, so a ROM that was going to do
# anything else would have started doing it.
_HANG_OBSERVE_CYCLES = 20_000


@pyuvm.test()
class sep_spi_not_detected_terminal_test(sep_base_test):
    """Both slot addresses blank -> ROM converges on a terminal error and hangs."""

    build_env = False
    rom_build_dir = _FW_DIR
    flash_image = _FLASH_IMAGE

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        spans = {}
        for slot in ("primary", "backup"):
            spans[slot] = mm.erase_slot(buf, slot)
            # A partially erased slot would still be rejected, for a reason this
            # test did not plant, and look identical.
            assert mm.slot_is_erased(buf, slot), (
                f"{slot} slot is not fully erased after erase_slot()"
            )
        self.logger.info(
            "CHK-STIMULUS-SPI PASS: both slots erased to 0x%02x -- primary "
            "0x%06x..0x%06x, backup 0x%06x..0x%06x",
            mm.ERASED_BYTE,
            spans["primary"][0],
            spans["primary"][1],
            spans["backup"][0],
            spans["backup"][1],
        )
        return buf

    async def run_scenario(self) -> None:
        dut = cocotb.top
        from ocah_spi_vip import OcahSpiFlash

        # Same OTP as the positive siblings: TEST_DEV, so rom_lifecycle_policy
        # accepts the part and the run terminates on the address condition under
        # test rather than on an invalid lifecycle.
        efuse = SepEfuseImage()
        efuse.set_lc_state(LC_TEST_DEV)
        self.write_efuse_image(efuse)

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
        loaded = bytes(self.mutate_flash_image(img))
        image_len = len(loaded)
        flash = OcahSpiFlash(
            dut.spi_cs_n_o,
            dut.spi_sck_o,
            mosi=dut.spi_mosi_o,
            miso=dut.spi_miso_i,
            name="sep_spi_no_detect_flash",
        )
        flash.preload(loaded)
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
                # Completion comes from the verdict word in cold_scratch[0].
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
                        "no-detect poll cyc=%d status=0x%08x retired=%d lines=%d",
                        cycle,
                        status,
                        retired,
                        len(console),
                    )

            # The hang is part of the expected result. Breaking out the cycle the
            # verdict is written would show the ROM reported a failure but not that
            # it stayed stopped.
            if fw_done:
                lines_at_done = len(console)
                for _ in range(_HANG_OBSERVE_CYCLES):
                    await RisingEdge(dut.clk_i)
                    probe = self.rd(dut.scratch_cold_probe_o)
                    hang_status = (probe >> 32) & 0xFFFF_FFFF
                    if hang_status != last_status:
                        last_status = hang_status
                        status_seq.append(hang_status)
                    # "Did it claim PASS after the terminal error?" The loop
                    # above latched the FAIL and stopped, so a later PASS has to
                    # be looked for directly -- that is the whole point of this
                    # window.
                    if (probe & 0xFFFF_FFFF) == TEST_PASS_CODE:
                        fw_pass = 1
                post_lines = console[lines_at_done:]
                self.logger.info(
                    "CHK-HANG: %d cycles after the terminal status, "
                    "cold_scratch[1]=0x%08x, fw_pass=%d, %d new console line(s): %s",
                    _HANG_OBSERVE_CYCLES,
                    last_status,
                    fw_pass,
                    len(post_lines),
                    post_lines,
                )
        finally:
            txns = flash.get_transactions()
            await flash.stop()
            # Logged here so a failing assertion below cannot suppress it.
            self.logger.info("CHK-SPI-TXNS:\n%s", ev.summarize(txns, image_len))
            log_scratch_cold(self.logger)

        self._check(console, status_seq, fw_done, fw_pass, retired, txns, image_len)

    # --- checks ------------------------------------------------------------
    def _check(self, console, status_seq, fw_done, fw_pass, retired, txns, image_len) -> None:
        log = self.logger
        status_hex = [hex(v) for v in status_seq]
        log.info("cold_scratch[1] sequence: %s", status_hex)
        log.info("ROM console: %s", console)

        def index_of(marker: str) -> int:
            for i, line in enumerate(console):
                if marker in line:
                    return i
            return -1

        def count_of(marker: str) -> int:
            return sum(1 for line in console if marker in line)

        # A dark console or a core that never ran makes every check below vacuous.
        assert retired, "core retired no instructions; the ROM never ran"
        assert console, (
            "ROM console is empty, so no marker check below means anything (the "
            "virt console is DEBUG-build only -- check the ROM build)"
        )
        assert any(_SPI_PATH in line for line in console), (
            f"ROM never printed {_SPI_PATH}: it did not take the SPI branch, so "
            f"this run says nothing about flash addressing. Console: {console}"
        )
        assert not any(_SMC_PATH in line for line in console), (
            f"ROM printed {_SMC_PATH}: the manifest came from SMC SRAM, not SPI"
        )

        # A failed controller also reaches a terminal error, by skipping the
        # primary outright, without reading either address.
        assert any(_SPI_INIT_OK in line for line in console), (
            f"ROM never printed {_SPI_INIT_OK}: the SPI controller did not come "
            f"up, so the terminal error is a controller failure and not a "
            f"two-address no-detect. Console: {console}"
        )
        for marker in (_SPI_INIT_ERR, _SPI_INIT_FAILED_SKIP):
            assert not any(marker in line for line in console), (
                f"ROM printed {marker!r}: the backup was reached via the SPI-init "
                f"failure path, so no address decision was tested"
            )
        log.info("CHK-CONTROLLER-UP: %s, and neither init-failure path taken", _SPI_INIT_OK)

        # The count matters: one BAD_MAGIC would mean only one address was read.
        i_psrc = index_of(_PRIMARY_SRC)
        i_bsrc = index_of(_BACKUP_SRC)
        assert i_psrc >= 0, f"ROM never read {_PRIMARY_SRC}. Console: {console}"
        assert i_bsrc >= 0, f"ROM never read {_BACKUP_SRC}. Console: {console}"
        assert i_psrc < i_bsrc, (
            f"backup address (line {i_bsrc}) was read before the primary "
            f"(line {i_psrc}): the slot order is not primary-then-backup"
        )
        n_bad = count_of(_BAD_MAGIC_ERR)
        assert n_bad == 2, (
            f"expected exactly 2 {_BAD_MAGIC_ERR} rejections (one per address), "
            f"saw {n_bad}. Both addresses must be read and both must be rejected "
            f"for the reason this stimulus plants. Console: {console}"
        )
        log.info(
            "CHK-BOTH-ADDRESSES: primary@%d then backup@%d, %d x %s",
            i_psrc,
            i_bsrc,
            n_bad,
            _BAD_MAGIC_ERR,
        )

        # Without this, a run where the backup booted could still show the above.
        assert not any(_MANIFEST_OK in line for line in console), (
            f"ROM printed {_MANIFEST_OK}: a slot validated, so 'both addresses "
            f"no-detect' did not hold. Console: {console}"
        )

        i_all_failed = index_of(_ALL_FAILED)
        assert i_all_failed > i_bsrc, (
            f"{_ALL_FAILED} at line {i_all_failed} did not follow the backup "
            f"attempt at line {i_bsrc}. Console: {console}"
        )
        for want, what in (
            (_STATUS_LOOP_FAILED, "STATUS_ENCODE(ERROR, SEP_MSG_MANIFEST_LOAD_FAILED)"),
            (_STATUS_SLOT_REJECTED, "STATUS_ENCODE(ERROR, SEP_MSG_INVALID_MANIFEST_ID)"),
        ):
            assert want in status_seq, (
                f"cold_scratch[1] never held 0x{want:08x} ({what}); observed {status_hex}"
            )
        assert fw_done, (
            f"ROM never signalled completion within {_MAX_RUN_CYCLES} cycles; two "
            f"undetected addresses must converge on a mailbox FAIL and hang. "
            f"cold_scratch[1]: {status_hex}"
        )
        assert not fw_pass, "ROM signalled PASS with no valid manifest at either address"
        log.info(
            "CHK-TERMINAL PASS: %s after both rejections, cold_scratch[1] held "
            "0x%08x then 0x%08x, mailbox FAIL (fw_pass=0)",
            _ALL_FAILED,
            _STATUS_SLOT_REJECTED,
            _STATUS_LOOP_FAILED,
        )

        # Had the ROM continued -- retried, restarted, or reported further --
        # cold_scratch[1] would have moved off the terminal error. Read past the
        # ring-invalid writes: they carry no boot information and follow every
        # status, so the last one of them says nothing about where the ROM
        # stopped. The last status that does is what this asserts on.
        reported = [v for v in status_seq if v != _STATUS_RING_INVALID]
        assert reported and reported[-1] == _STATUS_LOOP_FAILED, (
            f"after {_HANG_OBSERVE_CYCLES} cycles past the mailbox FAIL, the last "
            f"status other than the ring-invalid report is "
            f"0x{(reported or [0])[-1]:08x}, not the terminal "
            f"0x{_STATUS_LOOP_FAILED:08x}: the ROM did not stay stopped. Full "
            f"status sequence: {status_hex}"
        )
        log.info(
            "CHK-HANG-HELD: last reported status still 0x%08x and fw_pass still 0 "
            "after %d cycles -- terminal, not transient",
            _STATUS_LOOP_FAILED,
            _HANG_OBSERVE_CYCLES,
        )

        for marker in _BOOT_PROGRESS:
            assert not any(marker in line for line in console), (
                f"ROM printed {marker}, which sits past the manifest stage: it "
                f"continued booting with no valid manifest. Console: {console}"
            )
        log.info("CHK-NO-BOOT: none of %s reached", ", ".join(_BOOT_PROGRESS))

        # Transport evidence the console cannot supply: both addresses really were
        # interrogated, in order, and both really answered blank.
        rds = ev.reads(txns)
        assert rds, (
            f"flash BFM served no read transactions; the ROM never addressed the "
            f"device. All {len(txns)} transactions: "
            f"{[hex(t['opcode']) for t in txns]}"
        )
        seen = {}
        for slot, base in (
            ("primary", mm.PRIMARY_MANIFEST_OFFSET),
            ("backup", mm.BACKUP_MANIFEST_OFFSET),
        ):
            hit = ev.covering_read(rds, base)
            assert hit is not None, (
                f"no SPI read covered the {slot} manifest address 0x{base:x}: that "
                f"address was never interrogated, so it was not shown undetected"
            )
            idx, txn = hit
            # Every returned byte, not just the magic: makes the device-side claim
            # independent of the stimulus self-check.
            data = bytes(txn["data_out"])
            assert ev.all_erased(data), (
                f"device returned non-erased bytes in the {len(data)}-byte read at "
                f"the {slot} address 0x{base:x} (first 16: {data[:16].hex()}), "
                f"expected all 0x{mm.ERASED_BYTE:02x}: that address was not blank, "
                f"so its rejection was not a no-detect"
            )
            seen[slot] = idx
        assert seen["primary"] < seen["backup"], (
            f"device served the backup address (read[{seen['backup']}]) before the "
            f"primary (read[{seen['primary']}])"
        )
        log.info(
            "CHK-DEVICE-BLANK: read[%d] 0x%06x and read[%d] 0x%06x both returned "
            "0x%02x -- one device, two addresses, both blank, in order",
            seen["primary"],
            mm.PRIMARY_MANIFEST_OFFSET,
            seen["backup"],
            mm.BACKUP_MANIFEST_OFFSET,
            mm.ERASED_BYTE,
        )
