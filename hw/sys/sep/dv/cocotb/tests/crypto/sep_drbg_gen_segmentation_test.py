# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Each completed CSRNG Generate command carries exactly glen blocks, with glen shortened to 4.

Every other entropy test leaves Generate unfinished, so CHK4's legality loop
never runs ("segmentation NOT EXERCISED"). Two independent reasons, both needed
to close it:

  * ``EDN.BOOT_GEN_CMD`` resets to ``glen=4095``. ``EDN_CTRL_AUTO`` sets
    ``BOOT_REQ``, so the first Generate is the boot command, not
    ``GENERATE_CMD``. Programming only ``GENERATE_CMD`` (the default
    ``SepEntropyCfg.glen`` path) does not shorten that command.
  * Even after the boot generate is shortened, the length must be short enough
    that a command completes inside the block budget.

This test sets ``SepEntropyCfg(glen=4, program_boot_generate=True)``. That one
object programs ``BOOT_GEN_CMD``, ``GENERATE_CMD``, and the golden, so DUT and
model stay in lockstep. Existing tests leave ``program_boot_generate`` False so
their one-open-command CHK4 budgets stay put.

What this proves that no other test does:
  * ``gen_last`` is observed asserted at the end of a Generate command;
  * every completed command carries exactly ``cfg.glen`` blocks -- a segment of
    any other length fails;
  * CHK1..CHK4 stay bit-exact at every stage of the entropy stack.

Not proven here: bit-exactness *across* a trailing CTR_DRBG Update boundary.
The test grades the one boot Generate; see the class docstring.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from sep_base_test import sep_base_test
from seq_lib.sep_esrc_bringup_seq import SepEntropyCfg
from seq_lib.sep_km_mem_smoke_seq import sep_km_release_seq

# Short enough that one Generate completes inside the budget, and > 1
# so a command still spans multiple beats (glen=1 would make every beat a
# boundary and hide an off-by-one in the countdown).
SEGMENTATION_GLEN = 4
# Poll window for completed Generate commands, sized so the one boot Generate
# retires with margin (about one command per 1.1 ms of sim at glen=4).
POLL_ITERATIONS = 400
POLL_CYCLES = 200
# One completed command is all this test reaches (see the class docstring).
MIN_COMPLETED_COMMANDS = 1


@pyuvm.test()
class sep_drbg_gen_segmentation_test(sep_base_test):
    """A completed Generate at glen=4 carries exactly 4 blocks, and CHK1..CHK4 stay bit-exact.

    Not claimed: bit-exactness across a trailing CTR_DRBG Update boundary. The
    Update fires after the last block of a command and this test completes
    exactly one command, so no golden-compared block lands on its far side.
    The limit is EDN issuing no second Generate, not the poll window. Reaching
    the boundary needs a second Generate commanded, which this test does not do.
    """

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()

        # glen feeds GENERATE_CMD and the golden;
        # program_boot_generate also writes BOOT_GEN_CMD, which is the command
        # BOOT_REQ actually issues (reset glen=4095). SepEntropyCfg is frozen.
        cfg = SepEntropyCfg(glen=SEGMENTATION_GLEN, program_boot_generate=True)

        await self.bring_up_entropy(cfg=cfg, strict=True)

        # Release KM after the shared TRNG reset, matching the smoke test.
        # SepEsrcConfigSeq preserves the reset register's hardware default while
        # pulsing the TRNG bit, and that default keeps KM held.
        await self.start_seq(sep_km_release_seq("km_release"))

        # Concurrent FIFO_RDATA drain after the last bring-up write, matching the
        # e2e smoke. Without it the entropy FIFO fills and the chain stalls.
        # Starting it earlier would contend the AXI sequencer with the bring-up
        # writes.
        self.start_fifo_drain()

        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        assert await self.wait_km_entropy_handshake(), "KM never handshook a genbits word"
        assert await self.wait_km_consumed_word(), "KM never consumed a genbits word"
        # The non-zero poll above only says the KM CPU reached its store. Compare
        # the stored word against the word the DUT delivered on the AXIS endpoint,
        # so the SRAM landing is a value check and not a liveness marker.
        self.check_km_sram_word_matches_consumed()

        # Let the one boot Generate retire. A second command does
        # not arrive however long the poll runs (see the class docstring), so
        # this waits for completion, not for a boundary.
        sb = self.drbg_sb
        # Exit once one command has completed and its glen blocks are scored.
        # A higher block target adds sim time for no extra contract.
        target_blocks = SEGMENTATION_GLEN * MIN_COMPLETED_COMMANDS
        for _ in range(POLL_ITERATIONS):
            if (
                sb.results["CHK4_genbits"].dut_items >= target_blocks
                and sum(sb.completed_generate_lengths().values()) >= MIN_COMPLETED_COMMANDS
            ):
                break
            await ClockCycles(cocotb.top.clk_i, POLL_CYCLES)

        await self.check_entropy_alerts_zero()
        await self.stop_fifo_drain()

        seg_hist = sb.completed_generate_lengths()
        completed = sum(seg_hist.values())
        # The whole point of the test: if this is 0 the run proved nothing about
        # segmentation, and CHK4's legality check silently did not execute.
        assert completed > 0, (
            f"no Generate command completed at glen={SEGMENTATION_GLEN} "
            f"({sb.results['CHK4_genbits'].dut_items} genbits observed, "
            f"{sb.open_generate_remaining()} left in the open command). gen_last was never "
            f"seen asserted, so this test did not exercise what it exists for."
        )
        # A second completed command would put a golden-compared block on the far
        # side of the trailing Update. This test does not reach one -- see
        # MIN_COMPLETED_COMMANDS -- so the boundary is explicitly not claimed
        # rather than silently assumed.
        assert completed >= MIN_COMPLETED_COMMANDS, (
            f"no Generate command completed in "
            f"{POLL_ITERATIONS * POLL_CYCLES} cycles "
            f"({sb.results['CHK4_genbits'].dut_items} genbits observed)"
        )
        # Every completed command must be exactly glen blocks. report() also
        # checks this against legal_gen_lengths; assert here so the failure names
        # the segmentation contract directly rather than a generic scoreboard error.
        assert set(seg_hist) == {SEGMENTATION_GLEN}, (
            f"Generate commands did not all carry glen={SEGMENTATION_GLEN} blocks: "
            f"observed blocks/cmd {dict(sorted(seg_hist.items()))}"
        )
        self.logger.info(
            "CHK-SEGMENTATION PASS: %d Generate command(s) completed, each exactly "
            "%d blocks. The trailing Update is NOT observed: no golden-compared "
            "block lands on its far side in this vehicle",
            completed,
            SEGMENTATION_GLEN,
        )

        # report() grades CHK1..CHK4 bit-exact on every block of the completed
        # command.
        assert sb.report()
