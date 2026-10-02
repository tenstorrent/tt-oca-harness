# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The ROM repeats the RSA signature comparison over one modexp result; both passes must succeed.

No random delay separates the two comparisons.
A single ``RSA_EXEC`` pins the reading that only the comparison repeats, not the modexp.
"""

from __future__ import annotations

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_oca_console as oc
from rom_fw.sep_rom_ot_secure_boot_test import sep_rom_ot_secure_boot_test

_CMP1 = "RSA_CMP1"
_CMP2 = "RSA_CMP2"
_EXEC = "RSA_EXEC"
_VERIFY_OK = "RSA_VERIFY_OK"


def _count(console: list[str], marker: str) -> int:
    return oc.count(console, marker)


@pyuvm.test()
class sep_rsa_verify_redundant_compare_test(sep_rom_ot_secure_boot_test):
    """Two PKCS#1 comparisons, one modexp, both comparisons must pass."""

    required_markers = sep_rom_ot_secure_boot_test.required_markers + (
        _EXEC,
        _CMP1,
        _CMP2,
        _VERIFY_OK,
    )
    forbidden_markers = sep_rom_ot_secure_boot_test.forbidden_markers + (
        "RSA_PKCS1_FAIL",
        "RSA_EXEC_FAIL",
        "MANIFEST_ERR=",
        "MANIFEST_ALL_FAILED",
    )

    def check_transport(self, console: list[str], flash) -> None:
        n_exec = _count(console, _EXEC)
        n_cmp1 = _count(console, _CMP1)
        n_cmp2 = _count(console, _CMP2)

        assert n_exec == 1, (
            f"{_EXEC} appeared {n_exec} times, expected 1: the modexp runs once "
            f"and only the comparison repeats. More than one means either the backup slot was "
            f"also verified (wrong scenario) or the modexp itself is being "
            f"repeated. Console: {console}"
        )
        assert n_cmp1 == 1 and n_cmp2 == 1, (
            f"comparison pass count is {_CMP1}={n_cmp1}, {_CMP2}={n_cmp2}, "
            f"expected 1 each. Both tokens are printed unconditionally, once per "
            f"pass, so this is the direct measure of how many times the ROM "
            f"compared the recovered digest. Console: {console}"
        )

        attempts = oc.split_attempts(console)
        assert [a.src for a in attempts] == [mm.PRIMARY_MANIFEST_OFFSET], (
            f"slot attempts read {[hex(a.src) for a in attempts]}, expected the primary "
            f"only. Console: {console}"
        )
        # A comparison before RSA_EXEC would read stale DMEM, so RSA_EXEC must come first.
        oc.assert_attempt(
            attempts[0],
            error=None,
            stage="accepted",
            ordered=(_EXEC, _CMP1, _CMP2, _VERIFY_OK, "MANIFEST_OK", "PAYLOAD_OK"),
        )

        self.logger.info(
            "CHK-RSA-REDUNDANT-CMP: one %s followed by %s then %s then %s -- the "
            "PKCS#1 comparison was evaluated twice over a single modexp result, "
            "and the accept path required both",
            _EXEC,
            _CMP1,
            _CMP2,
            _VERIFY_OK,
        )


oc.assert_known(
    sep_rsa_verify_redundant_compare_test.required_markers
    + sep_rsa_verify_redundant_compare_test.forbidden_markers,
    sep_rsa_verify_redundant_compare_test.__name__,
)
