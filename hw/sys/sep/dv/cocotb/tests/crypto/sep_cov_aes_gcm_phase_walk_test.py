# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Walk the AES GCM phase sequence so the GHASH block runs.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more.

Target: `aes_ghash` holds 114 uncovered lines in the merged VCS run
`build/runs/20260919_225443__vcs__all`, and every one of them sits under a
`gcm_phase_i` arm of the GHASH FSM -- GCM_INIT at
`vendor/lowRISC/opentitan/upstream/hw/ip/aes/rtl/aes_ghash.sv:684`, GCM_RESTORE
at :710, GCM_AAD/GCM_TEXT at :725, GCM_SAVE at :755, and the GHASH_ADD_S,
GHASH_MULT and GHASH_MASKED_* states that follow them. SEP's AES instance takes
the vendor default `AESGCMEnable = 1` (`aes.sv:14`; `hw/sys/sep/rtl/aes_wrapper.sv:134`
overrides no parameter), so `aes_ctrl_reg_shadowed.sv:88-96` passes a
CTRL_SHADOWED.MODE of AES_GCM through instead of remapping it to AES_NONE, and
`aes_core.sv:584` elaborates the GHASH block. `sep_aes_mode_keysize_rand_test`
walks ECB, CBC and CTR only, so no leaf has ever selected GCM.

Stimulus: one AES-128 encrypt session over CTRL_GCM_SHADOWED
(`AES_CTRL_GCM_SHADOWED_REG_ADDR`, 0x1091_0088), driving each phase in a legal
successor order taken from the register map -- INIT, AAD (full then partial
block), TEXT (full then partial block), SAVE, then INIT again followed by
RESTORE, TEXT and TAG. The partial blocks set NUM_VALID_BYTES below 16, which
the register map allows in GCM_AAD and GCM_TEXT only.

Phase start conditions come from `aes_control_fsm.sv:286-316`: GCM_INIT and
GCM_SAVE take no input data, GCM_RESTORE, GCM_AAD and GCM_TAG consume a
DATA_IN block, and GCM_TEXT both consumes and produces one. The test follows
that split. STATUS is polled for flow control -- idle before the next phase
write, OUTPUT_VALID before a DATA_OUT read -- and the values read are logged,
never compared. The block handed to GCM_RESTORE is the block GCM_SAVE produced,
which is sequencing, not a check: this leaf does not claim the save/restore
pair round-trips.

AES masking stalls without entropy, so the run brings up the real
ESRC/DRBG/CSRNG/EDN stack first, in the stimulus-only order that
`tests/system/sep_cov_entropy_pool_burst_test.py` uses, and reseeds the masking
PRNG before the session.

no_cpu / +skip_fuse_sense / +esrc_noise_force.
"""

from __future__ import annotations

import pyuvm
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import AES
from seq_lib.sep_aes_seq import (
    AES_DATA_IN_0,
    AES_KEY_LEN_128,
    AES_OP_ENC,
    SepAes,
)
from seq_lib.sep_esrc_bringup_seq import (
    SepEsrcConfigSeq,
    SepEsrcEnableEdnSeq,
    SepEsrcEnableGeneratorsSeq,
)

# MODE encoding for GCM, from `aes_pkg.sv:123` (`AES_GCM = 6'b10_0000`). The
# Python mirror in seq_lib/sep_aes_seq.py stops at CTR.
AES_MODE_GCM = 0b10_0000

AES_CTRL_GCM_SHADOWED = AES.addr("CTRL_GCM_SHADOWED")
GCM_PHASE_LSB = AES.field_lsb("CTRL_GCM_SHADOWED", "phase")
GCM_NVB_LSB = AES.field_lsb("CTRL_GCM_SHADOWED", "num_valid_bytes")

# One-hot phase encodings, `aes_pkg.sv:150-157`.
GCM_INIT = 0b00_0001
GCM_RESTORE = 0b00_0010
GCM_AAD = 0b00_0100
GCM_TEXT = 0b00_1000
GCM_SAVE = 0b01_0000
GCM_TAG = 0b10_0000

FULL_BLOCK_BYTES = 16
PARTIAL_BLOCK_BYTES = 5

# Bound on a DATA_OUT poll. A single AES-128 block settles in far fewer reads;
# the cap keeps a phase that never produces output from spending the run
# timeout in one loop.
OUTPUT_POLLS = 400


def gcm_ctrl(phase: int, num_valid_bytes: int = FULL_BLOCK_BYTES) -> int:
    """CTRL_GCM_SHADOWED word for one phase and input-block length."""
    return (phase << GCM_PHASE_LSB) | (num_valid_bytes << GCM_NVB_LSB)


@pyuvm.test()
class sep_cov_aes_gcm_phase_walk_test(sep_base_test):
    """AES GCM phase walk over the GHASH block. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        noise = self.start_esrc_noise_driver()
        try:
            await self.start_seq(SepEsrcConfigSeq("esrc_config"))
            await self.start_seq(SepEsrcEnableGeneratorsSeq("esrc_enable_gens"))
            if not await self.wait_seed_ready():
                raise AssertionError("stimulus precondition: ESRC never produced a seed")
            await self.start_seq(SepEsrcEnableEdnSeq("esrc_enable_edn"))

            await self._gcm_session()
        finally:
            noise.kill()

    async def _gcm_session(self) -> None:
        aes = SepAes(self)
        rng = SepSeededRng(self.random_seed())
        key = [rng.getrandbits(32) for _ in range(4)]
        # J0: the 96-bit IV followed by the initial 32-bit counter value 1,
        # which is the counter block GCM starts from.
        iv = [rng.getrandbits(32) for _ in range(3)] + [1]

        await aes.configure(mode=AES_MODE_GCM, key_len=AES_KEY_LEN_128, operation=AES_OP_ENC)
        await aes.trigger_prng_reseed()
        await aes.load_key_iv(key, iv)

        # GCM_INIT takes no input block: the core derives the hash subkey and
        # encrypts J0 on its own (aes_control_fsm.sv:286-288).
        await self._phase(aes, "INIT", GCM_INIT)

        await self._phase(aes, "AAD full", GCM_AAD, data=[rng.getrandbits(32) for _ in range(4)])
        await self._phase(
            aes,
            "AAD partial",
            GCM_AAD,
            data=[rng.getrandbits(32) for _ in range(4)],
            num_valid_bytes=PARTIAL_BLOCK_BYTES,
        )

        await self._phase(
            aes, "TEXT full", GCM_TEXT, data=[rng.getrandbits(32) for _ in range(4)], read_out=True
        )
        await self._phase(
            aes,
            "TEXT partial",
            GCM_TEXT,
            data=[rng.getrandbits(32) for _ in range(4)],
            num_valid_bytes=PARTIAL_BLOCK_BYTES,
            read_out=True,
        )

        # GCM_SAVE takes no input and emits the running GHASH state.
        saved = await self._phase(aes, "SAVE", GCM_SAVE, read_out=True)

        # A second INIT re-derives the hash subkey so RESTORE has somewhere to
        # load the saved state into.
        await self._phase(aes, "INIT (second)", GCM_INIT)
        if saved is not None:
            await self._phase(aes, "RESTORE", GCM_RESTORE, data=saved)
        await self._phase(
            aes,
            "TEXT after restore",
            GCM_TEXT,
            data=[rng.getrandbits(32) for _ in range(4)],
            read_out=True,
        )

        # GCM_TAG consumes the length block and emits the tag.
        length_block = [0, 2 * 128, 0, 2 * 128]
        await self._phase(aes, "TAG", GCM_TAG, data=length_block, read_out=True)

    async def _phase(
        self,
        aes: SepAes,
        label: str,
        phase: int,
        *,
        data: list[int] | None = None,
        num_valid_bytes: int = FULL_BLOCK_BYTES,
        read_out: bool = False,
    ) -> list[int] | None:
        """Select one GCM phase, feed it its input block if it takes one, and
        collect its output block if it produces one."""
        ctrl = gcm_ctrl(phase, num_valid_bytes)
        # CTRL_GCM_SHADOWED is shadowed: the value must be written twice.
        await aes._wr(AES_CTRL_GCM_SHADOWED, ctrl)
        await aes._wr(AES_CTRL_GCM_SHADOWED, ctrl)

        if data is not None:
            for i, word in enumerate(data):
                await aes._wr(AES_DATA_IN_0 + 4 * i, word & 0xFFFF_FFFF)

        out: list[int] | None = None
        if read_out:
            if await aes.output_valid_within(OUTPUT_POLLS):
                out = await aes.read_data_out()
                self.logger.info(
                    "cov stimulus: GCM %s produced a block (0x%08x ...), logged not graded",
                    label,
                    out[0],
                )
            else:
                self.logger.info("cov stimulus: GCM %s produced no output inside the poll", label)

        await aes.wait_idle(f"gcm-{label}")
        self.logger.info(
            "cov stimulus: drove GCM phase %s (CTRL_GCM=0x%08x, num_valid_bytes=%d)",
            label,
            ctrl,
            num_valid_bytes,
        )
        return out
