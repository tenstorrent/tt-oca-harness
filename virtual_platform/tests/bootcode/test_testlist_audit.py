# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

from pathlib import Path

import pytest
import testlist_audit
from testlist_loader import load_testlist

pytestmark = pytest.mark.hostonly

LOGS = Path(__file__).resolve().parents[2] / "logs" / "sepvp"
GOLDEN_LOG = LOGS / testlist_audit.GOLDEN_TESTCASE / "sep-vp.log"
_IMAGES = {"signed", "spi_primary_slot_blank"}

_GOLDEN_OUTPUT = (
    "[spi_flash] Backdoor: loaded 276144 bytes from data/flash_memory.bin\n"
    "[spi_flash] Read @ 0x1000 len=256\n"
    "[spi_flash] Read @ 0x2000 len=256\n"
    "[0 ns] [INFO 2] [SIM_OUT] - MANIFEST_OK\n"
    "[1 ns] [INFO 2] [SIM_OUT] - BL1_COPIED\n"
    "[2 ns] [INFO 2] [SIM_OUT] - GO!\n"
    "[VP] SIMULATION OF THE TEST PASSED\n"
)


def _case(tmp_path, body):
    path = tmp_path / "one.toml"
    path.write_text(
        f"""
[[testcase]]
name = "one"
family = "audit"
classification = "vp-equivalent"
expect_verdict = "PASSED"
{body}
"""
    )
    return load_testlist(path, known_images=_IMAGES)[0]


def test_flags_an_error_token_a_healthy_boot_also_emits(tmp_path):
    golden = _GOLDEN_OUTPUT.replace("BL1_COPIED", "PUBK_UNAUTHORIZED")
    testcase = _case(tmp_path, 'expect = ["PUBK_UNAUTHORIZED"]\nimage = "signed"')

    kinds = {f.kind for f in testlist_audit.audit(testcase, golden)}

    assert "insensitive" in kinds


@pytest.mark.parametrize("token", ["PUBK_UNAUTHORIZED", "FLASH_READ_OOB", "PAYLOAD_TOO_LARGE"])
def test_oca_error_tokens_are_error_class(token):
    assert testlist_audit._ERROR_TOKEN_RE.search(token)


@pytest.mark.parametrize("token", ["MANIFEST_OK", "BL1_COPIED", "GO!"])
def test_happy_path_tokens_are_not_error_class(token):
    assert testlist_audit._ERROR_TOKEN_RE.search(token) is None


def test_flags_a_contract_a_healthy_boot_satisfies_with_an_unpinned_stimulus(tmp_path):
    testcase = _case(tmp_path, 'expect = ["GO!"]\nimage = "spi_primary_slot_blank"')

    findings = testlist_audit.audit(testcase, _GOLDEN_OUTPUT)

    assert [f.kind for f in findings] == ["golden_satisfiable"]


def test_golden_image_with_golden_configuration_is_reported_as_shared_stimulus(tmp_path):
    testcase = _case(tmp_path, 'expect = ["GO!"]\nimage = "signed"')

    assert [f.kind for f in testlist_audit.audit(testcase, _GOLDEN_OUTPUT)] == [
        "shares_golden_stimulus"
    ]


def test_an_image_assert_pins_an_otherwise_golden_satisfiable_contract(tmp_path):
    testcase = _case(
        tmp_path,
        'expect = ["GO!"]\nimage = "spi_primary_slot_blank"\n'
        "image_asserts = [{ range = [0x1000, 0x41000], all = 0xFF }]",
    )

    assert testlist_audit.audit(testcase, _GOLDEN_OUTPUT) == []


def test_a_real_negative_contract_is_not_flagged(tmp_path):
    testcase = _case(
        tmp_path,
        'expect = ["PUBK_UNAUTHORIZED", "GO!"]\nimage = "spi_primary_slot_blank"',
    )

    assert testlist_audit.audit(testcase, _GOLDEN_OUTPUT) == []


@pytest.mark.skipif(not GOLDEN_LOG.is_file(), reason="needs a full bootcode regression's logs")
def test_no_testcase_passes_for_the_wrong_reason():
    from test_sep_rom_testlist import TESTCASES

    golden_output = GOLDEN_LOG.read_text(errors="replace")
    findings = [
        finding
        for testcase in TESTCASES
        if testcase.classification != "retired"
        for finding in testlist_audit.audit(testcase, golden_output)
        if not (
            finding.kind == "shares_golden_stimulus"
            and finding.testcase in testlist_audit.SHARES_GOLDEN_STIMULUS
        )
    ]

    assert findings == [], "\n".join(f"{f.testcase}: {f.kind}: {f.detail}" for f in findings)


def test_the_shared_stimulus_allowlist_is_the_ruled_set_of_live_testcases():
    from test_sep_rom_testlist import TESTCASES

    assert testlist_audit.SHARES_GOLDEN_STIMULUS == {
        "sep_spi_detect_success_test",
        "rom_ot_secure_boot_golden",
        "sep_rsa_verify_redundant_compare_test",
        "sep_firmware_primary_manifest_major_version_valid_minor_0_length_correct_test",
    }
    live = {c.name for c in TESTCASES if c.classification != "retired"}
    assert testlist_audit.SHARES_GOLDEN_STIMULUS <= live
