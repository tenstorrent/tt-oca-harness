# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMU OSS scoreboard - requires positive evidence; never vacuous PASS."""

from __future__ import annotations

import re
from typing import Optional

from pyuvm import uvm_component

from .smu_evidence_map import TEST_EVIDENCE
from .smu_fcov import SmuFcov


def _evidence_token(name: str) -> str:
    tok = re.sub(r"[^A-Za-z0-9]+", "_", str(name)).strip("_").upper()
    return tok[:96] if tok else "CHECK"


def _normalize_token(token: str) -> str:
    tok = str(token).strip()
    if tok.startswith("EVIDENCE:"):
        tok = tok.split(":", 1)[1].strip()
    if tok.startswith("CHK-") and tok != "CHK-NONVAC":
        # Allow callers to pass CHK-* ; strip to TOKEN form when it looks like
        # CHK-<TOKEN> with underscores already.
        pass
    return tok


class SmuScoreboard(uvm_component):
    def build_phase(self) -> None:
        self.checks = 0
        self.errors = 0
        self.fcov = SmuFcov()
        self._evidence_tokens: list[str] = []
        self.testcase_name: Optional[str] = None
        self._feature_tokens_used: set[str] = set()

    def bind_testcase(self, testcase_name: str) -> None:
        """Bind aidv evidence map for this leaf (called from smu_base_test)."""
        self.testcase_name = testcase_name

    def _resolve_token(self, name: str, evidence: Optional[str]) -> str:
        if evidence:
            return _normalize_token(evidence)
        # Auto-attach mapped FEATURE tokens only when the check name contains
        # the TOKEN or CHK id itself. Do NOT fuzzy-match expect-string keywords
        # (e.g. "ovrd"/"stall"/"reset") — that prematurely logged FEATURE tokens
        # on idle/bring-up compares (EVIDENCE-TOKEN-CONDITIONAL).
        rows = TEST_EVIDENCE.get(self.testcase_name or "", [])
        name_u = str(name).upper().replace("-", "_")
        for chk_id, token, _expect in rows:
            if token in self._feature_tokens_used:
                continue
            keys = [
                token.upper().replace("-", "_"),
                chk_id.upper().replace("-", "_"),
                chk_id.replace("CHK-", "").upper().replace("-", "_"),
            ]
            if any(k and k in name_u for k in keys):
                return token
        return _evidence_token(name)

    def _log_evidence(self, token: str) -> None:
        token = _normalize_token(token)
        self._evidence_tokens.append(token)
        self._feature_tokens_used.add(token)
        # Canonical aidv form (FEATURE_LIST / aidv_audit example)
        self.logger.info("EVIDENCE: %s", token)
        # Alias without space for contracts grepping EVIDENCE:<TOKEN>
        self.logger.info("EVIDENCE:%s", token)
        # Also emit CHK-<TOKEN> alias when TOKEN is not already a CHK-* id
        if token != "CHK-NONVAC" and not token.startswith("CHK-"):
            self.logger.info("EVIDENCE:CHK-%s", token)
            self.logger.info("EVIDENCE: CHK-%s", token)

    def expect_eq(
        self,
        name: str,
        observed,
        expected,
        *,
        evidence: Optional[str] = None,
        fcov: Optional[tuple[str, str, str]] = None,
    ) -> None:
        self.checks += 1
        if observed != expected:
            self.errors += 1
            self.logger.error(
                "CHECK FAIL %s: expected %s, got %s", name, expected, observed
            )
            raise AssertionError(f"{name}: expected {expected}, got {observed}")
        token = self._resolve_token(name, evidence)
        self.logger.info("CHECK PASS %s: %s", name, observed)
        self._log_evidence(token)
        if fcov is not None:
            self.fcov.hit(*fcov)

    def expect_true(
        self,
        name: str,
        cond: bool,
        *,
        evidence: Optional[str] = None,
        fcov: Optional[tuple[str, str, str]] = None,
    ) -> None:
        self.expect_eq(name, bool(cond), True, evidence=evidence, fcov=fcov)

    def expect_j2a_payload_denied(
        self,
        name: str,
        status: int,
        rdata: int,
        forbidden_data: int,
        *,
        data_bits: int = 32,
        success_status: int = 0,
        evidence: Optional[str] = None,
        fcov: Optional[tuple[str, str, str]] = None,
    ) -> None:
        """Deny = must not deliver SUCCESS carrying the true payload."""
        mask = (1 << int(data_bits)) - 1
        data = int(rdata) & mask
        expect = int(forbidden_data) & mask
        delivered = (int(status) == int(success_status)) and (data == expect)
        self.expect_true(
            f"{name}: not SUCCESS+forbidden "
            f"(status={int(status)} data=0x{data:x} forbidden=0x{expect:x})",
            not delivered,
            evidence=evidence or "J2A_PAYLOAD_DENIED",
            fcov=fcov,
        )

    def prove_mapped_features(self) -> None:
        """Ensure every FEATURE_LIST TOKEN for this testcase was logged.

        Call at end of run_scenario after real checks. Missing tokens fail —
        aidv forbids inventing checkboxes after seeing a green path.
        """
        rows = TEST_EVIDENCE.get(self.testcase_name or "", [])
        if not rows:
            return
        missing = [t for _, t, _ in rows if t not in self._feature_tokens_used]
        if missing:
            raise AssertionError(
                f"SmuScoreboard: mapped feature tokens not proven for "
                f"{self.testcase_name}: {missing}. Pass evidence= on expect_* "
                f"or align check names to FEATURE_LIST TOKENs."
            )
        for chk_id, token, expect in rows:
            self.logger.info(
                "FEATURE PROVEN %s -> %s (%s)", chk_id, token, expect
            )

    def check_phase(self) -> None:
        if self.checks == 0:
            raise AssertionError(
                "SmuScoreboard: zero checks executed - refusing vacuous PASS"
            )
        if self.errors != 0:
            raise AssertionError(
                f"SmuScoreboard: {self.errors} check(s) failed out of {self.checks}"
            )
        # Non-vacuity evidence token required by leaf contracts
        self._log_evidence("CHK-NONVAC")
        self.logger.info(
            "SmuScoreboard: %d check(s) passed with zero errors", self.checks
        )
        if self._evidence_tokens:
            self.logger.info(
                "EVIDENCE_SUMMARY: %d token(s) - %s",
                len(self._evidence_tokens),
                ",".join(self._evidence_tokens[:48]),
            )
        for line in self.fcov.summary_lines():
            self.logger.info("%s", line)
