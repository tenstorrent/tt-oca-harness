# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The ROM repeats the RSA signature comparison over one modexp result; both passes must succeed.

The random delay between the two comparisons is not implemented, because BL0 has no entropy source.
A single ``RSA_EXEC`` pins the reading that only the comparison repeats, not the modexp.
"""

from __future__ import annotations

import pyuvm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_rom_ot_secure_boot_test import sep_rom_ot_secure_boot_test

# One token per comparison pass, printed before the accept decision.
_CMP1 = "RSA_CMP1"
_CMP2 = "RSA_CMP2"
_EXEC = "RSA_EXEC"
_VERIFY_OK = "RSA_VERIFY_OK"


def _count(console: list[str], marker: str) -> int:
    return sum(1 for line in console if marker in line)


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
        "RSA_VERIFY_FAIL",
        "MANIFEST_ERR=",
        "MANIFEST_ALL_FAILED",
    )

    def check_transport(self, console: list[str], flash) -> None:
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

        # A comparison before RSA_EXEC would read stale DMEM.
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
            _EXEC,
            _CMP1,
            _CMP2,
            _VERIFY_OK,
        )
