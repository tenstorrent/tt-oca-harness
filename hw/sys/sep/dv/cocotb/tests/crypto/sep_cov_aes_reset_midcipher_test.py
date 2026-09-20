# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Hold the AES engine in per-IP software reset while a block is in the cipher
core, so its control FSMs return to idle from a running state.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more. No ciphertext is read back or compared.

Target: the FSM arcs whose destination is the FSM's own reset state and which
no `case` arm assigns anywhere. In the AES reset domain those are:

* `aes/rtl/aes_control_fsm.sv` `aes_ctrl_ns` -- 11 arcs into CTRL_IDLE or
  CTRL_ERROR, from CTRL_LOAD, CTRL_PRNG_RESEED, CTRL_FINISH, CTRL_CLEAR_I,
  CTRL_CLEAR_CO, CTRL_GHASH_READY, CTRL_IDLE and CTRL_ERROR.
* `aes/rtl/aes_cipher_control_fsm.sv` -- 10 into CIPHER_CTRL_IDLE or
  CIPHER_CTRL_ERROR, from CIPHER_CTRL_INIT, CIPHER_CTRL_ROUND,
  CIPHER_CTRL_FINISH, CIPHER_CTRL_CLEAR_S, CIPHER_CTRL_CLEAR_KD,
  CIPHER_CTRL_PRNG_RESEED, CIPHER_CTRL_IDLE and CIPHER_CTRL_ERROR.
* `aes/rtl/aes_ctr_fsm.sv` -- 3, and `aes/rtl/aes_ghash.sv` -- 16.
* `hw/common/axi/axi_lite_to_tlul.sv` and `hw/common/axi/tlul_to_axi_lite.sv`
  -- 4 each into IDLE; `aes_wrapper.sv` instantiates that bridge pair inside
  the engine's reset domain.

The CTR and GHASH arcs need the counter and GHASH blocks to be running when
the reset lands, so the leaf drives one CTR session and one GCM session in
addition to ECB. The GCM phase order follows `sep_cov_aes_gcm_phase_walk_test`,
which established that SEP's AES takes the vendor default `AESGCMEnable = 1`.

Mechanism: `SW_RESET_N.aes_sw_rst_n` (`sep_reset_ctrl.sv:140`). Clearing it
raises `aes_isolate_req` (:173-179); `sep_isolate_rst_seq` waits for the AES
host and KM AXI ports to isolate and then drops `isolated_rst_n.aes`, the
`aes_wrapper` `rst_ni`.

AES masking stalls without entropy, so the run brings up the real
ESRC/DRBG/CSRNG/EDN stack first. AES is an EDN client (`sep_crypto.sv:456`);
the leaf lets the post-reset masking reseed finish -- `wait_idle` before each
session -- before it starts the block it will interrupt, so the pulse lands
while the cipher core is running rather than while the PRNG reseed has an
ungranted `edn_req` outstanding.

Randomness: the offsets and the data come from `SepSeededRng` seeded with the
run seed, so `--stage sim --seed N` replays a given landing point. The key
words are stimulus for a simulation only; nothing derived from them leaves it.

Safety: the AES bit is released after every pulse and `SW_RESET_N` is restored
in a `finally`.

no_cpu / +skip_fuse_sense / +esrc_noise_force.
"""

from __future__ import annotations

import pyuvm
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import AES
from seq_lib.sep_aes_seq import (
    AES_KEY_LEN_128,
    AES_MODE_CTR,
    AES_MODE_ECB,
    AES_OP_ENC,
    SepAes,
)
from seq_lib.sep_cov_reset_arc_seq import SepCovEngineReset
from seq_lib.sep_esrc_bringup_seq import (
    SepEsrcConfigSeq,
    SepEsrcEnableEdnSeq,
    SepEsrcEnableGeneratorsSeq,
)

# MODE encoding for GCM, `aes_pkg.sv:123` (`AES_GCM = 6'b10_0000`); the Python
# mirror in seq_lib/sep_aes_seq.py stops at CTR.
AES_MODE_GCM = 0b10_0000

AES_CTRL_GCM_SHADOWED = AES.addr("CTRL_GCM_SHADOWED")
GCM_PHASE_LSB = AES.field_lsb("CTRL_GCM_SHADOWED", "phase")
GCM_NVB_LSB = AES.field_lsb("CTRL_GCM_SHADOWED", "num_valid_bytes")

# One-hot phase encodings, `aes_pkg.sv:150-157`.
GCM_INIT = 0b00_0001
GCM_TEXT = 0b00_1000
FULL_BLOCK_BYTES = 16

# Offsets, in core clock cycles after the last DATA_IN word, at which the reset
# request is raised. An AES-128 block is 10 rounds and a masked core spends
# extra cycles in its PRNG steps, so a spread this wide lands the reset on
# different rounds and on the load and finish states either side of them.
# Which state a given offset hits is not claimed.
RESET_DELAY_MIN = 1
RESET_DELAY_MAX = 120

PASSES_PER_MODE = 5


@pyuvm.test()
class sep_cov_aes_reset_midcipher_test(sep_base_test):
    """Per-IP reset inside a running AES block. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        rng = SepSeededRng(self.random_seed())
        noise = self.start_esrc_noise_driver()
        rst = SepCovEngineReset(self, "aes")
        aes = SepAes(self)

        try:
            await self.start_seq(SepEsrcConfigSeq("esrc_config"))
            await self.start_seq(SepEsrcEnableGeneratorsSeq("esrc_enable_gens"))
            if not await self.wait_seed_ready():
                raise AssertionError("stimulus precondition: ESRC never produced a seed")
            await self.start_seq(SepEsrcEnableEdnSeq("esrc_enable_edn"))

            for idx in range(PASSES_PER_MODE):
                await self._block_pass(aes, rst, rng, idx, AES_MODE_ECB, "ecb")
            for idx in range(PASSES_PER_MODE):
                await self._block_pass(aes, rst, rng, idx, AES_MODE_CTR, "ctr")
            for idx in range(PASSES_PER_MODE):
                await self._gcm_pass(aes, rst, rng, idx)
        finally:
            noise.kill()
            await rst.restore()

        self.logger.info(
            "COV-STIM aes_reset_midcipher: %d per-IP resets driven inside a running "
            "AES block across ECB, CTR and GCM",
            rst.pulses,
        )

    def _key(self, rng) -> list[int]:
        return [rng.getrandbits(32) for _ in range(4)]

    async def _block_pass(
        self, aes: SepAes, rst: SepCovEngineReset, rng, idx: int, mode: int, tag: str
    ) -> None:
        # `configure` ends in `wait_idle`, so the post-reset masking reseed has
        # completed before the block that this pass interrupts is started.
        await aes.configure(mode=mode, key_len=AES_KEY_LEN_128, operation=AES_OP_ENC)
        iv = [rng.getrandbits(32) for _ in range(4)] if mode == AES_MODE_CTR else None
        await aes.load_key_iv(self._key(rng), iv)
        await aes.start_block_no_wait([rng.getrandbits(32) for _ in range(4)])
        delay = rst.delay(rng, RESET_DELAY_MIN, RESET_DELAY_MAX)
        await rst.pulse(delay_cycles=delay, tag=f"{tag}_block_{idx}")

    async def _gcm_pass(self, aes: SepAes, rst: SepCovEngineReset, rng, idx: int) -> None:
        await aes.configure(mode=AES_MODE_GCM, key_len=AES_KEY_LEN_128, operation=AES_OP_ENC)
        # J0: a 96-bit IV followed by the initial counter value 1.
        iv = [rng.getrandbits(32) for _ in range(3)] + [1]
        await aes.load_key_iv(self._key(rng), iv)

        # GCM_INIT takes no input block; it runs the cipher over J0 and arms
        # the GHASH block. GCM_TEXT then both consumes and produces one block,
        # so the reset lands with the GHASH FSM active.
        await aes._wr(AES_CTRL_GCM_SHADOWED, self._gcm_ctrl(GCM_INIT))
        await aes.wait_idle(f"gcm-init {idx}")
        await aes._wr(AES_CTRL_GCM_SHADOWED, self._gcm_ctrl(GCM_TEXT))
        await aes.start_block_no_wait([rng.getrandbits(32) for _ in range(4)])
        delay = rst.delay(rng, RESET_DELAY_MIN, RESET_DELAY_MAX)
        await rst.pulse(delay_cycles=delay, tag=f"gcm_text_{idx}")

    @staticmethod
    def _gcm_ctrl(phase: int) -> int:
        return (phase << GCM_PHASE_LSB) | (FULL_BLOCK_BYTES << GCM_NVB_LSB)
