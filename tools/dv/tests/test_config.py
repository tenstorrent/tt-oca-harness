# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for runlib.config run-mode reference validation.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib.cli import expand_items, target_plan  # noqa: E402
from runlib.config import (  # noqa: E402
    _merge_framework_config,
    load_test_catalog,
    selected_run_mode,
    validate_run_mode_request,
)
from runlib.models import ConfigError, Dut, TestCatalog  # noqa: E402


def make_dut(raw: dict, path: Path = Path("test_sim_cfg.toml")) -> Dut:
    return Dut(
        name="unit",
        kind="sim",
        description="unit-test DUT",
        framework="cocotb",
        visibility="public",
        runnability="runnable",
        license="Apache-2.0",
        root=".",
        default_tool="verilator",
        tools=["verilator"],
        path=path,
        raw=raw,
        frameworks=["cocotb"],
        default_framework="cocotb",
    )


def inline_raw(run_modes: dict, tests: list, defaults: dict | None = None) -> dict:
    raw = {"run_modes": run_modes, "tests": tests}
    if defaults is not None:
        raw["defaults"] = defaults
    return raw


SMOKE = {"smoke": {"timeout_sec": 60, "args": []}}


class TestlistRunModeValidation(unittest.TestCase):
    def test_unknown_testlist_run_mode_rejected(self):
        flow = make_dut(inline_raw(SMOKE, [{"name": "t1", "run_modes": ["smoke", "typo_mode"]}]))
        with self.assertRaises(ConfigError) as ctx:
            load_test_catalog(flow, Path("."))
        message = str(ctx.exception)
        self.assertIn("t1", message)
        self.assertIn("typo_mode", message)
        self.assertIn("smoke", message)  # the allowed set is listed

    def test_known_testlist_run_modes_pass(self):
        flow = make_dut(inline_raw(SMOKE, [{"name": "t1", "run_modes": ["smoke"]}]))
        catalog = load_test_catalog(flow, Path("."))
        self.assertEqual(list(catalog.tests), ["t1"])

    def test_unknown_reference_in_included_file_names_that_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "leaf.toml").write_text(
                'schema_version = 1\n[[tests]]\nname = "t_leaf"\nrun_modes = ["typo_mode"]\n'
            )
            (root / "all.toml").write_text('schema_version = 1\nincludes = ["leaf.toml"]\n')
            flow = make_dut({"run_modes": SMOKE, "testlist": {"path": str(root / "all.toml")}})
            with self.assertRaises(ConfigError) as ctx:
                load_test_catalog(flow, root)
            self.assertIn("leaf.toml", str(ctx.exception))

    def test_unknown_defaults_run_mode_rejected(self):
        flow = make_dut(inline_raw(SMOKE, [], defaults={"run_mode": "typo_mode"}))
        with self.assertRaises(ConfigError) as ctx:
            load_test_catalog(flow, Path("."))
        self.assertIn("[defaults].run_mode", str(ctx.exception))


class CliRunModeValidation(unittest.TestCase):
    def test_unknown_cli_run_mode_rejected(self):
        with self.assertRaises(ConfigError) as ctx:
            validate_run_mode_request({"run_modes": SMOKE}, "typo_mode", "--run-mode")
        message = str(ctx.exception)
        self.assertIn("--run-mode", message)
        self.assertIn("typo_mode", message)
        self.assertIn("smoke", message)

    def test_no_modes_defined_reports_none(self):
        with self.assertRaises(ConfigError) as ctx:
            validate_run_mode_request({}, "anything", "--run-mode")
        self.assertIn("none defined", str(ctx.exception))


class SelectedRunModeResolution(unittest.TestCase):
    def test_explicit_cli_typo_raises(self):
        flow = make_dut(inline_raw(SMOKE, [{"name": "t1", "run_modes": ["smoke"]}]))
        catalog = load_test_catalog(flow, Path("."))
        with self.assertRaises(ConfigError):
            selected_run_mode(flow.raw, catalog.tests["t1"], Namespace(run_mode="typo_mode"))

    def test_test_reference_resolves(self):
        flow = make_dut(inline_raw(SMOKE, [{"name": "t1", "run_modes": ["smoke"]}]))
        catalog = load_test_catalog(flow, Path("."))
        mode = selected_run_mode(flow.raw, catalog.tests["t1"], Namespace(run_mode=None))
        self.assertEqual(mode["timeout_sec"], 60)

    def test_implicit_smoke_fallback_stays_optional(self):
        # A DUT without a `smoke` mode (e.g. sep) must resolve to no mode, not error,
        # when neither the CLI, the test, nor [defaults] names one.
        sim_cfg = {"run_modes": {"cpu": {"timeout_sec": 60}}}
        self.assertEqual(selected_run_mode(sim_cfg, None, Namespace(run_mode=None)), {})


class InheritedProfileRunModes(unittest.TestCase):
    def test_profile_run_mode_counts_as_defined(self):
        profile = {
            "frameworks": {"cocotb": {}},
            "run_modes": {"inherited": {"timeout_sec": 120, "args": []}},
        }
        dut = {
            "frameworks": {"cocotb": {}},
            "tests": [{"name": "t1", "run_modes": ["inherited"]}],
        }
        merged, selected, _, _ = _merge_framework_config(
            profile, dut, Path("unit_sim_cfg.toml"), "unit_profile"
        )
        self.assertEqual(selected, "cocotb")
        flow = make_dut(merged)
        catalog = load_test_catalog(flow, Path("."))
        mode = selected_run_mode(merged, catalog.tests["t1"], Namespace(run_mode=None))
        self.assertEqual(mode["timeout_sec"], 120)

    def test_dut_entry_overrides_profile_entry(self):
        profile = {
            "frameworks": {"cocotb": {}},
            "run_modes": {"shared": {"timeout_sec": 120}},
        }
        dut = {
            "frameworks": {"cocotb": {}},
            "run_modes": {"shared": {"timeout_sec": 30}},
        }
        merged, _, _, _ = _merge_framework_config(
            profile, dut, Path("unit_sim_cfg.toml"), "unit_profile"
        )
        self.assertEqual(merged["run_modes"]["shared"]["timeout_sec"], 30)


class GroupMemberValidation(unittest.TestCase):
    def test_local_members_pass(self):
        raw = inline_raw(SMOKE, [{"name": "t1", "run_modes": ["smoke"]}])
        raw["groups"] = [{"name": "g1", "tests": ["t1"]}]
        catalog = load_test_catalog(make_dut(raw), Path("."))
        self.assertEqual(catalog.groups["g1"], ["t1"])

    def test_missing_member_rejected_with_source_group_and_test(self):
        raw = inline_raw(SMOKE, [{"name": "t1", "run_modes": ["smoke"]}])
        raw["groups"] = [{"name": "g1", "tests": ["t1", "missing_test"]}]
        flow = make_dut(raw)
        with self.assertRaises(ConfigError) as ctx:
            load_test_catalog(flow, Path("."))
        message = str(ctx.exception)
        self.assertIn(str(flow.path), message)
        self.assertIn("g1", message)
        self.assertIn("missing_test", message)

    def test_group_may_reference_tests_from_included_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "leaf.toml").write_text(
                'schema_version = 1\n[[tests]]\nname = "t_leaf"\nrun_modes = ["smoke"]\n'
            )
            (root / "all.toml").write_text(
                'schema_version = 1\nincludes = ["leaf.toml"]\n'
                '[[groups]]\nname = "g_root"\ntests = ["t_leaf"]\n'
            )
            flow = make_dut({"run_modes": SMOKE, "testlist": {"path": str(root / "all.toml")}})
            catalog = load_test_catalog(flow, root)
            self.assertEqual(catalog.groups["g_root"], ["t_leaf"])

    def test_missing_member_in_included_group_names_that_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "leaf.toml").write_text(
                'schema_version = 1\n'
                '[[tests]]\nname = "t_leaf"\nrun_modes = ["smoke"]\n'
                '[[groups]]\nname = "g_leaf"\ntests = ["t_gone"]\n'
            )
            (root / "all.toml").write_text('schema_version = 1\nincludes = ["leaf.toml"]\n')
            flow = make_dut({"run_modes": SMOKE, "testlist": {"path": str(root / "all.toml")}})
            with self.assertRaises(ConfigError) as ctx:
                load_test_catalog(flow, root)
            message = str(ctx.exception)
            self.assertIn("leaf.toml", message)
            self.assertIn("g_leaf", message)
            self.assertIn("t_gone", message)

    def test_membership_in_multiple_groups_is_legal(self):
        raw = inline_raw(SMOKE, [{"name": "t1", "run_modes": ["smoke"]}])
        raw["groups"] = [
            {"name": "g1", "tests": ["t1"]},
            {"name": "g2", "tests": ["t1"]},
        ]
        catalog = load_test_catalog(make_dut(raw), Path("."))
        # Selecting both groups runs the shared member once (first-seen order).
        self.assertEqual(expand_items(catalog, ["g1", "g2"], True), ["t1"])


class RuntimeSelectionDefenses(unittest.TestCase):
    # Directly constructed catalogs bypass load_test_catalog; selection must
    # still fail with ConfigError, never a raw KeyError (the #431 reproduce).
    def test_expand_items_rejects_phantom_group_member(self):
        catalog = TestCatalog(None, {}, {"smoke": ["missing_test"]})
        with self.assertRaises(ConfigError) as ctx:
            expand_items(catalog, ["smoke"], True)
        self.assertIn("missing_test", str(ctx.exception))

    def test_target_plan_rejects_unknown_item(self):
        catalog = TestCatalog(None, {}, {})
        with self.assertRaises(ConfigError) as ctx:
            target_plan(catalog, {}, ["missing_test"])
        self.assertIn("missing_test", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
