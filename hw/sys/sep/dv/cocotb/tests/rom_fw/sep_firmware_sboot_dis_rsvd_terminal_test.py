# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SBOOT_DIS reserved bits are a fuse-integrity fault, not a chicken bit.

``SBOOT_DIS`` is ``disable_secure_boot[0]`` plus ``rsvd[31:1]``, and ``rsvd`` is ``hw=rw`` in
``sep_efuse_map.rdl``, so a real part can present a non-zero word without the chicken bit blown.
[S18] masks to bit 0 and treats a non-zero ``rsvd`` as a fuse-integrity fault that stops the boot
(``rom_sboot_dis_policy()`` in ``bootrom/prod/src/lifecycle.c``, SEP-ROM-SB-041). This run
presents PROD with word ``0x00000002``: reserved bit 0 set, chicken bit clear. The ROM must print
``SBOOT_DIS_RSVD=`` and halt on ``ROM_ERR_SBOOT_DIS_RSVD_SET``. PROD makes the two answers differ:
under TEST_DEV the lifecycle alone does not enforce secure boot.

Not pinned: the bit-0 masking is not independently observable, because the fault stops the boot
before a manifest is read. ``FUSE: SBOOT_DIS:`` is forbidden: [S18] prints the masked value only
after the integrity check passes.

The run ends in a halt, so ``SepBootScoreboard`` is not used; the verdict is the ROM's
cold_scratch[0] FAIL, then a spin. No SPI flash is attached: [S18] precedes boot-mode selection
and SPI bring-up ([S21]), and entropy bring-up is lazy (``oca_platform.c`` ``ENTROPY_PREREQ()``).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from env.sep_rom_console import log_scratch_cold, rom_console_task
from env.sep_verdict import decode_verdict
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_SEP_ROOT = str(Path(__file__).resolve().parents[4])
# [S18] runs before any manifest transport is chosen, so the default ROM build suffices.
_FW_DIR = os.path.join(_SEP_ROOT, "bootrom", "prod", "build")
_ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod_sboot_dis_rsvd.toml"
)

# The word the preload emits: rsvd[0] set (register bit 1), disable_secure_boot
# clear. Asserted against the image rather than assumed, so a preload edit that
# moved the bit fails here instead of quietly testing the chicken bit.
_SBOOT_DIS_WORD = 0x0000_0002

# cold_scratch[1] words, in the order [S18] emits them. Both must match what
# report_status()/rom_err_fail() encode, and must stay in step with them:
#   ERROR + SEP_MSG_FUSE_SBOOT_DIS_RSVD (0x227)   -> 0x0f << 24 | 0x01 << 16 | 0x227
#   ERROR + ROM_ERR_SBOOT_DIS_RSVD_SET  (0xF008)  -> 0x0f << 24 | 0x01 << 16 | 0xF008
# SEP_STATUS_ID is 1 for BL0.
_SEP_MSG_FUSE_SBOOT_DIS_RSVD = 0x227
_STATUS_RSVD_DETECTED = 0x0F01_0000 | _SEP_MSG_FUSE_SBOOT_DIS_RSVD
_ROM_ERR_SBOOT_DIS_RSVD_SET = 0xF008
_STATUS_TERMINAL = 0x0F01_0000 | _ROM_ERR_SBOOT_DIS_RSVD_SET

# Must appear: the fault marker, and the lifecycle that makes it meaningful.
_RSVD_MARKER = "SBOOT_DIS_RSVD="
_LC_PROD = "LC=PROD"

# Must NOT appear. The first is [S18]'s own value print, emitted only once the
# integrity check has passed; the rest sit downstream of [S18] entirely.
_FUSE_VALUE_PRINT = "FUSE: SBOOT_DIS:"
_SBOOT_OFF = "SBOOT_OFF"
_DOWNSTREAM_MARKERS = ("MANIFEST_OK", "BL1_COPIED", "PRE_JUMP", "BL1_JUMP=")

# [S18] sits after the ROM self-hash ([S17]), which is the expensive part of the
# run at ~33 KB through the HMAC engine, and before any RSA work. Generous
# against that, and two orders of magnitude below the budget the crypto-path
# terminal tests use.
_MAX_RUN_CYCLES = 6_000_000
_PROGRESS_EVERY = 500_000

# How long to watch after the terminal verdict before believing the ROM halted.
# rom_err_fail() writes cold_scratch[1], then the cold_scratch[0] verdict, and
# only then enters `for(;;) wfi` -- a ROM that reported and carried on would
# write that verdict at the same instant, so the verdict alone does not say it
# stopped. Matches the window the other rom_fw terminal tests use.
_QUIESCE_CYCLES = 20_000


@pyuvm.test()
class sep_firmware_sboot_dis_rsvd_terminal_test(sep_base_test):
    """PROD + SBOOT_DIS.rsvd set: the ROM must stop, not read it as the chicken bit."""

    build_env = False
    rom_build_dir = _FW_DIR

    async def run_scenario(self) -> None:
        dut = cocotb.top

        assert os.path.isfile(_EFUSE_PRELOAD), f"eFuse preload missing: {_EFUSE_PRELOAD}"
        image = self.select_efuse_image(default_preload=_EFUSE_PRELOAD)

        # Guard the stimulus. select_efuse_image() falls back to a seeded random
        # image when the plusarg is absent, and a random image would almost
        # certainly sense TEST_DEV with an all-zero SBOOT_DIS -- an ordinary boot
        # that reaches none of the checks below.
        lc = image.lc_raw()
        sboot_word = image.field_int("SBOOT_DIS")
        assert lc == 0x1, (
            f"LC_STATE raw is 0x{lc:x}, expected 0x1 (PROD): the testlist must pass "
            f"+sep_efuse_preload={_EFUSE_PRELOAD}"
        )
        assert sboot_word == _SBOOT_DIS_WORD, (
            f"SBOOT_DIS is 0x{sboot_word:08x}, expected 0x{_SBOOT_DIS_WORD:08x} "
            f"(rsvd bit 0 set, disable_secure_boot clear)"
        )
        assert sboot_word & 0x1 == 0, (
            "disable_secure_boot is set, so the ROM would be entitled to disable "
            "secure boot and this run would say nothing about the reserved bits"
        )
        self.write_efuse_image(image)
        self.logger.info(
            "CHK-SBOOT-RSVD-STIMULUS PASS: OTP LC raw=0x%x (PROD), SBOOT_DIS=0x%08x",
            lc,
            sboot_word,
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

        await self.bring_up_cpu_boot(
            _ROM_BASE >> 1,
            pre_reset_hook=_load_tcm,
            run_pulse_cycles=40,
        )

        status_seq: list[int] = []
        last_status = None
        fw_done = False
        fw_pass = 0
        retired = 0
        last_log = 0
        post_status_moved = False
        post_console: list[str] = []
        for cycle in range(_MAX_RUN_CYCLES):
            await RisingEdge(dut.clk_i)
            probe = self.rd(dut.scratch_cold_probe_o)
            status = (probe >> 32) & 0xFFFF_FFFF
            if status != last_status:
                last_status = status
                status_seq.append(status)
            if self.rd(dut.cpu_trace_valid_o):
                retired += 1
            verdict = decode_verdict(probe)
            if verdict is not None:
                fw_done = True
                fw_pass = verdict[1]
                self.logger.info(
                    "ROM signalled completion at cycle %d via cold_scratch[0], pass=%d",
                    cycle,
                    fw_pass,
                )
                break
            if cycle - last_log >= _PROGRESS_EVERY:
                last_log = cycle
                self.logger.info(
                    "sboot rsvd poll cyc=%d status=0x%08x retired=%d lines=%d",
                    cycle,
                    status,
                    retired,
                    len(console),
                )

        if fw_done:
            console_len_at_done = len(console)
            for _ in range(_QUIESCE_CYCLES):
                await RisingEdge(dut.clk_i)
                probe = self.rd(dut.scratch_cold_probe_o)
                if ((probe >> 32) & 0xFFFF_FFFF) != last_status:
                    post_status_moved = True
                    break
            post_console = console[console_len_at_done:]

        log_scratch_cold(self.logger)
        status_hex = [hex(v) for v in status_seq]
        self.logger.info("cold_scratch[1] sequence: %s", status_hex)
        self.logger.info("ROM console: %s", console)

        # Liveness. Without it every absence check below is vacuously true.
        assert retired, "core retired no instructions; the ROM never ran"
        assert any(_LC_PROD in line for line in console), (
            f"ROM never printed {_LC_PROD}: the run did not sense the PROD "
            f"lifecycle this testcase depends on. Console: {console}"
        )

        # CHK-SBOOT-RSVD-DETECT: [S18] classified the word as a fuse-integrity
        # fault and said so. The marker carries the raw word, which is the
        # evidence that the ROM read our preload rather than a blank shadow.
        assert any(_RSVD_MARKER in line for line in console), (
            f"ROM never printed {_RSVD_MARKER}: [S18] did not treat the reserved "
            f"bit as a fault. Console: {console}"
        )
        assert any(f"{_RSVD_MARKER}0x{_SBOOT_DIS_WORD:08x}" in line for line in console), (
            f"{_RSVD_MARKER} did not carry 0x{_SBOOT_DIS_WORD:08x}; the ROM read a "
            f"different word than the preload staged. Console: {console}"
        )
        assert _STATUS_RSVD_DETECTED in status_seq, (
            f"cold_scratch[1] never held 0x{_STATUS_RSVD_DETECTED:08x} "
            f"(ERROR + SEP_MSG_FUSE_SBOOT_DIS_RSVD); observed {status_hex}"
        )
        self.logger.info(
            "CHK-SBOOT-RSVD-DETECT PASS: %s0x%08x, cold_scratch[1]=0x%08x",
            _RSVD_MARKER,
            _SBOOT_DIS_WORD,
            _STATUS_RSVD_DETECTED,
        )

        # CHK-SBOOT-RSVD-NOT-CHICKEN: the ROM did not interpret the word. The
        # value print happens only after the integrity check passes, so its
        # absence says the boot stopped at the check; SBOOT_OFF would say the
        # reserved bit had been read as the chicken bit, which is the defect.
        assert not any(_FUSE_VALUE_PRINT in line for line in console), (
            f"ROM printed {_FUSE_VALUE_PRINT}, so it interpreted a SBOOT_DIS word "
            f"it should have rejected. Console: {console}"
        )
        assert not any(_SBOOT_OFF in line for line in console), (
            f"ROM printed {_SBOOT_OFF}: a reserved bit was taken as the secure-boot "
            f"chicken bit. Console: {console}"
        )
        self.logger.info(
            "CHK-SBOOT-RSVD-NOT-CHICKEN PASS: neither %s nor %s reached",
            _FUSE_VALUE_PRINT,
            _SBOOT_OFF,
        )

        # CHK-SBOOT-RSVD-TERMINAL: the error code, and a halt rather than a boot.
        # The status word says why it stopped; the quiescence window says it
        # really stopped instead of reporting and carrying on.
        assert fw_done, (
            f"ROM never signalled completion within {_MAX_RUN_CYCLES} cycles; "
            f"cold_scratch[1] observed {status_hex}"
        )
        assert not fw_pass, "ROM signalled PASS: it booted on a fuse word it should have refused"
        assert _STATUS_TERMINAL in status_seq, (
            f"cold_scratch[1] never held 0x{_STATUS_TERMINAL:08x} "
            f"(ERROR + ROM_ERR_SBOOT_DIS_RSVD_SET); observed {status_hex}"
        )
        assert status_seq.index(_STATUS_RSVD_DETECTED) < status_seq.index(_STATUS_TERMINAL), (
            f"the terminal code preceded the detection code in {status_hex}: [S18] "
            f"did not reach the fault through the reserved-bit check"
        )
        assert not post_status_moved, (
            "cold_scratch[1] moved on after the terminal code, so the ROM reported "
            "the fault and then continued instead of halting"
        )
        assert not post_console, (
            f"ROM kept printing after the terminal code, so it did not halt: {post_console}"
        )
        self.logger.info(
            "CHK-SBOOT-RSVD-TERMINAL PASS: cold_scratch[1]=0x%08x, cold_scratch[0] FAIL "
            "(fw_pass=0), quiet for %d cycles",
            _STATUS_TERMINAL,
            _QUIESCE_CYCLES,
        )

        # CHK-SBOOT-RSVD-NO-PROGRESS: nothing downstream of [S18] ran.
        for marker in _DOWNSTREAM_MARKERS:
            assert not any(marker in line for line in console), (
                f"ROM printed {marker}, which sits downstream of [S18]: it continued "
                f"booting past a fault it was supposed to stop on. Console: {console}"
            )
        self.logger.info(
            "CHK-SBOOT-RSVD-NO-PROGRESS PASS: none of %s reached",
            ", ".join(_DOWNSTREAM_MARKERS),
        )
