# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Every `+smc_reset_sva_need_<group>` in an SMC testlist names a reported group.

`smc_reset_sva.sv` fails a run whose `+smc_reset_sva_need_<group>` count is 0
and judges only the first need plusarg of a run for an unknown group, so a
misspelled plusarg behind a correct one would pass silently. The groups are the
`SMC_RESET_SVA_REPORT` lines of the checker; this test reads them and checks
every need plusarg in every `args` list of every SMC testlist against that set.

    python3 -m unittest tools.dv.tests.test_smc_reset_sva_plusargs
"""

import re
import tomllib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SMC_DV = REPO_ROOT / "hw" / "sys" / "smc" / "dv"
CHECKER = SMC_DV / "tb" / "smc_reset_sva.sv"
TESTLISTS = sorted((SMC_DV / "testlists").glob("*.toml"))

REPORTED_GROUP = re.compile(r'`SMC_RESET_SVA_REPORT\("([a-z0-9_]+)"')
NEED_PLUSARG = re.compile(r"^\+smc_reset_sva_need_(\S*)$")


def reported_groups() -> set[str]:
    """Return the groups the checker's final block reports."""
    return set(REPORTED_GROUP.findall(CHECKER.read_text()))


def need_plusargs(testlist: Path) -> list[tuple[str, str]]:
    """Return (entry name, group) for every need plusarg in the testlist."""
    found: list[tuple[str, str]] = []

    def walk(node, owner: str) -> None:
        if isinstance(node, dict):
            owner = node.get("name", owner)
            for key, value in node.items():
                if key == "args" and isinstance(value, list):
                    for arg in value:
                        match = NEED_PLUSARG.match(str(arg))
                        if match:
                            found.append((owner, match.group(1)))
                else:
                    walk(value, owner)
        elif isinstance(node, list):
            for item in node:
                walk(item, owner)

    with testlist.open("rb") as fh:
        walk(tomllib.load(fh), testlist.name)
    return found


class SmcResetSvaPlusargs(unittest.TestCase):
    def test_checker_reports_groups(self) -> None:
        self.assertGreaterEqual(len(reported_groups()), 12, CHECKER)

    def test_testlists_carry_need_plusargs(self) -> None:
        self.assertTrue(any(need_plusargs(t) for t in TESTLISTS), TESTLISTS)

    def test_every_need_plusarg_names_a_reported_group(self) -> None:
        groups = reported_groups()
        unknown = [
            f"{testlist.name}: {owner}: +smc_reset_sva_need_{group}"
            for testlist in TESTLISTS
            for owner, group in need_plusargs(testlist)
            if group not in groups
        ]
        self.assertEqual(unknown, [], f"reported groups: {sorted(groups)}")


if __name__ == "__main__":
    unittest.main()
