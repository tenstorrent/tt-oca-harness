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
                    that just returned OKAY + the golden digest returns SLVERR
                    on read and does not return that live digest; a write to
                    HMAC CFG also SLVERR; AES DATA_OUT_0
                    on the sibling port stays OKAY; SW_RESET_N readback shows
                    the HMAC bit low; after release DIGEST_0 is OKAY at its
                    reset value.
  * CHK-DRAIN-ORDER  the HMAC reset does not assert until BOTH AXI-Lite paths
                    that domain depends on -- the SEP host path and the Key
                    Manager path -- report isolated. Each accelerator
                    reset depends on both.
  * CHK-HOST-DRAIN  host reads accepted before the reset request resolve OKAY
                    or SLVERR, never DECERR and never a hang, and at least one
                    drains OKAY -- so accepted traffic completed rather than
                    being dropped.
  * CHK-DRAIN-ARRIVAL  a further read issued WHILE isolation is draining also
                    resolves; it may drain or terminate, but it
                    may not hang. That the path is not left wedged is the
                    existing CHK-ISOLATE-REOPEN beat after release.
  * CHK-ABR-DRAIN-ORDER  the Adams Bridge reset does not assert until BOTH
                    paths its domain depends on report isolated: the full-AXI
                    SEP host path and the shared Key Manager path. An ABR-only
                    reset request must raise the Key Manager bit on its own --
                    a design that raises it only for a Key Manager reset never
                    releases the sequencer and fails here rather than passing
                    on a steady state.
  * CHK-ABR-HOST-DRAIN  host reads accepted before the ABR reset request resolve
                    OKAY or SLVERR, never DECERR and never a hang, and at least
                    one drains OKAY. The count still unretired as the isolate
                    closes is asserted non-zero, so the leg grades traffic the
                    isolate actually had to drain.
  * CHK-ABR-DRAIN-ARRIVAL  a read issued WHILE the ABR isolate drains resolves
                    too; it may drain or terminate, but it may not hang.
  * CHK-ABR-JTAG-OVERRIDE  the JTAG IC_RESET override holds the Adams Bridge
                    domain in reset while SW_RESET_N still reports it released,
                    and releasing the override lets the domain come back. The
                    override is sampled against the gated reset, so a mux that
                    ignored the override select fails here.
  * CHK-TRNG-NEIGHBORS  idle HMAC DIGEST and AES DATA_OUT survive a shared
                    TRNG-only reset. SW_RESET_N inside the window shows the
                    TRNG bit held and the four accelerator bits released.

Reference: sep_clock_uvm_sw_reset_per_ip_test --
the reference suite proves only the SW_RESET_N register -> sep_sw_rst_no output
bit mapping (via an HDL backdoor); this test proves the reset actually lands in the
IP and is domain-isolated at the level of a live crypto-datapath RESULT, frontdoor.
no_cpu / +skip_fuse_sense (entropy + crypto are independent of OTP lifecycle) /
+esrc_noise_force (deterministic ESRC ring-osc noise so the entropy stack is alive
under sim -- required by bring_up_entropy, same as the km/crypto entropy tests).

DELTA vs the card: the held state is a COMPLETED golden result resident in the
engine's output registers (re-readable across the sibling's reset), not a paused
mid-round micro-state. A cycle-accurate mid-round freeze and an all-pairs matrix
are not covered here; the resident-result observation proves the reset-domain
boundary against a real crypto-datapath value.
"""

from __future__ import annotations

import hashlib

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, with_timeout
from env.sep_aes_golden import aes256_ecb_encrypt_words
from env.sep_kmac_golden import kmac_family_words
from ocah_axi_vip import worst_resp
from sep_base_test import sep_base_test
from sep_reg_meta import KMAC
from seq_lib.sep_abr_mlkem_seq import MLKEM_STATUS
from seq_lib.sep_aes_seq import AES_DATA_OUT_0, SepAes
from seq_lib.sep_crypto_reset_iso_seq import (
    ENG_AES,
    ENG_HMAC,
    ENG_KMAC,
    ENG_OTBN,
    HMAC_DIGEST_RESET,
    RESP_OKAY,
    RESP_SLVERR,
    RST_ABR,
    RST_HMAC,
    SW_RESET_N_DEFAULT,
    SepCryptoResetIso,
)
from seq_lib.sep_hmac_seq import HMAC_CFG, HMAC_DIGEST_0, SepHmac
from seq_lib.sep_kmac_seq import SepKmac, SepKmacCfg
from seq_lib.sep_otbn_seq import OTBN_DMEM_RESULT_LO, OTBN_LOAD_CHECKSUM_RESET, SepOtbn
from seq_lib.sep_sw_reset_seq import SW_RESET_N_BIT, SepSwReset

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
        # The non-vacuity evidence is the re-read pair above, a second real DUT
        # read; both results are already pinned bit-exact to their goldens, so a
        # compare against the zero constant is decidable without the DUT.
        self.logger.info(
            "CHK-NONVAC PASS: HMAC DIGEST + AES DATA_OUT hold real golden results "
            "(!= reset 0): HMAC[0]=0x%08x AES[0]=0x%08x",
            h_digest[0],
            c_block[0],
        )

        # ---- Case A: pulse AES (victim); HMAC (neighbor) must survive ----------
        # Self-reset evidence = the victim's held result is PERTURBED (it differs from
        # the value it held stably across the prior re-reads). For AES this is asserted
        # as "!= C", not "== 0": the OpenTitan AES DATA_OUT registers are, per spec,
        # "Upon reset, these registers are cleared with pseudo-random data"
        # (vendor/lowRISC/opentitan/overlay/regs/aes/regs/gen/adoc/aes.adoc),
        # so an AES-domain reset replaces the ciphertext with PRNG
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

        # ---- Isolate window: HMAC held in reset; same DIGEST_0 must SLVERR --
        # Re-establish a live HMAC result so the pre-window beat is OKAY + the
        # golden (an unmapped address cannot produce OKAY -> SLVERR -> OKAY).
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

        # ---- Drain-before-reset (the in-window arrival case) -------------
        # Queue host reads that the fabric can accept BEFORE the reset request,
        # so the isolate coordinator has real traffic to drain. Accepted beats
        # must complete; anything not yet accepted is terminated. None may hang.
        axi_driver = self.env.axi_agent.driver
        drain_reads = [
            axi_driver.axi.init_read(address=HMAC_DIGEST_0, length=4, size=2) for _ in range(4)
        ]
        reset_task = cocotb.start_soon(self.rst.assert_reset(ENG_HMAC.rst_bit))

        # The HMAC reset may not assert until BOTH paths that domain depends on
        # report isolated. Sampling every cycle catches the assert edge -- but
        # only if the reset is still RELEASED here: entering the loop after the
        # edge would grade a steady state in which both isolate bits are high
        # anyway, and the check could not fail.
        assert int(cocotb.top.hmac_gated_rst_n_probe_o.value) == 1, (
            "HMAC gated reset was already asserted before the reset request was "
            "issued, so this domain asserted reset with no drain window at all"
        )

        # The drain window is the interval in which an isolate bit is asserted
        # while the gated reset is still released. The arrival beat (#245) is
        # issued INSIDE that window, on the first cycle a probe shows it open.
        # A fixed delay cannot place it there: the window opens relative to the
        # SW_RESET_N write's own B response, so any constant delay can land the
        # beat beside the pre-request batch instead, before the window exists.
        # The probe values at issue are kept
        # in the log, so the beat's position in the window is evidence, and a
        # design that never opens a window fails below rather than scoring the
        # pre-request property a second time.
        arrival_read = None
        arrival_iso = None
        for _ in range(1_000):
            host_iso = int(cocotb.top.hmac_host_isolated_probe_o.value)
            km_iso = int(cocotb.top.hmac_km_isolated_probe_o.value)
            if int(cocotb.top.hmac_gated_rst_n_probe_o.value) == 0:
                assert host_iso == 1 and km_iso == 1, (
                    "HMAC reset asserted before its AXI-Lite paths isolated: "
                    f"host_hmac={host_iso} km_hmac={km_iso}"
                )
                self.logger.info(
                    "CHK-DRAIN-ORDER PASS: HMAC reset asserted only after the host "
                    "and Key Manager paths both reported isolated (sampled in the "
                    "same cycle as the observed assert edge)"
                )
                break
            if arrival_read is None and (host_iso == 1 or km_iso == 1):
                arrival_read = axi_driver.axi.init_read(address=HMAC_DIGEST_0, length=4, size=2)
                arrival_iso = (host_iso, km_iso)
                self.logger.info(
                    "drain window open (host_hmac=%d km_hmac=%d, gated reset still "
                    "released): arrival read issued here",
                    host_iso,
                    km_iso,
                )
            await ClockCycles(cocotb.top.clk_i, 1)
        else:
            raise AssertionError("HMAC gated reset never asserted after the reset request")

        await reset_task

        drain_codes = []
        for event in drain_reads:
            await with_timeout(event.wait(), 10_000, "ns")
            drain_codes.append(worst_resp(getattr(event.data, "resp", None)))
        assert all(code in (RESP_OKAY, RESP_SLVERR) for code in drain_codes), (
            f"in-flight HMAC host reads returned unexpected responses {drain_codes}"
        )
        assert RESP_OKAY in drain_codes, (
            "no pre-reset HMAC host read drained successfully, so this run does "
            "not show that accepted traffic completes rather than being dropped"
        )
        self.logger.info(
            "CHK-HOST-DRAIN PASS: in-flight HMAC host reads resolved %s "
            "(no hang, no DECERR); at least one drained OKAY",
            drain_codes,
        )

        assert arrival_read is not None, (
            "no drain window was ever observed: the HMAC gated reset asserted "
            "without any cycle in which an isolate bit was set and the reset was "
            "still released, so the arrival-during-drain case has no beat and "
            "CHK-DRAIN-ARRIVAL has nothing to grade"
        )
        await with_timeout(arrival_read.wait(), 10_000, "ns")
        arrival_code = worst_resp(getattr(arrival_read.data, "resp", None))
        assert arrival_code in (RESP_OKAY, RESP_SLVERR), (
            f"read arriving during the isolate drain returned resp={arrival_code}, "
            "expected OKAY (drained) or SLVERR (terminated), never DECERR or a hang"
        )
        self.logger.info(
            "CHK-DRAIN-ARRIVAL PASS: a read issued inside the drain window "
            "(host_hmac=%d km_hmac=%d at issue, gated reset still released) "
            "resolved resp=%d, no hang",
            arrival_iso[0],
            arrival_iso[1],
            arrival_code,
        )

        sw = await self.rst.read_back()
        assert (sw >> RST_HMAC) & 1 == 0, (
            f"SW_RESET_N HMAC bit still released after isolate request: 0x{sw:08x}"
        )
        self.logger.info("CHK-ISOLATE-LANDED PASS: SW_RESET_N=0x%08x HMAC bit held", sw)

        iso_rd = await self.rst.probe(HMAC_DIGEST_0, expect_error=True)
        assert iso_rd.resp_code == RESP_SLVERR and not iso_rd.timed_out, (
            f"in-window HMAC DIGEST_0 read resp={iso_rd.resp_code} "
            f"timed_out={iso_rd.timed_out}, expected SLVERR (not hang/OKAY/DECERR)"
        )
        assert iso_rd.rdata != h_digest[0], (
            f"in-window HMAC DIGEST_0 read returned SLVERR with the live digest "
            f"0x{iso_rd.rdata:08x}; the HMAC responder still supplied the data"
        )
        self.logger.info(
            "CHK-ISOLATE-SLVERR PASS: HMAC DIGEST_0 read -> SLVERR (resp=%d) "
            "rdata=0x%08x, not the live digest",
            iso_rd.resp_code,
            iso_rd.rdata,
        )

        iso_wr = await self.rst.probe(HMAC_CFG, write=True, wdata=0x1, expect_error=True)
        assert iso_wr.resp_code == RESP_SLVERR and not iso_wr.timed_out, (
            f"in-window HMAC CFG write resp={iso_wr.resp_code} "
            f"timed_out={iso_wr.timed_out}, expected SLVERR"
        )
        self.logger.info(
            "CHK-ISOLATE-WR PASS: HMAC CFG write -> SLVERR (resp=%d)", iso_wr.resp_code
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
        # Witness the request inside the parked window. Without this the leg is
        # two non-events: park() only proves its CSR write returned OKAY, and the
        # "four accelerator domains released" half is read back BEFORE the park --
        # so a TRNG bit that did nothing would pass identically. Reading the
        # register back here requires the bit to be low while the neighbours are
        # high, in the same window the digests are sampled.
        sw_parked = await trng_rst.read_back()
        trng_bit = 1 << SW_RESET_N_BIT["trng"]
        neighbours = (
            (1 << SW_RESET_N_BIT["otbn"])
            | (1 << SW_RESET_N_BIT["aes"])
            | (1 << SW_RESET_N_BIT["hmac"])
            | (1 << SW_RESET_N_BIT["kmac"])
        )
        assert not (sw_parked & trng_bit), (
            f"SW_RESET_N=0x{sw_parked:08x} shows the TRNG domain NOT held inside the "
            "window the neighbour results are checked in, so this leg would pass "
            "whether or not the reset request reached the entropy complex"
        )
        assert (sw_parked & neighbours) == neighbours, (
            f"SW_RESET_N=0x{sw_parked:08x} shows an accelerator domain also held "
            "during the TRNG-only reset, so a surviving neighbour result proves "
            "nothing about isolation"
        )
        assert await self.hmac.read_digest() == h_digest, (
            "HMAC held DIGEST was disturbed by a TRNG-only reset"
        )
        assert await self.aes.read_data_out() == c_block, (
            "AES held DATA_OUT was disturbed by a TRNG-only reset"
        )
        await trng_rst.release("trng")
        self.logger.info(
            "CHK-TRNG-NEIGHBORS PASS: idle HMAC DIGEST and AES DATA_OUT survived "
            "the shared entropy-complex reset, with SW_RESET_N=0x%08x inside the "
            "window confirming the TRNG domain held and all four accelerator "
            "domains released",
            sw_parked,
        )

        # ---- Adams Bridge drain-before-reset ---------------------------------
        # ABR's host path is a full-AXI isolate and its Key Manager path is
        # shared with the KM domain, so the sequencer waits on host_abr AND
        # km_abr. The reset must still be released when the loop starts, or the
        # sampled state would be the settled one in which both bits are high
        # anyway and the order could not fail.
        abr_rst = SepCryptoResetIso(self)
        assert int(cocotb.top.abr_gated_rst_n_probe_o.value) == 1, (
            "ABR gated reset was already asserted before the reset request was "
            "issued, so this domain asserted reset with no drain window at all"
        )
        # Queue host reads the fabric can accept BEFORE the request, so the
        # full-AXI isolate has real traffic to drain. This is the only full-AXI
        # host isolate in the design; every other accelerator path is AXI-Lite,
        # so TerminateTransaction and NumPending are exercised nowhere else.
        abr_axi = self.env.axi_agent.driver
        abr_drain_reads = [
            abr_axi.axi.init_read(address=MLKEM_STATUS, length=4, size=2) for _ in range(16)
        ]
        abr_task = cocotb.start_soon(abr_rst.assert_reset(RST_ABR))
        abr_arrival = None
        abr_outstanding = None
        abr_saw_window = False
        for _ in range(1_000):
            host_iso = int(cocotb.top.abr_host_isolated_probe_o.value)
            km_iso = int(cocotb.top.abr_km_isolated_probe_o.value)
            if int(cocotb.top.abr_gated_rst_n_probe_o.value) == 0:
                assert host_iso == 1 and km_iso == 1, (
                    "ABR reset asserted before its AXI paths isolated: "
                    f"host_abr={host_iso} km_abr={km_iso}"
                )
                self.logger.info(
                    "CHK-ABR-DRAIN-ORDER PASS: ABR reset asserted only after the "
                    "full-AXI host path and the shared Key Manager path both "
                    "reported isolated (sampled in the same cycle as the observed "
                    "assert edge)"
                )
                break
            if not abr_saw_window and (host_iso == 1 or km_iso == 1):
                abr_saw_window = True
                # Beats still unretired as the isolate closes. Without this the
                # drain check below would pass on traffic that had already
                # completed before the reset request went out -- the reads and
                # the SW_RESET_N write share one master, so ordering alone does
                # not put them in the window.
                abr_outstanding = sum(1 for e in abr_drain_reads if not e.is_set())
                abr_arrival = abr_axi.axi.init_read(address=MLKEM_STATUS, length=4, size=2)
                self.logger.info(
                    "ABR drain window open (host_abr=%d km_abr=%d, gated reset still released)",
                    host_iso,
                    km_iso,
                )
            await ClockCycles(cocotb.top.clk_i, 1)
        else:
            raise AssertionError(
                "ABR gated reset never asserted after the reset request: the "
                "sequencer is still waiting for host_abr and km_abr to isolate"
            )
        await abr_task

        abr_codes = []
        for event in abr_drain_reads:
            await with_timeout(event.wait(), 10_000, "ns")
            abr_codes.append(worst_resp(getattr(event.data, "resp", None)))
        assert all(code in (RESP_OKAY, RESP_SLVERR) for code in abr_codes), (
            f"in-flight ABR host reads returned unexpected responses {abr_codes}"
        )
        assert RESP_OKAY in abr_codes, (
            "no pre-reset ABR host read drained successfully, so this run does not "
            "show that the full-AXI isolate completes accepted traffic rather than "
            "dropping it"
        )
        assert abr_outstanding, (
            f"{abr_outstanding} of the {len(abr_drain_reads)} pre-request ABR reads "
            "were still unretired when the isolate closed, so every one of them had "
            "already completed and this leg grades no traffic that the isolate had "
            "to drain"
        )
        self.logger.info(
            "CHK-ABR-HOST-DRAIN PASS: %d of %d ABR host reads were still unretired "
            "when the full-AXI isolate closed, and all resolved %s (no hang, no "
            "DECERR); at least one drained OKAY",
            abr_outstanding,
            len(abr_drain_reads),
            abr_codes,
        )

        assert abr_arrival is not None, (
            "no ABR drain window was observed, so the arrival-during-drain case has "
            "no beat and CHK-ABR-DRAIN-ARRIVAL has nothing to grade"
        )
        await with_timeout(abr_arrival.wait(), 10_000, "ns")
        abr_arrival_code = worst_resp(getattr(abr_arrival.data, "resp", None))
        assert abr_arrival_code in (RESP_OKAY, RESP_SLVERR), (
            "an ABR host read issued INSIDE the drain window returned "
            f"{abr_arrival_code}; it may drain or terminate, but it may not hang or "
            "DECERR"
        )
        self.logger.info(
            "CHK-ABR-DRAIN-ARRIVAL PASS: a read issued inside the ABR drain window "
            "resolved %d rather than hanging",
            abr_arrival_code,
        )

        assert abr_saw_window, (
            "no ABR drain window was observed: the gated reset asserted with no "
            "cycle in which an isolate bit was set and the reset still released"
        )
        await abr_rst.release_resets()

        # ---- ABR JTAG IC_RESET override -------------------------------------
        # The override mux sits after the SW-reset AND: asserting it must hold
        # the domain even though SW_RESET_N still shows ABR released. Both
        # directions are graded, so a mux stuck in either position fails.
        sw_before = await abr_rst.read_back()
        assert sw_before & (1 << RST_ABR), (
            f"SW_RESET_N=0x{sw_before:08x} shows ABR already held before the JTAG "
            "override is applied, so a held gated reset below would prove nothing"
        )
        assert int(cocotb.top.abr_gated_rst_n_probe_o.value) == 1, (
            "ABR gated reset is already asserted before the JTAG override, so the "
            "override cannot be shown to be what holds it"
        )
        cocotb.top.jtag_abr_rst_hold_i.value = 1
        await ClockCycles(cocotb.top.clk_i, 10)
        sw_held = await abr_rst.read_back()
        assert int(cocotb.top.abr_gated_rst_n_probe_o.value) == 0, (
            "JTAG override asserted but the ABR gated reset stayed released, so "
            "the override select does not reach the reset mux"
        )
        assert sw_held & (1 << RST_ABR), (
            f"SW_RESET_N=0x{sw_held:08x} shows the ABR bit low inside the override "
            "window, so the hold cannot be attributed to JTAG rather than software"
        )
        cocotb.top.jtag_abr_rst_hold_i.value = 0
        await ClockCycles(cocotb.top.clk_i, 10)
        assert int(cocotb.top.abr_gated_rst_n_probe_o.value) == 1, (
            "ABR gated reset stayed asserted after the JTAG override released, so "
            "the mux is stuck on the override leg"
        )
        self.logger.info(
            "CHK-ABR-JTAG-OVERRIDE PASS: the override held the ABR domain with "
            "SW_RESET_N=0x%08x still reporting it released, and the domain "
            "returned when the override released",
            sw_held,
        )

        self.logger.info(
            "per-IP SW-reset isolation ALL CHECKS PASS: live crypto results "
            "(HMAC<->AES, KMAC, OTBN; TRNG neighbours HMAC DIGEST and AES DATA_OUT; "
            "SW_RESET_N=0x%08x; entropy-backed: CHK5_aes/kmac beats reported)",
            sw_final,
        )
