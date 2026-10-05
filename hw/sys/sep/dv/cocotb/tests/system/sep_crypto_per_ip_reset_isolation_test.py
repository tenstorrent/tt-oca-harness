# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A crypto engine's SW reset clears its own result and leaves a sibling's held result intact.

no_cpu host-AXI test that proves the SEP per-IP SW_RESET_N domains are isolated
while a neighbour engine holds a live, golden-checked crypto result in its
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
    self-tested env/sep_aes_golden. AES is the held-result engine in the
    SEP_VPLAN row; its masking-PRNG reseed consumes the brought-up entropy.

Entropy is brought up first (ESRC->DRBG->CSRNG->EDN) so the AES masking-PRNG
reseed is served, so the reset lands on an entropy-backed crypto op rather than
a poked status bit.

Isolation proof (both directions, then the remaining isolated bits):
  * CHK-NONVAC      both held results are golden-matched and survive a second
                    independent read, so the later survives/cleared checks are
                    observations rather than restatements of one sample.
  * CHK-SELF-RESET  the pulsed engine's held result clears to its reset value
                    (proves the pulse landed in that engine's domain).
  * CHK-NEIGHBOR-SURVIVES  the sibling's held crypto result is bit-exact intact.
  * CHK-REVERSE     roles swapped (AES-victim then HMAC-victim).
  * CHK-KMAC-SELF / CHK-KMAC-NEIGHBOR / CHK-OTBN  KMAC SHA3-256 STATE and
                    OTBN DMEM hold across a neighbour pulse. KMAC's own pulse returns STATUS to its
                    register-map reset on the fields the RDL resets, and to
                    the idle 0 on sha3_absorb/sha3_squeeze/fifo_depth/
                    fifo_full, which have no RDL reset. KMAC STATE reads 0
                    after its own pulse; that expected value is RTL-derived
                    (no spec states it). OTBN LOAD_CHECKSUM (rst_ni CSR)
                    clears to its register-map reset. DMEM is the cross-domain
                    leak check (a neighbour must not wipe it). OTBN's own reset runs
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
  * CHK-<ENG>-DRAIN-OPEN  before each drained reset request, the host isolate
                    bit reads 0 and the gated reset is still released, so the
                    drain-order check below can fail.
  * CHK-DRAIN-ORDER  the HMAC reset does not assert until both AXI-Lite paths
                    that domain depends on -- the SEP host path and the Key
                    Manager path -- report isolated. The host isolate bit
                    starts at 0 when the request is issued. The Key Manager
                    path is already isolated while the Key Manager is held at
                    its reset default, so the graded order is the host term.
  * CHK-HOST-DRAIN  host reads issued in the same cycle as the reset request
                    resolve OKAY or SLVERR, never DECERR and never a hang. The
                    exact events still unretired when the isolate request rises
                    are recorded, and at least one of those events must drain
                    OKAY -- so an earlier completed read cannot satisfy the
                    verdict.
  * CHK-DRAIN-ARRIVAL  a further read is issued on the first cycle the isolate
                    request is seen, with an empty AR queue and its own AXI ID.
                    Its AR handshake on s_axi must fall while the request is up
                    and the gated reset is still released, and it must resolve;
                    it may drain or terminate, but it may not hang.
                    CHK-ISOLATE-REOPEN, after release, shows that the path is
                    not wedged.
  * CHK-KMAC-DRAIN-ORDER / CHK-KMAC-DRAIN-ARRIVAL  the same two contracts on the
                    KMAC reset: it asserts only after the host and Key Manager
                    paths both report isolated, and a read accepted in the
                    drain window resolves OKAY or SLVERR.
  * CHK-ABR-DRAIN-ORDER  the Adams Bridge reset does not assert until both
                    paths its domain depends on report isolated: the full-AXI
                    SEP host path and the shared Key Manager path. The host
                    isolate bit starts at 0 when the request is issued. The
                    shared Key Manager path is already isolated while the Key
                    Manager is held at its reset default, so the graded order
                    is the host term.
  * CHK-ABR-HOST-DRAIN  host reads issued in the same cycle as the ABR reset
                    request resolve OKAY or SLVERR, never DECERR and never a
                    hang. The exact events still unretired when the isolate
                    request rises are recorded, and at least one of those
                    events must drain OKAY.
  * CHK-ABR-DRAIN-ARRIVAL  the CHK-DRAIN-ARRIVAL contract on the ABR full-AXI
                    isolate: the arrival AR is accepted on s_axi while the
                    request is up and the gated reset is released, and it
                    resolves.
  * CHK-ABR-JTAG-OVERRIDE  the JTAG IC_RESET override holds the Adams Bridge
                    domain in reset while SW_RESET_N still reports it released,
                    and releasing the override lets the domain come back. The
                    override is sampled against the gated reset, so a mux that
                    ignored the override select fails here.
  * CHK-TRNG-NEIGHBORS  idle HMAC DIGEST and AES DATA_OUT survive a shared
                    TRNG-only reset. SW_RESET_N inside the window shows the
                    TRNG bit held and the five accelerator bits released
                    (OTBN, AES, HMAC, KMAC, ABR).
  * CHK-EDN-PEND / CHK-EDN-PEND-AES  before EDN is enabled, OTBN URND and
                    AES each hold ``edn_req`` with ``edn_ack`` low.
  * CHK-EDN-FLUSH / CHK-EDN-FLUSH-AES  resetting that requester drops its
                    ``edn_req`` and ``edn_ack`` stays low.
  * CHK-EDN-FLUSH-KMAC  a KMAC reset while AES is requesting leaves the AES
                    ``edn_req`` high and the AES ``edn_ack`` low.
  * CHK-EDN-SIBLING  after entropy is up, with OTBN still in reset, AES
                    receives ``edn_ack`` and the OTBN URND handshake stays low.
  * CHK-EDN-REARM  releasing OTBN lets URND request again and receive
                    ``edn_ack``.
  * CHK-EDN-EDGE  URND is granted, then a KMAC software reset is stepped
                    across one measured acknowledge period. The KMAC
                    endpoint's ``edn_ack`` and ``edn_bus`` are 0 on every
                    gated-reset edge. URND may complete its own beat.
  * CHK-EDN-LEAD  a software reset of KMAC, AES or OTBN cancels that
                    engine's EDN endpoints before its gated reset asserts.
                    The endpoint holds a word when the reset is requested.
                    On the last cycle before the gated reset falls, while
                    that reset is still released, the endpoint's
                    ``edn_ack`` and ``edn_bus`` are already 0. They stay 0
                    on every cycle until the gated reset releases.
  * CHK-EDN-DISCARD  a word an endpoint held when its engine was reset is
                    never acknowledged to any client afterwards, and no
                    word is acknowledged twice across the EDN steps.
  * CHK-EDN-HOLD / CHK-EDN-HOLD-KEEP  a KMAC software reset must leave a URND
                    word unchanged when the previous cycle had not already
                    acknowledged it, and that word is the one URND is
                    acknowledged with. The cycle after an acknowledge still
                    shows the word while the acknowledge state machine pops
                    the endpoint FIFO; the empty read on the next cycle is
                    that pop, so it is not the arm.

This test proves the reset actually lands in the IP and is domain-isolated at the level of a live
crypto-datapath result, frontdoor.

Run mode: no_cpu with +skip_fuse_sense (entropy + crypto are independent of OTP
lifecycle) and +esrc_noise_force (deterministic ESRC ring-osc noise so the entropy
stack is alive under sim -- required by bring_up_entropy, same as the km/crypto
entropy tests).

Scope: the held state is a completed golden result resident in the
engine's output registers (re-readable across the sibling's reset), not a paused
mid-round micro-state. A cycle-accurate mid-round freeze and an all-pairs matrix
are not covered here; the resident-result observation proves the reset-domain
boundary against a real crypto-datapath value.
"""

from __future__ import annotations

import hashlib

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge, with_timeout
from cocotb.utils import get_sim_time
from env.sep_aes_golden import aes256_ecb_encrypt_words
from env.sep_kmac_golden import kmac_family_words
from ocah_axi_vip import worst_resp
from sep_base_test import sep_base_test
from sep_reg_meta import register_fields
from seq_lib.sep_abr_mlkem_seq import MLKEM_STATUS
from seq_lib.sep_aes_seq import AES_DATA_OUT_0, AES_TRIGGER, AES_TRIGGER_PRNG_RESEED, SepAes
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
    SW_RESET_N,
    SW_RESET_N_DEFAULT,
    SepCryptoResetIso,
)
from seq_lib.sep_hmac_seq import HMAC_CFG, HMAC_DIGEST_0, SepHmac
from seq_lib.sep_kmac_seq import (
    KMAC_CFG_SHADOWED,
    KMAC_MODE,
    KMAC_STATUS,
    KMAC_STRENGTH,
    SepKmac,
    SepKmacCfg,
    build_kmac_cfg,
)
from seq_lib.sep_otbn_seq import OTBN_DMEM_RESULT_LO, OTBN_LOAD_CHECKSUM_RESET, SepOtbn
from seq_lib.sep_sw_reset_seq import SW_RESET_N_BIT, SepSwReset

# Fixed known vectors (RAND-NONE).
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
# KMAC STATUS after its own SW_RESET_N pulse, in two parts read off the IP-XACT.
# The RDL gives sha3_idle, fifo_empty and the two alert bits a reset value; that
# part is the register-map reset. sha3_absorb, sha3_squeeze, fifo_depth and
# fifo_full have no RDL reset, so the generated DEFAULT holds a 0 placeholder for
# them. Their 0 here is the idle state their field descriptions define (not
# absorbing, not squeezing, no FIFO entries, FIFO not full), and reserved bits
# read 0. sha3_squeeze reads 1 before the pulse, so that leg discriminates.
_KMAC_STATUS_FIELDS = register_fields(KMAC_STATUS)[1]
KMAC_STATUS_RDL_MASK = sum(f.mask for f in _KMAC_STATUS_FIELDS if f.reset is not None)
KMAC_STATUS_RDL_RESET = sum(f.reset << f.lsb for f in _KMAC_STATUS_FIELDS if f.reset is not None)
KMAC_STATUS_IDLE_MASK = ~KMAC_STATUS_RDL_MASK & 0xFFFF_FFFF

_ZERO_DIGEST = [0] * 8
# s_axi ARIDs for the drain-window legs. Neither is ID 0, which the background
# entropy FIFO drain uses: the fabric holds a read back while reads with the
# same ID are outstanding to another target, and a background read held that
# way at the head of the AR channel would hold the arrival read back with it.
# The arrival read has its own ID so its AR handshake is found on the bus.
_DRAIN_ARID = 1
_ARRIVAL_ARID = 5
# Reads issued in the same cycle as the reset request, so the isolate has
# accepted traffic to drain. Few enough that the arrival read is not queued
# behind them.
_DRAIN_READS = 2
# crypto_edn_req/ack client index. AES, KMAC, OTBN RND, OTBN URND.
_EDN_AES = 0
_EDN_KMAC = 1
_EDN_URND = 3
# Cold OTBN raises URND edn_req and holds it until an ack. Bound the wait;
# a client that never requests fails here rather than spinning.
_EDN_PEND_CYCLES = 50_000
# After the requester's edn_req has fallen, sample long enough to cover the
# one-cycle adapter flush and the cycles after it.
_EDN_QUIET_CYCLES = 40
# Isolate-before-reset can take longer than the flush itself. This bound is
# only the wait for edn_req to fall, not the quiet sample.
_EDN_DROP_CYCLES = 2_000
# AES masking reseed ack after EDN is enabled. Above a real grant, below a hang.
_EDN_ACK_CYCLES = 200_000
# CHK-EDN-HOLD arming. Each attempt lands a KMAC reset edge a different
# number of cycles after a URND acknowledge, so the edge walks the phase at
# which URND holds a staged word. The check fails if none of them arm.
_EDN_HOLD_ATTEMPTS = 40
_EDN_HOLD_STEP = 13
# Recovery bound for CHK-EDN-HOLD-KEEP. The steady URND acknowledge period
# is ~10 cycles, so this is far above a re-request round trip and well below
# a hang. Exceeding it means the sibling did not recover by itself.
_EDN_KEEP_CYCLES = 20_000
# CHK-EDN-LEAD resets per engine. OTBN URND requests continuously, and its
# endpoint reads 0 on the cycle the acknowledge state machine pops a word, so
# one quiet pre-edge cycle could be that pop. Each OTBN trial issues the reset
# a different number of cycles after a URND acknowledge, and every trial must
# show the quiet cycle. AES and KMAC are idle when reset, so their held word
# leaves the bus only through the cancel.
_EDN_LEAD_TRIALS = {"kmac": 2, "aes": 2, "otbn": 6}
# Bound on the reset request's AXI write, the isolate drain and the reset
# release, in cycles.
_EDN_LEAD_CYCLES = 2_000
# Gated-reset TB probe per SW_RESET_N bit, for the engines this test pulses.
_GATED_RST_PROBE = {
    ENG_HMAC.rst_bit: "hmac_gated_rst_n_probe_o",
    ENG_AES.rst_bit: "aes_gated_rst_n_probe_o",
    ENG_KMAC.rst_bit: "kmac_gated_rst_n_probe_o",
    ENG_OTBN.rst_bit: "otbn_gated_rst_n_probe_o",
    SW_RESET_N_BIT["trng"]: "trng_gated_rst_n_probe_o",
}
# OTBN RND and URND share the OTBN reset.
_EDN_OTBN_RND = 2
# Cycles of URND traffic recorded after the last reset for CHK-EDN-DISCARD.
# A cancelled word handed to another client would be acknowledged within a
# few grants; this is ~200 URND acknowledges.
_EDN_DISCARD_WATCH_CYCLES = 2_000


def sha256_digest_words(msg_words: list[int]) -> list[int]:
    """hashlib golden: msg words pushed little-endian per word (msg_be=0); DIGEST
    word i == big-endian word i of the standard SHA-256 (digest_swap=0)."""
    msg = b"".join((w & 0xFFFF_FFFF).to_bytes(4, "little") for w in msg_words)
    h = hashlib.sha256(msg).digest()
    return [int.from_bytes(h[i * 4 : i * 4 + 4], "big") for i in range(8)]


@pyuvm.test()
class sep_crypto_per_ip_reset_isolation_test(sep_base_test):
    """Pulse one crypto engine's SW-reset; the sibling's held crypto result survives."""

    async def _wait_gated_rst(self, rst_bit: int, level: int, what: str) -> None:
        """Bounded wait for an engine's gated-reset TB probe to reach ``level``."""
        probe = getattr(cocotb.top, _GATED_RST_PROBE[rst_bit])
        for _ in range(_EDN_DROP_CYCLES):
            if self.rd_known(probe) == level:
                return
            await RisingEdge(cocotb.top.clk_i)
        raise AssertionError(
            f"{what}: {_GATED_RST_PROBE[rst_bit]} did not go {level} in {_EDN_DROP_CYCLES} cycles"
        )

    async def _pulse_reset(self, rst_bit: int) -> None:
        """Active-low pulse of one IP's SW_RESET_N (assert, settle, release, settle).

        The engine's gated-reset probe must fall after the request and rise after
        the release, so a neighbour-survives check always follows a reset that
        landed.
        """
        await self.rst.assert_reset(rst_bit)
        await self._wait_gated_rst(rst_bit, 0, "reset pulse assert")
        await ClockCycles(cocotb.top.clk_i, 40)
        await self.rst.release_resets()
        await self._wait_gated_rst(rst_bit, 1, "reset pulse release")
        await ClockCycles(cocotb.top.clk_i, 40)
        self.logger.info("reset pulse landed: %s fell and released", _GATED_RST_PROBE[rst_bit])

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

    def _require_open_isolate_terms(self, *, host, km, rst, name: str) -> None:
        """Host path and gated reset must be live before the request.

        Sample here, not in the drain loop. An idle or KM-held Key Manager
        path can already read isolated (``km_* = hmac/kmac/abr | km``), so a
        loop that treats ``km_iso==1`` at iteration 0 as the window opening
        is scoring a settled bit. The host path is the one this request
        opens; it must still be 0. The KM bit is logged, not required to
        start at 0.
        """
        host_iso = self.rd_known(host)
        km_iso = self.rd_known(km)
        gated = self.rd_known(rst)
        assert gated == 1, (
            f"{name} gated reset was already asserted before the reset request "
            "was issued, so this domain asserted reset with no drain window"
        )
        assert host_iso == 0, (
            f"{name} host isolate was already 1 before the reset request, so "
            "the host term of the drain-order check cannot fail"
        )
        self.logger.info(
            "CHK-%s-DRAIN-OPEN PASS: host_iso=0 gated=1 before the reset "
            "request (km_iso=%d already; the KM path ORs this engine with the "
            "held Key Manager isolate and is not required to start at 0)",
            name,
            km_iso,
        )

    async def _request_reset_direct(self, rst_bit: int) -> None:
        """Write SW_RESET_N on the AXI master itself, not through the sequencer.

        The drain reads must go out in the same cycle as the reset request. A
        sequencer write can wait behind a background sequence read (the
        entropy FIFO drain) for an unknown number of cycles. The value is the
        same one ``SepCryptoResetIso.assert_reset`` writes, and the B response
        is checked here.
        """
        value = SW_RESET_N_DEFAULT & ~(1 << rst_bit) & 0xFFFF_FFFF
        ev = self.env.axi_agent.driver.axi.init_write(
            address=SW_RESET_N, data=value.to_bytes(4, "little"), size=2
        )
        await with_timeout(ev.wait(), 10_000, "ns")
        code = worst_resp(getattr(ev.data, "resp", None))
        assert code == RESP_OKAY, (
            f"SW_RESET_N write of 0x{value:08x} returned resp={code}, expected OKAY"
        )

    async def _drain_with_arrival(
        self, *, name: str, addr: int, start_reset, req, host, km, rst, n_drain: int
    ) -> dict:
        """Put reads in flight across the isolate request, then time one inside it.

        The sequencer asserts the gated reset one clock after every path
        reports isolated, so the drain window is a few cycles long, and a beat
        queued behind other traffic lands after the reset (a read made during
        reset, not mid-drain). So only ``n_drain`` reads go out, in the same
        cycle as the reset request, which the fabric accepts at once and which
        are still in flight when the isolate request rises. The arrival read
        goes out on the first cycle the isolate request is seen, with an empty
        AR queue and its own AXI ID, so its AR handshake is found on the bus
        and timed against the reset edge.

        Every value the checks grade is sampled at the same clock edge in this
        one loop: the s_axi AR handshake, the isolate request, both isolate
        completion bits and the gated reset.
        """
        axi = self.env.axi_agent.driver.axi
        top = cocotb.top

        def ar_ids_this_edge() -> list[int]:
            v, r = top.s_axi_arvalid.value, top.s_axi_arready.value
            if not (v.is_resolvable and r.is_resolvable) or not (int(v) and int(r)):
                return []
            return [int(top.s_axi_arid.value)]

        self._require_open_isolate_terms(host=host, km=km, rst=rst, name=name)
        reset_task = cocotb.start_soon(start_reset())
        drain = [
            axi.init_read(address=addr, length=4, size=2, arid=_DRAIN_ARID) for _ in range(n_drain)
        ]

        arrival = None
        arrival_hs = None
        outstanding: set[int] = set()
        reset_edge = None
        for _ in range(2_000):
            await RisingEdge(top.clk_i)
            now = get_sim_time("ns")
            sample = {
                "req": self.rd_known(req),
                "host": self.rd_known(host),
                "km": self.rd_known(km),
                "rst": self.rd_known(rst),
            }
            if arrival is not None and arrival_hs is None:
                if _ARRIVAL_ARID in ar_ids_this_edge():
                    arrival_hs = dict(sample, t=now)
            if sample["rst"] == 0:
                reset_edge = dict(sample, t=now)
                break
            if arrival is None and sample["req"] == 1:
                outstanding = {id(e) for e in drain if not e.is_set()}
                arrival = axi.init_read(address=addr, length=4, size=2, arid=_ARRIVAL_ARID)
                self.logger.info(
                    "%s drain window open at %.2f ns (req=%d host_iso=%d km_iso=%d "
                    "gated=%d); %d of %d drain reads unretired; arrival read "
                    "issued with ARID %d",
                    name,
                    now,
                    sample["req"],
                    sample["host"],
                    sample["km"],
                    sample["rst"],
                    len(outstanding),
                    n_drain,
                    _ARRIVAL_ARID,
                )
        else:
            raise AssertionError(f"{name} gated reset never asserted after the reset request")
        await reset_task
        return {
            "drain": drain,
            "outstanding": outstanding,
            "arrival": arrival,
            "hs": arrival_hs,
            "reset": reset_edge,
        }

    def _check_arrival_in_window(self, rec: dict, *, name: str, chk: str) -> None:
        """The arrival AR was accepted while the isolate was up and reset released."""
        hs, edge = rec["hs"], rec["reset"]
        assert rec["arrival"] is not None, (
            f"{name}: the isolate request was never seen with the gated reset "
            f"released, so {chk} has no beat to grade"
        )
        hs_at = "never seen" if hs is None else f"at {hs['t']:.2f} ns"
        assert hs is not None and hs["t"] < edge["t"], (
            f"{name}: the arrival read's AR was not accepted on s_axi before the "
            f"gated reset asserted at {edge['t']:.2f} ns (handshake {hs_at}), so "
            f"{chk} would grade a read made during reset, not one made mid-drain"
        )
        assert hs["req"] == 1 and hs["rst"] == 1, (
            f"{name}: at the arrival AR handshake ({hs['t']:.2f} ns) req={hs['req']} "
            f"gated={hs['rst']}; the beat must enter while isolation is requested "
            "and the domain reset is still released"
        )

    async def _drain_kmac(self) -> None:
        """Assert the KMAC reset and grade its drain window.

        Two properties: the gated reset may not assert until both AXI-Lite
        paths report isolated, and a beat accepted inside the drain window
        resolves rather than hanging. The drain reads that go out with the
        request only give the isolate traffic to work through; accepted-traffic
        drain is not claimed on this domain. The Adams Bridge and HMAC legs
        carry that property.
        """
        rec = await self._drain_with_arrival(
            name="KMAC",
            addr=KMAC_STATUS,
            start_reset=lambda: self._request_reset_direct(ENG_KMAC.rst_bit),
            req=cocotb.top.kmac_host_isolate_req_probe_o,
            host=cocotb.top.kmac_host_isolated_probe_o,
            km=cocotb.top.kmac_km_isolated_probe_o,
            rst=cocotb.top.kmac_gated_rst_n_probe_o,
            n_drain=_DRAIN_READS,
        )
        edge = rec["reset"]
        assert edge["host"] == 1 and edge["km"] == 1, (
            "KMAC reset asserted before its AXI-Lite paths isolated: "
            f"host_kmac={edge['host']} km_kmac={edge['km']}"
        )
        self.logger.info(
            "CHK-KMAC-DRAIN-ORDER PASS: KMAC reset asserted at %.2f ns only after "
            "the host and Key Manager paths both reported isolated (sampled in the "
            "same cycle as the observed assert edge)",
            edge["t"],
        )
        for event in rec["drain"]:
            await with_timeout(event.wait(), 10_000, "ns")

        self._check_arrival_in_window(rec, name="KMAC", chk="CHK-KMAC-DRAIN-ARRIVAL")
        await with_timeout(rec["arrival"].wait(), 10_000, "ns")
        arrival_code = worst_resp(getattr(rec["arrival"].data, "resp", None))
        assert arrival_code in (RESP_OKAY, RESP_SLVERR), (
            f"read arriving during the KMAC isolate drain returned "
            f"resp={arrival_code}, expected OKAY (drained) or SLVERR (terminated), "
            f"never DECERR or a hang"
        )
        hs = rec["hs"]
        self.logger.info(
            "CHK-KMAC-DRAIN-ARRIVAL PASS: arrival AR accepted on s_axi at %.2f ns "
            "(req=%d host_iso=%d km_iso=%d gated=%d), %.2f ns before the gated "
            "reset asserted at %.2f ns; resolved resp=%d, no hang",
            hs["t"],
            hs["req"],
            hs["host"],
            hs["km"],
            hs["rst"],
            edge["t"] - hs["t"],
            edge["t"],
            arrival_code,
        )

        # The drain legs above only assert. Complete the pulse so the caller
        # sees the same released state _pulse_reset would have left, and the
        # STATUS readback that follows grades a reachable domain.
        await ClockCycles(cocotb.top.clk_i, 40)
        await self.rst.release_resets()
        await ClockCycles(cocotb.top.clk_i, 40)

    def _edn_level(self, sig) -> int:
        if not sig.value.is_resolvable:
            raise AssertionError(f"{sig._name} is X/Z")
        return int(sig.value)

    def _edn_req(self) -> int:
        return self._edn_level(cocotb.top.crypto_edn_req_o)

    def _edn_ack(self) -> int:
        return self._edn_level(cocotb.top.crypto_edn_ack_o)

    async def _wait_edn_req(
        self, bit: int, high: bool, cycles: int, what: str, *, ack_low: bool = False
    ) -> None:
        """Bounded wait for ``edn_req`` bit ``bit`` to reach ``high``. With
        ``ack_low``, that client's ``edn_ack`` must stay low on every sampled
        cycle, including the one where the request reaches the level."""
        for _ in range(cycles):
            if ack_low and self._edn_ack() & (1 << bit):
                raise AssertionError(
                    f"{what}: edn_ack bit {bit} high while waiting for edn_req "
                    f"(req=0x{self._edn_req():x} ack=0x{self._edn_ack():x})"
                )
            if bool(self._edn_req() & (1 << bit)) == high:
                return
            await RisingEdge(cocotb.top.clk_i)
        raise AssertionError(
            f"{what} edn_req bit {bit} did not go {'high' if high else 'low'} "
            f"in {cycles} cycles (req=0x{self._edn_req():x} ack=0x{self._edn_ack():x})"
        )

    async def _sample_edn(
        self,
        bit: int,
        *,
        req_high: bool,
        cycles: int,
        what: str,
        check_bus: bool = False,
    ) -> None:
        """Every cycle of the window: this client's ack stays low, and its req
        stays at the level the reset is required to leave. With ``check_bus``,
        this client's ``edn_bus`` word is also 0 on every cycle."""
        for _ in range(cycles):
            req = self._edn_req()
            ack = self._edn_ack()
            if ack & (1 << bit):
                raise AssertionError(
                    f"{what}: edn_ack bit {bit} high (req=0x{req:x} ack=0x{ack:x})"
                )
            if bool(req & (1 << bit)) != req_high:
                raise AssertionError(
                    f"{what}: edn_req bit {bit} is {'low' if req_high else 'high'} "
                    f"(req=0x{req:x} ack=0x{ack:x})"
                )
            if check_bus:
                bus = self._edn_bus_word(bit)
                if bus:
                    raise AssertionError(
                        f"{what}: edn_bus word {bit} is 0x{bus:08x}, not 0 "
                        f"(req=0x{req:x} ack=0x{ack:x})"
                    )
            await RisingEdge(cocotb.top.clk_i)

    async def _prove_edn_cancel_before_grant(self) -> None:
        """Cancel an EDN request that has not been granted.

        EDN is still disabled, so a high ``edn_req`` with a low ``edn_ack`` is
        an outstanding request. Resetting that client must drop the request
        without an ack. Resetting a different client clears only that
        client's endpoint and must leave this request asserted.
        """
        await self._wait_edn_req(_EDN_URND, True, _EDN_PEND_CYCLES, "OTBN URND")
        if self._edn_ack() & (1 << _EDN_URND):
            raise AssertionError("OTBN URND edn_ack before EDN is enabled")
        self.logger.info(
            "CHK-EDN-PEND PASS: OTBN URND edn_req high and edn_ack low before EDN is enabled"
        )

        await self.rst.assert_reset(ENG_OTBN.rst_bit)
        await self._wait_edn_req(
            _EDN_URND, False, _EDN_DROP_CYCLES, "CHK-EDN-FLUSH OTBN drop", ack_low=True
        )
        await self._sample_edn(
            _EDN_URND, req_high=False, cycles=_EDN_QUIET_CYCLES, what="CHK-EDN-FLUSH OTBN"
        )
        self.logger.info("CHK-EDN-FLUSH PASS: OTBN reset dropped URND edn_req and edn_ack stayed 0")
        await self.rst.release_resets()

        # The trigger bit raises edn_req and holds it until EDN grants the reseed.
        # Waiting for AES idle here cannot finish: EDN is still disabled.
        await self.aes._wr(AES_TRIGGER, AES_TRIGGER_PRNG_RESEED)
        await self._wait_edn_req(_EDN_AES, True, _EDN_PEND_CYCLES, "AES")
        if self._edn_ack() & (1 << _EDN_AES):
            raise AssertionError("AES edn_ack before EDN is enabled")
        self.logger.info(
            "CHK-EDN-PEND-AES PASS: AES edn_req high and edn_ack low before EDN is enabled"
        )

        await self.rst.assert_reset(ENG_KMAC.rst_bit)
        # The sibling window starts only once the KMAC gated reset has fallen,
        # and must end with it still asserted.
        await self._wait_gated_rst(ENG_KMAC.rst_bit, 0, "CHK-EDN-FLUSH-KMAC reset")
        await self._sample_edn(
            _EDN_AES,
            req_high=True,
            cycles=_EDN_DROP_CYCLES,
            what="CHK-EDN-FLUSH KMAC sibling",
        )
        if self.rd_known(cocotb.top.kmac_gated_rst_n_probe_o) != 0:
            raise AssertionError(
                "CHK-EDN-FLUSH-KMAC FAIL: KMAC gated reset released inside the sibling window"
            )
        self.logger.info(
            "CHK-EDN-FLUSH-KMAC PASS: KMAC reset left the pending AES edn_req high "
            "and AES edn_ack low"
        )
        await self.rst.release_resets()

        await self._wait_edn_req(_EDN_AES, True, _EDN_DROP_CYCLES, "AES still pending")
        await self.rst.assert_reset(ENG_AES.rst_bit)
        await self._wait_edn_req(
            _EDN_AES, False, _EDN_DROP_CYCLES, "CHK-EDN-FLUSH AES drop", ack_low=True
        )
        await self._sample_edn(
            _EDN_AES, req_high=False, cycles=_EDN_QUIET_CYCLES, what="CHK-EDN-FLUSH AES"
        )
        self.logger.info(
            "CHK-EDN-FLUSH-AES PASS: AES reset dropped AES edn_req and edn_ack stayed 0"
        )
        # Leave OTBN in reset across entropy bring-up. assert_reset restores
        # every other engine, including AES, to the released default.
        await self.rst.assert_reset(ENG_OTBN.rst_bit)
        await self._wait_edn_req(_EDN_URND, False, _EDN_DROP_CYCLES, "OTBN held")

    async def _prove_edn_sibling_after_flush(self) -> None:
        """With OTBN held in reset, AES must still be granted, and the cancelled
        URND request must not be acknowledged. Releasing OTBN must let URND
        request and be acknowledged again."""
        await self.aes._wr(AES_TRIGGER, AES_TRIGGER_PRNG_RESEED)
        granted = False
        for _ in range(_EDN_ACK_CYCLES):
            req = self._edn_req()
            ack = self._edn_ack()
            if ack & (1 << _EDN_URND) or req & (1 << _EDN_URND):
                raise AssertionError(
                    "CHK-EDN-SIBLING FAIL: URND handshake while OTBN is in reset "
                    f"(req=0x{req:x} ack=0x{ack:x})"
                )
            if ack & (1 << _EDN_AES):
                granted = True
            if granted and not (req & (1 << _EDN_AES)):
                break
            await RisingEdge(cocotb.top.clk_i)
        else:
            raise AssertionError(
                "CHK-EDN-SIBLING FAIL: AES edn_req was not granted while OTBN is in reset "
                f"(req=0x{self._edn_req():x} ack=0x{self._edn_ack():x})"
            )
        await self._sample_edn(
            _EDN_URND, req_high=False, cycles=_EDN_QUIET_CYCLES, what="CHK-EDN-SIBLING"
        )
        self.logger.info(
            "CHK-EDN-SIBLING PASS: AES edn_ack while OTBN is in reset; URND edn_ack stayed 0"
        )
        await self.aes.wait_idle("edn-sibling-reseed")

        await self.rst.release_resets()
        await self._wait_edn_req(_EDN_URND, True, _EDN_PEND_CYCLES, "OTBN URND after release")
        for _ in range(_EDN_ACK_CYCLES):
            if self._edn_ack() & (1 << _EDN_URND):
                self.logger.info(
                    "CHK-EDN-REARM PASS: OTBN URND edn_req was acknowledged after release"
                )
                return
            await RisingEdge(cocotb.top.clk_i)
        raise AssertionError(
            "CHK-EDN-REARM FAIL: OTBN URND edn_req was not acknowledged after release "
            f"(req=0x{self._edn_req():x} ack=0x{self._edn_ack():x})"
        )

    def _edn_bus_word(self, bit: int) -> int:
        bus = self._edn_level(cocotb.top.crypto_edn_bus_o)
        return (bus >> (32 * bit)) & 0xFFFF_FFFF

    def _edn_fips(self, bit: int) -> bool:
        return bool(self._edn_level(cocotb.top.crypto_edn_fips_o) & (1 << bit))

    def _edn_snap(self, bit: int) -> dict:
        return {
            "req": bool(self._edn_req() & (1 << bit)),
            "ack": bool(self._edn_ack() & (1 << bit)),
            "bus": self._edn_bus_word(bit),
            "fips": self._edn_fips(bit),
        }

    def _require_kmac_suppressed(self, tag: str, where: str, snap: dict) -> None:
        """The KMAC endpoint's response is gated off while its reset is low."""
        if snap["ack"] or snap["bus"] or snap["fips"]:
            raise AssertionError(
                f"{tag} FAIL: KMAC endpoint response was live {where} "
                f"(ack={int(snap['ack'])} bus=0x{snap['bus']:08x} "
                f"fips={int(snap['fips'])})"
            )

    def _require_urnd_undisturbed(self, tag: str, where: str, pre: dict | None, cur: dict) -> None:
        """A KMAC reset must not cancel or rewrite URND's beat.

        URND may acknowledge on the edge. That ack has to present URND's own
        word. An ack of a zero bus, a rewritten word, or a dropped request
        with no ack is the endpoint clear reaching the sibling.
        """
        if pre is None:
            raise AssertionError(f"{tag} FAIL: no URND sample before the KMAC reset {where}")
        if cur["ack"]:
            if cur["bus"] == 0:
                raise AssertionError(
                    f"{tag} FAIL: URND edn_ack with a zero bus {where} "
                    f"(pre bus=0x{pre['bus']:08x}). A KMAC reset must not "
                    "clear the sibling beat"
                )
            if not pre["ack"] and pre["bus"] != 0 and cur["bus"] != pre["bus"]:
                raise AssertionError(
                    f"{tag} FAIL: URND bus 0x{pre['bus']:08x}->0x{cur['bus']:08x} "
                    f"{where} on an acknowledge, so the completed beat is not "
                    "the word URND had staged"
                )
            return
        # The cycle after URND's own ack retires the request. That drop is
        # the handshake ending, not the KMAC reset cancelling it. A zero bus
        # with ack low is the empty gap between URND beats. Replacing a
        # requested word with a different word is not that gap.
        if pre["ack"]:
            return
        if pre["req"] and not cur["req"]:
            raise AssertionError(
                f"{tag} FAIL: KMAC reset dropped URND edn_req {where} "
                f"(pre bus=0x{pre['bus']:08x}) with edn_ack low"
            )
        if (
            pre["req"]
            and pre["bus"] != 0
            and cur["bus"] != 0
            and (cur["bus"] != pre["bus"] or cur["fips"] != pre["fips"])
        ):
            raise AssertionError(
                f"{tag} FAIL: KMAC reset replaced URND bus "
                f"0x{pre['bus']:08x}->0x{cur['bus']:08x} fips "
                f"{int(pre['fips'])}->{int(cur['fips'])} {where} with edn_ack low"
            )

    async def _arm_kmac_edn(self, tag: str) -> None:
        """Commit KMAC CFG with EDN entropy so the masking PRNG raises edn_req."""
        if self._edn_req() & (1 << _EDN_KMAC) and not (self._edn_ack() & (1 << _EDN_KMAC)):
            return
        cfg = build_kmac_cfg(
            mode=KMAC_MODE["sha3"],
            kstrength=KMAC_STRENGTH[256],
            kmac_en=False,
        )
        kmac = SepKmac(self)
        await kmac._wr(KMAC_CFG_SHADOWED, cfg)
        await kmac._wr(KMAC_CFG_SHADOWED, cfg)
        for _ in range(_EDN_PEND_CYCLES):
            if self._edn_req() & (1 << _EDN_KMAC):
                return
            await RisingEdge(cocotb.top.clk_i)
        raise AssertionError(
            f"{tag} FAIL: KMAC edn_req did not rise after CFG entropy_ready "
            f"(req=0x{self._edn_req():x} ack=0x{self._edn_ack():x})"
        )

    async def _arm_urnd(self, tag: str) -> None:
        """Pulse OTBN so URND edn_req is high again after a KMAC reset."""
        await self.rst.assert_reset(ENG_OTBN.rst_bit)
        await self._wait_edn_req(_EDN_URND, False, _EDN_DROP_CYCLES, f"{tag} OTBN hold")
        await self.rst.release_resets()
        await self._wait_edn_req(_EDN_URND, True, _EDN_PEND_CYCLES, f"{tag} OTBN release")

    async def _prove_kmac_edn_edge(self, tag: str) -> None:
        """A KMAC software reset suppresses only the KMAC EDN endpoint.

        URND is granted on a steady cadence. Each step re-arms that stream,
        waits ``offset`` cycles past a grant, and resets KMAC. The offset
        walks one measured acknowledge period. On the falling edge of the
        KMAC gated reset the KMAC response is 0, and URND may acknowledge
        its own word. The software-reset write is an AXI transaction and
        outlasts one KMAC seed, so a KMAC request outstanding on the edge is
        graded only when one occurs. CHK-EDN-LEAD grades the cancel ahead of
        the reset.
        """
        clk = cocotb.top.clk_i
        acks: list[int] = []
        edge: list[dict] = []
        prev_ack = False
        prev_rst = 1
        prev_urnd: dict | None = None
        prev_kmac: dict | None = None
        cycle = 0
        stop = False

        async def watch() -> None:
            nonlocal prev_ack, prev_rst, prev_urnd, prev_kmac, cycle
            while not stop:
                await RisingEdge(clk)
                await ReadOnly()
                cycle += 1
                urnd = self._edn_snap(_EDN_URND)
                kmac = self._edn_snap(_EDN_KMAC)
                rst = self._edn_level(cocotb.top.kmac_gated_rst_n_probe_o)
                if urnd["ack"] and not prev_ack:
                    acks.append(cycle)
                if not edge and prev_rst == 1 and rst == 0:
                    edge.append(
                        {
                            "urnd_pre": prev_urnd,
                            "urnd": urnd,
                            "kmac_pre": prev_kmac,
                            "kmac": kmac,
                        }
                    )
                prev_ack = urnd["ack"]
                prev_rst = rst
                prev_urnd = urnd
                prev_kmac = kmac

        async def take_edge(where: str) -> dict:
            edge.clear()
            await self.rst.assert_reset(ENG_KMAC.rst_bit)
            for _ in range(_EDN_DROP_CYCLES):
                if edge:
                    break
                await RisingEdge(clk)
            else:
                raise AssertionError(f"{tag} FAIL: KMAC gated reset did not fall {where}")
            snap = edge[0]
            where_txt = f"on the KMAC reset edge {where}"
            self._require_kmac_suppressed(tag, where_txt, snap["kmac"])
            self._require_urnd_undisturbed(tag, where_txt, snap["urnd_pre"], snap["urnd"])
            return snap

        watch_task = cocotb.start_soon(watch())
        try:
            if not (self._edn_req() & (1 << _EDN_URND)):
                await self._arm_urnd(tag)
            for _ in range(_EDN_ACK_CYCLES):
                if len(acks) >= 5:
                    break
                await RisingEdge(clk)
            else:
                raise AssertionError(
                    f"{tag} FAIL: URND edn_ack did not repeat ({len(acks)} pulses)"
                )
            recent = [acks[i] - acks[i - 1] for i in range(1, len(acks))][-4:]
            steady = max(recent)
            if not 2 <= steady <= 16:
                raise AssertionError(
                    f"{tag} FAIL: URND acknowledge period {steady} is not walkable"
                )
            self.logger.info("%s: steady URND edn_ack gap %d cycles", tag, steady)
            urnd_completions = 0
            for offset in range(steady):
                if offset:
                    await self._arm_urnd(tag)
                base = len(acks)
                for _ in range(_EDN_ACK_CYCLES):
                    if len(acks) >= base + 3:
                        break
                    await RisingEdge(clk)
                else:
                    raise AssertionError(
                        f"{tag} FAIL: URND edn_ack did not resume before "
                        f"offset {offset} (req=0x{self._edn_req():x} "
                        f"ack=0x{self._edn_ack():x})"
                    )
                await ClockCycles(clk, offset)
                snap = await take_edge(f"at offset {offset}")
                await self.rst.release_resets()
                cur = snap["urnd"]
                pre = snap["urnd_pre"]
                if cur["ack"]:
                    urnd_completions += 1
                self.logger.info(
                    "%s offset %d: KMAC edn_ack=%d bus=0x%08x; URND edn_ack=%d bus 0x%08x->0x%08x",
                    tag,
                    offset,
                    int(snap["kmac"]["ack"]),
                    snap["kmac"]["bus"],
                    int(cur["ack"]),
                    pre["bus"] if pre else 0,
                    cur["bus"],
                )
            if urnd_completions < 1:
                raise AssertionError(
                    f"{tag} FAIL: URND edn_ack was never high on a KMAC reset "
                    f"edge across {steady} offsets, so the walk never showed a "
                    "sibling beat completing"
                )
            await self._arm_kmac_edn(tag)
            snap = await take_edge("after a KMAC edn_req")
            pre_k = snap["kmac_pre"]
            outstanding = bool(pre_k and pre_k["req"] and not pre_k["ack"])
            self.logger.info(
                "%s suppress: KMAC pre-edge req=%d ack=%d bus=0x%08x; on the "
                "edge req=%d ack=%d bus=0x%08x",
                tag,
                int(pre_k["req"]) if pre_k else 0,
                int(pre_k["ack"]) if pre_k else 0,
                pre_k["bus"] if pre_k else 0,
                int(snap["kmac"]["req"]),
                int(snap["kmac"]["ack"]),
                snap["kmac"]["bus"],
            )
            if outstanding:
                if snap["kmac"]["req"]:
                    raise AssertionError(
                        f"{tag} FAIL: KMAC edn_req stayed high on the reset "
                        f"edge (bus=0x{snap['kmac']['bus']:08x})"
                    )
                await self._sample_edn(
                    _EDN_KMAC,
                    req_high=False,
                    cycles=_EDN_QUIET_CYCLES,
                    what=f"{tag} KMAC suppressed",
                    check_bus=True,
                )
                self.logger.info(
                    "%s PASS: KMAC edn_ack and edn_bus stayed 0 on all %d reset "
                    "edges; URND acknowledged its own beat on %d of them; an "
                    "outstanding KMAC edn_req (bus=0x%08x on the cycle before "
                    "the edge) was quiet on the edge, and KMAC edn_req, edn_ack "
                    "and edn_bus stayed 0 on every cycle of the %d-cycle quiet "
                    "window",
                    tag,
                    steady,
                    urnd_completions,
                    pre_k["bus"],
                    _EDN_QUIET_CYCLES,
                )
            else:
                self.logger.info(
                    "%s PASS: KMAC edn_ack and edn_bus stayed 0 on all %d reset "
                    "edges; URND acknowledged its own beat on %d of them. The "
                    "software-reset write outlasts one KMAC seed, so no KMAC "
                    "request was outstanding on the last edge",
                    tag,
                    steady,
                    urnd_completions,
                )
        finally:
            stop = True
            await RisingEdge(clk)
            await watch_task
            await self.rst.release_resets()

    async def _prove_edn_sibling_hold(self, tag: str) -> None:
        """A KMAC software reset must not disturb URND's in-flight EDN data.

        KMAC is the engine being reset; URND is a sibling that is not. While
        URND holds ``edn_req`` with a word already presented on ``edn_bus``
        and no acknowledge yet, that word and its ``edn_fips`` must not
        change because an unrelated engine was reset, and it must still be
        the word URND is finally acknowledged with.

        ``prim_edn_req`` feeds ``{edn_fips, edn_bus}`` into
        ``prim_sync_reqack_data`` with ``DataSrc2Dst=0``, whose
        ``SyncReqAckDataHoldDst2Src`` contract requires the data to hold
        across the handshake window. Resetting KMAC clears only the KMAC
        endpoint, so a sibling word that changes on that edge breaks the
        contract.

        The acknowledge state machine pops its endpoint FIFO on some cycles
        where ``edn_ack`` is already low. The next cycle reads 0 because the
        FIFO is empty, and the grant after that is the next word. That gap
        is URND retiring its own beat. The arm is an edge that still
        presents the staged word. An edge that presents a different word
        fails on that attempt. If every candidate edge zeroes the word, the
        check fails. The acknowledge of the armed word may be the reset-edge
        cycle itself.
        """
        clk = cocotb.top.clk_i
        armed: dict = {}
        delivered: list[tuple[int, int]] = []
        seen = False
        gap_pre = None
        gaps = 0
        stop = False

        async def watch() -> None:
            nonlocal seen, gap_pre
            prev = None
            prev2 = None
            want_ack = False
            while not stop:
                await RisingEdge(clk)
                await ReadOnly()
                req = bool(self._edn_req() & (1 << _EDN_URND))
                ack = bool(self._edn_ack() & (1 << _EDN_URND))
                bus = self._edn_bus_word(_EDN_URND)
                fips = int(self._edn_fips(_EDN_URND))
                rst = self._edn_level(cocotb.top.kmac_gated_rst_n_probe_o)
                if want_ack and ack:
                    delivered.append((bus, fips))
                    want_ack = False
                if prev is not None and prev["rst"] == 1 and rst == 0 and not seen:
                    seen = True
                    already = (
                        prev2 is not None
                        and prev2["ack"]
                        and prev2["bus"] == prev["bus"]
                        and prev["bus"] != 0
                    )
                    pending = prev["req"] and not prev["ack"] and prev["bus"] != 0 and not already
                    cur = {"bus": bus, "fips": fips, "req": req, "ack": ack}
                    if pending and bus == prev["bus"] and fips == prev["fips"]:
                        armed.update(pre=prev, cur=cur)
                        want_ack = True
                        if ack:
                            delivered.append((bus, fips))
                            want_ack = False
                    elif pending and bus == 0 and not ack:
                        gap_pre = prev
                    elif pending:
                        armed.update(pre=prev, cur=cur)
                prev2 = prev
                prev = {"req": req, "ack": ack, "bus": bus, "fips": fips, "rst": rst}

        watch_task = cocotb.start_soon(watch())
        try:
            for attempt in range(_EDN_HOLD_ATTEMPTS):
                if armed:
                    break
                seen = False
                gap_pre = None
                if not (self._edn_req() & (1 << _EDN_URND)):
                    await self._arm_urnd(tag)
                for _ in range(_EDN_ACK_CYCLES):
                    if self._edn_ack() & (1 << _EDN_URND):
                        break
                    await RisingEdge(clk)
                else:
                    raise AssertionError(
                        f"{tag} SETUP FAILED (not a contract result): URND "
                        f"stopped being acknowledged before attempt {attempt}"
                    )
                await ClockCycles(clk, attempt % _EDN_HOLD_STEP)
                await self.rst.assert_reset(ENG_KMAC.rst_bit)
                for _ in range(_EDN_DROP_CYCLES):
                    if seen:
                        break
                    await RisingEdge(clk)
                await self.rst.release_resets()
                if gap_pre is not None and not armed:
                    gaps += 1
                    self.logger.info(
                        "%s attempt %d: empty-FIFO gap, URND bus "
                        "0x%08x->0 with edn_ack low; not the arm",
                        tag,
                        attempt,
                        gap_pre["bus"],
                    )
            if not armed:
                if gaps:
                    raise AssertionError(
                        f"{tag} FAIL: {gaps} KMAC reset edges each zeroed a "
                        "URND word that was staged with edn_ack low, and none "
                        "left that word present. The sibling word did not "
                        "survive the edge."
                    )
                raise AssertionError(
                    f"{tag} FAIL: no KMAC reset edge landed while URND held a "
                    f"staged word ({_EDN_HOLD_ATTEMPTS} attempts). The check "
                    "never armed, so it proves nothing."
                )
            pre = armed["pre"]
            cur = armed["cur"]
            self.logger.info(
                "%s armed: URND staged bus=0x%08x fips=%d before the KMAC "
                "reset edge; on the edge bus=0x%08x fips=%d",
                tag,
                pre["bus"],
                pre["fips"],
                cur["bus"],
                cur["fips"],
            )
            # Both halves are reported from one armed edge, so a run shows
            # the data-hold break and the lost word together instead of
            # stopping at the first.
            failures: list[str] = []
            if cur["bus"] != pre["bus"] or cur["fips"] != pre["fips"]:
                failures.append(
                    f"{tag} FAIL: the KMAC reset rewrote a sibling's in-flight "
                    f"EDN data. URND bus 0x{pre['bus']:08x}->0x{cur['bus']:08x} "
                    f"fips {pre['fips']}->{cur['fips']} across the reset edge "
                    f"(edge edn_req={int(cur['req'])} edn_ack={int(cur['ack'])}), "
                    "and the previous cycle had not acknowledged that word. "
                    "This breaks the prim_sync_reqack_data DataSrc2Dst=0 hold "
                    "contract."
                )
                self.logger.error(failures[-1])
            else:
                self.logger.info(
                    "%s PASS: URND bus 0x%08x and fips %d were unchanged across a KMAC reset edge",
                    tag,
                    pre["bus"],
                    pre["fips"],
                )
            for _ in range(_EDN_KEEP_CYCLES):
                if delivered:
                    break
                await RisingEdge(clk)
            else:
                failures.append(
                    f"{tag}-KEEP FAIL: URND was not acknowledged within "
                    f"{_EDN_KEEP_CYCLES} cycles of the KMAC reset, so the "
                    f"staged word 0x{pre['bus']:08x} was lost and the client "
                    "did not recover on its own"
                )
                self.logger.error(failures[-1])
                delivered.append((-1, -1))
            got_bus, got_fips = delivered[0]
            if got_bus == -1:
                pass
            elif got_bus != pre["bus"] or got_fips != pre["fips"]:
                failures.append(
                    f"{tag}-KEEP FAIL: URND had 0x{pre['bus']:08x} (fips "
                    f"{pre['fips']}) staged when KMAC was reset, but was "
                    f"acknowledged with 0x{got_bus:08x} (fips {got_fips}). "
                    "An unrelated engine's reset discarded a sibling's "
                    "entropy word."
                )
                self.logger.error(failures[-1])
            else:
                self.logger.info(
                    "%s-KEEP PASS: URND was acknowledged with the same word "
                    "0x%08x it had staged before the KMAC reset",
                    tag,
                    pre["bus"],
                )
            if failures:
                raise AssertionError(" | ".join(failures))
        finally:
            stop = True
            await RisingEdge(clk)
            await watch_task
            await self.rst.release_resets()

    async def _watch_edn_acks(self) -> None:
        """Record every crypto EDN acknowledge as ``(cycle, client, word)``."""
        clk = cocotb.top.clk_i
        while not self._edn_log_stop:
            await RisingEdge(clk)
            await ReadOnly()
            self._edn_cycle += 1
            ack = self._edn_ack()
            for bit in range(4):
                if ack & (1 << bit):
                    self._edn_acked.append((self._edn_cycle, bit, self._edn_bus_word(bit)))

    async def _edn_lead_trial(
        self, tag: str, eng, bits: tuple[int, ...], rst_sig, *, delay: int, idle: bool
    ) -> dict[int, int]:
        """One software reset of ``eng``, graded for the cancel ahead of it.

        The reset is requested on a cycle where ``bits[0]`` holds a word with
        ``edn_ack`` low, at least ``delay`` cycles after that endpoint's last
        acknowledge. With ``idle`` the engine's ``edn_req`` must also be low,
        so the acknowledge state machine has no request to pop the word for
        and only a cancel can clear it. The last cycle before ``rst_sig`` falls must show every
        endpoint in ``bits`` with ``edn_ack`` and ``edn_bus`` at 0 while the
        reset is still released, and each asserted-reset cycle must too.
        Returns the words the endpoints held when the reset was requested.
        """
        clk = cocotb.top.clk_i
        lead_bit = bits[0]
        since_ack = 0
        for _ in range(_EDN_ACK_CYCLES):
            await RisingEdge(clk)
            await ReadOnly()
            if self._edn_ack() & (1 << lead_bit):
                since_ack = 0
                continue
            since_ack += 1
            if idle and self._edn_req() & (1 << lead_bit):
                continue
            if since_ack > delay and self._edn_bus_word(lead_bit):
                break
        else:
            raise AssertionError(
                f"{tag} SETUP FAILED (not a contract result): {eng.name} endpoint "
                f"{lead_bit} never held a word with edn_ack low"
                + (" and edn_req low" if idle else "")
            )
        held = {b: self._edn_bus_word(b) for b in bits}
        issued_at = self._edn_cycle
        if self._edn_level(rst_sig) != 1:
            raise AssertionError(f"{tag} FAIL: {eng.name} gated reset already asserted")
        await RisingEdge(clk)
        reset_task = cocotb.start_soon(self.rst.assert_reset(eng.rst_bit))

        def quiet(snap: dict) -> bool:
            return all(not snap["ack"][b] and snap["bus"][b] == 0 for b in bits)

        def sample() -> dict:
            ack = self._edn_ack()
            return {
                "rst": self._edn_level(rst_sig),
                "ack": {b: bool(ack & (1 << b)) for b in bits},
                "bus": {b: self._edn_bus_word(b) for b in bits},
            }

        samples: list[dict] = []
        for _ in range(_EDN_LEAD_CYCLES):
            await RisingEdge(clk)
            await ReadOnly()
            samples.append(sample())
            if samples[-1]["rst"] == 0:
                break
        else:
            raise AssertionError(f"{tag} FAIL: {eng.name} gated reset did not fall")
        if len(samples) < 2:
            raise AssertionError(
                f"{tag} FAIL: {eng.name} gated reset fell on the first cycle after "
                "the request, so no pre-edge cycle was sampled"
            )
        lead = 0
        for snap in reversed(samples[:-1]):
            if snap["rst"] != 1 or not quiet(snap):
                break
            lead += 1
        pre = samples[-2]
        if lead < 1:
            raise AssertionError(
                f"{tag} FAIL: {eng.name} endpoint still live on the last cycle "
                f"before its gated reset fell (ack={pre['ack']} bus="
                f"{ {b: hex(w) for b, w in pre['bus'].items()} }; held "
                f"{ {b: hex(w) for b, w in held.items()} } at the request). The "
                "cancel did not precede the reset"
            )

        def require_quiet(snap: dict) -> None:
            if not quiet(snap):
                raise AssertionError(
                    f"{tag} FAIL: {eng.name} endpoint live while its gated reset "
                    f"is asserted (ack={snap['ack']} bus="
                    f"{ {b: hex(w) for b, w in snap['bus'].items()} })"
                )

        # The falling-edge sample is the first asserted-reset cycle. Every later
        # cycle is sampled too; the release is issued once the reset write has
        # completed, from the normal phase of a clock edge.
        require_quiet(samples[-1])
        reset_cycles = 1
        release_task = None
        for _ in range(_EDN_LEAD_CYCLES):
            await RisingEdge(clk)
            if release_task is None and reset_task.done():
                release_task = cocotb.start_soon(self.rst.release_resets())
            await ReadOnly()
            snap = sample()
            if snap["rst"] == 1:
                break
            reset_cycles += 1
            require_quiet(snap)
        else:
            raise AssertionError(f"{tag} FAIL: {eng.name} gated reset did not release")
        await RisingEdge(clk)
        if release_task is None:
            raise AssertionError(f"{tag} FAIL: {eng.name} released before its release write")
        await release_task
        self.logger.info(
            "%s %s trial: held %s at the request; edn_ack and edn_bus 0 on %d "
            "cycle(s) before the gated reset fell and on all %d asserted-reset cycles",
            tag,
            eng.name,
            {b: f"0x{w:08x}" for b, w in held.items()},
            lead,
            reset_cycles,
        )
        for b, w in held.items():
            if w:
                self._edn_discarded.append((issued_at, b, w))
        return held

    async def _prove_edn_cancel_lead(self, tag: str) -> None:
        """A software reset cancels the engine's endpoints before it asserts.

        KMAC and AES are idle when reset, holding the word of their last
        acknowledge. OTBN URND requests continuously, so its trials start
        at a different offset from a URND acknowledge each time.
        """
        # KMAC: take one seed, so the endpoint holds the acknowledged word.
        for trial in range(_EDN_LEAD_TRIALS["kmac"]):
            await self._arm_kmac_edn(f"{tag} kmac trial {trial}")
            await self._edn_lead_trial(
                tag, ENG_KMAC, (_EDN_KMAC,), cocotb.top.kmac_gated_rst_n_probe_o, delay=0, idle=True
            )
        # AES: a PRNG reseed leaves the endpoint holding its last word.
        for trial in range(_EDN_LEAD_TRIALS["aes"]):
            await self.aes._wr(AES_TRIGGER, AES_TRIGGER_PRNG_RESEED)
            await self.aes.wait_idle(f"{tag} aes trial {trial}")
            await self._edn_lead_trial(
                tag, ENG_AES, (_EDN_AES,), cocotb.top.aes_gated_rst_n_probe_o, delay=0, idle=True
            )
        for trial in range(_EDN_LEAD_TRIALS["otbn"]):
            # A cold OTBN requests URND until acknowledged; the AES and KMAC
            # trials above can leave it idle, so pulse it back if so.
            if not (self._edn_req() & (1 << _EDN_URND)):
                await self._arm_urnd(f"{tag} otbn {trial}")
            await self._edn_lead_trial(
                tag,
                ENG_OTBN,
                (_EDN_URND, _EDN_OTBN_RND),
                cocotb.top.otbn_gated_rst_n_probe_o,
                delay=trial,
                idle=False,
            )
        self.logger.info(
            "%s PASS: %d KMAC, %d AES and %d OTBN software resets each showed "
            "the engine's EDN endpoints with edn_ack and edn_bus at 0 on the last "
            "cycle before the gated reset fell, while it was still released, and "
            "on every asserted-reset cycle",
            tag,
            _EDN_LEAD_TRIALS["kmac"],
            _EDN_LEAD_TRIALS["aes"],
            _EDN_LEAD_TRIALS["otbn"],
        )

    def _check_edn_discard(self, tag: str) -> None:
        """No word held by a reset endpoint is acknowledged after that reset."""
        if not self._edn_discarded:
            raise AssertionError(f"{tag} FAIL: no reset endpoint held a word, so nothing is graded")
        redelivered = []
        unacked = 0
        for at, bit, word in self._edn_discarded:
            before = [a for a in self._edn_acked if a[2] == word and a[0] <= at]
            after = [a for a in self._edn_acked if a[2] == word and a[0] > at]
            if not before:
                unacked += 1
            if after:
                redelivered.append((bit, word, after))
        if redelivered:
            raise AssertionError(
                f"{tag} FAIL: a word held by a reset endpoint was acknowledged "
                "after the reset: "
                + "; ".join(
                    f"endpoint {b} word 0x{w:08x} -> "
                    + ", ".join(f"client {c} at cycle {t}" for t, c, _ in a)
                    for b, w, a in redelivered
                )
            )
        self.logger.info(
            "%s PASS: %d words held by reset endpoints (%d not yet acknowledged "
            "when the reset was requested) were never acknowledged to any client "
            "afterwards, across %d recorded acknowledges",
            tag,
            len(self._edn_discarded),
            unacked,
            len(self._edn_acked),
        )

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        self.rst = SepCryptoResetIso(self)
        self.aes = SepAes(self)
        await self._prove_edn_cancel_before_grant()

        # Entropy up so the AES masking-PRNG reseed is served.
        # strict=False / score_km=False: this test asserts on the held crypto
        # results, not on the bit-exact DRBG golden stream. The scoreboard
        # observes the AES and KMAC EDN legs, and its report() must pass at the
        # end of the test.
        # OTBN stays in the reset taken above, so its cancelled URND request is
        # not granted when EDN starts.
        await self.bring_up_entropy(
            strict=False, score_km=False, score_sinks={"aes": "observe", "kmac": "observe"}
        )
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.start_fifo_drain()
        self._edn_acked: list[tuple[int, int, int]] = []
        self._edn_discarded: list[tuple[int, int, int]] = []
        self._edn_cycle = 0
        self._edn_log_stop = False
        ack_log = cocotb.start_soon(self._watch_edn_acks())
        await self._prove_edn_sibling_after_flush()
        await self._prove_kmac_edn_edge("CHK-EDN-EDGE")
        await self._prove_edn_cancel_lead("CHK-EDN-LEAD")
        # Runs here because the URND grant stream is live only while entropy
        # is flowing; by the end of the scenario the engines are parked and
        # URND requests go unacknowledged.
        await self._prove_edn_sibling_hold("CHK-EDN-HOLD")
        # URND keeps being acknowledged here, which is the window a held word
        # would have to reappear in.
        await ClockCycles(cocotb.top.clk_i, _EDN_DISCARD_WATCH_CYCLES)
        self._edn_log_stop = True
        await ack_log
        self._check_edn_discard("CHK-EDN-DISCARD")

        self.hmac = SepHmac(self)
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
        # as "!= C", not "== 0": the OpenTitan AES DATA_OUT description says
        # "Upon reset, these registers are cleared with pseudo-random data"
        # (vendor/lowRISC/opentitan/upstream/hw/ip/aes/data/aes.hjson), so an
        # AES-domain reset replaces the ciphertext with PRNG data rather than a
        # clean 0. The SEP overlay register doc lists DATA_OUT reset 0x0; "!= C"
        # holds under either reading. DATA_OUT is fully inside the AES gated
        # reset (gated_rst_ni.aes, hw/sys/sep/rtl/sep_crypto.sv), so there is no
        # out-of-domain ciphertext leak. (The 4-word
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
        # Host reads go out with the reset request, so the isolate has accepted
        # traffic to drain. A read issued once the isolate request is up is then
        # timed on the bus against the reset edge.
        rec = await self._drain_with_arrival(
            name="HMAC",
            addr=HMAC_DIGEST_0,
            start_reset=lambda: self._request_reset_direct(ENG_HMAC.rst_bit),
            req=cocotb.top.hmac_host_isolate_req_probe_o,
            host=cocotb.top.hmac_host_isolated_probe_o,
            km=cocotb.top.hmac_km_isolated_probe_o,
            rst=cocotb.top.hmac_gated_rst_n_probe_o,
            n_drain=_DRAIN_READS,
        )
        edge = rec["reset"]
        assert edge["host"] == 1 and edge["km"] == 1, (
            "HMAC reset asserted before its AXI-Lite paths isolated: "
            f"host_hmac={edge['host']} km_hmac={edge['km']}"
        )
        self.logger.info(
            "CHK-DRAIN-ORDER PASS: HMAC reset asserted at %.2f ns only after the "
            "host and Key Manager paths both reported isolated (sampled in the "
            "same cycle as the observed assert edge)",
            edge["t"],
        )

        drain_results = []
        for event in rec["drain"]:
            await with_timeout(event.wait(), 10_000, "ns")
            drain_results.append((id(event), worst_resp(getattr(event.data, "resp", None))))
        drain_codes = [code for _event_id, code in drain_results]
        host_outstanding_codes = [
            code for event_id, code in drain_results if event_id in rec["outstanding"]
        ]
        assert all(code in (RESP_OKAY, RESP_SLVERR) for code in drain_codes), (
            f"in-flight HMAC host reads returned unexpected responses {drain_codes}"
        )
        assert rec["outstanding"], (
            f"0 of the {len(rec['drain'])} HMAC drain reads were unretired when the "
            "isolate request arrived, so this leg grades no traffic that the "
            "isolate had to drain"
        )
        assert RESP_OKAY in host_outstanding_codes, (
            "no HMAC host read that was outstanding when the isolate request "
            f"arrived drained with OKAY; outstanding responses were {host_outstanding_codes}"
        )
        self.logger.info(
            "CHK-HOST-DRAIN PASS: %d of %d HMAC host reads were unretired when the "
            "isolate request arrived and all resolved %s (no hang, no DECERR); at "
            "least one drained OKAY",
            len(rec["outstanding"]),
            len(rec["drain"]),
            host_outstanding_codes,
        )

        self._check_arrival_in_window(rec, name="HMAC", chk="CHK-DRAIN-ARRIVAL")
        await with_timeout(rec["arrival"].wait(), 10_000, "ns")
        arrival_code = worst_resp(getattr(rec["arrival"].data, "resp", None))
        assert arrival_code in (RESP_OKAY, RESP_SLVERR), (
            f"read arriving during the isolate drain returned resp={arrival_code}, "
            "expected OKAY (drained) or SLVERR (terminated), never DECERR or a hang"
        )
        hs = rec["hs"]
        self.logger.info(
            "CHK-DRAIN-ARRIVAL PASS: arrival AR accepted on s_axi at %.2f ns "
            "(req=%d host_iso=%d km_iso=%d gated=%d), %.2f ns before the gated "
            "reset asserted at %.2f ns; resolved resp=%d, no hang",
            hs["t"],
            hs["req"],
            hs["host"],
            hs["km"],
            hs["rst"],
            edge["t"] - hs["t"],
            edge["t"],
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
        await self._drain_kmac()
        kmac_status = await self.kmac.read_status()
        assert kmac_status & KMAC_STATUS_RDL_MASK == KMAC_STATUS_RDL_RESET, (
            f"KMAC STATUS not restored to register-map reset 0x{KMAC_STATUS_RDL_RESET:08x} "
            f"under mask 0x{KMAC_STATUS_RDL_MASK:08x} after its own SW_RESET_N pulse: "
            f"0x{kmac_status:08x}"
        )
        assert kmac_status & KMAC_STATUS_IDLE_MASK == 0, (
            f"KMAC STATUS not idle after its own SW_RESET_N pulse: 0x{kmac_status:08x} "
            f"has bits 0x{kmac_status & KMAC_STATUS_IDLE_MASK:08x} set under mask "
            f"0x{KMAC_STATUS_IDLE_MASK:08x} (sha3_absorb/sha3_squeeze/fifo_depth/"
            "fifo_full/reserved)"
        )
        kmac_after = await self.kmac.read_digest()
        # STATE is a window, not a PeakRDL CSR, so it has no REG_DEFAULT, and no
        # spec states its value after reset. The expected share0^share1 == 0 is
        # RTL-derived: the KMAC domain reset leaves it 0 (unlike AES DATA_OUT,
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
            "CHK-KMAC-SELF PASS: KMAC STATUS=0x%08x: register-map reset 0x%08x under "
            "mask 0x%08x, idle 0 under mask 0x%08x; STATE cleared to 0 "
            "(held[0]=0x%08x); HMAC DIGEST intact",
            kmac_status,
            KMAC_STATUS_RDL_RESET,
            KMAC_STATUS_RDL_MASK,
            KMAC_STATUS_IDLE_MASK,
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
            f"0x{SW_RESET_N_DEFAULT:08x} (bit0 held, otbn/aes/hmac/kmac/trng/abr released)"
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
        await self._wait_gated_rst(SW_RESET_N_BIT["trng"], 0, "CHK-TRNG-NEIGHBORS reset")
        await ClockCycles(cocotb.top.clk_i, 40)
        # Witness the request inside the parked window. Without this the leg is
        # two non-events: park() only proves its CSR write returned OKAY, and the
        # "accelerator domains released" half is read back BEFORE the park --
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
            | (1 << SW_RESET_N_BIT["abr"])
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
        assert self.rd_known(cocotb.top.trng_gated_rst_n_probe_o) == 0, (
            "TRNG gated reset released before the neighbour results were read, so "
            "they were not sampled inside the reset"
        )
        await trng_rst.release("trng")
        self.logger.info(
            "CHK-TRNG-NEIGHBORS PASS: idle HMAC DIGEST and AES DATA_OUT survived "
            "the shared entropy-complex reset, with SW_RESET_N=0x%08x inside the "
            "window confirming the TRNG domain held and all five accelerator "
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
        # Host reads go out with the reset request, so the full-AXI isolate has
        # accepted traffic to drain. ABR's host path is the only full-AXI host
        # isolate in the design; the other accelerator paths are AXI-Lite.
        rec = await self._drain_with_arrival(
            name="ABR",
            addr=MLKEM_STATUS,
            start_reset=lambda: self._request_reset_direct(RST_ABR),
            req=cocotb.top.abr_host_isolate_req_probe_o,
            host=cocotb.top.abr_host_isolated_probe_o,
            km=cocotb.top.abr_km_isolated_probe_o,
            rst=cocotb.top.abr_gated_rst_n_probe_o,
            n_drain=_DRAIN_READS,
        )
        edge = rec["reset"]
        assert edge["host"] == 1 and edge["km"] == 1, (
            "ABR reset asserted before its AXI paths isolated: "
            f"host_abr={edge['host']} km_abr={edge['km']}"
        )
        self.logger.info(
            "CHK-ABR-DRAIN-ORDER PASS: ABR reset asserted at %.2f ns only after the "
            "full-AXI host path and the shared Key Manager path both reported "
            "isolated (sampled in the same cycle as the observed assert edge)",
            edge["t"],
        )

        abr_results = []
        for event in rec["drain"]:
            await with_timeout(event.wait(), 10_000, "ns")
            abr_results.append((id(event), worst_resp(getattr(event.data, "resp", None))))
        abr_codes = [code for _event_id, code in abr_results]
        abr_outstanding_codes = [
            code for event_id, code in abr_results if event_id in rec["outstanding"]
        ]
        assert all(code in (RESP_OKAY, RESP_SLVERR) for code in abr_codes), (
            f"in-flight ABR host reads returned unexpected responses {abr_codes}"
        )
        assert rec["outstanding"], (
            f"0 of the {len(rec['drain'])} ABR drain reads were unretired when the "
            "isolate request arrived, so this leg grades no traffic that the "
            "isolate had to drain"
        )
        assert RESP_OKAY in abr_outstanding_codes, (
            "no ABR host read that was outstanding when the isolate request "
            f"arrived drained with OKAY; outstanding responses were {abr_outstanding_codes}"
        )
        self.logger.info(
            "CHK-ABR-HOST-DRAIN PASS: %d of %d ABR host reads were unretired when "
            "the isolate request arrived and all resolved %s (no hang, no DECERR); "
            "at least one drained OKAY",
            len(rec["outstanding"]),
            len(rec["drain"]),
            abr_outstanding_codes,
        )

        self._check_arrival_in_window(rec, name="ABR", chk="CHK-ABR-DRAIN-ARRIVAL")
        await with_timeout(rec["arrival"].wait(), 10_000, "ns")
        abr_arrival_code = worst_resp(getattr(rec["arrival"].data, "resp", None))
        assert abr_arrival_code in (RESP_OKAY, RESP_SLVERR), (
            "an ABR host read accepted INSIDE the drain window returned "
            f"{abr_arrival_code}; it may drain or terminate, but it may not hang or "
            "DECERR"
        )
        hs = rec["hs"]
        self.logger.info(
            "CHK-ABR-DRAIN-ARRIVAL PASS: arrival AR accepted on s_axi at %.2f ns "
            "(req=%d host_iso=%d km_iso=%d gated=%d), %.2f ns before the gated "
            "reset asserted at %.2f ns; resolved resp=%d, no hang",
            hs["t"],
            hs["req"],
            hs["host"],
            hs["km"],
            hs["rst"],
            edge["t"] - hs["t"],
            edge["t"],
            abr_arrival_code,
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
