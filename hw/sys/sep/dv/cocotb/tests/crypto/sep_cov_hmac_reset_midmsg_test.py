# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Hold the HMAC engine in per-IP software reset while a SHA-2 message is being
absorbed, padded or compressed, so its FSMs return to idle from a running state.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more. No digest is read back or compared.

Target: the FSM arcs whose destination is the FSM's own reset state and which
no `case` arm assigns anywhere. In the HMAC reset domain those are:

* `hmac/rtl/hmac.sv` `done_state_d` -- DoneAwaitMessageComplete -> DoneAwaitCmd.
* `prim/rtl/prim_sha2.sv` -- ShaCompress -> ShaIdle on `sha_st_d`, and
  FifoLoadFromFifo -> FifoIdle on `fifo_st_d`.
* `prim/rtl/prim_sha2_pad.sv` -- StPad80, StPad00 and StLenHi -> StIdle.
* `hw/common/axi/axi_lite_to_tlul.sv` and `hw/common/axi/tlul_to_axi_lite.sv`
  -- 4 each into IDLE; `hmac_wrapper.sv` instantiates that bridge pair inside
  the engine's reset domain.

The pad states are reached only after CMD.hash_process, and the compression
states only while a 512-bit block is being digested, so the pulses are spread
across three landing points: mid-push, just after hash_process, and after the
message is complete but before the done event is cleared.

Mechanism: `SW_RESET_N.hmac_sw_rst_n` (`sep_reset_ctrl.sv:139`). Clearing it
raises `hmac_isolate_req` (:182-188); `sep_isolate_rst_seq` waits for the HMAC
host and KM AXI ports to isolate and then drops `isolated_rst_n.hmac`, the
`hmac_wrapper` `rst_ni`.

HMAC is not an EDN client: `sep_crypto.sv:429-477` wires the four
`crypto_edn_req` slots to OTBN RND, OTBN URND, AES and KMAC only. So this leaf
needs no entropy bring-up and cannot drop an ungranted entropy request.

Randomness: the offsets and message words come from `SepSeededRng` seeded with
the run seed, so `--stage sim --seed N` replays a given landing point. Nothing
derived from them leaves the simulation.

Safety: the HMAC bit is released after every pulse and `SW_RESET_N` is restored
in a `finally`.

no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import pyuvm
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from seq_lib.sep_cov_reset_arc_seq import SepCovEngineReset
from seq_lib.sep_hmac_seq import (
    HMAC_CMD,
    HMAC_CMD_HASH_PROCESS,
    HMAC_CMD_HASH_START,
    HMAC_MSG_FIFO,
    SepHmac,
)

# Message words per pass. Several 512-bit blocks, so the compressor is running
# while the push is still going.
MSG_WORDS = 64

# Words pushed before the mid-push pulse.
WORDS_BEFORE_PULSE = 24

# Offsets, in core clock cycles from the register write that precedes them, at
# which the reset request is raised. A SHA-256 compression is 64 rounds and the
# pad FSM walks StPad80, StPad00 and StLenHi in the few cycles after the last
# message word, so a spread this wide covers both. Which state a given offset
# hits is not claimed.
RESET_DELAY_MIN = 1
RESET_DELAY_MAX = 160

PASSES = 9


@pyuvm.test()
class sep_cov_hmac_reset_midmsg_test(sep_base_test):
    """Per-IP reset inside a running SHA-256 message. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        rng = SepSeededRng(self.random_seed())
        rst = SepCovEngineReset(self, "hmac")
        hmac = SepHmac(self)

        try:
            for idx in range(PASSES):
                stage = ("push", "process", "complete")[idx % 3]
                await self._pass(hmac, rst, rng, idx, stage)
        finally:
            await rst.restore()

        self.logger.info(
            "COV-STIM hmac_reset_midmsg: %d per-IP resets driven inside a running "
            "SHA-256 message",
            rst.pulses,
        )

    async def _pass(
        self, hmac: SepHmac, rst: SepCovEngineReset, rng, idx: int, stage: str
    ) -> None:
        # CFG is re-written every pass: the previous pass reset the domain, so
        # the engine comes back at its register reset values.
        await hmac.configure_sha256()
        await hmac._wr(HMAC_CMD, HMAC_CMD_HASH_START)

        words = MSG_WORDS if stage != "push" else WORDS_BEFORE_PULSE
        for _ in range(words):
            await hmac._wait_fifo_space()
            await hmac._wr(HMAC_MSG_FIFO, rng.getrandbits(32))

        delay = rst.delay(rng, RESET_DELAY_MIN, RESET_DELAY_MAX)
        if stage == "push":
            await rst.pulse(delay_cycles=delay, tag=f"sha256_push_{idx}")
            return

        await hmac._wr(HMAC_CMD, HMAC_CMD_HASH_PROCESS)
        if stage == "process":
            await rst.pulse(delay_cycles=delay, tag=f"sha256_process_{idx}")
            return

        # `_wait_done` is flow control on the engine's own INTR_STATE bit, not
        # a value compare: it says the pad and compressor have finished and the
        # done FSM is holding the completion.
        await hmac._wait_done()
        await rst.pulse(delay_cycles=delay, tag=f"sha256_complete_{idx}")
