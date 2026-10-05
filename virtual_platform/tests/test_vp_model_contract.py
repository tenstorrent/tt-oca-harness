# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""sep-vp model behaviour that the testlist judges depend on."""

import pexpect
import pytest
from sepvp.config import SimConfig

pytestmark = [pytest.mark.bootcode, pytest.mark.needs_debug]

_TIMEOUT = 180
_PASSED = r"\[VP\] SIMULATION OF THE TEST PASSED"
_FAILED = r"\[VP\] SIMULATION OF THE TEST FAILED"


def _config(name, elf, **kwargs):
    kwargs.setdefault("boot_timeout", _TIMEOUT)
    return SimConfig(name=name, elf=elf, **kwargs)


def test_console_and_status_lines_carry_channel_tags(vp, bootcode_elf):
    t = vp(_config("contract_tags", bootcode_elf, boot="primary"))
    t.spawn()
    t.expect(r"\[SIM_OUT\] - COLD\r?\n", error_patterns=[], timeout=_TIMEOUT)
    t.expect(
        r"\[SEP_STATUS\] - BL0 +INFO +0x[0-9a-fA-F]{4} +SEP_MSG_\w+",
        error_patterns=[],
        timeout=_TIMEOUT,
    )
    t.close()


def test_a_signed_boot_announces_the_passed_verdict(vp, bootcode_elf, oca_images):
    t = vp(
        _config(
            "contract_verdict_passed",
            bootcode_elf,
            boot="primary",
            flash_image=oca_images["signed"],
            otp="tests/fuse_maps/prod_secure.yaml",
        )
    )
    t.spawn()
    t.expect(_PASSED, error_patterns=[_FAILED], timeout=_TIMEOUT)
    t.close()


def test_a_boot_with_no_manifest_announces_the_failed_verdict(vp, bootcode_elf):
    # A secondary chiplet with no staged SMC manifest ends in rom_err_fail.
    t = vp(_config("contract_verdict_failed", bootcode_elf))
    t.spawn()
    t.expect(_FAILED, error_patterns=[_PASSED], timeout=_TIMEOUT)
    t.close()


def test_preboot_init_write_is_applied(vp, bootcode_elf):
    t = vp(
        _config(
            "contract_init_write",
            bootcode_elf,
            extra_ini=[("string", "och_sep_ss1.init_writes", "0x10802030=0x12345678")],
        )
    )
    t.spawn()
    t.expect(r"\[init_writes\] 0x10802030 = 0x12345678", error_patterns=[], timeout=30)
    t.close()


@pytest.mark.parametrize(
    "raw_value, diagnostic",
    [
        ("missing-equals", r"malformed entry"),
        ("0x10802031=0", r"address is not 4-byte aligned"),
        ("0x100000000=0", r"invalid address"),
        ("0xdead0000=1", r"write rejected at 0xdead0000"),
    ],
)
def test_preboot_init_write_rejects_invalid_raw_values(vp, bootcode_elf, raw_value, diagnostic):
    t = vp(
        _config(
            "contract_invalid_init_write",
            bootcode_elf,
            extra_ini=[("string", "och_sep_ss1.init_writes", raw_value)],
        )
    )
    t.spawn()
    t.expect(rf"\[init_writes\] {diagnostic}", error_patterns=[], timeout=30)
    t.child.expect(pexpect.EOF, timeout=30)
    t.child.close()
    assert t.child.exitstatus not in (None, 0) or t.child.signalstatus is not None
