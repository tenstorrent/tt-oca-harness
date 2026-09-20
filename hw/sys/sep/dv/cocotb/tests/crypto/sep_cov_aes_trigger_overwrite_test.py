# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Withdraw an AES clear request by rewriting TRIGGER before the clear starts,
so the main control FSM returns to idle with no work left to do.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more. STATUS is polled for flow control; no register value is compared.

Target,
`vendor/lowRISC/opentitan/upstream/hw/ip/aes/rtl/aes_control_fsm.sv:681-686`.
The CTRL_GHASH_READY case ends with

    end else if (key_iv_data_in_clear_i || data_out_clear_i ||
                 cipher_key_clear_i     || cipher_data_out_clear_i) begin
      if (ghash_in_ready_i) aes_ctrl_ns = CTRL_CLEAR_I;
    end else begin
      // Another write to the trigger register must have overwritten the
      // trigger bits that actually caused us to enter this state. Just return.
      aes_ctrl_ns = CTRL_IDLE;
    end

That last leg is the only CTRL_GHASH_READY -> CTRL_IDLE arc, and it is dark:
`seq_lib/sep_aes_seq.py` and `sep_cov_aes_key192_dec_clear_test` both set a
clear trigger and then let it run to completion, so the FSM always takes the
CTRL_CLEAR_I leg instead.

Stimulus, repeated over the three key lengths: programme AES, set TRIGGER with
KEY_IV_DATA_IN_CLEAR and DATA_OUT_CLEAR, then immediately write TRIGGER again
with those bits clear. The trigger bits are write-only pulses, so the second
write is the architected way for software to change its mind, and both writes
are legal accesses answered with OKAY. A seeded gap of a few cycles is inserted
between the two writes so the withdrawal lands at a different point of the
handshake on each pass.

Each key length finishes with a clear that is allowed to run, so the run does
not leave AES holding a half-withdrawn trigger for whatever shares the build.

AES masking stalls without entropy, so the run brings up the real
ESRC/DRBG/CSRNG/EDN stack first.

RANDCFG: the key words and the withdrawal gaps come from the run seed through
`SepSeededRng`. The key never leaves the simulation and no ciphertext is read.

no_cpu / +skip_fuse_sense / +esrc_noise_force.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import AES
from seq_lib.sep_aes_seq import (
    AES_CTRL_SHADOWED,
    AES_KEY_SHARE0_0,
    AES_KEY_SHARE1_0,
    AES_MODE_ECB,
    AES_OP_ENC,
    AES_STATUS,
    AES_STATUS_IDLE,
    AES_TRIGGER,
    AES_KEYLEN_CTRL,
    SepAes,
    build_aes_ctrl,
)

AES_TRIGGER_KEY_IV_DATA_IN_CLEAR = AES.field_mask("TRIGGER", "key_iv_data_in_clear")
AES_TRIGGER_DATA_OUT_CLEAR = AES.field_mask("TRIGGER", "data_out_clear")

CLEAR_BITS = AES_TRIGGER_KEY_IV_DATA_IN_CLEAR | AES_TRIGGER_DATA_OUT_CLEAR

KEY_BITS = (128, 192, 256)
WITHDRAWALS_PER_KEYLEN = 6

# The FSM reaches CTRL_GHASH_READY within a handful of cycles of the trigger
# write, so the withdrawal gap is swept across that short span.
GAP_MIN_CYCLES = 0
GAP_MAX_CYCLES = 12

STATUS_POLLS = 400
POLL_GAP_CYCLES = 10


@pyuvm.test()
class sep_cov_aes_trigger_overwrite_test(sep_base_test):
    """AES clear trigger withdrawn before the clear runs. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        from seq_lib.sep_esrc_bringup_seq import (
            SepEsrcConfigSeq,
            SepEsrcEnableEdnSeq,
            SepEsrcEnableGeneratorsSeq,
        )

        await self.bring_up_no_cpu()
        noise = self.start_esrc_noise_driver()
        try:
            await self.start_seq(SepEsrcConfigSeq("esrc_config"))
            await self.start_seq(SepEsrcEnableGeneratorsSeq("esrc_enable_gens"))
            if not await self.wait_seed_ready():
                raise AssertionError("stimulus precondition: ESRC never produced a seed")
            await self.start_seq(SepEsrcEnableEdnSeq("esrc_enable_edn"))

            self.aes = SepAes(self)
            rng = SepSeededRng(self.random_seed())
            for key_bits in KEY_BITS:
                await self._walk(rng, key_bits)
        finally:
            noise.kill()

    async def _poll_idle(self, label: str) -> None:
        for _ in range(STATUS_POLLS):
            st = await self.aes._rd(AES_STATUS)
            if st & (1 << AES_STATUS_IDLE):
                return
            await ClockCycles(cocotb.top.clk_i, POLL_GAP_CYCLES)
        self.logger.info("cov stimulus: AES STATUS.idle not seen at %s, continuing", label)

    async def _programme(self, rng: SepSeededRng, key_bits: int) -> None:
        ctrl = build_aes_ctrl(
            sideload=False,
            operation=AES_OP_ENC,
            mode=AES_MODE_ECB,
            key_len=AES_KEYLEN_CTRL[key_bits],
        )
        # CTRL_SHADOWED is shadowed: the value must be written twice.
        await self.aes._wr(AES_CTRL_SHADOWED, ctrl)
        await self.aes._wr(AES_CTRL_SHADOWED, ctrl)
        for i in range(8):
            await self.aes._wr(AES_KEY_SHARE0_0 + i * 4, rng.getrandbits(32))
            await self.aes._wr(AES_KEY_SHARE1_0 + i * 4, 0)
        await self._poll_idle(f"programmed aes-{key_bits}")

    async def _walk(self, rng: SepSeededRng, key_bits: int) -> None:
        await self._programme(rng, key_bits)

        span = GAP_MAX_CYCLES - GAP_MIN_CYCLES
        for idx in range(WITHDRAWALS_PER_KEYLEN):
            gap = GAP_MIN_CYCLES + (rng.getrandbits(16) % (span + 1))
            await self.aes._wr(AES_TRIGGER, CLEAR_BITS)
            if gap:
                await ClockCycles(cocotb.top.clk_i, gap)
            await self.aes._wr(AES_TRIGGER, 0)
            self.logger.info(
                "cov stimulus: aes-%d withdrawal %d -- clear trigger set then cleared "
                "%d cycles later",
                key_bits,
                idx,
                gap,
            )
            await self._poll_idle(f"aes-{key_bits} withdrawal {idx}")

        # Let one clear run to completion, so the engine is left settled.
        await self.aes._wr(AES_TRIGGER, CLEAR_BITS)
        await self._poll_idle(f"aes-{key_bits} completed clear")
        self.logger.info("cov stimulus: aes-%d clear allowed to complete", key_bits)
