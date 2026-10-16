# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Every SMC ROM/OCCP testlist entry must declare how it treats the status strap.

`smc_dual_base_test` draws the `STATUS_RPT_DISABLE` strap at random when neither
`+FORCE_STATUS_REPORTING` nor `+STATUS_RPT_DISABLE` is given, so an entry whose
pass criterion needs GET_STATUS-family answers fails on the draws that set it.
Each `[[tests]]` entry of `smc_rom.toml` whose firmware mode is `occp_rom_only`
(this includes the `occp_master`-based `smc_rom_*` entries) must carry one of the
two plusargs, or be listed in `RANDOM_STRAP_OK` with the reason it tolerates
both strap states. `RANDOM_STRAP_OK` is held to `RANDOM_STRAP_OK_CEILING`, so it
can only shrink: a new status-dependent entry declares its mode instead.

Run from the repository root:

    python3 -m unittest tools/dv/tests/test_smc_rom_status_reporting.py
"""

import tomllib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TESTLIST = REPO_ROOT / "hw" / "sys" / "smc" / "dv" / "testlists" / "smc_rom.toml"

CHECKED_MODES = {"occp_rom_only"}
STRAP_ARGS = {"+FORCE_STATUS_REPORTING", "+STATUS_RPT_DISABLE"}

_LIB_GUARD = (
    "status commands go through the OCCP command library, which expects "
    "OCCP_UNSUPPORTED_STATUS and skips status-buffer checks when the strap is set"
)

# Entries that keep the random strap, with the reason each tolerates both states.
RANDOM_STRAP_OK: dict[str, str] = {
    "smc_occp_sanity_test": _LIB_GUARD,
    "smc_occp_random_command_test": _LIB_GUARD,
    "smc_occp_mem_boundary_access_test": _LIB_GUARD,
    "smc_occp_invalid_cmd_test": _LIB_GUARD,
    "smc_occp_invalid_length_field_test": _LIB_GUARD,
    "smc_occp_undersize_header_test": _LIB_GUARD,
    "smc_occp_unaligned_access_test": _LIB_GUARD,
    "smc_occp_zero_length_rw_test": _LIB_GUARD,
    "smc_occp_max_size_transfer_test": _LIB_GUARD,
    "smc_occp_min_size_transfer_test": _LIB_GUARD,
    "smc_occp_jump_invalid_region_test": _LIB_GUARD,
    "smc_occp_register_access_test": _LIB_GUARD,
    "smc_occp_validate_boot_invalid_region_test": _LIB_GUARD,
    "smc_occp_secure_access_test": _LIB_GUARD,
    "smc_occp_undersize_body_test": _LIB_GUARD,
    "smc_occp_oversize_body_test": _LIB_GUARD,
    "smc_occp_jump_rejection_test": _LIB_GUARD,
    "smc_rom_invalid_lc_state_test": _LIB_GUARD,
    "smc_rom_mem_repair_fail_test": _LIB_GUARD,
    "smc_rom_mbist_fail_test": _LIB_GUARD,
    "smc_rom_mbist_timeout_test": _LIB_GUARD,
    "smc_occp_validate_boot_test": _LIB_GUARD,
}

# Size of `RANDOM_STRAP_OK` at the audit. It never grows.
RANDOM_STRAP_OK_CEILING = 22


def _checked_entries() -> dict[str, set[str]]:
    with TESTLIST.open("rb") as f:
        tests = tomllib.load(f)["tests"]
    return {
        t["name"]: set(t.get("args", [])) for t in tests if t["firmware"]["mode"] in CHECKED_MODES
    }


class SmcRomStatusReportingTest(unittest.TestCase):
    def test_every_entry_declares_a_strap_mode(self):
        undeclared = sorted(
            name
            for name, args in _checked_entries().items()
            if not (args & STRAP_ARGS) and name not in RANDOM_STRAP_OK
        )
        self.assertEqual(
            undeclared,
            [],
            "entries with neither +FORCE_STATUS_REPORTING nor +STATUS_RPT_DISABLE "
            "and no RANDOM_STRAP_OK reason",
        )

    def test_random_strap_ok_is_current(self):
        entries = _checked_entries()
        stale = sorted(n for n in RANDOM_STRAP_OK if n not in entries)
        self.assertEqual(stale, [], "RANDOM_STRAP_OK names entries that no longer exist")
        declared = sorted(n for n in RANDOM_STRAP_OK if entries.get(n, set()) & STRAP_ARGS)
        self.assertEqual(declared, [], "RANDOM_STRAP_OK names entries that now declare a mode")

    def test_random_strap_ok_does_not_grow(self):
        self.assertLessEqual(len(RANDOM_STRAP_OK), RANDOM_STRAP_OK_CEILING)

    def test_both_strap_args_are_not_combined(self):
        both = sorted(n for n, a in _checked_entries().items() if STRAP_ARGS <= a)
        self.assertEqual(both, [])


if __name__ == "__main__":
    unittest.main()
