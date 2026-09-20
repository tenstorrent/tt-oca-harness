# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Hold the TRNG domain in per-IP software reset at randomized points while the
entropy source, CSRNG and EDN are mid-flow, so their main FSMs return to their
reset state from a running state.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more. No entropy value is read back or compared.

Target: the FSM arcs whose destination is the FSM's own reset state and which
no `case` arm assigns anywhere. In the TRNG reset domain those are:

* `entropy_src/rtl/entropy_src_main_sm.sv` -- 18 arcs into Idle, from
  StartupHTStart, StartupPhase1, StartupPass1, StartupFail1, ContHTStart,
  ContHTRunning, BootHTRunning, BootPostHTChk, BootPhaseDone, FWInsertStart,
  FWInsertMsg, Sha3Process, Sha3Valid, Sha3Done, Sha3MsgDone, AlertState,
  AlertHang and Error.
* `edn/rtl/edn_main_sm.sv` -- 17 arcs into Idle, and `edn/rtl/edn_ack_sm.sv`
  -- 7 arcs into Disabled or Error.
* `csrng/rtl/csrng_main_sm.sv` -- 6 arcs into MainSmIdle,
  `csrng/rtl/csrng_cmd_stage.sv` -- 18, and `csrng/rtl/csrng_ctr_drbg.sv`
  -- 8 on `state_d` plus 1 on `gen_subcmd_d`.

Together that is the largest single cluster of reset-only arcs in SEP.
`csrng_cmd_stage` and `edn_main_sm` also walk through many of their states
inside one auto-mode reseed/generate cycle, so a spread of landing points
reaches a different source state on each pass.

Mechanism: `SW_RESET_N.trng_sw_rst_n` (`sep_reset_ctrl.sv:137`). Clearing it
raises `trng_isolate_req`, which `sep_reset_ctrl.sv:226-228` drives onto the
entropy-source, CSRNG and EDN isolate requests; `u_trng_isolate_seq`
(:213-222) waits for all three to report isolated before it drops
`isolated_rst_n.trng`. The ordering used here -- quiesce the crypto consumers
first, then the TRNG -- is the one `SepSwReset.begin_trng_recovery` exists for,
and is what `sep_trng_reset_recovery_test` drives. This leaf differs only in
that it repeats the pulse at seeded offsets instead of once from a settled
pool, and that it grades nothing.

The crypto engines are left idle for the whole run, so none of them has an
`edn_req` outstanding when the TRNG domain clears.

Randomness: the offsets come from `SepSeededRng` seeded with the run seed, so
`--stage sim --seed N` replays a given landing point. They are not a key, nonce
or token and nothing derived from them leaves the simulation.

Safety: the TRNG bit is released and the entropy stack reinitialized inside
every iteration, and `SW_RESET_N` is restored in a `finally`, so no later leaf
inherits a held TRNG or held consumers.

no_cpu / +skip_fuse_sense / +esrc_noise_force.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from seq_lib.sep_esrc_bringup_seq import (
    SepEsrcConfigSeq,
    SepEsrcEnableEdnSeq,
    SepEsrcEnableGeneratorsSeq,
)
from seq_lib.sep_sw_reset_seq import SepSwReset

# Offsets, in core clock cycles after EDN is enabled for the iteration, at
# which the TRNG reset request is raised. EDN auto mode issues an instantiate,
# then reseed and generate commands back to back, and one command walks
# csrng_cmd_stage through its arbitration, send and acknowledge states in a few
# hundred cycles, so a spread this wide lands the reset in a different set of
# states on each pass. Which state a given offset hits is not claimed.
RESET_DELAY_MIN = 100
RESET_DELAY_MAX = 12_000

# Cycles the domain is held before release, and the settle after release. Long
# enough for `u_trng_isolate_seq` to walk its request/isolated handshake in
# both directions.
HOLD_CYCLES = 600
SETTLE_CYCLES = 400

# Each iteration costs a full ESRC restart and a fresh seed, which dominates
# the runtime. Four passes give four independent landing points per FSM.
RESET_PASSES = 4


@pyuvm.test()
class sep_cov_trng_reset_midflow_test(sep_base_test):
    """Per-IP TRNG reset inside a running entropy flow. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        rng = SepSeededRng(self.random_seed())
        noise = self.start_esrc_noise_driver()
        resets = SepSwReset(self)
        saved = await resets.read_back()
        pulses = 0

        try:
            await self._bring_up_entropy(first=True)
            for idx in range(RESET_PASSES):
                delay = RESET_DELAY_MIN + (
                    rng.getrandbits(32) % (RESET_DELAY_MAX - RESET_DELAY_MIN + 1)
                )
                await ClockCycles(cocotb.top.clk_i, delay)

                # Consumers quiesced first, then the TRNG domain, and the TRNG
                # left held so the reset is observed rather than raced.
                await resets.begin_trng_recovery(reset_km=False, release_trng=False)
                await ClockCycles(cocotb.top.clk_i, HOLD_CYCLES)
                await resets.release("trng")
                await ClockCycles(cocotb.top.clk_i, SETTLE_CYCLES)
                pulses += 1
                self.logger.info(
                    "COV-STIM trng_reset_midflow pass %d: TRNG domain held in reset "
                    "%d cycles into the entropy flow, then released",
                    idx,
                    delay,
                )

                await self._bring_up_entropy(first=False)
        finally:
            noise.kill()
            await resets.restore_after_trng_reinit(saved)

        self.logger.info(
            "COV-STIM trng_reset_midflow: %d TRNG resets driven with ESRC, CSRNG and "
            "EDN mid-flow; SW_RESET_N restored to 0x%08x",
            pulses,
            saved,
        )

    async def _bring_up_entropy(self, *, first: bool) -> None:
        """Configure and start the entropy stack.

        After a TRNG reset the domain comes back with its CSRs at their reset
        values, so the same programming runs again with `reset_trng=False`:
        the reset has already happened, and the consumers stay held until the
        run ends. `wait_seed_ready` is flow control on the ESRC status the
        design publishes, not a value compare.
        """
        tag = "init" if first else "reinit"
        await self.start_seq(SepEsrcConfigSeq(f"esrc_config_{tag}", reset_trng=first))
        await self.start_seq(SepEsrcEnableGeneratorsSeq(f"esrc_enable_gens_{tag}"))
        if not await self.wait_seed_ready():
            raise AssertionError(
                f"stimulus precondition: ESRC never produced a seed on {tag}"
            )
        await self.start_seq(SepEsrcEnableEdnSeq(f"esrc_enable_edn_{tag}"))
