# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Walk the CSRNG software application port through its whole command set,
including the sequences the design answers with a command error.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more.

Target: `csrng_cmd_stage` holds 45 uncovered lines and `csrng_main_sm` 11 in the
merged VCS run `build/runs/20260919_225443__vcs__all`; `csrng_core` holds none.
CSRNG's software port is the last of its three application ports
(`vendor/lowRISC/opentitan/upstream/hw/ip/csrng/rtl/csrng_core.sv:554-556`), and
the suite never writes CMD_REQ -- every CSRNG command in the run comes from EDN
on hardware application 0. That leaves dark, in
`vendor/lowRISC/opentitan/upstream/hw/ip/csrng/rtl/csrng_cmd_stage.sv`:

* :307-313 and :332-339 -- a GEN or an UPD arriving before an INSTANTIATE, which
  the stage answers with `invalid_cmd_seq`.
* :341-344 -- the UNI command, and :328-330 the sequence error that follows an
  UNI.
* :347-349 -- `invalid_acmd`, an application command outside the encoded set.
* :320-322 -- `reseed_cnt_exceeded`, raised once RESEED_INTERVAL generates have
  run without a reseed.
* :380-398 -- `GenCmdChk` and `SendMOP`, the multi-block generate walk, which
  needs a generate length above one 128-bit block.

and in `vendor/lowRISC/opentitan/upstream/hw/ip/csrng/rtl/csrng_main_sm.sv`:

* :85, :105, :110-119 -- `MainSmCmdVld`, `MainSmClrAData` and
  `MainSmCmdCompWait`, the additional-data path, which needs a command whose
  `clen` field is non-zero.

CSRNG is already enabled with SW_APP_ENABLE set by the shared bring-up
(`seq_lib/sep_esrc_bringup_seq.py`, `CSRNG_CTRL_ENABLE`), so every line above is
reached by writing CMD_REQ.

Stimulus: after the standard ESRC bring-up (generators off, configure,
generators on, wait for the first seed) and with EDN left disabled so the
software port is the only active application, the commands are issued in this
order:

1. GEN before any INSTANTIATE, then UPD before any INSTANTIATE -- two sequence
   errors.
2. An application command of 0x6, outside the encoded set -- an invalid-command
   error.
3. INSTANTIATE with `clen`=4 and four additional-data words, which is the
   additional-data path through the main FSM.
4. GENERATE for four 128-bit blocks, with the GENBITS words drained.
5. UPDATE with `clen`=4 and four additional-data words, then RESEED.
6. UNINSTANTIATE, then an UPDATE after it -- a third sequence error.
7. INSTANTIATE again with RESEED_INTERVAL set to 1, then two generates, so the
   reseed counter is exceeded.

SW_CMD_STS is polled for flow control; SW_CMD_STS, GENBITS, RECOV_ALERT_STS and
ERR_CODE are read and logged. Nothing read is compared against an expectation.
The commands the design refuses are refused in a status register, not with a bus
error, so no access here is marked `allow_error`.

no_cpu / +skip_fuse_sense / +esrc_noise_force.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from sep_base_test import sep_base_test
from sep_reg_meta import sym
from seq_lib.sep_cov_stimulus_seq import SepCovStim
from seq_lib.sep_esrc_bringup_seq import (
    SepEsrcConfigSeq,
    SepEsrcEnableGeneratorsSeq,
    csrng_cmd,
)

CSRNG_CMD_REQ = sym("CSRNG_CMD_REQ_REG_ADDR")
CSRNG_SW_CMD_STS = sym("CSRNG_SW_CMD_STS_REG_ADDR")
CSRNG_GENBITS_VLD = sym("CSRNG_GENBITS_VLD_REG_ADDR")
CSRNG_GENBITS = sym("CSRNG_GENBITS_REG_ADDR")
CSRNG_RESEED_INTERVAL = sym("CSRNG_RESEED_INTERVAL_REG_ADDR")
CSRNG_RECOV_ALERT_STS = sym("CSRNG_RECOV_ALERT_STS_REG_ADDR")
CSRNG_ERR_CODE = sym("CSRNG_ERR_CODE_REG_ADDR")
CSRNG_MAIN_SM_STATE = sym("CSRNG_MAIN_SM_STATE_REG_ADDR")

# Application command encodings, csrng_pkg.sv: INS=1, RES=2, GEN=3, UPD=4,
# UNI=5. 6 is outside the encoded set, which is what makes it the invalid-acmd
# stimulus.
ACMD_INS = 1
ACMD_RES = 2
ACMD_GEN = 3
ACMD_UPD = 4
ACMD_UNI = 5
ACMD_INVALID = 6

# Four additional-data words, the maximum a single clen field expresses without
# spanning more than one seed line.
ADATA_WORDS = 4

# Generate length in 128-bit blocks. More than one is what walks GenCmdChk and
# SendMOP; each block is four GENBITS reads.
GEN_BLOCKS = 4
GENBITS_WORDS_PER_BLOCK = 4

# One generate allowed between reseeds, so the second generate of part 7 finds
# the counter already at zero.
SHORT_RESEED_INTERVAL = 1

# SW_CMD_STS bit positions, from the generated CSRNG_SW_CMD_STS bitfield:
# cmd_rdy[1], cmd_ack[2], cmd_sts[5:3].
SW_CMD_RDY = 1 << 1
SW_CMD_ACK = 1 << 2

# Bounds on the polls. A command answered by a live CSRNG settles in far fewer
# reads; the caps keep a command that is never answered from spending the run
# timeout in one loop.
CMD_POLLS = 400
GENBITS_POLLS = 200
POLL_GAP_CYCLES = 20


@pyuvm.test()
class sep_cov_csrng_sw_cmd_walk_test(sep_base_test):
    """CSRNG software-port command walk, valid and refused. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        noise = self.start_esrc_noise_driver()
        try:
            self.stim = SepCovStim(self)
            await self.start_seq(SepEsrcConfigSeq("esrc_config"))
            await self.start_seq(SepEsrcEnableGeneratorsSeq("esrc_enable_gens"))
            if not await self.wait_seed_ready():
                raise AssertionError("stimulus precondition: ESRC never produced a seed")

            await self._out_of_sequence_commands()
            await self._instantiate_with_adata()
            await self._generate_and_drain()
            await self._update_reseed_uninstantiate()
            await self._reseed_counter_exceeded()
            await self._log_alerts()
        finally:
            noise.kill()

    async def _cmd(self, word: int, label: str, *, adata: list[int] | None = None) -> None:
        """Write one application command, and its additional-data words when the
        command carries a non-zero clen, then wait for the acknowledge. Both
        waits are bounded and neither outcome is graded."""
        sts = 0
        for _ in range(CMD_POLLS):
            sts = await self.stim._rd(CSRNG_SW_CMD_STS)
            if sts & SW_CMD_RDY:
                break
            await ClockCycles(cocotb.top.clk_i, POLL_GAP_CYCLES)
        await self.stim._wr(CSRNG_CMD_REQ, word)
        for extra in adata or []:
            await self.stim._wr(CSRNG_CMD_REQ, extra & 0xFFFF_FFFF)
        for _ in range(CMD_POLLS):
            sts = await self.stim._rd(CSRNG_SW_CMD_STS)
            if sts & SW_CMD_ACK:
                break
            await ClockCycles(cocotb.top.clk_i, POLL_GAP_CYCLES)
        self.logger.info(
            "cov stimulus: CMD_REQ %s (0x%08x) issued, SW_CMD_STS=0x%08x, logged not graded",
            label,
            word,
            sts,
        )

    async def _out_of_sequence_commands(self) -> None:
        """Part 1 and 2: commands the stage refuses before an instantiate."""
        await self._cmd(csrng_cmd(acmd=ACMD_GEN, glen=1), "generate before instantiate")
        await self._cmd(csrng_cmd(acmd=ACMD_UPD), "update before instantiate")
        await self._cmd(csrng_cmd(acmd=ACMD_INVALID), "application command 0x6")

    async def _instantiate_with_adata(self) -> None:
        """Part 3: instantiate carrying additional data."""
        adata = [0xA5A5_0000 | i for i in range(ADATA_WORDS)]
        await self._cmd(
            csrng_cmd(acmd=ACMD_INS, clen=ADATA_WORDS),
            "instantiate with additional data",
            adata=adata,
        )

    async def _drain_genbits(self, blocks: int) -> None:
        """Read the genbits words one generate produced, polling GENBITS_VLD."""
        for _ in range(blocks * GENBITS_WORDS_PER_BLOCK):
            for _ in range(GENBITS_POLLS):
                if (await self.stim._rd(CSRNG_GENBITS_VLD)) & 0x1:
                    break
                await ClockCycles(cocotb.top.clk_i, POLL_GAP_CYCLES)
            else:
                self.logger.info("cov stimulus: GENBITS never became valid inside the poll")
                return
            word = await self.stim._rd(CSRNG_GENBITS)
            self.logger.info("cov stimulus: GENBITS word 0x%08x, logged not graded", word)

    async def _generate_and_drain(self) -> None:
        """Part 4: a multi-block generate."""
        await self._cmd(csrng_cmd(acmd=ACMD_GEN, glen=GEN_BLOCKS), f"generate {GEN_BLOCKS} blocks")
        await self._drain_genbits(GEN_BLOCKS)

    async def _update_reseed_uninstantiate(self) -> None:
        """Parts 5 and 6: update, reseed, uninstantiate, then update again."""
        adata = [0x5A5A_0000 | i for i in range(ADATA_WORDS)]
        await self._cmd(
            csrng_cmd(acmd=ACMD_UPD, clen=ADATA_WORDS),
            "update with additional data",
            adata=adata,
        )
        await self._cmd(csrng_cmd(acmd=ACMD_RES), "reseed")
        await self._cmd(csrng_cmd(acmd=ACMD_UNI), "uninstantiate")
        await self._cmd(csrng_cmd(acmd=ACMD_UPD), "update after uninstantiate")

    async def _reseed_counter_exceeded(self) -> None:
        """Part 7: run past RESEED_INTERVAL generates without a reseed."""
        await self.stim._wr(CSRNG_RESEED_INTERVAL, SHORT_RESEED_INTERVAL)
        await self._cmd(csrng_cmd(acmd=ACMD_INS), "instantiate (short reseed interval)")
        for i in range(3):
            await self._cmd(csrng_cmd(acmd=ACMD_GEN, glen=1), f"generate {i + 1} of 3")
            await self._drain_genbits(1)

    async def _log_alerts(self) -> None:
        state = await self.stim._rd(CSRNG_MAIN_SM_STATE)
        recov = await self.stim._rd(CSRNG_RECOV_ALERT_STS)
        err = await self.stim._rd(CSRNG_ERR_CODE)
        self.logger.info(
            "cov stimulus: MAIN_SM_STATE=0x%08x RECOV_ALERT_STS=0x%08x ERR_CODE=0x%08x,"
            " logged not graded",
            state,
            recov,
            err,
        )
