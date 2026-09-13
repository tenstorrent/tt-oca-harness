# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for the formal backend registry: the `sby` entry, the `native-formal` profile, and
the --doctor / --list views of a free default backend beside licensed ones.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

from __future__ import annotations

import io
import re
import sys
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib import cli  # noqa: E402
from runlib.config import configs_root, load_profile, load_simulators  # noqa: E402
from runlib.models import ConfigError, Dut  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def formal_flow(tools: list[str], default_tool: str) -> Dut:
    return Dut(
        name="unit_fv",
        kind="fv",
        description="unit-test formal flow",
        framework="formal",
        visibility="public",
        runnability="contributor",
        license="none",
        root=".",
        default_tool=default_tool,
        tools=tools,
        path=Path("unit_formal_cfg.toml"),
        raw={},
        frameworks=["formal"],
        default_framework="formal",
    )


class RegistryFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.simulators = load_simulators(REPO_ROOT)
        cls.profile = load_profile(configs_root(REPO_ROOT), "native-formal", Path("unit"))

    def licensed_tool(self) -> str:
        return next(name for name, cfg in sorted(self.simulators.items()) if cfg["license_env"])


class FormalRegistryTest(RegistryFixture):
    def test_sby_is_a_license_free_formal_backend(self) -> None:
        sby = self.simulators["sby"]
        self.assertEqual(sby["kind"], "formal")
        self.assertEqual(sby["binary"], "sby")
        self.assertEqual(sby["frameworks"], ["formal"])
        self.assertEqual(sby["license_env"], [])
        self.assertEqual(sby["supports_cov"], ["formal"])

    def test_formal_backends_serve_the_formal_framework_only(self) -> None:
        formal = {name for name, cfg in self.simulators.items() if cfg.get("kind") == "formal"}
        self.assertIn("sby", formal)
        for name in formal:
            self.assertEqual(self.simulators[name]["frameworks"], ["formal"], name)

    def test_profile_defaults_to_sby_and_keeps_licensed_backends_selectable(self) -> None:
        self.assertEqual(self.profile["default_tool"], "sby")
        self.assertEqual(self.profile["tools"][0], "sby")
        for tool in self.profile["tools"]:
            self.assertEqual(self.simulators[tool]["kind"], "formal", tool)
        licensed = [tool for tool in self.profile["tools"] if self.simulators[tool]["license_env"]]
        self.assertTrue(licensed)

    def test_profile_license_marking_follows_the_default_backend(self) -> None:
        self.assertEqual(self.profile["license"], "none")
        self.assertEqual(self.profile["visibility"], "public")
        self.assertEqual(self.profile["runnability"], "contributor")
        self.assertEqual(self.simulators[self.profile["default_tool"]]["license_env"], [])


def which_from(found: dict[str, str]):
    """A `shutil.which` stand-in that answers from `found` whatever PATH it is asked to search."""

    def which(executable: str, mode: int = 0, path: str | None = None) -> str | None:
        return found.get(executable)

    return which


class DoctorToolTableTest(RegistryFixture):
    def run_doctor(self, tool: str, found: dict[str, str]) -> tuple[int, str]:
        args = Namespace(dut=None, tool=tool, mode="sim", framework=None, overlay=None)
        out = io.StringIO()
        with (
            mock.patch.object(cli, "load_duts", return_value={}),
            mock.patch.object(cli, "load_site_layer", return_value=None),
            mock.patch.object(cli, "_doctor_python_environment", return_value=False),
            mock.patch("shutil.which", side_effect=which_from(found)),
            redirect_stdout(out),
        ):
            rc = cli.cmd_doctor(REPO_ROOT, args)
        return rc, out.getvalue()

    def test_sby_on_path_is_found_with_no_license_needed(self) -> None:
        rc, out = self.run_doctor("sby", {"sby": "/opt/fv/bin/sby"})
        self.assertEqual(rc, 0)
        row = next(line for line in out.splitlines() if line.split()[:1] == ["sby"])
        self.assertIn("found: /opt/fv/bin/sby", row)
        self.assertIn("none needed", row)
        self.assertIn("Result: required tool `sby` is available", out)

    def test_missing_sby_draws_no_license_note(self) -> None:
        rc, out = self.run_doctor("sby", {})
        self.assertEqual(rc, 2)
        self.assertIn("MISSING from PATH", out)
        self.assertNotIn("Note:", out)

    def test_missing_licensed_tool_points_at_the_list_marking(self) -> None:
        tool = self.licensed_tool()
        rc, out = self.run_doctor(tool, {})
        self.assertEqual(rc, 2)
        self.assertIn(f"Note: `{tool}` needs a commercial license", out)
        self.assertIn("(licensed)", out)


class SelectedToolAvailabilityTest(RegistryFixture):
    def check(self, tool: str) -> str:
        flow = formal_flow([tool], tool)
        with (
            mock.patch("shutil.which", side_effect=which_from({})),
            self.assertRaises(ConfigError) as ctx,
        ):
            cli.validate_selected_tool_available(
                tool, self.simulators, Namespace(dry_run=False), flow
            )
        return str(ctx.exception)

    def test_absent_free_tool_gets_no_license_hint(self) -> None:
        message = self.check("sby")
        self.assertIn("requires `sby` in PATH", message)
        self.assertNotIn("license", message)

    def test_absent_licensed_tool_gets_the_hint(self) -> None:
        tool = self.licensed_tool()
        message = self.check(tool)
        self.assertIn(f"`{tool}` needs a commercial license", message)
        self.assertIn("(licensed)", message)


class ListFlowsMarkingTest(RegistryFixture):
    def test_free_default_is_unmarked_and_licensed_backends_are_marked(self) -> None:
        flow = formal_flow(list(self.profile["tools"]), self.profile["default_tool"])
        out = io.StringIO()
        with redirect_stdout(out):
            cli.list_flows({flow.name: flow}, self.simulators)
        row = next(
            line for line in ANSI_RE.sub("", out.getvalue()).splitlines() if "unit_fv" in line
        )
        self.assertRegex(row, r"\bformal\s+sby/")
        self.assertNotIn("formal (licensed)", row)
        self.assertNotIn("sby (licensed)", row)
        for tool in self.profile["tools"]:
            if self.simulators[tool]["license_env"]:
                self.assertIn(f"{tool} (licensed)", row)


if __name__ == "__main__":
    unittest.main()
