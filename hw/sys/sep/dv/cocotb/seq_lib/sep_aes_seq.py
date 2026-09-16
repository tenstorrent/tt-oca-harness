# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OpenTitan AES run-control driver (direct AXI on the SEP CPU-LSU bus).

Configures the AES core for ECB-256 encryption, writes the key shares / data,
triggers the masking-PRNG reseed, and runs one block, mirroring the AES op
helpers in the reference sep_km_aes_sideload_kat_test_seq (RAL there; direct AXI
here, like SepOtbn). All accesses are 32-bit beats (size=2): the AES register
block is 32-bit behind the wrapper's 64->32 dw-converter.

AES register map (base from the generated SEP header; offsets from aes.adoc):
  KEY_SHARE0_0..7 @ 0x04..0x20   KEY_SHARE1_0..7 @ 0x24..0x40
  DATA_IN_0..3    @ 0x54..0x60   DATA_OUT_0..3   @ 0x64..0x70
  CTRL_SHADOWED   @ 0x74 (shadowed: written twice)
  TRIGGER         @ 0x80         STATUS          @ 0x84
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
from cocotb.triggers import ClockCycles
from sep_reg_meta import AES, sym

from seq_lib.sep_axi_reg_driver import SepAxiRegDriver

AES_BASE = sym("AES_REG_MAP_BASE_ADDR")
AES_KEY_SHARE0_0 = sym("AES_KEY_SHARE0_0__REG_ADDR")
AES_KEY_SHARE1_0 = sym("AES_KEY_SHARE1_0__REG_ADDR")
AES_IV_0 = sym("AES_IV_0__REG_ADDR")
AES_DATA_IN_0 = sym("AES_DATA_IN_0__REG_ADDR")
AES_DATA_OUT_0 = sym("AES_DATA_OUT_0__REG_ADDR")
AES_CTRL_SHADOWED = AES.addr("CTRL_SHADOWED")
AES_TRIGGER = AES.addr("TRIGGER")
AES_STATUS = AES.addr("STATUS")

# CTRL_SHADOWED field encodings (vendor/lowRISC/opentitan/overlay/regs/aes/regs/gen/adoc/aes.adoc):
#   OPERATION[1:0]=01 ENC, MODE[7:2]=000001 ECB, KEY_LEN[10:8]=100 AES-256,
#   SIDELOAD[11], PRNG_RESEED_RATE[14:12]=100 PER_8K, MANUAL_OPERATION[15]=0.
AES_OP_ENC = 0b01
AES_OP_DEC = 0b10
AES_MODE_ECB = 0b00_0001
AES_MODE_CBC = 0b00_0010
AES_MODE_CTR = 0b01_0000
AES_KEY_LEN_128 = 0b001
AES_KEY_LEN_192 = 0b010
AES_KEY_LEN_256 = 0b100
AES_PRS_RATE_PER_8K = 0b100

# mode name / key-bit-width -> CTRL_SHADOWED field encodings (aes.adoc).
AES_MODE_CTRL = {"ecb": AES_MODE_ECB, "cbc": AES_MODE_CBC, "ctr": AES_MODE_CTR}
AES_KEYLEN_CTRL = {128: AES_KEY_LEN_128, 192: AES_KEY_LEN_192, 256: AES_KEY_LEN_256}

# STATUS bit positions from the generated field layout.
AES_STATUS_IDLE = AES.field_lsb("STATUS", "idle")
AES_STATUS_OUTPUT_VALID = AES.field_lsb("STATUS", "output_valid")
AES_STATUS_INPUT_READY = AES.field_lsb("STATUS", "input_ready")
# AES's own alert bits in STATUS: a shadowed-register write mismatch (recoverable)
# or a fatal fault. Both must stay 0 across a clean run.
AES_STATUS_ALERT_RECOV_CTRL_UPDATE_ERR = AES.field_lsb("STATUS", "alert_recov_ctrl_update_err")
AES_STATUS_ALERT_FATAL_FAULT = AES.field_lsb("STATUS", "alert_fatal_fault")

AES_TRIGGER_PRNG_RESEED = AES.field_mask("TRIGGER", "prng_reseed")
AES_TRIGGER_DATA_OUT_CLEAR = AES.field_mask("TRIGGER", "data_out_clear")


def build_aes_ctrl(
    *,
    sideload: bool,
    operation: int = AES_OP_ENC,
    mode: int = AES_MODE_ECB,
    key_len: int = AES_KEY_LEN_256,
    reseed_rate: int = AES_PRS_RATE_PER_8K,
) -> int:
    """CTRL_SHADOWED word. OPERATION selects ENC/DEC, MODE the cipher mode
    (ECB/CBC/CTR), KEY_LEN the key width (128/192/256), SIDELOAD the KM key vs
    KEY_SHARE. Defaults are ECB-256 (the KM AES sideload KAT path)."""
    return (
        operation
        | (mode << 2)
        | (key_len << 8)
        | ((1 if sideload else 0) << 11)
        | (reseed_rate << 12)
    )


@dataclass
class SepAesCfg:
    """Single source of truth for one AES mode x key-size cell: drives BOTH the
    DUT programming (CTRL + key + IV + data) and the golden (env/sep_aes_golden
    ``aes_encrypt_words``). SW key (SIDELOAD=0); ``iv_words`` required for CBC/CTR."""

    mode: str  # "ecb"/"cbc"/"ctr"
    key_bits: int  # 128/192/256
    key_words: list[int]  # KEY_SHARE0 words (len = key_bits/32)
    pt_words: list[int]  # DATA_IN words (multiple of 4)
    iv_words: list[int] | None = None
    operation: int = AES_OP_ENC

    def mode_ctrl(self) -> int:
        return AES_MODE_CTRL[self.mode]

    def keylen_ctrl(self) -> int:
        return AES_KEYLEN_CTRL[self.key_bits]

    def golden_kwargs(self) -> dict:
        return dict(
            mode=self.mode, key_words=self.key_words, pt_words=self.pt_words, iv_words=self.iv_words
        )


class SepAes(SepAxiRegDriver):
    """Direct-AXI OpenTitan AES run control. The test owns one instance."""

    _DRIVER_TAG = "AES"

    async def _poll_status_bit(
        self, bitpos: int, tag: str, *, timeout: int = 4_000, poll_cycles: int = 20
    ) -> None:
        for i in range(timeout):
            st = await self._rd(AES_STATUS)
            if st & (1 << bitpos):
                return
            if i and i % 500 == 0:
                self.log.info("AES wait %s: poll %d, STATUS=0x%08x", tag, i, st)
            await ClockCycles(cocotb.top.clk_i, poll_cycles)
        raise AssertionError(f"AES {tag} timeout (STATUS bit {bitpos} never set)")

    async def wait_idle(self, tag: str = "idle") -> None:
        await self._poll_status_bit(AES_STATUS_IDLE, tag)

    async def check_status_clean(self, tag: str = "EOT") -> None:
        """Assert AES raised neither alert: STATUS.ALERT_RECOV_CTRL_UPDATE_ERR
        (a shadowed CTRL write mismatch) nor STATUS.ALERT_FATAL_FAULT. Tightens
        the run's no-error evidence alongside the CSRNG/EDN alert check."""
        st = await self._rd(AES_STATUS)
        recov = (st >> AES_STATUS_ALERT_RECOV_CTRL_UPDATE_ERR) & 1
        fatal = (st >> AES_STATUS_ALERT_FATAL_FAULT) & 1
        assert recov == 0 and fatal == 0, (
            f"AES alert set [{tag}]: STATUS=0x{st:08x} "
            f"(recov_ctrl_update_err={recov}, fatal_fault={fatal})"
        )
        self.log.info("AES STATUS clean [%s]: no recoverable/fatal alert (0x%08x)", tag, st)

    async def _configure_ecb_256(self, *, sideload: bool, operation: int, op_name: str) -> None:
        """Write CTRL_SHADOWED twice (shadowed register) for ECB-256 ENC/DEC."""
        ctrl = build_aes_ctrl(sideload=sideload, operation=operation)
        await self._wr(AES_CTRL_SHADOWED, ctrl)
        await self._wr(AES_CTRL_SHADOWED, ctrl)
        await self.wait_idle("post-config")
        self.log.info(
            "AES configured ECB-256 %s sideload=%d (CTRL=0x%08x)", op_name, sideload, ctrl
        )

    async def configure_ecb_enc_256(self, *, sideload: bool) -> None:
        await self._configure_ecb_256(sideload=sideload, operation=AES_OP_ENC, op_name="ENC")

    async def configure_ecb_dec_256(self, *, sideload: bool) -> None:
        await self._configure_ecb_256(sideload=sideload, operation=AES_OP_DEC, op_name="DEC")

    def _key_mask_rng(self):
        """Independent stream for KEY_SHARE1, so the share draws do not consume
        the test's RAND-REP key/pt stream. ``0xA5E5`` is a domain tag, not a credential."""
        rng = getattr(self, "_key_mask_rng_inst", None)
        if rng is None:
            from env.sep_seeded_rng import SepSeededRng

            rng = SepSeededRng(int(self.test.random_seed()) ^ 0xA5E5)
            self._key_mask_rng_inst = rng
        return rng

    async def write_full_key(self, key_words: list[int]) -> None:
        """Write an AES-256 SW key as two shares (``write_key``)."""
        assert len(key_words) == 8, "AES-256 SW key needs 8 words"
        await self.write_key(key_words)

    async def write_key(self, key_words: list[int]) -> None:
        """Write a 128/192/256-bit SW key as two non-zero shares.

        OpenTitan requires all 8 words of both shares each time (unused
        upper key words are 0). ``SHARE0 ^ SHARE1`` is the effective key
        the golden uses. ``KEY_SHARE1 = 0`` is the documented unmask path
        (aes CTRL_AUX FORCE_MASKS) and fails ``AesSecCmKeyMaskingStateShare``
        because AddRoundKey on the mask share is then a no-op.
        """
        assert len(key_words) in (4, 6, 8), "AES key = 4/6/8 words (128/192/256)"
        padded = [(w & 0xFFFF_FFFF) for w in key_words] + [0] * (8 - len(key_words))
        rng = self._key_mask_rng()
        share1 = [rng.getrandbits(32) for _ in range(8)]
        if all(w == 0 for w in share1):
            share1[0] = 1
        share0 = [(padded[i] ^ share1[i]) & 0xFFFF_FFFF for i in range(8)]
        for i in range(8):
            await self._wr(AES_KEY_SHARE0_0 + i * 4, share0[i])
            await self._wr(AES_KEY_SHARE1_0 + i * 4, share1[i])

    async def write_iv(self, iv_words: list[int]) -> None:
        """Write IV_0..3 (little-endian words). Required for CBC/CTR, unused ECB."""
        assert len(iv_words) == 4, "AES IV = 4 words (128-bit)"
        for i, word in enumerate(iv_words):
            await self._wr(AES_IV_0 + i * 4, word & 0xFFFF_FFFF)

    async def load_key_iv(self, key_words: list[int], iv_words: list[int] | None = None) -> None:
        """Spec-ordered SW key + IV load (aes programmers_guide.md): a KEY write
        kicks off a PRNG reseed, and any KEY/IV write while the unit is NOT idle is
        IGNORED. So wait for idle after the key before writing the IV, else CBC/CTR
        never receives its IV and the engine never starts. Caller configures
        CTRL_SHADOWED first (``configure`` already waits idle)."""
        await self.write_key(key_words)
        await self.wait_idle("post-key")
        if iv_words is not None:
            await self.write_iv(iv_words)
            await self.wait_idle("post-iv")
        # Seed the masking PRD buffer before the first crypt. ``prd_sub_bytes_q``
        # resets to 0 and loads live PRNG output on any ``state_we``, so a crypt
        # issued straight out of reset masks its data-in with a zero share and
        # ``AesSecCmKeyMaskingStateShare`` reads a share that never changes.
        # ``DATA_OUT_CLEAR`` raises ``state_we`` without starting a crypt, so the
        # buffer holds a real mask by the first block and the assertion is armed
        # from it. The key and the IV are untouched.
        await self._clear_data_out()

    async def configure(
        self, *, mode: int, key_len: int, operation: int = AES_OP_ENC, sideload: bool = False
    ) -> None:
        """Configure CTRL_SHADOWED for a mode/key-length (double-write, wait idle)."""
        ctrl = build_aes_ctrl(sideload=sideload, operation=operation, mode=mode, key_len=key_len)
        await self._wr(AES_CTRL_SHADOWED, ctrl)
        await self._wr(AES_CTRL_SHADOWED, ctrl)
        await self.wait_idle("post-config")
        self.log.info(
            "AES configured CTRL=0x%08x (mode=0x%02x key_len=0x%x op=%d sideload=%d)",
            ctrl,
            mode,
            key_len,
            operation,
            sideload,
        )

    async def run_blocks(self, pt_words: list[int]) -> list[int]:
        """Encrypt/decrypt consecutive 128-bit blocks; the HW auto-chains the IV
        (CBC) / increments the counter (CTR) across successive blocks."""
        assert len(pt_words) % 4 == 0, "AES data must be whole 128-bit blocks"
        out: list[int] = []
        for i in range(0, len(pt_words), 4):
            out += await self.run_ecb_block(pt_words[i : i + 4])
        return out

    async def read_public_key_shares(self) -> tuple[list[int], list[int], int]:
        """Read the public KEY_SHARE0/1 CSRs, plus a positive control.

        These key registers are declared write-only, and the generated register
        block ties their read data to zero. That has a consequence worth stating
        plainly: reading them back as zero is NOT by itself evidence that the
        sideloaded key is unexposed -- they would read zero even if the key were
        mirrored somewhere else, and even if the transfer never happened. What
        the readback can do is catch the day someone makes them readable.

        For that to be worth anything the read path has to be known alive, so we
        also return STATUS, a readable register in the same CSR window reached
        over the same bus. A caller that asserts the shares are zero must also
        assert the control read is non-zero; otherwise a dead read path returning
        zeros for everything would look identical to a pass.
        """
        s0 = [await self._rd(AES_KEY_SHARE0_0 + i * 4) for i in range(8)]
        s1 = [await self._rd(AES_KEY_SHARE1_0 + i * 4) for i in range(8)]
        control = await self._rd(AES_STATUS)
        return s0, s1, control

    async def _clear_data_out(self) -> None:
        """Pulse DATA_OUT_CLEAR and wait idle. Fills the masking PRD buffer."""
        await self._wr(AES_TRIGGER, AES_TRIGGER_DATA_OUT_CLEAR)
        await self.wait_idle("post-data-out-clear")

    async def trigger_prng_reseed(self) -> None:
        """Reseed the masking PRNG from the entropy source, then wait idle."""
        await self._wr(AES_TRIGGER, AES_TRIGGER_PRNG_RESEED)
        await self.wait_idle("post-prng-reseed")
        await self._clear_data_out()

    async def run_ecb_block(self, pt_words: list[int]) -> list[int]:
        """Run one ECB block: write DATA_IN, wait OUTPUT_VALID, read DATA_OUT."""
        assert len(pt_words) == 4, "AES block needs 4 data words"
        await self._poll_status_bit(AES_STATUS_INPUT_READY, "input_ready")
        for i, word in enumerate(pt_words):
            await self._wr(AES_DATA_IN_0 + i * 4, word & 0xFFFF_FFFF)
        await self._poll_status_bit(AES_STATUS_OUTPUT_VALID, "output_valid")
        return await self.read_data_out()

    async def output_valid_within(self, polls: int, *, poll_cycles: int = 20) -> bool:
        """Bounded probe: did OUTPUT_VALID assert within this window?

        Returns rather than raises, because a caller proving the engine must
        REFUSE to start needs the negative as a result, not as an error. Keep
        the window short: it is spent in full on every passing run.
        """
        for _ in range(polls):
            if await self._rd(AES_STATUS) & (1 << AES_STATUS_OUTPUT_VALID):
                return True
            await ClockCycles(cocotb.top.clk_i, poll_cycles)
        return False

    async def start_block_no_wait(self, pt_words: list[int]) -> None:
        """Write one input block and return without waiting for a result."""
        assert len(pt_words) == 4, "AES block needs 4 data words"
        await self._poll_status_bit(AES_STATUS_INPUT_READY, "input_ready")
        for i, word in enumerate(pt_words):
            await self._wr(AES_DATA_IN_0 + i * 4, word & 0xFFFF_FFFF)

    async def read_data_out(self) -> list[int]:
        """Read DATA_OUT_0..3. Re-readable: AES holds the last ciphertext in the
        output registers until the next block output, an explicit DATA_OUT_CLEAR
        trigger, or a reset of the AES domain (no auto-clear on read by default)."""
        return [await self._rd(AES_DATA_OUT_0 + i * 4) for i in range(4)]
