# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMU OSS scoreboard - requires positive evidence; never vacuous PASS."""

from __future__ import annotations

import re
from typing import Optional

from pyuvm import uvm_component

from .smu_evidence_map import TEST_EVIDENCE, UNMAPPED_TESTS
from .smu_fcov import SmuFcov

# How a token became attached to a passing check. BIND_EXPLICIT is the only
# binding a caller states outright; BIND_CHECK_NAME depends on the check name
# containing the TOKEN or CHK id, so it binds a row to whatever check happens
# to be named that way.
BIND_EXPLICIT = "evidence-arg"
BIND_CHECK_NAME = "check-name-substring"
BIND_DERIVED = "derived-from-check-name"
BIND_SCOREBOARD = "scoreboard-check-phase"


def _evidence_token(name: str) -> str:
    tok = re.sub(r"[^A-Za-z0-9]+", "_", str(name)).strip("_").upper()
    return tok[:96] if tok else "CHECK"


def _normalize_token(token: str) -> str:
    tok = str(token).strip()
    if tok.startswith("EVIDENCE:"):
        tok = tok.split(":", 1)[1].strip()
    return tok


class SmuScoreboard(uvm_component):
    def build_phase(self) -> None:
        self.checks = 0
        self.errors = 0
        self.fcov = SmuFcov()
        self._evidence_tokens: list[str] = []
        self.testcase_name: Optional[str] = None
        self._feature_tokens_used: set[str] = set()
        self._token_binding: dict[str, str] = {}

    def bind_testcase(self, testcase_name: str) -> None:
        """Bind the evidence map for this leaf (called from smu_base_test)."""
        self.testcase_name = testcase_name

    def _resolve_token(self, name: str, evidence: Optional[str]) -> tuple[str, str]:
        """Return the token for this check and the binding path that chose it."""
        if evidence:
            return _normalize_token(evidence), BIND_EXPLICIT
        # Auto-attach mapped FEATURE tokens only when the check name contains
        # the TOKEN or CHK id itself; matching expect-string keywords (e.g.
        # "ovrd"/"stall"/"reset") would log FEATURE tokens on idle/bring-up
        # compares (EVIDENCE-TOKEN-CONDITIONAL).
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
                return token, BIND_CHECK_NAME
        return _evidence_token(name), BIND_DERIVED

    def _log_evidence(self, token: str, binding: str = BIND_SCOREBOARD) -> None:
        token = _normalize_token(token)
        self._evidence_tokens.append(token)
        self._feature_tokens_used.add(token)
        # An explicit evidence= on any carrying check outranks a name match.
        if binding == BIND_EXPLICIT or token not in self._token_binding:
            self._token_binding[token] = binding
        # Canonical form: the FEATURE_LIST token spelling
        self.logger.info("EVIDENCE: %s", token)
        # Alias without a space: log consumers also grep EVIDENCE:<TOKEN>
        self.logger.info("EVIDENCE:%s", token)
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
            self.logger.error("CHECK FAIL %s: expected %s, got %s", name, expected, observed)
            raise AssertionError(f"{name}: expected {expected}, got {observed}")
        token, binding = self._resolve_token(name, evidence)
        self.logger.info("CHECK PASS %s: %s", name, observed)
        self._log_evidence(token, binding)
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
        """Require every evidence-map TOKEN for this testcase to have been logged.

        Called at the end of run_scenario. A token reaches the logged set only
        through a passing ``expect_*`` compare, so a missing token raises. A
        token that reached it only because a check name happened to contain it
        also raises: the map row is proved only by a compare that names the
        token in ``evidence=``. The EXPECT column is free-text contract wording:
        it is reported alongside the token and is not compared against anything.

        A testcase with no map rows must be listed in ``UNMAPPED_TESTS``; any
        other unmapped testcase raises here.
        """
        testcase = self.testcase_name or ""
        rows = TEST_EVIDENCE.get(testcase, [])
        if not rows:
            reason = UNMAPPED_TESTS.get(testcase)
            if reason is None:
                raise AssertionError(
                    f"SmuScoreboard: {testcase!r} has no TEST_EVIDENCE rows and no "
                    f"UNMAPPED_TESTS entry. Add evidence-map rows, or record the "
                    f"decision to run it without them in UNMAPPED_TESTS."
                )
            self.logger.info(
                "EVIDENCE MAP UNMAPPED %s: declared in UNMAPPED_TESTS, no mapped "
                "token contract on this run - %s",
                testcase,
                reason,
            )
            return
        missing = [t for _, t, _ in rows if t not in self._feature_tokens_used]
        if missing:
            raise AssertionError(
                f"SmuScoreboard: mapped feature tokens not logged for "
                f"{testcase}: {missing}. Pass evidence= on expect_* "
                f"or align check names to FEATURE_LIST TOKENs."
            )
        name_bound = []
        for chk_id, token, expect in rows:
            binding = self._token_binding.get(token, BIND_SCOREBOARD)
            if binding == BIND_CHECK_NAME:
                name_bound.append(token)
            self.logger.info(
                "EVIDENCE TOKEN SEEN %s -> %s (bound-by=%s); contract text, not compared: %s",
                chk_id,
                token,
                binding,
                expect,
            )
        if name_bound:
            raise AssertionError(
                f"EVIDENCE BINDING WEAK {testcase}: {len(name_bound)} of {len(rows)} mapped "
                f"row(s) attached by check-name substring only, with no evidence= argument: "
                f'{",".join(name_bound)}. Pass evidence="<TOKEN>" on the compare that '
                "proves each one."
            )

    def check_phase(self) -> None:
        if self.checks == 0:
            raise AssertionError("SmuScoreboard: zero checks executed - refusing vacuous PASS")
        if self.errors != 0:
            raise AssertionError(
                f"SmuScoreboard: {self.errors} check(s) failed out of {self.checks}"
            )
        # Non-vacuity evidence token
        self._log_evidence("CHK-NONVAC", BIND_SCOREBOARD)
        self.logger.info("SmuScoreboard: %d check(s) passed with zero errors", self.checks)
        if self._evidence_tokens:
            self.logger.info(
                "EVIDENCE_SUMMARY: %d token(s) - %s",
                len(self._evidence_tokens),
                ",".join(self._evidence_tokens[:48]),
            )
        for line in self.fcov.summary_lines():
            self.logger.info("%s", line)
