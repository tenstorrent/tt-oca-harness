# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Flag testcases whose assertions a healthy boot would also satisfy.

``insensitive``: expects an error token the golden log also emits.
``golden_satisfiable``: a healthy boot meets the full contract and no image assert, fuse map,
strap or init write pins the stimulus.
``shares_golden_stimulus``: boots the golden stimulus and only adds assertions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from sepvp.judges import JudgeError, console_tokens, judge
from sepvp.run_result import RunResult, StopReason

# Tokens the ROM prints only off the happy path.
_ERROR_TOKEN_RE = re.compile(
    r"(_ERR=|MISMATCH|_FAIL|INVALID|ERROR|SBOOT_OFF|NOT_DETECTED|REVOKED|ROLLBACK"
    r"|_EMPTY|BAD_|_RANGE|NO_BL1_IMAGE|UNAUTHORIZED|_OOB|RESERVED|AMBIGUOUS"
    r"|UNPROVISIONED|UNSUPPORTED|TOO_LARGE)"
)
GOLDEN_TESTCASE = "rom_ot_secure_boot_golden"
GOLDEN_IMAGE = "signed"
# Entries accepted as boots of the golden stimulus; any other shares_golden_stimulus is a finding.
SHARES_GOLDEN_STIMULUS = frozenset(
    {
        GOLDEN_TESTCASE,
        "sep_spi_detect_success_test",
        "sep_rsa_verify_redundant_compare_test",
        "sep_firmware_primary_manifest_major_version_valid_minor_0_length_correct_test",
    }
)


@dataclass(frozen=True)
class Finding:
    testcase: str
    kind: str
    detail: str


def log_tokens(log: Path) -> list[str]:
    """The firmware console tokens a run produced, in order."""
    return console_tokens(log.read_text(errors="replace"))


def _counts(tokens: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    return counts


def _stimulus_is_pinned(testcase) -> bool:
    """True when something outside the run proves the stimulus was applied."""
    return bool(
        testcase.image_asserts
        or testcase.efuse
        or testcase.init_writes
        or testcase.preloaded_test_programs
        or testcase.rotate_update
    )


def _runs_golden_stimulus(testcase) -> bool:
    """True when the entry boots the golden image with the golden configuration."""
    return (
        testcase.image == GOLDEN_IMAGE
        and not testcase.efuse
        and not testcase.init_writes
        and not testcase.preloaded_test_programs
        and not testcase.rotate_update
    )


def golden_satisfies(testcase, golden_output: str) -> bool:
    """Would a healthy boot pass this entry's complete contract?"""
    result = RunResult(
        output=golden_output,
        stop_reason=StopReason.FIRMWARE_VERDICT,
        duration=0.0,
        exit_code=None,
        signal=9,
        firmware_verdict="PASSED",
        timed_out=False,
        harness_terminated=True,
    )
    try:
        judge(
            result,
            expect=testcase.expect,
            forbid=testcase.forbid,
            expect_counts=testcase.expect_counts,
            terminal_token=testcase.terminal_token,
            expect_silence=testcase.expect_silence,
            liveness=[],
            expect_status=testcase.expect_status,
            forbid_status=testcase.forbid_status,
            spi_reads=testcase.spi_reads,
            spi_read_order=testcase.spi_read_order,
            expect_verdict=testcase.expect_verdict,
        )
    except JudgeError:
        return False
    return True


def audit(testcase, golden_output: str) -> list[Finding]:
    """Findings for one testcase, judged against a healthy boot's raw output."""
    findings = []
    golden_counts = _counts(console_tokens(golden_output))

    for token in testcase.expect:
        if not _ERROR_TOKEN_RE.search(token):
            continue
        hits = golden_counts.get(token, 0)
        if hits:
            findings.append(
                Finding(
                    testcase.name,
                    "insensitive",
                    f"expects {token!r}, which a golden boot also emits "
                    f"({hits}x); it cannot show the failure path ran",
                )
            )

    if testcase.name == GOLDEN_TESTCASE:
        return findings
    if not golden_satisfies(testcase, golden_output):
        return findings
    if _runs_golden_stimulus(testcase):
        findings.append(
            Finding(
                testcase.name,
                "shares_golden_stimulus",
                "runs the golden stimulus and adds assertions to it, so it cannot "
                "fail unless the golden entry fails as well",
            )
        )
    elif not _stimulus_is_pinned(testcase):
        findings.append(
            Finding(
                testcase.name,
                "golden_satisfiable",
                "a healthy boot satisfies this contract and nothing outside the run "
                "pins the stimulus, so the entry would stay green if the stimulus "
                "silently failed to apply",
            )
        )
    return findings
