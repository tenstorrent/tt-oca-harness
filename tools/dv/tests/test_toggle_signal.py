# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Tests for the signal-level toggle family derived from Verilator's bit-edge points.

The database built here holds four declared variables over two hierarchies: a two-bit
vector whose low bit toggles both ways, a struct whose members never toggle, a scalar
clock, and a same-named vector one level down. One line point keeps the other families
in the picture.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib.coverage_model import (  # noqa: E402
    metrics_from_observations,
    toggle_signal_name,
)
from runlib.coverage_parsers.verilator import parse_verilator_details  # noqa: E402
from runlib.coverage_policy import (  # noqa: E402
    apply_coverage_policy,
    evaluate_thresholds,
    load_coverage_policy,
)

TOOL = "verilator"
DUT = "fixture"
SOURCE = "hw/common/och_prim/rtl/prim_fixture.sv"
OTHER_SOURCE = "hw/common/och_prim/rtl/prim_fixture_sub.sv"
TOP = "fixture_top.u_dut"
SUB = "fixture_top.u_dut.u_sub"
# Verilator coverage points as (hierarchy, source, line, type, object, count).
COVERAGE_POINTS = [
    (TOP, SOURCE, 10, "toggle", "data_i[0]:0->1", 5),
    (TOP, SOURCE, 10, "toggle", "data_i[0]:1->0", 3),
    (TOP, SOURCE, 10, "toggle", "data_i[1]:0->1", 0),
    (TOP, SOURCE, 10, "toggle", "data_i[1]:1->0", 0),
    (TOP, SOURCE, 11, "toggle", "rsp_o.valid:0->1", 0),
    (TOP, SOURCE, 11, "toggle", "rsp_o.valid:1->0", 0),
    (TOP, SOURCE, 11, "toggle", "rsp_o.bank_dout[3][2]:0->1", 0),
    (TOP, SOURCE, 12, "toggle", "clk_i:0->1", 7),
    (TOP, SOURCE, 12, "toggle", "clk_i:1->0", 7),
    (SUB, OTHER_SOURCE, 20, "toggle", "data_i[0]:0->1", 0),
    (SUB, OTHER_SOURCE, 20, "toggle", "data_i[0]:1->0", 0),
    (TOP, SOURCE, 30, "line", "block", 9),
]
# Signal, bit-edge member count, summed count, covered.
EXPECTED_SIGNALS = [
    (TOP, SOURCE, 10, "data_i", 4, 8, True),
    (TOP, SOURCE, 11, "rsp_o", 3, 0, False),
    (TOP, SOURCE, 12, "clk_i", 2, 14, True),
    (SUB, OTHER_SOURCE, 20, "data_i", 2, 0, False),
]

POLICY_TOML = """\
schema_version = 1
dut = "fixture"
scope_epoch = "fixture-v1"

[[thresholds]]
id = "toggle-signal-top"
metric_family = "toggle_signal"
scope = "fixture_top.u_dut"
population = "effective"
minimum_percent = 90.0

[[holes]]
id = "toggle-signal-rsp_o"
title = "rsp_o is never driven"
category = "tied_off"
disposition = "waive"
status = "accepted"
confidence = "high"
rationale = "The response port is tied off in this configuration."
owner = "fixture-dv"
reviewer = "fixture-dv"
date = "2026-09-01"
[[holes.native]]
tool = "verilator"
metric_family = "toggle_signal"
hierarchy = "fixture_top.u_dut"
line = 11
"""


def coverage_dat(points: list[tuple[str, str, int, str, str, int]]) -> str:
    """The merged Verilator coverage database: one `C '<key>' <count>` line per point. A key
    is the point's fields, each written as `\\x01<name>\\x02<value>`."""
    lines = ["# SystemC::Coverage-3"]
    for hierarchy, source, line, kind, object_name, count in points:
        fields = [
            ("f", source),
            ("l", str(line)),
            ("n", "7"),
            ("t", kind),
            ("page", f"v_{kind}/prim_fixture_"),
            ("o", object_name),
            ("h", hierarchy),
        ]
        key = "".join(f"\x01{name}\x02{value}" for name, value in fields)
        lines.append(f"C '{key}' {count}")
    return "\n".join(lines) + "\n"


def locator_field(locator: str, key: str) -> str:
    """The value of `key` in a `|`-joined native locator."""
    for part in locator.split("|"):
        name, separator, value = part.partition("=")
        if separator and name == key:
            return value
    raise KeyError(key)


class ToggleSignalName(unittest.TestCase):
    def test_selections_and_the_edge_suffix_are_dropped(self):
        for object_name, expected in (
            ("a[3]:0->1", "a"),
            ("a.b[1][2]:1->0", "a"),
            ("x:0->1", "x"),
            ("sep_cpu_tcm_rsp.dccm_bank_dout[0][0]:0->1", "sep_cpu_tcm_rsp"),
            ("clk_ref_i:1->0", "clk_ref_i"),
        ):
            with self.subTest(object_name=object_name):
                self.assertEqual(toggle_signal_name(object_name), expected)


class FixtureCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def parse(self, points=None):
        merged = self.root / "merged.dat"
        merged.write_text(
            coverage_dat(COVERAGE_POINTS if points is None else points), encoding="utf-8"
        )
        return parse_verilator_details(
            dut=DUT,
            tool=TOOL,
            target="default",
            build_fingerprint="0aecd4b109ca",
            merged=merged,
        )

    def policy(self, text: str = POLICY_TOML):
        path = self.root / "coverage_policy.toml"
        path.write_text(text, encoding="utf-8")
        return load_coverage_policy(path, expected_dut=DUT)

    def derived(self, details):
        return [
            observation
            for observation in details.observations
            if observation.metric_family == "toggle_signal"
        ]


class DerivedObservations(FixtureCase):
    def test_bit_edges_collapse_into_one_observation_per_signal(self):
        derived = self.derived(self.parse())
        self.assertEqual(
            [
                (
                    observation.hierarchy,
                    observation.source,
                    observation.line,
                    locator_field(observation.native_locator, "o"),
                    int(locator_field(observation.native_locator, "bits")),
                    observation.count,
                    observation.covered,
                )
                for observation in derived
            ],
            EXPECTED_SIGNALS,
        )
        for observation in derived:
            with self.subTest(locator=observation.native_locator):
                self.assertEqual(observation.native_metric, "toggle_signal")
                self.assertEqual(observation.category, "toggle_signal")
                self.assertEqual(observation.goal, 1)
                self.assertEqual(observation.tool, TOOL)

    def test_the_locator_carries_the_group_and_the_member_count(self):
        derived = self.derived(self.parse())
        self.assertEqual(
            derived[1].native_locator,
            f"f={SOURCE}|h={TOP}|l=11|o=rsp_o|t=toggle_signal|bits=3",
        )

    def test_the_bit_edge_points_are_left_alone(self):
        details = self.parse()
        toggles = [
            observation
            for observation in details.observations
            if observation.metric_family == "toggle"
        ]
        self.assertEqual(len(toggles), 11)
        self.assertEqual(sum(1 for observation in toggles if observation.covered), 4)
        self.assertTrue(
            all(locator_field(o.native_locator, "t") == "toggle" for o in toggles),
        )

    def test_the_family_is_a_metric_record_of_its_own(self):
        records = {
            record.metric_family: record
            for record in metrics_from_observations(self.parse().observations)
        }
        self.assertEqual(sorted(records), ["line", "toggle", "toggle_signal"])
        signals = records["toggle_signal"]
        self.assertEqual((signals.covered, signals.total, signals.excluded), (2, 4, 0))
        self.assertEqual(signals.raw_percent, 50.0)

    def test_ids_are_stable_and_distinct_per_group(self):
        first = [observation.id for observation in self.derived(self.parse())]
        second = [observation.id for observation in self.derived(self.parse())]
        self.assertEqual(first, second)
        self.assertEqual(len(set(first)), len(EXPECTED_SIGNALS))
        self.assertTrue(all(identifier.startswith("VLTCOV-") for identifier in first))

    def test_a_database_without_toggles_has_no_derived_family(self):
        details = self.parse([point for point in COVERAGE_POINTS if point[3] != "toggle"])
        self.assertEqual(self.derived(details), [])
        self.assertEqual([record.metric_family for record in details.metrics], ["line"])


class PolicyOnTheDerivedFamily(FixtureCase):
    def test_a_scoped_threshold_grades_the_signals_of_one_hierarchy(self):
        details = self.parse()
        outcomes = evaluate_thresholds(details, self.policy())
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0]["actual_percent"], 66.6667)
        self.assertEqual(outcomes[0]["unclassified_points"], 1)
        self.assertFalse(outcomes[0]["met"])

    def test_a_native_selector_claims_exactly_the_one_derived_observation(self):
        details = apply_coverage_policy(self.parse(), self.policy())
        matched = details.policy_application["matched"]
        self.assertEqual([entry["policy_id"] for entry in matched], ["toggle-signal-rsp_o"])
        claimed = [
            observation
            for observation in details.observations
            if observation.policy_id == "toggle-signal-rsp_o"
        ]
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0].metric_family, "toggle_signal")
        self.assertEqual(claimed[0].line, 11)
        self.assertEqual(claimed[0].status, "accepted")
        self.assertEqual(details.holes_summary()["by_metric"]["toggle_signal"], 2)
        self.assertEqual(details.thresholds[0]["actual_percent"], 100.0)
        self.assertTrue(details.thresholds[0]["met"])


if __name__ == "__main__":
    unittest.main()
