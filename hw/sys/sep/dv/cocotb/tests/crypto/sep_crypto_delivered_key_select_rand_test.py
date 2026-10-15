# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""HMAC and AES select the delivered key by their stated rules.

Contract (``hw/sys/sep/doc/hmac.adoc`` and ``hw/sys/sep/doc/aes.adoc``, OCAH
Modifications; ``hw/sys/sep/doc/crypto.adoc``, Key Manager Key Delivery;
``vendor/lowRISC/opentitan/upstream/hw/ip/hmac/data/hmac.hjson``, key_length):
  * HMAC uses the delivered key whenever KEY_CTRL.KEY_VALID is set. The
    256-bit delivered key sits at the most-significant end of the 1024-bit key
    field, and only CFG.key_length = 256 matches it.
  * A supported key_length that disagrees gives a repeatable digest and no
    error; key_length 128 takes the top 128 bits of the delivered key.
  * key_length = Key_None with hmac_en = 1 raises a configuration error at
    start and leaves DIGEST unchanged.
  * AES ignores the delivered key while CTRL_SHADOWED.sideload = 0 and reports
    no error; it uses the delivered key while sideload = 1.
  * Two engines that hold two different delivered keys each use their own key.

Run mode: no_cpu (``lsu_stub_all_live``), real fuse sense with a PROD image,
``+esrc_noise_force`` and the Key Manager firmware image of the open Key
Manager sideload tests. The Key Manager, TRNG, AES and ABR run; HMAC is
released before the key transfers; OTBN and KMAC stay in reset. ABR stays out
of reset because the Key Manager boot clears the ABR key interface
(``hw/ip/key_manager/approm/prod/drivers/rom_boot.c``); with ABR held in
reset that access ends the boot with an AXI slave-error fault.

Randomization (``SepSeededRng`` from the run seed, drawn before the first
stimulus): the table rows of the delivered HMAC key K_h, the delivered AES key
K_a, the HMAC software decoy key K_d and the AES software key K_s (K_h differs
from K_a, K_d from K_h, and K_s differs from K_a in every 32-bit word), the
message length (1 to 128 bytes) and bytes, the AES key size and mode of the
software-key leg, the order of the 11 mismatched HMAC cells, the digest size of
the Key_None leg and the AES ALERT_TEST bit of the alert control. The 14 keyed
HMAC cells, the Key_None leg, the AES legs and the two-engine leg run on every
seed.

Checkers:
  CHK-KEYSEL-HMAC-MATCH     key_length 256 on SHA2_384 and SHA2_512 gives the
                            HMAC golden of K_h. Control: the SHA2_256 cell.
  CHK-KEYSEL-HMAC-MISMATCH  each of the 11 mismatched cells gives two equal
                            digests and no hmac_err; key_length 128 gives the
                            golden of the top 128 bits of K_h. Control: the
                            Key_None leg shows hmac_err = 1.
  CHK-KEYSEL-HMAC-NONE      Key_None with a valid delivered key sets hmac_err
                            and leaves DIGEST at d_prev.
  CHK-KEYSEL-AES-SW         sideload = 0 encrypts with K_s, no pulse on vector
                            bit 32 (Crypto alert, source 33) and both AES alert
                            status bits 0. Controls: an AES ALERT_TEST write
                            pulses bit 32; sideload = 1 encrypts with K_a.
  CHK-KEYSEL-TWO            after back-to-back transfers, HMAC uses K_h and AES
                            (sideload = 1, AES_256) uses K_a.
The digest of a mismatched length above 128 bits has no stated value; its
comparisons are logged as ``OBS-KEYSEL-MISMATCH``.

DIGEST byte order: the register text settles the register order (DIGEST_0 holds
digest bytes 0..3) and the ``digest_swap`` swap (``hmac.adoc``:116-117), not the
byte order of a word at ``digest_swap`` = 0. Every HMAC golden compare accepts the
big-endian or the little-endian read of each word, with one order for every
readback of the seed (``env/sep_hmac_golden.py`` ``SepDigestOrder``); the order is
logged as ``OBS-HMAC-DIGEST-ORDER``.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_aes_golden import aes_encrypt_words
from env.sep_axi_agent import SepAxiOp
from env.sep_bit_watch import SepBitWatch
from env.sep_chk_log import SepChkLog
from env.sep_crypto_kat_rows import (
    AES_IV_ROWS,
    AES_KEY_ROWS,
    KMAC_SAMPLE_KEY_ROW,
    RFC_SK_ROWS,
    SP800_38A_PT_BLOCK1,
)
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_hmac_golden import SepDigestOrder, digest_order, hmac_sha2_bytes
from env.sep_seeded_rng import SepSeededRng
from env.sep_trial_wait import TrialTimeout
from sep_base_test import sep_base_test
from sep_reg_meta import AES, HMAC, sym
from seq_lib.sep_aes_seq import (
    AES_CTRL_SHADOWED,
    AES_DATA_IN_0,
    AES_DATA_OUT_0,
    AES_IV_0,
    AES_KEY_LEN_256,
    AES_KEYLEN_CTRL,
    AES_MODE_CTRL,
    AES_MODE_ECB,
    AES_OP_ENC,
    AES_STATUS,
    AES_TRIGGER,
    AES_TRIGGER_DATA_OUT_CLEAR,
    SepAes,
    build_aes_ctrl,
)
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_hmac_seq import (
    HMAC_CMD,
    HMAC_CMD_HASH_PROCESS,
    HMAC_CMD_HASH_START,
    HMAC_DIGEST_WORDS,
    HMAC_INTR_DONE,
    HMAC_INTR_ERR,
    HMAC_INTR_STATE,
    HMAC_MSG_FIFO,
    HMAC_STATUS,
    HMAC_STATUS_IDLE,
    SepHmac,
    build_cfg,
)
from seq_lib.sep_km_mailbox_seq import KM_DEST_AES, KM_DEST_HMAC, SepKmMailbox

TEST = "sep_crypto_delivered_key_select_rand_test"

# Published 256-bit test constants (env/sep_crypto_kat_rows.py). The seed picks a row,
# never the bytes.
KEY_ROWS = AES_KEY_ROWS[256] + (KMAC_SAMPLE_KEY_ROW,) + RFC_SK_ROWS
IV_ROWS = AES_IV_ROWS
AES_PT = SP800_38A_PT_BLOCK1

MATCHED = ((384, 256), (512, 256))
MATCHED_CTRL = (256, 256)
MISMATCHED = (
    (256, 128),
    (256, 384),
    (256, 512),
    (384, 128),
    (384, 384),
    (384, 512),
    (384, 1024),
    (512, 128),
    (512, 384),
    (512, 512),
    (512, 1024),
)
VEC_ALERT_BIT = 32  # source 33, Crypto alert (hw/sys/sep/doc/interrupts.adoc)

ST_IDLE = AES.field_mask("STATUS", "idle")
ST_OV = AES.field_mask("STATUS", "output_valid")
ST_ERR = AES.field_mask("STATUS", "alert_recov_ctrl_update_err") | AES.field_mask(
    "STATUS", "alert_fatal_fault"
)
HMAC_DIGEST_0 = sym("HMAC_DIGEST_0__REG_ADDR")
HMAC_KEY_0 = sym("HMAC_KEY_0__REG_ADDR")


def _hmac_key_regs() -> int:
    """Count of the HMAC KEY multireg registers in the generated register map."""
    n = 0
    while True:
        try:
            sym(f"HMAC_KEY_{n}__REG_ADDR")
        except KeyError:
            return n
        n += 1


HMAC_KEY_REGS = _hmac_key_regs()

WAIT_LIMIT = 20_000  # outer limit of a wait with no clean time (logged as bound=)
ALERT_TEST_FIELDS = ("recov_ctrl_update_err", "fatal_fault")  # aes.rdl ALERT_TEST fields
ALERT_WINDOW = 200  # clocks after the ALERT_TEST write response (outer limit, logged)


def _le_words(data: bytes) -> list[int]:
    return [int.from_bytes(data[i : i + 4], "little") for i in range(0, len(data), 4)]


def _sideload_key_bytes(words: list[int]) -> bytes:
    """Delivered-key byte order of env/sep_hmac_golden.py (word 7 most significant, big-endian)."""
    return b"".join((w & 0xFFFF_FFFF).to_bytes(4, "big") for w in reversed(words))


def _sw_key_bytes(words: list[int]) -> bytes:
    """Software KEY_0..KEY_n order (KEY_0 first, big-endian per word)."""
    return b"".join((w & 0xFFFF_FFFF).to_bytes(4, "big") for w in words)


def hmac_golden(key: bytes, msg: bytes, sha: int) -> bytes:
    """HMAC digest bytes; a DIGEST readback is graded against it with ``SepDigestOrder``."""
    out = hmac_sha2_bytes(key, msg, sha)
    assert len(out) == 4 * HMAC_DIGEST_WORDS[sha]
    return out


@dataclass(frozen=True)
class Plan:
    seed: int
    kh: int
    ka: int
    kd: int
    ks: int
    decoy: tuple[int, ...]  # the 32 KEY register words, K_d first
    msg: bytes
    aes_bits: int
    aes_mode: str
    mismatch_order: tuple[tuple[int, int], ...]
    none_sha: int
    alert_field: str  # an AES ALERT_TEST field name (aes.rdl ALERT_TEST)

    @staticmethod
    def words(row: int) -> list[int]:
        return _le_words(KEY_ROWS[row][1])

    def describe(self) -> str:
        return (
            f"kh={KEY_ROWS[self.kh][0]} ka={KEY_ROWS[self.ka][0]} kd={KEY_ROWS[self.kd][0]} "
            f"ks={KEY_ROWS[self.ks][0]} msg_len={len(self.msg)} msg={self.msg.hex()} "
            f"aes_keylen={self.aes_bits} aes_mode={self.aes_mode} "
            f"mismatch_order={','.join(f'{s}/{k}' for s, k in self.mismatch_order)} "
            f"none_sha={self.none_sha} alert_test_field={self.alert_field}"
        )


def draw_plan(seed: int) -> Plan:
    """Every draw of the leaf, in a fixed order, with no simulator access."""
    rng = SepSeededRng(seed)
    while True:
        kh, ka, kd, ks = rng.sample(range(len(KEY_ROWS)), 4)
        w_ks, w_ka = Plan.words(ks), Plan.words(ka)
        if all(a != b for a, b in zip(w_ks, w_ka, strict=True)):
            break
    others = [r for r in range(len(KEY_ROWS)) if r not in (kh, kd)]
    decoy = Plan.words(kd)
    for r in others[:3]:
        decoy += Plan.words(r)
    assert len(decoy) == HMAC_KEY_REGS and len(set(decoy)) == HMAC_KEY_REGS and 0 not in decoy, (
        "decoy KEY words are not 32 distinct non-zero words"
    )
    n = rng.randrange(1, 129)
    msg = bytearray()
    used: set[int] = set()
    while len(msg) < n:
        take = min(4, n - len(msg))
        chunk = bytes(rng.getrandbits(8) for _ in range(take))
        word = int.from_bytes(chunk, "little")
        if take == 4 and (word == 0 or word in used):
            continue
        used.add(word)
        msg += chunk
    aes_bits = rng.choice((128, 192, 256))
    aes_mode = rng.choice(("ecb", "cbc", "ctr"))
    order = list(MISMATCHED)
    rng.shuffle(order)
    none_sha = rng.choice((256, 384, 512))
    alert_field = rng.choice(ALERT_TEST_FIELDS)
    return Plan(
        seed, kh, ka, kd, ks, tuple(decoy), bytes(msg), aes_bits, aes_mode, tuple(order),
        none_sha, alert_field,
    )  # fmt: skip


@pyuvm.test()
class sep_crypto_delivered_key_select_rand_test(sep_base_test):
    """HMAC prefers the delivered key by key_length; AES uses it only with sideload = 1."""

    required_evidence = (
        "CHK-KEYSEL-HMAC-MATCH",
        "CHK-KEYSEL-HMAC-MISMATCH",
        "CHK-KEYSEL-HMAC-NONE",
        "CHK-KEYSEL-AES-SW",
        "CHK-KEYSEL-TWO",
    )

    async def run_scenario(self) -> None:
        dut = cocotb.top
        image = self.select_efuse_image(lc_raw=0x1)  # LC_PROD: the KM reads OTP at boot
        self.write_efuse_image(image)
        await self.bring_up_no_cpu(park=("otbn", "hmac", "kmac"))
        await self.bring_up_entropy(strict=True, score_km="observe", score_sinks={"aes": "observe"})
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.start_fifo_drain()
        self.logger.info("BASELINE sw_reset_n=0x%02x", self.swrst.value)

        seed = self.random_seed()
        plan = draw_plan(seed)
        self.logger.info("PLAN seed=%d %s", seed, plan.describe())
        self.plan = plan
        self.chk = SepChkLog(self, TEST, seed)
        self.digest_order = SepDigestOrder()
        self.km = SepKmMailbox(self)
        self.hmac = SepHmac(self)
        self.aes = SepAes(self)
        self.vec = SepBitWatch(
            dut.sep_internal_interrupts_probe_o, {"alert": VEC_ALERT_BIT}, name="vec32"
        ).start()
        kh, ka = Plan.words(plan.kh), Plan.words(plan.ka)

        # Key Manager boot and two key loads (bring-up: a failure raises).
        await self.swrst.release("km")
        await self.km.wait_km_ready()
        h_h = await self.km.key_load(key_words=kh, dest=KM_DEST_HMAC)
        h_a = await self.km.key_load(key_words=ka, dest=KM_DEST_AES)
        await self.swrst.release("hmac")
        await self.hmac.wait_idle("post-release")

        # Two-engine leg: back-to-back transfers, then one HMAC run and one AES block.
        open_graded_window(TEST, self.logger)
        rc_h, _ = await self.km.key_transfer(handle=h_h, dest=KM_DEST_HMAC)
        rc_a, _ = await self.km.key_transfer(handle=h_a, dest=KM_DEST_AES)
        g_kh = {s: hmac_golden(_sideload_key_bytes(kh), plan.msg, s) for s in (256, 384, 512)}
        g_ka_ecb = aes_encrypt_words("ecb", ka, _le_words(AES_PT))
        h_two = await self._hmac_try(256, 256)
        a_two = await self._aes_sideload_block()
        h_two_ok, _ = self.digest_order.match(h_two, g_kh[256])
        self.chk.ok(
            "KEYSEL-TWO",
            rc_h == 0 and rc_a == 0 and h_two_ok and a_two == g_ka_ecb,
            rc_hmac=rc_h,
            rc_aes=rc_a,
            **{
                "hmac==golden_kh": int(h_two_ok),
                "aes==golden_ka": int(a_two == g_ka_ecb),
            },
        )

        matched = await self._matched_cells(g_kh)
        mismatch = await self._mismatched_cells(kh, matched)
        none_err = await self._none_leg()
        self.chk.ctrl("KEYSEL-HMAC-MISMATCH", none_err == 1, none_leg_hmac_err=none_err)
        for line in mismatch:
            self.chk.ok("KEYSEL-HMAC-MISMATCH", line.pop("_ok"), **line)

        await self._aes_legs(ka)
        self.chk.obs("HMAC-DIGEST-ORDER", **self.digest_order.fields())
        close_graded_window(self.logger)

        await self.km.check_outbound_empty("EOT")
        await self.stop_fifo_drain()
        assert self.drbg_sb.report()
        self.chk.finish()

    # --- HMAC -----------------------------------------------------------------------
    async def _poll_hmac(self, addr: int, mask: int, want: int, bound: int, what: str) -> int:
        t = 0
        while t <= bound:
            v = await self.hmac._rd(addr)
            if v & mask == want:
                return v
            await ClockCycles(cocotb.top.clk_i, 10)
            t += 10
        raise TrialTimeout(what, bound)

    async def _push_msg(self, msg: bytes) -> None:
        off = 0
        while off + 4 <= len(msg):
            await self.hmac._wr(HMAC_MSG_FIFO, int.from_bytes(msg[off : off + 4], "little"))
            off += 4
        rem = len(msg) - off
        if rem:
            seq = SepAxiAccessSeq(
                "hmac_wr_partial",
                op=SepAxiOp.WRITE,
                addr=HMAC_MSG_FIFO,
                wdata=int.from_bytes(msg[off:], "little"),
                length=rem,
                size=2,
            )
            await self.start_seq(seq)
            if not seq.resp_ok:
                raise AssertionError(f"HMAC partial MSG_FIFO write ({rem}B) not OKAY")

    async def _read_digest(self, sha: int) -> list[int]:
        return [await self.hmac._rd(HMAC_DIGEST_0 + 4 * i) for i in range(HMAC_DIGEST_WORDS[sha])]

    async def _hmac_run(self, sha: int, keylen: int | None) -> tuple[list[int], int]:
        """The HMAC run of the procedure. Returns (DIGEST, INTR_STATE after done)."""
        await self._poll_hmac(
            HMAC_STATUS, HMAC_STATUS_IDLE, HMAC_STATUS_IDLE, WAIT_LIMIT, "hmac_idle"
        )
        for i, w in enumerate(self.plan.decoy):
            await self.hmac._wr(HMAC_KEY_0 + 4 * i, w)
        await self.hmac._wr(HMAC_INTR_STATE, HMAC_INTR_ERR | HMAC_INTR_DONE)
        await self.hmac._wr(
            HMAC.addr("CFG"), build_cfg(hmac_en=True, sha_bits=sha, key_bits=keylen)
        )
        await self.hmac._wr(HMAC_CMD, HMAC_CMD_HASH_START)
        await self._push_msg(self.plan.msg)
        await self.hmac._wr(HMAC_CMD, HMAC_CMD_HASH_PROCESS)
        intr = await self._poll_hmac(
            HMAC_INTR_STATE, HMAC_INTR_DONE, HMAC_INTR_DONE, WAIT_LIMIT, "hmac_done"
        )
        digest = await self._read_digest(sha)
        await self.hmac._wr(HMAC_INTR_STATE, HMAC_INTR_DONE)
        return digest, intr

    async def _hmac_try(self, sha: int, keylen: int) -> list[int] | None:
        try:
            digest, _ = await self._hmac_run(sha, keylen)
            return digest
        except TrialTimeout as exc:
            self.logger.info("HMAC run sha=%d keylen=%d: %s", sha, keylen, exc)
            return None

    async def _matched_cells(self, g_kh: dict[int, bytes]) -> dict[int, list[int] | None]:
        decoy = list(self.plan.decoy)
        out: dict[int, list[int] | None] = {}
        for sha, keylen in MATCHED:
            d = await self._hmac_try(sha, keylen)
            out[sha] = d
            g_decoy = hmac_golden(_sw_key_bytes(decoy[:8]), self.plan.msg, sha)
            assert g_decoy != g_kh[sha], "decoy golden equals the delivered-key golden"
            hit, _ = self.digest_order.match(d, g_kh[sha])
            self.chk.ok(
                "KEYSEL-HMAC-MATCH",
                hit,
                sha=sha,
                keylen=keylen,
                **{
                    "digest==golden_kh": int(hit),
                    "digest==golden_decoy": int(digest_order(d, g_decoy) is not None),
                },
            )
        close_graded_window(self.logger)
        sha, keylen = MATCHED_CTRL
        d = await self._hmac_try(sha, keylen)
        out[sha] = d
        hit, _ = self.digest_order.match(d, g_kh[sha])
        self.chk.ctrl(
            "KEYSEL-256",
            hit,
            sha=sha,
            keylen=keylen,
            **{"digest==golden_kh": int(hit)},
        )
        open_graded_window(TEST, self.logger)
        return out

    async def _mismatched_cells(
        self, kh: list[int], matched: dict[int, list[int] | None]
    ) -> list[dict]:
        lines = []
        top128 = _sideload_key_bytes(kh)[:16]
        decoy = list(self.plan.decoy)
        for sha, keylen in self.plan.mismatch_order:
            runs = []
            errs = []
            reason = ""
            for _ in range(2):
                try:
                    d, intr = await self._hmac_run(sha, keylen)
                    intr = await self.hmac._rd(HMAC_INTR_STATE)
                    runs.append(d)
                    errs.append(int(bool(intr & HMAC_INTR_ERR)))
                except TrialTimeout as exc:
                    reason = f"timeout:{exc.what} bound={exc.bound}"
                    break
            repeat = len(runs) == 2 and runs[0] == runs[1]
            err = int(any(errs))
            line = {"sha": sha, "keylen": keylen, "err": err, "run1==run2": int(repeat)}
            ok = not reason and repeat and err == 0
            if keylen == 128:
                g = hmac_golden(top128, self.plan.msg, sha)
                hit = bool(runs) and self.digest_order.match(runs[0], g)[0]
                line["digest==golden_kh128"] = int(hit)
                ok = ok and hit
            else:
                line["digest==golden_kh128"] = "na"
                if runs:
                    g_decoy = hmac_golden(_sw_key_bytes(decoy[: keylen // 32]), self.plan.msg, sha)
                    self.chk.obs(
                        "KEYSEL-MISMATCH",
                        sha=sha,
                        keylen=keylen,
                        eq_matched=int(runs[0] == matched.get(sha)),
                        eq_decoy=int(digest_order(runs[0], g_decoy) is not None),
                    )
            if reason:
                line["reason"] = reason
            line["_ok"] = ok
            lines.append(line)
        return lines

    async def _none_leg(self) -> int:
        """Key_None with hmac_en = 1; returns the hmac_err value seen (or -1)."""
        sha = self.plan.none_sha
        cfg = build_cfg(hmac_en=False, sha_bits=sha) | HMAC.field_mask("CFG", "hmac_en")
        assert cfg & HMAC.field_mask("CFG", "key_length") == 0, "Key_None field not 0"
        err = -1
        unchanged = 0
        reason = ""
        try:
            await self._poll_hmac(
                HMAC_STATUS, HMAC_STATUS_IDLE, HMAC_STATUS_IDLE, WAIT_LIMIT, "hmac_idle"
            )
            for i, w in enumerate(self.plan.decoy):
                await self.hmac._wr(HMAC_KEY_0 + 4 * i, w)
            await self.hmac._wr(HMAC_INTR_STATE, HMAC_INTR_ERR)
            await self.hmac._wr(HMAC.addr("CFG"), cfg)
            d_prev = await self._read_digest(sha)
            await self.hmac._wr(HMAC_CMD, HMAC_CMD_HASH_START)
            await self._poll_hmac(
                HMAC_INTR_STATE, HMAC_INTR_ERR, HMAC_INTR_ERR, WAIT_LIMIT, "hmac_err"
            )
            err = 1
            unchanged = int(await self._read_digest(sha) == d_prev)
            await self.hmac._wr(HMAC_INTR_STATE, HMAC_INTR_ERR)
        except TrialTimeout as exc:
            err = 0
            reason = f"timeout:{exc.what} bound={exc.bound}"
        fields = {"sha": sha, "err": err, "digest_unchanged": unchanged}
        if reason:
            fields["reason"] = reason
        self.chk.ok("KEYSEL-HMAC-NONE", err == 1 and unchanged == 1, **fields)
        return err

    # --- AES -----------------------------------------------------------------------
    async def _aes_wait(self, mask: int, want: int, bound: int, what: str) -> None:
        t0 = self.vec.clk
        while self.vec.clk - t0 <= bound:
            if await self.aes._rd(AES_STATUS) & mask == want:
                return
        raise TrialTimeout(what, bound)

    async def _aes_block(self, ctrl: int, key: list[int] | None, iv: list[int] | None) -> list[int]:
        """CTRL twice, the optional key and IV, DATA_OUT_CLEAR, one block of AES_PT."""
        await self._aes_wait(ST_IDLE, ST_IDLE, WAIT_LIMIT, "aes_idle")
        await self.aes._wr(AES_CTRL_SHADOWED, ctrl)
        await self.aes._wr(AES_CTRL_SHADOWED, ctrl)
        await self._aes_wait(ST_IDLE, ST_IDLE, WAIT_LIMIT, "aes_idle_after_ctrl")
        if key is not None:
            await self.aes.write_key(key)
            await self._aes_wait(ST_IDLE, ST_IDLE, WAIT_LIMIT, "aes_idle_after_key")
        if iv is not None:
            for i, w in enumerate(iv):
                await self.aes._wr(AES_IV_0 + 4 * i, w)
            await self._aes_wait(ST_IDLE, ST_IDLE, WAIT_LIMIT, "aes_idle_after_iv")
        await self.aes._wr(AES_TRIGGER, AES_TRIGGER_DATA_OUT_CLEAR)
        await self._aes_wait(ST_IDLE, ST_IDLE, WAIT_LIMIT, "aes_idle_after_clear")
        for i, w in enumerate(_le_words(AES_PT)):
            await self.aes._wr(AES_DATA_IN_0 + 4 * i, w)
        await self._aes_wait(ST_OV, ST_OV, WAIT_LIMIT, "aes_output_valid")
        return [await self.aes._rd(AES_DATA_OUT_0 + 4 * i) for i in range(4)]

    async def _aes_sideload_block(self) -> list[int] | None:
        ctrl = build_aes_ctrl(sideload=True, mode=AES_MODE_ECB, key_len=AES_KEY_LEN_256)
        try:
            return await self._aes_block(ctrl, None, None)
        except TrialTimeout as exc:
            self.logger.info("AES sideload block: %s", exc)
            return None

    async def _aes_legs(self, ka: list[int]) -> None:
        plan = self.plan
        ks = Plan.words(plan.ks)
        bits, mode = plan.aes_bits, plan.aes_mode
        iv = None if mode == "ecb" else _le_words(IV_ROWS[mode])
        g_ks = aes_encrypt_words(mode, ks[: bits // 32], _le_words(AES_PT), iv)
        g_ka = aes_encrypt_words(mode, ka, _le_words(AES_PT), iv)
        if bits == 256:
            assert g_ks != g_ka, "the K_s and K_a goldens are equal"
        ctrl = build_aes_ctrl(
            sideload=False,
            operation=AES_OP_ENC,
            mode=AES_MODE_CTRL[mode],
            key_len=AES_KEYLEN_CTRL[bits],
        )
        reason = ""
        ct: list[int] | None = None
        status = -1
        mark = self.vec.mark()
        try:
            # All eight words of both shares of K_s; the engine takes the key size.
            ct = await self._aes_block(ctrl, ks, iv)
            status = await self.aes._rd(AES_STATUS)
        except TrialTimeout as exc:
            reason = f"timeout:{exc.what} bound={exc.bound}"
        alert_cycles = self.vec.high_clocks_since(mark, "alert")
        close_graded_window(self.logger)

        side = await self._aes_sideload_block()
        g_ka_ecb = aes_encrypt_words("ecb", ka, _le_words(AES_PT))
        side_ok = side == g_ka_ecb
        self.chk.ctrl(
            "KEYSEL-AES-SIDELOAD", side_ok, **{"ctrl_sideload_ct==golden_ka": int(side_ok)}
        )

        await ClockCycles(cocotb.top.clk_i, 1)
        m2 = self.vec.mark()
        await self.aes._wr(AES.addr("ALERT_TEST"), AES.field_mask("ALERT_TEST", plan.alert_field))
        await ClockCycles(cocotb.top.clk_i, ALERT_WINDOW)
        ctrl_cycles = self.vec.high_clocks_since(m2, "alert")
        self.chk.ctrl(
            "KEYSEL-ALERT-TEST",
            ctrl_cycles > 0,
            alert_test_field=plan.alert_field,
            ctrl_alert_cycles=ctrl_cycles,
            bound=ALERT_WINDOW,
        )
        status_err = int(status < 0 or bool(status & ST_ERR))
        ne = "na" if bits != 256 else int(ct is not None and ct != g_ka)
        fields = {
            "keylen": bits,
            "mode": mode,
            "ct==golden_ks": int(ct == g_ks),
            "ct!=golden_ka": ne,
            "alert_cycles": alert_cycles,
            "status_err": status_err,
            "ctrl_alert_cycles": ctrl_cycles,
            "ctrl_sideload_ct==golden_ka": int(side_ok),
        }
        if reason:
            fields["reason"] = reason
        ok = not reason and ct == g_ks and alert_cycles == 0 and status_err == 0 and ne != 0
        self.chk.ok("KEYSEL-AES-SW", ok, **fields)
