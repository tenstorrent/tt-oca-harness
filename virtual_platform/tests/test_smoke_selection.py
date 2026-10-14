# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""The sep-vp CI legs select their tests with ``-m smoke``; pin what that selects.

A mistyped marker in a testlist entry's ``pytest_markers`` or on a test function only
warns, so a smoke boot could drop out of CI without failing anything.
"""

import subprocess
import sys

import pytest
from sepvp import paths

pytestmark = pytest.mark.hostonly

SMOKE = {
    "tests/bootcode/test_bootcode_oca.py::test_unsigned_boots_to_bl1",
    "tests/bootcode/test_sep_rom_testlist.py::test_sep_rom_testlist[rom_ot_encrypted_boot_golden]",
}


def test_smoke_selects_minimum_test_set():
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-m", "smoke", "--collect-only", "-q"]
        + ["-o", "addopts=", "-p", "no:cacheprovider"],
        cwd=paths.VP_DIR,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    selected = {line for line in result.stdout.splitlines() if "::" in line}
    assert selected == SMOKE
