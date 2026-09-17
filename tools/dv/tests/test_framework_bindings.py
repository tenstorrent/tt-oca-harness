# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for per-framework `module` binding maps: `false` exclusions and selection.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib.cli import _binding_matrix, validate_item_bindings  # noqa: E402
from runlib.config import load_test_catalog  # noqa: E402
from runlib.models import ConfigError, Dut, TestCatalog  # noqa: E402
from runlib.results import result_payload  # noqa: E402

SMOKE = {"smoke": {"timeout_sec": 60, "args": []}}

TESTLIST = """
schema_version = 1

[[tests]]
name = "both_test"
module = { cocotb = "both_test", uvm = "both_test" }

[[tests]]
name = "excluded_test"
module = { cocotb = "excluded_test", uvm = false }

[[tests]]
name = "missing_test"
module = "missing_test"

[[groups]]
name = "all"
tests = ["both_test", "excluded_test", "missing_test"]

[[groups]]
name = "declared"
tests = ["both_test", "excluded_test"]

[[groups]]
name = "only_excluded"
tests = ["excluded_test"]
"""


def make_flow(framework: str, raw: dict) -> Dut:
    return Dut(
        name="unit",
        kind="sim",
        description="unit-test DUT",
        framework=framework,
        visibility="public",
        runnability="runnable",
        license="Apache-2.0",
        root=".",
        default_tool="vcs",
        tools=["vcs"],
        path=Path("test_sim_cfg.toml"),
        raw=raw,
        frameworks=["cocotb", "uvm"],
        default_framework="cocotb",
    )


def load(framework: str, text: str = TESTLIST) -> tuple[Dut, TestCatalog]:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "all.toml").write_text(text)
        flow = make_flow(
            framework, {"run_modes": SMOKE, "testlist": {"path": str(root / "all.toml")}}
        )
        return flow, load_test_catalog(flow, root)


def select(
    framework: str, requested: list[str], expanded: list[str], skip: bool = False
) -> tuple[list[str], Namespace]:
    flow, catalog = load(framework)
    args = Namespace(items=requested, skip_unimplemented=skip)
    kept = validate_item_bindings(flow, catalog, expanded, args)
    return kept, args


class BindingMapParsing(unittest.TestCase):
    def test_false_marks_the_framework_excluded(self):
        _flow, catalog = load("uvm")
        test = catalog.tests["excluded_test"]
        self.assertEqual(test.module, "")
        self.assertEqual(test.excluded, frozenset({"uvm"}))
        self.assertEqual(test.bindings, {"cocotb": "excluded_test"})

    def test_excluded_framework_leaves_other_views_bound(self):
        _flow, catalog = load("cocotb")
        self.assertEqual(catalog.tests["excluded_test"].module, "excluded_test")

    def test_bare_string_has_no_exclusions(self):
        _flow, catalog = load("uvm")
        test = catalog.tests["missing_test"]
        self.assertEqual(test.module, "")
        self.assertEqual(test.excluded, frozenset())
        self.assertEqual(test.bindings, {"cocotb": "missing_test"})

    def test_true_is_rejected(self):
        text = 'schema_version = 1\n[[tests]]\nname = "t"\nmodule = { cocotb = "t", uvm = true }\n'
        with self.assertRaises(ConfigError) as ctx:
            load("uvm", text)
        self.assertIn("t.module.uvm must be a non-empty string or `false`", str(ctx.exception))

    def test_empty_string_is_rejected(self):
        text = 'schema_version = 1\n[[tests]]\nname = "t"\nmodule = { cocotb = "t", uvm = "" }\n'
        with self.assertRaises(ConfigError):
            load("uvm", text)

    def test_exclusions_alone_are_rejected(self):
        text = 'schema_version = 1\n[[tests]]\nname = "t"\nmodule = { uvm = false }\n'
        with self.assertRaises(ConfigError) as ctx:
            load("uvm", text)
        self.assertIn("at least one framework binding", str(ctx.exception))

    def test_exclusion_for_unimplemented_framework_is_rejected(self):
        text = (
            'schema_version = 1\n[[tests]]\nname = "t"\nmodule = { cocotb = "t", questa = false }\n'
        )
        with self.assertRaises(ConfigError) as ctx:
            load("uvm", text)
        message = str(ctx.exception)
        self.assertIn("exclusion(s)", message)
        self.assertIn("questa", message)


class SelectionUnderAFramework(unittest.TestCase):
    def test_group_member_declared_false_skips_without_flag(self):
        kept, args = select("uvm", ["declared"], ["both_test", "excluded_test"])
        self.assertEqual(kept, ["both_test"])
        self.assertEqual(args._skipped_excluded, ["excluded_test"])
        self.assertEqual(args._skipped_unimplemented, [])

    def test_group_member_with_no_entry_errors_without_flag(self):
        with self.assertRaises(ConfigError) as ctx:
            select("uvm", ["all"], ["both_test", "excluded_test", "missing_test"])
        message = str(ctx.exception)
        self.assertIn("missing_test", message)
        self.assertIn("no uvm entry", message)
        self.assertIn("--skip-unimplemented", message)
        self.assertIn("declare `uvm = false`", message)
        self.assertNotIn("excluded_test", message)

    def test_flag_skips_missing_and_records_both_kinds_apart(self):
        kept, args = select(
            "uvm", ["all"], ["both_test", "excluded_test", "missing_test"], skip=True
        )
        self.assertEqual(kept, ["both_test"])
        self.assertEqual(args._skipped_excluded, ["excluded_test"])
        self.assertEqual(args._skipped_unimplemented, ["missing_test"])

    def test_explicit_excluded_name_errors_even_with_flag(self):
        with self.assertRaises(ConfigError) as ctx:
            select("uvm", ["excluded_test"], ["excluded_test"], skip=True)
        message = str(ctx.exception)
        self.assertIn("uvm = false", message)
        self.assertIn("implemented: cocotb", message)
        self.assertNotIn("--skip-unimplemented", message)

    def test_explicit_missing_name_errors_even_with_flag(self):
        with self.assertRaises(ConfigError) as ctx:
            select("uvm", ["missing_test"], ["missing_test"], skip=True)
        self.assertIn("no uvm entry", str(ctx.exception))

    def test_group_of_only_excluded_members_is_an_error(self):
        with self.assertRaises(ConfigError) as ctx:
            select("uvm", ["only_excluded"], ["excluded_test"])
        self.assertIn("left no runnable scenarios", str(ctx.exception))

    def test_default_framework_view_is_untouched(self):
        kept, args = select("cocotb", ["all"], ["both_test", "excluded_test", "missing_test"])
        self.assertEqual(kept, ["both_test", "excluded_test", "missing_test"])
        self.assertFalse(hasattr(args, "_skipped_excluded"))
        self.assertFalse(hasattr(args, "_skipped_unimplemented"))


class BindingMatrix(unittest.TestCase):
    def test_counts_sum_to_the_catalog_size(self):
        flow, catalog = load("uvm")
        matrix = _binding_matrix(flow, catalog)
        self.assertEqual(matrix["cocotb"], {"implemented": 3, "excluded": 0, "missing": 0})
        self.assertEqual(matrix["uvm"], {"implemented": 1, "excluded": 1, "missing": 1})


class ResultRecording(unittest.TestCase):
    def payload(self, args: Namespace | None) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload: dict[str, Any] = result_payload(
                flow=make_flow("uvm", {}),
                root=root,
                tool="vcs",
                run_dir=root / "run",
                stages=[],
                dry_run=True,
                args=args,
                versions={},
                git_metadata={},
            )
            return payload

    def test_both_skip_lists_are_recorded_side_by_side(self):
        payload = self.payload(
            Namespace(_skipped_excluded=["excluded_test"], _skipped_unimplemented=[])
        )
        self.assertEqual(
            payload["selection"],
            {"skipped_unimplemented": [], "skipped_excluded": ["excluded_test"]},
        )

    def test_nothing_skipped_means_no_selection_block(self):
        self.assertNotIn("selection", self.payload(Namespace()))
        self.assertNotIn("selection", self.payload(None))


if __name__ == "__main__":
    unittest.main()
