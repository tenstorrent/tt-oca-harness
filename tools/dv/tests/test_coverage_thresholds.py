# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for coverage policy grading: threshold populations, fail-closed policy rules,
and the comparison identity.

The policy grammar is the versioned, checked-in threshold configuration; these tests pin
what a rule grades, what a malformed or contradicted policy refuses, and what makes two
grades comparable.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib.coverage_model import CoverageDetails, CoverageObservation  # noqa: E402
from runlib.coverage_policy import (  # noqa: E402
    CoveragePolicy,
    HoleRule,
    ThresholdRule,
    apply_coverage_policy,
    load_coverage_policy,
)
from runlib.models import ConfigError  # noqa: E402

DUT = "fixture"
TOOL = "verilator"
OUTCOME_FIELDS = {
    "id",
    "metric_family",
    "population",
    "scope",
    "minimum_percent",
    "actual_percent",
    "max_unclassified_points",
    "unclassified_points",
    "met",
}
BASELINE_POLICY = """\
schema_version = 1
dut = "fixture"
scope_epoch = "fixture-v1"

[[thresholds]]
id = "line-effective"
metric_family = "line"
minimum_percent = 98.0
max_unclassified_points = 0

[[holes]]
id = "line-unreachable"
title = "unreachable arm"
category = "unreachable"
disposition = "waive"
status = "accepted"
confidence = "high"
rationale = "fixture"
owner = "fixture-dv"
reviewer = "fixture-dv"
[[holes.native]]
tool = "verilator"
metric_family = "line"
native_locator = "l-u0"
"""


def observation(ident, family="line", covered=True, hierarchy="top.u_a", native_metric=None):
    return CoverageObservation(
        id=ident,
        tool=TOOL,
        metric_family=family,
        native_metric=native_metric or family,
        native_locator=ident,
        count=1 if covered else 0,
        covered=covered,
        hierarchy=hierarchy,
        source="fixture.sv",
        line=1,
    )


def points(prefix, family, covered, uncovered, hierarchy="top.u_a", native_metric=None):
    return [
        observation(f"{prefix}-c{i}", family, True, hierarchy, native_metric)
        for i in range(covered)
    ] + [
        observation(f"{prefix}-u{i}", family, False, hierarchy, native_metric)
        for i in range(uncovered)
    ]


def details(observations, target="t1", fingerprint="fp1"):
    return CoverageDetails(
        dut=DUT,
        tool=TOOL,
        target=target,
        build_fingerprint=fingerprint,
        details_available=True,
        observations_complete=True,
        observations=observations,
    )


def rule(**overrides):
    values = {
        "id": "line-effective",
        "tool": "*",
        "target": "*",
        "scope": "*",
        "metric_family": "line",
        "population": "effective",
        "minimum_percent": 98.0,
        "max_unclassified_points": None,
    }
    values.update(overrides)
    return ThresholdRule(**values)


def hole(
    ident,
    selector,
    *,
    status="accepted",
    disposition="waive",
    confidence="high",
    expected=1,
):
    return HoleRule(
        id=ident,
        title=ident,
        category="unreachable",
        disposition=disposition,
        status=status,
        confidence=confidence,
        rationale="fixture",
        owner="fixture-dv",
        reviewer="fixture-dv",
        issues=[],
        expected_matches=expected,
        selectors=[selector],
    )


def policy(thresholds=(), holes=(), *, scope_epoch="fixture-v1", sha="policy-sha"):
    return CoveragePolicy(
        path=Path("/fixture/coverage_policy.toml"),
        dut=DUT,
        scope_epoch=scope_epoch,
        thresholds=list(thresholds),
        holes=list(holes),
        sha256=sha,
    )


def graded(observations, holes=(), thresholds=(), **policy_overrides):
    return apply_coverage_policy(
        details(observations), policy(thresholds, holes, **policy_overrides)
    )


def outcomes(graded_details):
    return {outcome["id"]: outcome for outcome in graded_details.thresholds}


LINE_WAIVERS = (hole("w0", {"native_locator": "l-u0"}), hole("w1", {"native_locator": "l-u1"}))


def line_points():
    """100 line points, 97 covered; LINE_WAIVERS accept two of the three holes."""
    return points("l", "line", 97, 3)


class ThresholdPopulations(unittest.TestCase):
    def test_effective_grades_after_waivers_and_raw_grades_the_unwaived_figure(self):
        result = outcomes(
            graded(line_points(), LINE_WAIVERS, [rule(id="eff"), rule(id="raw", population="raw")])
        )
        self.assertEqual(set(result["eff"]), OUTCOME_FIELDS)
        self.assertEqual(result["raw"]["actual_percent"], 97.0)
        self.assertFalse(result["raw"]["met"])
        self.assertEqual(result["eff"]["actual_percent"], round(100.0 * 97 / 98, 4))
        self.assertTrue(result["eff"]["met"])
        self.assertEqual(result["eff"]["unclassified_points"], 1)

    def test_unclassified_points_fail_the_rule_closed(self):
        strict = rule(id="strict", max_unclassified_points=0)
        lenient = rule(id="lenient", max_unclassified_points=1)
        result = outcomes(graded(line_points(), LINE_WAIVERS, [strict, lenient]))
        self.assertFalse(result["strict"]["met"])
        self.assertTrue(result["lenient"]["met"])
        self.assertEqual(result["strict"]["actual_percent"], result["lenient"]["actual_percent"])

    def test_scope_tool_and_target_select_the_rules_and_the_points(self):
        observations = points("a", "line", 9, 1, hierarchy="top.u_a") + points(
            "b", "line", 0, 10, hierarchy="top.u_b"
        )
        result = outcomes(
            graded(
                observations,
                thresholds=[
                    rule(id="all", minimum_percent=40.0),
                    rule(id="a", scope="top.u_a*", minimum_percent=90.0),
                    rule(id="b", scope="top.u_b*", minimum_percent=1.0),
                    rule(id="other-tool", tool="vcs"),
                    rule(id="other-target", target="t2"),
                ],
            )
        )
        self.assertEqual(set(result), {"all", "a", "b"})
        self.assertEqual((result["all"]["actual_percent"], result["all"]["met"]), (45.0, True))
        self.assertEqual((result["a"]["actual_percent"], result["a"]["met"]), (90.0, True))
        self.assertEqual((result["b"]["actual_percent"], result["b"]["met"]), (0.0, False))
        self.assertEqual(result["a"]["unclassified_points"], 1)
        self.assertEqual(result["b"]["unclassified_points"], 10)

    def test_a_family_with_several_native_metrics_grades_its_weakest(self):
        observations = points("s", "fsm", 10, 0, native_metric="fsm_state") + points(
            "t", "fsm", 5, 5, native_metric="fsm_transition"
        )
        result = outcomes(
            graded(observations, thresholds=[rule(metric_family="fsm", minimum_percent=60.0)])
        )
        self.assertEqual(result["line-effective"]["actual_percent"], 50.0)
        self.assertFalse(result["line-effective"]["met"])

    def test_a_family_without_points_is_not_met(self):
        result = outcomes(graded(line_points(), thresholds=[rule(metric_family="toggle")]))
        self.assertIsNone(result["line-effective"]["actual_percent"])
        self.assertFalse(result["line-effective"]["met"])


class PolicyApplication(unittest.TestCase):
    def test_a_waiver_stamps_its_points_and_leaves_the_effective_population(self):
        result = graded(line_points(), LINE_WAIVERS)
        waived = {obs.id: obs for obs in result.observations if obs.policy_id}
        self.assertEqual(set(waived), {"l-u0", "l-u1"})
        self.assertEqual(
            (waived["l-u0"].status, waived["l-u0"].disposition, waived["l-u0"].owner),
            ("accepted", "waive", "fixture-dv"),
        )
        [metric] = result.metrics
        self.assertEqual((metric.covered, metric.total, metric.excluded), (97, 100, 2))
        self.assertEqual(
            (metric.raw_percent, metric.effective_percent), (97.0, round(100.0 * 97 / 98, 4))
        )
        summary = result.holes_summary()
        self.assertEqual(
            (
                summary["open"],
                summary["accepted"],
                summary["unclassified"],
                summary["hole_group_count"],
            ),
            (1, 2, 1, 2),
        )
        self.assertEqual(
            [entry["policy_id"] for entry in result.policy_application["matched"]], ["w0", "w1"]
        )
        self.assertEqual(result.policy_application["policy_sha256"], "policy-sha")

    def test_a_selector_matching_the_wrong_number_of_points_is_refused(self):
        with self.assertRaisesRegex(ConfigError, "matched 0 observation\\(s\\), expected 1"):
            graded(line_points(), [hole("gone", {"native_locator": "l-u9"})])
        with self.assertRaisesRegex(ConfigError, "matched 3 observation\\(s\\), expected 1"):
            graded(line_points(), [hole("wide", {"native_locator": "l-u*"})])
        graded(line_points(), [hole("wide", {"native_locator": "l-u*"}, expected=3)])

    def test_an_accepted_waiver_on_a_covered_point_is_refused(self):
        with self.assertRaisesRegex(ConfigError, "unexpectedly matched a covered point"):
            graded(line_points(), [hole("stale", {"native_locator": "l-c0"})])
        graded(
            line_points(),
            [hole("tracked", {"native_locator": "l-c0"}, status="open", disposition="cover")],
        )

    def test_two_entries_claiming_one_point_are_refused(self):
        with self.assertRaisesRegex(ConfigError, "claimed by both"):
            graded(
                line_points(),
                [
                    hole("first", {"native_locator": "l-u0"}),
                    hole("second", {"native_locator": "l-u0"}),
                ],
            )

    def test_without_a_policy_the_raw_figure_is_the_only_grade(self):
        result = apply_coverage_policy(details(line_points()), None)
        self.assertEqual(result.thresholds, [])
        self.assertIsNone(result.policy_application["policy"])
        self.assertIsNone(result.policy_fingerprint)
        self.assertTrue(result.comparison_key.startswith("COVCMP-"))


class ComparisonIdentity(unittest.TestCase):
    def key(self, **kwargs):
        target = kwargs.pop("target", "t1")
        fingerprint = kwargs.pop("fingerprint", "fp1")
        observations = kwargs.pop("observations", line_points())
        result = apply_coverage_policy(details(observations, target, fingerprint), policy(**kwargs))
        return result.comparison_key

    def test_the_key_follows_policy_scope_epoch_build_and_target(self):
        base = self.key()
        self.assertEqual(base, self.key())
        self.assertNotEqual(base, self.key(sha="other-policy"))
        self.assertNotEqual(base, self.key(scope_epoch="fixture-v2"))
        self.assertNotEqual(base, self.key(fingerprint="fp2"))
        self.assertNotEqual(base, self.key(target="t2"))

    def test_the_key_ignores_the_hit_counts(self):
        self.assertEqual(self.key(), self.key(observations=points("l", "line", 50, 50)))


class PolicyFile(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def load(self, text, dut=DUT):
        path = self.root / "coverage_policy.toml"
        path.write_text(text)
        return load_coverage_policy(path, expected_dut=dut)

    def test_the_baseline_loads_with_the_grammar_defaults(self):
        loaded = self.load(BASELINE_POLICY)
        [threshold] = loaded.thresholds
        self.assertEqual(
            (threshold.tool, threshold.target, threshold.scope, threshold.population),
            ("*", "*", "*", "effective"),
        )
        [entry] = loaded.holes
        self.assertEqual(entry.expected_matches, 1)
        self.assertEqual(len(loaded.sha256), 64)

    def test_malformed_or_contradictory_policies_are_refused(self):
        cases = [
            ("schema_version = 1", "schema_version = 2", "schema_version must be 1"),
            ('dut = "fixture"', 'dut = "other"', "does not match"),
            ("minimum_percent = 98.0", "minimum_percent = 101.0", "between 0 and 100"),
            (
                "minimum_percent = 98.0",
                'population = "waived"\nminimum_percent = 98.0',
                "raw. or .effective",
            ),
            ("max_unclassified_points = 0", "max_unclassified_points = -1", ">= 0"),
            ('category = "unreachable"', 'category = "vibes"', "category is unsupported"),
            ('disposition = "waive"', 'disposition = "ignore"', "disposition is unsupported"),
            ('status = "accepted"', 'status = "pending"', "status is unsupported"),
            ('confidence = "high"', 'confidence = "low"', "low-confidence"),
            (
                'disposition = "waive"\nstatus = "accepted"',
                'disposition = "cover"\nstatus = "open"',
                "requires a GitHub issue URL",
            ),
            (
                'rationale = "fixture"',
                'rationale = "fixture"\ndate = "2026-09-01"',
                r"unsupported key\(s\): date",
            ),
            (
                'rationale = "fixture"',
                'rationale = "fixture"\nexpires = "2027-03-31"',
                r"unsupported key\(s\): expires",
            ),
            ('owner = "fixture-dv"', 'ownr = "fixture-dv"', r"unsupported key\(s\): ownr"),
            (
                'rationale = "fixture"',
                'rationale = "fixture"\nexpected_matches = 0',
                "positive integer",
            ),
            ('native_locator = "l-u0"', 'locator = "l-u0"', "unsupported selector key"),
            (
                "[[holes.native]]\n",
                "",
                r"unsupported key\(s\): metric_family, native_locator, tool",
            ),
            (
                '[[holes.native]]\ntool = "verilator"\nmetric_family = "line"\n'
                'native_locator = "l-u0"\n',
                "",
                "at least one",
            ),
        ]
        for old, new, message in cases:
            with self.subTest(message=message):
                text = BASELINE_POLICY.replace(old, new)
                self.assertNotEqual(text, BASELINE_POLICY)
                with self.assertRaisesRegex(ConfigError, message):
                    self.load(text)
        with self.assertRaisesRegex(ConfigError, "duplicate hole id"):
            self.load(BASELINE_POLICY + BASELINE_POLICY[BASELINE_POLICY.index("[[holes]]") :])
        with self.assertRaisesRegex(ConfigError, "does not match"):
            self.load(BASELINE_POLICY, dut="other")


if __name__ == "__main__":
    unittest.main()
