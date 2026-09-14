# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Scoreboard base: the feature registry and the two-stream pairing behind the bench scoreboard.

A bench ``<Dut>Scoreboard`` registers one feature per reference model
(``add_feature``) and connects two analysis streams per feature: the observed
VIP monitor stream to ``observed_export(feature)`` and the ``expected_ap`` of
that feature's ``<Dut><Feature>RefModel`` to ``expected_export(feature)``,
naming a lane when one feature is judged on several independent in-order
streams (one per monitored port). The base pairs the two queues of a lane in
observation order and hands each pair to ``compare_pair()``, which the bench
implements with ``compare_equal()`` or ``record_compare()``: a mismatch is
logged at once with feature, expected, observed, and context. Analysis
delivery order is unordered, so either stream may arrive first. A reset that
cancels predicted transactions withdraws them with ``flush_expected()``.
``check_phase`` reports items left unpaired, turns each feature into one
``CHK-SB-<FEATURE>`` record through the shared evidence recorder, and
finalizes it once; a required feature (``require_feature``, from the env cfg)
that ends with zero comparisons fails the run, so a scenario cannot pass
without exercising what it claims to check. The scoreboard holds no
expected-value state: prediction is the reference model's job.

The SV-UVM twin is ``ocah_scoreboard``. There a mismatch or an unpaired item is
a ``uvm_error`` that fails the run by itself; here both fold into the feature's
record, because a logged error does not fail a cocotb run. Pure Python apart
from the PyUVM component bases, so the pairing contract is validated
simulator-free (``examples/example_ocah_lib_selftest.py``).
"""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from ocah_checker import OcahChecker
from pyuvm import uvm_analysis_export, uvm_scoreboard

__all__ = ["OcahScoreboard", "OcahScoreboardError"]

_FEATURE_RE = re.compile(r"^[A-Za-z0-9_]+$")


class OcahScoreboardError(RuntimeError):
    """Raised on a scoreboard usage defect: unknown feature, missing ``compare_pair``."""


@dataclass
class _Feature:
    name: str
    required: bool = False
    compares: int = 0
    mismatches: int = 0
    unpaired: int = 0


class _StreamExport(uvm_analysis_export):
    """Analysis export routing one stream of one feature and lane into the scoreboard."""

    def __init__(self, name: str, parent: object, write_fn: Callable[[object], None]) -> None:
        super().__init__(name, parent)
        self._write_fn = write_fn

    def write(self, item: object) -> None:
        self._write_fn(item)


class OcahScoreboard(uvm_scoreboard):
    """Feature registry, per-lane pairing, per-feature counters, ``CHK-SB-*`` evidence."""

    def __init__(self, name: str, parent: object) -> None:
        super().__init__(name, parent)
        # Evidence identity for the CHK-SB-* records; a bench sets its own.
        self.name_tag = "ocah_scoreboard"
        self.evidence: OcahChecker | None = None
        self._features: dict[str, _Feature] = {}
        self._feature_order: list[str] = []
        # Two-stream pairing per feature and lane (pair key), in observation
        # order on both sides; _key_feature maps a key back to its feature.
        self._observed_q: dict[str, deque[object]] = {}
        self._expected_q: dict[str, deque[object]] = {}
        self._key_feature: dict[str, str] = {}
        self._exports: dict[str, _StreamExport] = {}

    def build_phase(self) -> None:
        super().build_phase()
        self.evidence = OcahChecker(name=self.name_tag, fail_fast=False, logger=self.logger)

    def check_phase(self) -> None:
        super().check_phase()
        evidence = self._evidence()
        any_required = False
        for name in self._feature_order:
            feature = self._features[name]
            any_required |= feature.required
            feature.unpaired += self._report_unpaired(
                name, self._observed_q, "observed item(s) never paired with an expectation"
            )
            feature.unpaired += self._report_unpaired(
                name, self._expected_q, "expected item(s) never paired with an observation"
            )
            if not feature.required and feature.compares == 0 and feature.unpaired == 0:
                continue
            evidence.expect_true(
                self.feature_check_id(name),
                feature.compares > 0 and feature.mismatches == 0 and feature.unpaired == 0,
                context=(
                    f"feature={name} compares={feature.compares} "
                    f"mismatches={feature.mismatches} unpaired={feature.unpaired} "
                    f"required={int(feature.required)}"
                ),
            )
        evidence.finalize(require_checks=any_required or evidence.check_count > 0)

    # ------------------------------------------------------------------
    # Feature registry (build_phase of the bench scoreboard).
    # ------------------------------------------------------------------

    def add_feature(self, feature: str, *, required: bool = False) -> None:
        """Register a feature; the name becomes ``CHK-SB-<FEATURE>``."""
        if not _FEATURE_RE.match(feature):
            raise OcahScoreboardError(f"feature name `{feature}` must match {_FEATURE_RE.pattern}")
        if feature in self._features:
            raise OcahScoreboardError(f"feature `{feature}` registered twice")
        self._features[feature] = _Feature(name=feature, required=required)
        self._feature_order.append(feature)

    def require_feature(self, feature: str) -> None:
        """Mark a registered feature as required (from the env cfg)."""
        self._feature(feature, "require_feature").required = True

    def has_feature(self, feature: str) -> bool:
        return feature in self._features

    def compare_count(self, feature: str) -> int:
        return self._features[feature].compares if feature in self._features else 0

    def mismatch_count(self, feature: str) -> int:
        return self._features[feature].mismatches if feature in self._features else 0

    def observed_export(self, feature: str, lane: str = "") -> uvm_analysis_export:
        """Analysis export for the observed stream of a feature (and lane)."""
        return self._export(feature, lane, "observed", self.push_observed)

    def expected_export(self, feature: str, lane: str = "") -> uvm_analysis_export:
        """Analysis export for the expected stream of a feature (and lane)."""
        return self._export(feature, lane, "expected", self.push_expected)

    # ------------------------------------------------------------------
    # Recording (compare_pair of the bench scoreboard).
    # ------------------------------------------------------------------

    def record_compare(
        self,
        feature: str,
        *,
        passed: bool,
        expected: str,
        observed: str,
        context: str = "",
    ) -> None:
        """Record one comparison verdict; a mismatch is logged at once."""
        entry = self._feature(feature, "record_compare")
        entry.compares += 1
        if passed:
            self.logger.debug(
                "%s: expected=%s observed=%s context=%s", feature, expected, observed, context
            )
            return
        entry.mismatches += 1
        self.logger.error(
            "%s mismatch: expected=%s observed=%s context=%s", feature, expected, observed, context
        )

    def compare_equal(
        self,
        feature: str,
        observed: object,
        expected: object,
        context: str = "",
    ) -> bool:
        """Exact comparison; an unresolvable observation (``None``) never matches."""
        passed = observed is not None and observed == expected
        self.record_compare(
            feature,
            passed=passed,
            expected=self._format(expected),
            observed=self._format(observed),
            context=context,
        )
        return passed

    # ------------------------------------------------------------------
    # Two-stream pairing.
    # ------------------------------------------------------------------

    def push_observed(self, feature: str, item: object, lane: str = "") -> None:
        """Enqueue one observed item of a feature and pair whatever is pairable."""
        self._feature(feature, "push_observed")
        key = self._pair_key(feature, lane)
        self._observed_q.setdefault(key, deque()).append(item)
        self._try_pair(key)

    def push_expected(self, feature: str, item: object, lane: str = "") -> None:
        """Enqueue one expected item of a feature (from its reference model)."""
        self._feature(feature, "push_expected")
        key = self._pair_key(feature, lane)
        self._expected_q.setdefault(key, deque()).append(item)
        self._try_pair(key)

    def flush_expected(self, feature: str) -> int:
        """Drop every expected item of a feature still waiting, on every lane.

        A reset cancels the transactions they predicted. Returns how many
        were dropped.
        """
        dropped = 0
        for key, queue in self._expected_q.items():
            if self._key_feature[key] != feature:
                continue
            dropped += len(queue)
            queue.clear()
        return dropped

    def compare_pair(self, feature: str, observed: object, expected: object) -> None:
        """Bench hook: compare one pair through ``compare_equal`` or ``record_compare``."""
        raise OcahScoreboardError(f"compare_pair() not implemented for feature `{feature}`")

    @staticmethod
    def feature_check_id(feature: str) -> str:
        """``CHK-SB-<FEATURE>``: upper case, underscores as dashes."""
        return "CHK-SB-" + feature.upper().replace("_", "-")

    # ------------------------------------------------------------------
    # Internals.
    # ------------------------------------------------------------------

    def _try_pair(self, key: str) -> None:
        observed_q = self._observed_q.get(key)
        expected_q = self._expected_q.get(key)
        if observed_q is None or expected_q is None:
            return
        while observed_q and expected_q:
            self.compare_pair(self._key_feature[key], observed_q.popleft(), expected_q.popleft())

    def _pair_key(self, feature: str, lane: str) -> str:
        key = feature if lane == "" else f"{feature}/{lane}"
        self._key_feature[key] = feature
        return key

    def _export(
        self,
        feature: str,
        lane: str,
        stream: str,
        push: Callable[[str, object, str], None],
    ) -> _StreamExport:
        self._feature(feature, f"{stream}_export")
        name = f"{self._pair_key(feature, lane).replace('/', '_')}_{stream}"
        export = self._exports.get(name)
        if export is None:
            export = _StreamExport(name, self, lambda item: push(feature, item, lane))
            self._exports[name] = export
        return export

    def _report_unpaired(self, feature: str, queues: dict[str, deque[object]], what: str) -> int:
        total = 0
        for key, queue in queues.items():
            if self._key_feature[key] != feature or not queue:
                continue
            total += len(queue)
            self.logger.error("%d %s (feature %s, lane %s)", len(queue), what, feature, key)
        return total

    def _feature(self, feature: str, what: str) -> _Feature:
        entry = self._features.get(feature)
        if entry is None:
            raise OcahScoreboardError(
                f"{what} on unregistered feature `{feature}`; known: {self._feature_order}"
            )
        return entry

    def _evidence(self) -> OcahChecker:
        if self.evidence is None:
            raise OcahScoreboardError("check_phase before build_phase: no evidence recorder")
        return self.evidence

    @staticmethod
    def _format(value: object) -> str:
        if isinstance(value, bool) or not isinstance(value, int):
            return str(value)
        return f"0x{value:x}"
