# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP Key Manager prestage: seeded fuse plans and KM ROM parameter blocks.

``hw/sys/sep/dv/cocotb/env/sep_km_fuse_plan.py`` draws the fuse image of the Key
Manager OTP and eFuse-window tests, and ``env/sep_km_img_param.py`` draws the
parameter block of the scripted KM images. ``dv_sim_prestage.py`` stages both
from the leaf seed before the simulator starts, and the tests rebuild the same
plans at runtime. These tests hold the contracts that make the staged images and
the goldens agree, with no simulator:

* the same seed gives the same plan and image bytes; a set of fixed seeds gives
  plans that differ;
* the hex that ``stage()`` writes equals the image of the runtime plan;
* the drawn images and blocks keep the rules of the test contracts;
* the staged KM ROM image keeps the template and puts the block, with its
  parity, at the fixed ROM word address.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests -p 'test_sep_km_prestage.py'
"""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
COCOTB = ROOT / "hw" / "sys" / "sep" / "dv" / "cocotb"
ENV = COCOTB / "env"
for p in (str(ENV), str(COCOTB)):
    if p not in sys.path:
        sys.path.insert(0, p)

import dv_sim_prestage  # noqa: E402
import sep_km_fuse_plan as F  # noqa: E402
import sep_km_img_param as P  # noqa: E402
from sep_efuse_image import LC_PROD, LC_TEST_DEV, WORD_MASK, SepEfuseImage, lc_encode  # noqa: E402

SEEDS = (1, 2, 3, 7, 0xFFFF_FFFF)
SPREAD_SEEDS = tuple(range(1, 9))


def _field_words(words: list[int], name: str) -> list[int]:
    fld = SepEfuseImage.field(name)
    return words[fld.word : fld.word + fld.n_words]


def _quiet(fn, *args, **kwargs):
    buf = io.StringIO()
    with redirect_stdout(buf):
        out = fn(*args, **kwargs)
    return out, buf.getvalue()


class FusePlanReplayTest(unittest.TestCase):
    def test_same_seed_same_image(self) -> None:
        for item in F.TESTS:
            for seed in SEEDS:
                a, b = F.plan(item, seed), F.plan(item, seed)
                self.assertEqual(a.words, b.words, (item, seed))
                self.assertEqual(a.identity(), b.identity(), (item, seed))

    def test_seeds_spread(self) -> None:
        for item in F.TESTS:
            ids = {F.plan(item, s).identity() for s in SPREAD_SEEDS}
            self.assertEqual(len(ids), len(SPREAD_SEEDS), item)

    def test_stage_writes_the_plan(self) -> None:
        for item in F.TESTS:
            for seed in SEEDS[:3]:
                with tempfile.TemporaryDirectory() as tmp:
                    staged, log = _quiet(dv_sim_prestage.stage, item, seed, tmp, sim_args=[])
                    self.assertTrue(staged)
                    self.assertIn("KM-FUSE-PLAN", log)
                    text = (Path(tmp) / "out" / "sep_efuse.hex").read_text()
                    want = "".join(f"{w & WORD_MASK:08x}\n" for w in F.plan(item, seed).words)
                    self.assertEqual(text, want, (item, seed))
                    self.assertIn(F.plan(item, seed).identity(), log)

    def test_unknown_item_raises(self) -> None:
        with self.assertRaises(KeyError):
            F.plan("sep_not_a_km_test", 1)


class XbarEfusePlanTest(unittest.TestCase):
    def test_fixed_fields(self) -> None:
        for seed in SEEDS:
            pl = F.plan(F.T_XBAR_EFUSE, seed)
            w = pl.words
            self.assertEqual(pl.lc_raw, LC_TEST_DEV)
            self.assertEqual(_field_words(w, "LC_STATE"), [lc_encode(LC_TEST_DEV)])
            self.assertEqual(_field_words(w, "SIP_DIS"), [0, 0])
            self.assertEqual(_field_words(w, "SYS_DIS"), [0, 0])
            self.assertEqual(_field_words(w, "LOCKS_SPARE"), [0])
            locks = _field_words(w, "LOCKS")
            vector = locks[0] | (locks[1] << 32)
            reg_r, bit_r = F.read_lock_bit(pl.read_locked)
            reg_w, bit_w = F.write_lock_bit(pl.write_locked)
            self.assertEqual((reg_r, reg_w), ("LOCKS", "LOCKS"))
            self.assertEqual(vector, (1 << bit_r) | (1 << bit_w))

    def test_drawn_words_nonzero_and_distinct(self) -> None:
        fixed: set[int] = set()
        for name in F.FIXED_FIELDS:
            fld = SepEfuseImage.field(name)
            fixed.update(range(fld.word, fld.word + fld.n_words))
        for seed in SEEDS:
            w = F.plan(F.T_XBAR_EFUSE, seed).words
            drawn = [w[i] for i in range(len(w)) if i not in fixed]
            self.assertNotIn(0, drawn)
            self.assertEqual(len(set(drawn)), len(drawn))

    def test_locked_fields_and_targets(self) -> None:
        for seed in SEEDS:
            pl = F.plan(F.T_XBAR_EFUSE, seed)
            self.assertNotEqual(pl.read_locked, pl.write_locked)
            for name in (pl.read_locked, pl.write_locked):
                self.assertNotIn(name, F.FIXED_FIELDS + F.SPARE_FIELDS)
            self.assertEqual(pl.targets["denied"].field, pl.write_locked)
            spares = [
                pl.targets[k].field
                for k in ("km_spare", "host_spare", "tm_km_spare", "tm_host_spare")
            ]
            self.assertEqual(len(set(spares)), 4)
            for name in spares:
                self.assertIn(name, F.SPARE_FIELDS)
            for tgt in pl.targets.values():
                word = pl.words[F.field_word(tgt.field) + tgt.word]
                self.assertEqual((word >> tgt.bit) & 1, 0, (seed, tgt))
                self.assertEqual(tgt.address, (F.field_word(tgt.field) + tgt.word) * 32 + tgt.bit)


class OtpIfacePlanTest(unittest.TestCase):
    def test_dual_rail_fields(self) -> None:
        for seed in SEEDS:
            pl = F.plan(F.T_OTP_IFACE, seed)
            seen: set[int] = set()
            for name in F.OTP_DUAL_RAIL_FIELDS:
                for word in _field_words(pl.words, name):
                    self.assertNotIn(word, (0, WORD_MASK))
                    self.assertNotIn(word, seen)
                    seen.add(word)
                value = sum(wd << (32 * i) for i, wd in enumerate(_field_words(pl.words, name)))
                self.assertEqual(pl.otp_fields[name], value)

    def test_lc_mask_and_zero_fields(self) -> None:
        lcs = set()
        for seed in SPREAD_SEEDS + SEEDS:
            pl = F.plan(F.T_OTP_IFACE, seed)
            self.assertIn(pl.lc_raw, (LC_TEST_DEV, LC_PROD))
            lcs.add(pl.lc_raw)
            self.assertEqual(_field_words(pl.words, "LC_STATE"), [lc_encode(pl.lc_raw)])
            self.assertTrue(1 <= bin(pl.lock_mask_a).count("1") <= 8)
            self.assertEqual(pl.lock_mask_a & ~F.OTP_LOCK_ALL, 0)
            for name in ("LOCKS", "LOCKS_SPARE", "SIP_DIS", "SYS_DIS") + F.OTP_SHADOW_WRITE_FIELDS:
                self.assertEqual(set(_field_words(pl.words, name)), {0}, (seed, name))
        self.assertEqual(lcs, {LC_TEST_DEV, LC_PROD})


class ImgParamReplayTest(unittest.TestCase):
    def test_same_seed_same_block(self) -> None:
        for item in P.TESTS:
            for seed in SEEDS:
                self.assertEqual(P.block_words(item, seed), P.block_words(item, seed))

    def test_seeds_spread(self) -> None:
        for item in P.TESTS:
            blocks = {tuple(P.block_words(item, s)) for s in SPREAD_SEEDS}
            self.assertEqual(len(blocks), len(SPREAD_SEEDS), item)

    def test_block_header_and_check(self) -> None:
        for item, block_id in ((P.T_SCR, P.BLOCK_SCR), (P.T_MBOX_KM, P.BLOCK_MBOX_KM)):
            for seed in SEEDS:
                words = P.block_words(item, seed)
                self.assertEqual(words[0], P.PARAM_MAGIC)
                self.assertEqual(words[1], (P.PARAM_VERSION << 16) | block_id)
                self.assertEqual(words[2], len(words) - 4)
                check = 0
                for w in words[:-1]:
                    check ^= w
                self.assertEqual(words[-1], check)
                self.assertLessEqual(len(words), P.PARAM_MAX_WORDS)

    def test_unknown_item_raises(self) -> None:
        with self.assertRaises(KeyError):
            P.plan("sep_not_a_km_test", 1)

    def test_verify_block_accepts_every_drawn_block(self) -> None:
        for item, block_id in ((P.T_SCR, P.BLOCK_SCR), (P.T_MBOX_KM, P.BLOCK_MBOX_KM)):
            for seed in SEEDS:
                P.verify_block(P.block_words(item, seed), block_id)

    def test_verify_block_rejects_a_bad_check_word(self) -> None:
        words = P.block_words(P.T_SCR, 1)
        for bit in (0, 31):
            bad = list(words)
            bad[-1] ^= 1 << bit
            with self.assertRaisesRegex(ValueError, "check word"):
                P.verify_block(bad)

    def test_verify_block_rejects_a_bad_header(self) -> None:
        words = P.block_words(P.T_MBOX_KM, 1)
        for idx, pattern in ((0, "magic"), (1, "version"), (2, "length")):
            bad = list(words)
            bad[idx] ^= 1
            bad[-1] = P.check_word(bad[:-1])
            with self.assertRaisesRegex(ValueError, pattern):
                P.verify_block(bad, P.BLOCK_MBOX_KM)
        with self.assertRaisesRegex(ValueError, "version"):
            P.verify_block(words, P.BLOCK_SCR)


class ScrPlanTest(unittest.TestCase):
    def test_keys(self) -> None:
        for seed in SPREAD_SEEDS:
            pl = P.plan(P.T_SCR, seed)
            self.assertNotEqual(pl.ka, 0)
            self.assertNotEqual(pl.kb, 0)
            for i in range(4):
                self.assertNotEqual((pl.ka >> (8 * i)) & 0xFF, (pl.kb >> (8 * i)) & 0xFF)

    def test_addresses(self) -> None:
        for seed in SPREAD_SEEDS:
            pl = P.plan(P.T_SCR, seed)
            every = pl.addrs8 + pl.addrs64 + pl.addrs_lock
            self.assertEqual(len(set(every)), 8 + 64 + 2)
            for a in every:
                self.assertTrue(P.SRAM_DRAW_LO <= a <= P.SRAM_DRAW_HI)
                self.assertEqual(a % 4, 0)
            self.assertEqual(pl.addrs8[1], pl.addrs8[0] + 4)
            b1, b2 = pl.addrs8[2], pl.addrs8[3]
            self.assertEqual(b1 % P.SRAM_REGION_BYTES, b2 % P.SRAM_REGION_BYTES)
            self.assertNotEqual(b1 // P.SRAM_REGION_BYTES, b2 // P.SRAM_REGION_BYTES)

    def test_data(self) -> None:
        for seed in SPREAD_SEEDS:
            pl = P.plan(P.T_SCR, seed)
            self.assertEqual(pl.data8[0], pl.data8[1])
            self.assertEqual(len(set(pl.data8)), 7)
            self.assertNotIn(0, pl.data8 + pl.data64 + pl.data_lock)
            self.assertEqual(len(set(pl.data64)), 64)
            self.assertEqual(sorted(pl.order8), list(range(8)))

    def test_payload_offsets(self) -> None:
        pl = P.plan(P.T_SCR, 5)
        pay = pl.payload()
        self.assertEqual(pay[pl.OFF_KA], pl.ka)
        self.assertEqual(pay[pl.OFF_KB], pl.kb)
        self.assertEqual(pay[pl.OFF_ADDRS8 : pl.OFF_ADDRS8 + 8], pl.addrs8)
        self.assertEqual(pay[pl.OFF_DATA8 : pl.OFF_DATA8 + 8], pl.data8)
        self.assertEqual(pay[pl.OFF_ADDRS64 : pl.OFF_ADDRS64 + 64], pl.addrs64)
        self.assertEqual(pay[pl.OFF_DATA64 : pl.OFF_DATA64 + 64], pl.data64)
        self.assertEqual(pay[pl.OFF_ADDRS_LOCK : pl.OFF_ADDRS_LOCK + 2], pl.addrs_lock)
        self.assertEqual(pay[pl.OFF_DATA_LOCK : pl.OFF_DATA_LOCK + 2], pl.data_lock)
        order = [(pay[pl.OFF_ORDER8] >> (4 * i)) & 0xF for i in range(8)]
        self.assertEqual(order, pl.order8)


class MboxPlanTest(unittest.TestCase):
    def test_counts_and_words(self) -> None:
        for seed in SPREAD_SEEDS:
            pl = P.plan(P.T_MBOX_KM, seed)
            self.assertTrue(1 <= pl.n_drawn <= P.MBOX_DEPTH)
            self.assertTrue(1 <= pl.m_drawn <= P.MBOX_DEPTH)
            self.assertEqual([len(x) for x in pl.out_pass], [16, 1, 15, pl.n_drawn])
            self.assertEqual([len(x) for x in pl.in_pass], [16, 1, 15, pl.m_drawn])
            for one_pass in pl.out_pass + pl.in_pass + [pl.out_overflow] + pl.out_irq:
                self.assertNotIn(0, one_pass)
                self.assertEqual(len(set(one_pass)), len(one_pass))
            self.assertEqual(sorted(pl.flush_order), list(range(6)))
            self.assertEqual(sorted(pl.src_order), list(range(4)))
            self.assertTrue(0 <= pl.irq_enable_s <= 0x1F)

    def test_payload_offsets(self) -> None:
        pl = P.plan(P.T_MBOX_KM, 4)
        pay = pl.payload()
        self.assertEqual(len(pay), pl.PAYLOAD_WORDS)
        self.assertEqual(pay[pl.OFF_N], pl.n_drawn)
        self.assertEqual(pay[pl.OFF_M], pl.m_drawn)
        self.assertEqual(pay[pl.OFF_IRQ_S], pl.irq_enable_s)
        self.assertEqual(pay[pl.OFF_OUT_PASS : pl.OFF_OUT_PASS + 16], pl.out_pass[0])
        self.assertEqual(pay[pl.OFF_OVERFLOW : pl.OFF_OVERFLOW + 18], pl.out_overflow)
        flush = [(pay[pl.OFF_FLUSH_ORDER] >> (3 * i)) & 0x7 for i in range(6)]
        self.assertEqual(flush, pl.flush_order)
        src = [(pay[pl.OFF_SRC_ORDER] >> (2 * i)) & 0x3 for i in range(4)]
        self.assertEqual(src, pl.src_order)


TEMPLATE = (
    "// SPDX-License-Identifier: Apache-2.0\n"
    "// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.\n"
    "@00000000\n"
    "E00000013\n"
    "C12345678\n"
)


class StageImgParamTest(unittest.TestCase):
    def _stage(self, item: str, seed: int, template: str) -> tuple[str, str]:
        with tempfile.TemporaryDirectory() as tdir, tempfile.TemporaryDirectory() as cwd:
            name = dv_sim_prestage.KM_IMG_PARAM_REGISTRY[item]
            (Path(tdir) / f"{name}.parhex").write_text(template)
            saved = dv_sim_prestage._KM_IMG_TEMPLATE_DIR
            dv_sim_prestage._KM_IMG_TEMPLATE_DIR = Path(tdir)
            try:
                _, log = _quiet(dv_sim_prestage.stage, item, seed, cwd, sim_args=[])
            finally:
                dv_sim_prestage._KM_IMG_TEMPLATE_DIR = saved
            text = (Path(cwd) / dv_sim_prestage.km_img_param_name(item)).read_text()
            return text, log

    def test_staged_image_is_template_plus_block(self) -> None:
        for item in P.TESTS:
            for seed in SEEDS[:3]:
                text, log = self._stage(item, seed, TEMPLATE)
                lines = text.splitlines()
                head = TEMPLATE.splitlines()
                self.assertEqual(lines[: len(head)], head)
                self.assertEqual(lines[len(head)], f"@{P.PARAM_BASE_WORD:08X}")
                body = lines[len(head) + 1 :]
                words = P.block_words(item, seed)
                self.assertEqual(len(body), len(words))
                for line, w in zip(body, words):
                    self.assertEqual(len(line), 9)
                    self.assertEqual(int(line[1:], 16), w)
                    self.assertEqual(int(line[0], 16), P.word_parity(w))
                self.assertIn(f"staged_sha256={P.identity(text)}", log)
                self.assertIn("KM-IMG-PARAM", log)

    def test_parity_matches_rom_fill(self) -> None:
        # Per-byte odd parity (bit i = ~^byte_i, tb_backdoor_mem): 0x13 has three ones.
        self.assertEqual(P.word_parity(0x0000_0013), 0xE)
        self.assertEqual(P.word_parity(0x0000_0000), 0xF)

    def _template_path(self, tdir: str) -> Path:
        path = Path(tdir) / "template.parhex"
        path.write_text(TEMPLATE)
        return path

    def test_staged_block_reads_back_the_block(self) -> None:
        with tempfile.TemporaryDirectory() as tdir:
            for item in P.TESTS:
                text = P.staged_text(self._template_path(tdir), item, 7)
                self.assertEqual(P.staged_block(text), P.block_words(item, 7))

    def test_stage_rejects_a_staged_block_with_a_bad_check_word(self) -> None:
        good = P.staged_text

        def corrupt(template, item, seed):
            lines = good(template, item, seed).splitlines()
            w = int(lines[-1][1:], 16) ^ 1
            lines[-1] = f"{P.word_parity(w):X}{w:08X}"
            return "\n".join(lines) + "\n"

        real_load = dv_sim_prestage._load_env_module

        def load(modname, filename):
            mod = real_load(modname, filename)
            if modname == "sep_km_img_param":
                mod.staged_text = corrupt
            return mod

        dv_sim_prestage._load_env_module = load
        try:
            with self.assertRaisesRegex(ValueError, "check word"):
                self._stage(P.T_SCR, 1, TEMPLATE)
        finally:
            dv_sim_prestage._load_env_module = real_load

    def test_staged_block_rejects_a_bad_parity_nibble(self) -> None:
        with tempfile.TemporaryDirectory() as tdir:
            text = P.staged_text(self._template_path(tdir), P.T_SCR, 1)
        lines = text.splitlines()
        nib = int(lines[-1][0], 16) ^ 1
        lines[-1] = f"{nib:X}{lines[-1][1:]}"
        with self.assertRaisesRegex(ValueError, "parity"):
            P.staged_block("\n".join(lines) + "\n")

    def test_template_that_reaches_the_block_raises(self) -> None:
        overlong = TEMPLATE + f"@{P.PARAM_BASE_WORD:08X}\nF00000000\n"
        with self.assertRaises(ValueError):
            self._stage(P.T_SCR, 1, overlong)

    def test_missing_template_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tdir, tempfile.TemporaryDirectory() as cwd:
            saved = dv_sim_prestage._KM_IMG_TEMPLATE_DIR
            dv_sim_prestage._KM_IMG_TEMPLATE_DIR = Path(tdir)
            try:
                with self.assertRaises(FileNotFoundError):
                    _quiet(dv_sim_prestage.stage, P.T_SCR, 1, cwd, sim_args=[])
            finally:
                dv_sim_prestage._KM_IMG_TEMPLATE_DIR = saved

    def test_other_items_stage_no_km_image(self) -> None:
        with tempfile.TemporaryDirectory() as cwd:
            _quiet(dv_sim_prestage.stage, "sep_km_mem_smoke_test", 1, cwd, sim_args=[])
            self.assertEqual(list(Path(cwd).glob("*.param.parhex")), [])


if __name__ == "__main__":
    unittest.main()
