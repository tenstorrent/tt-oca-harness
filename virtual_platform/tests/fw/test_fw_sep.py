# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""DV firmware compatibility: build a VP-suitable test and assert its output on sep-vp.

Tests come from the shared DV firmware engine (``hw/sys/sep/dv/fw/tests``, default
tcm link mode) and print via the firmware output path; the VP decodes the firmware's
pass/fail mailbox magic to a text line (``[VP] SIMULATION OF THE TEST PASSED`` /
``... FAILED``), so success is asserted directly.

Builds go through `make ocah-dv-fw-tests TARGET=sep TEST=<name>` (see
sepvp.pytest_plugin.fw_test_builder). A test that cannot build (or whose ELF is
absent with --no-build) skips with a reason.
"""

import pytest
from sepvp.config import SimConfig

pytestmark = pytest.mark.fw_sep

# VP-decoded firmware pass/fail markers (from the mailbox magic).
FW_PASS = r"\[VP\] SIMULATION OF THE TEST PASSED"
FW_FAIL = r"\[VP\] SIMULATION OF THE TEST FAILED"

TIMEOUT = 60

# (test name, a printf substring it must emit). Start with VP-safe tests; add more as
# they are confirmed to build and run on the VP.
VP_SAFE_TESTS = [
    ("hello_world", "Hello from SEP OSS firmware!"),
]


@pytest.mark.parametrize("test_name, printf_marker", VP_SAFE_TESTS)
def test_fw_sep_test_passes(vp, fw_test_builder, test_name, printf_marker):
    """Build a DV fw test, run it on the VP, assert its printf marker then PASS."""
    elf = fw_test_builder(test_name)
    t = vp(SimConfig(name=f"fw_{test_name}", elf=elf, boot_timeout=TIMEOUT))
    t.spawn()
    # The firmware's stdout and the VP PASS/FAIL line — FAIL aborts immediately.
    t.expect(printf_marker, error_patterns=[FW_FAIL], timeout=TIMEOUT)
    t.expect(FW_PASS, error_patterns=[FW_FAIL], timeout=TIMEOUT)
    t.close()
