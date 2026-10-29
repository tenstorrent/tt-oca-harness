# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A crypto engine's SW reset returns its control registers to reset and leaves a sibling's result intact.

no_cpu host-AXI test that proves the SEP per-IP SW_RESET_N domains are isolated
while a neighbour engine holds a live, golden-checked crypto result in its
datapath output registers: pulsing one engine's reset returns that engine's
graded control and status registers (AES CTRL_SHADOWED, KMAC STATUS, OTBN
LOAD_CHECKSUM) to their reset values, logs its own result registers, and leaves
the sibling's held crypto result bit-exact intact. This is the
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
  * CHK-SELF-RESET  the first AES CTRL_SHADOWED read after the AES pulse
                    returns every field to its register-map reset; the read
                    before the pulse shows the programmed value, which differs
                    from that reset (proves the pulse landed in that engine's
                    domain). DATA_OUT after the pulse is logged only.
  * CHK-NEIGHBOR-SURVIVES  the sibling's held crypto result is bit-exact intact.
  * CHK-REVERSE     roles swapped (AES-victim then HMAC-victim): AES DATA_OUT
                    survives the HMAC pulse. HMAC DIGEST has no stated reset
                    value, so its value after the pulse is logged only.
  * CHK-KMAC-SELF / CHK-KMAC-NEIGHBOR / CHK-OTBN  KMAC SHA3-256 STATE and
                    OTBN DMEM hold across a neighbour pulse. KMAC's own pulse returns STATUS to its
                    register-map reset on the fields with a stated reset
                    (sha3_idle, fifo_empty, the two alert bits); STATUS before
                    the pulse differs from that reset. sha3_absorb,
                    sha3_squeeze, fifo_depth and fifo_full have no stated
                    reset value and are logged only. KMAC STATE after its own
                    pulse has no stated value and is logged only. OTBN
                    LOAD_CHECKSUM (rst_ni CSR) clears from the held mark to
                    its register-map reset. DMEM is the cross-domain
                    leak check (a neighbour must not wipe it). OTBN's own reset runs
                    a secure wipe, so DMEM retention across that pulse is not
                    claimed. KM (bit 0) stays held at the reset default and is
                    not claimed.
  * CHK-ISOLATE-*   while HMAC's SW_RESET_N is held, the same DIGEST_0 address
                    that just returned OKAY + the golden digest returns SLVERR
                    on read with the isolated read data 0x1501A7ED; a write to
                    HMAC CFG also SLVERR; AES DATA_OUT_0
                    on the sibling port stays OKAY; SW_RESET_N readback shows
                    the HMAC bit low; after release DIGEST_0 is OKAY (its
                    data is logged: DIGEST has no stated reset value).
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
                    verdict. A read accepted on s_axi with the isolate
                    request up completes SLVERR with 0x1501A7ED, every SLVERR
                    carries 0x1501A7ED, and no OKAY follows a SLVERR of the
                    same ID. The AR handshake of each read on the slave port
                    of the HMAC host isolate stage, and the isolate request at
                    it, are logged only (OBS-HOST-DRAIN-STAGE): no spec states
                    where the isolate stage accepts a read.
  * CHK-DRAIN-ARRIVAL  a further read is issued on the first cycle the isolate
                    request is seen, with an empty AR queue and its own AXI ID.
                    Its AR handshake on s_axi must fall while the request is up
                    and the gated reset is still released. It is a new
                    transaction on an isolated path, so it completes SLVERR
                    with read data 0x1501A7ED.
                    CHK-ISOLATE-REOPEN, after release, shows that the path is
                    not wedged.
  * CHK-KMAC-DRAIN-ORDER / CHK-KMAC-DRAIN-ARRIVAL  the same two contracts on the
                    KMAC reset: it asserts only after the host and Key Manager
                    paths both report isolated, and a read accepted in the
                    drain window completes SLVERR with read data 0x1501A7ED.
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
                    events must drain OKAY. The CHK-HOST-DRAIN s_axi timing
                    and SLVERR data terms apply. The AR handshake of each read
                    at the ABR host isolate stage is logged only
                    (OBS-ABR-HOST-DRAIN-STAGE).
  * CHK-ABR-DRAIN-ARRIVAL  the CHK-DRAIN-ARRIVAL contract on the ABR full-AXI
                    isolate: the arrival AR is accepted on s_axi while the
                    request is up and the gated reset is released, and it
                    completes SLVERR with read data 0x1501A7ED.
  * CHK-ABR-JTAG-OVERRIDE  the JTAG IC_RESET override holds the Adams Bridge
                    domain in reset while SW_RESET_N still reports it released,
                    and releasing the override lets the domain come back. The
                    override is sampled against the gated reset, so a mux that
                    ignored the override select fails here.
  * CHK-TRNG-FIPS-LOCK-RESET  ``ENTROPY_SOURCE.FIPS_LOCK`` set to 1 before the
                    TRNG-only reset reads its RDL reset value after the
                    release: the TRNG reset is a full-IP reset in which "all
                    entropy-source CSRs and FIPS_LOCK return to reset values"
                    (``hw/ip/entropy_source/doc/architecture.adoc:224-227``).
                    Control: FIPS_LOCK reads 1 after the set, before the reset.
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
                    across one measured acknowledge period. URND may
                    complete its own beat and is not disturbed (a URND
                    word that reads 0 on an edge with ``edn_ack`` low is
                    the last word acknowledged to URND before the edge, the
                    pop of a delivered word, and URND is acknowledged again
                    within a bound), and the KMAC endpoint's
                    ``edn_ack`` is 0 on every gated-reset edge. An edge
                    with no KMAC ``edn_req`` outstanding is logged as
                    INFO-EDN-EDGE-KMAC-IDLE; CHK-EDN-LEAD grades the KMAC
                    cancel on a live request.
  * CHK-EDN-LEAD  a software reset of KMAC, AES or OTBN cancels that
                    engine's EDN endpoints from the first cycle its paths
                    all report isolated until its reset releases. The
                    KMAC, AES, OTBN URND and OTBN RND trials each need
                    resets whose cancel finds the endpoint's edn_req high
                    and not just acknowledged, so an acknowledge EDN would
                    otherwise give lands in the window. The KMAC trials also grade
                    CHK-KMAC-DRAIN-ORDER on their reset edge. No endpoint
                    of the engine is acknowledged on any cycle of the cancel
                    window. The bus of a cancelled endpoint has no stated
                    value and is logged (OBS-EDN-CANCEL-BUS).
  * CHK-EDN-DISCARD  a word committed to an endpoint and not yet
                    acknowledged on the cycle before its cancel started is
                    never acknowledged to any client afterwards. At least
                    one such word is required. OTBN trials walk the cancel
                    start over every phase of one URND acknowledge period
                    from a fresh URND burst. A word an endpoint held at the
                    reset request is logged only (OBS-EDN-HELD-AT-REQUEST).
  * CHK-EDN-HOLD / CHK-EDN-HOLD-KEEP  a KMAC software reset must leave a URND
                    word unchanged when the previous cycle had not already
                    acknowledged it, and that word is the one URND is
                    acknowledged with. A word equal to the last URND
                    acknowledge is a delivered word that EDN holds on the
                    bus until the next request pops it, so it is not the
                    arm. An edge that zeroes a staged word is not the arm
                    either: that word must be the last word acknowledged to
                    URND before the edge, and URND must be acknowledged
                    again within a bound.

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

import contextlib
import hashlib

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, NextTimeStep, ReadOnly, RisingEdge, with_timeout
from cocotb.utils import get_sim_time
from env.sep_aes_golden import aes256_ecb_encrypt_words
from env.sep_axi_agent import SepAxiOp
from env.sep_fcov_gate import close_graded_window, open_graded_window, set_iprst_edn_pass
from env.sep_kmac_golden import kmac_family_words
from env.sep_reset_taps import ISO_BENCH
from ocah_axi_vip import worst_resp
from sep_base_test import sep_base_test
from sep_reg_meta import ENTROPY_SOURCE, register_fields, sym, word_reset
from seq_lib.sep_abr_mlkem_seq import MLKEM_STATUS
from seq_lib.sep_aes_seq import (
    AES_CTRL_SHADOWED,
    AES_DATA_OUT_0,
    AES_OP_ENC,
    AES_TRIGGER,
    AES_TRIGGER_PRNG_RESEED,
    SepAes,
    build_aes_ctrl,
)
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_crypto_reset_iso_seq import (
    ENG_AES,
    ENG_HMAC,
    ENG_KMAC,
    ENG_OTBN,
    RESP_OKAY,
    RESP_SLVERR,
    RST_ABR,
    RST_HMAC,
    SW_RESET_N,
    SW_RESET_N_DEFAULT,
    SepCryptoResetIso,
)
from seq_lib.sep_esrc_fips_lock_seq import LOCK_BIT, SepEsrcFipsLock
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
from seq_lib.sep_otbn_seq import (
    OTBN_DMEM_RESULT_LO,
    OTBN_LOAD_CHECKSUM_RESET,
    OTBN_RND_PROG,
    SepOtbn,
)
from seq_lib.sep_sw_reset_seq import SW_RESET_N_BIT, SepSwReset

TEST = "sep_crypto_per_ip_reset_isolation_test"

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
# First CSR word of each entropy-complex IP, read inside the TRNG reset.
TRNG_ISO_CSR = (
    ("esrc", sym("ENTROPY_SOURCE_REG_MAP_BASE_ADDR")),
    ("csrng", sym("CSRNG_REG_MAP_BASE_ADDR")),
    ("edn", sym("EDN_REG_MAP_BASE_ADDR")),
)
_RESP_DECERR = 3
FIPS_LOCK_RESET = ENTROPY_SOURCE.reset("FIPS_LOCK") & LOCK_BIT
# KMAC STATUS after its own SW_RESET_N pulse, read off the IP-XACT. The spec
# gives sha3_idle (1), fifo_empty (1) and the two alert bits (0) a reset value
# (vendor/lowRISC/opentitan/upstream/hw/ip/kmac/data/kmac.hjson:707, :737, :745,
# :759); that part is graded. sha3_absorb, sha3_squeeze, fifo_depth and fifo_full
# have no stated reset value, and bits outside every field are reserved with no
# stated value; both are logged, not graded. Before the pulse STATUS shows the
# squeeze state (sha3_idle 0), so the graded part differs from its reset and the
# leg discriminates.
_KMAC_STATUS_FIELDS = register_fields(KMAC_STATUS)[1]
KMAC_STATUS_FIELD_MASK = sum(f.mask for f in _KMAC_STATUS_FIELDS)
KMAC_STATUS_RDL_MASK = sum(f.mask for f in _KMAC_STATUS_FIELDS if f.reset is not None)
KMAC_STATUS_RDL_RESET = sum(f.reset << f.lsb for f in _KMAC_STATUS_FIELDS if f.reset is not None)
KMAC_STATUS_UNSTATED_MASK = KMAC_STATUS_FIELD_MASK & ~KMAC_STATUS_RDL_MASK
# Read data of a new transaction on an isolated path: SLVERR with 0x1501A7ED in
# each 32-bit word (hw/sys/sep/doc/reset_controller.adoc:127-129). No generated
# constant holds it.
ISO_DATA = 0x1501_A7ED
KMAC_STATUS_RESERVED_MASK = ~KMAC_STATUS_FIELD_MASK & 0xFFFF_FFFF
# AES CTRL_SHADOWED after its own SW_RESET_N pulse. Every field has a reset
# value (vendor/lowRISC/opentitan/upstream/hw/ip/aes/data/aes.hjson:650
# OPERATION 0x1, :675 MODE 0x3f, :730 KEY_LEN 1, :762 SIDELOAD 0, :770
# PRNG_RESEED_RATE 1, :804 MANUAL_OPERATION 0), read here from the generated
# register map. Bits outside the fields are reserved with no stated value; they
# are logged, not graded.
AES_CTRL_FIELD_MASK = sum(f.mask for f in register_fields(AES_CTRL_SHADOWED)[1])
AES_CTRL_RESET = word_reset(AES_CTRL_SHADOWED) & AES_CTRL_FIELD_MASK
# The value SepAes.configure_ecb_enc_256(sideload=False) programs.
AES_CTRL_ECB256_ENC = build_aes_ctrl(sideload=False, operation=AES_OP_ENC) & AES_CTRL_FIELD_MASK

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
# CHK-EDN-HOLD arming. Each attempt starts a fresh URND request burst and
# writes the KMAC reset on the AXI master itself a different number of cycles
# after the first URND acknowledge of that burst, so the edge walks the phase
# at which URND holds a staged word. _EDN_HOLD_STEP is above the steady URND
# acknowledge period, so each pass of the step walks every phase. The check
# fails if none of the attempts arm.
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
# show the quiet cycle.
#
# The "kmac", "aes", "otbn_urnd" and "otbn_rnd" counts are resets whose cancel
# finds the endpoint's edn_req live: high on the last released cycle before the gated
# reset falls, with no edn_ack on that cycle or the one before. With a live
# request and EDN granting, the adapter would acknowledge the engine inside the
# window if the cancel did not hold it off, so the CHK-EDN-LEAD compare can
# fail. KMAC is armed by a CFG commit with EDN entropy, AES by a PRNG reseed,
# OTBN RND by the RND program. Each of these reseeds spans several EDN words.
# OTBN URND is armed by an OTBN reset pulse: a cold OTBN raises URND edn_req
# and holds it until an acknowledge.
_EDN_LEAD_TRIALS = {"kmac": 2, "aes": 2, "otbn": 6, "otbn_urnd": 2, "otbn_rnd": 2}
# Live-request trials: each one arms a fresh request and writes the reset on
# the AXI master itself a walking 0 to _EDN_HOLD_STEP - 1 cycles after the
# request is seen, so the cancel start steps over every phase of one EDN word.
# The bound is _EDN_LIVE_PASSES passes of that walk per engine; CHK-EDN-LEAD
# fails if fewer resets than the count above find a live request.
_EDN_LIVE_PASSES = 2
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
# Isolate-complete bits (``crypto_isolated_probe_o``, bench stage order) of the
# host and Key Manager paths of each engine whose EDN endpoints a software
# reset cancels. The cancel runs from the cycle all of them read 1 until the
# reset releases (hw/sys/sep/doc/reset_controller.adoc:149-151).
_CANCEL_ISO_MASK = {
    ENG_AES.rst_bit: (1 << ISO_BENCH.index("host_aes")) | (1 << ISO_BENCH.index("km_aes")),
    ENG_KMAC.rst_bit: (1 << ISO_BENCH.index("host_kmac")) | (1 << ISO_BENCH.index("km_kmac")),
    ENG_OTBN.rst_bit: (1 << ISO_BENCH.index("host_otbn")) | (1 << ISO_BENCH.index("km_otbn")),
}
# CHK-EDN-DISCARD needs a word committed to an endpoint and not yet
# acknowledged on the cycle before the cancel starts. URND shows such a word
# with edn_ack low on one cycle of each acknowledge period. Each walk trial
# starts a fresh URND burst, waits for its first acknowledge, waits
# ``walk`` cycles and writes the OTBN reset on the AXI master itself, so the
# cancel start of a trial is a fixed cycle of the burst. ``walk`` steps from
# 0 to _EDN_HOLD_STEP - 1, which is above the measured acknowledge period, so
# one pass puts a cancel start on every phase of the period. CHK-EDN-DISCARD
# fails if no trial finds such a word.
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

    def _grade(self, ok: bool, chk: str, fail: str, passed: str) -> None:
        """Log ``<chk> PASS``, or close the graded window and raise ``<chk> FAIL``."""
        if not ok:
            close_graded_window(self.logger)
            raise AssertionError(f"{chk} FAIL: {fail}")
        self.logger.info("%s PASS: %s", chk, passed)

    @contextlib.asynccontextmanager
    async def _graded_window(self):
        """Open the graded window around one graded DUT step.

        The caller opens it at least one clock before the reset request it
        grades. Any failure inside closes it before the error propagates. On
        success it stays open two more clocks, so the sampler sees the last
        graded event before the close.
        """
        open_graded_window(TEST, self.logger)
        try:
            yield
        except BaseException:
            # A failure raised in a ReadOnly phase cannot write the gate there.
            await NextTimeStep()
            close_graded_window(self.logger)
            raise
        await ClockCycles(cocotb.top.clk_i, 2)
        close_graded_window(self.logger)

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

    async def _obs_trng_iso_resp(self) -> None:
        """OBS-TRNG-ISO-RESP: one CSR read of each entropy-complex IP inside its reset.

        No line states the response of a host access to the entropy complex
        while its reset is held. The line logs it and grades nothing.
        """
        mon = self.env.axi_monitor
        for ip, addr in TRNG_ISO_CSR:
            mon.arm_expected_decerr(1)
            seq = SepAxiAccessSeq(
                f"trng_iso_{ip}",
                op=SepAxiOp.READ,
                addr=addr,
                length=4,
                size=2,
                allow_ungraded_read_resp=True,
                allow_timeout=True,
            )
            await self.start_seq(seq)
            if seq.timed_out or seq.resp_code != _RESP_DECERR:
                mon.release_expected_decerr(1)
            self.logger.info(
                "OBS-TRNG-ISO-RESP ip=%s addr=0x%08x resp=%s rdata=0x%08x timed_out=%d",
                ip,
                addr,
                "none" if seq.timed_out else seq.resp_code,
                seq.rdata & 0xFFFF_FFFF,
                int(seq.timed_out),
            )

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

        LOAD_CHECKSUM is a CRC of the data written to memory
        (``vendor/lowRISC/opentitan/upstream/hw/ip/otbn/data/otbn.hjson:763``).
        Stage DMEM first, then write the mark last, so the DMEM store cannot
        mix the held checksum.
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
            f"CHK-{name}-DRAIN-OPEN FAIL: {name} gated reset was already asserted "
            "before the reset request "
            "was issued, so this domain asserted reset with no drain window"
        )
        assert host_iso == 0, (
            f"CHK-{name}-DRAIN-OPEN FAIL: {name} host isolate was already 1 before "
            "the reset request, so "
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
        self,
        *,
        name: str,
        addr: int,
        start_reset,
        req,
        host,
        km,
        rst,
        n_drain: int,
        stage: str | None = None,
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
        completion bits and the gated reset. The drain reads share ARID
        ``_DRAIN_ARID`` and go out in issue order, so the n-th ARID handshake on
        ``s_axi`` is the n-th drain read; its time and the isolate request at it
        are recorded. With ``stage`` (an ``ISO_BENCH`` path name) the loop also
        samples the AR handshake on the slave port of that isolate stage
        (``iso_slv_ar_hs_probe_o``) for the log. No other traffic targets the
        stage in this window, and the arrival AR queues behind the drain ARs on
        the one ``s_axi`` AR channel and the in-order path to the stage, so the
        n-th stage AR handshake is the n-th drain read. A drain AR not yet accepted at the
        reset edge is watched for up to 2000 more clocks.
        """
        axi = self.env.axi_agent.driver.axi
        top = cocotb.top

        def ar_ids_this_edge() -> list[int]:
            v, r = top.s_axi_arvalid.value, top.s_axi_arready.value
            if not (v.is_resolvable and r.is_resolvable) or not (int(v) and int(r)):
                return []
            return [int(top.s_axi_arid.value)]

        stage_bit = None if stage is None else ISO_BENCH.index(stage)

        def stage_ar_this_edge() -> bool:
            if stage_bit is None:
                return False
            return bool(self.rd_known(top.iso_slv_ar_hs_probe_o, mask=1 << stage_bit))

        self._require_open_isolate_terms(host=host, km=km, rst=rst, name=name)
        reset_task = cocotb.start_soon(start_reset())
        drain = [
            axi.init_read(address=addr, length=4, size=2, arid=_DRAIN_ARID) for _ in range(n_drain)
        ]

        arrival = None
        arrival_hs = None
        drain_hs: list[dict] = []
        stage_hs: list[dict] = []
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
            ids = ar_ids_this_edge()
            if _DRAIN_ARID in ids and len(drain_hs) < n_drain:
                drain_hs.append(dict(sample, t=now))
            if stage_ar_this_edge() and len(stage_hs) < n_drain:
                stage_hs.append(dict(sample, t=now))
            if arrival is not None and arrival_hs is None:
                if _ARRIVAL_ARID in ids:
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
        stage_need = 0 if stage_bit is None else n_drain
        for _ in range(2_000):
            if len(drain_hs) >= n_drain and len(stage_hs) >= stage_need:
                break
            await RisingEdge(top.clk_i)
            sample = {
                "req": self.rd_known(req),
                "host": self.rd_known(host),
                "km": self.rd_known(km),
                "rst": self.rd_known(rst),
                "t": get_sim_time("ns"),
            }
            if _DRAIN_ARID in ar_ids_this_edge() and len(drain_hs) < n_drain:
                drain_hs.append(sample)
            if stage_ar_this_edge() and len(stage_hs) < stage_need:
                stage_hs.append(sample)
        await reset_task
        return {
            "drain": drain,
            "drain_hs": drain_hs,
            "stage": stage,
            "stage_hs": stage_hs,
            "outstanding": outstanding,
            "arrival": arrival,
            "hs": arrival_hs,
            "reset": reset_edge,
        }

    def _check_arrival_in_window(self, rec: dict, *, name: str, chk: str) -> None:
        """The arrival AR was accepted while the isolate was up and reset released."""
        hs, edge = rec["hs"], rec["reset"]
        assert rec["arrival"] is not None, (
            f"{chk} FAIL: {name}: the isolate request was never seen with the gated reset "
            f"released, so {chk} has no beat to grade"
        )
        hs_at = "never seen" if hs is None else f"at {hs['t']:.2f} ns"
        assert hs is not None and hs["t"] < edge["t"], (
            f"{chk} FAIL: {name}: the arrival read's AR was not accepted on s_axi before the "
            f"gated reset asserted at {edge['t']:.2f} ns (handshake {hs_at}), so "
            f"{chk} would grade a read made during reset, not one made mid-drain"
        )
        assert hs["req"] == 1 and hs["rst"] == 1, (
            f"{chk} FAIL: {name}: at the arrival AR handshake ({hs['t']:.2f} ns) "
            f"req={hs['req']} "
            f"gated={hs['rst']}; the beat must enter while isolation is requested "
            "and the domain reset is still released"
        )

    async def _grade_host_drain(self, rec: dict, *, name: str, chk: str) -> None:
        """Grade the drain reads that went out with the reset request.

        Golden: ``hw/sys/sep/doc/reset_controller.adoc:127-130``. Once isolation
        is requested, new transactions complete with SLVERR and read data
        0x1501A7ED in each 32-bit word; the isolate unit drains the
        transactions it accepted before that. Each read is one aligned 32-bit
        word. Graded rules:

        * a read accepted on ``s_axi`` with the request up is a new
          transaction, so it completes SLVERR with 0x1501A7ED;
        * every SLVERR carries 0x1501A7ED (only a new transaction on an
          isolated path completes SLVERR here);
        * the reads share one ARID and complete in order, and a read that the
          isolate unit saw as new makes every later read new, so no OKAY may
          follow a SLVERR;
        * every response is OKAY or SLVERR (never DECERR, never a hang), and at
          least one read still unretired when the request rose drains OKAY.

        A read accepted on ``s_axi`` before the request passes ``u_axi_demux``
        and, on AXI-Lite paths, the bus conversion before the isolate stage
        (``reset_controller.adoc:109-112``). No spec states where the stage
        accepts a read, and an ARVALID already pending at the stage when the
        request rises cannot be withdrawn, so such a read may complete OKAY or
        SLVERR. Its stage AR handshake (``rec["stage_hs"]``) and the request at
        it are logged as ``OBS-HOST-DRAIN-STAGE`` (HMAC) or
        ``OBS-ABR-HOST-DRAIN-STAGE`` (ABR) and not graded.
        """
        rows = []
        for i, event in enumerate(rec["drain"]):
            await with_timeout(event.wait(), 10_000, "ns")
            data = event.data
            raw = bytes(getattr(data, "data", b""))
            hs = rec["drain_hs"][i] if i < len(rec["drain_hs"]) else None
            st_hs = rec["stage_hs"][i] if i < len(rec["stage_hs"]) else None
            rows.append(
                {
                    "i": i,
                    "code": worst_resp(getattr(data, "resp", None)),
                    "rdata": int.from_bytes(raw[:4], "little") if len(raw) >= 4 else None,
                    "hs": hs,
                    "after": hs is not None and hs["req"] == 1,
                    "st_hs": st_hs,
                    "out": id(event) in rec["outstanding"],
                }
            )

        def txt(row: dict) -> str:
            hs, st_hs = row["hs"], row["st_hs"]
            at = "AR not seen" if hs is None else f"AR at {hs['t']:.2f} ns req={hs['req']}"
            st = (
                "stage AR not seen"
                if st_hs is None
                else f"stage AR at {st_hs['t']:.2f} ns req={st_hs['req']}"
            )
            rd_txt = "none" if row["rdata"] is None else f"0x{row['rdata']:08x}"
            return f"read {row['i']}: {at}, {st} resp={row['code']} rdata={rd_txt}"

        detail = "; ".join(txt(row) for row in rows)
        codes = [row["code"] for row in rows]
        assert len(rec["drain_hs"]) == len(rows), (
            f"{chk} FAIL: {name}: {len(rec['drain_hs'])} of {len(rows)} drain AR handshakes "
            f"seen on s_axi, so a read cannot be placed before or after the isolate "
            f"request ({detail})"
        )
        self.logger.info(
            "%s: %s drain AR handshakes at the %s isolate stage, %d of %d seen (no spec "
            "states where the stage accepts a read; not graded): %s",
            chk.replace("CHK-", "OBS-").replace("-HOST-DRAIN", "-HOST-DRAIN-STAGE"),
            name,
            rec["stage"],
            len(rec["stage_hs"]),
            len(rows),
            detail,
        )
        assert all(code in (RESP_OKAY, RESP_SLVERR) for code in codes), (
            f"{chk} FAIL: in-flight {name} host reads returned unexpected responses "
            f"{codes} ({detail})"
        )
        for row in rows:
            if row["after"]:
                assert row["code"] == RESP_SLVERR and row["rdata"] == ISO_DATA, (
                    f"{chk} FAIL: {name} {txt(row)}: accepted on s_axi after the isolate "
                    f"request rose, expected SLVERR with the isolated read data "
                    f"0x{ISO_DATA:08x}"
                )
            if row["code"] == RESP_SLVERR:
                assert row["rdata"] == ISO_DATA, (
                    f"{chk} FAIL: {name} {txt(row)}: a SLVERR drain read must carry the "
                    f"isolated read data 0x{ISO_DATA:08x}"
                )
        for prev, row in zip(rows, rows[1:]):
            assert not (prev["code"] == RESP_SLVERR and row["code"] == RESP_OKAY), (
                f"{chk} FAIL: {name}: drain read {row['i']} completed OKAY after the "
                f"earlier same-ID read {prev['i']} completed SLVERR ({detail})"
            )
        assert rec["outstanding"], (
            f"{chk} FAIL: 0 of the {len(rows)} {name} drain reads were unretired when the "
            "isolate request arrived, so this leg grades no traffic that the isolate "
            "had to drain"
        )
        out_codes = [row["code"] for row in rows if row["out"]]
        assert RESP_OKAY in out_codes, (
            f"{chk} FAIL: no {name} host read that was outstanding when the isolate "
            f"request arrived drained with OKAY; outstanding responses were {out_codes} "
            f"({detail})"
        )
        self.logger.info(
            "%s PASS: %d of %d %s host reads were unretired when the isolate request "
            "arrived and resolved %s (no hang, no DECERR), at least one OKAY; %d accepted "
            "on s_axi after the request, each SLVERR with 0x%08x; every SLVERR carries "
            "0x%08x and no OKAY follows a SLVERR; %s",
            chk,
            len(rec["outstanding"]),
            len(rows),
            name,
            out_codes,
            sum(row["after"] for row in rows),
            ISO_DATA,
            ISO_DATA,
            detail,
        )

    async def _arrival_beat(self, rec: dict, *, name: str, chk: str) -> tuple[int, int]:
        """Wait for the arrival read and grade its beat as a new transaction.

        The arrival AR is accepted after the isolate request rose, so the
        isolate stage sees it as a new transaction on an isolated path: it
        completes with SLVERR and read data 0x1501A7ED in each 32-bit word
        (hw/sys/sep/doc/reset_controller.adoc:127-129). The read is one aligned
        32-bit word.
        """
        self._check_arrival_in_window(rec, name=name, chk=chk)
        await with_timeout(rec["arrival"].wait(), 10_000, "ns")
        data = rec["arrival"].data
        code = worst_resp(getattr(data, "resp", None))
        raw = bytes(getattr(data, "data", b""))
        rdata = int.from_bytes(raw[:4], "little") if len(raw) >= 4 else None
        rd_txt = "none" if rdata is None else f"0x{rdata:08x}"
        assert code == RESP_SLVERR and rdata == ISO_DATA, (
            f"{chk} FAIL: {name} read accepted after the isolate request rose returned "
            f"resp={code} rdata={rd_txt}, expected SLVERR with the isolated read data "
            f"0x{ISO_DATA:08x}"
        )
        return code, rdata

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
        self._grade(
            edge["host"] == 1 and edge["km"] == 1,
            "CHK-KMAC-DRAIN-ORDER",
            "KMAC reset asserted before its AXI-Lite paths isolated: "
            f"host_kmac={edge['host']} km_kmac={edge['km']}",
            f"KMAC reset asserted at {edge['t']:.2f} ns only after the host and Key "
            f"Manager paths both reported isolated (host_kmac={edge['host']} "
            f"km_kmac={edge['km']}, sampled in the same cycle as the observed assert edge)",
        )
        for event in rec["drain"]:
            await with_timeout(event.wait(), 10_000, "ns")

        arrival_code, arrival_rdata = await self._arrival_beat(
            rec, name="KMAC", chk="CHK-KMAC-DRAIN-ARRIVAL"
        )
        hs = rec["hs"]
        self.logger.info(
            "CHK-KMAC-DRAIN-ARRIVAL PASS: arrival AR accepted on s_axi at %.2f ns "
            "(req=%d host_iso=%d km_iso=%d gated=%d), %.2f ns before the gated "
            "reset asserted at %.2f ns; resp=%d (SLVERR) rdata=0x%08x == isolated "
            "read data",
            hs["t"],
            hs["req"],
            hs["host"],
            hs["km"],
            hs["rst"],
            edge["t"] - hs["t"],
            edge["t"],
            arrival_code,
            arrival_rdata,
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
        log_bus: bool = False,
    ) -> int:
        """Every cycle of the window: this client's ack stays low, and its req
        stays at the level the reset is required to leave. With ``log_bus``,
        returns the number of cycles on which this client's ``edn_bus`` word
        was non-zero (no spec states the bus of a cancelled endpoint, so the
        caller logs it and grades nothing on it)."""
        bus_live = 0
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
            if log_bus and self._edn_bus_word(bit):
                bus_live += 1
            await RisingEdge(cocotb.top.clk_i)
        return bus_live

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
        """The cancelled KMAC endpoint gives no acknowledge on its reset edge.

        The spec states the cancel, not the bus value of a cancelled endpoint
        (hw/sys/sep/doc/reset_controller.adoc:149-153), so ``edn_bus`` and
        ``edn_fips`` are logged as ``OBS-EDN-CANCEL-BUS`` and not graded.
        """
        if snap["ack"]:
            raise AssertionError(
                f"{tag} FAIL: KMAC endpoint acknowledged {where} "
                f"(ack={int(snap['ack'])} bus=0x{snap['bus']:08x})"
            )
        self.logger.info(
            "OBS-EDN-CANCEL-BUS: %s KMAC endpoint %s: edn_bus=0x%08x edn_fips=%d (no stated value)",
            tag,
            where,
            snap["bus"],
            int(snap["fips"]),
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
        # the handshake ending, not the KMAC reset cancelling it. A word that
        # reads 0 with ack low must be the last word acknowledged to URND (the
        # caller grades it). Replacing a requested word with a different
        # non-zero word fails here.
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

    def _last_urnd_ack(self, before: int) -> tuple[int, int] | None:
        """The last URND acknowledge of the recorder before cycle ``before``, as
        ``(cycle, word)``, or None when there is none."""
        for c, b, w in reversed(self._edn_acked):
            if b == _EDN_URND and c < before:
                return c, w
        return None

    async def _require_zeroed_word_acked(
        self, tag: str, where: str, edge: int, word: int
    ) -> tuple[int, int, int]:
        """A URND word that reads 0 on a KMAC reset edge with ``edn_ack`` low
        must be a word URND already received, and URND must keep being served.

        EDN acknowledges the word at the head of the endpoint FIFO and leaves
        it on ``edn_bus``; the next ``edn_req`` pops it ("the next request will
        change the prior data by popping the data FIFO",
        vendor/lowRISC/opentitan/upstream/hw/ip/edn/doc/theory_of_operation.md:152-160).
        A KMAC software reset leaves the other clients unaffected
        (hw/sys/sep/doc/reset_controller.adoc:149-153). So the last URND
        acknowledge before the edge must carry ``word``: a different word
        there means the edge cleared a word that URND never received. Then
        the next URND acknowledge after the edge must come within
        ``_EDN_KEEP_CYCLES`` cycles with a non-zero word. ``edge`` is the
        recorder cycle of the edge; the caller states whether the KMAC reset
        is still asserted during the wait. Returns ``(cycles from that last
        acknowledge to the edge, cycles from the edge to the next
        acknowledge, the next word)``.
        """
        clk = cocotb.top.clk_i
        last = self._last_urnd_ack(edge)
        if last is None:
            raise AssertionError(
                f"{tag} FAIL: URND word 0x{word:08x} read 0 with edn_ack low on the "
                f"KMAC reset edge {where}, and URND has no acknowledge before the "
                "edge. The KMAC reset cleared a word that URND never received"
            )
        at, last_word = last
        if last_word != word:
            raise AssertionError(
                f"{tag} FAIL: URND word 0x{word:08x} read 0 with edn_ack low on the "
                f"KMAC reset edge {where}, but the last URND acknowledge before the "
                f"edge ({edge - at} cycles before it) carried 0x{last_word:08x}. "
                "The KMAC reset cleared a word that URND never received"
            )
        while True:
            nxt = [(c, w) for c, b, w in self._edn_acked if b == _EDN_URND and c > edge]
            if nxt:
                c, w = nxt[0]
                if w == 0:
                    raise AssertionError(
                        f"{tag} FAIL: the first URND acknowledge after the KMAC reset "
                        f"edge {where} ({c - edge} cycles after it) carried a zero bus"
                    )
                return edge - at, c - edge, w
            if self._edn_cycle > edge + _EDN_KEEP_CYCLES:
                raise AssertionError(
                    f"{tag} FAIL: URND was not acknowledged within {_EDN_KEEP_CYCLES} "
                    f"cycles after the KMAC reset edge {where} that popped URND word "
                    f"0x{word:08x}. The KMAC reset stopped the service of a sibling"
                )
            await RisingEdge(clk)

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
        KMAC gated reset the KMAC endpoint gives no acknowledge, and URND may
        acknowledge its own word. The KMAC bus on the edge has no stated value
        and is logged as ``OBS-EDN-CANCEL-BUS``. A URND word that reads 0 on
        the edge with ``edn_ack`` low must be the last word acknowledged to
        URND before the edge (the pop of a delivered word), and URND must be
        acknowledged again within ``_EDN_KEEP_CYCLES`` while the KMAC reset is
        still asserted. The software-reset write is an AXI transaction and
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
        kmac_live = 0
        kmac_idle = 0
        zeroed = 0

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
                            "ack_cycle": self._edn_cycle,
                        }
                    )
                prev_ack = urnd["ack"]
                prev_rst = rst
                prev_urnd = urnd
                prev_kmac = kmac

        async def take_edge(where: str) -> dict:
            nonlocal kmac_live, kmac_idle, zeroed
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
            pre_k = snap["kmac_pre"]
            if pre_k and pre_k["req"] and not pre_k["ack"]:
                kmac_live += 1
            else:
                kmac_idle += 1
                self.logger.info(
                    "INFO-EDN-EDGE-KMAC-IDLE: %s no KMAC edn_req outstanding before the "
                    "reset edge %s, so this edge does not grade the KMAC cancel",
                    tag,
                    where,
                )
            self._require_kmac_suppressed(tag, where_txt, snap["kmac"])
            self._require_urnd_undisturbed(tag, where_txt, snap["urnd_pre"], snap["urnd"])
            pre_u = snap["urnd_pre"]
            cur_u = snap["urnd"]
            if (
                pre_u["req"]
                and not pre_u["ack"]
                and pre_u["bus"] != 0
                and cur_u["bus"] == 0
                and not cur_u["ack"]
            ):
                # The KMAC reset stays asserted during this wait.
                dist, lat, nxt = await self._require_zeroed_word_acked(
                    tag, where_txt, snap["ack_cycle"], pre_u["bus"]
                )
                zeroed += 1
                self.logger.info(
                    "%s %s: URND bus 0x%08x->0 with edn_ack low: the pop of the word "
                    "acknowledged to URND %d cycles before the edge; with the KMAC "
                    "reset asserted, the next URND acknowledge came %d cycles after "
                    "the edge with 0x%08x",
                    tag,
                    where,
                    pre_u["bus"],
                    dist,
                    lat,
                    nxt,
                )
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
            self._urnd_period = steady
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
                bus_live = await self._sample_edn(
                    _EDN_KMAC,
                    req_high=False,
                    cycles=_EDN_QUIET_CYCLES,
                    what=f"{tag} KMAC suppressed",
                    log_bus=True,
                )
                self.logger.info(
                    "OBS-EDN-CANCEL-BUS: %s KMAC edn_bus non-zero on %d of the %d "
                    "quiet-window cycles (no stated value)",
                    tag,
                    bus_live,
                    _EDN_QUIET_CYCLES,
                )
                self.logger.info(
                    "%s PASS: URND was not disturbed on any of the %d reset edges "
                    "and acknowledged its own beat on %d of them; %d URND words "
                    "that read 0 on an edge were each the last word acknowledged "
                    "to URND before it, and URND was acknowledged again after it; "
                    "KMAC edn_ack was "
                    "0 on every edge, %d of them with a KMAC edn_req outstanding; "
                    "the outstanding KMAC edn_req of the last edge (bus=0x%08x on "
                    "the cycle before it) was dropped on the edge, and KMAC edn_req "
                    "and edn_ack stayed 0 on every cycle of the %d-cycle quiet window",
                    tag,
                    steady + 1,
                    urnd_completions,
                    zeroed,
                    kmac_live,
                    pre_k["bus"],
                    _EDN_QUIET_CYCLES,
                )
            else:
                self.logger.info(
                    "%s PASS: URND was not disturbed on any of the %d reset edges "
                    "and acknowledged its own beat on %d of them; %d URND words "
                    "that read 0 on an edge were each the last word acknowledged "
                    "to URND before it, and URND was acknowledged again after it; "
                    "KMAC edn_ack was "
                    "0 on every edge. KMAC edn_req was outstanding on %d edges and "
                    "idle on %d (INFO-EDN-EDGE-KMAC-IDLE); CHK-EDN-LEAD grades the "
                    "KMAC cancel on a live request",
                    tag,
                    steady + 1,
                    urnd_completions,
                    zeroed,
                    kmac_live,
                    kmac_idle,
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

        A software reset cancels only that engine's endpoints, and other
        clients are unaffected (hw/sys/sep/doc/reset_controller.adoc:149-153),
        so a sibling word that changes on the KMAC reset edge breaks the
        contract.

        A word equal to the last URND acknowledge before the edge is a word
        URND already received: EDN leaves it on ``edn_bus`` until the next
        ``edn_req`` pops it
        (vendor/lowRISC/opentitan/upstream/hw/ip/edn/doc/theory_of_operation.md:152-160),
        so it is not pending and is not the arm. The arm is an edge that
        still presents a pending staged word. An edge that presents a
        different word fails on that attempt. An edge that zeroes a staged
        word with ``edn_ack`` low is not the arm: after the KMAC reset is
        released, that word must be the last word acknowledged to URND before
        the edge, and URND must be acknowledged again within
        ``_EDN_KEEP_CYCLES`` cycles, or the attempt fails. If no attempt arms,
        the check fails. The acknowledge of the armed word may be the
        reset-edge cycle itself.
        """
        clk = cocotb.top.clk_i
        armed: dict = {}
        delivered: list[tuple[int, int]] = []
        seen = False
        edge_pre: dict = {}
        gap_pre = None
        pops = 0
        stop = False

        async def watch() -> None:
            nonlocal seen, gap_pre
            prev = None
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
                    edge_pre.update(prev=prev, req=req, ack=ack, bus=bus, cycle=self._edn_cycle)
                    # A word equal to the last URND acknowledge is already
                    # delivered and waits for its pop: it is not pending.
                    last = self._last_urnd_ack(self._edn_cycle)
                    held = last is not None and last[1] == prev["bus"]
                    staged = prev["req"] and not prev["ack"] and prev["bus"] != 0
                    pending = staged and not held
                    cur = {"bus": bus, "fips": fips, "req": req, "ack": ack}
                    if pending and bus == prev["bus"] and fips == prev["fips"]:
                        armed.update(pre=prev, cur=cur)
                        want_ack = True
                        if ack:
                            delivered.append((bus, fips))
                            want_ack = False
                    elif staged and bus == 0 and not ack:
                        gap_pre = prev
                    elif pending:
                        armed.update(pre=prev, cur=cur)
                prev = {"req": req, "ack": ack, "bus": bus, "fips": fips, "rst": rst}

        period = getattr(self, "_urnd_period", None)
        if period is None or period >= _EDN_HOLD_STEP:
            msg = (
                f"{tag} SETUP FAILED (not a contract result): the measured URND "
                f"acknowledge period {period} is not below the {_EDN_HOLD_STEP}-cycle "
                "step, so the attempts cannot walk every phase"
            )
            self.logger.error(msg)
            raise AssertionError(msg)
        watch_task = cocotb.start_soon(watch())
        try:
            for attempt in range(_EDN_HOLD_ATTEMPTS):
                if armed:
                    break
                seen = False
                gap_pre = None
                edge_pre.clear()
                # A fresh burst every attempt: the edge is timed from the
                # first acknowledge of the burst, so each attempt starts from
                # the same URND state and only the step offset differs.
                await self._arm_urnd(tag)
                for _ in range(_EDN_ACK_CYCLES):
                    if self._edn_ack() & (1 << _EDN_URND):
                        break
                    await RisingEdge(clk)
                else:
                    msg = (
                        f"{tag} SETUP FAILED (not a contract result): URND "
                        f"stopped being acknowledged before attempt {attempt}"
                    )
                    self.logger.error(msg)
                    raise AssertionError(msg)
                await ClockCycles(clk, attempt % _EDN_HOLD_STEP)
                # A sequencer write waits behind the background entropy FIFO
                # drain read for an unknown number of cycles, which would
                # erase the step offset. The direct write does not queue
                # behind it.
                await self._request_reset_direct(ENG_KMAC.rst_bit)
                for _ in range(_EDN_DROP_CYCLES):
                    if seen:
                        break
                    await RisingEdge(clk)
                else:
                    msg = (
                        f"{tag} FAIL: KMAC gated reset did not fall within "
                        f"{_EDN_DROP_CYCLES} cycles of the reset request on "
                        f"attempt {attempt}"
                    )
                    self.logger.error(msg)
                    raise AssertionError(msg)
                await self.rst.release_resets()
                if gap_pre is not None and not armed:
                    pops += 1
                    # The KMAC reset is released before this wait.
                    dist, lat, nxt = await self._require_zeroed_word_acked(
                        tag, f"on attempt {attempt}", edge_pre["cycle"], gap_pre["bus"]
                    )
                    self.logger.info(
                        "%s attempt %d: URND bus 0x%08x->0 with edn_ack low: not the "
                        "arm; the pop of the word acknowledged to URND %d cycles before "
                        "the edge; after the KMAC reset release, the next URND "
                        "acknowledge came %d cycles after the edge with 0x%08x",
                        tag,
                        attempt,
                        gap_pre["bus"],
                        dist,
                        lat,
                        nxt,
                    )
                elif not armed:
                    ep = edge_pre["prev"]
                    self.logger.info(
                        "%s attempt %d (offset %d): not the arm; URND before the "
                        "KMAC reset edge req=%d ack=%d bus=0x%08x, on the edge "
                        "req=%d ack=%d bus=0x%08x",
                        tag,
                        attempt,
                        attempt % _EDN_HOLD_STEP,
                        int(ep["req"]),
                        int(ep["ack"]),
                        ep["bus"],
                        int(edge_pre["req"]),
                        int(edge_pre["ack"]),
                        edge_pre["bus"],
                    )
            if not armed:
                msg = (
                    f"{tag} FAIL: no KMAC reset edge landed while URND held a "
                    f"pending staged word ({_EDN_HOLD_ATTEMPTS} attempts; {pops} "
                    "edges popped a word URND had already received). The check "
                    "never armed, so it proves nothing."
                )
                self.logger.error(msg)
                raise AssertionError(msg)
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
                    "This breaks the contract that a software reset leaves "
                    "other EDN clients unaffected "
                    "(hw/sys/sep/doc/reset_controller.adoc:149-153)."
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
        self,
        tag: str,
        eng,
        bits: tuple[int, ...],
        rst_sig,
        *,
        delay: int,
        graded: bool = False,
        iso: tuple | None = None,
        after_ack: bool = False,
        live: bool = False,
    ) -> bool:
        """One software reset of ``eng``, graded for the cancel of its endpoints.

        By default the reset is requested on a cycle where ``bits[0]`` holds a
        word with ``edn_ack`` low, at least ``delay`` cycles after that
        endpoint's last acknowledge. With ``after_ack`` the request goes out
        exactly ``delay`` cycles after an acknowledge of ``bits[0]``. With
        ``live`` it goes out ``delay`` cycles after the first cycle ``bits[0]``
        shows ``edn_req`` high. In both of these the reset is written on the
        AXI master itself, so ``delay`` walks the phase of the cancel start.

        The cancel runs from the first cycle all of the engine's paths report
        isolated until its reset releases (hw/sys/sep/doc/reset_controller.adoc:149-151).
        No endpoint in ``bits`` may be acknowledged on any cycle of that window.
        A word an endpoint held with ``edn_ack`` low on the cycle before the
        cancel start, and that no client was acknowledged with before, is a
        word committed and not yet acknowledged; it joins the CHK-EDN-DISCARD
        set. The words the endpoints held at the request are logged as
        ``OBS-EDN-HELD-AT-REQUEST``. The bus of a cancelled endpoint has no
        stated value and is logged as ``OBS-EDN-CANCEL-BUS``.

        With ``graded`` the reset runs inside the graded window. With ``iso``
        (the host and Key Manager isolate-completion probes of the domain), the
        cycle the gated reset falls must show both at 1 (CHK-KMAC-DRAIN-ORDER).
        Returns True when the request of ``bits[0]`` was live at the cancel:
        ``edn_req`` high on the last released cycle before the gated reset
        falls, and no ``edn_ack`` on that cycle or the one before.
        """
        clk = cocotb.top.clk_i
        lead_bit = bits[0]
        if after_ack:
            for _ in range(_EDN_ACK_CYCLES):
                await RisingEdge(clk)
                await ReadOnly()
                if self._edn_ack() & (1 << lead_bit):
                    break
            else:
                raise AssertionError(
                    f"{tag} SETUP FAILED (not a contract result): {eng.name} endpoint "
                    f"{lead_bit} was never acknowledged"
                )
            for _ in range(delay):
                await RisingEdge(clk)
                await ReadOnly()
        elif live:
            for _ in range(_EDN_PEND_CYCLES):
                await RisingEdge(clk)
                await ReadOnly()
                if self._edn_req() & (1 << lead_bit):
                    break
            else:
                raise AssertionError(
                    f"{tag} SETUP FAILED (not a contract result): {eng.name} endpoint "
                    f"{lead_bit} never raised edn_req"
                )
            for _ in range(delay):
                await RisingEdge(clk)
                await ReadOnly()
        else:
            since_ack = 0
            for _ in range(_EDN_ACK_CYCLES):
                await RisingEdge(clk)
                await ReadOnly()
                if self._edn_ack() & (1 << lead_bit):
                    since_ack = 0
                    continue
                since_ack += 1
                if since_ack > delay and self._edn_bus_word(lead_bit):
                    break
            else:
                raise AssertionError(
                    f"{tag} SETUP FAILED (not a contract result): {eng.name} endpoint "
                    f"{lead_bit} never held a word with edn_ack low"
                )
        held = {b: self._edn_bus_word(b) for b in bits}
        issued_at = self._edn_cycle
        if self._edn_level(rst_sig) != 1:
            raise AssertionError(f"{tag} FAIL: {eng.name} gated reset already asserted")
        await RisingEdge(clk)
        if graded:
            open_graded_window(TEST, self.logger)
        try:
            res = await self._edn_lead_reset(
                tag, eng, bits, rst_sig, held, iso, direct=after_ack or live
            )
        except BaseException:
            if graded:
                # The failure can be raised in the ReadOnly phase of a sample,
                # where the gate cannot be written. The next time step is
                # before the next clk_i rising edge.
                await NextTimeStep()
                close_graded_window(self.logger)
            raise
        if graded:
            await ClockCycles(clk, 2)
            close_graded_window(self.logger)
        self.logger.info(
            "%s %s trial (delay %d): edn_ack 0 on %d released cycle(s) of the "
            "cancel window and on all %d asserted-reset cycles; request live at "
            "the cancel %s; committed and not yet acknowledged at the cancel "
            "start %s%s; graded window %s",
            tag,
            eng.name,
            delay,
            res["lead"],
            res["reset_cycles"],
            {b: int(v) for b, v in res["live"].items()},
            {b: f"0x{w:08x}" for b, (_c, w) in res["committed"].items()} or "none",
            ""
            if res["fall_iso"] is None
            else f"; CHK-KMAC-DRAIN-ORDER PASS: host_iso={res['fall_iso'][0]} "
            f"km_iso={res['fall_iso'][1]} on the cycle the gated reset fell",
            "open" if graded else "closed",
        )
        self.logger.info(
            "OBS-EDN-CANCEL-BUS: %s %s trial: edn_bus %s on the cancel start, "
            "non-zero on %d of %d cancel-window cycles (no stated value)",
            tag,
            eng.name,
            {b: f"0x{w:08x}" for b, w in res["start_bus"].items()},
            res["bus_live"],
            res["lead"] + res["reset_cycles"],
        )
        for b, w in held.items():
            if w:
                self._edn_held.append((issued_at, b, w))
        for b, (at, w) in res["committed"].items():
            self._edn_committed.append((at, b, w))
        return res["live"][lead_bit]

    async def _edn_lead_reset(
        self, tag: str, eng, bits: tuple[int, ...], rst_sig, held: dict, iso, *, direct: bool
    ) -> dict:
        """Request the reset of ``eng`` and grade the cancel window.

        With ``direct`` the reset is written on the AXI master itself, so the
        write does not wait behind the background entropy FIFO drain read.
        """
        clk = cocotb.top.clk_i
        if direct:
            reset_task = cocotb.start_soon(self._request_reset_direct(eng.rst_bit))
        else:
            reset_task = cocotb.start_soon(self.rst.assert_reset(eng.rst_bit))
        mask = _CANCEL_ISO_MASK[eng.rst_bit]

        def sample() -> dict:
            ack = self._edn_ack()
            req = self._edn_req()
            return {
                "cyc": self._edn_cycle,
                "req": {b: bool(req & (1 << b)) for b in bits},
                "rst": self._edn_level(rst_sig),
                "cx": (self._edn_level(cocotb.top.crypto_isolated_probe_o) & mask) == mask,
                "ack": {b: bool(ack & (1 << b)) for b in bits},
                "bus": {b: self._edn_bus_word(b) for b in bits},
                "iso": None if iso is None else tuple(self._edn_level(p) for p in iso),
            }

        def require_quiet(snap: dict, where: str) -> None:
            if any(snap["ack"].values()):
                raise AssertionError(
                    f"{tag} FAIL: {eng.name} endpoint acknowledged {where} "
                    f"(ack={snap['ack']} bus="
                    f"{ {b: hex(w) for b, w in snap['bus'].items()} }; held "
                    f"{ {b: hex(w) for b, w in held.items()} } at the request)"
                )

        samples: list[dict] = []
        for _ in range(_EDN_LEAD_CYCLES):
            await RisingEdge(clk)
            await ReadOnly()
            samples.append(sample())
            if samples[-1]["rst"] == 0:
                break
        else:
            raise AssertionError(f"{tag} FAIL: {eng.name} gated reset did not fall")
        fall_iso = samples[-1]["iso"]
        if fall_iso is not None and fall_iso != (1, 1):
            raise AssertionError(
                f"CHK-KMAC-DRAIN-ORDER FAIL: {eng.name} reset asserted before its "
                f"AXI-Lite paths isolated in a {tag} trial: host_iso={fall_iso[0]} "
                f"km_iso={fall_iso[1]} on the cycle the gated reset fell"
            )
        # Cancel start: the first cycle every path of the domain reports
        # isolated. If none is seen while the reset is released, the window
        # starts on the cycle the gated reset falls.
        c0 = next((i for i, sn in enumerate(samples) if sn["cx"]), len(samples) - 1)
        window = samples[c0:]
        for sn in window[:-1]:
            if sn["rst"] != 1:
                raise AssertionError(f"{tag} FAIL: {eng.name} gated reset fell and rose again")
            require_quiet(sn, "on a released cycle after its paths reported isolated")
        require_quiet(window[-1], "on the cycle its gated reset fell")
        lead = len(window) - 1
        committed: dict[int, tuple[int, int]] = {}
        if c0 >= 1:
            pre = samples[c0 - 1]
            for b in bits:
                w = pre["bus"][b]
                if pre["ack"][b] or not w:
                    continue
                if any(a[2] == w for a in self._edn_acked):
                    continue
                committed[b] = (pre["cyc"], w)
        start_bus = dict(window[0]["bus"])
        bus_live = sum(1 for sn in window if any(sn["bus"].values()))
        # A request is live at the cancel when edn_req is high on the last
        # released cycle before the gated reset falls and neither that cycle
        # nor the one before acknowledged it.
        live = {
            b: len(samples) >= 3
            and samples[-2]["req"][b]
            and not samples[-2]["ack"][b]
            and not samples[-3]["ack"][b]
            for b in bits
        }

        # Every later asserted-reset cycle is sampled too; the release is issued
        # once the reset write has completed, from the normal phase of a clock
        # edge.
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
            require_quiet(snap, "while its gated reset is asserted")
            if any(snap["bus"].values()):
                bus_live += 1
        else:
            raise AssertionError(f"{tag} FAIL: {eng.name} gated reset did not release")
        await RisingEdge(clk)
        if release_task is None:
            raise AssertionError(f"{tag} FAIL: {eng.name} released before its release write")
        await release_task
        return {
            "lead": lead,
            "reset_cycles": reset_cycles,
            "fall_iso": fall_iso,
            "committed": committed,
            "start_bus": start_bus,
            "bus_live": bus_live,
            "live": live,
        }

    async def _edn_live_trials(
        self, tag: str, name: str, eng, bits: tuple[int, ...], rst_sig, arm, iso=None
    ) -> int:
        """Reset ``eng`` while ``bits[0]`` has a live EDN request.

        Each attempt calls ``arm`` for a fresh request and writes the reset a
        walking 0 to ``_EDN_HOLD_STEP - 1`` cycles after the request is seen.
        The attempts stop once ``_EDN_LEAD_TRIALS[name]`` resets found the
        request live at the cancel. Every attempt runs inside the graded
        window; the cancel cell samples only a reset with a live request.
        Fails if fewer resets than that count found one, so the cancel of a
        live request is graded on every engine. Returns the attempts made.
        """
        need = _EDN_LEAD_TRIALS[name]
        budget = _EDN_LIVE_PASSES * _EDN_HOLD_STEP
        armed = 0
        attempts = 0
        while armed < need and attempts < budget:
            await arm(f"{tag} {name} attempt {attempts}")
            if await self._edn_lead_trial(
                tag,
                eng,
                bits,
                rst_sig,
                delay=attempts % _EDN_HOLD_STEP,
                live=True,
                graded=True,
                iso=iso,
            ):
                armed += 1
            attempts += 1
        if armed < need:
            raise AssertionError(
                f"{tag} FAIL: {armed} of {attempts} {name} resets found edn_req live at "
                f"the cancel ({need} required). The acknowledge compare cannot fail "
                "without a live request, so the cancel is not graded."
            )
        return attempts

    async def _arm_aes_live(self, tag: str) -> None:
        # A PRNG reseed raises the AES edn_req for several EDN words.
        await self.aes._wr(AES_TRIGGER, AES_TRIGGER_PRNG_RESEED)

    async def _arm_rnd_live(self, tag: str) -> None:
        # The RND program blocks on its RND reads, each of several EDN words.
        await self.otbn.load_program(OTBN_RND_PROG)
        await self.otbn.start_execute()

    async def _prove_edn_cancel_lead(self, tag: str) -> None:
        """A software reset cancels the engine's endpoints from its isolated cycle.

        KMAC, AES, OTBN URND and OTBN RND are reset while the endpoint's EDN
        request is live, so EDN would acknowledge it inside the window without
        the cancel; each needs ``_EDN_LEAD_TRIALS`` such resets. Six more OTBN
        trials start at a different offset from a URND acknowledge each time,
        with the graded window closed. The committed-word walk then puts an OTBN cancel start on every phase of one URND
        acknowledge period, from a fresh URND burst each time, until one
        finds a URND word committed and not yet acknowledged (the
        CHK-EDN-DISCARD minimum).

        The KMAC trials also grade the reset order: the KMAC gated reset falls
        only on a cycle where the host and Key Manager paths both report
        isolated.
        """
        kmac_iso = (cocotb.top.kmac_host_isolated_probe_o, cocotb.top.kmac_km_isolated_probe_o)
        n_kmac = await self._edn_live_trials(
            tag,
            "kmac",
            ENG_KMAC,
            (_EDN_KMAC,),
            cocotb.top.kmac_gated_rst_n_probe_o,
            self._arm_kmac_edn,
            iso=kmac_iso,
        )
        n_aes = await self._edn_live_trials(
            tag,
            "aes",
            ENG_AES,
            (_EDN_AES,),
            cocotb.top.aes_gated_rst_n_probe_o,
            self._arm_aes_live,
        )
        urnd_phase_live = 0
        for trial in range(_EDN_LEAD_TRIALS["otbn"]):
            # A cold OTBN requests URND until acknowledged; the AES and KMAC
            # trials above can leave it idle, so pulse it back if so.
            if not (self._edn_req() & (1 << _EDN_URND)):
                await self._arm_urnd(f"{tag} otbn {trial}")
            urnd_phase_live += await self._edn_lead_trial(
                tag,
                ENG_OTBN,
                (_EDN_URND, _EDN_OTBN_RND),
                cocotb.top.otbn_gated_rst_n_probe_o,
                delay=trial,
            )
        # Committed-word walk: one pass of the cancel start over every phase
        # of the URND acknowledge period, each from a fresh URND burst.
        period = getattr(self, "_urnd_period", None)
        if period is None or period >= _EDN_HOLD_STEP:
            raise AssertionError(
                f"{tag} SETUP FAILED (not a contract result): the measured URND "
                f"acknowledge period {period} is not below the {_EDN_HOLD_STEP}-cycle "
                "step, so the walk cannot cover every phase"
            )
        walk = 0
        walk_live = 0
        while not self._edn_committed and walk < _EDN_HOLD_STEP:
            await self._arm_urnd(f"{tag} commit walk {walk}")
            walk_live += await self._edn_lead_trial(
                tag,
                ENG_OTBN,
                (_EDN_URND, _EDN_OTBN_RND),
                cocotb.top.otbn_gated_rst_n_probe_o,
                delay=walk,
                graded=True,
                after_ack=True,
            )
            walk += 1
        self.logger.info(
            "%s: committed-word walk ran %d OTBN trial(s) over a %d-cycle URND "
            "acknowledge period; %d word(s) committed and not yet acknowledged on "
            "the cycle before a cancel start",
            tag,
            walk,
            period,
            len(self._edn_committed),
        )
        # URND with a live request: each attempt pulses OTBN, so URND raises
        # edn_req and holds it until an acknowledge, then walks the reset
        # request over the phase of the URND acknowledge period.
        n_urnd = await self._edn_live_trials(
            tag,
            "otbn_urnd",
            ENG_OTBN,
            (_EDN_URND, _EDN_OTBN_RND),
            cocotb.top.otbn_gated_rst_n_probe_o,
            self._arm_urnd,
        )
        n_rnd = await self._edn_live_trials(
            tag,
            "otbn_rnd",
            ENG_OTBN,
            (_EDN_OTBN_RND, _EDN_URND),
            cocotb.top.otbn_gated_rst_n_probe_o,
            self._arm_rnd_live,
        )
        self.logger.info(
            "%s PASS: %d KMAC, %d AES, %d OTBN URND and %d OTBN RND resets with a "
            "live request (%d, %d, %d and %d attempts), %d OTBN URND phase resets "
            "(URND live on %d) and %d walk resets (URND live on %d) each showed no "
            "edn_ack on the engine's EDN endpoints from the first cycle its paths "
            "reported isolated, on the cycle the gated reset fell and on every "
            "asserted-reset cycle",
            tag,
            _EDN_LEAD_TRIALS["kmac"],
            _EDN_LEAD_TRIALS["aes"],
            _EDN_LEAD_TRIALS["otbn_urnd"],
            _EDN_LEAD_TRIALS["otbn_rnd"],
            n_kmac,
            n_aes,
            n_urnd,
            n_rnd,
            _EDN_LEAD_TRIALS["otbn"],
            urnd_phase_live,
            walk,
            walk_live,
        )

    def _check_edn_discard(self, tag: str) -> None:
        """No committed word is acknowledged after its cancel.

        A word committed to an endpoint and not yet acknowledged on the cycle
        before its cancel started must never be acknowledged to any client
        afterwards (hw/sys/sep/doc/reset_controller.adoc:152-153). At least one
        such word is required, so the discard is graded.

        The words the endpoints held at each reset request are logged as
        ``OBS-EDN-HELD-AT-REQUEST``, with any acknowledge of the same word
        after the request. EDN keeps serving the engine while it drains
        (reset_controller.adoc:151), and no text states whether a word on the
        endpoint bus before the paths isolate is committed, so they are not
        graded.
        """
        for at, bit, word in self._edn_held:
            later = [(t, c) for t, c, w in self._edn_acked if w == word and t > at]
            self.logger.info(
                "OBS-EDN-HELD-AT-REQUEST: endpoint %d word 0x%08x on the bus at the "
                "reset request (cycle %d); acknowledged after it %s (no stated value)",
                bit,
                word,
                at,
                ", ".join(f"to client {c} at cycle {t}" for t, c in later) or "never",
            )
        if not self._edn_committed:
            raise AssertionError(
                f"{tag} FAIL: no cancel start found a word committed and not yet "
                "acknowledged, so the discard of such a word is not graded"
            )
        redelivered = []
        for at, bit, word in self._edn_committed:
            after = [a for a in self._edn_acked if a[2] == word and a[0] > at]
            if after:
                redelivered.append((bit, word, after))
        if redelivered:
            raise AssertionError(
                f"{tag} FAIL: a word committed to a cancelled endpoint and not yet "
                "acknowledged was acknowledged after the cancel: "
                + "; ".join(
                    f"endpoint {b} word 0x{w:08x} -> "
                    + ", ".join(f"client {c} at cycle {t}" for t, c, _ in a)
                    for b, w, a in redelivered
                )
            )
        self.logger.info(
            "%s PASS: %d word(s) committed and not yet acknowledged at a cancel "
            "start (%s) were never acknowledged to any client afterwards, across "
            "%d recorded acknowledges",
            tag,
            len(self._edn_committed),
            ", ".join(f"endpoint {b} 0x{w:08x}" for _t, b, w in self._edn_committed),
            len(self._edn_acked),
        )

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        self.rst = SepCryptoResetIso(self)
        self.aes = SepAes(self)
        self.otbn = SepOtbn(self)
        set_iprst_edn_pass(False, self.logger)
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
        self._edn_held: list[tuple[int, int, int]] = []
        self._edn_committed: list[tuple[int, int, int]] = []
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
        # The acknowledge watcher ends in a ReadOnly phase, where the label
        # cannot be written.
        await NextTimeStep()
        # The cancel cells of the graded CHK-EDN-LEAD trials are held from each
        # reset release; this label releases them after CHK-EDN-DISCARD has
        # graded every word those resets cancelled.
        set_iprst_edn_pass(True, self.logger)
        await ClockCycles(cocotb.top.clk_i, 2)
        set_iprst_edn_pass(False, self.logger)

        self.hmac = SepHmac(self)
        self.kmac = SepKmac(self)

        # Establish a held, golden-checked result in each engine.
        h_digest = await self._run_hmac()
        c_block = await self._run_aes()

        # Re-readability + CHK-NONVAC: each result is a golden-matched value that
        # the engine HOLDS (a second read returns the same value -- so "survives"
        # later is a real, non-trivial observation, not a one-shot artifact).
        assert await self.hmac.read_digest() == h_digest, (
            "CHK-NONVAC FAIL: HMAC DIGEST not held on re-read"
        )
        assert await self.aes.read_data_out() == c_block, (
            "CHK-NONVAC FAIL: AES DATA_OUT not held on re-read"
        )
        # The non-vacuity evidence is the re-read pair above, a second real DUT
        # read; both results are already pinned bit-exact to their goldens, so a
        # compare against the zero constant is decidable without the DUT.
        self.logger.info(
            "CHK-NONVAC PASS: HMAC DIGEST + AES DATA_OUT hold golden results and "
            "read the same on a second read: HMAC[0]=0x%08x AES[0]=0x%08x",
            h_digest[0],
            c_block[0],
        )

        # ---- Case A: pulse AES (victim); HMAC (neighbor) must survive ----------
        # Self-reset evidence is the first CTRL_SHADOWED read after the AES
        # pulse: every field returns to its register-map reset
        # (vendor/lowRISC/opentitan/upstream/hw/ip/aes/data/aes.hjson:627-804;
        # hw/sys/sep/doc/crypto.adoc:97 gives each accelerator its own
        # software reset). The read before the pulse shows the programmed
        # ECB-256 ENC value, which differs from that reset, so the check can
        # fail on a pulse that did not land. DATA_OUT after the pulse is
        # logged only: aes.hjson states that a reset clears it "with
        # pseudo-random data", so it has no exact value.
        ctrl_pre = await self.aes._rd(AES_CTRL_SHADOWED)
        async with self._graded_window():
            await self._pulse_reset(ENG_AES.rst_bit)
            ctrl_post = await self.aes._rd(AES_CTRL_SHADOWED)
            self._grade(
                (ctrl_pre & AES_CTRL_FIELD_MASK) == AES_CTRL_ECB256_ENC
                and AES_CTRL_ECB256_ENC != AES_CTRL_RESET
                and (ctrl_post & AES_CTRL_FIELD_MASK) == AES_CTRL_RESET,
                "CHK-SELF-RESET",
                f"AES CTRL_SHADOWED before the pulse 0x{ctrl_pre:08x} (expected "
                f"programmed 0x{AES_CTRL_ECB256_ENC:08x}), first read after its own "
                f"SW_RESET_N pulse 0x{ctrl_post:08x}; expected reset "
                f"0x{AES_CTRL_RESET:08x} under field mask 0x{AES_CTRL_FIELD_MASK:08x}",
                f"AES CTRL_SHADOWED 0x{ctrl_pre:08x} before the pulse (programmed "
                f"0x{AES_CTRL_ECB256_ENC:08x}, not the reset), first read after its own "
                f"SW_RESET_N pulse 0x{ctrl_post:08x} == reset 0x{AES_CTRL_RESET:08x} "
                f"under field mask 0x{AES_CTRL_FIELD_MASK:08x}",
            )
        self.logger.info(
            "OBS-AES-CTRL-RESERVED: CTRL_SHADOWED reserved bits 0x%08x after the pulse "
            "(no stated value)",
            ctrl_post & ~AES_CTRL_FIELD_MASK & 0xFFFF_FFFF,
        )
        aes_after = await self.aes.read_data_out()
        self.logger.info(
            "OBS-AES-DATA-OUT: DATA_OUT after the AES pulse %s (held %s; differs=%s)",
            [hex(w) for w in aes_after],
            [hex(w) for w in c_block],
            aes_after != c_block,
        )
        hmac_survived = await self.hmac.read_digest()
        self._grade(
            hmac_survived == h_digest,
            "CHK-NEIGHBOR-SURVIVES",
            "HMAC held DIGEST was disturbed by AES's reset (domains not isolated): "
            f"before={[hex(w) for w in h_digest]} after={[hex(w) for w in hmac_survived]}",
            f"HMAC DIGEST bit-exact intact across the AES reset ([0]=0x{h_digest[0]:08x})",
        )

        # ---- Case B (reverse): pulse HMAC (victim); AES (neighbor) must survive --
        # Re-establish the AES held result (cleared by its Case-A reset); HMAC still
        # holds its digest (it was the neighbour, untouched). No register-map
        # reset value is stated for HMAC DIGEST (an external register with no
        # reset, vendor/lowRISC/opentitan/overlay/regs/hmac/regs/hmac.rdl:242),
        # so the DIGEST after the HMAC pulse is logged, not graded. The gated
        # reset probe in _pulse_reset shows that the pulse landed.
        c_block = await self._run_aes()
        assert await self.hmac.read_digest() == h_digest, "HMAC DIGEST lost before Case B"
        await self._pulse_reset(ENG_HMAC.rst_bit)
        hmac_after = await self.hmac.read_digest()
        self.logger.info(
            "OBS-HMAC-DIGEST: DIGEST after HMAC's own SW_RESET_N pulse %s (held %s)",
            [hex(w) for w in hmac_after],
            [hex(w) for w in h_digest],
        )
        aes_survived = await self.aes.read_data_out()
        self._grade(
            aes_survived == c_block,
            "CHK-REVERSE",
            "AES held DATA_OUT was disturbed by HMAC's reset (domains not isolated): "
            f"before={[hex(w) for w in c_block]} after={[hex(w) for w in aes_survived]}",
            f"AES DATA_OUT bit-exact intact across the HMAC reset ([0]=0x{c_block[0]:08x})",
        )

        # ---- Isolate window: HMAC held in reset; same DIGEST_0 must SLVERR --
        # Re-establish a live HMAC result so the pre-window beat is OKAY + the
        # golden (an unmapped address cannot produce OKAY -> SLVERR -> OKAY).
        # AES still holds C from Case B; that is the sibling-OKAY witness.
        h_digest = await self._run_hmac()
        pre = await self.rst.probe(HMAC_DIGEST_0)
        assert pre.resp_code == RESP_OKAY and pre.rdata == h_digest[0], (
            f"CHK-ISOLATE-PRE FAIL: isolate pre-window HMAC DIGEST_0 resp={pre.resp_code} "
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
            stage="host_hmac",
        )
        edge = rec["reset"]
        assert edge["host"] == 1 and edge["km"] == 1, (
            "CHK-DRAIN-ORDER FAIL: HMAC reset asserted before its AXI-Lite paths isolated: "
            f"host_hmac={edge['host']} km_hmac={edge['km']}"
        )
        self.logger.info(
            "CHK-DRAIN-ORDER PASS: HMAC reset asserted at %.2f ns only after the "
            "host and Key Manager paths both reported isolated (sampled in the "
            "same cycle as the observed assert edge)",
            edge["t"],
        )

        await self._grade_host_drain(rec, name="HMAC", chk="CHK-HOST-DRAIN")

        arrival_code, arrival_rdata = await self._arrival_beat(
            rec, name="HMAC", chk="CHK-DRAIN-ARRIVAL"
        )
        hs = rec["hs"]
        self.logger.info(
            "CHK-DRAIN-ARRIVAL PASS: arrival AR accepted on s_axi at %.2f ns "
            "(req=%d host_iso=%d km_iso=%d gated=%d), %.2f ns before the gated "
            "reset asserted at %.2f ns; resp=%d (SLVERR) rdata=0x%08x == isolated "
            "read data",
            hs["t"],
            hs["req"],
            hs["host"],
            hs["km"],
            hs["rst"],
            edge["t"] - hs["t"],
            edge["t"],
            arrival_code,
            arrival_rdata,
        )

        sw = await self.rst.read_back()
        assert (sw >> RST_HMAC) & 1 == 0, (
            f"CHK-ISOLATE-LANDED FAIL: SW_RESET_N HMAC bit still released after isolate "
            f"request: 0x{sw:08x}"
        )
        self.logger.info("CHK-ISOLATE-LANDED PASS: SW_RESET_N=0x%08x HMAC bit held", sw)

        iso_rd = await self.rst.probe(HMAC_DIGEST_0, expect_error=True)
        assert iso_rd.resp_code == RESP_SLVERR and not iso_rd.timed_out, (
            f"CHK-ISOLATE-SLVERR FAIL: in-window HMAC DIGEST_0 read resp={iso_rd.resp_code} "
            f"timed_out={iso_rd.timed_out}, expected SLVERR (not hang/OKAY/DECERR)"
        )
        assert iso_rd.rdata == ISO_DATA, (
            f"CHK-ISOLATE-SLVERR FAIL: in-window HMAC DIGEST_0 read returned SLVERR with data "
            f"0x{iso_rd.rdata:08x}, expected the isolated read data 0x{ISO_DATA:08x} "
            f"(live digest word 0x{h_digest[0]:08x})"
        )
        self.logger.info(
            "CHK-ISOLATE-SLVERR PASS: HMAC DIGEST_0 read -> SLVERR (resp=%d) "
            "rdata=0x%08x == isolated read data 0x%08x (live digest 0x%08x)",
            iso_rd.resp_code,
            iso_rd.rdata,
            ISO_DATA,
            h_digest[0],
        )

        iso_wr = await self.rst.probe(HMAC_CFG, write=True, wdata=0x1, expect_error=True)
        assert iso_wr.resp_code == RESP_SLVERR and not iso_wr.timed_out, (
            f"CHK-ISOLATE-WR FAIL: in-window HMAC CFG write resp={iso_wr.resp_code} "
            f"timed_out={iso_wr.timed_out}, expected SLVERR"
        )
        self.logger.info(
            "CHK-ISOLATE-WR PASS: HMAC CFG write -> SLVERR (resp=%d)", iso_wr.resp_code
        )

        sib = await self.rst.probe(AES_DATA_OUT_0)
        assert sib.resp_code == RESP_OKAY and sib.rdata == c_block[0], (
            f"CHK-ISOLATE-SIBLING FAIL: in-window sibling AES DATA_OUT_0 resp={sib.resp_code} "
            f"rdata=0x{sib.rdata:08x}, expected OKAY + 0x{c_block[0]:08x}"
        )
        self.logger.info(
            "CHK-ISOLATE-SIBLING PASS: AES DATA_OUT_0 OKAY 0x%08x in HMAC window", sib.rdata
        )

        await self.rst.release_resets()
        await ClockCycles(cocotb.top.clk_i, 40)
        post = await self.rst.probe(HMAC_DIGEST_0)
        assert post.resp_code == RESP_OKAY, (
            f"CHK-ISOLATE-REOPEN FAIL: post-release HMAC DIGEST_0 resp={post.resp_code}, "
            "expected OKAY"
        )
        self.logger.info("CHK-ISOLATE-REOPEN PASS: HMAC DIGEST_0 OKAY after release")
        # HMAC DIGEST has no stated reset value (hmac.rdl:242), so the data is logged.
        self.logger.info(
            "OBS-HMAC-DIGEST-REOPEN: DIGEST_0 after release 0x%08x (held 0x%08x)",
            post.rdata,
            h_digest[0],
        )

        # Remaining SW_RESET_N bits that this DUT isolates: KMAC and OTBN.
        # KM (bit 0) stays held at the reset default -- a different mechanism.
        h_digest = await self._run_hmac()
        k_digest = await self._run_kmac()
        assert await self.kmac.read_digest() == k_digest, "KMAC STATE not held on re-read"
        kmac_pre = await self.kmac.read_status()
        # The KMAC reset of the drain leg is the own-reset pulse graded below.
        async with self._graded_window():
            await self._drain_kmac()
            kmac_status = await self.kmac.read_status()
            self._grade(
                (kmac_pre & KMAC_STATUS_RDL_MASK) != KMAC_STATUS_RDL_RESET
                and (kmac_status & KMAC_STATUS_RDL_MASK) == KMAC_STATUS_RDL_RESET,
                "CHK-KMAC-SELF",
                f"KMAC STATUS before the pulse 0x{kmac_pre:08x}, first read after its "
                f"own SW_RESET_N pulse 0x{kmac_status:08x}; expected the pre-pulse "
                f"value to differ from register-map reset 0x{KMAC_STATUS_RDL_RESET:08x} "
                f"under mask 0x{KMAC_STATUS_RDL_MASK:08x}, and the post-pulse value to "
                "equal it there",
                f"KMAC STATUS 0x{kmac_pre:08x} before the pulse (not the reset under "
                f"mask 0x{KMAC_STATUS_RDL_MASK:08x}), first read after its own "
                f"SW_RESET_N pulse 0x{kmac_status:08x}: register-map reset "
                f"0x{KMAC_STATUS_RDL_RESET:08x} under mask 0x{KMAC_STATUS_RDL_MASK:08x}",
            )
        self.logger.info(
            "OBS-KMAC-STATUS-UNSTATED: STATUS sha3_absorb/sha3_squeeze/fifo_depth/"
            "fifo_full bits 0x%08x under mask 0x%08x after the pulse (no stated reset value)",
            kmac_status & KMAC_STATUS_UNSTATED_MASK,
            KMAC_STATUS_UNSTATED_MASK,
        )
        self.logger.info(
            "OBS-KMAC-STATUS-RESERVED: STATUS reserved bits 0x%08x after the pulse "
            "(no stated value)",
            kmac_status & KMAC_STATUS_RESERVED_MASK,
        )
        # STATE is a window, not a register-map CSR, and no spec states its value
        # after reset, so it is logged, not graded.
        kmac_after = await self.kmac.read_digest()
        self.logger.info(
            "OBS-KMAC-STATE: STATE after KMAC's own SW_RESET_N pulse %s (held %s)",
            [hex(w) for w in kmac_after],
            [hex(w) for w in k_digest],
        )
        hmac_survived = await self.hmac.read_digest()
        self._grade(
            hmac_survived == h_digest,
            "CHK-NEIGHBOR-SURVIVES",
            "HMAC DIGEST disturbed by KMAC reset: "
            f"before={[hex(w) for w in h_digest]} after={[hex(w) for w in hmac_survived]}",
            f"HMAC DIGEST bit-exact intact across the KMAC reset ([0]=0x{h_digest[0]:08x})",
        )

        k_digest = await self._run_kmac()
        await self._pulse_reset(ENG_HMAC.rst_bit)
        kmac_survived = await self.kmac.read_digest()
        assert kmac_survived == k_digest, (
            "CHK-KMAC-NEIGHBOR FAIL: KMAC STATE disturbed by HMAC reset:\n"
            f"  before={[hex(w) for w in k_digest]}\n  after={[hex(w) for w in kmac_survived]}"
        )
        self.logger.info("CHK-KMAC-NEIGHBOR PASS: HMAC reset left KMAC STATE bit-exact intact")

        mark, dmem_mark = await self._otbn_hold_checksum_and_dmem()
        await self._pulse_reset(ENG_AES.rst_bit)
        otbn_survived = await self.otbn.read_load_checksum()
        dmem_survived = await self.otbn.read_dmem(OTBN_DMEM_RESULT_LO)
        self._grade(
            otbn_survived == mark and dmem_survived == dmem_mark,
            "CHK-OTBN",
            f"OTBN LOAD_CHECKSUM 0x{otbn_survived:08x} (held 0x{mark:08x}) or DMEM "
            f"0x{dmem_survived:08x} (held 0x{dmem_mark:08x}) disturbed by the AES "
            "reset (cross-domain leak)",
            f"LOAD_CHECKSUM 0x{otbn_survived:08x} and DMEM 0x{dmem_survived:08x} held "
            "across the AES neighbour reset",
        )
        # The read above is the last LOAD_CHECKSUM value before the OTBN pulse;
        # it is the held mark, which differs from the register-map reset.
        async with self._graded_window():
            await self._pulse_reset(ENG_OTBN.rst_bit)
            await self.otbn.wait_idle("post-otbn-reset")
            otbn_after = await self.otbn.read_load_checksum()
            self._grade(
                mark != OTBN_LOAD_CHECKSUM_RESET and otbn_after == OTBN_LOAD_CHECKSUM_RESET,
                "CHK-OTBN",
                f"OTBN LOAD_CHECKSUM first read after its own SW_RESET_N pulse "
                f"0x{otbn_after:08x}, held 0x{mark:08x} before it; expected reset "
                f"0x{OTBN_LOAD_CHECKSUM_RESET:08x}",
                f"LOAD_CHECKSUM held 0x{mark:08x} (not the reset) before the OTBN pulse, "
                f"first read after it 0x{otbn_after:08x} == reset "
                f"0x{OTBN_LOAD_CHECKSUM_RESET:08x}",
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

        fips = SepEsrcFipsLock(self)
        await fips.set_lock()
        lock_set = await fips.read_lock_word() & LOCK_BIT
        if lock_set != LOCK_BIT:
            close_graded_window(self.logger)
            raise AssertionError(
                f"CTRL-MISSING CHK-TRNG-FIPS-LOCK-RESET: FIPS_LOCK.LOCK=0x{lock_set:x} after "
                "the write of 1, so a reset could not show a clear"
            )
        self.logger.info("CTRL-TRNG-FIPS-LOCK-SET: FIPS_LOCK.LOCK=1 before the TRNG reset")
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
            f"CHK-TRNG-NEIGHBORS FAIL: SW_RESET_N=0x{sw_parked:08x} shows the TRNG "
            "domain NOT held inside the "
            "window the neighbour results are checked in, so this leg would pass "
            "whether or not the reset request reached the entropy complex"
        )
        assert (sw_parked & neighbours) == neighbours, (
            f"CHK-TRNG-NEIGHBORS FAIL: SW_RESET_N=0x{sw_parked:08x} shows an "
            "accelerator domain also held "
            "during the TRNG-only reset, so a surviving neighbour result proves "
            "nothing about isolation"
        )
        assert await self.hmac.read_digest() == h_digest, (
            "CHK-TRNG-NEIGHBORS FAIL: HMAC held DIGEST was disturbed by a TRNG-only reset"
        )
        assert await self.aes.read_data_out() == c_block, (
            "CHK-TRNG-NEIGHBORS FAIL: AES held DATA_OUT was disturbed by a TRNG-only reset"
        )
        assert self.rd_known(cocotb.top.trng_gated_rst_n_probe_o) == 0, (
            "CHK-TRNG-NEIGHBORS FAIL: TRNG gated reset released before the neighbour "
            "results were read, so "
            "they were not sampled inside the reset"
        )
        await self._obs_trng_iso_resp()
        await trng_rst.release("trng")
        await self._wait_gated_rst(SW_RESET_N_BIT["trng"], 1, "CHK-TRNG-FIPS-LOCK-RESET release")
        lock_after = await fips.read_lock_word() & LOCK_BIT
        self._grade(
            lock_after == FIPS_LOCK_RESET,
            "CHK-TRNG-FIPS-LOCK-RESET",
            f"FIPS_LOCK.LOCK=0x{lock_after:x} after the TRNG-only reset, held 0x{LOCK_BIT:x} "
            f"before it; expected reset 0x{FIPS_LOCK_RESET:x}",
            f"FIPS_LOCK.LOCK held 0x{LOCK_BIT:x} before the TRNG-only reset, read "
            f"0x{lock_after:x} == reset 0x{FIPS_LOCK_RESET:x} after the release",
        )
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
            stage="host_abr",
        )
        edge = rec["reset"]
        assert edge["host"] == 1 and edge["km"] == 1, (
            "CHK-ABR-DRAIN-ORDER FAIL: ABR reset asserted before its AXI paths isolated: "
            f"host_abr={edge['host']} km_abr={edge['km']}"
        )
        self.logger.info(
            "CHK-ABR-DRAIN-ORDER PASS: ABR reset asserted at %.2f ns only after the "
            "full-AXI host path and the shared Key Manager path both reported "
            "isolated (sampled in the same cycle as the observed assert edge)",
            edge["t"],
        )

        await self._grade_host_drain(rec, name="ABR", chk="CHK-ABR-HOST-DRAIN")

        abr_arrival_code, abr_arrival_rdata = await self._arrival_beat(
            rec, name="ABR", chk="CHK-ABR-DRAIN-ARRIVAL"
        )
        hs = rec["hs"]
        self.logger.info(
            "CHK-ABR-DRAIN-ARRIVAL PASS: arrival AR accepted on s_axi at %.2f ns "
            "(req=%d host_iso=%d km_iso=%d gated=%d), %.2f ns before the gated "
            "reset asserted at %.2f ns; resp=%d (SLVERR) rdata=0x%08x == isolated "
            "read data",
            hs["t"],
            hs["req"],
            hs["host"],
            hs["km"],
            hs["rst"],
            edge["t"] - hs["t"],
            edge["t"],
            abr_arrival_code,
            abr_arrival_rdata,
        )
        await abr_rst.release_resets()

        # ---- ABR JTAG IC_RESET override -------------------------------------
        # The override mux sits after the SW-reset AND: asserting it must hold
        # the domain even though SW_RESET_N still shows ABR released. Both
        # directions are graded, so a mux stuck in either position fails.
        sw_before = await abr_rst.read_back()
        assert sw_before & (1 << RST_ABR), (
            f"CHK-ABR-JTAG-OVERRIDE FAIL: SW_RESET_N=0x{sw_before:08x} shows ABR already "
            "held before the JTAG "
            "override is applied, so a held gated reset below would prove nothing"
        )
        assert int(cocotb.top.abr_gated_rst_n_probe_o.value) == 1, (
            "CHK-ABR-JTAG-OVERRIDE FAIL: ABR gated reset is already asserted before the "
            "JTAG override, so the "
            "override cannot be shown to be what holds it"
        )
        cocotb.top.jtag_abr_rst_hold_i.value = 1
        await ClockCycles(cocotb.top.clk_i, 10)
        sw_held = await abr_rst.read_back()
        assert int(cocotb.top.abr_gated_rst_n_probe_o.value) == 0, (
            "CHK-ABR-JTAG-OVERRIDE FAIL: JTAG override asserted but the ABR gated reset "
            "stayed released, so "
            "the override select does not reach the reset mux"
        )
        assert sw_held & (1 << RST_ABR), (
            f"CHK-ABR-JTAG-OVERRIDE FAIL: SW_RESET_N=0x{sw_held:08x} shows the ABR bit low "
            "inside the override "
            "window, so the hold cannot be attributed to JTAG rather than software"
        )
        cocotb.top.jtag_abr_rst_hold_i.value = 0
        await ClockCycles(cocotb.top.clk_i, 10)
        assert int(cocotb.top.abr_gated_rst_n_probe_o.value) == 1, (
            "CHK-ABR-JTAG-OVERRIDE FAIL: ABR gated reset stayed asserted after the JTAG "
            "override released, so "
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
