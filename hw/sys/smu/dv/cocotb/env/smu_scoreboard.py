# SPDX-License-Identifier: Apache-2.0
"""SMU OSS scoreboard - requires positive evidence; never vacuous PASS."""

from __future__ import annotations

import re
from typing import Optional

from pyuvm import uvm_component

from .smu_fcov import SmuFcov


def _evidence_token(name: str) -> str:
    tok = re.sub(r"[^A-Za-z0-9]+", "_", str(name)).strip("_").upper()
    return (tok[:96] if tok else "CHECK")


class SmuScoreboard(uvm_component):
    def build_phase(self) -> None:
        self.checks = 0
        self.errors = 0
        self.fcov = SmuFcov()
        self._evidence_tokens: list[str] = []

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
        token = evidence or _evidence_token(name)
        self._evidence_tokens.append(token)
        self.logger.info("CHECK PASS %s: %s", name, observed)
        self.logger.info("EVIDENCE: %s", token)
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
        """Deny = must not deliver SUCCESS carrying the true payload.

        BUSY / SLVERR / DECERR all count as denied delivery. SUCCESS is allowed
        only when the captured data is not the forbidden (true) CSR value
        (covers sticky-DR re-gate probes on a different address).
        """
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

    def check_phase(self) -> None:
        if self.checks == 0:
            raise AssertionError(
                "SmuScoreboard: zero checks executed - refusing vacuous PASS"
            )
        if self.errors != 0:
            raise AssertionError(
                f"SmuScoreboard: {self.errors} check(s) failed out of {self.checks}"
            )
        self.logger.info(
            "SmuScoreboard: %d check(s) passed with zero errors", self.checks
        )
        if self._evidence_tokens:
            self.logger.info(
                "EVIDENCE_SUMMARY: %d token(s) - %s",
                len(self._evidence_tokens),
                ",".join(self._evidence_tokens[:32]),
            )
        for line in self.fcov.summary_lines():
            self.logger.info("%s", line)
