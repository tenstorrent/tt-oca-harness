# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Each KM sideload destination uses exactly the delivered key, and a shred leaves it invalid.

no_cpu / real fuse-sense / +km_rom_hex=rom_main.rom.parhex. RANDCFG.

The Key Manager delivers a key as two XOR shares into the KEY_SHARE0 /
KEY_SHARE1 words of a ``<engine>_wrapper_key_reg`` block, and KEY_CTRL.KEY_VALID
qualifies it (hw/sys/sep/doc/crypto.adoc, "Key Manager Key Delivery"). The share words are
write-only and sit on the KM-private bus, so the delivered value is graded at
the consumer. This leaf walks all eight delivery destinations -- AES, HMAC,
KMAC, OTBN and the four ABR blocks -- through two rounds. Each round loads a
fresh seeded key per destination with CMD_KEY_LOAD + CMD_KEY_TRANSFER, proves
that AES, HMAC, KMAC and OTBN used exactly that key and that each ABR
destination used the delivered words in register order, then sends one
CMD_ENGINE_SHRED for all eight destinations and proves the documented
invalid-key behaviour of each consumer. The shred clears KEY_VALID and
overwrites both shares with PRNG data (hw/ip/key_manager/doc/firmware.adoc,
"Crypto Engine Drivers").

Preconditions (asserted, not graded here): rom_main boots on real entropy and
announces RESP_KM_READY; every CMD_KEY_TRANSFER and CMD_ENGINE_SHRED returns
success and echoes its arguments. These are firmware responses. The hardware
effect of each transfer and shred is graded at the consumer below.

Checkers (``r`` is the round, 1 or 2):
  CHK-AES-r     sideload ECB-256 ciphertext == AES-256 golden of the round key
  CHK-HMAC-r    HMAC-SHA256 digest == golden of the round key, with a different
                software key in the KEY CSRs
  CHK-KMAC-r    sideload KMAC256 digest == SP 800-185 golden of the round key
  CHK-OTBN-r    the key-dump program reads key == round key, share0 ^ share1 ==
                round key, ERR_BITS == 0
  CHK-MLDSA-r   the KV seed read completes (VALID, ERROR == SUCCESS) and the
                KEYGEN public key equals a direct-seed KEYGEN of the same words
                in the same order
  CHK-MLKEM-SEED-r
                the D||Z KV read completes, the encapsulation key equals a
                direct-seed KEYGEN of the same D and Z, and the Z the engine
                holds (abr_mlkem_seed_z_probe_o) equals the delivered Z word for
                word. The encapsulation key depends on D only, and software
                cannot read Z back, so the probe is what grades Z
  CHK-MLKEM-MSG-r
                the message KV read completes and the ENCAPS ciphertext equals
                a direct-message ENCAPS of the same words in the same order
  CHK-ROUND     every round-2 ABR output differs from its round-1 output. The
                ABR compares are differential, so this is what fails an engine
                that ignores its seed or message
  CHK-HMAC-CLR-r
                with KEY_VALID clear HMAC uses its software key registers: the
                digest == golden of the software key (hw/sys/sep/doc/hmac.adoc)
  CHK-OTBN-CLR-r
                reading a key share whose key is not valid sets
                ERR_BITS.KEY_INVALID and stops the program (hw/sys/sep/doc/otbn.adoc)
  CHK-ABR-CLR-r each ABR KV read on a shredded block fails: kv status ERROR ==
                KV_READ_FAIL (hw/sys/sep/doc/crypto.adoc km-key-delivery-summary, "Seed
                read does not complete"; encoding from
                vendor/chipsalliance/adams-bridge/upstream/src/abr_top/rtl/kv_def.rdl). D and Z
                have their own KEY_VALID and the D||Z read fails if either is
                clear, so each is graded alone: after the shred only D is
                delivered again and the read must fail (Z is clear); after a
                shred of D and Z only Z is delivered again and the read must
                fail (D is clear). Each single-half leg then delivers the other
                half too and the read must complete, so the re-delivered half
                is shown valid
  CHK-KMAC-CLR  a keyed operation on the delivered key with KEY_VALID clear
                raises kmac_err (hw/sys/sep/doc/kmac.adoc) with ERR_CODE[31:24] ==
                KeyNotValid (OpenTitan KMAC "Error Report" table). Both read
                clear just before CMD_START, so the error belongs to that
                start. Last KMAC operation: the engine is left in its error
                state
  CHK-AES-CLR   with sideload selected and the key shredded, AES produces no
                output in a bounded window. hw/sys/sep/doc/aes.adoc defers core behaviour
                to the OpenTitan AES documentation, which states the unit only
                starts if the sideload key is valid ("System Key-Manager
                Interface"). Last AES operation
  CHK-REFUSE-KEEP
                round 1 only, after CHK-OTBN-1 and before the shred: a second key
                K2 is loaded with DEST_VALID = AES | HMAC, and CMD_KEY_TRANSFER of
                K2 with mask AES | HMAC | OTBN (OTBN not permitted) returns
                failure (-1) with no return argument; the KM-BUS key-path tap
                shows no AW on any of the five ports and no X/Z on the AW
                handshake; ``km_engine_key_valid_o`` is unchanged; AES, HMAC and
                OTBN outputs still equal the round-1 goldens. Then the same
                handle with mask AES | HMAC succeeds, the tap shows AWs on the
                AES and HMAC ports only, and AES and HMAC outputs equal the K2
                goldens, so the refusal comes from the OTBN policy and the tap
                sees those ports live ("If _any_ requested crypto engines are
                disallowed, the request will result in _failure_ and no
                requested key transfers will take place.",
                ``hw/ip/key_manager/doc/firmware.adoc:497-500``; failure = -1,
                ``:908``)
  CHK-OTBN-KEY-S1-SHRED
                each round, right after CHK-OTBN-CLR-r: a key-dump program that
                reads ``KEY_S1_L`` first runs on the shredded key. ERR_BITS is
                cleared and reads 0 before EXECUTE, then reads KEY_INVALID only,
                and INSN_CNT reads 0, so the first instruction faulted and the
                program returned no key material (hw/sys/sep/doc/otbn.adoc,
                "reading a share whose key is not valid sets
                ``ERR_BITS.KEY_INVALID`` and stops the program"; OpenTitan
                ``otbn.hjson`` INSN_CNT, "Instructions triggering an error do
                not count"). INSN_CNT is shown live: it reads nonzero after the
                round's completed key-dump run in CHK-OTBN-r. The S0-first
                key-dump program is loaded again afterwards
  OBS-ABR-ZEROIZE-KM-VALID
                ``km_engine_key_valid_o[7:4]`` (the four Adams Bridge
                destination KEY_VALID bits) just before and just after each ABR
                ZEROIZE of the CHK-MLDSA-r, CHK-MLKEM-SEED-r and CHK-MLKEM-MSG-r
                legs. hw/ip/key_manager/regs/gen/adoc/abr_wrapper_key.adoc states
                no effect of an engine ZEROIZE on these bits, so they are logged

Ordering that the compares rely on:
  * ABR runs the KV leg before its direct-register reference, after a
    ZEROIZE. In round 1 a missing delivery leaves the seed register zero; in
    round 2 it leaves the round-1 reference words. Both fail the compare.
  * Every round-2 key word differs from the round-1 word at the same index,
    so a stale share word changes the consumer output. AES, HMAC, KMAC and
    OTBN then fail their golden; ABR fails its KV-vs-direct compare.
  * Key Manager word i and ABR register index i carry the same dword
    (hw/sys/sep/doc/adams_bridge.adoc, abr-seed-word-order). Every ABR seed, message, D
    and Z has eight pairwise-distinct words, so a dword reversal or any other
    word permutation in KM-to-ABR delivery changes the engine input and fails
    the KV-vs-direct compare.

Short-key and long-key legs. After CHK-ROUND one OTBN key shorter than the
12-word share width, then one longer than it, are each loaded and transferred,
and the key-dump program runs once after each. Each length comes from its own
``SepSeededRng`` stream (the run seed XOR a leg salt, so the round draws keep
their seed mapping). The KM-BUS key-path tap (``km_key_aw_{valid,ready,addr}_o``,
ports 0 OTBN, 1 AES, 2 HMAC, 3 KMAC, 4 Adams Bridge) records every AW handshake
of the transfer; an X/Z cycle on the AW VALID or READY of any port fails the
check that reads the tap:
  CHK-XFER-SHORT-KEY  n drawn in 1..11. ERR_BITS reads 0, share0 ^ share1 words
                0..n-1 equal the short key, and the OTBN port shows each of
                the 12 ``KEY_SHARE0`` and 12 ``KEY_SHARE1`` offsets of the OTBN
                bank written exactly once: "Form one full-width key share from
                the supplied key, padding short keys with DRBG words. ... The
                helper writes the destination's share width."
                (``hw/ip/key_manager/doc/firmware.adoc:1805-1808``;
                ``KEY_SHARE0[12]``, ``KEY_SHARE1[12] @ 0x030``,
                ``hw/ip/key_manager/regs/otbn_wrapper_key.rdl:51``, ``:57``).
                The offsets come from the generated Key Manager register
                header.
  CHK-XFER-LONG-KEY   n drawn in 13..128; no word past the first 12 equals any
                of the first 12, so every slice other than the leading one
                differs. The key is loaded one word at a time while the inbound
                FIFO has room. CMD_KEY_TRANSFER returns success; the OTBN port
                shows each of the 24 share offsets written exactly once and the
                AES, HMAC, KMAC and Adams Bridge ports show no AW; ERR_BITS
                reads 0 and share0 ^ share1 equals the 12 leading words ("If
                the key is longer, it uses only that many leading words; it does
                not reject the length.", ``firmware.adoc:1810-1811``; selected
                engines only, ``:1945-1947``). The tap is shown live on all
                five ports: during the round-1 deliveries every port shows at
                least one AW and no X/Z, which this check also requires
  OBS-ABR-CLR-VALID
                the VALID bit of each failed CHK-ABR-CLR KV read. crypto.adoc,
                km-key-delivery-summary, says only "Seed read does not complete",
                and kv_def.rdl says VALID means the flow is done; no text states
                VALID for a read that ends with KV_READ_FAIL, so it is logged.
  OBS-XFER-PAD  share0 ^ share1 words n..11 and the positions that are not 0.
                firmware.adoc, "Crypto Engine Drivers", pads short keys with
                DRBG words and states no pad position; the pad values are
                random, so no value is graded.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env.sep_aes_golden import aes256_ecb_encrypt_words
from env.sep_chk_log import diff_words, word_digest
from env.sep_fcov_gate import close_graded_window, open_graded_window, set_open_value_leg_pass
from env.sep_hmac_golden import hmac_sha256_words
from env.sep_kmac_golden import kmac_family_words
from env.sep_seeded_rng import SepSeededRng
from env.sep_spec_tables import kv_error_code, kv_status_field
from sep_base_test import sep_base_test
from sep_reg_meta import OTBN
from seq_lib.sep_abr_keygen_seq import (
    ABR_CTRL,
    ABR_ENTROPY,
    ABR_MLDSA_KV_RD_SEED_CTRL,
    ABR_MLDSA_KV_RD_SEED_STATUS,
    ABR_PUBKEY,
    ABR_SEED,
    ABR_STATUS,
    CMD_KEYGEN,
    CTRL_ZEROIZE,
    ENTROPY_WORDS,
    PK_WORDS,
    ST_ERROR,
    ST_READY,
    ST_VALID,
    SepAbr,
)
from seq_lib.sep_abr_mlkem_seq import (
    KEM_CMD_ENCAPS,
    KEM_CMD_KEYGEN,
    KEM_CT_WORDS,
    KEM_CTRL_ZEROIZE,
    KEM_EK_WORDS,
    KEM_ST_ERROR,
    KEM_ST_READY,
    KEM_ST_VALID,
    KV_READ_EN,
    MLKEM_CIPHERTEXT,
    MLKEM_CTRL,
    MLKEM_ENCAPS_KEY,
    MLKEM_KV_MSG_RD_CTRL,
    MLKEM_KV_MSG_RD_STATUS,
    MLKEM_KV_SEED_RD_CTRL,
    MLKEM_KV_SEED_RD_STATUS,
    MLKEM_MSG,
    MLKEM_SEED_D,
    MLKEM_SEED_Z,
    MLKEM_STATUS,
    SepAbrMlkem,
)
from seq_lib.sep_aes_seq import AES_STATUS, AES_STATUS_OUTPUT_VALID, SepAes
from seq_lib.sep_hmac_seq import SepHmac
from seq_lib.sep_km_mailbox_seq import (
    KM_CMD_KEY_LOAD,
    KM_CMD_KEY_TRANSFER,
    KM_DEST_ABR_MLDSA_SEED,
    KM_DEST_ABR_MLKEM_MSG,
    KM_DEST_ABR_MLKEM_SEED_D,
    KM_DEST_ABR_MLKEM_SEED_Z,
    KM_DEST_AES,
    KM_DEST_HMAC,
    KM_DEST_KMAC,
    KM_DEST_OTBN,
    KM_MBOX_WRITE_DATA,
    KM_MBOX_WRITE_SEPARATOR,
    KM_RC_FAILURE,
    KM_RC_SUCCESS,
    KM_RESP_CMD,
    KM_STATUS_INBOUND_FULL,
    SepKmMailbox,
)
from seq_lib.sep_kmac_seq import (
    KMAC_ERR_CODE,
    KMAC_ERR_CODE_SHIFT,
    KMAC_ERR_KEY_NOT_VALID,
    KMAC_INTR_KMAC_ERR,
    KMAC_INTR_STATE,
    SepKmac,
)
from seq_lib.sep_otbn_seq import OTBN_ADDR_ERRBIT, OTBN_KEYDUMP_PROG, SepOtbn

TEST = "sep_km_sideload_share_walk_test"
ROUNDS = 2
# Leg salts of the short-key, long-key and refusal draws.
_SHORT_KEY_SALT = 0x5348_4B59
_LONG_KEY_SALT = 0x4C4F_4E47
_REFUSE_SALT = 0x5246_5345

# Words per share per destination (hw/sys/sep/doc/crypto.adoc, km-key-delivery-summary).
DEST_WORDS = {
    KM_DEST_AES: 8,
    KM_DEST_HMAC: 8,
    KM_DEST_KMAC: 8,
    KM_DEST_OTBN: 12,
    KM_DEST_ABR_MLDSA_SEED: 8,
    KM_DEST_ABR_MLKEM_SEED_D: 8,
    KM_DEST_ABR_MLKEM_SEED_Z: 8,
    KM_DEST_ABR_MLKEM_MSG: 8,
}
DEST_NAME = {
    KM_DEST_AES: "aes",
    KM_DEST_HMAC: "hmac",
    KM_DEST_KMAC: "kmac",
    KM_DEST_OTBN: "otbn",
    KM_DEST_ABR_MLDSA_SEED: "abr_mldsa_seed",
    KM_DEST_ABR_MLKEM_SEED_D: "abr_mlkem_seed_d",
    KM_DEST_ABR_MLKEM_SEED_Z: "abr_mlkem_seed_z",
    KM_DEST_ABR_MLKEM_MSG: "abr_mlkem_msg",
}
ABR_DESTS = (
    KM_DEST_ABR_MLDSA_SEED,
    KM_DEST_ABR_MLKEM_SEED_D,
    KM_DEST_ABR_MLKEM_SEED_Z,
    KM_DEST_ABR_MLKEM_MSG,
)
ALL_DESTS = 0
for _d in DEST_WORDS:
    ALL_DESTS |= _d
# The only destinations the single-half legs deliver again after a shred.
MLKEM_SEED_DESTS = KM_DEST_ABR_MLKEM_SEED_D | KM_DEST_ABR_MLKEM_SEED_Z

KV_SUCCESS = kv_error_code("SUCCESS")
KV_READ_FAIL = kv_error_code("KV_READ_FAIL")
OTBN_ERR_KEY_INVALID = OTBN.field_mask("ERR_BITS", "key_invalid")
OTBN_ADDR_INSN_CNT = OTBN.addr("INSN_CNT")
OTBN_INSN_CNT_MASK = OTBN.field_mask("INSN_CNT", "insn_cnt")
# The key-dump program with its first two instructions swapped, so the first
# key-share read is KEY_S1_L.
OTBN_KEYDUMP_S1_FIRST_PROG = (OTBN_KEYDUMP_PROG[1], OTBN_KEYDUMP_PROG[0], *OTBN_KEYDUMP_PROG[2:])
# KM-VALID carries KEY_VALID in DEST_VALID bit order, so a destination mask
# selects its bits.
KM_VALID_ABR_MASK = sum(ABR_DESTS)
KM_VALID_ABR_LSB = (KM_VALID_ABR_MASK & -KM_VALID_ABR_MASK).bit_length() - 1

# The consumer outputs CHK-ROUND compares. The other consumers have goldens.
ABR_OUTPUTS = ("mldsa", "mlkem_seed", "mlkem_msg")

AES_BLOCK_WORDS = 4
HMAC_MSG_WORDS = 8
KMAC_MSG_WORDS = 8

_POLL_ITERS = 20000
# SEP_STATUS reads for inbound_full to read 0 before one mailbox word.
_INBOUND_POLLS = 2_000
_INBOUND_POLL_GAP = 20
# CMD_KEY_LOAD word 0 bits 6:0 carry KEY_SIZE, and the key is KEY_SIZE + 1 words
# (hw/ip/key_manager/doc/firmware.adoc, key-load-command-payload-figure).
_KEY_WORDS_MAX = 128
_POLL_GAP = 200
# Bounded windows for the cleared-state probes, in 20-cycle polls. A healthy
# engine answers a valid request in far fewer.
_KV_STATUS_POLLS = 2000
_KMAC_ERR_POLLS = 200
_AES_REFUSE_POLLS = 50


# OTBN key-path port of the KM-BUS tap and the share-word offsets of its bank,
# from the generated Key Manager register header.
_KM_GEN_PY = Path(__file__).resolve().parents[6] / "ip" / "key_manager" / "regs" / "gen" / "py"
_KM_REG_SPEC = importlib.util.spec_from_file_location(
    "km_share_walk_key_manager_reg", _KM_GEN_PY / "key_manager_reg.py"
)
if _KM_REG_SPEC is None or _KM_REG_SPEC.loader is None:
    raise FileNotFoundError(_KM_GEN_PY / "key_manager_reg.py")
_KM_REG = importlib.util.module_from_spec(_KM_REG_SPEC)
_KM_REG_SPEC.loader.exec_module(_KM_REG)
# KM-BUS key-path port index of each destination block (docs/SEP_TB_ARCH.adoc,
# KM-BUS key-path part).
_KEY_PORT_NAME = ("otbn", "aes", "hmac", "kmac", "abr")
_OTBN_KEY_PORT = _KEY_PORT_NAME.index("otbn")
_AES_KEY_PORT = _KEY_PORT_NAME.index("aes")
_HMAC_KEY_PORT = _KEY_PORT_NAME.index("hmac")
_BLOCK_SPAN = 0x1000
_OTBN_KEY_BASE = int(_KM_REG.OTBN_WRAPPER_KEY_REG_MAP_BASE_ADDR)
if _OTBN_KEY_BASE % _BLOCK_SPAN or int(_KM_REG.OTBN_WRAPPER_KEY_REG_MAP_SIZE) > _BLOCK_SPAN:
    raise AssertionError("OTBN_WRAPPER_KEY: not a 4 KiB-aligned block below 4 KiB")
OTBN_SHARE_OFFSETS = frozenset(
    int(getattr(_KM_REG, f"OTBN_WRAPPER_KEY_KEY_SHARE{s}_{i}__REG_ADDR")) - _OTBN_KEY_BASE
    for s in (0, 1)
    for i in range(DEST_WORDS[KM_DEST_OTBN])
)
if len(OTBN_SHARE_OFFSETS) != 2 * DEST_WORDS[KM_DEST_OTBN]:
    raise AssertionError("OTBN_WRAPPER_KEY: share offsets are not 2 x 12 distinct words")


class _KeyPortWrites:
    """AW handshakes on the five key-path ports (``KM-BUS``), as (port, block offset).

    ``xz`` counts clocks where a VALID or READY bit is not 0 or 1. Every check
    that reads this monitor requires it to be 0, so an unknown handshake fails
    the check instead of reading as no write.
    """

    def __init__(self, test: sep_base_test) -> None:
        top = cocotb.top
        self.test = test
        self.clk = top.clk_i
        self.valid = top.km_key_aw_valid_o
        self.ready = top.km_key_aw_ready_o
        self.addr = top.km_key_aw_addr_o
        if len(self.valid) != len(_KEY_PORT_NAME):
            raise AssertionError(
                f"km_key_aw_valid_o is {len(self.valid)} bits, expected one per key-path "
                f"port {_KEY_PORT_NAME}"
            )
        self.writes: list[tuple[int, int]] = []
        self.xz = 0
        self._on = False

    def start(self) -> None:
        self.writes = []
        self.xz = 0
        self._on = True
        cocotb.start_soon(self._run())

    async def stop(self) -> list[tuple[int, int]]:
        self._on = False
        await ClockCycles(self.clk, 2)
        return list(self.writes)

    def port_offsets(self, port: int) -> list[int]:
        return [off for p, off in self.writes if p == port]

    def counts(self) -> list[int]:
        return [len(self.port_offsets(p)) for p in range(len(_KEY_PORT_NAME))]

    async def _run(self) -> None:
        while True:
            await RisingEdge(self.clk)
            await ReadOnly()
            if not self._on:
                return
            try:
                hs = self.test.rd(self.valid) & self.test.rd(self.ready)
            except AssertionError:
                self.xz += 1
                continue
            for p in range(len(_KEY_PORT_NAME)):
                if (hs >> p) & 1:
                    lane = 0xFFFF_FFFF << (32 * p)
                    addr = self.test.rd_known(self.addr, lane) >> (32 * p)
                    self.writes.append((p, addr % _BLOCK_SPAN))


def _distinct_words(rng: SepSeededRng, n: int, avoid: list[int] | None) -> list[int]:
    """``n`` random words; word ``i`` differs from ``avoid[i]``, and no word is 0."""
    out = []
    for i in range(n):
        w = rng.getrandbits(32)
        while w == 0 or (avoid is not None and w == avoid[i]):
            w = rng.getrandbits(32)
        out.append(w)
    return out


def _unique_words(rng: SepSeededRng, n: int, avoid: list[int] | None) -> list[int]:
    """``_distinct_words`` with no word repeated inside the block, so any word
    permutation of the block is a different value."""
    while True:
        words = _distinct_words(rng, n, avoid)
        if len(set(words)) == n:
            return words


class SepKmShareWalkCfg:
    """Single source of truth: every key, message and software key of the run."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        self.keys: list[dict[int, list[int]]] = []
        prev: dict[int, list[int]] | None = None
        for _ in range(ROUNDS):
            keys = {}
            for dest, n in DEST_WORDS.items():
                avoid = None if prev is None else prev[dest]
                if dest in ABR_DESTS:
                    keys[dest] = _unique_words(rng, n, avoid)
                else:
                    keys[dest] = _distinct_words(rng, n, avoid)
            self.keys.append(keys)
            prev = keys
        self.aes_pt = _distinct_words(rng, AES_BLOCK_WORDS, None)
        self.hmac_msg = _distinct_words(rng, HMAC_MSG_WORDS, None)
        self.kmac_msg = _distinct_words(rng, KMAC_MSG_WORDS, None)
        self.abr_entropy = _distinct_words(rng, ENTROPY_WORDS, None)
        # HMAC software keys: the decoy in the KEY CSRs while a delivered key
        # is valid, and the key the cleared-state check expects.
        self.hmac_sw = [
            _distinct_words(rng, DEST_WORDS[KM_DEST_HMAC], self.keys[r][KM_DEST_HMAC])
            for r in range(ROUNDS)
        ]

    def summary(self) -> str:
        first = " ".join(
            f"{DEST_NAME[d]}_sha={word_digest(self.keys[0][d])}/{word_digest(self.keys[1][d])}"
            for d in DEST_WORDS
        )
        return f"seed={self.seed} {first} aes_pt[0]=0x{self.aes_pt[0]:08x}"


@pyuvm.test()
class sep_km_sideload_share_walk_test(sep_base_test):
    """Every destination consumes exactly the delivered key; a shred leaves it invalid."""

    required_evidence = (
        *(
            f"CHK-{name}-{r}"
            for r in (1, 2)
            for name in (
                "AES",
                "HMAC",
                "KMAC",
                "OTBN",
                "MLDSA",
                "MLKEM-SEED",
                "MLKEM-MSG",
                "HMAC-CLR",
                "OTBN-CLR",
                "ABR-CLR",
            )
        ),
        "CHK-ROUND",
        "CHK-KMAC-CLR",
        "CHK-AES-CLR",
        "CHK-XFER-SHORT-KEY",
        "CHK-XFER-LONG-KEY",
        "CHK-REFUSE-KEEP",
        "CHK-OTBN-KEY-S1-SHRED",
    )

    # ------------------------------------------------------------------ ABR --
    async def _abr_wait(
        self, drv, status_addr: int, err_bit: int, mask: int, expect: int, *, what: str
    ) -> int:
        for _ in range(_POLL_ITERS):
            st = await drv.rd32(status_addr)
            if (st & mask) == expect:
                return st
            if st & err_bit:
                raise AssertionError(f"{what}: STATUS.ERROR set (0x{st:08x})")
            await ClockCycles(cocotb.top.clk_i, _POLL_GAP)
        raise AssertionError(
            f"{what}: STATUS mask 0x{mask:x} never 0x{expect:x} in {_POLL_ITERS} polls"
        )

    async def _mldsa_zeroize(self, *, what: str) -> None:
        await self.abr.wr32(ABR_CTRL, CTRL_ZEROIZE)
        await self._abr_wait(
            self.abr, ABR_STATUS, ST_ERROR, ST_READY, ST_READY, what=f"{what} ML-DSA READY"
        )

    async def _mlkem_zeroize(self, *, what: str) -> None:
        await self.kem.wr32(MLKEM_CTRL, KEM_CTRL_ZEROIZE)
        await self._abr_wait(
            self.kem, MLKEM_STATUS, KEM_ST_ERROR, KEM_ST_VALID, 0, what=f"{what} ML-KEM VALID clear"
        )
        await self._abr_wait(
            self.kem,
            MLKEM_STATUS,
            KEM_ST_ERROR,
            KEM_ST_READY,
            KEM_ST_READY,
            what=f"{what} ML-KEM READY",
        )

    async def _km_valid(self) -> int:
        """KM-VALID (``km_engine_key_valid_o``), sampled in the read-only phase."""
        await ReadOnly()
        v = self.rd_known(cocotb.top.km_engine_key_valid_o)
        await RisingEdge(cocotb.top.clk_i)
        return v

    async def _zeroize_obs(self, zeroize, *, tag: int, site: str) -> None:
        """One ABR ZEROIZE, with OBS-ABR-ZEROIZE-KM-VALID around it."""
        before = await self._km_valid()
        await zeroize(what=site)
        after = await self._km_valid()
        self.logger.info(
            "OBS-ABR-ZEROIZE-KM-VALID r=%d site=%s abr_key_valid_before=0x%x "
            "abr_key_valid_after=0x%x km_valid_before=0x%02x km_valid_after=0x%02x",
            tag,
            site.replace(" ", "_"),
            (before & KM_VALID_ABR_MASK) >> KM_VALID_ABR_LSB,
            (after & KM_VALID_ABR_MASK) >> KM_VALID_ABR_LSB,
            before,
            after,
        )

    def _obs_clr_valid(self, tag: int, leg: str, st: int) -> None:
        """OBS-ABR-CLR-VALID: the VALID bit of a failed KV read on a shredded block."""
        self.logger.info(
            "OBS-ABR-CLR-VALID r=%d leg=%s valid=%d error=%d status=0x%08x",
            tag,
            leg.replace(" ", "_"),
            kv_status_field(st, "VALID"),
            kv_status_field(st, "ERROR"),
            st,
        )

    async def _kv_read(self, ctrl: int, status: int, *, what: str) -> tuple[int, int]:
        """Arm one KV read; return (status word, ERROR field) once it settles.

        Settled means VALID (the flow is done) or a non-SUCCESS ERROR. The
        bound turns a read that never settles into a named failure.
        """
        await self.abr.wr32(ctrl, KV_READ_EN)
        st = 0
        for _ in range(_KV_STATUS_POLLS):
            st = await self.abr.rd32(status)
            err = kv_status_field(st, "ERROR")
            if kv_status_field(st, "VALID") or err != KV_SUCCESS:
                return st, err
            await ClockCycles(cocotb.top.clk_i, 20)
        raise AssertionError(
            f"{what}: KV read neither completed nor failed in {_KV_STATUS_POLLS} polls "
            f"(status 0x{st:08x})"
        )

    def _kv_ok(self, st: int, err: int, *, chk: str) -> None:
        assert err == KV_SUCCESS and kv_status_field(st, "VALID") == 1, (
            f"{chk} FAIL: KV read of a delivered seed did not complete cleanly: status "
            f"0x{st:08x} ERROR={err} (SUCCESS={KV_SUCCESS})"
        )

    async def _mldsa_keygen(self, seed_words: list[int] | None, *, what: str) -> list[int]:
        await self._abr_wait(
            self.abr, ABR_STATUS, ST_ERROR, ST_READY, ST_READY, what=f"{what} pre-command READY"
        )
        if seed_words is not None:
            await self.abr.write_word_pairs(ABR_SEED, seed_words)
        await self.abr.write_word_pairs(ABR_ENTROPY, self.walk.abr_entropy)
        await self.abr.wr32(ABR_CTRL, CMD_KEYGEN)
        st = await self._abr_wait(
            self.abr, ABR_STATUS, ST_ERROR, ST_VALID, ST_VALID, what=f"{what} VALID"
        )
        assert (st & ST_ERROR) == 0, f"{what}: VALID with ERROR (0x{st:08x})"
        pk = await self.abr.read_word_pairs(ABR_PUBKEY, PK_WORDS)
        assert any(w != 0 for w in pk), f"{what} FAIL: the public key is all zero"
        return pk

    async def _mlkem_keygen(
        self, d: list[int] | None, z: list[int] | None, *, what: str
    ) -> list[int]:
        await self._abr_wait(
            self.kem,
            MLKEM_STATUS,
            KEM_ST_ERROR,
            KEM_ST_READY,
            KEM_ST_READY,
            what=f"{what} pre-command READY",
        )
        if d is not None:
            await self.kem.write_word_pairs(MLKEM_SEED_D, d)
        if z is not None:
            await self.kem.write_word_pairs(MLKEM_SEED_Z, z)
        await self.kem.wr32(MLKEM_CTRL, KEM_CMD_KEYGEN)
        st = await self._abr_wait(
            self.kem, MLKEM_STATUS, KEM_ST_ERROR, KEM_ST_VALID, KEM_ST_VALID, what=f"{what} VALID"
        )
        assert (st & KEM_ST_ERROR) == 0, f"{what}: VALID with ERROR (0x{st:08x})"
        ek = await self.kem.read_word_pairs(MLKEM_ENCAPS_KEY, KEM_EK_WORDS)
        assert any(w != 0 for w in ek), f"{what} FAIL: the encapsulation key is all zero"
        return ek

    async def _mlkem_encaps(self, ek: list[int], msg: list[int] | None, *, what: str) -> list[int]:
        await self._abr_wait(
            self.kem,
            MLKEM_STATUS,
            KEM_ST_ERROR,
            KEM_ST_READY,
            KEM_ST_READY,
            what=f"{what} pre-command READY",
        )
        await self.kem.write_word_pairs(MLKEM_ENCAPS_KEY, ek)
        if msg is not None:
            await self.kem.write_word_pairs(MLKEM_MSG, msg)
        await self.kem.wr32(MLKEM_CTRL, KEM_CMD_ENCAPS)
        st = await self._abr_wait(
            self.kem, MLKEM_STATUS, KEM_ST_ERROR, KEM_ST_VALID, KEM_ST_VALID, what=f"{what} VALID"
        )
        assert (st & KEM_ST_ERROR) == 0, f"{what}: VALID with ERROR (0x{st:08x})"
        ct = await self.kem.read_word_pairs(MLKEM_CIPHERTEXT, KEM_CT_WORDS)
        assert any(w != 0 for w in ct), f"{what} FAIL: the ciphertext is all zero"
        return ct

    def _seed_z_probe(self) -> list[int]:
        """The eight Z words the ABR engine holds, word i at bits [32*i +: 32]."""
        v = self.rd_known(cocotb.top.abr_mlkem_seed_z_probe_o)
        return [(v >> (32 * i)) & 0xFFFF_FFFF for i in range(DEST_WORDS[KM_DEST_ABR_MLKEM_SEED_Z])]

    @staticmethod
    def _same(got: list[int], exp: list[int], *, chk: str, what: str) -> None:
        assert len(got) == len(exp), f"{chk} FAIL: {what} is {len(got)} words, expected {len(exp)}"
        bad = diff_words(got, exp)
        assert not bad, (
            f"{chk} FAIL: {what} differs at words {bad} of {len(exp)}: "
            f"got_sha={word_digest(got)} exp_sha={word_digest(exp)}"
        )

    # ------------------------------------------------------------- rounds --
    async def _transfer(self, r: int, handle: int, dest: int) -> None:
        rc, arg = await self.km.key_transfer(handle=handle, dest=dest)
        assert rc == KM_RC_SUCCESS, (
            f"precondition FAIL (round {r + 1}): CMD_KEY_TRANSFER dest=0x{dest:02x} "
            f"({DEST_NAME[dest]}) rc={rc}"
        )
        assert (arg & 0xFF) == handle and ((arg >> 8) & 0xFF) == dest, (
            f"precondition FAIL (round {r + 1}): RETURN_ARG 0x{arg:08x} does not echo "
            f"handle 0x{handle:02x} and dest 0x{dest:02x}"
        )

    async def _load_all(self, r: int) -> None:
        self.handles[r] = {}
        bus = _KeyPortWrites(self)
        bus.start()
        for dest in DEST_WORDS:
            words = self.walk.keys[r][dest]
            handle = await self.km.key_load(key_words=list(words), dest=dest)
            self.handles[r][dest] = handle
            await self._transfer(r, handle, dest)
        await bus.stop()
        if r == 0:
            self.round1_aw = (bus.counts(), bus.xz)
        self.logger.info(
            "STEP round %d: CMD_KEY_LOAD + CMD_KEY_TRANSFER rc=0 for all %d destinations",
            r + 1,
            len(DEST_WORDS),
        )

    async def _consume(self, r: int) -> dict[str, list[int]]:
        keys = self.walk.keys[r]
        tag = r + 1
        out: dict[str, list[int]] = {}

        # AES: ECB-256 encrypt with the delivered key selected.
        golden = aes256_ecb_encrypt_words(keys[KM_DEST_AES], self.walk.aes_pt)
        await self.aes.configure_ecb_enc_256(sideload=True)
        await self.aes.trigger_prng_reseed()
        ct = await self.aes.run_ecb_block(list(self.walk.aes_pt))
        assert ct == golden, (
            f"CHK-AES-{tag} FAIL: ct={[hex(w) for w in ct]} golden={[hex(w) for w in golden]}"
        )
        self.logger.info(
            "CHK-AES-%d PASS: ct == AES-256(K, PT) golden ct=%s k_sha=%s",
            tag,
            [hex(w) for w in ct],
            word_digest(keys[KM_DEST_AES]),
        )
        out["aes"] = ct

        # HMAC: a different software key sits in the KEY CSRs; the delivered
        # key wins while KEY_VALID is set.
        await self.hmac.write_key(self.walk.hmac_sw[r])
        await self.hmac.configure_keyed_256()
        digest = await self.hmac.run_keyed_mac(list(self.walk.hmac_msg))
        golden = hmac_sha256_words(keys[KM_DEST_HMAC], self.walk.hmac_msg)
        assert digest == golden, (
            f"CHK-HMAC-{tag} FAIL: digest={[hex(w) for w in digest]} "
            f"golden={[hex(w) for w in golden]}"
        )
        self.logger.info(
            "CHK-HMAC-%d PASS: digest == HMAC-SHA256(K, msg) golden d[0]=0x%08x d[7]=0x%08x "
            "k_sha=%s sw_key_sha=%s",
            tag,
            digest[0],
            digest[7],
            word_digest(keys[KM_DEST_HMAC]),
            word_digest(self.walk.hmac_sw[r]),
        )
        out["hmac"] = digest

        # KMAC: keyed KMAC256 on the delivered key.
        digest = await self.kmac.keyed_mac(list(self.walk.kmac_msg), sideload=True)
        golden = kmac_family_words(
            "kmac", 256, list(self.walk.kmac_msg), len(digest) * 4, key_words=keys[KM_DEST_KMAC]
        )
        assert digest == golden, (
            f"CHK-KMAC-{tag} FAIL: digest={[hex(w) for w in digest]} "
            f"golden={[hex(w) for w in golden]}"
        )
        self.logger.info(
            "CHK-KMAC-%d PASS: digest == KMAC256(K, msg) golden d[0]=0x%08x d[7]=0x%08x k_sha=%s",
            tag,
            digest[0],
            digest[7],
            word_digest(keys[KM_DEST_KMAC]),
        )
        out["kmac"] = digest

        # OTBN: the key-dump program reads both key shares from the sideload WSRs.
        await self.otbn.execute()
        errbits = await self.otbn.read_errbits()
        assert errbits == 0, f"CHK-OTBN-{tag} FAIL: ERR_BITS=0x{errbits:08x}"
        key, s0, s1, pad = await self.otbn.read_keydump_outputs()
        exp = keys[KM_DEST_OTBN]
        assert key == exp, (
            f"CHK-OTBN-{tag} FAIL: key differs at words {diff_words(key, exp)}: "
            f"key_sha={word_digest(key)} exp_sha={word_digest(exp)}"
        )
        assert [a ^ b for a, b in zip(s0, s1)] == exp, f"CHK-OTBN-{tag} FAIL: share0^share1 != K"
        assert all(w == 0 for w in pad), (
            f"CHK-OTBN-{tag} FAIL: pad nonzero at words {[i for i, w in enumerate(pad) if w]}"
        )
        self.logger.info(
            "CHK-OTBN-%d PASS: DMEM key == K (12 words), share0^share1 == K, ERR_BITS=0x%08x "
            "key_sha=%s s0_sha=%s s1_sha=%s",
            tag,
            errbits,
            word_digest(key),
            word_digest(s0),
            word_digest(s1),
        )
        out["otbn"] = key
        self.insn_live[r] = await self.otbn._rd(OTBN_ADDR_INSN_CNT) & OTBN_INSN_CNT_MASK

        # ABR ML-DSA seed: KV leg first, then the direct-seed reference.
        seed = keys[KM_DEST_ABR_MLDSA_SEED]
        await self._zeroize_obs(self._mldsa_zeroize, tag=tag, site=f"CHK-MLDSA-{tag} pre-KV")
        st, err = await self._kv_read(
            ABR_MLDSA_KV_RD_SEED_CTRL, ABR_MLDSA_KV_RD_SEED_STATUS, what=f"CHK-MLDSA-{tag}"
        )
        self._kv_ok(st, err, chk=f"CHK-MLDSA-{tag}")
        pk_kv = await self._mldsa_keygen(None, what=f"CHK-MLDSA-{tag} KV")
        await self._zeroize_obs(self._mldsa_zeroize, tag=tag, site=f"CHK-MLDSA-{tag} pre-ref")
        pk_ref = await self._mldsa_keygen(seed, what=f"CHK-MLDSA-{tag} ref")
        self._same(pk_kv, pk_ref, chk=f"CHK-MLDSA-{tag}", what="the KV-seed public key")
        self.logger.info(
            "CHK-MLDSA-%d PASS: KV seed read status 0x%08x; KEYGEN PK == direct-seed PK "
            "(%d words, pk[0]=0x%08x)",
            tag,
            st,
            PK_WORDS,
            pk_kv[0],
        )
        out["mldsa"] = pk_kv

        # ABR ML-KEM seed D||Z: KV leg first, then the direct-seed reference.
        d = keys[KM_DEST_ABR_MLKEM_SEED_D]
        z = keys[KM_DEST_ABR_MLKEM_SEED_Z]
        await self._zeroize_obs(self._mlkem_zeroize, tag=tag, site=f"CHK-MLKEM-SEED-{tag} pre-KV")
        st, err = await self._kv_read(
            MLKEM_KV_SEED_RD_CTRL, MLKEM_KV_SEED_RD_STATUS, what=f"CHK-MLKEM-SEED-{tag}"
        )
        self._kv_ok(st, err, chk=f"CHK-MLKEM-SEED-{tag}")
        z_kv = self._seed_z_probe()
        ek_kv = await self._mlkem_keygen(None, None, what=f"CHK-MLKEM-SEED-{tag} KV")
        await self._zeroize_obs(self._mlkem_zeroize, tag=tag, site=f"CHK-MLKEM-SEED-{tag} pre-ref")
        ek_ref = await self._mlkem_keygen(d, z, what=f"CHK-MLKEM-SEED-{tag} ref")
        self._same(ek_kv, ek_ref, chk=f"CHK-MLKEM-SEED-{tag}", what="the KV-seed encaps key")
        # Word i of the delivered Z must sit at engine index i.
        self._same(
            z_kv,
            z,
            chk=f"CHK-MLKEM-SEED-{tag}",
            what="the engine's Z after the KV read (the encapsulation key matched)",
        )
        self.logger.info(
            "CHK-MLKEM-SEED-%d PASS: KV seed read status 0x%08x; EK == direct-seed EK "
            "(%d words, ek[0]=0x%08x); engine Z == delivered Z z_sha=%s",
            tag,
            st,
            KEM_EK_WORDS,
            ek_kv[0],
            word_digest(z_kv),
        )
        out["mlkem_seed"] = ek_kv

        # ABR ML-KEM message: KV leg first, then the direct-message reference.
        msg = keys[KM_DEST_ABR_MLKEM_MSG]
        await self._zeroize_obs(self._mlkem_zeroize, tag=tag, site=f"CHK-MLKEM-MSG-{tag} pre-KV")
        st, err = await self._kv_read(
            MLKEM_KV_MSG_RD_CTRL, MLKEM_KV_MSG_RD_STATUS, what=f"CHK-MLKEM-MSG-{tag}"
        )
        self._kv_ok(st, err, chk=f"CHK-MLKEM-MSG-{tag}")
        ct_kv = await self._mlkem_encaps(ek_ref, None, what=f"CHK-MLKEM-MSG-{tag} KV")
        await self._zeroize_obs(self._mlkem_zeroize, tag=tag, site=f"CHK-MLKEM-MSG-{tag} pre-ref")
        ct_ref = await self._mlkem_encaps(ek_ref, msg, what=f"CHK-MLKEM-MSG-{tag} ref")
        self._same(ct_kv, ct_ref, chk=f"CHK-MLKEM-MSG-{tag}", what="the KV-message ciphertext")
        self.logger.info(
            "CHK-MLKEM-MSG-%d PASS: KV message read status 0x%08x; CT == direct-message CT "
            "(%d words, ct[0]=0x%08x)",
            tag,
            st,
            KEM_CT_WORDS,
            ct_kv[0],
        )
        out["mlkem_msg"] = ct_kv
        return out

    async def _shred(self, r: int, dest: int = ALL_DESTS) -> None:
        rc, arg = await self.km.engine_shred(dest=dest)
        assert rc == KM_RC_SUCCESS, f"precondition FAIL (round {r + 1}): CMD_ENGINE_SHRED rc={rc}"
        assert (arg & 0xFF) == dest, (
            f"precondition FAIL (round {r + 1}): CMD_ENGINE_SHRED echoed dest "
            f"0x{arg & 0xFF:02x}, requested 0x{dest:02x}"
        )
        self.logger.info("STEP round %d: CMD_ENGINE_SHRED dest=0x%02x rc=0", r + 1, dest)

    async def _cleared(self, r: int) -> None:
        tag = r + 1

        # HMAC with KEY_VALID clear takes its software key registers.
        sw = self.walk.hmac_sw[r]
        digest = await self.hmac.run_keyed_mac(list(self.walk.hmac_msg))
        golden_sw = hmac_sha256_words(sw, self.walk.hmac_msg, key_word_rev=False, key_be=True)
        golden_k = hmac_sha256_words(self.walk.keys[r][KM_DEST_HMAC], self.walk.hmac_msg)
        assert golden_sw != golden_k, "test construction error: SW key golden == delivered golden"
        assert digest == golden_sw, (
            f"CHK-HMAC-CLR-{tag} FAIL: after the shred the digest is not HMAC-SHA256 of the "
            f"software key, so KEY_VALID did not clear: digest={[hex(w) for w in digest]} "
            f"sw_golden={[hex(w) for w in golden_sw]}"
            + (" (equals the delivered-key golden)" if digest == golden_k else "")
        )
        self.logger.info(
            "CHK-HMAC-CLR-%d PASS: digest == HMAC-SHA256(SW key, msg) golden d[0]=0x%08x; "
            "delivered-key golden d[0]=0x%08x",
            tag,
            digest[0],
            golden_k[0],
        )

        # OTBN: reading a share whose key is not valid sets KEY_INVALID.
        await self.otbn.execute()
        errbits = await self.otbn.read_errbits()
        assert errbits == OTBN_ERR_KEY_INVALID, (
            f"CHK-OTBN-CLR-{tag} FAIL: ERR_BITS=0x{errbits:08x} after the shred, expected "
            f"KEY_INVALID only (0x{OTBN_ERR_KEY_INVALID:08x})"
        )
        self.logger.info("CHK-OTBN-CLR-%d PASS: ERR_BITS=0x%08x (KEY_INVALID)", tag, errbits)
        await self._otbn_s1_first(r)

        # ABR: every KV read on a shredded block reports a failed read flow.
        legs = (
            (
                "ML-DSA seed",
                ABR_MLDSA_KV_RD_SEED_CTRL,
                ABR_MLDSA_KV_RD_SEED_STATUS,
                self._mldsa_zeroize,
            ),
            (
                "ML-KEM seed",
                MLKEM_KV_SEED_RD_CTRL,
                MLKEM_KV_SEED_RD_STATUS,
                self._mlkem_zeroize,
            ),
            (
                "ML-KEM msg",
                MLKEM_KV_MSG_RD_CTRL,
                MLKEM_KV_MSG_RD_STATUS,
                self._mlkem_zeroize,
            ),
        )
        for name, ctrl, status, zeroize in legs:
            await zeroize(what=f"CHK-ABR-CLR-{tag} {name} pre")
            st, err = await self._kv_read(ctrl, status, what=f"CHK-ABR-CLR-{tag} {name}")
            assert err == KV_READ_FAIL, (
                f"CHK-ABR-CLR-{tag} FAIL: {name} KV read after the shred reports ERROR={err} "
                f"(status 0x{st:08x}), expected KV_READ_FAIL={KV_READ_FAIL}"
            )
            self.logger.info(
                "CHK-ABR-CLR-%d PASS: %s KV read on the shredded block: status 0x%08x "
                "(ERROR=KV_READ_FAIL)",
                tag,
                name,
                st,
            )
            self._obs_clr_valid(tag, name, st)

        # D and Z one at a time: deliver one of them again, so the D||Z read
        # can only fail on the other one's KEY_VALID. Then deliver the other one
        # too and require the read to complete: that is the control that the
        # first delivery made its half valid again, so the failure belongs to
        # the shredded half and not to a re-transfer that set nothing.
        for again, other, other_dest in (
            (KM_DEST_ABR_MLKEM_SEED_D, "Z", KM_DEST_ABR_MLKEM_SEED_Z),
            (KM_DEST_ABR_MLKEM_SEED_Z, "D", KM_DEST_ABR_MLKEM_SEED_D),
        ):
            if again == KM_DEST_ABR_MLKEM_SEED_Z:
                # Only D and Z are valid here; the other six are still shredded.
                await self._shred(r, MLKEM_SEED_DESTS)
            await self._transfer(r, self.handles[r][again], again)
            await self._mlkem_zeroize(what=f"CHK-ABR-CLR-{tag} only {DEST_NAME[again]} pre")
            st, err = await self._kv_read(
                MLKEM_KV_SEED_RD_CTRL,
                MLKEM_KV_SEED_RD_STATUS,
                what=f"CHK-ABR-CLR-{tag} only {DEST_NAME[again]}",
            )
            assert err == KV_READ_FAIL, (
                f"CHK-ABR-CLR-{tag} FAIL: with only {DEST_NAME[again]} delivered again after "
                f"the shred, the D||Z KV read reports ERROR={err} (status 0x{st:08x}), "
                f"expected KV_READ_FAIL={KV_READ_FAIL}: the shred left {other} KEY_VALID set"
            )
            self._obs_clr_valid(tag, f"only {DEST_NAME[again]}", st)
            await self._mlkem_zeroize(what=f"CHK-ABR-CLR-{tag} only {DEST_NAME[again]} recover")
            await self._transfer(r, self.handles[r][other_dest], other_dest)
            st_ok, err_ok = await self._kv_read(
                MLKEM_KV_SEED_RD_CTRL,
                MLKEM_KV_SEED_RD_STATUS,
                what=f"CHK-ABR-CLR-{tag} {DEST_NAME[again]} then {DEST_NAME[other_dest]}",
            )
            assert err_ok == KV_SUCCESS and kv_status_field(st_ok, "VALID") == 1, (
                f"CHK-ABR-CLR-{tag} FAIL: with {DEST_NAME[again]} and then "
                f"{DEST_NAME[other_dest]} delivered again, the D||Z KV read did not complete "
                f"(status 0x{st_ok:08x} ERROR={err_ok}): the {DEST_NAME[again]} delivery did "
                "not make its half valid, so the failed read above is not attributable to "
                f"the shredded {other}"
            )
            self.logger.info(
                "CHK-ABR-CLR-%d PASS: only %s delivered again, D||Z KV read status 0x%08x "
                "(ERROR=KV_READ_FAIL): the shred cleared %s; with %s delivered too the read "
                "completes, status 0x%08x (VALID, ERROR=SUCCESS)",
                tag,
                DEST_NAME[again],
                st,
                other,
                DEST_NAME[other_dest],
                st_ok,
            )
        # Leave every destination shredded, as the round expects.
        await self._shred(r, MLKEM_SEED_DESTS)

    async def _otbn_s1_first(self, r: int) -> None:
        """CHK-OTBN-KEY-S1-SHRED: a share-1-first read of the shredded key stops at once."""
        tag = r + 1
        live = self.insn_live[r]
        if live == 0:
            raise AssertionError(
                f"CHK-OTBN-KEY-S1-SHRED FAIL: r={tag} INSN_CNT read 0 after the completed "
                "key-dump run of CHK-OTBN, so INSN_CNT = 0 below would not show a stop"
            )
        await self.otbn.load_program(prog=OTBN_KEYDUMP_S1_FIRST_PROG)
        await self.otbn._wr(OTBN_ADDR_ERRBIT, 0)
        err_pre = await self.otbn.read_errbits()
        if err_pre != 0:
            raise AssertionError(
                f"CHK-OTBN-KEY-S1-SHRED FAIL: r={tag} ERR_BITS reads 0x{err_pre:08x} after "
                "the clear, so a KEY_INVALID read later would not belong to this run"
            )
        await self.otbn.execute()
        errbits = await self.otbn.read_errbits()
        insn = await self.otbn._rd(OTBN_ADDR_INSN_CNT) & OTBN_INSN_CNT_MASK
        line = (
            f"r={tag} first_read=KEY_S1_L err_bits_pre=0x{err_pre:x} err_bits=0x{errbits:08x} "
            f"expect_err_bits=0x{OTBN_ERR_KEY_INVALID:08x} insn_cnt={insn} expect_insn_cnt=0 "
            f"insn_cnt_after_completed_run={live}"
        )
        if errbits != OTBN_ERR_KEY_INVALID or insn != 0:
            raise AssertionError(f"CHK-OTBN-KEY-S1-SHRED FAIL: {line}")
        self.logger.info("CHK-OTBN-KEY-S1-SHRED PASS: %s", line)
        await self.otbn.load_program()

    async def _cleared_final(self) -> None:
        # Baseline: kmac_err and ERR_CODE clear after programming and just
        # before CMD_START, so an error read after the start comes from the
        # start on the shredded key.
        await self.kmac.program_sideload_keyed()
        err0 = await self.kmac._rd(KMAC_ERR_CODE)
        intr0 = await self.kmac._rd(KMAC_INTR_STATE)
        assert err0 == 0 and (intr0 & KMAC_INTR_KMAC_ERR) == 0, (
            f"CHK-KMAC-CLR FAIL: before CMD_START ERR_CODE 0x{err0:08x} and INTR_STATE "
            f"0x{intr0:08x}; kmac_err or ERR_CODE is already set, so an error after the "
            "start would not belong to the shredded key"
        )
        intr, err = await self.kmac.start_poll_err(_KMAC_ERR_POLLS)
        assert intr & KMAC_INTR_KMAC_ERR, (
            f"CHK-KMAC-CLR FAIL: a keyed KMAC on the shredded delivered key raised no "
            f"kmac_err in {_KMAC_ERR_POLLS} polls (INTR_STATE 0x{intr:08x})"
        )
        code = (err >> KMAC_ERR_CODE_SHIFT) & 0xFF
        assert code == KMAC_ERR_KEY_NOT_VALID, (
            f"CHK-KMAC-CLR FAIL: kmac_err set with error code 0x{code:02x} "
            f"(ERR_CODE 0x{err:08x}), expected KeyNotValid 0x{KMAC_ERR_KEY_NOT_VALID:02x}"
        )
        self.logger.info(
            "CHK-KMAC-CLR PASS: before CMD_START INTR_STATE 0x%08x ERR_CODE 0x%08x "
            "(kmac_err clear); after it INTR_STATE 0x%08x (kmac_err), ERR_CODE 0x%08x "
            "(code 0x%02x KeyNotValid)",
            intr0,
            err0,
            intr,
            err,
            code,
        )

        await self.aes.configure_ecb_enc_256(sideload=True)
        await self.aes.trigger_prng_reseed()
        await self.aes.start_block_no_wait(list(self.walk.aes_pt))
        produced = await self.aes.output_valid_within(_AES_REFUSE_POLLS)
        status = await self.aes._rd(AES_STATUS)
        assert not produced, (
            "CHK-AES-CLR FAIL: AES produced output with sideload selected and its key "
            f"shredded (STATUS 0x{status:08x})"
        )
        self.logger.info(
            "CHK-AES-CLR PASS: no AES output in %d polls with the key shredded, "
            "STATUS 0x%08x (output_valid=%d)",
            _AES_REFUSE_POLLS,
            status,
            (status >> AES_STATUS_OUTPUT_VALID) & 1,
        )

    async def _short_key(self) -> None:
        """OTBN delivery of a key shorter than the 12-word share width."""
        n_full = DEST_WORDS[KM_DEST_OTBN]
        rng = SepSeededRng(self.walk.seed ^ _SHORT_KEY_SALT)
        n = rng.randrange(1, n_full)
        key = _distinct_words(rng, n, None)
        self.logger.info("INFO-XFER-SHORT-KEY n=%d", n)
        handle = await self.km.key_load(key_words=list(key), dest=KM_DEST_OTBN)
        bus = _KeyPortWrites(self)
        bus.start()
        await self._transfer(ROUNDS, handle, KM_DEST_OTBN)
        await bus.stop()
        offsets = bus.port_offsets(_OTBN_KEY_PORT)
        await self.otbn.execute()
        errbits = await self.otbn.read_errbits()
        _, s0, s1, _ = await self.otbn.read_keydump_outputs()
        got = [a ^ b for a, b in zip(s0, s1)]
        bad = [i for i in range(n) if got[i] != key[i]]
        shares = [o for o in offsets if o in OTBN_SHARE_OFFSETS]
        repeated = sorted({o for o in shares if shares.count(o) > 1})
        missing = sorted(OTBN_SHARE_OFFSETS - set(shares))
        line = (
            f"contract=key_manager/doc/firmware.adoc:1805-1808 n={n} "
            f"key_match={n - len(bad)}/{n} bad_words={bad} err_bits=0x{errbits:x} "
            f"share_writes={len(shares)} expect_share_writes={len(OTBN_SHARE_OFFSETS)} "
            f"repeated={[hex(o) for o in repeated]} missing={[hex(o) for o in missing]} "
            f"aw_xz_clocks={bus.xz}"
        )
        if errbits != 0 or got[:n] != key or repeated or missing or bus.xz:
            raise AssertionError(f"CHK-XFER-SHORT-KEY FAIL: {line}")
        self.logger.info("CHK-XFER-SHORT-KEY PASS: %s", line)
        set_open_value_leg_pass("km_xfer_short_key", self.logger)
        await ClockCycles(cocotb.top.clk_i, 2)
        set_open_value_leg_pass(None, self.logger)
        self.logger.info(
            "OBS-XFER-PAD n=%d pad_sha=%s nonzero=%s",
            n,
            word_digest(got[n:]),
            [i for i in range(n, n_full) if got[i]],
        )

    async def _load_flow(self, words: list[int], dest: int) -> int:
        """CMD_KEY_LOAD, each word written only while ``inbound_full`` reads 0.

        A frame longer than the 16-word inbound FIFO gets SLVERR on overflow
        (SEP_CTRL.inbound_overflow_resp resets to 0), so the writer waits for room.
        """
        seq = self.km.seq_num
        frame = self.km.build_frame(KM_CMD_KEY_LOAD, seq, [len(words) - 1, dest, *words])
        for i, word in enumerate(frame):
            for _ in range(_INBOUND_POLLS):
                if not (await self.km._status() >> KM_STATUS_INBOUND_FULL) & 1:
                    break
                await ClockCycles(cocotb.top.clk_i, _INBOUND_POLL_GAP)
            else:
                raise AssertionError(
                    f"CMD_KEY_LOAD: SEP_STATUS.inbound_full stayed 1 for {_INBOUND_POLLS} "
                    f"polls at word {i} of {len(frame)}"
                )
            if i == len(frame) - 1:
                await self.km._wr(KM_MBOX_WRITE_SEPARATOR, 1)
            await self.km._wr(KM_MBOX_WRITE_DATA, word)
        self.km.seq_num = (self.km.seq_num + 1) & 0xFF
        rc, arg = await self.km.recv_resp_cmd(KM_CMD_KEY_LOAD, seq)
        handle = arg & 0xFF
        if rc != KM_RC_SUCCESS or handle == 0:
            raise AssertionError(
                f"precondition FAIL: CMD_KEY_LOAD of {len(words)} words dest=0x{dest:02x} "
                f"rc={rc} handle=0x{handle:02x}"
            )
        await self.km.check_outbound_empty("POST-KEY-LOAD")
        return handle

    async def _long_key(self) -> None:
        """OTBN delivery of a key longer than the 12-word share width."""
        n_full = DEST_WORDS[KM_DEST_OTBN]
        rng = SepSeededRng(self.walk.seed ^ _LONG_KEY_SALT)
        n = rng.randrange(n_full + 1, _KEY_WORDS_MAX + 1)
        head = _distinct_words(rng, n_full, None)
        tail = []
        for _ in range(n - n_full):
            w = rng.getrandbits(32)
            while w == 0 or w in head:
                w = rng.getrandbits(32)
            tail.append(w)
        key = head + tail
        self.logger.info("INFO-XFER-LONG-KEY n=%d key_sha=%s", n, word_digest(key))
        handle = await self._load_flow(key, KM_DEST_OTBN)
        bus = _KeyPortWrites(self)
        bus.start()
        rc, arg = await self.km.key_transfer(handle=handle, dest=KM_DEST_OTBN)
        await bus.stop()
        await self.otbn.execute()
        errbits = await self.otbn.read_errbits()
        _, s0, s1, _ = await self.otbn.read_keydump_outputs()
        got = [a ^ b for a, b in zip(s0, s1)]
        exp = key[:n_full]
        bad = diff_words(got, exp) if len(got) == len(exp) else list(range(n_full))
        counts = bus.counts()
        shares = [o for o in bus.port_offsets(_OTBN_KEY_PORT) if o in OTBN_SHARE_OFFSETS]
        repeated = sorted({o for o in shares if shares.count(o) > 1})
        missing = sorted(OTBN_SHARE_OFFSETS - set(shares))
        others = {
            _KEY_PORT_NAME[p]: counts[p] for p in range(len(_KEY_PORT_NAME)) if p != _OTBN_KEY_PORT
        }
        live_counts, live_xz = self.round1_aw
        silent = [
            name
            for p, name in enumerate(_KEY_PORT_NAME)
            if p >= len(live_counts) or not live_counts[p]
        ]
        line = (
            f"contract=key_manager/doc/firmware.adoc:1810-1811,1945-1947 n={n} rc={rc} "
            f"arg=0x{arg:08x} key_match={n_full - len(bad)}/{n_full} bad_words={bad} "
            f"err_bits=0x{errbits:x} share_writes={len(shares)} "
            f"expect_share_writes={len(OTBN_SHARE_OFFSETS)} "
            f"repeated={[hex(o) for o in repeated]} missing={[hex(o) for o in missing]} "
            f"aw_other_ports={others} aw_xz_clocks={bus.xz} "
            f"round1_aw_counts={dict(zip(_KEY_PORT_NAME, live_counts))} "
            f"round1_aw_xz_clocks={live_xz} round1_silent_ports={silent}"
        )
        if (
            rc != KM_RC_SUCCESS
            or errbits != 0
            or bad
            or repeated
            or missing
            or any(others.values())
            or bus.xz
            or silent
            or live_xz
        ):
            raise AssertionError(f"CHK-XFER-LONG-KEY FAIL: {line}")
        self.logger.info("CHK-XFER-LONG-KEY PASS: %s", line)

    async def _cmd_raw(self, cmd_id: int, payload: list[int]) -> tuple[int, int | None]:
        """Send one command; return (code, argument or None when the frame has none)."""
        seq = await self.km.send_command(cmd_id, payload)
        words = await self.km.recv_frame()
        resp_id = (words[0] >> 8) & 0xFF
        plen = (words[0] >> 16) & 0xFF
        if resp_id != KM_RESP_CMD or plen < 3:
            raise AssertionError(
                f"command 0x{cmd_id:02x}: expected RESP_CMD with 3 or more payload words, "
                f"got frame {[hex(w) for w in words]}"
            )
        if (words[1] & 0xFF) != seq or (words[2] & 0xFF) != cmd_id:
            raise AssertionError(
                f"command 0x{cmd_id:02x} seq {seq}: RESP_CMD echoes seq {words[1] & 0xFF} "
                f"id 0x{words[2] & 0xFF:02x}"
            )
        raw = words[3] & 0xFF
        code = raw - 256 if raw >= 128 else raw
        arg = words[4] if plen >= 4 else None
        await self.km.check_outbound_empty(f"POST-CMD-0x{cmd_id:02x}")
        return code, arg

    async def _aes_sideload_ct(self) -> list[int]:
        await self.aes.configure_ecb_enc_256(sideload=True)
        await self.aes.trigger_prng_reseed()
        return await self.aes.run_ecb_block(list(self.walk.aes_pt))

    async def _refuse_keep(self) -> None:
        """CHK-REFUSE-KEEP: a transfer that names one disallowed engine writes nothing."""
        k1 = self.walk.keys[0]
        rng = SepSeededRng(self.walk.seed ^ _REFUSE_SALT)
        k2 = []
        for i in range(DEST_WORDS[KM_DEST_AES]):
            w = rng.getrandbits(32)
            while w in (0, k1[KM_DEST_AES][i], k1[KM_DEST_HMAC][i]):
                w = rng.getrandbits(32)
            k2.append(w)
        pt, msg = self.walk.aes_pt, self.walk.hmac_msg
        aes_k1 = aes256_ecb_encrypt_words(k1[KM_DEST_AES], pt)
        aes_k2 = aes256_ecb_encrypt_words(k2, pt)
        hmac_k1 = hmac_sha256_words(k1[KM_DEST_HMAC], msg)
        hmac_k2 = hmac_sha256_words(k2, msg)
        assert aes_k1 != aes_k2 and hmac_k1 != hmac_k2, (
            "test construction error: the K2 goldens equal the K1 goldens"
        )
        allowed = KM_DEST_AES | KM_DEST_HMAC
        mask = allowed | KM_DEST_OTBN
        handle = await self.km.key_load(key_words=list(k2), dest=allowed)

        valid_pre = await self._km_valid()
        bus = _KeyPortWrites(self)
        bus.start()
        rc, arg = await self._cmd_raw(KM_CMD_KEY_TRANSFER, [handle, mask])
        await bus.stop()
        valid_post = await self._km_valid()
        ct = await self._aes_sideload_ct()
        digest = await self.hmac.run_keyed_mac(list(msg))
        await self.otbn.execute()
        errbits = await self.otbn.read_errbits()
        key, _, _, _ = await self.otbn.read_keydump_outputs()
        line = (
            f"contract=key_manager/doc/firmware.adoc:497-500,908 dest_valid=0x{allowed:02x} "
            f"mask=0x{mask:02x} rc={rc} expect_rc={KM_RC_FAILURE} "
            f"arg={'none' if arg is None else f'0x{arg:08x}'} expect_arg=none "
            f"aw_counts={dict(zip(_KEY_PORT_NAME, bus.counts()))} aw_xz_clocks={bus.xz} "
            f"km_valid_pre=0x{valid_pre:02x} km_valid_post=0x{valid_post:02x} "
            f"aes_k1={ct == aes_k1} hmac_k1={digest == hmac_k1} otbn_err_bits=0x{errbits:x} "
            f"otbn_k1={key == k1[KM_DEST_OTBN]}"
        )
        if (
            rc != KM_RC_FAILURE
            or arg is not None
            or bus.writes
            or bus.xz
            or valid_post != valid_pre
            or ct != aes_k1
            or digest != hmac_k1
            or errbits != 0
            or key != k1[KM_DEST_OTBN]
        ):
            raise AssertionError(f"CHK-REFUSE-KEEP FAIL: refused transfer: {line}")

        # The same handle with only the permitted engines is delivered, so the
        # refusal above belongs to OTBN and the tap sees the AES and HMAC ports.
        bus.start()
        rc2, arg2 = await self._cmd_raw(KM_CMD_KEY_TRANSFER, [handle, allowed])
        await bus.stop()
        ct2 = await self._aes_sideload_ct()
        digest2 = await self.hmac.run_keyed_mac(list(msg))
        counts = bus.counts()
        live = (_AES_KEY_PORT, _HMAC_KEY_PORT)
        line2 = (
            f"mask=0x{allowed:02x} rc={rc2} arg={'none' if arg2 is None else f'0x{arg2:08x}'} "
            f"aw_counts={dict(zip(_KEY_PORT_NAME, counts))} aw_xz_clocks={bus.xz} "
            f"aes_k2={ct2 == aes_k2} hmac_k2={digest2 == hmac_k2}"
        )
        if (
            rc2 != KM_RC_SUCCESS
            or any(counts[p] == 0 for p in live)
            or any(c for p, c in enumerate(counts) if p not in live)
            or bus.xz
            or ct2 != aes_k2
            or digest2 != hmac_k2
        ):
            raise AssertionError(f"CHK-REFUSE-KEEP FAIL: permitted transfer: {line2}")
        self.logger.info("CHK-REFUSE-KEEP PASS: refused: %s; permitted: %s", line, line2)

    # --------------------------------------------------------------- main --
    async def run_scenario(self) -> None:
        self.walk = SepKmShareWalkCfg(self.random_seed())
        self.handles: list[dict[int, int]] = [{} for _ in range(ROUNDS)]
        self.insn_live = [0] * ROUNDS
        self.round1_aw: tuple[list[int], int] = ([], 0)
        self.logger.info("RANDCFG: %s", self.walk.summary())

        image = self.select_efuse_image(lc_raw=0x1)  # LC_PROD
        self.write_efuse_image(image)
        await self.bring_up_no_cpu(park=("otbn", "aes", "hmac", "kmac"))

        # Checker and monitor summaries carry the retained evidence. Per-access
        # INFO records do not and dominate the log during the long mailbox waits.
        self.suppress_host_axi_transaction_info()

        self.km = SepKmMailbox(self)
        self.aes = SepAes(self)
        self.hmac = SepHmac(self)
        self.kmac = SepKmac(self)
        self.otbn = SepOtbn(self)
        self.abr = SepAbr(self)
        self.kem = SepAbrMlkem(self)

        await self.bring_up_entropy(
            strict=True,
            score_km="observe",
            score_sinks={"aes": "observe", "kmac": "observe", "otbn_urnd": "observe"},
        )
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.start_fifo_drain(log_batches=False)

        await self.swrst.release("km")
        await self.km.wait_km_ready()
        self.logger.info("STEP precondition: rom_main booted, RESP_KM_READY over the mailbox")

        # The wrapper key blocks sit in each engine's software-reset domain, so
        # every destination is released and idle before the first transfer.
        await self.swrst.release("aes", "hmac", "kmac", "otbn")
        await self.aes.wait_idle("post-release")
        await self.hmac.wait_idle("post-release")
        await self.kmac.wait_idle("post-release")
        await self.otbn.wait_idle("post-release")
        await self.otbn.load_program()

        outputs = []
        for r in range(ROUNDS):
            await self._load_all(r)
            outputs.append(await self._consume(r))
            if r == 0:
                await self._refuse_keep()
            await self._shred(r)
            await self._cleared(r)

        same = [name for name in ABR_OUTPUTS if outputs[1][name] == outputs[0][name]]
        assert not same, (
            f"CHK-ROUND FAIL: round-2 ABR output equals round 1 for {same} although every "
            "seed and message word changed: the engine does not use its input"
        )
        self.logger.info(
            "CHK-ROUND PASS: every ABR output differs between the rounds: %s",
            ", ".join(
                f"{n}[0]=0x{outputs[0][n][0]:08x}/0x{outputs[1][n][0]:08x}" for n in ABR_OUTPUTS
            ),
        )

        open_graded_window(TEST, self.logger)
        await self._short_key()
        await self._long_key()
        close_graded_window(self.logger)

        await self._cleared_final()

        await self.km.check_outbound_empty("EOT")
        await self.aes.check_status_clean("EOT")
        await self.hmac.check_status_clean("EOT")
        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        assert self.drbg_sb.report()
        self.logger.info("entropy alerts clear and DRBG scoreboard reports PASS")
