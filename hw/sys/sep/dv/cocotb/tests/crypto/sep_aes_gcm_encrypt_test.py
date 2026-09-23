# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AES-GCM encryption against a published GCM test vector (no_cpu, SW key).

AES_GCM is a supported mode of this AES instance: `aes_pkg.sv:123` defines the
MODE encoding, `AESGCMEnable` defaults to 1 and `hw/sys/sep/rtl/aes_wrapper.sv`
overrides no parameter, so `aes_core.sv` elaborates the GHASH block.
`sep_aes_mode_keysize_rand_test` walks ECB, CBC and CTR, so GCM is the one
supported mode with no graded leaf: nothing in this environment has ever
compared a GCM ciphertext or an authentication tag against a reference.

Vector: Test Case 3 of the GCM specification (McGrew and Viega, also carried in
the NIST CAVP GCM vector set) -- AES-128, a 96-bit IV, no AAD, and a plaintext
of four whole 128-bit blocks. The golden is the published ciphertext and tag,
transcribed as a constant. It is never recomputed here and never read from the
DUT.

Phase sequence, from the register map and `aes_control_fsm.sv:286-316`:
GCM_INIT takes no input block and derives the hash subkey and the encrypted
J0; GCM_TEXT consumes and produces one block; GCM_TAG consumes the length
block and produces the tag. With no AAD the GCM_AAD phase is skipped, which is
what the vector specifies.

The length block is the GCM trailer: the AAD length and the ciphertext length,
each a 64-bit big-endian bit count.

Word packing is little-endian per 32-bit register word throughout, the AES
register convention (`env/sep_aes_golden.py`).

Entropy: AES masking reseeds its PRNG from the crypto-EDN leg, so the run
brings up the real ESRC/DRBG/CSRNG/EDN stack first (+esrc_noise_force) or the
engine stalls. The other crypto clients are parked so AES is the only EDN sink.

Checkers:
  CHK-GCM-CIPHERTEXT  engine ciphertext == the vector's ciphertext, all 4 blocks
  CHK-GCM-TAG         engine tag == the vector's tag
  CHK-STATUS          no AES recoverable or fatal alert across the session

Pass Criteria: both value checks PASS and UVM_ERROR == 0.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from sep_base_test import sep_base_test
from sep_reg_meta import AES
from seq_lib.sep_aes_seq import (
    AES_DATA_IN_0,
    AES_KEY_LEN_128,
    AES_OP_ENC,
    AES_STATUS_INPUT_READY,
    SepAes,
)

# MODE encoding for GCM, from `aes_pkg.sv:123` (`AES_GCM = 6'b10_0000`). The
# Python mirror in seq_lib/sep_aes_seq.py stops at CTR.
AES_MODE_GCM = 0b10_0000

AES_CTRL_GCM_SHADOWED = AES.addr("CTRL_GCM_SHADOWED")
GCM_PHASE_LSB = AES.field_lsb("CTRL_GCM_SHADOWED", "phase")
GCM_NVB_LSB = AES.field_lsb("CTRL_GCM_SHADOWED", "num_valid_bytes")

# One-hot phase encodings, `aes_pkg.sv:150-157`.
GCM_INIT = 0b00_0001
GCM_TEXT = 0b00_1000
GCM_TAG = 0b10_0000

BLOCK_BYTES = 16

# Cycles to let a no-output phase run before polling idle. GCM_INIT is the
# longest of them at two AES-128 block encryptions; this is well past that.
SETTLE_CYCLES = 4000

# --- GCM specification Test Case 3: AES-128, 96-bit IV, no AAD, 4 blocks ---
KEY = bytes.fromhex("feffe9928665731c6d6a8f9467308308")
IV = bytes.fromhex("cafebabefacedbaddecaf888")
PLAINTEXT = bytes.fromhex(
    "d9313225f88406e5a55909c5aff5269a"
    "86a7a9531534f7da2e4c303d8a318a72"
    "1c3c0c95956809532fcf0e2449a6b525"
    "b16aedf5aa0de657ba637b391aafd255"
)
GOLDEN_CIPHERTEXT = bytes.fromhex(
    "42831ec2217774244b7221b784d0d49c"
    "e3aa212f2c02a4e035c17e2329aca12e"
    "21d514b25466931c7d8f6a5aac84aa05"
    "1ba30b396a0aac973d58e091473f5985"
)
GOLDEN_TAG = bytes.fromhex("4d5c2af327cd64a62cf35abd2ba6fab4")
AAD_BITS = 0
CIPHERTEXT_BITS = len(PLAINTEXT) * 8


def _to_words(data: bytes) -> list[int]:
    """Byte stream -> register words, little-endian per 32-bit word."""
    return [int.from_bytes(data[i : i + 4], "little") for i in range(0, len(data), 4)]


def _to_bytes(words: list[int]) -> bytes:
    return b"".join((w & 0xFFFF_FFFF).to_bytes(4, "little") for w in words)


def _gcm_ctrl(phase: int, num_valid_bytes: int = BLOCK_BYTES) -> int:
    return (phase << GCM_PHASE_LSB) | (num_valid_bytes << GCM_NVB_LSB)


def _length_block() -> bytes:
    """The GCM trailer: 64-bit big-endian AAD bit count, then ciphertext."""
    return AAD_BITS.to_bytes(8, "big") + CIPHERTEXT_BITS.to_bytes(8, "big")


@pyuvm.test()
class sep_aes_gcm_encrypt_test(sep_base_test):
    """AES-GCM encrypt: ciphertext and tag against a published vector."""

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu(park=("otbn", "hmac", "kmac"))
        await self.bring_up_entropy(strict=False, score_km=False)
        self.start_fifo_drain()
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"

        aes = SepAes(self)
        await aes.configure(
            mode=AES_MODE_GCM, key_len=AES_KEY_LEN_128, operation=AES_OP_ENC
        )
        await aes.trigger_prng_reseed()
        # J0 for a 96-bit IV is the IV followed by the 32-bit counter value 1.
        await aes.load_key_iv(_to_words(KEY), _to_words(IV + (1).to_bytes(4, "big")))

        # GCM_INIT encrypts two blocks back to back, one for the hash subkey
        # and one for S (`aes_control_fsm.sv:286-287`, gated on
        # `~hash_subkey_ready_q` and `~s_ready_q`). It is written ONCE: a
        # second write with the phase still at INIT re-raises `gcm_clear`
        # (`aes_control_fsm.sv:1072`) and discards both. The phase stays
        # selected while the engine works, so the wait below is what has to
        # cover the two blocks.
        await self._phase(aes, "INIT", GCM_INIT)

        ciphertext = b""
        for i in range(0, len(PLAINTEXT), BLOCK_BYTES):
            block = await self._phase(
                aes,
                f"TEXT block {i // BLOCK_BYTES}",
                GCM_TEXT,
                data=PLAINTEXT[i : i + BLOCK_BYTES],
                read_out=True,
            )
            assert block is not None, (
                f"AES produced no output block for GCM_TEXT block {i // BLOCK_BYTES}"
            )
            ciphertext += block

        tag = await self._phase(aes, "TAG", GCM_TAG, data=_length_block(), read_out=True)
        assert tag is not None, "AES produced no output block for GCM_TAG"

        assert ciphertext == GOLDEN_CIPHERTEXT, (
            "CHK-GCM-CIPHERTEXT FAIL: engine ciphertext does not match the "
            f"vector.\n  engine={ciphertext.hex()}\n  golden={GOLDEN_CIPHERTEXT.hex()}"
        )
        self.logger.info(
            "CHK-GCM-CIPHERTEXT PASS: %d blocks match the vector (%s...)",
            len(GOLDEN_CIPHERTEXT) // BLOCK_BYTES,
            ciphertext[:8].hex(),
        )

        assert tag == GOLDEN_TAG, (
            "CHK-GCM-TAG FAIL: engine authentication tag does not match the "
            f"vector.\n  engine={tag.hex()}\n  golden={GOLDEN_TAG.hex()}"
        )
        self.logger.info("CHK-GCM-TAG PASS: tag matches the vector (%s)", tag.hex())

        await aes.check_status_clean("gcm-encrypt")
        await self.stop_fifo_drain()

    async def _phase(
        self,
        aes: SepAes,
        label: str,
        phase: int,
        *,
        data: bytes | None = None,
        read_out: bool = False,
    ) -> bytes | None:
        """Select one GCM phase, feed its input block, collect its output."""
        ctrl = _gcm_ctrl(phase)
        # CTRL_GCM_SHADOWED is shadowed: the value must be written twice.
        await aes._wr(AES_CTRL_GCM_SHADOWED, ctrl)
        await aes._wr(AES_CTRL_GCM_SHADOWED, ctrl)

        if data is not None:
            assert len(data) == BLOCK_BYTES, f"GCM {label} needs a whole block"
            # A DATA_IN write while the engine is busy is dropped, and the
            # phase then never sees `data_in_new` and never starts
            # (`aes_control_fsm.sv:298-305`).
            await aes._poll_status_bit(AES_STATUS_INPUT_READY, f"gcm-{label}-input-ready")
            for i, word in enumerate(_to_words(data)):
                await aes._wr(AES_DATA_IN_0 + 4 * i, word)

        out: bytes | None = None
        if read_out:
            assert await aes.output_valid_within(400), (
                f"AES GCM {label}: OUTPUT_VALID never asserted"
            )
            out = _to_bytes(await aes.read_data_out())

        if not read_out:
            # No output register to poll on, so idle is the only completion
            # signal -- and a wait-for-idle issued right after the phase write
            # returns on the idle the engine has not left yet. Wait past the
            # two AES block encryptions GCM_INIT runs before trusting it.
            await ClockCycles(cocotb.top.clk_i, SETTLE_CYCLES)
        await aes.wait_idle(f"gcm-{label}")
        return out
