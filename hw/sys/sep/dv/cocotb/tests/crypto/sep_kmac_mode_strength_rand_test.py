# SPDX-License-Identifier: Apache-2.0
"""Standalone KMAC-engine mode x strength breadth, RAND-REP (KMAC mode/strength breadth).

Drives the OpenTitan KMAC engine directly over the CPU-LSU AXI master (no_cpu, no
firmware) across the SHA-3 / SHAKE / cSHAKE / KMAC family the Phase-1 KM->KMAC
sideload KAT (`sep_km_kmac_sideload_kat_test`, KMAC-256 keyed via keymgr,
cross-check only) does not reach:

    SHA3-256/512, SHAKE-128/256, cSHAKE-128/256, KMAC-128/256  (8 cells).

reference parity: MERGED_INTO the reference suite kmac mode/strength directed set. The reference SEP
KMAC coverage is a keyed KMAC cross-check (no standalone SHA3/SHAKE/cSHAKE digest
golden), so the independent pure-Python Keccak golden (env/sep_kmac_golden.py:
SHA3/SHAKE cross-checked vs hashlib, cSHAKE/KMAC vs NIST SP800-185) is the
reference and this rep is stronger than the reference suite. DISTINCT from
`sep_km_kmac_sideload_kat_test` (KMAC-256 via sideload, cross-check) -- KMAC
mode/strength breadth is standalone SW-key with an exact golden.

Entropy: the KMAC engine has masking hardwired on (EnMasking=1) and requires EDN
entropy (entropy_mode=EDN) before it produces output, so the test brings up the
real ESRC->DRBG->EDN stack (+esrc_noise_force) or the engine stalls. OTBN/AES/HMAC
are parked so KMAC is the only crypto EDN client: CHK1..CHK4 are bit-exact,
CHK5_kmac is per-sink ROUTING golden. KM is unused.

RAND-REP contract: a SepKmacCfg config object is the single source
of truth for BOTH DUT programming (CFG + KEY_LEN + PREFIX + key + message tail)
AND the golden. The 8 discrete (mode, strength) cells are WALKED DETERMINISTICALLY
in one invocation; the seed randomizes only the legal continuous knobs (message,
key content). The digest is read from STATE share0 ^ share1 (masking on).

Checkers:
  CHK-DIGEST     per cell: engine digest == independent Keccak/SP800-185 golden
  CHK-DONE-RW1C  per cell: INTR_STATE.kmac_done observed set -> W1C -> reads 0
                 (proven in sep_kmac_seq.run_family), and CMD DONE returns to idle
  CHK-ERR        per cell: ERR_CODE == 0 and INTR_STATE.kmac_err == 0
  CHK1..CHK4     bit-exact entropy golden (strict scoreboard report)
  CHK5_kmac      post-adapter KMAC beats == AXIS1 in order (single live crypto sink)
  CHK-RAND-REP   all 8 discrete cells walked in one invocation (seed logged)
"""

from __future__ import annotations

import random

import pyuvm

from sep_base_test import sep_base_test
from env.sep_kmac_golden import kmac_family_words
from seq_lib.sep_kmac_seq import SepKmac, SepKmacCfg
from seq_lib.sep_sw_reset_seq import SepSwReset

# (mode, sec/strength, output bytes, key_bits[kmac only], customization S)
CELLS = [
    ("sha3", 256, 32, None, b""),
    ("sha3", 512, 64, None, b""),
    ("shake", 128, 32, None, b""),
    ("shake", 256, 32, None, b""),
    # cSHAKE is only defined with a non-empty customization; with N=S="" SP800-185
    # collapses it to SHAKE (0x1F), but the engine in CShake mode always applies the
    # cSHAKE 0x04 domain -- so exercise cSHAKE with a real customization string.
    ("cshake", 128, 32, None, b"OSS DV cSHAKE"),
    ("cshake", 256, 32, None, b"Email Signature"),
    ("kmac", 128, 32, 128, b""),
    ("kmac", 256, 64, 256, b"My Tagged Application"),
]



@pyuvm.test()
class sep_kmac_mode_strength_rand_test(sep_base_test):
    """Standalone KMAC-family SHA3/SHAKE/cSHAKE/KMAC x strengths (no_cpu, SW key)."""

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        # Park every other crypto-EDN client so CHK5_kmac golden routing is
        # in-order (one live sink). KMAC stays released for the masking reseed.
        self.swrst = SepSwReset(self)
        await self.swrst.park("otbn", "aes", "hmac")
        await self.bring_up_entropy(
            strict=True, score_km=False, score_sinks={"kmac": "golden"})
        self.start_fifo_drain()
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"

        self.kmac = SepKmac(self)
        seed = self.random_seed()
        self.rng = random.Random(seed)
        self.logger.info("KMAC mode/strength breadth KMAC mode x strength breadth: seed=%d", seed)

        # Collect each cell's DUT result so the matrix claim rests on observed
        # output, not on the loop's own trip count. The former guard compared
        # `walked` against a product of file-scope constants -- it asserted its
        # own arithmetic. Distinct results additionally show the cells really did
        # program different configurations.
        results: dict[str, tuple[int, ...]] = {}
        for mode, sec, outb, key_bits, s in CELLS:
            results[f"{mode}-{sec}-{outb}"] = await self._run_cell(
                mode, sec, outb, key_bits, s)

        walked = len(results)
        assert walked == len(CELLS), f"walked {walked} cells != {len(CELLS)}"
        assert len(set(results.values())) == len(CELLS), (
            "KMAC cells produced duplicate digests, so they did not all run distinct "
            "configurations: "
            + ", ".join(f"{k}={results[k][0]:#010x}" for k in sorted(results)))
        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        self.drbg_sb.report()
        self.logger.info(
            "CHK1..CHK4 bit-exact + CHK5_kmac ROUTING (KMAC==AXIS1) PASS")
        self.logger.info(
            "CHK-RAND-REP PASS: walked all %d discrete cells "
            "(SHA3-256/512, SHAKE-128/256, cSHAKE-128/256, KMAC-128/256) in one "
            "invocation (seed=%d); message/key randomized per cell; entropy clean",
            walked, seed)

    def _rand_words(self, n: int) -> list[int]:
        return [self.rng.getrandbits(32) for _ in range(n)]

    async def _run_cell(self, mode: str, sec: int, outb: int,
                        key_bits: int | None, s: bytes) -> None:
        msg = self._rand_words(self.rng.randint(1, 8))
        key = self._rand_words(key_bits // 32) if mode == "kmac" else None
        cfg = SepKmacCfg(mode=mode, sec=sec, msg_words=msg, outlen_bytes=outb,
                         key_words=key, key_bits=key_bits, s=s)
        cell = f"{mode.upper()}-{sec}" + (f"/key{key_bits}" if mode == "kmac" else "")

        # run_family also proves CHK-DONE-RW1C (kmac_done set -> W1C -> reads 0).
        digest = await self.kmac.run_family(cfg, tag=cell)
        golden = kmac_family_words(**cfg.golden_kwargs())
        assert digest == golden, (
            f"{cell} digest != golden:\n  digest={[hex(w) for w in digest]}\n"
            f"  golden={[hex(w) for w in golden]}")

        # Mode and key sensitivity live in sep_kmac_golden (hashlib / NIST SP800-185
        # self-tests at import). This cell only compares digest == golden.
        await self.kmac.check_status_clean(cell)   # CHK-ERR
        self.logger.info("CHK-CELL PASS %s: digest==golden, DONE-RW1C, ERR clean, "
                         "non-vacuous (out=%dB, msg=%d words)", cell, outb, len(msg))
        return tuple(digest)
