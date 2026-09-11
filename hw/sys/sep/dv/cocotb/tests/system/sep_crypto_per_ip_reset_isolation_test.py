# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
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

Isolation proof (both directions, then the remaining isolated bits):
  * CHK-NONVAC      both held results are golden-matched and survive a second
                    independent read, so the later survives/cleared checks are
                    observations rather than restatements of one sample.
  * CHK-SELF-RESET  the pulsed engine's held result clears to its reset value
                    (proves the pulse landed in that engine's domain).
  * CHK-NEIGHBOR-SURVIVES  the sibling's held crypto result is bit-exact intact.
  * CHK-REVERSE     roles swapped (AES-victim then HMAC-victim).
  * CHK-KMAC / CHK-OTBN  KMAC SHA3-256 STATE and OTBN DMEM hold across a
                    neighbour pulse. KMAC's own pulse returns STATUS to its
                    register-map reset; OTBN LOAD_CHECKSUM (rst_ni CSR) clears
                    to its register-map reset. DMEM is the cross-domain leak
                    check (a neighbour must not wipe it). OTBN's own reset runs
                    a secure wipe, so DMEM retention across that pulse is not
                    claimed. KM (bit 0) stays held at the reset default and is
                    not claimed.
  * CHK-ISOLATE-*   while HMAC's SW_RESET_N is held, the same DIGEST_0 address
                    that just returned OKAY + the golden digest returns DECERR
                    on read; a write to HMAC CFG also DECERR; AES DATA_OUT_0
                    on the sibling port stays OKAY; SW_RESET_N readback shows
                    the HMAC bit low; after release DIGEST_0 is OKAY at its
                    reset value. Drain-before-reset is not claimed.
  * CHK-TRNG-NEIGHBORS  idle HMAC DIGEST and AES DATA_OUT survive a shared
                    TRNG-only reset, so resetting the entropy complex does not
                    reach the accelerator domains.

Proving only the SW_RESET_N register -> sep_sw_rst_no output bit mapping would
need an HDL backdoor and would stop there. This test proves the reset lands in the
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
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_aes_golden import aes256_ecb_encrypt_words
from env.sep_kmac_golden import kmac_family_words
from sep_base_test import sep_base_test
from sep_reg_meta import KMAC
from seq_lib.sep_aes_seq import AES_DATA_OUT_0, SepAes
from seq_lib.sep_crypto_reset_iso_seq import (
    ENG_AES,
    ENG_HMAC,
    ENG_KMAC,
    ENG_OTBN,
    HMAC_DIGEST_RESET,
    RESP_DECERR,
    RESP_OKAY,
    RST_HMAC,
    SW_RESET_N_DEFAULT,
    SepCryptoResetIso,
)
from seq_lib.sep_hmac_seq import HMAC_CFG, HMAC_DIGEST_0, SepHmac
from seq_lib.sep_kmac_seq import SepKmac, SepKmacCfg
from seq_lib.sep_otbn_seq import OTBN_DMEM_RESULT_LO, OTBN_LOAD_CHECKSUM_RESET, SepOtbn
from seq_lib.sep_sw_reset_seq import SepSwReset

# Directed known vectors (RAND-NONE).
HMAC_MSG = [0x6A6F6232, 0xDEADBEEF, 0x0BADF00D, 0xFEEDFACE]
AES_KEY = [
    0x03020100,
    0x07060504,
    0x0B0A0908,
    0x0F0E0D0C,
    0x13121110,
    0x17161514,
    0x1B1A1918,
    0x1F1E1D1C,
]
AES_PT = [0xAABBCCDD, 0x11223344, 0x55667788, 0x99001122]
KMAC_MSG = [0x6A6F6232, 0xDEADBEEF]
OTBN_CHECKSUM_MARK = 0xA11CED01
OTBN_DMEM_MARK = 0xD3E00D3E
KMAC_STATUS_RESET = KMAC.reset32("STATUS")

_ZERO_DIGEST = [0] * 8


def sha256_digest_words(msg_words: list[int]) -> list[int]:
    """hashlib golden: msg words pushed little-endian per word (msg_be=0); DIGEST
    word i == big-endian word i of the standard SHA-256 (digest_swap=0)."""
    msg = b"".join((w & 0xFFFF_FFFF).to_bytes(4, "little") for w in msg_words)
    h = hashlib.sha256(msg).digest()
    return [int.from_bytes(h[i * 4 : i * 4 + 4], "big") for i in range(8)]


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

    async def _run_kmac(self) -> list[int]:
        """SHA3-256, leave STATE in squeeze so a re-read is a held result."""
        cfg = SepKmacCfg(mode="sha3", sec=256, msg_words=list(KMAC_MSG), outlen_bytes=32)
        digest = await self.kmac.run_family(cfg, tag="sha3-hold", hold=True)
        golden = kmac_family_words(**cfg.golden_kwargs())
        assert digest == golden, (
            "KMAC SHA3-256 digest != golden:\n"
            f"  got={[hex(w) for w in digest]}\n  exp={[hex(w) for w in golden]}"
        )
        await self.kmac.check_status_clean("sha3-hold")
        return digest

    async def _otbn_hold_checksum_and_dmem(self) -> tuple[int, int]:
        """Hold a non-reset LOAD_CHECKSUM (rst_ni CSR) and a DMEM word used as
        the neighbour-reset leak check.

        LOAD_CHECKSUM is a running CRC of IMEM/DMEM bus writes
        (``vendor/lowRISC/opentitan/upstream/hw/ip/otbn/rtl/otbn.sv``
        ``u_mem_load_crc32``). Stage DMEM first, then write the mark last, so
        the DMEM store cannot mix the held checksum.
        """
        await self.otbn.wait_idle("pre-checksum-hold")
        await self.otbn.write_dmem(OTBN_DMEM_RESULT_LO, OTBN_DMEM_MARK)
        dmem = await self.otbn.read_dmem(OTBN_DMEM_RESULT_LO)
        assert dmem == OTBN_DMEM_MARK, f"OTBN DMEM hold write failed 0x{dmem:08x}"
        await self.otbn.write_load_checksum(OTBN_CHECKSUM_MARK)
        got = await self.otbn.read_load_checksum()
        assert got == OTBN_CHECKSUM_MARK, f"OTBN LOAD_CHECKSUM hold write failed 0x{got:08x}"
        return got, dmem

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()

        # Entropy up so the AES masking-PRNG reseed is served (card requirement).
        # strict=False / score_km=False: this test asserts on the held crypto
        # results, not on the bit-exact DRBG golden stream; the scoreboard is used
        # only to drive the deterministic ESRC noise + observe the AES EDN leg.
        await self.bring_up_entropy(
            strict=False, score_km=False, score_sinks={"aes": "observe", "kmac": "observe"}
        )
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.start_fifo_drain()

        self.rst = SepCryptoResetIso(self)
        self.hmac = SepHmac(self)
        self.aes = SepAes(self)
        self.kmac = SepKmac(self)
        self.otbn = SepOtbn(self)

        # Establish a held, golden-checked result in each engine.
        h_digest = await self._run_hmac()
        c_block = await self._run_aes()

        # Re-readability + CHK-NONVAC: each result is a real value (!= reset 0) that
        # the engine HOLDS (a second read returns the same value -- so "survives"
        # later is a real, non-trivial observation, not a one-shot artifact).
        assert await self.hmac.read_digest() == h_digest, "HMAC DIGEST not held on re-read"
        assert await self.aes.read_data_out() == c_block, "AES DATA_OUT not held on re-read"
        # No `!= _ZERO` guards. Both results are already pinned bit-exact to their
        # goldens above, so those comparisons reduce to relations between file-scope
        # constants -- decidable without running the DUT. The load-bearing non-vacuity
        # evidence is the re-read-holds pair below, which is a second real DUT read.
        self.logger.info(
            "CHK-NONVAC PASS: HMAC DIGEST + AES DATA_OUT hold real golden results "
            "(!= reset 0): HMAC[0]=0x%08x AES[0]=0x%08x",
            h_digest[0],
            c_block[0],
        )

        # ---- Case A: pulse AES (victim); HMAC (neighbor) must survive ----------
        # Self-reset evidence = the victim's held result is PERTURBED (no longer the
        # value it held stably across the prior re-reads). For AES this is asserted as
        # "!= C", NOT "== 0", and that is RTL-correct, not a hidden reset bug: the
        # OpenTitan AES DATA_OUT registers are, per spec, "cleared with pseudo-random
        # data" on reset (vendor/lowRISC/opentitan/overlay/regs/aes/regs/gen/adoc/aes.adoc -- the DATA_REG.SEC_WIPE SCA
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
            "CHK-NEIGHBOR-SURVIVES PASS: HMAC DIGEST bit-exact intact"
        )

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
        self.logger.info("CHK-REVERSE PASS: HMAC reset cleared its own DIGEST; AES DATA_OUT intact")

        # ---- Isolate window: HMAC held in reset; same DIGEST_0 must DECERR --
        # Re-establish a live HMAC result so the pre-window beat is OKAY + the
        # golden (an unmapped address cannot produce OKAY -> DECERR -> OKAY).
        # AES still holds C from Case B; that is the sibling-OKAY witness.
        h_digest = await self._run_hmac()
        pre = await self.rst.probe(HMAC_DIGEST_0)
        assert pre.resp_code == RESP_OKAY and pre.rdata == h_digest[0], (
            f"isolate pre-window HMAC DIGEST_0 resp={pre.resp_code} "
            f"rdata=0x{pre.rdata:08x}, expected OKAY + 0x{h_digest[0]:08x}"
        )
        self.logger.info(
            "CHK-ISOLATE-PRE PASS: HMAC DIGEST_0 OKAY with live golden 0x%08x", h_digest[0]
        )

        await self.rst.assert_reset(ENG_HMAC.rst_bit)
        await ClockCycles(cocotb.top.clk_i, 8)
        sw = await self.rst.read_back()
        assert (sw >> RST_HMAC) & 1 == 0, (
            f"SW_RESET_N HMAC bit still released after isolate request: 0x{sw:08x}"
        )
        self.logger.info("CHK-ISOLATE-LANDED PASS: SW_RESET_N=0x%08x HMAC bit held", sw)

        self.env.axi_monitor.arm_expected_decerr(1)
        iso_rd = await self.rst.probe(HMAC_DIGEST_0, expect_error=True)
        assert iso_rd.resp_code == RESP_DECERR and not iso_rd.timed_out, (
            f"in-window HMAC DIGEST_0 read resp={iso_rd.resp_code} "
            f"timed_out={iso_rd.timed_out}, expected DECERR (not hang/OKAY/SLVERR)"
        )
        self.logger.info(
            "CHK-ISOLATE-DECERR PASS: HMAC DIGEST_0 read -> DECERR (resp=%d)", iso_rd.resp_code
        )

        self.env.axi_monitor.arm_expected_decerr(1)
        iso_wr = await self.rst.probe(HMAC_CFG, write=True, wdata=0x1, expect_error=True)
        assert iso_wr.resp_code == RESP_DECERR and not iso_wr.timed_out, (
            f"in-window HMAC CFG write resp={iso_wr.resp_code} "
            f"timed_out={iso_wr.timed_out}, expected DECERR"
        )
        self.logger.info(
            "CHK-ISOLATE-WR PASS: HMAC CFG write -> DECERR (resp=%d)", iso_wr.resp_code
        )

        sib = await self.rst.probe(AES_DATA_OUT_0)
        assert sib.resp_code == RESP_OKAY and sib.rdata == c_block[0], (
            f"in-window sibling AES DATA_OUT_0 resp={sib.resp_code} "
            f"rdata=0x{sib.rdata:08x}, expected OKAY + 0x{c_block[0]:08x}"
        )
        self.logger.info(
            "CHK-ISOLATE-SIBLING PASS: AES DATA_OUT_0 OKAY 0x%08x in HMAC window", sib.rdata
        )

        await self.rst.release_resets()
        await ClockCycles(cocotb.top.clk_i, 40)
        post = await self.rst.probe(HMAC_DIGEST_0)
        assert post.resp_code == RESP_OKAY, (
            f"post-release HMAC DIGEST_0 resp={post.resp_code}, expected OKAY"
        )
        assert post.rdata == HMAC_DIGEST_RESET, (
            f"post-release HMAC DIGEST_0=0x{post.rdata:08x}, "
            f"expected reset 0x{HMAC_DIGEST_RESET:08x}"
        )
        self.logger.info("CHK-ISOLATE-REOPEN PASS: HMAC DIGEST_0 OKAY after release")
        self.logger.info("CHK-ISOLATE-RESET-DEFAULT PASS: rdata=0x%08x", post.rdata)

        # Remaining SW_RESET_N bits that this DUT isolates: KMAC and OTBN.
        # KM (bit 0) stays held at the reset default -- a different mechanism.
        h_digest = await self._run_hmac()
        k_digest = await self._run_kmac()
        assert await self.kmac.read_digest() == k_digest, "KMAC STATE not held on re-read"
        await self._pulse_reset(ENG_KMAC.rst_bit)
        kmac_status = await self.kmac.read_status()
        assert kmac_status == KMAC_STATUS_RESET, (
            f"KMAC STATUS not restored to register-map reset 0x{KMAC_STATUS_RESET:08x} "
            f"after its own SW_RESET_N pulse: 0x{kmac_status:08x}"
        )
        kmac_after = await self.kmac.read_digest()
        # STATE is a window, not a PeakRDL CSR, so it has no REG_DEFAULT. On this
        # DUT a domain reset leaves share0^share1 as 0 (unlike AES DATA_OUT,
        # which SEC_WIPE replaces with PRNG data). Assert that exact idle
        # presentation, not merely inequality against the held digest.
        assert kmac_after == _ZERO_DIGEST, (
            f"KMAC STATE not cleared by its own SW_RESET_N pulse: {[hex(w) for w in kmac_after]}"
        )
        hmac_survived = await self.hmac.read_digest()
        assert hmac_survived == h_digest, (
            "HMAC DIGEST disturbed by KMAC reset:\n"
            f"  before={[hex(w) for w in h_digest]}\n  after={[hex(w) for w in hmac_survived]}"
        )
        self.logger.info(
            "CHK-KMAC-SELF PASS: KMAC STATUS=0x%08x (REG_DEFAULT), "
            "STATE cleared to 0 (held[0]=0x%08x); HMAC DIGEST intact",
            kmac_status,
            k_digest[0],
        )

        k_digest = await self._run_kmac()
        await self._pulse_reset(ENG_HMAC.rst_bit)
        kmac_survived = await self.kmac.read_digest()
        assert kmac_survived == k_digest, (
            "KMAC STATE disturbed by HMAC reset:\n"
            f"  before={[hex(w) for w in k_digest]}\n  after={[hex(w) for w in kmac_survived]}"
        )
        self.logger.info("CHK-KMAC-NEIGHBOR PASS: HMAC reset left KMAC STATE bit-exact intact")

        mark, dmem_mark = await self._otbn_hold_checksum_and_dmem()
        await self._pulse_reset(ENG_AES.rst_bit)
        otbn_survived = await self.otbn.read_load_checksum()
        assert otbn_survived == mark, (
            f"OTBN LOAD_CHECKSUM disturbed by AES reset: 0x{otbn_survived:08x} != 0x{mark:08x}"
        )
        dmem_survived = await self.otbn.read_dmem(OTBN_DMEM_RESULT_LO)
        assert dmem_survived == dmem_mark, (
            f"OTBN DMEM disturbed by AES reset (cross-domain leak): "
            f"0x{dmem_survived:08x} != 0x{dmem_mark:08x}"
        )
        await self._pulse_reset(ENG_OTBN.rst_bit)
        await self.otbn.wait_idle("post-otbn-reset")
        otbn_after = await self.otbn.read_load_checksum()
        assert otbn_after == OTBN_LOAD_CHECKSUM_RESET, (
            f"OTBN LOAD_CHECKSUM not cleared by its own SW_RESET_N pulse: "
            f"0x{otbn_after:08x} != REG_DEFAULT 0x{OTBN_LOAD_CHECKSUM_RESET:08x}"
        )
        self.logger.info(
            "CHK-OTBN PASS: LOAD_CHECKSUM survived AES reset, cleared by OTBN reset "
            "(held 0x%08x -> 0x%08x); DMEM 0x%08x held across AES neighbour reset",
            mark,
            otbn_after,
            dmem_mark,
        )

        sw_final = await self.rst.read_back()
        assert sw_final == SW_RESET_N_DEFAULT, (
            f"SW_RESET_N=0x{sw_final:08x} after domain walk, expected default "
            f"0x{SW_RESET_N_DEFAULT:08x} (bit0 held, otbn/aes/hmac/kmac/trng released)"
        )

        # score_sinks={"aes": "observe", "kmac": "observe"} sets a >=1-beat
        # floor for those sinks; report() is what evaluates it.
        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        assert self.drbg_sb.report(), (
            "sep_drbg_scoreboard report failed (CHK5_aes/kmac beat floor or CHK1..CHK4)"
        )

        # ---- TRNG-only reset must leave idle neighbours untouched ------------
        # The entropy complex resets as one domain, so pulsing only its bit must
        # not reach the accelerators. Both results are re-established here: the
        # domain walk above secure-wiped AES and cleared HMAC. The scoreboard's
        # FIFO drainer is an ESRC CSR client and is already stopped, which is the
        # same quiesce firmware owes the TRNG before requesting its reset.
        h_digest = await self._run_hmac()
        c_block = await self._run_aes()

        trng_rst = SepSwReset(self)
        await trng_rst.park("trng")
        await ClockCycles(cocotb.top.clk_i, 40)
        assert await self.hmac.read_digest() == h_digest, (
            "HMAC held DIGEST was disturbed by a TRNG-only reset"
        )
        assert await self.aes.read_data_out() == c_block, (
            "AES held DATA_OUT was disturbed by a TRNG-only reset"
        )
        await trng_rst.release("trng")
        self.logger.info(
            "CHK-TRNG-NEIGHBORS PASS: idle HMAC DIGEST and AES DATA_OUT survived "
            "the shared entropy-complex reset"
        )

        self.logger.info(
            "per-IP SW-reset isolation ALL CHECKS PASS: live crypto results "
            "(HMAC<->AES, KMAC, OTBN, TRNG neighbours; SW_RESET_N=0x%08x; "
            "entropy-backed: CHK5_aes/kmac beats reported)",
            sw_final,
        )
