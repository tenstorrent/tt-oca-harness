# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Hold OTBN in per-IP software reset while a program is executing, so its
control FSMs return to their reset state from a running state.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more. No DMEM result is read back or compared.

Target: the FSM arcs whose destination is the FSM's own reset state and which
no `case` arm assigns anywhere. In the OTBN reset domain those are:

* `otbn/rtl/otbn_start_stop_control.sv` `state_d` -- 7 arcs into
  OtbnStartStopStateInitial, from Running, UrndRefresh, Locked and the four
  SecureWipe states. This FSM is the design's own proof that a reset-driven arc
  scores: `otbn_start_stop_control.sv:158-159` is the flop's reset value and no
  `case` arm writes OtbnStartStopStateInitial, yet the merged run already
  records Halt -> Initial and SecureWipeWdrUrnd -> Initial as covered.
* `otbn/rtl/otbn_controller.sv` `state_d` -- 5 arcs, including
  OtbnStateLocked -> OtbnStateHalt and OtbnStateStall -> OtbnStateHalt.
* `otbn/rtl/otbn_scramble_ctrl.sv` -- 3 into ScrambleCtrlIdle, from
  ScrambleCtrlImemReq, ScrambleCtrlDmemReq and ScrambleCtrlError.
* `hw/common/axi/axi_lite_to_tlul.sv` and `hw/common/axi/tlul_to_axi_lite.sv`
  -- 4 each into IDLE; `sep_crypto_otbn_wrapper.sv` instantiates that bridge
  pair inside the engine's reset domain.

Mechanism: `SW_RESET_N.otbn_sw_rst_n` (`sep_reset_ctrl.sv:141`). Clearing it
raises `otbn_isolate_req` (:164-170); `sep_isolate_rst_seq` waits for the OTBN
host and KM AXI ports to isolate and then drops `isolated_rst_n.otbn`, the
`sep_crypto_otbn_wrapper` `rst_ni`.

OTBN is the design's heaviest EDN client: `sep_crypto.sv:429-431` gives it two
request slots, RND and URND, and `otbn_start_stop_control` blocks in
UrndRefresh and in the SecureWipe*Urnd states until a word arrives. A pulse
that lands there would drop an ungranted request on the crypto entropy
arbiter, so this leaf does not aim at those states: each pass polls STATUS
until OTBN reports busy, which is past the start-up URND refresh, and then
pulses after a short seeded delay while the controller is executing. The
SecureWipe*Urnd reset arcs are therefore left to a mechanism that can hold the
entropy path, and are not claimed here.

Randomness: the offsets come from `SepSeededRng` seeded with the run seed, so
`--stage sim --seed N` replays a given landing point. Nothing derived from them
leaves the simulation.

Safety: the OTBN bit is released after every pulse and `SW_RESET_N` is restored
in a `finally`.

no_cpu / +skip_fuse_sense / +esrc_noise_force.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from seq_lib.sep_cov_reset_arc_seq import SepCovEngineReset
from seq_lib.sep_esrc_bringup_seq import (
    SepEsrcConfigSeq,
    SepEsrcEnableEdnSeq,
    SepEsrcEnableGeneratorsSeq,
)
from seq_lib.sep_otbn_seq import (
    OTBN_ADDR_STATUS,
    OTBN_STATUS_IDLE,
    OTBN_STATUS_LOCK,
    SepOtbn,
)

# Offsets, in core clock cycles after STATUS first reads busy, at which the
# reset request is raised. Which state a given offset hits is not claimed.
RESET_DELAY_MIN = 1
RESET_DELAY_MAX = 200

# Bound on the poll that waits for STATUS to leave IDLE after EXECUTE.
BUSY_POLLS = 2_000
BUSY_POLL_CYCLES = 5

PASSES = 8


@pyuvm.test()
class sep_cov_otbn_reset_midrun_test(sep_base_test):
    """Per-IP reset inside a running OTBN program. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        rng = SepSeededRng(self.random_seed())
        noise = self.start_esrc_noise_driver()
        rst = SepCovEngineReset(self, "otbn")
        otbn = SepOtbn(self)

        try:
            # OTBN's URND refresh blocks until EDN delivers, so the entropy
            # stack is brought up before the first EXECUTE.
            await self.start_seq(SepEsrcConfigSeq("esrc_config"))
            await self.start_seq(SepEsrcEnableGeneratorsSeq("esrc_enable_gens"))
            if not await self.wait_seed_ready():
                raise AssertionError("stimulus precondition: ESRC never produced a seed")
            await self.start_seq(SepEsrcEnableEdnSeq("esrc_enable_edn"))

            for idx in range(PASSES):
                await self._pass(otbn, rst, rng, idx)
        finally:
            noise.kill()
            await rst.restore()

        self.logger.info(
            "COV-STIM otbn_reset_midrun: %d per-IP resets driven inside a running "
            "OTBN program",
            rst.pulses,
        )

    async def _pass(self, otbn: SepOtbn, rst: SepCovEngineReset, rng, idx: int) -> None:
        # IMEM is writable only while OTBN is idle; `load_program` waits out the
        # post-reset secure wipe first, so each pass re-loads after the previous
        # pass cleared the memory.
        await otbn.load_program()
        await otbn.start_execute()
        await self._wait_busy(otbn, idx)
        delay = rst.delay(rng, RESET_DELAY_MIN, RESET_DELAY_MAX)
        await rst.pulse(delay_cycles=delay, tag=f"execute_{idx}")

    async def _wait_busy(self, otbn: SepOtbn, idx: int) -> None:
        """Spin until STATUS leaves IDLE.

        Flow control, not a check: STATUS is the register the design publishes
        for exactly this, and leaving IDLE is what says the start/stop FSM is
        past its URND refresh and the controller is executing.
        """
        for _ in range(BUSY_POLLS):
            st = await otbn._rd(OTBN_ADDR_STATUS)
            if st == OTBN_STATUS_LOCK:
                raise AssertionError(f"stimulus precondition: OTBN LOCKED on pass {idx}")
            if st != OTBN_STATUS_IDLE:
                return
            await ClockCycles(cocotb.top.clk_i, BUSY_POLL_CYCLES)
        raise AssertionError(
            f"stimulus precondition: OTBN never left IDLE after EXECUTE on pass {idx}"
        )
