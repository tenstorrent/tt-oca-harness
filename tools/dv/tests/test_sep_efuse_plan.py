# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP eFuse/lifecycle leaf plans: seed replay, prestage = runtime, profile table, bank watch.

``hw/sys/sep/dv/cocotb/env/sep_efuse_plan.py`` draws each leaf plan of the eFuse,
lifecycle and SEC_DIS tests from the seed. ``dv_sim_prestage.py`` stages the t=0
image of a prestaged test from that plan before the simulator starts, and the test
rebuilds the same plan at runtime. These tests hold the contracts that make the
staged image and the golden agree, with no simulator:

* the same seed gives the same plan and image bytes; a set of fixed seeds gives
  plans that differ in a drawn field;
* the hex that ``stage()`` writes equals the image of the runtime plan;
* ``feat_ctrl_profile`` equals an independent transcription of every row of the
  Per-LC-state Feature Control Profile table;
* the image rules, the vector filter, the token golden and the bank-watch decode.

The bank-watch module imports cocotb (the ``dv`` dependency group). Run from the
repository root:

    python3 -m unittest discover tools/dv/tests -p 'test_sep_efuse_plan.py'
"""

from __future__ import annotations

import hashlib
import io
import subprocess
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
import sep_efuse_bank_watch as bw  # noqa: E402
import sep_efuse_plan as P  # noqa: E402

SEEDS = (1, 2, 3, 7, 0xFFFF_FFFF)
SPREAD_SEEDS = tuple(range(1, 9))
FIXED_IMAGE_TESTS = (P.T_WINDOW_DECODE, P.T_TOKEN_CHANNEL, P.T_SHIM_FAULT)
# Images that stage a pair outside the vector filter, by a stated contract exception.
_FILTER_EXCEPTION_LEGS = (P.LEG_D_EARLIER, P.LEG_D_WALK, P.LEG_E)

DBG1 = 0x0000_0000_00FF_FFFF
DBG2 = 0x0000_FFFF_FF00_0000
FUNC = 0xFFFF_0000_0000_0000


def _hex(words: list[int]) -> str:
    return "".join(f"{w & 0xFFFF_FFFF:08x}\n" for w in words)


class SeedReplayTest(unittest.TestCase):
    def test_same_seed_same_plan_and_image(self) -> None:
        for test in P.PLANNERS:
            for seed in SEEDS:
                a, b = P.plan(test, seed), P.plan(test, seed)
                with self.subTest(test=test, seed=seed):
                    self.assertEqual(a.words(), b.words())
                    self.assertEqual(a.log_lines(), b.log_lines())
                    self.assertEqual(_hex(a.words()), _hex(b.words()))

    def test_runtime_draws_continue_the_same_stream(self) -> None:
        a, b = P.plan(P.T_TOKEN_FAULT, 5), P.plan(P.T_TOKEN_FAULT, 5)
        self.assertEqual(a.draw.word_order("x"), b.draw.word_order("x"))
        self.assertEqual(
            P.draw_match_offset(P.plan(P.T_SEC_DIS_TIMING, 4), 10, 90),
            P.draw_match_offset(P.plan(P.T_SEC_DIS_TIMING, 4), 10, 90),
        )

    def test_fixed_seeds_give_different_plans(self) -> None:
        for test in P.PLANNERS:
            plans = [P.plan(test, s) for s in SPREAD_SEEDS]
            draws = {tuple(sorted((k, repr(v)) for k, v in p.draws.items())) for p in plans}
            with self.subTest(test=test):
                self.assertGreater(len(draws), 1, f"{test}: eight seeds drew one plan")
        for test in P.PRESTAGED_TESTS:
            images = {tuple(P.plan(test, s).words()) for s in SPREAD_SEEDS}
            with self.subTest(test=test):
                self.assertGreater(len(images), 1, f"{test}: eight seeds staged one image")

    def test_fixed_image_tests_stage_one_image(self) -> None:
        for test in FIXED_IMAGE_TESTS:
            images = {tuple(P.plan(test, s).words()) for s in SPREAD_SEEDS}
            with self.subTest(test=test):
                self.assertEqual(len(images), 1)


class PrestageRuntimeEqualityTest(unittest.TestCase):
    def test_registry_holds_exactly_the_prestaged_tests(self) -> None:
        plan_keys = {
            k
            for k, v in dv_sim_prestage.EFUSE_IMAGE_REGISTRY.items()
            if v.get("fixed_from") == "efuse_plan"
        }
        self.assertEqual(plan_keys, set(P.PRESTAGED_TESTS))
        self.assertEqual(len(plan_keys), 10)
        for test in FIXED_IMAGE_TESTS:
            self.assertNotIn(test, dv_sim_prestage.EFUSE_IMAGE_REGISTRY)

    def test_staged_hex_equals_runtime_image(self) -> None:
        for test in P.PRESTAGED_TESTS:
            for seed in SEEDS:
                with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
                    self.assertTrue(dv_sim_prestage.stage(test, seed, tmp))
                    staged = (Path(tmp) / "out" / "sep_efuse.hex").read_text()
                runtime = P.plan(test, seed)
                with self.subTest(test=test, seed=seed):
                    self.assertEqual(staged, _hex(runtime.words()))
                    self.assertEqual(len(staged.split()), 256)

    def test_stage_in_a_fresh_interpreter(self) -> None:
        """``stage()`` as run_dv.py runs it: no env module imported before the call.

        In this process ``sep_efuse_plan`` is already in ``sys.modules``, which hides a
        file-path import that does not register the module (a dataclass then fails to
        build). A child interpreter imports only ``dv_sim_prestage``.
        """
        code = (
            "import io, sys, tempfile\n"
            "from contextlib import redirect_stdout\n"
            "from pathlib import Path\n"
            f"sys.path.insert(0, {str(COCOTB)!r})\n"
            "import dv_sim_prestage\n"
            "test, seed = sys.argv[1], int(sys.argv[2])\n"
            "with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):\n"
            "    ok = dv_sim_prestage.stage(test, seed, tmp)\n"
            "    hexs = (Path(tmp) / 'out' / 'sep_efuse.hex').read_text() if ok else ''\n"
            "sys.stdout.write(hexs)\n"
        )
        for test in P.PRESTAGED_TESTS:
            seed = SEEDS[0]
            res = subprocess.run(
                [sys.executable, "-I", "-c", code, test, str(seed)],
                capture_output=True,
                text=True,
                check=False,
            )
            with self.subTest(test=test, seed=seed):
                self.assertEqual(res.returncode, 0, res.stderr[-2000:])
                self.assertEqual(res.stdout, _hex(P.plan(test, seed).words()))


class ImageRuleTest(unittest.TestCase):
    def test_image_rules(self) -> None:
        for test in P.PLANNERS:
            for seed in SEEDS:
                p = P.plan(test, seed)
                img = p.image
                with self.subTest(test=test, seed=seed):
                    self.assertEqual(
                        img.words[P.field_word("LC_STATE")], ((~p.lc_raw & 0xF) << 4) | p.lc_raw
                    )
                    for name, used in P.NARROW_USED.items():
                        self.assertEqual(
                            img.field_int(name) & ~used, 0, f"{name} sets an unused bit"
                        )
                    self.assertEqual(img.field_int("LOCKS_SPARE") >> 18, 0)
                    if test not in (P.T_FIELD_LAYOUT, P.T_IF_STATUS, P.T_LOCK_SLOT):
                        self.assertEqual(img.field_int("LOCKS"), 0)
                        self.assertEqual(img.field_int("LOCKS_SPARE"), 0)
                    legal = P.vector_filter_legal(p.sip_dis, p.sys_dis)
                    if test == P.T_FEAT_MATRIX and p.leg["leg"] in _FILTER_EXCEPTION_LEGS:
                        continue
                    if test == P.T_JTAG_ACCESS:
                        self.assertEqual(p.sip_dis & (DBG1 | DBG2), DBG1 | DBG2)
                        self.assertNotEqual(p.sip_dis & FUNC, FUNC)
                        self.assertNotIn(p.sys_dis, (0, (1 << 64) - 1))
                        continue
                    self.assertTrue(
                        legal, f"pair {p.sip_dis:#x}/{p.sys_dis:#x} is not filter-legal"
                    )

    def test_wide_fields_hold_distinct_fixed_vectors(self) -> None:
        p = P.plan(P.T_SHIM_FAULT, 1)
        seen: set[int] = set()
        for name in P.WIDE_FIELDS:
            words = [p.image.words[P.field_word(name) + k] for k in range(8)]
            self.assertEqual(len(set(words)), 8)
            for w in words:
                self.assertNotIn(w, (0, 0xFFFF_FFFF, 0xBADC_AB1E))
                self.assertNotIn(w, seen)
                seen.add(w)
        nz = [p.image.words[i] for i in range(10, 255)]
        self.assertNotIn(0, nz)
        self.assertEqual(len(set(nz)), len(nz), "words 10..254 are not distinct")

    def test_field_layout_redraws_or_flags_adjacent_words(self) -> None:
        for seed in range(1, 41):
            p = P.plan(P.T_FIELD_LAYOUT, seed)
            w = p.image.words
            equal = any(w[i] == w[i + 1] for i in range(255))
            with self.subTest(seed=seed):
                self.assertEqual(equal, p.setup_fail == "adjacent_equal")
                jid = p.leg["jtag_id"]
                forms = {(jid << 1) & 0xFFFF_FFFF, ((jid << 1) | 1) & 0xFFFF_FFFF, jid}
                self.assertFalse(forms & set(w))
                self.assertNotEqual(jid, 0)
                self.assertEqual(
                    p.image.field_int("TRANSIENT_RMA_EN"), 1 - p.image.field_int("SBOOT_DIS")
                )

    def test_field_layout_has_no_setup_fail_over_4000_seeds(self) -> None:
        fails = [s for s in range(1, 4001) if P.plan(P.T_FIELD_LAYOUT, s).setup_fail]
        self.assertEqual(fails, [])

    def test_lock_leg_always_leaves_a_shadow_write_twin_over_4000_seeds(self) -> None:
        shadow = [
            P.SLOT_OF_FIELD[f] for f in ("SIP_DIS", "SYS_DIS", "REQUIRED_SIGNERS", "REQUIRED_ALGS")
        ]
        fails, redraws, leaves = [], 0, 0
        for seed in range(1, 4001):
            p = P.plan(P.T_LOCK_SLOT, seed)
            if p.setup_fail:
                fails.append(seed)
            if p.leg["kind"] != "lock_leg":
                continue
            leaves += 1
            layout = p.leg["layout"]
            free = [s for s in shadow if layout.get(s) not in ("write", "write_read")]
            if not free:
                fails.append(seed)
            self.assertEqual(free, p.leg["shadow_write_twin_free"])
            lock_bits = p.image.field_int("LOCKS") | (p.image.field_int("LOCKS_SPARE") << 64)
            for s in free:
                self.assertFalse(lock_bits >> P.write_lock_bit(s) & 1, (seed, s))
            if "shadow_write_twin_slot" in p.draws:
                redraws += 1
                s = p.draws["shadow_write_twin_slot"]
                self.assertIn(f"redraw.lock_kind.{s}", p.draws)
                self.assertTrue(any(f"name=redraw.lock_kind.{s} " in ln for ln in p.log_lines()))
        self.assertEqual(fails, [])
        self.assertGreater(leaves, 1000)
        self.assertGreater(redraws, 0, "no seed of 1..4000 exercised the redraw")

    def test_feat_matrix_leg_e_walks_the_contract_bits(self) -> None:
        seen = 0
        for seed in range(1, 400):
            p = P.plan(P.T_FEAT_MATRIX, seed)
            if "leg_e" in p.leg:
                seen += 1
                self.assertEqual(sorted(st["bit"] for st in p.leg["leg_e"]), [0, 1, 2, 3, 24])
        self.assertGreater(seen, 0)

    def test_jtag_access_go_result_takes_both_values(self) -> None:
        seen = set()
        for seed in range(1, 200):
            p = P.plan(P.T_JTAG_ACCESS, seed)
            ch = p.leg["go_channel"]
            content = {}
            for acc in p.leg["token_block"]:
                if acc["cls"] == "token_word" and acc["op"] == "wr" and acc["channel"] == ch:
                    content[acc["index"]] = acc["data"]
            golden = P.match_code(ch, P.words_token([content[k] for k in range(8)]), p.image)
            self.assertEqual(golden, p.leg["go_golden"])
            self.assertEqual(golden, p.leg["go_result"])
            seen.add((ch, golden))
        self.assertEqual(len(seen), 4, seen)

    def test_jtag_access_every_leaf_makes_a_denied_program_of_p(self) -> None:
        for seed in range(1, 500):
            p = P.plan(P.T_JTAG_ACCESS, seed)
            progs = [
                a
                for a in p.leg["denied"]
                if a["op"] == "wr" and a.get("reg") == "EFUSE_PROGRAM_CTRL"
            ]
            self.assertTrue(progs, f"seed {seed}: no denied EFUSE_PROGRAM_CTRL write")
            for a in progs:
                self.assertEqual(a["data"], P.program_ctrl_word(p.leg["spare_p"]["addr"]))

    def test_field_layout_redraw_is_logged_with_its_class(self) -> None:
        seen = 0
        for seed in range(1, 200):
            p = P.plan(P.T_FIELD_LAYOUT, seed)
            lines = p.log_lines()
            for key in p.draws:
                if key.startswith("redraw.") and ".class" in key:
                    seen += 1
                    self.assertTrue(any(f"name={key} " in ln for ln in lines))
                    self.assertIn(key.replace(".class", ".value"), p.draws)
        self.assertGreater(seen, 0, "no seed of 1..199 made a narrow redraw")

    def test_lock_slot_bits_follow_the_spec_layout(self) -> None:
        self.assertEqual(len(P.LOCK_SLOTS), 41)
        self.assertEqual(P.LOCK_SLOT_FIELD[0], "LC_STATE")
        self.assertEqual(P.LOCK_SLOT_FIELD[7], "CLASS_KEY")
        self.assertEqual(
            [P.LOCK_SLOT_FIELD[s] for s in (11, 13, 15)], ["CHIPLET_UID", "SIP_UID", "SYS_UID"]
        )
        self.assertEqual(P.LOCK_SLOT_FIELD[22], "REQUIRED_ALGS")
        self.assertEqual(P.LOCK_SLOT_FIELD[40], "SPARE8")
        for s in range(41):
            self.assertEqual((P.write_lock_bit(s), P.read_lock_bit(s)), (2 * s, 2 * s + 1))

    def test_bit_address_rule(self) -> None:
        self.assertEqual(P.bit_address("LC_STATE", 0, 1), 8 * 0xC + 1)
        self.assertEqual(P.bit_address("SPARE8", 7, 31), 8191)


class VectorFilterTest(unittest.TestCase):
    def test_filter_cases(self) -> None:
        self.assertTrue(P.vector_filter_legal(P.FIXED_SIP_DIS, P.FIXED_SYS_DIS))
        self.assertFalse(P.vector_filter_legal(0, 0))
        self.assertFalse(P.vector_filter_legal((1 << 64) - 1, 0))
        # Equal vectors: no group has a bit set in only one vector.
        self.assertFalse(P.vector_filter_legal(P.FIXED_SIP_DIS, P.FIXED_SIP_DIS))
        # Function group all ones in the OR.
        self.assertFalse(P.vector_filter_legal(P.FIXED_SIP_DIS | FUNC, P.FIXED_SYS_DIS))


class TokenGoldenTest(unittest.TestCase):
    def test_sec_dis_bound_digest_is_sha256_of_32_zero_bytes(self) -> None:
        self.assertEqual(
            P.SEC_DIS_BOUND_DIGEST,
            0x66687AADF862BD776C8FC18B8E9F8E20089714856EE233B3902A591D0D5F2925,
        )

    def test_hash_input_is_big_endian_index_7_first(self) -> None:
        words = P.token_words(P.TOKEN_T1)
        self.assertEqual(words[0], P.TOKEN_T1 & 0xFFFF_FFFF)
        msg = b"".join(w.to_bytes(4, "big") for w in reversed(words))
        self.assertEqual(
            int.from_bytes(hashlib.sha256(msg).digest(), "big"), P.token_digest(P.TOKEN_T1)
        )

    def test_match_codes(self) -> None:
        img = P.plan(P.T_TOKEN_CHANNEL, 1).image
        self.assertEqual(P.match_code(P.CH_SIP, P.TOKEN_T1, img), P.CODE_MATCH)
        self.assertEqual(P.match_code(P.CH_CHIPLET, P.TOKEN_T2, img), P.CODE_MATCH)
        self.assertEqual(P.match_code(P.CH_SEC_DIS, P.TOKEN_ZERO, img), P.CODE_MATCH)
        for ch in P.CHANNELS:
            self.assertEqual(P.match_code(ch, P.TOKEN_OTHER, img), P.CODE_MISMATCH)

    def test_token_channel_shapes_never_match(self) -> None:
        for seed in SEEDS:
            p = P.plan(P.T_TOKEN_CHANNEL, seed)
            self.assertEqual(len(p.leg["cell_order"]), 18)
            for (shape, ch), tok in p.leg["shape_tokens"].items():
                with self.subTest(seed=seed, shape=shape, ch=ch):
                    self.assertNotEqual(tok, P.RIGHT_TOKEN[ch])
                    self.assertEqual(P.match_code(ch, tok, p.image), P.CODE_MISMATCH)

    def test_word_write_ops(self) -> None:
        ops = P.token_write_ops(P.CH_SEC_DIS, P.TOKEN_OTHER, [7, 0, 1, 2, 3, 4, 5, 6])
        self.assertEqual(
            ops[0], (P.TOKEN_ARRAY_ADDR[P.CH_SEC_DIS][7], P.token_words(P.TOKEN_OTHER)[7])
        )
        self.assertEqual(P.token_go_op(P.CH_SEC_DIS), (P.TOKEN_EOP_ADDR, 1 << 16))
        self.assertEqual(P.token_go_op(P.CH_CHIPLET)[1], 1 << 8)

    def test_control_words(self) -> None:
        self.assertEqual(P.program_ctrl_word(0x1F01), 0x1F01 | 1 << 16 | 1 << 17 | 1 << 27)
        self.assertEqual(P.read_ctrl_word(0x20), 0x20 | 1 << 16 | 1 << 28)


def _expected_row(state: str, sip: int, sys_: int, d1: int, d2: int, sec: int) -> int:
    """Second transcription of the profile table (lifecycle_controller.adoc, feature-control-table)."""
    both_dbg1 = ~(sip | sys_) & DBG1
    both_dbg2 = ~(sip | sys_) & DBG2
    both_func = ~(sip | sys_) & FUNC
    if sec or state == "RMA_CHIPLET":
        return DBG1 | DBG2 | FUNC
    if state == "TEST_DEV":
        return (DBG1 if d1 else both_dbg1) | (DBG2 if d2 else both_dbg2) | both_func
    if state == "PROD":
        return (both_dbg1 if d1 else 0) | (both_dbg2 if d2 else 0) | both_func
    if state == "PROD_END":
        return both_func
    if state == "RMA_SIP":
        return ~sip & (DBG1 | DBG2 | FUNC)
    return 0


class FeatCtrlProfileTest(unittest.TestCase):
    SIP = (0x1234 << 48) | (0x00AB00 << 24) | 0x0000C3
    SYS = (0x4300 << 48) | (0x0F0000 << 24) | 0x00003C

    def test_raw_code_classes(self) -> None:
        want = {
            0b0000: "TEST_DEV",
            0b0001: "PROD",
            0b1000: "PROD_END",
            0b0010: "RMA_SIP",
            0b0011: "RMA_SIP",
            0b0110: "RMA_CHIPLET",
            0b0111: "RMA_CHIPLET",
        }
        for raw in range(16):
            self.assertEqual(P.lc_state_class(raw), want.get(raw, "INVALID"), f"raw {raw:04b}")

    def test_table_has_every_spec_row(self) -> None:
        self.assertEqual(len(P.FEAT_CTRL_PROFILE), 17)
        per_state: dict[str, int] = {}
        for st, *_r in P.FEAT_CTRL_PROFILE:
            per_state[st] = per_state.get(st, 0) + 1
        self.assertEqual(
            per_state,
            {"TEST_DEV": 5, "PROD": 5, "PROD_END": 2, "RMA_SIP": 2, "RMA_CHIPLET": 1, "INVALID": 2},
        )

    def test_every_row_against_the_spec(self) -> None:
        cells = []
        for st, raw in (("TEST_DEV", 0x0), ("PROD", 0x1)):
            for d1 in (0, 1):
                for d2 in (0, 1):
                    cells.append((st, raw, d1, d2, 0))
            cells.append((st, raw, 1, 0, 1))
        for st, raws in (
            ("PROD_END", (0x8,)),
            ("RMA_SIP", (0x2, 0x3)),
            ("RMA_CHIPLET", (0x6, 0x7)),
            ("INVALID", (0x4, 0x5, 0x9, 0xF)),
        ):
            for raw in raws:
                for sec in (0, 1):
                    for d1, d2 in ((0, 0), (1, 1)):
                        cells.append((st, raw, d1, d2, sec))
        rows_hit = set()
        for st, raw, d1, d2, sec in cells:
            row = P.feat_ctrl_profile(
                raw, self.SIP, self.SYS, demote_1=d1, demote_2=d2, sec_dis=sec
            )
            with self.subTest(state=st, raw=raw, d1=d1, d2=d2, sec=sec):
                self.assertEqual(row.state, st)
                self.assertEqual(row.value, _expected_row(st, self.SIP, self.SYS, d1, d2, sec))
            rows_hit.add(row.row)
        self.assertEqual(rows_hit, set(range(1, 18)), "a profile row was never selected")

    def test_overrides(self) -> None:
        for raw in range(16):
            self.assertEqual(P.feat_ctrl_profile(raw, self.SIP, self.SYS, sigint_err=1).value, 0)
            self.assertEqual(
                P.feat_ctrl_profile(raw, self.SIP, self.SYS, sigint_err=1, sec_dis=1).value,
                (1 << 64) - 1,
            )

    def test_state_upper_bound(self) -> None:
        self.assertEqual(P.feat_ctrl_state_upper_bound(0x0), (1 << 64) - 1)
        self.assertEqual(P.feat_ctrl_state_upper_bound(0x8), FUNC)
        self.assertEqual(P.feat_ctrl_state_upper_bound(0x5), 0)

    def test_profile_is_not_the_shared_golden(self) -> None:
        src = (ENV / "sep_efuse_plan.py").read_text()
        self.assertNotIn("sep_lcc_golden", src)
        self.assertNotIn("feat_ctrl_expected", src)


class BankWatchDecodeTest(unittest.TestCase):
    def test_bank_words_and_diff(self) -> None:
        value = (0xDEAD_BEEF << 32 * 5) | (0x1 << 32 * 255)
        words = bw.bank_words(value)
        self.assertEqual(words[5], 0xDEAD_BEEF)
        self.assertEqual(words[255], 1)
        self.assertEqual(sum(1 for w in words if w), 2)
        new = list(words)
        new[7] |= 1 << 3
        changes = bw.bank_diff(words, new)
        self.assertEqual(changes, [bw.BitChange(7, 3, 0, 1)])
        self.assertEqual(changes[0].addr, 7 * 32 + 3)
        self.assertTrue(bw.diff_is_exactly(changes, 7 * 32 + 3))
        self.assertFalse(bw.diff_is_exactly(changes, 7 * 32 + 4))
        self.assertFalse(bw.diff_is_exactly(bw.bank_diff(new, list(words)), 7 * 32 + 3))
        self.assertEqual(bw.bank_diff(words, words), [])

    def test_decode_rejects_x(self) -> None:
        self.assertEqual(bw.decode_bits("0101", "t"), 5)
        with self.assertRaises(bw.BankWatchXZError):
            bw.decode_bits("01x1", "t")

    def test_command_record_rule(self) -> None:
        P_ = bw.FUSE_COMMAND_PROGRAM
        R_ = bw.FUSE_COMMAND_READ
        samples = [
            (1, 0, 0, 0, 0, 0),
            (2, 1, R_, 0, 0, 255),  # new valid run
            (3, 1, R_, 0, 0, 255),  # held: no new record
            (4, 1, R_, 32, 0, 255),  # field change while valid
            (5, 0, 0, 0, 0, 0),
            (6, 1, P_, 99, 1, 1),  # program
            (7, 0, 0, 0, 0, 0),
            (8, 1, P_, 99, 1, 1),  # re-issue after a response
        ]
        cmds = bw.command_edges(samples)
        self.assertEqual([c.clk for c in cmds], [2, 4, 6, 8])
        self.assertEqual([c.name for c in cmds], ["READ", "READ", "PROGRAM", "PROGRAM"])
        self.assertEqual(len(bw.select_commands(cmds, program=True, address=99)), 2)
        self.assertEqual(len(bw.select_commands(cmds, program=False)), 2)


if __name__ == "__main__":
    unittest.main()
