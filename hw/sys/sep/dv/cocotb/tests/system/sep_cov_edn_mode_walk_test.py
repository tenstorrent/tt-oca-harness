# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Walk EDN through its three request modes: boot, software port and auto.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more.

Target: `edn_main_sm` holds 44 uncovered lines in the merged VCS run
`build/runs/20260919_225443__vcs__all`, and `edn_core` holds none. Every dark
line is a state the shared bring-up never selects. `seq_lib/sep_esrc_bringup_seq.py`
enables EDN once, with `EDN_CTRL_AUTO`, which sets BOOT_REQ_MODE and
AUTO_REQ_MODE together; the `Idle` arm at
`vendor/lowRISC/opentitan/upstream/hw/ip/edn/rtl/edn_main_sm.sv:67` takes
BOOT_REQ_MODE first, so the run spends its whole life on the boot path and stops
at `BootDone`. That leaves dark:

* :105-115 -- `BootDone -> BootLoadUni -> BootUniAckWait -> Idle`, the
  uninstantiate the boot path issues once BOOT_REQ_MODE is cleared.
* :70-72 -- the `Idle` arm for AUTO_REQ_MODE without BOOT_REQ_MODE.
* :120-171 -- every auto-request state: `AutoLoadIns`, `AutoFirstAckWait`,
  `AutoDispatch`, `AutoCaptGenCnt`, `AutoSendGenCmd`, `AutoAckWait`,
  `AutoCaptReseedCnt` and `AutoSendReseedCmd`.
* :175 -- `SWPortMode`, the state EDN sits in when it is enabled with neither
  mode bit.

All three mode bits are multi-bit-bool fields of the EDN CTRL register and the
commands come from BOOT_INS_CMD, RESEED_CMD, GENERATE_CMD, SW_CMD_REQ and
MAX_NUM_REQS_BETWEEN_RESEEDS, so the whole walk is register programming over the
frontdoor.

Stimulus, in four parts, after the standard ESRC bring-up (generators off,
configure, generators on, wait for the first seed) so CSRNG has real entropy to
answer the commands with:

1. Enable EDN in boot-request mode alone, let the boot instantiate and generate
   complete, then clear BOOT_REQ_MODE while leaving EDN_ENABLE set. That is the
   :105-115 uninstantiate, and it lands EDN in `SWPortMode` (:175).
2. From the software port, issue an instantiate and a generate through
   SW_CMD_REQ, polling SW_CMD_STS for flow control.
3. Disable EDN, then enable it with AUTO_REQ_MODE alone. Load the first command
   through SW_CMD_REQ, which is what `AutoLoadIns` waits on (:121), and let the
   auto dispatcher run. MAX_NUM_REQS_BETWEEN_RESEEDS is set to 1 so the counter
   reaches zero quickly and `AutoDispatch` takes both of its arms -- the
   generate arm (:146) and the reseed arm (:144).
4. Clear AUTO_REQ_MODE while the dispatcher is running, which is the
   `AutoDispatch` exit back to `Idle` (:139-141).

SW_CMD_STS, HW_CMD_STS and MAIN_SM_STATE are polled for flow control and logged.
Nothing read is compared against an expectation, and this leaf claims nothing
about the entropy any of these commands produced.

Not driven here: `RejectCsrngEntropy` (:178) and `Error` (:181). Both are
entered from a fault condition, not from a command.

no_cpu / +skip_fuse_sense / +esrc_noise_force.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from sep_base_test import sep_base_test
from sep_reg_meta import EDN, sym
from seq_lib.sep_cov_stimulus_seq import SepCovStim
from seq_lib.sep_esrc_bringup_seq import (
    CMD_INSTANTIATE,
    CMD_RESEED,
    SepEsrcConfigSeq,
    SepEsrcEnableGeneratorsSeq,
    csrng_generate_cmd,
)

EDN_CTRL = sym("EDN_CTRL_REG_ADDR")
EDN_SW_CMD_REQ = sym("EDN_SW_CMD_REQ_REG_ADDR")
EDN_SW_CMD_STS = sym("EDN_SW_CMD_STS_REG_ADDR")
EDN_HW_CMD_STS = sym("EDN_HW_CMD_STS_REG_ADDR")
EDN_MAIN_SM_STATE = sym("EDN_MAIN_SM_STATE_REG_ADDR")
EDN_MAX_REQS = sym("EDN_MAX_NUM_REQS_BETWEEN_RESEEDS_REG_ADDR")

# Multi-bit-bool encodings for the EDN CTRL fields, derived the way
# seq_lib/sep_esrc_bringup_seq.py derives them: edn.rdl resets every mode field
# to the disabled encoding, and the enabling value is that field's complement
# across its width. The encoding is chosen for Hamming distance, so it is
# neither 0 nor 1 and must not be written as a literal.
_MUBI4_FIELD = EDN.fields("CTRL")["EDN_ENABLE"]
MUBI4_FALSE = _MUBI4_FIELD["reset"]
MUBI4_TRUE = (~MUBI4_FALSE) & ((1 << _MUBI4_FIELD["bw"]) - 1)


def edn_ctrl(*, enable: bool, boot: bool = False, auto: bool = False) -> int:
    """EDN CTRL word for one mode combination."""
    return EDN.value(
        "CTRL",
        EDN_ENABLE=MUBI4_TRUE if enable else MUBI4_FALSE,
        BOOT_REQ_MODE=MUBI4_TRUE if boot else MUBI4_FALSE,
        AUTO_REQ_MODE=MUBI4_TRUE if auto else MUBI4_FALSE,
        CMD_FIFO_RST=MUBI4_FALSE,
    )


# SW_CMD_STS bit positions from the generated EDN_SW_CMD_STS bitfield:
# cmd_reg_rdy[0], cmd_rdy[1], cmd_ack[2], cmd_sts[5:3].
SW_CMD_REG_RDY = 1 << 0
SW_CMD_ACK = 1 << 2

# Generate length, in 128-bit genbits blocks. Four keeps each command short.
GEN_BLOCKS = 4

# One reseed allowed between generates, so AutoDispatch alternates between its
# generate and reseed arms instead of only ever taking the generate one.
AUTO_MAX_REQS = 1

# Bound on a SW_CMD_STS poll, and the settle a mode change is given. A command
# answered by a live CSRNG takes far fewer reads; the caps keep a command that
# is never answered from spending the run timeout in one loop.
CMD_POLLS = 400
POLL_GAP_CYCLES = 20
MODE_SETTLE_CYCLES = 4_000
AUTO_RUN_CYCLES = 40_000


@pyuvm.test()
class sep_cov_edn_mode_walk_test(sep_base_test):
    """EDN boot, software-port and auto request modes. Stimulus only."""

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

            await self._boot_mode_then_uninstantiate()
            await self._sw_port_commands()
            await self._auto_request_mode()
        finally:
            noise.kill()

    async def _log_state(self, label: str) -> None:
        state = await self.stim._rd(EDN_MAIN_SM_STATE)
        sw_sts = await self.stim._rd(EDN_SW_CMD_STS)
        hw_sts = await self.stim._rd(EDN_HW_CMD_STS)
        self.logger.info(
            "cov stimulus: %s -- MAIN_SM_STATE=0x%08x SW_CMD_STS=0x%08x HW_CMD_STS=0x%08x,"
            " logged not graded",
            label,
            state,
            sw_sts,
            hw_sts,
        )

    async def _boot_mode_then_uninstantiate(self) -> None:
        """Part 1: boot request mode, then clear BOOT_REQ_MODE."""
        await self.stim._wr(EDN_CTRL, edn_ctrl(enable=True, boot=True))
        await ClockCycles(cocotb.top.clk_i, MODE_SETTLE_CYCLES)
        await self._log_state("boot request mode")

        # EDN_ENABLE stays set, so BootDone falls through to BootLoadUni rather
        # than the SM being reset to Idle by the disable.
        await self.stim._wr(EDN_CTRL, edn_ctrl(enable=True))
        await ClockCycles(cocotb.top.clk_i, MODE_SETTLE_CYCLES)
        await self._log_state("BOOT_REQ_MODE cleared (uninstantiate, then SWPortMode)")

    async def _sw_cmd(self, cmd: int, label: str) -> None:
        """Issue one command through SW_CMD_REQ, waiting for the register to be
        ready first and for the acknowledge afterwards. Both waits are bounded
        and neither outcome is graded."""
        sts = 0
        for _ in range(CMD_POLLS):
            if (await self.stim._rd(EDN_SW_CMD_STS)) & SW_CMD_REG_RDY:
                break
            await ClockCycles(cocotb.top.clk_i, POLL_GAP_CYCLES)
        await self.stim._wr(EDN_SW_CMD_REQ, cmd)
        for _ in range(CMD_POLLS):
            sts = await self.stim._rd(EDN_SW_CMD_STS)
            if sts & SW_CMD_ACK:
                break
            await ClockCycles(cocotb.top.clk_i, POLL_GAP_CYCLES)
        self.logger.info(
            "cov stimulus: SW_CMD_REQ %s (0x%08x) issued, SW_CMD_STS=0x%08x, logged not graded",
            label,
            cmd,
            sts,
        )

    async def _sw_port_commands(self) -> None:
        """Part 2: instantiate and generate from the software port."""
        await self._sw_cmd(CMD_INSTANTIATE, "instantiate")
        await self._sw_cmd(csrng_generate_cmd(GEN_BLOCKS), "generate")
        await self._log_state("after the software-port commands")

    async def _auto_request_mode(self) -> None:
        """Parts 3 and 4: auto request mode, then leave it while it runs."""
        await self.stim._wr(EDN_CTRL, edn_ctrl(enable=False))
        await ClockCycles(cocotb.top.clk_i, MODE_SETTLE_CYCLES)

        # The auto dispatcher re-issues these two, so they must be staged before
        # the mode is entered.
        await self.stim._wr(EDN_MAX_REQS, AUTO_MAX_REQS)
        await self.stim._wr(
            sym("EDN_RESEED_CMD_REG_ADDR"),
            CMD_RESEED,
        )
        await self.stim._wr(
            sym("EDN_GENERATE_CMD_REG_ADDR"),
            csrng_generate_cmd(GEN_BLOCKS),
        )

        await self.stim._wr(EDN_CTRL, edn_ctrl(enable=True, auto=True))
        await ClockCycles(cocotb.top.clk_i, MODE_SETTLE_CYCLES)
        await self._log_state("auto request mode entered (AutoLoadIns)")

        # AutoLoadIns waits on a software command load before it hands the
        # dispatcher the port.
        await self._sw_cmd(CMD_INSTANTIATE, "auto-mode first load (instantiate)")
        await ClockCycles(cocotb.top.clk_i, AUTO_RUN_CYCLES)
        await self._log_state("auto dispatcher running")

        await self.stim._wr(EDN_CTRL, edn_ctrl(enable=True))
        await ClockCycles(cocotb.top.clk_i, MODE_SETTLE_CYCLES)
        await self._log_state("AUTO_REQ_MODE cleared")
