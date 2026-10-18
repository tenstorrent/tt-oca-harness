# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""An invalid AES CTRL_SHADOWED encoding maps to its safe value.

Contract (``vendor/lowRISC/opentitan/overlay/regs/aes/regs/gen/adoc/aes.adoc``,
CTRL_SHADOWED and TRIGGER): an invalid KEY_LEN (3'b000 or several bits) maps to
AES_256, an invalid OPERATION (2'b00 or 2'b11) maps to AES_ENC, an invalid MODE
(6'b00_0000 or several bits) maps to AES_NONE, and TRIGGER.START does not start
the unit while MODE is AES_NONE.

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense``,
``+esrc_noise_force``. The internal entropy source feeds ESRC, CSRNG and EDN
for the AES masking PRNG; HMAC, KMAC, OTBN and ABR stay in reset.

Randomization (``SepSeededRng`` from the run seed, drawn before the first
stimulus): the key table row, the plaintext P (drawn again until the AES-256
and AES-128 goldens differ and E_K(E_K(P)) differs from P), the multi-hot value
of each field (KEY_LEN from 3'b011, 3'b101, 3'b110, 3'b111; OPERATION 2'b11;
MODE a 6-bit value with two to five bits set) and the order of the six cells
{KEY_LEN, OPERATION, MODE} x {all-zero, multi-hot}. Every cell runs on every
seed.

Each cell runs in its own trial after an AES reset pulse, with its legal
neighbour as the control of the same trial. The calibration block gives the
clean block time t_blk; the MODE window is 20 x t_blk clocks.

Checkers:
  CHK-AES-INV-KEYLEN  the ciphertext of P equals the AES-256 golden (and so
                      differs from the AES-128 golden). Control: KEY_LEN =
                      AES_128 gives the AES-128 golden.
  CHK-AES-INV-OP      the result for C = E_K(P) equals E_K(C) and not P.
                      Control: OPERATION = AES_DEC returns P.
  CHK-AES-INV-MODE    after START, OUTPUT_VALID reads 0 at every sample of the
                      window and DATA_OUT keeps its base words. Control:
                      MODE = ECB with a new key load sets OUTPUT_VALID in a
                      bounded wait.
The readback of each invalid field is logged (``OBS-AES-ENC-RB``) and not
graded.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from env.sep_aes_golden import aes_decrypt_block, aes_encrypt_words
from env.sep_bit_watch import SepBitWatch
from env.sep_chk_log import SepChkLog
from env.sep_crypto_kat_rows import AES_KEY_ROWS, KMAC_SAMPLE_KEY_ROW
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_seeded_rng import SepSeededRng
from env.sep_trial_wait import TrialTimeout, poll_until, wait_until
from sep_base_test import sep_base_test
from sep_reg_meta import AES
from seq_lib.sep_aes_seq import (
    AES_CTRL_SHADOWED,
    AES_DATA_IN_0,
    AES_DATA_OUT_0,
    AES_KEY_LEN_128,
    AES_KEY_LEN_256,
    AES_MODE_ECB,
    AES_OP_DEC,
    AES_OP_ENC,
    AES_STATUS,
    AES_TRIGGER,
    AES_TRIGGER_DATA_OUT_CLEAR,
    SepAes,
    build_aes_ctrl,
)

TEST = "sep_aes_encoding_inject_rand_test"

# Published 256-bit test constants (env/sep_crypto_kat_rows.py). The seed picks a row,
# never the bytes.
KEY_ROWS = AES_KEY_ROWS[256] + (KMAC_SAMPLE_KEY_ROW,)

KEYLEN_MULTI = (0b011, 0b101, 0b110, 0b111)
OP_MULTI = 0b11
MODE_NONE = 0b11_1111
CELLS = tuple((f, k) for f in ("keylen", "op", "mode") for k in ("zero", "multi"))

ST_IDLE = AES.field_mask("STATUS", "idle")
ST_OV = AES.field_mask("STATUS", "output_valid")
CTRL_MANUAL = AES.field_mask("CTRL_SHADOWED", "manual_operation")
CTRL_FIELD = {
    "keylen": (
        AES.field_lsb("CTRL_SHADOWED", "key_len"),
        AES.field_width("CTRL_SHADOWED", "key_len"),
    ),
    "op": (
        AES.field_lsb("CTRL_SHADOWED", "operation"),
        AES.field_width("CTRL_SHADOWED", "operation"),
    ),
    "mode": (AES.field_lsb("CTRL_SHADOWED", "mode"), AES.field_width("CTRL_SHADOWED", "mode")),
}

WAIT_LIMIT = 20_000  # outer limit of a wait that has no clean time yet (logged as bound=)
MODE_WINDOW_FACTOR = 20  # MODE window = 20 x t_blk (test parameter)
OV_BOUND_FACTOR = 64  # bounded OUTPUT_VALID wait = 64 x t_blk


def _le_words(data: bytes) -> list[int]:
    return [int.from_bytes(data[i : i + 4], "little") for i in range(0, len(data), 4)]


def _le_bytes(words: list[int]) -> bytes:
    return b"".join((w & 0xFFFF_FFFF).to_bytes(4, "little") for w in words)


def _enc(key: list[int], pt: list[int]) -> list[int]:
    return aes_encrypt_words("ecb", key, pt)


def _dec(key: list[int], ct: list[int]) -> list[int]:
    return _le_words(aes_decrypt_block(_le_bytes(key), _le_bytes(ct)))


@dataclass(frozen=True)
class Plan:
    seed: int
    key_row: int
    pt: tuple[int, ...]
    keylen_multi: int
    mode_multi: int
    order: tuple[tuple[str, str], ...]

    @property
    def key(self) -> list[int]:
        return _le_words(KEY_ROWS[self.key_row][1])

    def written(self, field: str, kind: str) -> int:
        if kind == "zero":
            return 0
        return {"keylen": self.keylen_multi, "op": OP_MULTI, "mode": self.mode_multi}[field]

    def describe(self) -> str:
        return (
            f"key_row={KEY_ROWS[self.key_row][0]} pt={[hex(w) for w in self.pt]} "
            f"keylen_multi=0b{self.keylen_multi:03b} op_multi=0b{OP_MULTI:02b} "
            f"mode_multi=0b{self.mode_multi:06b} "
            f"order={','.join(f'{f}.{k}' for f, k in self.order)}"
        )


def draw_plan(seed: int) -> Plan:
    """Every draw of the leaf, in a fixed order, with no simulator access."""
    rng = SepSeededRng(seed)
    key_row = rng.randrange(len(KEY_ROWS))
    key = _le_words(KEY_ROWS[key_row][1])
    while True:
        pt = [rng.getrandbits(32) for _ in range(4)]
        if len(set(pt)) != 4 or 0 in pt:
            continue
        c = _enc(key, pt)
        if _enc(key, pt) != _enc(key[:4], pt) and _enc(key, c) != pt:
            break
    keylen_multi = rng.choice(KEYLEN_MULTI)
    while True:
        mode_multi = rng.getrandbits(6)
        if 2 <= bin(mode_multi).count("1") <= 5:
            break
    order = list(CELLS)
    rng.shuffle(order)
    return Plan(seed, key_row, tuple(pt), keylen_multi, mode_multi, tuple(order))


@pyuvm.test()
class sep_aes_encoding_inject_rand_test(sep_base_test):
    """Invalid KEY_LEN, OPERATION and MODE encodings map to AES_256, AES_ENC and AES_NONE."""

    required_evidence = ("CHK-AES-INV-KEYLEN", "CHK-AES-INV-OP", "CHK-AES-INV-MODE")

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu(park=("otbn", "hmac", "kmac", "abr"))
        await self.bring_up_entropy(strict=True, score_km=False)
        self.start_fifo_drain()
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.logger.info("BASELINE sw_reset_n=0x%02x", self.swrst.value)

        seed = self.random_seed()
        plan = draw_plan(seed)
        self.logger.info("PLAN seed=%d %s", seed, plan.describe())
        self.chk = SepChkLog(self, TEST, seed)
        self.aes = SepAes(self)
        # Clock count of the leaf: the clk of a watcher that samples every rising edge.
        self.clk = SepBitWatch(cocotb.top.rst_ni, {"rst_ni": 0}, name="clk_count").start()
        self.plan = plan
        key = plan.key
        pt = list(plan.pt)

        await self._pulse_aes()
        t_blk = await self._calibrate(key, pt)
        for field, kind in plan.order:
            await self._pulse_aes()
            if field == "keylen":
                await self._keylen_cell(kind, key, pt)
            elif field == "op":
                await self._op_cell(kind, key, pt)
            else:
                await self._mode_cell(kind, key, pt, t_blk)
        close_graded_window(self.logger)

        await self.stop_fifo_drain()
        assert self.drbg_sb.report()
        await self.clk.stop()
        self.chk.finish()

    # --- bus and waits ---------------------------------------------------------
    async def _pulse_aes(self) -> None:
        """AES reset bit 0 then 1; bring-up wait, a timeout raises."""
        dut = cocotb.top
        await self.swrst.park("aes")
        for _ in range(WAIT_LIMIT):
            if self.rd(dut.aes_gated_rst_n_probe_o) == 0:
                break
            await RisingEdge(dut.clk_i)
        else:
            raise AssertionError("AES gated reset never asserted after SW_RESET_N park")
        await self.swrst.release("aes")
        ok, _ = await self._poll(ST_IDLE, ST_IDLE, WAIT_LIMIT)
        if not ok:
            raise AssertionError(f"AES STATUS.IDLE not 1 after the reset pulse bound={WAIT_LIMIT}")

    async def _poll(self, mask: int, want: int, bound: int) -> tuple[bool, list[tuple[int, int]]]:
        """Back-to-back STATUS reads until (STATUS & mask) == want or bound clocks pass."""
        return await poll_until(self._status, self._now, mask, want, bound)

    async def _wait(self, mask: int, want: int, bound: int, what: str) -> list[tuple[int, int]]:
        return await wait_until(self._status, self._now, mask, want, bound, what)

    async def _status(self) -> int:
        return await self.aes._rd(AES_STATUS)

    def _now(self) -> int:
        return self.clk.clk

    async def _ctrl(self, value: int) -> None:
        await self.aes._wr(AES_CTRL_SHADOWED, value)
        await self.aes._wr(AES_CTRL_SHADOWED, value)

    async def _key_load(self, ctrl: int, key: list[int]) -> None:
        """CTRL twice, key words, IDLE, DATA_OUT_CLEAR, IDLE (key-load order of the trials)."""
        await self._ctrl(ctrl)
        await self.aes.write_key(key)
        await self._wait(ST_IDLE, ST_IDLE, WAIT_LIMIT, "idle_after_key")
        await self.aes._wr(AES_TRIGGER, AES_TRIGGER_DATA_OUT_CLEAR)
        await self._wait(ST_IDLE, ST_IDLE, WAIT_LIMIT, "idle_after_clear")

    async def _write_block(self, words: list[int]) -> None:
        for i, w in enumerate(words):
            await self.aes._wr(AES_DATA_IN_0 + 4 * i, w)

    async def _read_out(self) -> list[int]:
        return [await self.aes._rd(AES_DATA_OUT_0 + 4 * i) for i in range(4)]

    async def _block(self, words: list[int], bound: int) -> list[int]:
        await self._write_block(words)
        await self._wait(ST_OV, ST_OV, bound, "output_valid")
        return await self._read_out()

    async def _readback(self, field: str, written: int) -> None:
        lsb, width = CTRL_FIELD[field]
        rb = await self.aes._rd(AES_CTRL_SHADOWED)
        self.chk.obs(
            "AES-ENC-RB",
            field=field,
            written=f"0x{written:x}",
            read=f"0x{(rb >> lsb) & ((1 << width) - 1):x}",
        )

    # --- calibration ------------------------------------------------------------
    async def _calibrate(self, key: list[int], pt: list[int]) -> int:
        """Manual ECB-256: t_blk from the START write response to OUTPUT_VALID."""
        ctrl = (
            build_aes_ctrl(sideload=False, mode=AES_MODE_ECB, key_len=AES_KEY_LEN_256) | CTRL_MANUAL
        )
        try:
            await self._key_load(ctrl, key)
            await self._write_block(pt)
            await self.aes._wr(AES_TRIGGER, AES.field_mask("TRIGGER", "start"))
            t0 = self.clk.clk
            samples = await self._wait(ST_OV, ST_OV, WAIT_LIMIT, "calibration_output_valid")
            t_blk = max(1, samples[-1][0] - t0)
            ct = await self._read_out()
        except TrialTimeout as exc:
            self.chk.ctrl("AES-CAL", False, reason="timeout", bound=exc.bound)
            raise AssertionError("AES calibration block never completed") from exc
        ok = ct == _enc(key, pt)
        self.chk.ctrl("AES-CAL", ok, t_blk=t_blk, bound=WAIT_LIMIT, **{"ct==golden256": int(ok)})
        return t_blk

    # --- cells --------------------------------------------------------------------
    def _ctrl_word(self, *, key_len: int, operation: int, mode: int, manual: bool = False) -> int:
        word = build_aes_ctrl(sideload=False, operation=operation, mode=mode, key_len=key_len)
        return word | (CTRL_MANUAL if manual else 0)

    async def _keylen_cell(self, kind: str, key: list[int], pt: list[int]) -> None:
        v = self.plan.written("keylen", kind)
        g256, g128 = _enc(key, pt), _enc(key[:4], pt)
        ct: list[int] | None = None
        reason = ""
        open_graded_window(TEST, self.logger)
        try:
            await self._key_load(
                self._ctrl_word(key_len=v, operation=AES_OP_ENC, mode=AES_MODE_ECB), key
            )
            await self._readback("keylen", v)
            ct = await self._block(pt, WAIT_LIMIT)
        except TrialTimeout as exc:
            reason = f"timeout:{exc.what} bound={exc.bound}"
        close_graded_window(self.logger)
        ctrl_ok = False
        try:
            await self._key_load(
                self._ctrl_word(key_len=AES_KEY_LEN_128, operation=AES_OP_ENC, mode=AES_MODE_ECB),
                key[:4],
            )
            ctrl_ok = await self._block(pt, WAIT_LIMIT) == g128
        except TrialTimeout:
            ctrl_ok = False
        self.chk.ctrl(
            "AES-INV-KEYLEN", ctrl_ok, cell=f"keylen.{kind}", **{"ctrl_ct==golden128": int(ctrl_ok)}
        )
        fields = {
            "cell": f"keylen.{kind}",
            "written": f"0b{v:03b}",
            "ct==golden256": int(ct == g256),
            "ct!=golden128": int(ct is not None and ct != g128),
            "ctrl_ct==golden128": int(ctrl_ok),
        }
        if reason:
            fields["reason"] = reason
        elif ct != g256:
            fields["ct"] = ",".join(hex(w) for w in ct or [])
        self.chk.ok("AES-INV-KEYLEN", ct == g256, **fields)

    async def _op_cell(self, kind: str, key: list[int], pt: list[int]) -> None:
        v = self.plan.written("op", kind)
        c = _enc(key, pt)
        enc_c = _enc(key, c)
        assert _dec(key, c) == pt, "decrypt golden does not invert the encrypt golden"
        res: list[int] | None = None
        reason = ""
        open_graded_window(TEST, self.logger)
        try:
            await self._key_load(
                self._ctrl_word(key_len=AES_KEY_LEN_256, operation=v, mode=AES_MODE_ECB), key
            )
            await self._readback("op", v)
            res = await self._block(c, WAIT_LIMIT)
        except TrialTimeout as exc:
            reason = f"timeout:{exc.what} bound={exc.bound}"
        close_graded_window(self.logger)
        ctrl_ok = False
        try:
            # A decryption needs the key written after the control register.
            await self._key_load(
                self._ctrl_word(key_len=AES_KEY_LEN_256, operation=AES_OP_DEC, mode=AES_MODE_ECB),
                key,
            )
            ctrl_ok = await self._block(c, WAIT_LIMIT) == pt
        except TrialTimeout:
            ctrl_ok = False
        self.chk.ctrl(
            "AES-INV-OP", ctrl_ok, cell=f"op.{kind}", **{"ctrl_result==dec_golden": int(ctrl_ok)}
        )
        fields = {
            "cell": f"op.{kind}",
            "written": f"0b{v:02b}",
            "result==enc_golden": int(res == enc_c),
            "result!=dec_golden": int(res is not None and res != pt),
            "ctrl_result==dec_golden": int(ctrl_ok),
        }
        if reason:
            fields["reason"] = reason
        self.chk.ok("AES-INV-OP", res == enc_c, **fields)

    async def _mode_cell(self, kind: str, key: list[int], pt: list[int], t_blk: int) -> None:
        v = self.plan.written("mode", kind)
        window = MODE_WINDOW_FACTOR * t_blk
        start = AES.field_mask("TRIGGER", "start")
        ov_seen = None
        base: list[int] | None = None
        after: list[int] | None = None
        n_samples = 0
        reason = ""
        open_graded_window(TEST, self.logger)
        try:
            await self._key_load(
                self._ctrl_word(key_len=AES_KEY_LEN_256, operation=AES_OP_ENC, mode=v, manual=True),
                key,
            )
            await self._readback("mode", v)
            base = await self._read_out()
            await self._write_block(pt)
            await self.aes._wr(AES_TRIGGER, start)
            # The poll reads back to back for the whole window and stops early
            # only at an OUTPUT_VALID sample.
            _, samples = await self._poll(ST_OV, ST_OV, window)
            n_samples = len(samples)
            ov_seen = any(st & ST_OV for _, st in samples)
            after = await self._read_out()
        except TrialTimeout as exc:
            reason = f"timeout:{exc.what} bound={exc.bound}"
        close_graded_window(self.logger)
        ctrl_clk = -1
        try:
            await self._key_load(
                self._ctrl_word(
                    key_len=AES_KEY_LEN_256, operation=AES_OP_ENC, mode=AES_MODE_ECB, manual=True
                ),
                key,
            )
            await self._write_block(pt)
            await self.aes._wr(AES_TRIGGER, start)
            t0 = self.clk.clk
            samples = await self._wait(ST_OV, ST_OV, OV_BOUND_FACTOR * t_blk, "ctrl_output_valid")
            ctrl_clk = samples[-1][0] - t0
            ctrl_ct = await self._read_out()
            self.chk.obs(
                "AES-INV-MODE-CTRL-CT", **{"ctrl_ct==golden256": int(ctrl_ct == _enc(key, pt))}
            )
        except TrialTimeout:
            ctrl_clk = -1
        self.chk.ctrl(
            "AES-INV-MODE",
            ctrl_clk >= 0,
            cell=f"mode.{kind}",
            ctrl_valid_clk=ctrl_clk,
            bound=OV_BOUND_FACTOR * t_blk,
        )
        unchanged = base is not None and after == base
        ok = not reason and ov_seen is False and unchanged
        fields = {
            "cell": f"mode.{kind}",
            "written": f"0b{v:06b}",
            "output_valid": int(bool(ov_seen)),
            "data_out_unchanged": int(unchanged),
            "window_clk": window,
            "samples": n_samples,
            "ctrl_valid_clk": ctrl_clk,
        }
        if reason:
            fields["reason"] = reason
        self.chk.ok("AES-INV-MODE", ok, **fields)
