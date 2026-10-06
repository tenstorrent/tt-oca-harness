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
                is shown valid. The engine STATUS is logged, not graded: no SEP
                document states it
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
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_aes_golden import aes256_ecb_encrypt_words
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
    KM_DEST_ABR_MLDSA_SEED,
    KM_DEST_ABR_MLKEM_MSG,
    KM_DEST_ABR_MLKEM_SEED_D,
    KM_DEST_ABR_MLKEM_SEED_Z,
    KM_DEST_AES,
    KM_DEST_HMAC,
    KM_DEST_KMAC,
    KM_DEST_OTBN,
    KM_RC_SUCCESS,
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
from seq_lib.sep_otbn_seq import SepOtbn

ROUNDS = 2

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

# The consumer outputs CHK-ROUND compares. The other consumers have goldens.
ABR_OUTPUTS = ("mldsa", "mlkem_seed", "mlkem_msg")

AES_BLOCK_WORDS = 4
HMAC_MSG_WORDS = 8
KMAC_MSG_WORDS = 8

_POLL_ITERS = 20000
_POLL_GAP = 200
# Bounded windows for the cleared-state probes, in 20-cycle polls. A healthy
# engine answers a valid request in far fewer.
_KV_STATUS_POLLS = 2000
_KMAC_ERR_POLLS = 200
_AES_REFUSE_POLLS = 50


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
            f"{DEST_NAME[d]}[0]=0x{self.keys[0][d][0]:08x}/0x{self.keys[1][d][0]:08x}"
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
            await self.abr.write_words(ABR_SEED, seed_words)
        await self.abr.write_words(ABR_ENTROPY, self.walk.abr_entropy)
        await self.abr.wr32(ABR_CTRL, CMD_KEYGEN)
        st = await self._abr_wait(
            self.abr, ABR_STATUS, ST_ERROR, ST_VALID, ST_VALID, what=f"{what} VALID"
        )
        assert (st & ST_ERROR) == 0, f"{what}: VALID with ERROR (0x{st:08x})"
        pk = await self.abr.read_words(ABR_PUBKEY, PK_WORDS)
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
            await self.kem.write_words(MLKEM_SEED_D, d)
        if z is not None:
            await self.kem.write_words(MLKEM_SEED_Z, z)
        await self.kem.wr32(MLKEM_CTRL, KEM_CMD_KEYGEN)
        st = await self._abr_wait(
            self.kem, MLKEM_STATUS, KEM_ST_ERROR, KEM_ST_VALID, KEM_ST_VALID, what=f"{what} VALID"
        )
        assert (st & KEM_ST_ERROR) == 0, f"{what}: VALID with ERROR (0x{st:08x})"
        ek = await self.kem.read_words(MLKEM_ENCAPS_KEY, KEM_EK_WORDS)
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
        await self.kem.write_words(MLKEM_ENCAPS_KEY, ek)
        if msg is not None:
            await self.kem.write_words(MLKEM_MSG, msg)
        await self.kem.wr32(MLKEM_CTRL, KEM_CMD_ENCAPS)
        st = await self._abr_wait(
            self.kem, MLKEM_STATUS, KEM_ST_ERROR, KEM_ST_VALID, KEM_ST_VALID, what=f"{what} VALID"
        )
        assert (st & KEM_ST_ERROR) == 0, f"{what}: VALID with ERROR (0x{st:08x})"
        ct = await self.kem.read_words(MLKEM_CIPHERTEXT, KEM_CT_WORDS)
        assert any(w != 0 for w in ct), f"{what} FAIL: the ciphertext is all zero"
        return ct

    def _seed_z_probe(self) -> list[int]:
        """The eight Z words the ABR engine holds, word i at bits [32*i +: 32]."""
        v = self.rd_known(cocotb.top.abr_mlkem_seed_z_probe_o)
        return [(v >> (32 * i)) & 0xFFFF_FFFF for i in range(DEST_WORDS[KM_DEST_ABR_MLKEM_SEED_Z])]

    @staticmethod
    def _same(got: list[int], exp: list[int], *, chk: str, what: str) -> None:
        assert len(got) == len(exp), f"{chk} FAIL: {what} is {len(got)} words, expected {len(exp)}"
        bad = next((i for i, (g, e) in enumerate(zip(got, exp)) if g != e), None)
        assert bad is None, (
            f"{chk} FAIL: {what} differs at word {bad} of {len(exp)}: "
            f"got=0x{got[bad]:08x} exp=0x{exp[bad]:08x}"
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
        for dest in DEST_WORDS:
            words = self.walk.keys[r][dest]
            handle = await self.km.key_load(key_words=list(words), dest=dest)
            self.handles[r][dest] = handle
            await self._transfer(r, handle, dest)
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
            "CHK-AES-%d PASS: ct == AES-256(K, PT) golden ct=%s k[0]=0x%08x",
            tag,
            [hex(w) for w in ct],
            keys[KM_DEST_AES][0],
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
            "k[0]=0x%08x sw_key[0]=0x%08x",
            tag,
            digest[0],
            digest[7],
            keys[KM_DEST_HMAC][0],
            self.walk.hmac_sw[r][0],
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
            "CHK-KMAC-%d PASS: digest == KMAC256(K, msg) golden d[0]=0x%08x d[7]=0x%08x "
            "k[0]=0x%08x",
            tag,
            digest[0],
            digest[7],
            keys[KM_DEST_KMAC][0],
        )
        out["kmac"] = digest

        # OTBN: the key-dump program reads both key shares from the sideload WSRs.
        await self.otbn.load_program()
        await self.otbn.execute()
        errbits = await self.otbn.read_errbits()
        assert errbits == 0, f"CHK-OTBN-{tag} FAIL: ERR_BITS=0x{errbits:08x}"
        key, s0, s1, pad = await self.otbn.read_keydump_outputs()
        exp = keys[KM_DEST_OTBN]
        assert key == exp, (
            f"CHK-OTBN-{tag} FAIL: key={[hex(w) for w in key]} exp={[hex(w) for w in exp]}"
        )
        assert [a ^ b for a, b in zip(s0, s1)] == exp, f"CHK-OTBN-{tag} FAIL: share0^share1 != K"
        assert all(w == 0 for w in pad), f"CHK-OTBN-{tag} FAIL: pad={[hex(w) for w in pad]}"
        self.logger.info(
            "CHK-OTBN-%d PASS: DMEM key == K (12 words), share0^share1 == K, ERR_BITS=0x%08x "
            "key[0]=0x%08x key[11]=0x%08x s0[0]=0x%08x s1[0]=0x%08x",
            tag,
            errbits,
            key[0],
            key[11],
            s0[0],
            s1[0],
        )
        out["otbn"] = key

        # ABR ML-DSA seed: KV leg first, then the direct-seed reference.
        seed = keys[KM_DEST_ABR_MLDSA_SEED]
        await self._mldsa_zeroize(what=f"CHK-MLDSA-{tag} pre-KV")
        st, err = await self._kv_read(
            ABR_MLDSA_KV_RD_SEED_CTRL, ABR_MLDSA_KV_RD_SEED_STATUS, what=f"CHK-MLDSA-{tag}"
        )
        self._kv_ok(st, err, chk=f"CHK-MLDSA-{tag}")
        pk_kv = await self._mldsa_keygen(None, what=f"CHK-MLDSA-{tag} KV")
        await self._mldsa_zeroize(what=f"CHK-MLDSA-{tag} pre-ref")
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
        await self._mldsa_zeroize(what=f"CHK-MLDSA-{tag} post")

        # ABR ML-KEM seed D||Z: KV leg first, then the direct-seed reference.
        d = keys[KM_DEST_ABR_MLKEM_SEED_D]
        z = keys[KM_DEST_ABR_MLKEM_SEED_Z]
        await self._mlkem_zeroize(what=f"CHK-MLKEM-SEED-{tag} pre-KV")
        st, err = await self._kv_read(
            MLKEM_KV_SEED_RD_CTRL, MLKEM_KV_SEED_RD_STATUS, what=f"CHK-MLKEM-SEED-{tag}"
        )
        self._kv_ok(st, err, chk=f"CHK-MLKEM-SEED-{tag}")
        z_kv = self._seed_z_probe()
        ek_kv = await self._mlkem_keygen(None, None, what=f"CHK-MLKEM-SEED-{tag} KV")
        await self._mlkem_zeroize(what=f"CHK-MLKEM-SEED-{tag} pre-ref")
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
            "(%d words, ek[0]=0x%08x); engine Z == delivered Z z[0]=0x%08x z[3]=0x%08x",
            tag,
            st,
            KEM_EK_WORDS,
            ek_kv[0],
            z_kv[0],
            z_kv[3],
        )
        out["mlkem_seed"] = ek_kv

        # ABR ML-KEM message: KV leg first, then the direct-message reference.
        msg = keys[KM_DEST_ABR_MLKEM_MSG]
        await self._mlkem_zeroize(what=f"CHK-MLKEM-MSG-{tag} pre-KV")
        st, err = await self._kv_read(
            MLKEM_KV_MSG_RD_CTRL, MLKEM_KV_MSG_RD_STATUS, what=f"CHK-MLKEM-MSG-{tag}"
        )
        self._kv_ok(st, err, chk=f"CHK-MLKEM-MSG-{tag}")
        ct_kv = await self._mlkem_encaps(ek_ref, None, what=f"CHK-MLKEM-MSG-{tag} KV")
        await self._mlkem_zeroize(what=f"CHK-MLKEM-MSG-{tag} pre-ref")
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
        await self._mlkem_zeroize(what=f"CHK-MLKEM-MSG-{tag} post")
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
        await self.hmac.write_key(sw)
        await self.hmac.configure_keyed_256()
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
        await self.otbn.load_program()
        await self.otbn.execute()
        errbits = await self.otbn.read_errbits()
        assert errbits == OTBN_ERR_KEY_INVALID, (
            f"CHK-OTBN-CLR-{tag} FAIL: ERR_BITS=0x{errbits:08x} after the shred, expected "
            f"KEY_INVALID only (0x{OTBN_ERR_KEY_INVALID:08x})"
        )
        self.logger.info("CHK-OTBN-CLR-%d PASS: ERR_BITS=0x%08x (KEY_INVALID)", tag, errbits)

        # ABR: every KV read on a shredded block reports a failed read flow.
        legs = (
            (
                "ML-DSA seed",
                ABR_MLDSA_KV_RD_SEED_CTRL,
                ABR_MLDSA_KV_RD_SEED_STATUS,
                ABR_STATUS,
                self._mldsa_zeroize,
            ),
            (
                "ML-KEM seed",
                MLKEM_KV_SEED_RD_CTRL,
                MLKEM_KV_SEED_RD_STATUS,
                MLKEM_STATUS,
                self._mlkem_zeroize,
            ),
            (
                "ML-KEM msg",
                MLKEM_KV_MSG_RD_CTRL,
                MLKEM_KV_MSG_RD_STATUS,
                MLKEM_STATUS,
                self._mlkem_zeroize,
            ),
        )
        for name, ctrl, status, eng_status, zeroize in legs:
            await zeroize(what=f"CHK-ABR-CLR-{tag} {name} pre")
            st, err = await self._kv_read(ctrl, status, what=f"CHK-ABR-CLR-{tag} {name}")
            assert err == KV_READ_FAIL, (
                f"CHK-ABR-CLR-{tag} FAIL: {name} KV read after the shred reports ERROR={err} "
                f"(status 0x{st:08x}), expected KV_READ_FAIL={KV_READ_FAIL}"
            )
            est = await self.abr.rd32(eng_status)
            self.logger.info(
                "CHK-ABR-CLR-%d PASS: %s KV read on the shredded block: status 0x%08x "
                "(ERROR=KV_READ_FAIL); engine STATUS 0x%08x (logged, not graded)",
                tag,
                name,
                st,
                est,
            )
            await zeroize(what=f"CHK-ABR-CLR-{tag} {name} recover")

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
            await self._mlkem_zeroize(
                what=f"CHK-ABR-CLR-{tag} {DEST_NAME[again]} then {DEST_NAME[other_dest]} recover"
            )
        # Leave every destination shredded, as the round expects.
        await self._shred(r, MLKEM_SEED_DESTS)

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

    # --------------------------------------------------------------- main --
    async def run_scenario(self) -> None:
        self.walk = SepKmShareWalkCfg(self.random_seed())
        self.handles: list[dict[int, int]] = [{} for _ in range(ROUNDS)]
        self.logger.info("RANDCFG: %s", self.walk.summary())

        image = self.select_efuse_image(lc_raw=0x1)  # LC_PROD
        self.write_efuse_image(image)
        await self.bring_up_no_cpu(park=("otbn", "aes", "hmac", "kmac"))

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
        self.start_fifo_drain()

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

        outputs = []
        for r in range(ROUNDS):
            await self._load_all(r)
            outputs.append(await self._consume(r))
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

        await self._cleared_final()

        await self.km.check_outbound_empty("EOT")
        await self.aes.check_status_clean("EOT")
        await self.hmac.check_status_clean("EOT")
        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        assert self.drbg_sb.report()
        self.logger.info("entropy alerts clear and DRBG scoreboard reports PASS")
