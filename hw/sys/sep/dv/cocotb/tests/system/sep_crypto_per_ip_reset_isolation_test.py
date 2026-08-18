# SPDX-License-Identifier: Apache-2.0
"""Per-IP SW-reset domain isolation across crypto engines.

no_cpu host-AXI test that proves the SEP per-IP SW_RESET_N domains are isolated
WHILE a neighbour engine holds a LIVE, golden-checked crypto RESULT in its
datapath output registers: pulsing one engine's reset clears that engine's own
result but leaves the sibling's held crypto result bit-exact intact. This is the
SEP-level stateful-isolation property a single-IP tb structurally cannot observe;
it extends the per-IP reset pulse + static non-corruption check to a live,
golden-checked crypto result held across a sibling's reset.

Engine pair (two independently-resettable crypto engines, both holding a real
result that survives re-reads):
  * HMAC -- a plain SHA-256 over a known message; the 256-bit DIGEST is held in
    DIGEST_0..7 and value-checked against an independent hashlib golden.
  * AES  -- one ECB-256 encryption of a known block under a known SW key; the
    ciphertext is held in DATA_OUT_0..3 and value-checked against the FIPS-197
    self-tested env/sep_aes_golden. AES is the "held/mid-encrypt" engine named in
    the VPLAN card; its masking-PRNG reseed consumes the brought-up entropy.

Entropy is brought up first (ESRC->DRBG->CSRNG->EDN) so the AES masking-PRNG
reseed is served -- satisfying the card's "with entropy bring-up" requirement and
exercising a real entropy-backed crypto op rather than a poked status bit.

Isolation proof (both directions):
  * CHK-NONVAC      both held results are real golden-matched values != reset 0.
  * CHK-SELF-RESET  the pulsed engine's held result clears to its reset value
                    (proves the pulse landed in that engine's domain).
  * CHK-NEIGHBOR-SURVIVES  the sibling's held crypto result is bit-exact intact.
  * CHK-REVERSE     roles swapped (AES-victim then HMAC-victim).

reference ref: clock sep_clock_uvm_sw_reset_per_ip_test @ 9ec8f9f4b --
COVERED_STRONGER: reference suite proves only the SW_RESET_N register -> sep_sw_rst_no output
bit mapping (via an HDL backdoor); this test proves the reset actually lands in the
IP and is domain-isolated at the level of a live crypto-datapath RESULT, frontdoor.
no_cpu / +skip_fuse_sense (entropy + crypto are independent of OTP lifecycle) /
+esrc_noise_force (deterministic ESRC ring-osc noise so the entropy stack is alive
under sim -- required by bring_up_entropy, same as the km/crypto entropy tests).

DELTA vs the card: the held state is a COMPLETED golden result resident in the
engine's output registers (re-readable across the sibling's reset), not a paused
mid-round micro-state. A cycle-accurate mid-round freeze + all-pairs matrix are
deferred (GAP); the resident-result observation already proves the reset-domain
boundary against a real crypto-datapath value.
"""

from __future__ import annotations

import hashlib

import cocotb
from cocotb.triggers import ClockCycles
import pyuvm

from sep_base_test import sep_base_test
from env.sep_aes_golden import aes256_ecb_encrypt_words
from seq_lib.sep_hmac_seq import SepHmac
from seq_lib.sep_aes_seq import SepAes
from seq_lib.sep_crypto_reset_iso_seq import SepCryptoResetIso, ENG_HMAC, ENG_AES

# Directed known vectors (RAND-NONE).
HMAC_MSG = [0x6A6F6232, 0xDEADBEEF, 0x0BADF00D, 0xFEEDFACE]
AES_KEY = [0x03020100, 0x07060504, 0x0B0A0908, 0x0F0E0D0C,
           0x13121110, 0x17161514, 0x1B1A1918, 0x1F1E1D1C]
AES_PT = [0xAABBCCDD, 0x11223344, 0x55667788, 0x99001122]

_ZERO_DIGEST = [0] * 8
_ZERO_BLOCK = [0] * 4


def sha256_digest_words(msg_words: list[int]) -> list[int]:
    """hashlib golden: msg words pushed little-endian per word (msg_be=0); DIGEST
    word i == big-endian word i of the standard SHA-256 (digest_swap=0)."""
    msg = b"".join((w & 0xFFFF_FFFF).to_bytes(4, "little") for w in msg_words)
    h = hashlib.sha256(msg).digest()
    return [int.from_bytes(h[i * 4:i * 4 + 4], "big") for i in range(8)]


@pyuvm.test()
class sep_crypto_per_ip_reset_isolation_test(sep_base_test):
    """Pulse one crypto engine's SW-reset; the sibling's held crypto result survives."""

    async def _pulse_reset(self, rst_bit: int) -> None:
        """Active-low pulse of one IP's SW_RESET_N (assert, settle, release, settle)."""
        await self.rst.assert_reset(rst_bit)
        await ClockCycles(cocotb.top.clk_i, 40)
        await self.rst.release_resets()
        await ClockCycles(cocotb.top.clk_i, 40)

    async def _run_hmac(self) -> list[int]:
        """Run SHA-256 -> DIGEST holds the golden digest; value-check it."""
        await self.hmac.configure_sha256()
        digest = await self.hmac.run_sha256(list(HMAC_MSG))
        golden = sha256_digest_words(list(HMAC_MSG))
        assert digest == golden, (
            "HMAC SHA-256 digest != hashlib golden:\n"
            f"  got={[hex(w) for w in digest]}\n  exp={[hex(w) for w in golden]}"
        )
        await self.hmac.check_status_clean("sha256")
        return digest

    async def _run_aes(self) -> list[int]:
        """Run ECB-256 ENC -> DATA_OUT holds the golden ciphertext; value-check it."""
        await self.aes.configure_ecb_enc_256(sideload=False)
        await self.aes.write_full_key(list(AES_KEY))
        await self.aes.trigger_prng_reseed()
        ct = await self.aes.run_ecb_block(list(AES_PT))
        golden = aes256_ecb_encrypt_words(list(AES_KEY), list(AES_PT))
        assert ct == golden, (
            "AES ECB-256 ciphertext != FIPS-197 golden:\n"
            f"  got={[hex(w) for w in ct]}\n  exp={[hex(w) for w in golden]}"
        )
        await self.aes.check_status_clean("ecb-enc")
        return ct

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()

        # Entropy up so the AES masking-PRNG reseed is served (card requirement).
        # strict=False / score_km=False: this test asserts on the held crypto
        # results, not on the bit-exact DRBG golden stream; the scoreboard is used
        # only to drive the deterministic ESRC noise + observe the AES EDN leg.
        await self.bring_up_entropy(strict=False, score_km=False,
                                    score_sinks={"aes": "observe"})
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.start_fifo_drain()

        self.rst = SepCryptoResetIso(self)
        self.hmac = SepHmac(self)
        self.aes = SepAes(self)

        # Establish a held, golden-checked result in each engine.
        h_digest = await self._run_hmac()
        c_block = await self._run_aes()

        # Re-readability + CHK-NONVAC: each result is a real value (!= reset 0) that
        # the engine HOLDS (a second read returns the same value -- so "survives"
        # later is a real, non-trivial observation, not a one-shot artifact).
        assert await self.hmac.read_digest() == h_digest, "HMAC DIGEST not held on re-read"
        assert await self.aes.read_data_out() == c_block, "AES DATA_OUT not held on re-read"
        assert h_digest != _ZERO_DIGEST, "HMAC digest is all-zero (no real result)"
        assert c_block != _ZERO_BLOCK, "AES ciphertext is all-zero (no real result)"
        self.logger.info(
            "CHK-NONVAC PASS: HMAC DIGEST + AES DATA_OUT hold real golden results "
            "(!= reset 0): HMAC[0]=0x%08x AES[0]=0x%08x", h_digest[0], c_block[0])

        # ---- Case A: pulse AES (victim); HMAC (neighbor) must survive ----------
        # Self-reset evidence = the victim's held result is PERTURBED (no longer the
        # value it held stably across the prior re-reads). For AES this is asserted as
        # "!= C", NOT "== 0", and that is RTL-correct, not a hidden reset bug: the
        # OpenTitan AES DATA_OUT registers are, per spec, "cleared with pseudo-random
        # data" on reset (hw/sys/sep/regs/gen/adoc/blocks/aes.adoc -- the DATA_REG.SEC_WIPE SCA
        # countermeasure), so an AES-domain reset replaces the ciphertext with PRNG
        # data rather than a clean 0. DATA_OUT is fully inside aes_sw_rst_ni
        # (sep_crypto.sv) so there is no out-of-domain ciphertext leak. (The 4-word
        # read is non-atomic -- interleaved with entropy-FIFO drains -- so individual
        # words may still read 0 mid-wipe; "!= the held C" is the seed-robust check.)
        # The unmasked HMAC DIGEST below has no SEC_WIPE and clears cleanly to 0.
        # AES additionally re-runs to the exact golden C after reset (Case B's
        # _run_aes), proving the AES domain truly reset and recovered.
        await self._pulse_reset(ENG_AES.rst_bit)
        aes_after = await self.aes.read_data_out()
        assert aes_after != c_block, (
            "AES DATA_OUT not perturbed by its own SW_RESET_N pulse (reset did not land):\n"
            f"  held={[hex(w) for w in c_block]}\n  after={[hex(w) for w in aes_after]}"
        )
        hmac_survived = await self.hmac.read_digest()
        assert hmac_survived == h_digest, (
            "HMAC held DIGEST was disturbed by AES's reset (domains not isolated):\n"
            f"  before={[hex(w) for w in h_digest]}\n  after ={[hex(w) for w in hmac_survived]}"
        )
        self.logger.info(
            "CHK-SELF-RESET PASS: AES reset perturbed its own DATA_OUT (masking-presented); "
            "CHK-NEIGHBOR-SURVIVES PASS: HMAC DIGEST bit-exact intact")

        # ---- Case B (reverse): pulse HMAC (victim); AES (neighbor) must survive --
        # Re-establish the AES held result (cleared by its Case-A reset); HMAC still
        # holds its digest (it was the neighbour, untouched).
        c_block = await self._run_aes()
        assert await self.hmac.read_digest() == h_digest, "HMAC DIGEST lost before Case B"
        await self._pulse_reset(ENG_HMAC.rst_bit)
        hmac_after = await self.hmac.read_digest()
        assert hmac_after == _ZERO_DIGEST, (
            f"HMAC DIGEST not cleared by its own SW_RESET_N pulse: {[hex(w) for w in hmac_after]}"
        )
        aes_survived = await self.aes.read_data_out()
        assert aes_survived == c_block, (
            "AES held DATA_OUT was disturbed by HMAC's reset (domains not isolated):\n"
            f"  before={[hex(w) for w in c_block]}\n  after ={[hex(w) for w in aes_survived]}"
        )
        self.logger.info(
            "CHK-REVERSE PASS: HMAC reset cleared its own DIGEST; AES DATA_OUT intact")

        self.logger.info(
            "CHK-ALL PASS: per-IP SW-reset domain isolation with live crypto results "
            "(HMAC<->AES, both directions, entropy-backed)")
