# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for formal view discovery: a DUT's formal config found by convention, through the
registry, or through the site layer; its `--validate-configs` row, `--list` row, and `--list
--json` entry; the unavailable state of a site-named config whose file is absent; and how an
`alias_of` name is listed.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import textwrap
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib import cli  # noqa: E402
from runlib.duts import (  # noqa: E402
    discover_formal_views,
    formal_view,
    list_dut_names,
    load_formal_views,
    resolve_dut,
)
from runlib.models import ConfigError  # noqa: E402
from runlib.site import load_site_layer  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_CONFIGS = REPO_ROOT / "hw" / "common" / "dv" / "configs"

SIM_CFG = """
schema_version = 1
name = "{name}"
profile = "native"
default_framework = "cocotb"
description = "{name} cocotb flow"
default_tool = "verilator"
tools = ["verilator"]

[testlist]
path = "testlists/all.toml"

[build]
top_module = "{name}_tb_top"
top_file = "hw/sys/{name}/dv/tb/tb_top.sv"
filelist = "hw/sys/{name}/dv/build/{name}.f"
bender_filelist = "hw/sys/{name}/dv/build/{name}_bender.f"
work_dir = "hw/sys/{name}/dv/build"

[run_modes.smoke]
description = "{name} smoke"
timeout_sec = 600
args = []

[frameworks.cocotb]
python_root = "hw/sys/{name}/dv/cocotb"
test_dir = "hw/sys/{name}/dv/cocotb/tests"
results_dir = "{{run_dir}}/{{item}}/results"
cocotb_log = "{{run_dir}}/{{item}}/logs/{{item}}.log"

[targets.default]
build_dir = "hw/sys/{name}/dv/build/cocotb"
"""

SIM_TESTLIST = """
schema_version = 1

[[tests]]
name = "{name}_smoke"
module = "test_{name}"
"""

FORMAL_CFG = """
name = "{name}"
kind = "fv"
profile = "native-formal"
description = "{name} TAP formal"

[testlist]
path = "formal_testlist.toml"

[formal.apps.fpv.sby]
cwd = "hw/sys/{name}/dv/formal/fpv/sby"
script = "{name}.sby"
args = ["bmc", "cover"]

[targets.default]
build_dir = "hw/sys/{name}/dv/formal/build"
"""

FORMAL_TESTLIST = """
schema_version = 1

[[tests]]
name = "{name}_fpv"
module = "fpv"
"""


class TempRepo(unittest.TestCase):
    """A repository root with the real registries and profiles and two conventional DUTs.

    `widget` and `gizmo` carry sim configs; `widget` also carries `widget_formal_cfg.toml`.
    `gizmo` is registered with a `formal_cfg` pointer whose file is absent.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        configs = self.root / "hw" / "common" / "dv" / "configs"
        configs.mkdir(parents=True)
        for name in ("simulators.toml", "executors.toml", "parsers.toml"):
            shutil.copy(REAL_CONFIGS / name, configs / name)
        shutil.copytree(REAL_CONFIGS / "profiles", configs / "profiles")
        self.write(
            "hw/common/dv/configs/duts.toml",
            """
            schema_version = 1
            [duts.gizmo]
            root = "hw/sys/gizmo/dv"
            formal_cfg = "hw/sys/gizmo/dv/absent_formal_cfg.toml"
            """,
        )
        for name in ("widget", "gizmo"):
            self.write(f"hw/sys/{name}/dv/{name}_sim_cfg.toml", SIM_CFG.format(name=name))
            self.write(f"hw/sys/{name}/dv/testlists/all.toml", SIM_TESTLIST.format(name=name))
        self.write_formal("widget", "hw/sys/widget/dv/widget_formal_cfg.toml")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, rel: str, text: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
        return path

    def write_formal(self, name: str, rel: str) -> Path:
        cfg = self.write(rel, FORMAL_CFG.format(name=name))
        self.write(
            str(Path(rel).parent / "formal_testlist.toml"), FORMAL_TESTLIST.format(name=name)
        )
        return cfg

    def write_site(self, text: str) -> None:
        self.write("hw/common/dv/configs/site.local.toml", "schema_version = 1\n" + text)

    def site(self):
        return load_site_layer(self.root, {})


class DiscoveryTest(TempRepo):
    def test_convention_registry_and_absence(self) -> None:
        self.assertEqual(list_dut_names(self.root), ["gizmo", "widget"])
        widget = formal_view(self.root, "widget")
        assert widget is not None
        self.assertEqual(widget.source, "convention")
        self.assertTrue(widget.available)
        self.assertEqual(widget.path, self.root / "hw/sys/widget/dv/widget_formal_cfg.toml")
        gizmo = formal_view(self.root, "gizmo")
        assert gizmo is not None
        self.assertEqual(gizmo.source, "registry")
        self.assertFalse(gizmo.available)
        self.assertIn("named by duts.toml", gizmo.reason)
        (self.root / "hw/sys/widget/dv/widget_formal_cfg.toml").unlink()
        self.assertIsNone(formal_view(self.root, "widget"))

    def test_site_pointer_wins_and_may_be_unavailable(self) -> None:
        cfg = self.write_formal("widget", "companion/widget/widget_formal_cfg.toml")
        self.write_site(f'[duts.widget]\nformal_cfg = "{cfg.relative_to(self.root)}"\n')
        view = formal_view(self.root, "widget", self.site())
        assert view is not None
        self.assertEqual((view.source, view.path, view.available), ("site", cfg, True))
        self.write_site('[duts.widget]\nformal_cfg = "companion/absent.toml"\n')
        view = formal_view(self.root, "widget", self.site())
        assert view is not None
        self.assertEqual(view.source, "site")
        self.assertFalse(view.available)
        self.assertIn("named by the site layer", view.reason)

    def test_load_formal_views_loads_only_available_ones(self) -> None:
        views = load_formal_views(self.root)
        self.assertEqual(sorted(views), ["gizmo", "widget"])
        assert views["widget"].flow is not None
        self.assertEqual(views["widget"].flow.kind, "fv")
        self.assertEqual(views["widget"].flow.default_tool, "sby")
        self.assertIsNone(views["gizmo"].flow)
        self.assertEqual(
            {name: view.path for name, view in discover_formal_views(self.root).items()},
            {name: view.path for name, view in views.items()},
        )

    def test_selecting_an_unavailable_view_names_the_pointer(self) -> None:
        with self.assertRaises(ConfigError) as ctx:
            resolve_dut(self.root, "gizmo", mode="formal")
        self.assertIn("formal config not found", str(ctx.exception))
        self.assertIn("named by duts.toml", str(ctx.exception))
        flow = resolve_dut(self.root, "widget", mode="formal")
        self.assertEqual(flow.description, "widget TAP formal")


class ValidateConfigsTest(TempRepo):
    def validate(self) -> tuple[int, str]:
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cli.cmd_validate_configs(self.root)
        return rc, out.getvalue()

    def row(self, out: str, label: str) -> str:
        return next(line for line in out.splitlines() if line.strip().startswith(label))

    def test_formal_rows_follow_the_simulation_rows(self) -> None:
        rc, out = self.validate()
        self.assertEqual(rc, 2, out)
        self.assertRegex(self.row(out, "widget (formal)"), r"widget \(formal\)\s+OK")
        gizmo = self.row(out, "gizmo (formal)")
        self.assertIn("FAIL: formal config not found", gizmo)
        self.assertIn("named by duts.toml", gizmo)
        self.assertIn("2 DUT(s), 4 view(s): 3 OK, 1 FAILED", out)

    def test_absent_site_named_config_is_unavailable_not_fatal(self) -> None:
        self.write(
            "hw/common/dv/configs/duts.toml",
            'schema_version = 1\n[duts.gizmo]\nroot = "hw/sys/gizmo/dv"\n',
        )
        self.write_site('[duts.gizmo]\nformal_cfg = "companion/gizmo/gizmo_formal_cfg.toml"\n')
        rc, out = self.validate()
        self.assertEqual(rc, 0, out)
        gizmo = self.row(out, "gizmo (formal)")
        self.assertIn("UNAVAILABLE: formal config not found", gizmo)
        self.assertIn("named by the site layer", gizmo)
        self.assertIn("4 view(s): 3 OK, 0 FAILED, 1 unavailable", out)

    def test_broken_formal_config_fails_its_own_row(self) -> None:
        path = self.root / "hw/sys/widget/dv/widget_formal_cfg.toml"
        path.write_text(path.read_text() + "\n[frobnicate]\nx = 1\n", encoding="utf-8")
        rc, out = self.validate()
        self.assertEqual(rc, 2)
        self.assertIn("frobnicate", self.row(out, "widget (formal)"))
        self.assertRegex(self.row(out, "widget "), r"^\s+widget\s+OK")


class ListingTest(TempRepo):
    def setUp(self) -> None:
        super().setUp()
        self.write(
            "hw/common/dv/configs/duts.toml",
            'schema_version = 1\n[duts.gizmo]\nroot = "hw/sys/gizmo/dv"\n',
        )
        self.write_site('[duts.gizmo]\nformal_cfg = "companion/gizmo/gizmo_formal_cfg.toml"\n')

    def test_validate_all_returns_the_views(self) -> None:
        duts, registries, views = cli.validate_all(self.root)
        self.assertEqual(sorted(duts), ["gizmo", "widget"])
        assert registries.site is not None
        self.assertIsNotNone(views["widget"].flow)
        self.assertIsNone(views["gizmo"].flow)

    def test_list_rows(self) -> None:
        duts, registries, views = cli.validate_all(self.root)
        out = io.StringIO()
        with redirect_stdout(out):
            cli.list_flows(duts, registries.simulators, views)
        lines = [line for line in out.getvalue().splitlines()]
        widget_rows = [line for line in lines if line.startswith("widget")]
        self.assertEqual(len(widget_rows), 2)
        self.assertRegex(widget_rows[0], r"^widget\s+dv\s+.*cocotb")
        fv = widget_rows[1]
        self.assertRegex(fv, r"^widget\s+fv\s+.*formal")
        self.assertIn("sby", fv)
        self.assertNotIn("(licensed)", fv)
        self.assertTrue(fv.endswith("widget TAP formal"), fv)
        gizmo_fv = next(line for line in lines if line.startswith("gizmo") and " fv " in line)
        self.assertIn("unavailable: formal config not found", gizmo_fv)
        # The formal row follows the DUT's own rows, ahead of the next DUT.
        names = [line.split()[0] for line in lines[1:] if line and not line.startswith(" ")]
        self.assertEqual(names, ["gizmo", "gizmo", "widget", "widget"])

    def test_list_json_entries(self) -> None:
        duts, registries, views = cli.validate_all(self.root)
        out = io.StringIO()
        with redirect_stdout(out):
            cli.list_flows_json(self.root, duts, views)
        entries = json.loads(out.getvalue())["duts"]
        by_key = {(entry["name"], entry["mode"]): entry for entry in entries}
        self.assertEqual(by_key[("widget", "sim")]["available"], True)
        self.assertEqual(by_key[("widget", "sim")]["framework"], "cocotb")
        formal = by_key[("widget", "formal")]
        self.assertEqual(
            (formal["kind"], formal["framework"], formal["available"]), ("fv", "formal", True)
        )
        self.assertEqual(formal["default_tool"], "sby")
        gizmo = by_key[("gizmo", "formal")]
        self.assertEqual(gizmo["available"], False)
        self.assertEqual(gizmo["path"], "companion/gizmo/gizmo_formal_cfg.toml")
        self.assertIn("named by the site layer", gizmo["reason"])
        runnable = [e["name"] for e in entries if e["mode"] == "formal" and e["available"]]
        self.assertEqual(runnable, ["widget"])

    def test_doctor_preflight_covers_formal_views(self) -> None:
        args = Namespace(dut=None, tool="sby", mode="sim", framework=None, overlay=None)

        def doctor() -> str:
            out = io.StringIO()
            with (
                mock.patch.object(cli, "_doctor_python_environment", return_value=False),
                mock.patch("shutil.which", return_value="/usr/bin/sby"),
                redirect_stdout(out),
            ):
                cli.cmd_doctor(self.root, args)
            return out.getvalue()

        self.assertIn("configs : OK", doctor())
        path = self.root / "hw/sys/widget/dv/widget_formal_cfg.toml"
        path.write_text(path.read_text() + "\n[frobnicate]\nx = 1\n", encoding="utf-8")
        report = doctor()
        self.assertIn("configs : FAIL", report)
        self.assertIn("frobnicate", report)


class AliasListingTest(TempRepo):
    """An `alias_of` name is listed once, as a row naming the DUT it selects."""

    def setUp(self) -> None:
        super().setUp()
        self.write(
            "hw/common/dv/configs/duts.toml",
            """
            schema_version = 1
            [duts.gizmo]
            root = "hw/sys/gizmo/dv"
            [duts.gizmo_alt]
            root = "hw/sys/gizmo/dv"
            alias_of = "gizmo"
            [duts.widget_alt]
            root = "hw/sys/widget/dv"
            alias_of = "widget"
            """,
        )

    def listing(self) -> list[str]:
        duts, registries, views = cli.validate_all(self.root)
        out = io.StringIO()
        with redirect_stdout(out):
            cli.list_flows(duts, registries.simulators, views)
        return out.getvalue().splitlines()

    def entries(self) -> list[dict]:
        duts, _registries, views = cli.validate_all(self.root)
        out = io.StringIO()
        with redirect_stdout(out):
            cli.list_flows_json(self.root, duts, views)
        return json.loads(out.getvalue())["duts"]

    def test_alias_row_names_its_dut(self) -> None:
        lines = self.listing()
        names = [line.split()[0] for line in lines[1:] if line and not line.startswith(" ")]
        self.assertEqual(names, ["gizmo", "gizmo_alt", "widget", "widget", "widget_alt"])
        self.assertRegex(
            next(line for line in lines if line.startswith("widget_alt")),
            r"^widget_alt\s+alias of widget$",
        )

    def test_json_lists_each_dut_once_with_its_aliases(self) -> None:
        entries = self.entries()
        keys = [(e["name"], e["mode"], e["framework"]) for e in entries]
        self.assertEqual(
            keys,
            [
                ("gizmo", "sim", "cocotb"),
                ("widget", "sim", "cocotb"),
                ("widget", "formal", "formal"),
            ],
        )
        self.assertEqual(
            {(e["name"], e["mode"]): e["aliases"] for e in entries},
            {
                ("gizmo", "sim"): ["gizmo_alt"],
                ("widget", "sim"): ["widget_alt"],
                ("widget", "formal"): ["widget_alt"],
            },
        )

    def test_formal_view_only_the_alias_reaches_is_listed(self) -> None:
        cfg = self.write_formal("gizmo", "companion/gizmo/gizmo_formal_cfg.toml")
        self.write_site(f'[duts.gizmo_alt]\nformal_cfg = "{cfg.relative_to(self.root)}"\n')
        self.assertRegex(
            next(line for line in self.listing() if " fv " in line and "gizmo" in line),
            r"^gizmo_alt\s+fv\s+.*gizmo TAP formal$",
        )
        formal = [e for e in self.entries() if e["mode"] == "formal"]
        self.assertEqual([e["name"] for e in formal], ["gizmo_alt", "widget"])


if __name__ == "__main__":
    unittest.main()
