# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared scaffolding for the warm-reset dispatch legs of ``vector.S``.

``vector.S`` reads ``cold_scratch[7]`` before it touches DCCM or any fuse and takes one
of four legs:

* A: zero -> ``cold_boot``;
* B: below ``WARM_HANDLER_ICCM_BASE`` and outside the SEP SRAM window -> ``warm_reset_hang``;
* C: at or above ``WARM_HANDLER_ICCM_END`` -> ``warm_reset_hang``;
* D: inside a permitted window -> status ``WARM_RESET_JUMP``, then ``jr t1``.

Subclasses cover leg B (``sep_warm_reset_below_range_hang_test``), leg A
(``sep_warm_reset_unarmed_cold_boot_test``) and leg D into a non-instruction
(``sep_warm_reset_bad_target_exception_test``). ``sep_warm_reset_invalid_hang_test``
(leg C) and ``sep_scratch_7_test`` (leg D) do not use this base.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import cocotb
from cocotb.triggers import RisingEdge
from env.sep_efuse_image import LC_TEST_DEV, SepEfuseImage
from env.sep_rom_console import log_scratch_cold, rom_console_task
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_SEP_ROOT = str(Path(__file__).resolve().parents[4])
# The dispatch runs before any transport is selected, so the SPI build variant
# is irrelevant.
_FW_DIR = os.path.join(_SEP_ROOT, "bootrom", "prod", "build")
_ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")

# These bounds must match WARM_HANDLER_ICCM_BASE and WARM_HANDLER_ICCM_END in
# vector.S.
RANGE_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
RANGE_END = RANGE_BASE + sym("SEP_ICCM_MEM_SIZE")

# cold_scratch[1] status words, all from vector.S / status_values.h.
STATUS_WARM_HANG = 0x0F01_0069  # ERROR + SEP_MSG_WARM_RESET_HANG
STATUS_WARM_JUMP = 0x0101_0068  # INFO  + SEP_MSG_WARM_RESET_JUMP
STATUS_GENERAL_EXCEPTION = 0x0F01_0028  # ERROR + SEP_MSG_GENERAL_EXCEPTION
STATUS_BOOTROM_START = 0x8001_0044
STATUS_PRESTART_DONE = 0x8001_0056

# cold_scratch[0] terminal verdict written by trap_vector_early, and by every C
# failure path through errors.h.
VERDICT_FAIL = 0xDEAD_BEEF

# Written by cold_boot over cold_scratch[7] as its first store.
COLD_POISON = 0xFFFF_FFFF

# Same halt shape as the MEM_REPAIR gate: `wfi; j back`, two instructions.
QUIESCE_CYCLES = 2_000
QUIESCE_PC_SPAN_MAX = 64


class sep_warm_dispatch_base(sep_base_test):
    """Bring the ROM up to the warm-dispatch decision and sample the outcome."""

    build_env = False
    rom_build_dir = _FW_DIR

    # Subclass contract.
    #   seed: what +sep_cold_scratch7 must carry, or None for "not armed at all"
    #         (the register's cold reset value of 0, which is leg A's stimulus).
    seed: int | None = None
    max_run_cycles = 400_000
    progress_every = 50_000
    #   stage_tcm: pulse tcm_load_i, which loads sep_itcm.hex/sep_dtcm.hex AND
    #         writes every ICCM/DCCM row with valid ECC. The warm dispatch itself
    #         needs neither -- the ROM runs from Boot ROM and the decision is made
    #         before DCCM is touched -- but sep_itcm.hex is the ROM's own .text,
    #         so staging it leaves a COPY OF THE ROM sitting in ICCM. Any test
    #         whose subject is what the ICCM target contains must turn this off.
    stage_tcm = True

    async def bring_up_to_dispatch(self) -> list[str]:
        """Stage the ROM, check the stimulus, and release the core.

        Returns the console sink. It stays empty on every leg that stops before
        the C runtime, which is itself evidence -- ``simputs()`` needs C.
        """
        dut = cocotb.top

        # Guard the stimulus before anything downstream can describe the wrong
        # run. A missing or mismatched deposit silently turns every leg into
        # leg A, and leg A's own expectations would then be met for the wrong
        # reason.
        seeded = cocotb.plusargs.get("sep_cold_scratch7")
        if self.seed is None:
            assert seeded is None, (
                f"+sep_cold_scratch7={seeded} is set, but this test needs "
                f"cold_scratch[7] at its cold reset value of 0 to drive the beqz "
                f"early-out"
            )
            self.logger.info(
                "CHK-STIMULUS-HANDLER PASS: cold_scratch[7] left unarmed (reset value 0)"
            )
        else:
            assert seeded is not None, (
                "+sep_cold_scratch7 is not set: cold_scratch[7] would read 0, the "
                "ROM would take the beqz early-out to cold_boot, and this test's "
                "leg would not be exercised at all"
            )
            assert int(str(seeded), 16) == self.seed, (
                f"+sep_cold_scratch7={seeded} does not match the address this test "
                f"checks for (0x{self.seed:08x})"
            )
            assert self.seed != COLD_POISON, (
                f"the seed must differ from cold_boot's own poison "
                f"0x{COLD_POISON:08x}, or a run that cold booted would leave the "
                f"same value and CHK-SEED could not tell the two apart"
            )
            self.logger.info(
                "CHK-STIMULUS-HANDLER: cold_scratch[7] seed = 0x%08x",
                self.seed,
            )

        efuse_img = SepEfuseImage()
        efuse_img.set_lc_state(LC_TEST_DEV)
        self.write_efuse_image(efuse_img)

        console: list[str] = []
        cocotb.start_soon(rom_console_task(self.logger, sink=console))

        hook = None
        if self.stage_tcm:
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

            hook = _load_tcm
        else:
            self.logger.info(
                "TCM staging skipped: ICCM keeps its default fill, so the warm "
                "target holds no instruction"
            )

        await self.bring_up_cpu_boot(
            _ROM_BASE >> 1,
            pre_reset_hook=hook,
            run_pulse_cycles=40,
        )
        return console

    async def sample_until(self, stop_status: int | None) -> dict:
        """Sample cold_scratch[1]/[7] and the trace port until ``stop_status``.

        Both registers are sampled every cycle and recorded on change, so the
        caller gets the ORDER of the words the ROM wrote, not just the final
        resting value -- which is what distinguishes "reached the hang" from
        "passed through on the way to somewhere else".
        """
        dut = cocotb.top
        status_seq: list[int] = []
        cold7_seq: list[int] = []
        verdict_seq: list[int] = []
        last_status = None
        last_cold7 = None
        last_verdict = None
        stopped = False
        retired = 0
        last_log = 0

        for cycle in range(self.max_run_cycles):
            await RisingEdge(dut.clk_i)
            probe = self.rd(dut.scratch_cold_probe_o)
            status = (probe >> 32) & 0xFFFF_FFFF
            if status != last_status:
                last_status = status
                status_seq.append(status)
            cold7 = (probe >> 224) & 0xFFFF_FFFF
            if cold7 != last_cold7:
                last_cold7 = cold7
                cold7_seq.append(cold7)
            # cold_scratch[0] is the verdict channel: trap_vector_early and every
            # C failure path write TEST_FAIL_CODE here.
            verdict = probe & 0xFFFF_FFFF
            if verdict != last_verdict:
                last_verdict = verdict
                verdict_seq.append(verdict)
            if self.rd(dut.cpu_trace_valid_o):
                retired += 1
            if stop_status is not None and status == stop_status:
                stopped = True
                self.logger.info("stop status 0x%08x seen at cycle %d", stop_status, cycle)
                break
            if cycle - last_log >= self.progress_every:
                last_log = cycle
                self.logger.info(
                    "warm dispatch poll cyc=%d status=0x%08x cold7=0x%08x retired=%d",
                    cycle,
                    status,
                    cold7,
                    retired,
                )

        log_scratch_cold(self.logger)
        self.logger.info("cold_scratch[1] sequence: %s", [hex(v) for v in status_seq])
        self.logger.info("cold_scratch[7] sequence: %s", [hex(v) for v in cold7_seq])
        return {
            "status_seq": status_seq,
            "cold7_seq": cold7_seq,
            "verdict_seq": verdict_seq,
            "stopped": stopped,
            "retired": retired,
        }

    async def observe_quiesce(self, resting_status: int) -> dict:
        """After a terminal status, prove the core actually STOPPED.

        The spin keeps retiring, so instruction volume proves nothing; PC
        LOCALITY is the evidence. Code that continued into cold_boot would walk
        hundreds of addresses.
        """
        dut = cocotb.top
        post_pcs: set[int] = set()
        moved = False
        for _ in range(QUIESCE_CYCLES):
            await RisingEdge(dut.clk_i)
            if self.rd(dut.cpu_trace_valid_o):
                # cpu_trace_addr_o is already a byte PC (tb_top drives it from
                # trace_rv_i_address_ip); do not shift it.
                post_pcs.add(self.rd(dut.cpu_trace_addr_o))
            if ((self.rd(dut.scratch_cold_probe_o) >> 32) & 0xFFFF_FFFF) != resting_status:
                moved = True
        span = (max(post_pcs) - min(post_pcs)) if post_pcs else 0
        return {"pcs": post_pcs, "span": span, "moved": moved}

    def assert_hung(self, quiesce: dict, resting_status: int) -> None:
        """The shared shape of a `warm_reset_hang` verdict."""
        assert not quiesce["moved"], (
            f"cold_scratch[1] moved on from 0x{resting_status:08x} within "
            f"{QUIESCE_CYCLES} cycles: the ROM reported the reject and carried on"
        )
        assert quiesce["pcs"], (
            f"core retired nothing in the {QUIESCE_CYCLES} cycles after the "
            f"terminal status; expected the `wfi; j` spin"
        )
        assert quiesce["span"] <= QUIESCE_PC_SPAN_MAX, (
            f"after the terminal status the PC covered {quiesce['span']} bytes "
            f"across {len(quiesce['pcs'])} addresses "
            f"({[hex(p) for p in sorted(quiesce['pcs'])]}); a hung ROM spins "
            f"inside {QUIESCE_PC_SPAN_MAX} bytes"
        )
        self.logger.info(
            "CHK-HANG PASS: cold_scratch[1] held 0x%08x while the PC spun across %d "
            "byte(s) at %s for %d cycles",
            resting_status,
            quiesce["span"],
            [hex(p) for p in sorted(quiesce["pcs"])],
            QUIESCE_CYCLES,
        )
