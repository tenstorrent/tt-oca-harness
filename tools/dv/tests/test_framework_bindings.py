# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for per-framework `module` binding maps: parsing, selection under a framework,
the implicit selection, the `--list` marks and counts, and result recording.

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

from runlib.cli import (  # noqa: E402
    _binding_marks,
    _binding_matrix,
    _flow_view_dict,
    _implemented_summary,
    requested_items,
    validate_item_bindings,
)
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

[[tests]]
name = "uvm_only_test"
module = { uvm = "uvm_only_test" }

[[tests]]
name = "uvm_only_declared_test"
module = { cocotb = false, uvm = "uvm_only_declared_test" }

[[groups]]
name = "all"
tests = ["both_test", "excluded_test", "missing_test", "uvm_only_test", "uvm_only_declared_test"]

[[groups]]
name = "declared"
tests = ["both_test", "excluded_test"]

[[groups]]
name = "only_excluded"
tests = ["excluded_test"]

[[groups]]
name = "uvm_side"
tests = ["uvm_only_test", "uvm_only_declared_test"]
"""

ALL = ["both_test", "excluded_test", "missing_test", "uvm_only_test", "uvm_only_declared_test"]


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
    framework: str, requested: list[str], expanded: list[str], **extra: Any
) -> tuple[list[str], Namespace]:
    flow, catalog = load(framework)
    args = Namespace(items=requested, **extra)
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

    def test_map_may_omit_the_default_framework(self):
        _flow, catalog = load("cocotb")
        test = catalog.tests["uvm_only_test"]
        self.assertEqual(test.module, "")
        self.assertEqual(test.bindings, {"uvm": "uvm_only_test"})
        self.assertEqual(test.excluded, frozenset())
        declared = catalog.tests["uvm_only_declared_test"]
        self.assertEqual(declared.module, "")
        self.assertEqual(declared.excluded, frozenset({"cocotb"}))

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
    def test_group_runs_its_bound_subset_and_records_the_rest_apart(self):
        kept, args = select("uvm", ["all"], ALL)
        self.assertEqual(kept, ["both_test", "uvm_only_test", "uvm_only_declared_test"])
        self.assertEqual(args._skipped_excluded, ["excluded_test"])
        self.assertEqual(args._skipped_unimplemented, ["missing_test"])

    def test_default_view_skips_the_same_way(self):
        kept, args = select("cocotb", ["all"], ALL)
        self.assertEqual(kept, ["both_test", "excluded_test", "missing_test"])
        self.assertEqual(args._skipped_excluded, ["uvm_only_declared_test"])
        self.assertEqual(args._skipped_unimplemented, ["uvm_only_test"])

    def test_fully_bound_selection_records_nothing(self):
        kept, args = select("uvm", ["both_test"], ["both_test"])
        self.assertEqual(kept, ["both_test"])
        self.assertFalse(hasattr(args, "_skipped_excluded"))
        self.assertFalse(hasattr(args, "_skipped_unimplemented"))

    def test_explicit_excluded_name_errors(self):
        with self.assertRaises(ConfigError) as ctx:
            select("uvm", ["excluded_test"], ["excluded_test"])
        message = str(ctx.exception)
        self.assertIn("uvm = false", message)
        self.assertIn("implemented: cocotb", message)
        self.assertIn("--framework", message)

    def test_explicit_missing_name_errors(self):
        with self.assertRaises(ConfigError) as ctx:
            select("cocotb", ["uvm_only_test"], ["uvm_only_test"])
        message = str(ctx.exception)
        self.assertIn("no cocotb entry", message)
        self.assertIn("implemented: uvm", message)

    def test_explicit_name_beside_a_group_still_errors(self):
        with self.assertRaises(ConfigError) as ctx:
            select(
                "uvm", ["declared", "missing_test"], ["both_test", "excluded_test", "missing_test"]
            )
        message = str(ctx.exception)
        self.assertIn("missing_test", message)
        self.assertNotIn("excluded_test", message)

    def test_group_with_nothing_bound_is_an_error(self):
        with self.assertRaises(ConfigError) as ctx:
            select("uvm", ["only_excluded"], ["excluded_test"])
        message = str(ctx.exception)
        self.assertIn("left no runnable scenarios", message)
        self.assertIn("select a group or scenario implemented for `uvm`", message)

    def test_build_only_with_nothing_bound_says_how_to_pick_a_target(self):
        with self.assertRaises(ConfigError) as ctx:
            select(
                "cocotb", ["uvm_side"], ["uvm_only_test", "uvm_only_declared_test"], build_only=True
            )
        message = str(ctx.exception)
        self.assertIn("a build-only run selects scenarios to pick the build target", message)
        self.assertIn("--items", message)


class ImplicitSelection(unittest.TestCase):
    def test_smoke_group_wins(self):
        text = TESTLIST + '\n[[groups]]\nname = "smoke"\ntests = ["both_test"]\n'
        _flow, catalog = load("uvm", text)
        self.assertEqual(requested_items(catalog, Namespace(items=None), "uvm"), ["smoke"])

    def test_explicit_items_pass_through(self):
        _flow, catalog = load("uvm")
        self.assertEqual(requested_items(catalog, Namespace(items=["all"]), "uvm"), ["all"])

    def test_fallback_is_the_first_scenario_the_framework_implements(self):
        text = (
            "schema_version = 1\n"
            '[[tests]]\nname = "cocotb_first"\nmodule = "cocotb_first"\n'
            '[[tests]]\nname = "uvm_second"\nmodule = { cocotb = "x", uvm = "uvm_second" }\n'
        )
        _flow, catalog = load("uvm", text)
        self.assertEqual(requested_items(catalog, Namespace(items=None), "uvm"), ["uvm_second"])
        _flow, catalog = load("cocotb", text)
        self.assertEqual(
            requested_items(catalog, Namespace(items=None), "cocotb"), ["cocotb_first"]
        )

    def test_fallback_with_nothing_implemented_names_the_framework(self):
        text = 'schema_version = 1\n[[tests]]\nname = "cocotb_only"\nmodule = "cocotb_only"\n'
        _flow, catalog = load("uvm", text)
        with self.assertRaises(ConfigError) as ctx:
            requested_items(catalog, Namespace(items=None), "uvm")
        message = str(ctx.exception)
        self.assertIn("no scenario implemented for framework `uvm`", message)
        self.assertIn("--items", message)


class ListViews(unittest.TestCase):
    def test_counts_sum_to_the_catalog_size(self):
        flow, catalog = load("uvm")
        matrix = _binding_matrix(flow, catalog)
        self.assertEqual(matrix["cocotb"], {"implemented": 3, "excluded": 1, "missing": 1})
        self.assertEqual(matrix["uvm"], {"implemented": 3, "excluded": 1, "missing": 1})
        self.assertEqual(
            _implemented_summary(flow, catalog),
            "cocotb 3/5 (1 excluded, 1 missing), uvm 3/5 (1 excluded, 1 missing)",
        )

    def test_marks_tell_the_binding_states_apart(self):
        _flow, catalog = load("cocotb")
        marks = {name: _binding_marks(test, "cocotb") for name, test in catalog.tests.items()}
        self.assertEqual(marks["both_test"], ["+uvm"])
        self.assertEqual(marks["excluded_test"], ["-uvm"])
        self.assertEqual(marks["missing_test"], [])
        self.assertEqual(marks["uvm_only_test"], ["+uvm", "no cocotb"])
        self.assertEqual(marks["uvm_only_declared_test"], ["+uvm", "-cocotb"])

    def test_view_entry_keeps_its_shape(self):
        entry = _flow_view_dict(make_flow("uvm", {}))
        self.assertEqual(entry["framework"], "uvm")
        self.assertEqual(entry["frameworks"], ["cocotb", "uvm"])
        self.assertNotIn("partial", entry)


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
