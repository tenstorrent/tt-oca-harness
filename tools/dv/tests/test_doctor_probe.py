# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for --doctor: the import probe (batching, timeout retry, the budget knob), the
module selection `--items`/`--tag` scope, and the tool version rows with the Verilator floor.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

from __future__ import annotations

import io
import sys
import tempfile
import textwrap
import unittest
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib import cli  # noqa: E402
from runlib.cli import _probe_imports, doctor_probe_timeout  # noqa: E402
from runlib.config import load_simulators  # noqa: E402
from runlib.models import ConfigError, Dut, TestCatalog, TestEntry  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]


def write_module(root: Path, name: str, body: str) -> None:
    (root / f"{name}.py").write_text(textwrap.dedent(body), encoding="utf-8")


class ProbeImportsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        write_module(self.root, "probe_ok", "VALUE = 1\n")
        write_module(self.root, "probe_bad", 'raise ImportError("boom")\n')
        write_module(
            self.root,
            "probe_slow",
            """
            import time

            time.sleep(5)
            """,
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_reports_each_module_from_its_own_import(self) -> None:
        results = _probe_imports([self.root], ["probe_ok", "probe_bad"])
        self.assertEqual(results["probe_ok"], (True, "import OK"))
        self.assertFalse(results["probe_bad"][0])
        self.assertIn("ImportError: boom", results["probe_bad"][1])

    def test_timeout_fails_only_its_own_batch(self) -> None:
        results = _probe_imports([self.root], ["probe_slow", "probe_ok"], timeout=0.2, batch_size=1)
        self.assertEqual(results["probe_ok"], (True, "import OK"))
        self.assertFalse(results["probe_slow"][0])
        self.assertIn("timed out twice", results["probe_slow"][1])
        self.assertIn("OCAH_DOCTOR_PROBE_TIMEOUT", results["probe_slow"][1])

    def test_retry_recovers_a_batch_that_is_slow_once(self) -> None:
        marker = self.root / "warm.marker"
        write_module(
            self.root,
            "probe_cold",
            f"""
            import pathlib
            import time

            marker = pathlib.Path({str(marker)!r})
            if not marker.exists():
                marker.touch()
                time.sleep(5)
            """,
        )
        results = _probe_imports([self.root], ["probe_cold"], timeout=0.5, batch_size=1)
        self.assertEqual(results["probe_cold"], (True, "import OK"))

    def test_empty_module_list_probes_nothing(self) -> None:
        self.assertEqual(_probe_imports([self.root], []), {})


class DoctorProbeTimeoutTest(unittest.TestCase):
    def test_default_when_unset(self) -> None:
        with mock.patch.object(cli, "DOCTOR_PROBE_TIMEOUT_ENV", ""):
            self.assertEqual(doctor_probe_timeout(), cli.DOCTOR_PROBE_TIMEOUT_DEFAULT)

    def test_positive_number_is_used(self) -> None:
        with mock.patch.object(cli, "DOCTOR_PROBE_TIMEOUT_ENV", " 300 "):
            self.assertEqual(doctor_probe_timeout(), 300.0)

    def test_rejects_non_numeric_and_non_positive(self) -> None:
        for raw in ("abc", "0", "-5"):
            with (
                self.subTest(raw=raw),
                mock.patch.object(cli, "DOCTOR_PROBE_TIMEOUT_ENV", raw),
                self.assertRaises(ConfigError),
            ):
                doctor_probe_timeout()


def unit_catalog() -> TestCatalog:
    """Three scenarios: two with a cocotb module, one out of scope for the framework."""
    tests = {
        "a_test": TestEntry(name="a_test", module="pkg.a", tags=["fast"]),
        "b_test": TestEntry(name="b_test", module="pkg.b", tags=["slow"]),
        "c_test": TestEntry(name="c_test", module="", tags=["fast"]),
    }
    groups = {"smoke": ["a_test"], "all": ["a_test", "b_test", "c_test"]}
    return TestCatalog(path=None, tests=tests, groups=groups)


def cocotb_flow() -> Dut:
    return Dut(
        name="unit",
        kind="dv",
        description="unit-test cocotb flow",
        framework="cocotb",
        visibility="public",
        runnability="contributor",
        license="none",
        root=".",
        default_tool="verilator",
        tools=["verilator"],
        path=Path("unit_sim_cfg.toml"),
        raw={},
        frameworks=["cocotb"],
        default_framework="cocotb",
    )


class DoctorModuleSelectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = unit_catalog()

    def test_no_selection_probes_every_test(self) -> None:
        names, scope = cli._doctor_module_selection(self.catalog, Namespace(items=None, tag=None))
        self.assertEqual(names, ["a_test", "b_test", "c_test"])
        self.assertEqual(scope, "")

    def test_absent_arguments_probe_every_test(self) -> None:
        names, scope = cli._doctor_module_selection(self.catalog, None)
        self.assertEqual(names, ["a_test", "b_test", "c_test"])
        self.assertEqual(scope, "")

    def test_items_select_a_group_as_a_run_does(self) -> None:
        names, scope = cli._doctor_module_selection(
            self.catalog, Namespace(items=["smoke"], tag=None)
        )
        self.assertEqual(names, ["a_test"])
        self.assertEqual(scope, "--items smoke")

    def test_tags_filter_the_items(self) -> None:
        names, scope = cli._doctor_module_selection(
            self.catalog, Namespace(items=["all"], tag=["fast"])
        )
        self.assertEqual(names, ["a_test", "c_test"])
        self.assertEqual(scope, "--items all --tag fast")

    def test_tags_alone_start_from_the_whole_catalog(self) -> None:
        names, scope = cli._doctor_module_selection(
            self.catalog, Namespace(items=None, tag=["slow"])
        )
        self.assertEqual(names, ["b_test"])
        self.assertEqual(scope, "--tag slow")

    def test_unknown_item_is_a_config_error(self) -> None:
        with self.assertRaises(ConfigError):
            cli._doctor_module_selection(self.catalog, Namespace(items=["nosuch"], tag=None))

    def test_tag_matching_nothing_is_a_config_error(self) -> None:
        with self.assertRaises(ConfigError):
            cli._doctor_module_selection(self.catalog, Namespace(items=None, tag=["cold"]))


class DoctorPythonEnvironmentScopeTest(unittest.TestCase):
    """The module probe covers exactly the selection, and only an unscoped failure draws the hint."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "build/dv/python").mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_environment(
        self, args: Namespace | None, failing: dict[str, str]
    ) -> tuple[bool, str, list[list[str]]]:
        selection = None
        if args is not None and (args.items or args.tag):
            selection = cli._doctor_module_selection(unit_catalog(), args)
        probed: list[list[str]] = []

        def probe(
            paths: list[Path], modules: list[str], **_: object
        ) -> dict[str, tuple[bool, str]]:
            probed.append(list(modules))
            return {
                name: (False, failing[name]) if name in failing else (True, "import OK")
                for name in modules
            }

        out = io.StringIO()
        with (
            mock.patch.object(cli, "_python_supported", return_value=(True, "3.11.0")),
            mock.patch.object(cli, "_dist_version", return_value="1.0"),
            mock.patch.object(cli, "_path_in_pythonpath", return_value=True),
            mock.patch.object(cli, "load_test_catalog", return_value=unit_catalog()),
            mock.patch.object(cli, "cocotb_cfg", return_value={}),
            mock.patch.object(cli, "cocotb_python_paths", return_value=[]),
            mock.patch.object(cli, "_probe_imports", side_effect=probe),
            redirect_stdout(out),
        ):
            failed = cli._doctor_python_environment(self.root, cocotb_flow(), selection)
        return failed, out.getvalue(), probed

    def test_unscoped_probe_imports_every_bound_module(self) -> None:
        failed, out, probed = self.run_environment(Namespace(items=None, tag=None), {})
        self.assertFalse(failed)
        self.assertEqual(probed[-1], ["pkg.a", "pkg.b"])
        self.assertIn("2 modules import with the run PYTHONPATH", out)
        self.assertNotIn("(--items", out)

    def test_scoped_probe_ignores_a_module_outside_the_selection(self) -> None:
        failed, out, probed = self.run_environment(
            Namespace(items=["smoke"], tag=None), {"pkg.b": "ImportError: private submodule"}
        )
        self.assertFalse(failed)
        self.assertEqual(probed[-1], ["pkg.a"])
        self.assertIn("1 modules import with the run PYTHONPATH (--items smoke)", out)
        self.assertNotIn("test modules fix", out)

    def test_unscoped_failure_names_the_module_and_the_scope_hint(self) -> None:
        failed, out, probed = self.run_environment(
            Namespace(items=None, tag=None), {"pkg.b": "ImportError: private submodule"}
        )
        self.assertTrue(failed)
        self.assertEqual(probed[-1], ["pkg.a", "pkg.b"])
        self.assertIn("1/2 modules failed to import", out)
        self.assertIn("ImportError: private submodule", out)
        self.assertIn("test modules fix", out)
        self.assertIn("--items <group or test>", out)

    def test_scoped_failure_draws_no_hint(self) -> None:
        failed, out, _ = self.run_environment(
            Namespace(items=["all"], tag=None), {"pkg.b": "ImportError: private submodule"}
        )
        self.assertTrue(failed)
        self.assertIn("1/2 modules failed to import (--items all)", out)
        self.assertNotIn("test modules fix", out)

    def test_selection_without_a_bound_module_warns(self) -> None:
        failed, out, probed = self.run_environment(Namespace(items=["c_test"], tag=None), {})
        self.assertFalse(failed)
        self.assertEqual(probed[-1], [])
        self.assertIn("no module for framework `cocotb` (--items c_test)", out)


class DoctorSelectionErrorTest(unittest.TestCase):
    """A `--items`/`--tag` the catalog cannot resolve is a usage error, not an environment verdict."""

    def test_unknown_item_is_reported_before_any_probe(self) -> None:
        args = Namespace(
            dut="dtp",
            tool="verilator",
            mode="sim",
            framework=None,
            overlay=None,
            items=["nosuch"],
            tag=None,
        )
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(cli, "load_site_layer", return_value=None),
            mock.patch.object(cli, "_doctor_python_environment") as environment,
            mock.patch("shutil.which", return_value="/usr/bin/verilator"),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            rc = cli.cmd_doctor(REPO_ROOT, args)
        self.assertEqual(rc, 2)
        self.assertIn("ERROR: unknown test/group `nosuch`", err.getvalue())
        self.assertNotIn("NOT ready", out.getvalue())
        environment.assert_not_called()


class MinVersionTest(unittest.TestCase):
    FLOOR = {"min_version": "5.036"}

    def test_release_key_orders_verilator_numbering(self) -> None:
        self.assertEqual(cli._release_key("Verilator 5.052 2026-09-05 rev v5.052"), (5, 52))
        self.assertEqual(cli._release_key("Verilator 5.036"), (5, 36))
        self.assertEqual(cli._release_key("SBY v0.69"), (0, 69))
        self.assertIsNone(cli._release_key("unknown"))

    def test_older_release_is_below_the_floor(self) -> None:
        self.assertEqual(
            cli._below_min_version(self.FLOOR, "Verilator 5.020 2024-01-01 rev v5.020"), "5.036"
        )
        self.assertEqual(
            cli._below_min_version(self.FLOOR, "Verilator 4.228 2022-07-24 rev v4.228"), "5.036"
        )

    def test_floor_and_newer_releases_pass(self) -> None:
        for line in (
            "Verilator 5.036 2025-02-01 rev v5.036",
            "Verilator 5.052 2026-09-05 rev v5.052",
            "Verilator 6.001 2027-01-01 rev v6.001",
        ):
            with self.subTest(line=line):
                self.assertEqual(cli._below_min_version(self.FLOOR, line), "")

    def test_tables_without_a_floor_and_unparsable_output_are_not_judged(self) -> None:
        self.assertEqual(cli._below_min_version({}, "Verilator 5.020"), "")
        self.assertEqual(cli._below_min_version({"min_version": 5}, "Verilator 5.020"), "")
        self.assertEqual(cli._below_min_version(self.FLOOR, "unknown"), "")

    def test_version_query_covers_every_registry_tool(self) -> None:
        self.assertTrue(set(load_simulators(REPO_ROOT)).issubset(cli._DOCTOR_VERSION_ARGS))

    def test_absent_binary_reports_unknown_and_unknown_tool_reports_nothing(self) -> None:
        self.assertEqual(cli._tool_version_line("sby", str(self.missing()), {}), "unknown")
        self.assertEqual(cli._tool_version_line("fvtool", "/usr/bin/fvtool", {}), "")

    @staticmethod
    def missing() -> Path:
        with tempfile.TemporaryDirectory() as tmp:
            return Path(tmp) / "sby"


class DoctorToolVersionRowTest(unittest.TestCase):
    """`--doctor --tool verilator` on a host whose Verilator is found: the version row and the verdict."""

    FLOOR = load_simulators(REPO_ROOT)["verilator"]["min_version"]

    def run_doctor(self, version_line: str) -> tuple[int, str]:
        args = Namespace(dut=None, tool="verilator", mode="sim", framework=None, overlay=None)
        out = io.StringIO()
        with (
            mock.patch.object(cli, "load_duts", return_value={}),
            mock.patch.object(cli, "load_site_layer", return_value=None),
            mock.patch.object(cli, "_doctor_python_environment", return_value=False),
            mock.patch.object(cli, "_tool_version_line", return_value=version_line),
            mock.patch(
                "shutil.which",
                side_effect=lambda name, *a, **k: (
                    "/usr/bin/verilator" if name == "verilator" else None
                ),
            ),
            redirect_stdout(out),
        ):
            rc = cli.cmd_doctor(REPO_ROOT, args)
        return rc, out.getvalue()

    def test_release_at_or_above_the_floor_is_available(self) -> None:
        rc, out = self.run_doctor("Verilator 5.052 2026-09-05 rev v5.052")
        self.assertEqual(rc, 0)
        self.assertIn("version: Verilator 5.052 2026-09-05 rev v5.052", out)
        self.assertNotIn("below min_version", out)
        self.assertIn("Result: required tool `verilator` is available", out)

    def test_release_below_the_floor_fails_the_required_tool(self) -> None:
        rc, out = self.run_doctor("Verilator 5.020 2024-01-01 rev v5.020")
        self.assertEqual(rc, 2)
        self.assertIn(f"below min_version {self.FLOOR}", out)
        self.assertIn("Result: required tool `verilator` is too old", out)
        self.assertIn(f"its registry table sets min_version {self.FLOOR}", out)

    def test_unknown_version_is_reported_and_not_judged(self) -> None:
        rc, out = self.run_doctor("unknown")
        self.assertEqual(rc, 0)
        self.assertIn("version: unknown", out)


if __name__ == "__main__":
    unittest.main()
