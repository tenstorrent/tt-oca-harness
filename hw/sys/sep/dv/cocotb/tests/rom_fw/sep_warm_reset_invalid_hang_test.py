# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""TP006: an out-of-range warm-reset handler address must hang, not be jumped to.

The reject arm of the warm dispatch in ``bootrom/prod/src/vector.S``, and the
partner of ``sep_scratch_7_test``, which covers the accept arm::

    lw   t1, (SEP_COLD_SCRATCH_7)      # handler address
    beqz t1, cold_boot                 # zero -> COLD BOOT, not a hang
    bltu t1, WARM_HANDLER_RANGE_BASE, warm_reset_hang
    bgeu t1, WARM_HANDLER_RANGE_END, warm_reset_hang
    ... 0x01010068 -> cold_scratch[1], then jr t1              # accept
  warm_reset_hang:
    sw   0x0f010069, (SEP_COLD_SCRATCH_1)
    wfi, then spin

The accept arm leaves the slot INTACT, as the spec and the reference do.

HOW THIS ROM DIFFERS FROM THE PROCEDURE, WHICH CHANGES THE STIMULUS. Two of
TP006's statements do not hold against the OSS ROM, and a test built on them
would prove nothing:

  * *"a value clearly outside the valid ICCM range (e.g. 0x0, ...)"*. **Zero does
    not reach the hang.** The ``beqz`` immediately after the slot read sends it to
    ``cold_boot``, which is a silent normal boot. 0xFFFFFFFF does hang, but it is
    also the value ``cold_boot`` itself poisons the register with, so a run that
    never armed the handler would leave the same value behind and the evidence
    could not tell the two apart. This test therefore uses
    ``WARM_HANDLER_RANGE_END`` exactly -- the smallest address the upper bound
    rejects, which pins ``bgeu`` rather than ``bgtu``, and which the ROM never
    writes itself.
  * *"scratch 1 contains the ERROR: WARM_RESET_HANG string ... scratch 0 =
    0xdeadbeef ... via test_fail()"*. There is no string: the dispatch runs before
    the C runtime, so ``simputs()`` does not exist, and the whole record is the
    status WORD 0x0f010069 = STATUS_ENCODE(ERROR, SEP_MSG_WARM_RESET_HANG=0x69)
    (``status_values.h:83``). ``cold_scratch[0]`` is not written at all, and there
    is no ``test_fail()`` anywhere in this ROM -- ``0xDEADBEEF`` appears only as
    the mailbox ``ROM_FW_FAIL`` constant and on the early trap path.

WHAT THE STIMULUS IS, AND WHY IT IS NOT A BACKDOOR. The value is deposited into
cold_scratch[7] through ``+sep_cold_scratch7`` -- the same one-shot register
deposit ``sep_scratch_7_test`` uses for the accept arm, written through the CSR's
own storage and left writable so the ROM can still poison it. It is not a force
and it does not skip any ROM step. A real warm reset is not needed to reach this
path: the ROM's only evidence that a warm reset occurred is a non-zero in-range
value in the slot, so depositing one is exactly how the ROM is told a warm reset
happened.

THE CHECK THAT MAKES THIS NON-VACUOUS IS CHK-SEED. A deposit that does not survive
to the ROM's read leaves the slot at 0, which is the ``beqz`` early-out to a silent
cold boot -- and every "it did not jump anywhere" check below would then hold for
the wrong reason. The seed is therefore OBSERVED rather than assumed, and it is
asserted first and separately.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from env.sep_efuse_image import LC_TEST_DEV, SepEfuseImage
from env.sep_rom_console import log_scratch_cold, rom_console_task
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_SEP_ROOT = str(Path(__file__).resolve().parents[4])
# The dispatch is the first thing after MRAC setup, long before any transport is
# selected, so the SPI build variant is irrelevant; reuse the OT one rather than
# adding a firmware profile.
_FW_DIR = os.path.join(_SEP_ROOT, "bootrom", "prod", "build_ot")
_ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")

# WARM_HANDLER_RANGE_BASE / _END in vector.S, named by symbol rather than line.
# build/boot_rom.sym resolves WARM_HANDLER_RANGE_BASE to 0xC0000000 (SEP ICCM
# base) and WARM_HANDLER_RANGE_END to 0xC0040000 (ICCM base + size), the range
# sep-boot-flow.puml:45 specifies.
_RANGE_BASE = 0xC000_0000
_RANGE_END = 0xC004_0000
# The seeded handler: the smallest address the upper bound rejects. Must match
# +sep_cold_scratch7 in the testlist.
_INVALID_HANDLER = _RANGE_END

# cold_scratch[1] words, all from vector.S (by symbol).
_STATUS_WARM_HANG = 0x0F01_0069  # ERROR + SEP_MSG_WARM_RESET_HANG, warm_reset_hang
_STATUS_WARM_JUMP = 0x0101_0068  # INFO  + SEP_MSG_WARM_RESET_JUMP, accept arm
_STATUS_BOOTROM_START = 0x8001_0044
_STATUS_PRESTART_DONE = 0x8001_0056
# Written by cold_boot as the out-of-range poison, its first store. Seeing it means
# the dispatch fell through to a cold boot instead of hanging.
_COLD_POISON = 0xFFFF_FFFF

# The ROM has no C runtime on this path, so any console line at all means
# execution continued past the dispatch into cold_boot.
_MAX_RUN_CYCLES = 400_000
_PROGRESS_EVERY = 50_000
# Same halt shape as the MEM_REPAIR gate: `wfi; j back`, two instructions.
_QUIESCE_CYCLES = 2_000
_QUIESCE_PC_SPAN_MAX = 64


@pyuvm.test()
class sep_warm_reset_invalid_hang_test(sep_base_test):
    """Seed an out-of-range warm handler; the ROM must hang instead of jumping."""

    build_env = False
    rom_build_dir = _FW_DIR

    async def run_scenario(self) -> None:
        dut = cocotb.top

        # Guard the stimulus. Without the deposit the ROM reads cold_scratch[7] at
        # its reset value -- 0, the spec's "always 0 on cold resets" -- takes the
        # beqz early-out, and cold boots, and every check below would be describing
        # an ordinary boot.
        seeded = cocotb.plusargs.get("sep_cold_scratch7")
        assert seeded is not None, (
            "+sep_cold_scratch7 is not set: cold_scratch[7] would read 0, the ROM "
            "would take the beqz early-out to cold_boot, and no warm dispatch "
            "decision would be exercised at all"
        )
        assert int(str(seeded), 16) == _INVALID_HANDLER, (
            f"+sep_cold_scratch7={seeded} does not match the address this test "
            f"checks for (0x{_INVALID_HANDLER:08x})"
        )
        # Self-check the stimulus shape, so a future edit cannot turn it into a
        # value that reaches the hang for a different reason, or not at all.
        assert _INVALID_HANDLER != 0, (
            "a zero handler is the beqz early-out to cold_boot, not the reject arm"
        )
        assert not (_RANGE_BASE <= _INVALID_HANDLER < _RANGE_END), (
            f"0x{_INVALID_HANDLER:08x} is INSIDE "
            f"[0x{_RANGE_BASE:08x}, 0x{_RANGE_END:08x}) -- that is the accept arm"
        )
        assert _INVALID_HANDLER == _RANGE_END, (
            f"0x{_INVALID_HANDLER:08x} is not the boundary value; only "
            f"0x{_RANGE_END:08x} exactly distinguishes the ROM's `bgeu` from a "
            f"mistaken `bgtu`, which would accept the first out-of-range address"
        )
        assert _INVALID_HANDLER != _COLD_POISON, (
            f"the seed must differ from cold_boot's own poison "
            f"0x{_COLD_POISON:08x}, or a run that cold booted would leave the same "
            f"value in the register and CHK-SEED could not tell them apart"
        )
        self.logger.info(
            "CHK-STIMULUS-HANDLER: cold_scratch[7] seed = 0x%08x, the smallest "
            "address rejected by `bgeu handler, 0x%08x`",
            _INVALID_HANDLER,
            _RANGE_END,
        )

        efuse_img = SepEfuseImage()
        efuse_img.set_lc_state(LC_TEST_DEV)
        self.write_efuse_image(efuse_img)

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
        cold7_seq: list[int] = []
        last_status = None
        last_cold7 = None
        halted = False
        retired = 0
        last_log = 0
        for cycle in range(_MAX_RUN_CYCLES):
            await RisingEdge(dut.clk_i)
            status = (self.rd(dut.scratch_cold_probe_o) >> 32) & 0xFFFF_FFFF
            if status != last_status:
                last_status = status
                status_seq.append(status)
            cold7 = (self.rd(dut.scratch_cold_probe_o) >> 224) & 0xFFFF_FFFF
            if cold7 != last_cold7:
                last_cold7 = cold7
                cold7_seq.append(cold7)
            if self.rd(dut.cpu_trace_valid_o):
                retired += 1
            # No mailbox on this path, so no fw_done: the terminal status word is
            # the only completion signal, and it is the last thing the reject arm
            # writes before spinning.
            if status == _STATUS_WARM_HANG:
                halted = True
                self.logger.info("ROM hung on the warm reject arm at cycle %d", cycle)
                break
            if cycle - last_log >= _PROGRESS_EVERY:
                last_log = cycle
                self.logger.info(
                    "warm dispatch poll cyc=%d status=0x%08x cold7=0x%08x retired=%d",
                    cycle,
                    status,
                    cold7,
                    retired,
                )

        # Did it actually STOP? Same reasoning as the MEM_REPAIR gate's halt: the
        # spin keeps retiring, so volume proves nothing and PC LOCALITY is the
        # evidence. Code that continued into cold_boot would walk hundreds of
        # addresses.
        post_pcs: set[int] = set()
        post_status_moved = False
        if halted:
            for _ in range(_QUIESCE_CYCLES):
                await RisingEdge(dut.clk_i)
                if self.rd(dut.cpu_trace_valid_o):
                    # cpu_trace_addr_o is already a byte PC (tb_top.sv drives it
                    # from trace_rv_i_address_ip); do not shift it. The spin is the
                    # `wfi; j` pair under the `warm_reset_hang` label in
                    # build_ot/boot_rom.dis, and `cold_boot` is the very next
                    # instruction, so check the addresses against the label in the
                    # .dis, not by eye.
                    post_pcs.add(self.rd(dut.cpu_trace_addr_o))
                if ((self.rd(dut.scratch_cold_probe_o) >> 32) & 0xFFFF_FFFF) != _STATUS_WARM_HANG:
                    post_status_moved = True
        post_span = (max(post_pcs) - min(post_pcs)) if post_pcs else 0

        log_scratch_cold(self.logger)
        status_hex = [hex(v) for v in status_seq]
        cold7_hex = [hex(v) for v in cold7_seq]
        self.logger.info("cold_scratch[1] sequence: %s", status_hex)
        self.logger.info("cold_scratch[7] sequence: %s", cold7_hex)
        self.logger.info("ROM console: %s", console)

        # Guard the guard: on this path the console is legitimately empty, so
        # retirement is the only available liveness evidence.
        assert retired, "core retired no instructions; the ROM never ran"

        # CHK-SEED: the deposit reached the register the ROM reads. Everything
        # below is vacuous without it -- a wiped deposit means the ROM read 0 and
        # cold booted, which satisfies every absence check for the wrong reason.
        assert _INVALID_HANDLER in cold7_seq, (
            f"cold_scratch[7] never held the seeded handler address "
            f"0x{_INVALID_HANDLER:08x}; observed {cold7_hex}. The tb deposit did "
            f"not take, so this run says nothing about the warm dispatch"
        )
        self.logger.info("CHK-SEED: cold_scratch[7] held 0x%08x", _INVALID_HANDLER)

        # CHK-WARM-REJECT: the range check rejected it and said so.
        assert _STATUS_WARM_HANG in status_seq, (
            f"cold_scratch[1] never held 0x{_STATUS_WARM_HANG:08x} "
            f"(STATUS_ENCODE(ERROR, SEP_MSG_WARM_RESET_HANG)); observed "
            f"{status_hex}"
        )
        assert halted, (
            f"cold_scratch[1] never reached 0x{_STATUS_WARM_HANG:08x} within "
            f"{_MAX_RUN_CYCLES} cycles; observed {status_hex}"
        )
        self.logger.info("CHK-WARM-REJECT PASS: cold_scratch[1] = 0x%08x", _STATUS_WARM_HANG)

        # CHK-NO-JUMP: the accept arm did not run. Two independent witnesses,
        # because either alone is weak: the ROM announces the jump in
        # cold_scratch[1] BEFORE transferring control. The procedure's "no jump to
        # the invalid scratch-7 address is observed" is exactly this.
        assert _STATUS_WARM_JUMP not in status_seq, (
            f"cold_scratch[1] held 0x{_STATUS_WARM_JUMP:08x} "
            f"(SEP_MSG_WARM_RESET_JUMP): the ROM accepted an out-of-range handler "
            f"and jumped to it. Observed {status_hex}"
        )
        self.logger.info(
            "CHK-NO-JUMP: 0x%08x absent from cold_scratch[1]",
            _STATUS_WARM_JUMP,
        )

        # CHK-NO-COLD-FALLTHROUGH: it did not quietly fall into a normal boot
        # either. The reject arm sits ABOVE cold_boot and both of these words are
        # written after it, so their absence places execution on the hang.
        # cold_scratch[7] never taking cold_boot's -1 poison is the independent
        # second witness, written by a different instruction in a different block.
        for word, name in (
            (_STATUS_BOOTROM_START, "BOOTROM_START"),
            (_STATUS_PRESTART_DONE, "BOOTROM_PRESTART_DONE"),
        ):
            assert word not in status_seq, (
                f"cold_scratch[1] held 0x{word:08x} ({name}), which cold_boot "
                f"writes: the ROM fell through the dispatch into a normal boot "
                f"instead of hanging. Observed {status_hex}"
            )
        assert _COLD_POISON not in cold7_seq, (
            f"cold_scratch[7] held cold_boot's poison 0x{_COLD_POISON:08x} "
            f"({cold7_hex}): execution reached cold_boot"
        )
        self.logger.info(
            "CHK-NO-COLD-FALLTHROUGH: no cold_boot status word and no 0x%08x poison", _COLD_POISON
        )

        # CHK-PRE-C: the dispatch stopped the ROM before the C runtime, which is
        # what keeps BL1's DCCM state intact across a warm reset. A silent console
        # proves it, because the virtual console is simputs() and simputs() needs C.
        assert not console, (
            f"ROM printed {console}; the warm dispatch runs before the C runtime, "
            f"so any console output means execution continued into cold_boot"
        )
        self.logger.info("CHK-PRE-C: console silent, so the hang preceded C")

        # CHK-HANG: it really stopped, rather than passing through the status word.
        assert not post_status_moved, (
            f"cold_scratch[1] moved on from 0x{_STATUS_WARM_HANG:08x} within "
            f"{_QUIESCE_CYCLES} cycles: the ROM reported the reject and carried on"
        )
        assert post_pcs, (
            f"core retired nothing in the {_QUIESCE_CYCLES} cycles after the "
            f"terminal status; expected the `wfi; j` spin, so either the trace "
            f"probe is dead or the core stopped in a way the ROM does not do"
        )
        assert post_span <= _QUIESCE_PC_SPAN_MAX, (
            f"after the terminal status the PC covered {post_span} bytes across "
            f"{len(post_pcs)} addresses ({[hex(p) for p in sorted(post_pcs)]}); a "
            f"hung ROM spins inside {_QUIESCE_PC_SPAN_MAX} bytes, so this one "
            f"reported the reject and then carried on executing"
        )
        self.logger.info(
            "CHK-HANG: cold_scratch[1] held 0x%08x while the PC spun across %d "
            "byte(s) at %s for %d cycles",
            _STATUS_WARM_HANG,
            post_span,
            [hex(p) for p in sorted(post_pcs)],
            _QUIESCE_CYCLES,
        )
