# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Each AES mode and key size encrypts and round-trips to an independent golden.

RAND-REP. The test drives the OpenTitan AES engine directly over the CPU-LSU AXI master (no_cpu, no
firmware, SW key) across the full standalone matrix the KM->AES sideload
KAT (`sep_km_aes_sideload_kat_test`, ECB-256 via keymgr) does not reach:

    {ECB, CBC, CTR} x {128, 192, 256}  (9 cells).

The independent pure-Python golden (env/sep_aes_golden.py: FIPS-197 ECB 128/192/256 +
SP 800-38A CBC/CTR, self-tested) is the reference. Distinct from
`sep_km_aes_sideload_kat_test` (ECB-256 via sideload) -- AES mode/key-size breadth
is standalone SW-key across modes/sizes.

Entropy: OpenTitan AES masking reseeds its PRNG from the crypto-EDN leg, so the
test brings up the real ESRC->DRBG->EDN stack (+esrc_noise_force) before any AES
op or the engine stalls. OTBN/KMAC/HMAC are parked so AES is the only crypto
EDN client: CHK1..CHK4 are bit-exact, CHK5_aes is per-sink ROUTING golden
(each post-adapter beat equals the next AXIS1 word). KM is unused.

One SepAesCfg object drives both the DUT programming (CTRL, key, IV, data) and
the golden. The nine (mode, key-size) cells are walked on every seed. The seed
sets only the key, IV and plaintext content.

Checkers (CHK-CELL carries the ciphertext, round-trip and no-alert checks on one log line per cell):
  CHK-CELL     per cell: engine ciphertext == independent golden (2 blocks);
               round trip recovers the plaintext (ECB/CBC via engine DECRYPT, CTR
               via re-encrypt); no AES recoverable/fatal alert across both
  CHK1..CHK4   bit-exact entropy golden (strict scoreboard report)
  CHK5_aes     post-adapter AES beats == AXIS1 in order (single live crypto sink)
  CHK-RAND-REP every discrete cell produced its own golden-matching ciphertext,
               and all ciphertexts are distinct (seed logged)
"""

from __future__ import annotations

import pyuvm
from env.sep_aes_golden import aes_encrypt_words
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from seq_lib.sep_aes_seq import AES_OP_DEC, AES_OP_ENC, SepAes, SepAesCfg

MODES = ["ecb", "cbc", "ctr"]
KEY_SIZES = [128, 192, 256]
NUM_BLOCKS = 2  # 2 x 128-bit blocks per cell -> exercises CBC chaining / CTR increment


@pyuvm.test()
class sep_aes_mode_keysize_rand_test(sep_base_test):
    """AES ECB/CBC/CTR x 128/192/256 with a SW key each match the golden and round-trip."""

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu(park=("otbn", "hmac", "kmac"))
        # Every other crypto-EDN client is JTAG-held across rst_ni release, then
        # parked in SW_RESET_N, so CHK5_aes golden routing is in order (one live
        # sink). AES stays released for the masking reseed.
        await self.bring_up_entropy(strict=True, score_km=False, score_sinks={"aes": "golden"})
        # The default floor is one scored beat, which is far below what the
        # per-beat routing claim needs across the whole cell walk.
        self.drbg_sb.set_min_matches(CHK5_aes=32)
        self.start_fifo_drain()
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"

        self.aes = SepAes(self)
        seed = self.random_seed()
        self.rng = SepSeededRng(seed)
        self.logger.info("AES mode x key-size breadth: seed=%d", seed)
        await self.aes.trigger_prng_reseed()  # seed the masking PRNG from EDN

        # Collect each cell's DUT ciphertext, so the matrix claim rests on observed
        # output. Distinct results also show the nine cells programmed nine different
        # configurations: two cells that silently ran the same mode and key size on
        # the same random inputs would collide here.
        results: dict[str, tuple[int, ...]] = {}
        for mode in MODES:
            for key_bits in KEY_SIZES:
                results[f"{mode}-{key_bits}"] = await self._run_cell(mode, key_bits)

        walked = len(results)
        expected = len(MODES) * len(KEY_SIZES)
        # Construction guard, not a DUT contract: this compares the walk against
        # the cell list that drove it, so only a table or keying mistake in this
        # file can trip it. The DUT evidence is the per-cell golden compare.
        assert walked == expected, f"walked {walked} cells != {expected}"
        assert len(set(results.values())) == expected, (
            "AES cells produced duplicate ciphertexts, so they did not all run distinct "
            "configurations: " + ", ".join(f"{k}={results[k][0]:#010x}" for k in sorted(results))
        )
        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        assert self.drbg_sb.report()
        self.logger.info("CHK1..CHK4 bit-exact + CHK5_aes ROUTING (AES==AXIS1) PASS")
        self.logger.info(
            "CHK-RAND-REP PASS: walked all %d discrete cells ({ECB,CBC,CTR} x "
            "{128,192,256}) in one invocation (seed=%d); key/IV/plaintext "
            "randomized per cell; entropy alerts clean",
            walked,
            seed,
        )

    def _rand_words(self, n: int) -> list[int]:
        return [self.rng.getrandbits(32) for _ in range(n)]

    async def _run_cell(self, mode: str, key_bits: int) -> tuple[int, ...]:
        key = self._rand_words(key_bits // 32)
        pt = self._rand_words(4 * NUM_BLOCKS)
        iv = self._rand_words(4) if mode != "ecb" else None
        cfg = SepAesCfg(mode=mode, key_bits=key_bits, key_words=key, pt_words=pt, iv_words=iv)
        cell = f"AES-{mode.upper()}-{key_bits}"

        # --- CHK-CELL (ciphertext): encrypt and value-check against the independent golden ---
        await self.aes.configure(
            mode=cfg.mode_ctrl(), key_len=cfg.keylen_ctrl(), operation=AES_OP_ENC
        )
        await self.aes.load_key_iv(key, iv)  # spec-ordered: idle between key + IV
        ct = await self.aes.run_blocks(pt)
        golden = aes_encrypt_words(**cfg.golden_kwargs())
        assert ct == golden, (
            f"{cell} ciphertext != golden:\n  ct    ={[hex(w) for w in ct]}\n"
            f"  golden={[hex(w) for w in golden]}"
        )

        await self.aes.check_status_clean(cell + "-enc")  # CHK-CELL (no alert)

        # --- CHK-CELL (round trip): recover the plaintext --------------------
        if mode in ("ecb", "cbc"):
            await self.aes.configure(
                mode=cfg.mode_ctrl(), key_len=cfg.keylen_ctrl(), operation=AES_OP_DEC
            )
            await self.aes.load_key_iv(key, iv)  # CBC decrypt needs the original IV
            rt = await self.aes.run_blocks(ct)
        else:  # CTR is a stream cipher: re-encrypting the ciphertext yields the pt
            await self.aes.configure(
                mode=cfg.mode_ctrl(), key_len=cfg.keylen_ctrl(), operation=AES_OP_ENC
            )
            await self.aes.load_key_iv(key, iv)
            rt = await self.aes.run_blocks(ct)
        assert rt == pt, (
            f"{cell} round-trip != plaintext:\n  rt={[hex(w) for w in rt]}\n"
            f"  pt={[hex(w) for w in pt]}"
        )
        await self.aes.check_status_clean(cell + "-rt")

        self.logger.info(
            "CHK-CELL PASS %s: ct==golden, round-trip==pt, no alert, non-vacuous (%d blocks)",
            cell,
            NUM_BLOCKS,
        )
        return tuple(ct)
