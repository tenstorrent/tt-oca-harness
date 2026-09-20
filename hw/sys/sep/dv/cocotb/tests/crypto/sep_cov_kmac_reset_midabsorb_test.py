# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Hold the KMAC engine in per-IP software reset while a SHAKE-256 operation is
absorbing, padding or squeezing, so its sub-FSMs return to idle from a running
state.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more. No digest is read back or compared.

Target: the FSM arcs whose destination is the FSM's own reset state and which
no `case` arm assigns anywhere. In the KMAC reset domain those are:

* `kmac/rtl/kmac.sv` `kmac_st_d` -- 5 arcs into KmacIdle, from KmacPrefix,
  KmacKeyBlock, KmacMsgFeed, KmacDigest and KmacTerminalError.
* `kmac/rtl/kmac_core.sv` -- 3 into StKmacIdle;
  `kmac/rtl/kmac_msgfifo.sv` -- 2 into FlushIdle;
  `kmac/rtl/kmac_entropy.sv` -- 7 into StRandReset.
* `kmac/rtl/sha3.sv` -- 3 into StIdle_sparse;
  `kmac/rtl/sha3pad.sv` -- 8 into StPadIdle;
  `kmac/rtl/keccak_round.sv` -- 6 into KeccakStIdle.
* `hw/common/axi/axi_lite_to_tlul.sv` -- 4 into IDLE, and
  `hw/common/axi/tlul_to_axi_lite.sv` -- 4 into IDLE. `kmac_wrapper.sv` is one
  of the four wrappers that instantiate that bridge pair inside the engine's
  reset domain.

Mechanism: `SW_RESET_N.kmac_sw_rst_n` (`sep_reset_ctrl.sv:138`). Clearing it
raises `kmac_isolate_req` (:191-197); `sep_isolate_rst_seq` waits for the KMAC
host and KM AXI ports to isolate and then drops `isolated_rst_n.kmac`, the
`kmac_wrapper` `rst_ni`.

Three landing points are driven per pass, because the engine is in a different
set of states at each: after CMD.start with the message pushed but CMD.process
not yet written (msgfifo and pad absorbing), after CMD.process (pad, keccak and
the core running), and once the engine has reached squeeze.

KMAC masking stalls without entropy, so the run brings up the real
ESRC/DRBG/CSRNG/EDN stack first, in the order `sep_cov_kmac_pad_block_aligned_test`
uses. The engine is an EDN client (`sep_crypto.sv:477`), so a pulse that lands
while `kmac_entropy` has an ungranted `edn_req` and the entropy staging FIFO is
empty would drop that request; the entropy stack is kept running and the noise
driver kept alive for the whole leaf to keep that window short.

Randomness: the offsets come from `SepSeededRng` seeded with the run seed, so
`--stage sim --seed N` replays a given landing point. They are not a key, nonce
or token and nothing derived from them leaves the simulation.

Safety: the KMAC bit is released after every pulse and `SW_RESET_N` is restored
in a `finally`.

no_cpu / +skip_fuse_sense / +esrc_noise_force.
"""

from __future__ import annotations

import pyuvm
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from seq_lib.sep_cov_reset_arc_seq import SepCovEngineReset
from seq_lib.sep_esrc_bringup_seq import (
    SepEsrcConfigSeq,
    SepEsrcEnableEdnSeq,
    SepEsrcEnableGeneratorsSeq,
)
from seq_lib.sep_kmac_seq import (
    KMAC_CFG_SHADOWED,
    KMAC_CMD,
    KMAC_CMD_PROCESS,
    KMAC_CMD_START,
    KMAC_MODE,
    KMAC_STRENGTH,
    SepKmac,
    build_kmac_cfg,
)

# Message words pushed before the reset lands. Long enough that the absorb
# spans several keccak rounds, so a pulse during the push can find the pad FSM
# in StMessage and the keccak FSM in an active phase.
MSG_WORDS = 96

# Offsets, in core clock cycles from the register write that precedes them, at
# which the reset request is raised. One keccak permutation is 24 rounds, so a
# spread this wide lands the reset on different rounds and phases. Which state
# a given offset hits is not claimed.
RESET_DELAY_MIN = 4
RESET_DELAY_MAX = 900

PASSES = 6


@pyuvm.test()
class sep_cov_kmac_reset_midabsorb_test(sep_base_test):
    """Per-IP reset inside a running KMAC operation. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        rng = SepSeededRng(self.random_seed())
        noise = self.start_esrc_noise_driver()
        rst = SepCovEngineReset(self, "kmac")
        kmac = SepKmac(self)

        try:
            await self.start_seq(SepEsrcConfigSeq("esrc_config"))
            await self.start_seq(SepEsrcEnableGeneratorsSeq("esrc_enable_gens"))
            if not await self.wait_seed_ready():
                raise AssertionError("stimulus precondition: ESRC never produced a seed")
            await self.start_seq(SepEsrcEnableEdnSeq("esrc_enable_edn"))

            for idx in range(PASSES):
                stage = ("absorb", "process", "squeeze")[idx % 3]
                await self._pass(kmac, rst, rng, idx, stage)
        finally:
            noise.kill()
            await rst.restore()

        self.logger.info(
            "COV-STIM kmac_reset_midabsorb: %d per-IP resets driven inside a running "
            "SHAKE-256 operation",
            rst.pulses,
        )

    async def _pass(
        self, kmac: SepKmac, rst: SepCovEngineReset, rng, idx: int, stage: str
    ) -> None:
        cfg_word = build_kmac_cfg(
            mode=KMAC_MODE["shake"], kstrength=KMAC_STRENGTH[256], kmac_en=False
        )
        # CFG_SHADOWED takes two identical writes; the engine is reset between
        # passes, so the shadow is re-armed every time.
        await kmac._wr(KMAC_CFG_SHADOWED, cfg_word)
        await kmac._wr(KMAC_CFG_SHADOWED, cfg_word)
        await kmac.wait_idle(f"pre-start {idx}")

        await kmac._wr(KMAC_CMD, KMAC_CMD_START)
        msg = b"".join(
            (rng.getrandbits(32)).to_bytes(4, "little") for _ in range(MSG_WORDS)
        )
        await kmac._push_msg_bytes(msg)

        delay = rst.delay(rng, RESET_DELAY_MIN, RESET_DELAY_MAX)
        if stage == "absorb":
            await rst.pulse(delay_cycles=delay, tag=f"shake_absorb_{idx}")
            return

        await kmac._wr(KMAC_CMD, KMAC_CMD_PROCESS)
        if stage == "process":
            await rst.pulse(delay_cycles=delay, tag=f"shake_process_{idx}")
            return

        # `_wait_squeeze` is flow control on the engine's own STATUS bit, not a
        # value compare: it says the pad and keccak blocks have finished the
        # absorb and the core is holding the state for read-out.
        await kmac._wait_squeeze()
        await rst.pulse(delay_cycles=delay, tag=f"shake_squeeze_{idx}")
