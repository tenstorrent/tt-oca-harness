# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The crypto-EDN adapter grants two clients that request at once, and every client is served.

``sep_crypto_edn_multisink_arbitration_test`` proves AES and KMAC complete and
that their beat time-spans overlap. It cannot create a same-cycle dual
``edn_req``: AES/KMAC masking reseeds are short pulses separated by AXI
configuration. This test holds AES (crypto_edn[0]) and OTBN URND
(crypto_edn[3]) with ``edn_req`` high *before* EDN is enabled, then brings up
the real entropy chain so ``prim_arbiter_ppc`` inside ``drbg_axis_edn_adapter``
has to grant both. CHK-GRANT-ALT grades sharing and an alternating grant
prefix. It does not prove round-robin order under simultaneous request: a
fixed-priority arbiter that serves URND whenever AES has dropped ``edn_req``
gives the same stream.

The grant monitor starts only after the ESRC seed is ready so the dual-req
window is not sampled during ``wait_seed_ready``. CHK1..CHK4 stay bit-exact
on that bring-up.

OTBN RND (crypto_edn[2]) joins after the alternation proof as the third client
driven, and KMAC (crypto_edn[1]) follows as the fourth. RND is not inside the
alternation proof: RND only requests while an OTBN
program is blocked on the RND CSR, and OTBN cannot execute until its
post-reset secure wipe has consumed URND, which already needs EDN enabled. So
this test drives it as its own client -- a program that reads RND four times
-- and claims routing and consume for it, not alternation.

Four crypto sinks are live (AES, KMAC, OTBN URND and OTBN RND) plus the entropy
pool, so CHK5 is five-sink ROUTING: each post-adapter beat equals the AXIS1 word
the adapter granted that cycle.

Checkers:
  CHK-DUAL-REQ     AES and URND hold crypto_edn_req high together.
  CHK-NO-STARVE    both requesting clients get edn_ack.
  CHK-GRANT-ALT    the post-adapter grants share and alternate (see the limit above).
  CHK-RND-REQ      OTBN raises its RND request bit.
  CHK-RND-CONSUME  the RND CSR reads retire with ERR_BITS=0.
  CHK-KMAC-CLIENT  a keyed KMAC-256 on the KMAC client matches the Keccak golden.
  CHK-FOUR-CLIENT  all four adapter clients are granted in one run.
  CHK1..CHK4, CHK-ROUTING  bit-exact entropy golden and five-sink routing.

Probes: ``tb_top.crypto_edn_req_o`` / ``crypto_edn_ack_o`` (observation
ports).
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from env.sep_drbg_scoreboard import SepDrbgScoreboard
from env.sep_kmac_golden import kmac_family_words
from sep_base_test import sep_base_test
from seq_lib.sep_aes_seq import AES_TRIGGER, AES_TRIGGER_PRNG_RESEED, SepAes
from seq_lib.sep_esrc_bringup_seq import (
    SepEntropyCfg,
    SepEsrcConfigSeq,
    SepEsrcEnableEdnSeq,
    SepEsrcEnableGeneratorsSeq,
)
from seq_lib.sep_kmac_seq import SepKmac, SepKmacCfg
from seq_lib.sep_otbn_seq import (
    OTBN_DMEM_RND_BASE,
    OTBN_RND_PROG,
    OTBN_RND_READS,
    SepOtbn,
)

_AES_BIT = 0
_KMAC_BIT = 1
_RND_BIT = 2
_URND_BIT = 3
_ALL_CLIENTS = (_AES_BIT, _KMAC_BIT, _RND_BIT, _URND_BIT)
_BOTH = (1 << _AES_BIT) | (1 << _URND_BIT)
# The RND client only requests while an OTBN program is blocked on the RND CSR,
# so it is brought in after the AES/URND alternation window rather than held
# alongside it.
_RND_REQ_CYCLES = 200_000

# KMAC-256 keyed cell for the KMAC adapter client. Fixed, because this leaf
# grades arbitration and routing; the KMAC value matrix is walked by
# sep_kmac_mode_strength_rand_test.
_KMAC_KEY = (
    0x00010203,
    0x04050607,
    0x08090A0B,
    0x0C0D0E0F,
    0x10111213,
    0x14151617,
    0x18191A1B,
    0x1C1D1E1F,
)
_KMAC_MSG = [0x00010203, 0x04050607, 0x08090A0B, 0x0C0D0E0F]
_KMAC_S = b"crypto EDN four-client"
# Non-vacuity floors for the sinks whose full stimulus this leaf cannot
# derive. They are above one, so a sink that took nothing fails, and below the
# observed traffic, so a seed change does not trip them. They are NOT
# starvation bounds -- see the floor block in run_scenario for what does and
# does not bound each sink.
_KMAC_MIN_BEATS = 4
_POOL_MIN_BEATS = 16
# One OTBN RND CSR read pulls a 256-bit EDN word, i.e. eight 32-bit beats, so the
# RND routing floor is OTBN_RND_READS x this -- the sink's whole stimulus.
_EDN_BEATS_PER_RND_READ = 8
_DUAL_REQ_CYCLES = 50_000
# Enough consecutive grants to see the arbiter alternate, and the floor below
# which the sample says nothing. Literals, so the asserts do not move with the
# collection loop.
_GRANT_SAMPLE_TARGET = 16
_GRANT_MIN_SAMPLES = 4
_GRANT_POLLS = 200_000
_GRANT_POLL_CYCLES = 20


def _req() -> int:
    try:
        return int(cocotb.top.crypto_edn_req_o.value)
    except ValueError:
        return 0


def _ack() -> int:
    try:
        return int(cocotb.top.crypto_edn_ack_o.value)
    except ValueError:
        return 0


@pyuvm.test()
class sep_crypto_edn_round_robin_grant_test(sep_base_test):
    """AES and OTBN URND, requesting together, are both granted; all four clients are served."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        await self.bring_up_no_cpu()

        # OTBN is released at cold reset (SW_RESET_N reset 0x7E). Without EDN it
        # parks in UrndRefresh with crypto_edn_req[3] held.
        for _ in range(_DUAL_REQ_CYCLES):
            if _req() & (1 << _URND_BIT):
                break
            await RisingEdge(dut.clk_i)
        else:
            raise AssertionError(
                f"OTBN URND edn_req never asserted (crypto_edn_req_o=0x{_req():x})"
            )

        aes = SepAes(self)
        await aes._wr(AES_TRIGGER, AES_TRIGGER_PRNG_RESEED)

        dual_seen = None
        for _ in range(_DUAL_REQ_CYCLES):
            req = _req()
            if (req & _BOTH) == _BOTH:
                dual_seen = req
                break
            await RisingEdge(dut.clk_i)
        assert dual_seen is not None, (
            "CHK-DUAL-REQ FAIL: AES and OTBN URND edn_req were never high in the "
            f"same cycle (last crypto_edn_req_o=0x{_req():x})"
        )
        self.logger.info(
            "CHK-DUAL-REQ PASS: crypto_edn_req bits 0x%x (AES bit %d + URND bit %d)",
            dual_seen,
            _AES_BIT,
            _URND_BIT,
        )

        # Same entropy bring-up as the other no_cpu consumers, split so the
        # grant monitor is not running during wait_seed_ready.
        cfg = SepEntropyCfg()
        self.entropy_cfg = cfg
        self.drbg_sb = SepDrbgScoreboard(
            dut,
            self.logger,
            strict=True,
            golden_kwargs=cfg.golden_kwargs(),
            chk2_backdoor=cfg.chk2_backdoor,
            score_km=False,
            score_sinks={
                "aes": "golden",
                "otbn_urnd": "golden",
                "otbn_rnd": "golden",
                "kmac": "golden",
                # The entropy FIFO pulls mux endpoint [2] from reset, so the pool
                # is a live fifth endpoint throughout and is scored rather than
                # left unclaimed while four crypto clients are loading the DRBG.
                "pool": "golden",
            },
        )
        self.drbg_sb.start()
        await self.assert_noise_force_active()
        await self.start_seq(SepEsrcConfigSeq("esrc_config", cfg=cfg))
        await self.start_seq(SepEsrcEnableGeneratorsSeq("esrc_enable_gens"))
        if not await self.wait_seed_ready():
            await self.report_entropy_stall()
            raise AssertionError("ESRC never produced a seed (drbg_seed_valid_o)")
        self.start_fifo_drain()
        self.drbg_sb.enable_chk5()

        grants: list[int] = []
        dual_grants: list[int] = []
        # Which adapter clients were granted anywhere in the run. `grants` is the
        # AES/URND alternation sample and records only those two bits; CHK-FOUR-CLIENT
        # needs every client, including the two driven later.
        acked = {"mask": 0}

        async def _monitor() -> None:
            prev_ack = 0
            while True:
                await RisingEdge(dut.clk_i)
                req = _req()
                ack = _ack()
                for bit in _ALL_CLIENTS:
                    mask = 1 << bit
                    rising = (ack & mask) and not (prev_ack & mask)
                    if not rising:
                        continue
                    acked["mask"] |= mask
                    if bit in (_AES_BIT, _URND_BIT) and (req & mask):
                        grants.append(bit)
                        if (req & _BOTH) == _BOTH:
                            dual_grants.append(bit)
                prev_ack = ack

        # Both clients are still held (EDN has not been enabled). Start the
        # grant sampler, then enable EDN so the adapter has to pick.
        cocotb.start_soon(_monitor())
        await self.start_seq(SepEsrcEnableEdnSeq("esrc_enable_edn"))

        # Collect grants for a fixed budget; the asserts below decide.
        for _ in range(_GRANT_POLLS):
            if len(grants) >= _GRANT_SAMPLE_TARGET:
                break
            await ClockCycles(dut.clk_i, _GRANT_POLL_CYCLES)
        assert len(grants) >= _GRANT_MIN_SAMPLES, (
            f"CHK-NO-STARVE FAIL: only {len(grants)} post-adapter grants observed in "
            f"{_GRANT_POLLS} polls of {_GRANT_POLL_CYCLES} cycles, need "
            f"{_GRANT_MIN_SAMPLES} to judge sharing "
            f"(grants={grants[:16]} dual_grants={dual_grants[:16]})"
        )

        assert _AES_BIT in grants and _URND_BIT in grants, (
            f"CHK-NO-STARVE FAIL: a requesting client got no edn_ack (grants={grants})"
        )
        self.logger.info(
            "CHK-NO-STARVE PASS: both clients acked (AES grants=%d URND grants=%d)",
            grants.count(_AES_BIT),
            grants.count(_URND_BIT),
        )

        # Sharing between the two clients: the grant stream must strictly
        # alternate until the first same-client pair. This does not separate
        # round-robin from fixed priority, because a URND grant may follow AES
        # dropping edn_req (dual_grants is logged, not graded). A repeat
        # after both clients have already been served is the legal tail (one
        # client dropped req).
        pairs = list(zip(grants, grants[1:]))
        alt_pairs = 0
        for a, b in pairs:
            if a == b:
                break
            alt_pairs += 1
        min_alt = _GRANT_MIN_SAMPLES - 1
        assert alt_pairs >= min_alt, (
            "CHK-GRANT-ALT FAIL: alternating prefix too short "
            f"(alt_pairs={alt_pairs} need>={min_alt} grants={grants} "
            f"dual_grants={dual_grants})"
        )
        # An alternating prefix of two or more grants contains both clients by
        # construction; the alternation floor above carries the claim.
        self.logger.info(
            "CHK-GRANT-ALT PASS: %d consecutive post-adapter grant pairs "
            "strictly alternate between AES and OTBN URND (grants=%s "
            "dual_grants=%s)",
            alt_pairs,
            grants[:16],
            dual_grants[:12],
        )

        # --- OTBN RND, the third adapter client ------------------------------
        # AES (bit 0) and OTBN URND (bit 3) are proven above. RND (bit 2) cannot
        # join that window: it only requests while an OTBN program is blocked on
        # the RND CSR, and OTBN cannot execute until its post-reset secure wipe
        # has consumed URND, which needs EDN already enabled. So it is driven
        # here, after the alternation proof, as its own client.
        otbn = SepOtbn(self)
        await otbn.wait_idle("post-urnd-wipe", timeout=8_000)
        await otbn.load_program(OTBN_RND_PROG)
        await otbn.start_execute()

        rnd_req_seen = False
        for _ in range(_RND_REQ_CYCLES):
            if _req() & (1 << _RND_BIT):
                rnd_req_seen = True
                break
            await RisingEdge(dut.clk_i)
        assert rnd_req_seen, (
            "CHK-RND-REQ FAIL: OTBN RND never raised crypto_edn_req bit "
            f"{_RND_BIT} while a program was blocked on the RND CSR "
            f"(last crypto_edn_req_o=0x{_req():x}). Without this request "
            "CHK5_otbn_rnd cannot fail."
        )
        self.logger.info(
            "CHK-RND-REQ PASS: OTBN raised crypto_edn_req bit %d (RND) (crypto_edn_req_o=0x%x)",
            _RND_BIT,
            _req(),
        )

        await otbn.wait_idle("post-rnd-prog", timeout=20_000)
        rnd_err = await otbn.read_errbits()
        assert rnd_err == 0, (
            f"CHK-RND-CONSUME FAIL: OTBN RND program ERR_BITS=0x{rnd_err:08x}, expected 0"
        )
        rnd_words = await otbn.read_dmem_words(OTBN_DMEM_RND_BASE, OTBN_RND_READS)
        # Each CSR read of RND is served from a fresh 256-bit EDN fetch, so a
        # DUT that latched one value and replayed it -- or that returned the
        # reset value -- fails here. This is the consume proof at the OTBN end;
        # CHK5_otbn_rnd below is the bit-exact routing proof at the adapter.
        assert len(set(rnd_words)) == OTBN_RND_READS, (
            f"CHK-RND-CONSUME FAIL: {OTBN_RND_READS} RND CSR reads returned "
            f"{len(set(rnd_words))} distinct words "
            f"({[f'0x{w:08x}' for w in rnd_words]}) -- RND was not refetched "
            "per read"
        )
        self.logger.info(
            "CHK-RND-CONSUME PASS: %d RND CSR reads retired with ERR_BITS=0 and "
            "returned %d distinct words %s",
            OTBN_RND_READS,
            len(set(rnd_words)),
            [f"0x{w:08x}" for w in rnd_words],
        )

        # --- KMAC, the fourth and last adapter client ------------------------
        # AES, OTBN URND and OTBN RND are all proven above. KMAC is the adapter's
        # remaining client, and like AES it requests while it masks. Running a
        # real keyed KMAC here makes every one of the four clients a live,
        # value-checked consumer in one run, and it is what lets the arbiter be
        # graded under its full client load rather than a subset of it.
        kmac = SepKmac(self)
        kmac_cfg = SepKmacCfg(
            mode="kmac",
            sec=256,
            msg_words=list(_KMAC_MSG),
            outlen_bytes=32,
            key_words=list(_KMAC_KEY),
            key_bits=256,
            s=_KMAC_S,
        )
        kmac_golden = kmac_family_words(**kmac_cfg.golden_kwargs())
        kmac_digest = await kmac.run_family(kmac_cfg, tag="KMAC-fourth-client")
        assert kmac_digest == kmac_golden, (
            "CHK-KMAC-CLIENT FAIL: KMAC digest does not match the Keccak golden "
            f"(got {[f'0x{w:08x}' for w in kmac_digest]}, "
            f"want {[f'0x{w:08x}' for w in kmac_golden]}). A KMAC that took EDN "
            "beats but produced the wrong digest is not a working client."
        )
        await kmac.check_status_clean("EOT")
        self.logger.info(
            "CHK-KMAC-CLIENT PASS: the KMAC adapter client completed a keyed "
            "KMAC-256 matching the Keccak golden"
        )

        # --- CHK-FOUR-CLIENT --------------------------------------------------
        # Every adapter client was granted at some point in this run. The grant
        # sampler above only watches AES and URND, so this is taken from the
        # per-client ack bits the monitor accumulated across the whole run.
        acked_mask = acked["mask"]
        missing = [b for b in _ALL_CLIENTS if not (acked_mask & (1 << b))]
        assert not missing, (
            f"CHK-FOUR-CLIENT FAIL: adapter client bit(s) {missing} were never "
            f"granted (acked_mask=0x{acked_mask:x}). drbg_axis_edn_adapter fans out "
            "to AES, KMAC, OTBN RND and OTBN URND, and this leaf drives all four."
        )
        self.logger.info(
            "CHK-FOUR-CLIENT PASS: all four adapter clients were granted in one run "
            "(acked_mask=0x%x)",
            acked_mask,
        )

        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        # Routing floors, and exactly what each one is worth.
        #
        # An unobserved beat creates no scoreboard item, so zero mismatches
        # does NOT catch a sink that routed a few beats correctly and then
        # starved. Only a floor catches that -- and a floor only catches it if
        # it is independent of the thing it bounds.
        #
        #   RND   the one real bound: derived from this test's own stimulus,
        #         OTBN_RND_READS CSR reads of _EDN_BEATS_PER_RND_READ beats
        #         each. A DUT that routed part of that and starved fails it.
        #   AES,  non-vacuity floors only. They are constants: above zero, so a
        #   URND  sink that took nothing fails, and below the traffic every
        #   KMAC, seed produces, so a seed change does not trip them. They do
        #   pool  NOT bound their sink's full stimulus.
        #
        # The floors are constants. The scoreboard scores one item per
        # req && ack cycle on the same ports the grant monitor counts, so a
        # grant-derived floor would hold by construction. The grant counts are
        # logged below as diagnostics.
        #
        # What still carries each unbounded sink: AES and URND by CHK-NO-STARVE
        # and CHK-GRANT-ALT on the grant stream; KMAC by CHK-KMAC-CLIENT, whose
        # digest cannot match the Keccak golden if its masking reseed was short.
        # The pool has nothing else here, and deriving its floor needs the
        # EDN-beats-per-pool-seed ratio -- a design fact this test does not own.
        self.drbg_sb.set_min_matches(
            CHK5_aes=_GRANT_MIN_SAMPLES,
            CHK5_otbn_urnd=_GRANT_MIN_SAMPLES,
            CHK5_otbn_rnd=OTBN_RND_READS * _EDN_BEATS_PER_RND_READ,
            CHK5_kmac=_KMAC_MIN_BEATS,
            CHK5_pool=_POOL_MIN_BEATS,
        )
        self.logger.info(
            "CHK-ROUTING floors: rnd>=%d (derived from stimulus); aes>=%d "
            "urnd>=%d kmac>=%d pool>=%d (non-vacuity only, NOT starvation "
            "bounds). Diagnostic, not a floor: %d AES and %d URND grants were "
            "observed on crypto_edn_ack_o.",
            OTBN_RND_READS * _EDN_BEATS_PER_RND_READ,
            _GRANT_MIN_SAMPLES,
            _GRANT_MIN_SAMPLES,
            _KMAC_MIN_BEATS,
            _POOL_MIN_BEATS,
            grants.count(_AES_BIT),
            grants.count(_URND_BIT),
        )
        assert self.drbg_sb.report()
        ra = self.drbg_sb.results["CHK5_aes"]
        ru = self.drbg_sb.results["CHK5_otbn_urnd"]
        rr = self.drbg_sb.results["CHK5_otbn_rnd"]
        rk = self.drbg_sb.results["CHK5_kmac"]
        rp = self.drbg_sb.results["CHK5_pool"]
        self.logger.info(
            "CHK-ROUTING PASS: CHK5_aes match=%d, CHK5_otbn_urnd match=%d, "
            "CHK5_otbn_rnd match=%d and CHK5_kmac match=%d equal the AXIS1 "
            "grant-order stream, and CHK5_pool match=%d equals the AXIS2 stream "
            "(mismatch=0 on all five)",
            ra.matches,
            ru.matches,
            rr.matches,
            rk.matches,
            rp.matches,
        )
        self.logger.info(
            "CHK1..CHK4 bit-exact + CHK5 ROUTING on all four adapter clients and "
            "the entropy pool PASS"
        )
