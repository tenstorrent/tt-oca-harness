# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The RSA signature comparison is evaluated twice over one modexp result.

The specification requires the signature verification comparison to be repeated "at least twice with a random delay in between", and to
pass "only ... if individual checks pass". This testcase covers the repetition
half on a normal signed boot.

WHAT IS AND IS NOT COVERED. That requirement has two halves and this testcase asserts
one of them:

  * repetition + both-must-pass -- asserted here.
  * the random delay between the repeats -- NOT asserted, and not implemented.
    BL0 has no entropy source (the TRNG starts in BL1), so there is nothing to
    derive a varying delay from. That half is an open spec question.

This does NOT cover the wider reading, whose expected result is "OTBN command
monitor records exactly 2 RSA verify commands per boot" -- a repeated *modexp*.
The requirement's antecedent is the comparison ``PASS := (h==h')``, so the ROM
repeats the comparison and runs the modexp once --
and this testcase pins that reading down by asserting ``RSA_EXEC`` appears exactly
once. If the procedure author rules for the wider reading instead, this assertion
is the one that has to change, which is why it is explicit rather than implied.

WHY THE COUNTS AND THE ORDER, not just presence. ``required_markers`` can only ask
whether a string appeared. Presence alone cannot distinguish one comparison from
two, which is the entire property under test, so ``check_transport`` counts the
occurrences and checks that both comparisons follow the single modexp.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_rom_ot_secure_boot_test import sep_rom_ot_secure_boot_test

# rsa_verify.c emits one token per comparison pass, unconditionally, before the
# accept decision -- so the count is observable whatever the verdict.
_CMP1 = "RSA_CMP1"
_CMP2 = "RSA_CMP2"
# The single modular exponentiation the two comparisons both read back.
_EXEC = "RSA_EXEC"
_VERIFY_OK = "RSA_VERIFY_OK"


def _count(console: list[str], marker: str) -> int:
    return sum(1 for line in console if marker in line)


@pyuvm.test()
class sep_rsa_verify_redundant_compare_test(sep_rom_ot_secure_boot_test):
    """Two PKCS#1 comparisons, one modexp, both comparisons must pass."""

    required_markers = sep_rom_ot_secure_boot_test.required_markers + (
        _EXEC, _CMP1, _CMP2, _VERIFY_OK,
    )
    forbidden_markers = sep_rom_ot_secure_boot_test.forbidden_markers + (
        # A rejected comparison on a correctly signed image would mean the
        # redundant path itself broke the good case.
        "RSA_PKCS1_FAIL", "RSA_VERIFY_FAIL", "MANIFEST_ERR=", "MANIFEST_ALL_FAILED",
    )

    def check_transport(self, console: list[str], flash) -> None:
        # A clean primary boot verifies one slot, so each token must appear once.
        # Two would mean the backup was also tried and this run is not the
        # single-slot scenario the counts below are written for.
        n_exec = _count(console, _EXEC)
        n_cmp1 = _count(console, _CMP1)
        n_cmp2 = _count(console, _CMP2)

        assert n_exec == 1, (
            f"{_EXEC} appeared {n_exec} times, expected 1. This testcase asserts "
            f"the narrow reading of step 27: the modexp runs once and only the "
            f"comparison repeats. More than one means either the backup slot was "
            f"also verified (wrong scenario) or the modexp itself is being "
            f"repeated. Console: {console}"
        )
        assert n_cmp1 == 1 and n_cmp2 == 1, (
            f"comparison pass count is {_CMP1}={n_cmp1}, {_CMP2}={n_cmp2}, "
            f"expected 1 each. Both tokens are printed unconditionally, once per "
            f"pass, so this is the direct measure of how many times the ROM "
            f"compared the recovered digest. Console: {console}"
        )

        # Order: both comparisons must read back a result the modexp already
        # produced. A comparison ahead of RSA_EXEC would be reading stale DMEM.
        i_exec = fd.first_index(console, _EXEC)
        i_cmp1 = fd.first_index(console, _CMP1)
        i_cmp2 = fd.first_index(console, _CMP2)
        i_ok = fd.first_index(console, _VERIFY_OK)
        assert i_exec < i_cmp1 < i_cmp2 < i_ok, (
            f"expected {_EXEC} -> {_CMP1} -> {_CMP2} -> {_VERIFY_OK}, got indices "
            f"{i_exec}, {i_cmp1}, {i_cmp2}, {i_ok}. Both comparisons must follow "
            f"the modexp, and the verdict must follow both of them. Console: "
            f"{console}"
        )

        self.logger.info(
            "CHK-RSA-REDUNDANT-CMP: one %s followed by %s then %s then %s -- the "
            "PKCS#1 comparison was evaluated twice over a single modexp result, "
            "and the accept path required both",
            _EXEC, _CMP1, _CMP2, _VERIFY_OK,
        )
