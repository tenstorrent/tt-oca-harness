# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP Boot ROM warm-reset handler dispatch (PyUVM).

FEATURE UNDER TEST. The first decision the Boot ROM makes, before it touches DCCM
or any fuse: read the warm-reset handler slot, and if it is non-zero and inside the
legal window, announce the decision and transfer control there instead of
cold-booting. ``bootrom/prod/src/vector.S``::

    li   t0, SEP_COLD_SCRATCH_7
    lw   t1, 0(t0)                 # handler address
    beqz t1, cold_boot             # zero -> cold boot
    bltu t1, WARM_HANDLER_RANGE_BASE, warm_reset_hang
    bgeu t1, WARM_HANDLER_RANGE_END, warm_reset_hang
    <status: WARM_RESET_JUMP>
    jr   t1                        # slot left intact, see below

This covers the accept-and-jump arm only. The reject arm's UPPER bound (``bgeu``)
is ``sep_warm_reset_invalid_hang_test`` (seeds ``WARM_HANDLER_RANGE_END``), its
LOWER bound (``bltu``) is ``sep_warm_reset_below_range_hang_test``, and the
``beqz`` early-out to ``cold_boot`` is ``sep_warm_reset_unarmed_cold_boot_test``.

COLD SCRATCH 7, AND ICCM. The ROM reads ``cold_scratch[7]`` and range-checks
against SEP ICCM [0xC0000000, 0xC0040000), matching ``sep-boot-flow.puml:42-56``.
The spec picks the COLD bank for a reason it states outright: that register
"maintains value across warm/watchdog resets", which is the entire point of a
handler address that has to survive the reset it is dispatching from. The warm
bank does not retain -- its ``arst_n = sep_reset_n & wdt_rst_ni`` -- so a handler
parked there would be wiped by the very reset it should survive.

WHY THE JUMP TARGET IS A REAL INSTRUCTION. Seeding an in-range address that holds
garbage and keying off the resulting exception does not work here: this ROM's
``trap_vector`` dereferences ``sp``, and ``sp`` is only set up in ``cold_boot``, so
on the warm path a trap would run with an uninitialised stack pointer and destroy
the observation. The target therefore holds one ``j .`` instruction, written into
ICCM by ``+sep_iccm_word`` with ECC computed by the testbench, and the evidence is
the retired PC, which proves control reached exactly the seeded address rather
than merely that some exception occurred. ICCM carries SECDED, so a raw write
would read back as an ECC error rather than an instruction -- which is why this
needs a dedicated ECC-aware poke.

``SepBootScoreboard`` requires ``fw_done`` plus ``fw_pass``; the warm handler never
writes the mailbox, so a passing warm dispatch would be scored as a failure. The
checks below replace it.
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
# Same ROM build as the OT boot tests, so this test adds no new firmware profile.
# The warm branch is upstream of every transport decision, so which SPI variant
# the ROM was built with cannot matter here.
_FW_DIR = os.path.join(_SEP_ROOT, "bootrom", "prod", "build_ot")

_ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")

# The ROM's accept window, from the generated register header rather than from
# literals -- these are the same two symbols vector.S builds
# WARM_HANDLER_RANGE_BASE/END from, so the test cannot drift from the ROM.
_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
_ICCM_END = _ICCM_BASE + sym("SEP_ICCM_MEM_SIZE")

# Handler entry, and the value seeded into cold_scratch[7]. Offset
# from the ICCM base so "the ROM used the scratch value" and "the ROM used the
# range base" are distinguishable outcomes.
#
# See the module docstring for why this is ICCM and cold scratch 7.
_HANDLER_OFFSET = 0x100
_HANDLER_ADDR = _ICCM_BASE + _HANDLER_OFFSET
# `j .` -- jump to self. The PC settling here is the evidence of dispatch.
_HANDLER_INSN = 0x0000_006F

# cold_scratch[1] status words, as the ROM encodes them (include/errors.h:
# STATUS_ENCODE(type, value) = type<<24 | SEP_STATUS_ID<<16 | value, and
# SEP_STATUS_ID is 1 for BL0).
#   STATUS_TYPE_INFO(0x01)  + SEP_MSG_WARM_RESET_JUMP(0x68)
_STATUS_WARM_RESET_JUMP = 0x0101_0068
# cold_boot's out-of-range poison for the handler slot (vector.S). Only cold_boot
# writes it, so its ABSENCE is what proves the warm path was taken.
_COLD_POISON = 0xFFFF_FFFF

# Fuse sense is not skipped (see run_scenario), and the core is held until it
# completes, so the budget has to cover it. The first ROM console line lands
# around 50k cycles; the warm branch is earlier still.
_MAX_RUN_CYCLES = 400_000
_PROGRESS_EVERY = 50_000


@pyuvm.test()
class sep_scratch_7_test(sep_base_test):
    """Seed the warm handler slot, boot the ROM, and prove it jumped there."""

    build_env = False
    rom_build_dir = _FW_DIR

    async def run_scenario(self) -> None:
        dut = cocotb.top

        # Guard the stimulus itself. The seed and the ICCM word arrive as
        # plusargs from the testlist, and a typo in either would leave the ROM
        # cold-booting -- which without this check reads as "the feature is
        # broken" instead of "the test was not set up".
        seeded = cocotb.plusargs.get("sep_cold_scratch7")
        assert seeded is not None, (
            "+sep_cold_scratch7 is not set: the testlist must seed the warm handler "
            "slot or this test proves nothing about the warm path"
        )
        assert int(str(seeded), 16) == _HANDLER_ADDR, (
            f"+sep_cold_scratch7={seeded} does not match the address this test "
            f"expects (0x{_HANDLER_ADDR:08x}); the ICCM poke puts the "
            f"handler instruction only at that address"
        )
        assert _ICCM_BASE <= _HANDLER_ADDR < _ICCM_END, (
            f"handler address 0x{_HANDLER_ADDR:08x} is outside the ROM's "
            f"accept window [0x{_ICCM_BASE:08x}, 0x{_ICCM_END:08x}) -- this test "
            f"would then be exercising the reject arm, which is a different item"
        )

        # Real fuse sense, not bypassed. The warm branch itself reads no fuse, but
        # the core is not released until sense completes, so the sequencing is part
        # of the scenario rather than incidental.
        efuse_img = SepEfuseImage()
        efuse_img.set_lc_state(LC_TEST_DEV)
        self.write_efuse_image(efuse_img)

        console: list[str] = []
        cocotb.start_soon(rom_console_task(self.logger, sink=console))

        # Stage the ROM's TCM images the same way the OT boot tests do; the
        # responder loads them on the tcm_load_i pulse below.
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

        # The sampler has to be running BEFORE reset is released. The transient
        # fact this test depends on -- the seed being visible in cold_scratch[7]
        # while the ROM reads it -- occurs inside bring_up_cpu_boot, so sampling
        # afterwards would race it away. The slot's retention is asserted by
        # CHK-RETAINED after the run rather than caught in flight.
        obs = _WarmDispatchObserver(self)
        sampler = cocotb.start_soon(obs.run(dut))
        await self.bring_up_cpu_boot(
            _ROM_BASE >> 1,
            pre_reset_hook=_load_tcm,
            run_pulse_cycles=40,
        )
        await sampler
        log_scratch_cold(self.logger)

        obs.check(self.logger, console)


class _WarmDispatchObserver:
    """Records the warm-dispatch observables for the whole run.

    Kept as a class so the sampling loop and the checks live next to each other,
    and so the checks read against recorded *sequences* rather than end-of-run
    snapshots -- the seed's arrival is transient.
    """

    def __init__(self, test: sep_base_test) -> None:
        self._test = test
        # Change-only sequences, so a value that appears and is overwritten is
        # still evidence. An end-state read cannot see the seed at all.
        self.cold7_seq: list[int] = []
        self.status_seq: list[int] = []
        self.pcs: set[int] = set()
        self.retired = 0

    async def run(self, dut) -> None:
        rd = self._test.rd
        log = self._test.logger
        last_cold7 = None
        last_status = None
        last_log = 0
        for cycle in range(_MAX_RUN_CYCLES):
            await RisingEdge(dut.clk_i)
            cold7 = (rd(dut.scratch_cold_probe_o) >> 224) & 0xFFFF_FFFF
            if cold7 != last_cold7:
                last_cold7 = cold7
                self.cold7_seq.append(cold7)
            status = (rd(dut.scratch_cold_probe_o) >> 32) & 0xFFFF_FFFF
            if status != last_status:
                last_status = status
                self.status_seq.append(status)
            if rd(dut.cpu_trace_valid_o):
                self.retired += 1
                self.pcs.add(rd(dut.cpu_trace_addr_o) & 0xFFFF_FFFF)
            # Stop as soon as every positive fact is in hand. Not an early PASS:
            # the negative checks are evaluated over what was recorded, and the
            # forbidden cold-boot status can only be written before the jump --
            # i.e. it would already be in status_seq if it had happened.
            # The slot's value is not a stop term: the accept arm leaves it intact,
            # so such a term would never fire, the sampler would run its whole
            # budget, and post-jump execution would pollute the sequences asserted
            # below. The retention check lives after the loop.
            if _STATUS_WARM_RESET_JUMP in self.status_seq and _HANDLER_ADDR in self.pcs:
                log.info("warm dispatch observed at cycle %d; stopping sampler", cycle)
                return
            if cycle - last_log >= _PROGRESS_EVERY:
                last_log = cycle
                log.info(
                    "warm dispatch poll cyc=%d cold7=0x%08x status=0x%08x retired=%d pcs=%d",
                    cycle,
                    cold7,
                    status,
                    self.retired,
                    len(self.pcs),
                )
        log.info(
            "sampler ran out at %d cycles: cold7_seq=%s status_seq=%s retired=%d",
            _MAX_RUN_CYCLES,
            [hex(v) for v in self.cold7_seq],
            [hex(v) for v in self.status_seq],
            self.retired,
        )

    def check(self, log, console: list[str]) -> None:
        cold7_hex = [hex(v) for v in self.cold7_seq]
        status_hex = [hex(v) for v in self.status_seq]
        log.info("cold_scratch[7] sequence: %s", cold7_hex)
        log.info("cold_scratch[1] sequence: %s", status_hex)
        log.info("retired=%d distinct PCs=%d", self.retired, len(self.pcs))

        # CHK-SEED: the stimulus actually reached the DUT. Without this, every
        # check below could pass vacuously on a run where the deposit no-oped
        # (e.g. the Verilator public-scope entry missing) because a zero slot
        # means cold boot, and cold boot also retires instructions.
        assert _HANDLER_ADDR in self.cold7_seq, (
            f"cold_scratch[7] never held the seeded handler address "
            f"0x{_HANDLER_ADDR:08x}; observed {cold7_hex}. The tb deposit did "
            f"not take, so this run says nothing about the warm path"
        )
        log.info("CHK-COLD7-SEED PASS: cold_scratch[7] held 0x%08x", _HANDLER_ADDR)

        # CHK-ANNOUNCE: the ROM took the accept arm and said so before leaving.
        assert _STATUS_WARM_RESET_JUMP in self.status_seq, (
            f"ROM never wrote WARM_RESET_JUMP (0x{_STATUS_WARM_RESET_JUMP:08x}) to "
            f"cold_scratch[1]; observed {status_hex}"
        )
        log.info(
            "CHK-WARM-ANNOUNCE: cold_scratch[1] = 0x%08x (WARM_RESET_JUMP)",
            _STATUS_WARM_RESET_JUMP,
        )

        # CHK-JUMP: control reached exactly the seeded address. This is the check
        # that the address came from the scratch register and not from anywhere
        # else -- the ICCM base and the ROM base would both fail it.
        assert _HANDLER_ADDR in self.pcs, (
            f"no instruction retired at the handler address "
            f"0x{_HANDLER_ADDR:08x}; the ROM announced the jump but control "
            f"did not arrive there. Distinct PCs seen: "
            f"{sorted(hex(p) for p in self.pcs)[:32]}"
        )
        log.info("CHK-WARM-JUMP PASS: retired at 0x%08x", _HANDLER_ADDR)

        # CHK-RETAINED: the slot is left ALONE, as the spec asks.
        # sep-boot-flow.puml:46-48 branches to the address and writes nothing;
        # the reference's vector.S does the same. Persistence is the point of a
        # watchdog handler slot: BL1 parks its re-entry address here before arming
        # the watchdog, so the SECOND watchdog reset has to reach the handler too.
        # Poisoning it to 0 would silently disarm recovery after the first dispatch.
        assert self.cold7_seq[-1] == _HANDLER_ADDR, (
            f"cold_scratch[7] ended at {hex(self.cold7_seq[-1])} rather than the "
            f"seeded handler address 0x{_HANDLER_ADDR:08x}. The ROM must leave the "
            f"slot intact on the accept path -- clearing it would disarm watchdog "
            f"recovery from the second reset onward. Sequence: {cold7_hex}"
        )
        log.info(
            "CHK-WARM-RETAINED: cold_scratch[7] left at 0x%08x for the next watchdog reset",
            _HANDLER_ADDR,
        )

        # CHK-NO-COLD: the negative half of the dispatch -- proof the ROM did not
        # simply fall through to cold_boot.
        #
        # NOT KEYED ON BOOTROM_START: sep-boot-flow.puml:40 puts BOOTROM_START
        # BEFORE the scratch-7 decision, so a spec-correct ROM emits it on the warm
        # path too, and keying on its absence would lock this test to a ROM that
        # writes it inside cold_boot.
        #
        # The two witnesses below hold either way. cold_boot's
        # 0xFFFFFFFF write to the slot is unconditional on that path and cannot be
        # confused with anything the warm path does, and console output stays a
        # cold-boot-only signal because every simputs call is downstream of the C
        # runtime, which the warm path never reaches.
        assert _COLD_POISON not in self.cold7_seq, (
            f"cold_scratch[7] took cold_boot's out-of-range poison "
            f"0x{_COLD_POISON:08x}: the ROM fell through to cold_boot instead of "
            f"dispatching to the warm handler. Sequence: {cold7_hex}"
        )
        assert not console, (
            f"ROM produced console output, which only happens on the cold-boot "
            f"path (every simputs call sits downstream of cold_boot): {console}"
        )
        log.info(
            "CHK-WARM-NO-COLD: cold_boot's 0x%08x poison never appeared and "
            "no cold-path console output",
            _COLD_POISON,
        )
