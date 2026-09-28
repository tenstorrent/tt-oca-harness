# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for simulation views the site layer names: a `[duts.<name>] sim_cfg` pointer that
replaces a DUT's simulation config, its `--validate-configs` row, `--list` row and `--list --json`
entry, and the unavailable state of a pointer whose file is absent.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib import cli  # noqa: E402
from runlib.duts import unavailable_sim_views  # noqa: E402
from test_formal_views import SIM_CFG, SIM_TESTLIST, TempRepo  # noqa: E402

ABSENT = "companion/gizmo/gizmo_sim_cfg.toml"


class SiteSimViewTest(TempRepo):
    """`widget` keeps its own configs; the site layer points `gizmo`'s simulation view away."""

    def setUp(self) -> None:
        super().setUp()
        self.write(
            "hw/common/dv/configs/duts.toml",
            'schema_version = 1\n[duts.gizmo]\nroot = "hw/sys/gizmo/dv"\n',
        )

    def validate(self) -> tuple[int, str]:
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cli.cmd_validate_configs(self.root)
        return rc, out.getvalue()

    def listings(self) -> tuple[list[str], list[dict]]:
        duts, registries, views = cli.validate_all(self.root)
        absent = unavailable_sim_views(self.root, registries.site)
        table, entries = io.StringIO(), io.StringIO()
        with redirect_stdout(table):
            cli.list_flows(duts, registries.simulators, views, absent, self.root, registries.site)
        with redirect_stdout(entries):
            cli.list_flows_json(self.root, duts, views, absent, registries.site)
        return table.getvalue().splitlines(), json.loads(entries.getvalue())["duts"]

    def test_absent_site_sim_cfg_is_unavailable_not_fatal(self) -> None:
        self.write_site(f'[duts.gizmo]\nsim_cfg = "{ABSENT}"\n')
        rc, out = self.validate()
        self.assertEqual(rc, 0, out)
        gizmo = next(line for line in out.splitlines() if line.strip().startswith("gizmo"))
        self.assertIn("UNAVAILABLE: sim config not found", gizmo)
        self.assertIn("named by the site layer", gizmo)
        self.assertIn("2 DUT(s), 3 view(s): 2 OK, 0 FAILED, 1 unavailable", out)

    def test_absent_site_sim_cfg_lists_one_unavailable_row_and_entry(self) -> None:
        self.write_site(f'[duts.gizmo]\nsim_cfg = "{ABSENT}"\n')
        table, entries = self.listings()
        gizmo_rows = [line for line in table if line.startswith("gizmo")]
        self.assertEqual(len(gizmo_rows), 1)
        self.assertIn("unavailable: sim config not found", gizmo_rows[0])
        gizmo = [entry for entry in entries if entry["name"] == "gizmo"]
        self.assertEqual(
            gizmo,
            [
                {
                    "name": "gizmo",
                    "mode": "sim",
                    "available": False,
                    "path": ABSENT,
                    "reason": gizmo[0]["reason"],
                    "aliases": [],
                }
            ],
        )
        self.assertIn("named by the site layer", gizmo[0]["reason"])
        widget = [(e["mode"], e["available"]) for e in entries if e["name"] == "widget"]
        self.assertEqual(widget, [("sim", True), ("formal", True)])

    def test_site_sim_cfg_view_is_loaded_validated_and_listed(self) -> None:
        cfg = self.write(ABSENT, SIM_CFG.format(name="gizmo"))
        self.write(
            str(Path(ABSENT).parent / "testlists/all.toml"), SIM_TESTLIST.format(name="gizmo")
        )
        self.write_site(f'[duts.gizmo]\nsim_cfg = "{ABSENT}"\n')
        rc, out = self.validate()
        self.assertEqual(rc, 0, out)
        self.assertIn("2 DUT(s), 3 view(s): 3 OK, 0 FAILED", out)
        duts, _registries, _views = cli.validate_all(self.root)
        self.assertEqual(duts["gizmo"].path, cfg)
        _table, entries = self.listings()
        gizmo = next(entry for entry in entries if entry["name"] == "gizmo")
        self.assertEqual((gizmo["mode"], gizmo["available"]), ("sim", True))


if __name__ == "__main__":
    unittest.main()
