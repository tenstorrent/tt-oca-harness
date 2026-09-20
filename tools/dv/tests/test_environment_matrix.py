# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The supported-environment matrix, held as one statement across the files that pin it.

The Python range, the locked DV stack, the hosted toolchain pins, the tool registry, and the
doctor's own checks each state part of the contributor environment; these tests fail when two
of them disagree. Some of the files are shared with the register and lint flows
(`pyproject.toml`, `uv.lock`, `.python-version`, `lint.yml`), so a failure here after a change
to one of them means the matrix moved and the runner guide's Supported environments section
has to follow.

Run from the repository root, inside the locked `dv` group (the floor test reads cocotb's own
package data):

    uv run --locked --group dv python -m unittest discover tools/dv/tests
"""

from __future__ import annotations

import re
import sys
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib import cli  # noqa: E402
from runlib.config import load_simulators, validate_simulator_registry  # noqa: E402
from runlib.models import ConfigError  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
ROOT_PROJECT = REPO_ROOT / "pyproject.toml"
DV_PROJECT = REPO_ROOT / "hw/common/dv/pyproject.toml"
LOCKFILE = REPO_ROOT / "uv.lock"
PYTHON_VERSION_FILE = REPO_ROOT / ".python-version"
DV_RUN_ACTION = REPO_ROOT / ".github/actions/dv-run/action.yml"
DASHBOARD_WORKFLOW = REPO_ROOT / ".github/workflows/dashboard.yml"
LINT_WORKFLOW = REPO_ROOT / ".github/workflows/lint.yml"
HOSTED_WORKFLOWS = (
    REPO_ROOT / ".github/workflows/sim.yml",
    REPO_ROOT / ".github/workflows/regress.yml",
)
# A matrix row runs on the hosted image, or on the label the repository variable names with the
# hosted image as its fallback.
HOSTED_RUNNER_RE = re.compile(
    r"^(ubuntu-latest|\$\{\{ vars\.DV_LARGE_RUNNER \|\| 'ubuntu-latest' \}\})$"
)

# The two tools a bare clone runs with no license: the open simulator and the open formal backend.
LICENSE_FREE_TOOLS = {"verilator", "sby"}
REGISTRY_TOOLS = {"verilator", "vcs", "xcelium", "sby"}


def version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", text))


def python_range(specifier: str) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """`>=A,<B` as two tuples, whichever way the clauses are ordered or spaced."""
    lower = re.search(r">=\s*([\d.]+)", specifier)
    upper = re.search(r"<\s*([\d.]+)", specifier)
    assert lower and upper, specifier
    return version_tuple(lower.group(1)), version_tuple(upper.group(1))


def satisfies(version: str, specifier: str) -> bool:
    have = version_tuple(version)
    for clause in specifier.split(","):
        match = re.fullmatch(r"\s*(>=|<=|==|!=|<|>)\s*([\w.]+)\s*", clause)
        assert match, clause
        op, target = match.group(1), version_tuple(match.group(2))
        ok = {
            ">=": have >= target,
            "<=": have <= target,
            "==": have == target,
            "!=": have != target,
            "<": have < target,
            ">": have > target,
        }[op]
        if not ok:
            return False
    return True


def action_input_default(text: str, name: str) -> str:
    match = re.search(rf"^  {re.escape(name)}:\n(?:    .*\n)*?    default: '([^']*)'", text, re.M)
    assert match, name
    return match.group(1)


def python_versions_in(text: str) -> list[str]:
    return re.findall(r"python-version: ['\"]?([\d.]+)['\"]?", text)


class PythonRangeTest(unittest.TestCase):
    """The supported interpreter range is one statement in the runner, both projects, and the lock."""

    def setUp(self) -> None:
        self.runner_range = (cli.SUPPORTED_PYTHON_MIN, cli.SUPPORTED_PYTHON_MAX_EXCLUSIVE)

    def test_root_project_matches_the_runner(self) -> None:
        project = tomllib.loads(ROOT_PROJECT.read_text())["project"]
        self.assertEqual(python_range(project["requires-python"]), self.runner_range)

    def test_dv_package_matches_the_runner(self) -> None:
        project = tomllib.loads(DV_PROJECT.read_text())["project"]
        self.assertEqual(python_range(project["requires-python"]), self.runner_range)

    def test_lockfile_matches_the_runner(self) -> None:
        lock = tomllib.loads(LOCKFILE.read_text())
        self.assertEqual(python_range(lock["requires-python"]), self.runner_range)

    def test_pinned_interpreter_is_inside_the_range(self) -> None:
        pinned = version_tuple(PYTHON_VERSION_FILE.read_text().strip())
        self.assertGreaterEqual(pinned, cli.SUPPORTED_PYTHON_MIN)
        self.assertLess(pinned, cli.SUPPORTED_PYTHON_MAX_EXCLUSIVE)

    def test_hosted_jobs_select_the_pinned_interpreter(self) -> None:
        pinned = PYTHON_VERSION_FILE.read_text().strip()
        self.assertEqual(action_input_default(DV_RUN_ACTION.read_text(), "python-version"), pinned)
        self.assertEqual(python_versions_in(DASHBOARD_WORKFLOW.read_text()), [pinned])
        lint = LINT_WORKFLOW.read_text()
        job = re.search(r"^  dv-unit-tests:\n(.*?)(?=^  [a-z-]+:\n)", lint, re.M | re.S)
        assert job, "dv-unit-tests job"
        self.assertEqual(python_versions_in(job.group(1)), [pinned])


class LockedDvStackTest(unittest.TestCase):
    """The lockfile's `ocah-dv` member is the DV stack, and the doctor reports each of its parts."""

    @classmethod
    def setUpClass(cls) -> None:
        lock = tomllib.loads(LOCKFILE.read_text())
        cls.packages = {pkg["name"]: pkg for pkg in lock["package"]}
        cls.dv_package = cls.packages["ocah-dv"]

    def test_dv_member_is_the_in_tree_package(self) -> None:
        self.assertEqual(self.dv_package["source"], {"editable": "hw/common/dv"})

    def test_doctor_reports_every_locked_dependency(self) -> None:
        locked = {dep["name"] for dep in self.dv_package["dependencies"]}
        self.assertEqual(locked, set(cli.DOCTOR_DISTRIBUTIONS))

    def test_dv_project_declares_the_same_dependencies(self) -> None:
        project = tomllib.loads(DV_PROJECT.read_text())["project"]
        declared = {re.match(r"[A-Za-z0-9_.-]+", dep).group(0) for dep in project["dependencies"]}
        self.assertEqual(declared, set(cli.DOCTOR_DISTRIBUTIONS))

    def test_locked_versions_satisfy_the_declared_specifiers(self) -> None:
        for dist in self.dv_package["metadata"]["requires-dist"]:
            with self.subTest(dist=dist["name"]):
                locked = self.packages[dist["name"]]["version"]
                self.assertTrue(
                    satisfies(locked, dist["specifier"]),
                    f"{dist['name']} {locked} violates {dist['specifier']}",
                )


class RegistryFloorTest(unittest.TestCase):
    """The registry's Verilator `min_version` is cocotb's documented floor, and the hosted tag meets it.

    cocotb states the floor as `VLT_MIN` in its Makefile flow; the Python runner the launcher
    uses checks no floor, so the doctor's comparison against the registry value is the check.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.verilator = load_simulators(REPO_ROOT)["verilator"]

    @staticmethod
    def cocotb_floor() -> str:
        from cocotb_tools.config import makefiles_dir

        makefile = Path(makefiles_dir, "simulators", "Makefile.verilator")
        match = re.search(r"^VLT_MIN := (\S+)$", makefile.read_text(), re.M)
        assert match, f"{makefile} names no VLT_MIN"
        return match.group(1)

    def test_registry_floor_is_cocotb_s(self) -> None:
        self.assertEqual(self.verilator["min_version"], self.cocotb_floor())

    def test_hosted_tag_is_a_release_at_or_above_the_floor(self) -> None:
        tag = action_input_default(DV_RUN_ACTION.read_text(), "verilator-version")
        self.assertRegex(tag, r"^v\d+\.\d{3}$")
        self.assertGreaterEqual(version_tuple(tag), version_tuple(self.verilator["min_version"]))
        self.assertEqual(cli._below_min_version(self.verilator, f"Verilator {tag[1:]}"), "")

    def test_min_version_must_be_a_dotted_release(self) -> None:
        for bad in ("5", 5, "v5.036", "5.036 or newer"):
            with self.subTest(value=bad), self.assertRaises(ConfigError):
                validate_simulator_registry(
                    {"verilator": {**self.verilator, "min_version": bad}}, "unit"
                )


class HostedMatrixTest(unittest.TestCase):
    """Hosted CI is Verilator on the GitHub-hosted image, or on the larger label the repository
    variable names, through the composite action alone."""

    def test_action_runs_verilator_by_default_and_selects_no_framework(self) -> None:
        action = DV_RUN_ACTION.read_text()
        self.assertEqual(action_input_default(action, "tool"), "verilator")
        self.assertNotRegex(action, r"^  framework:", re.M)

    def test_every_hosted_row_passes_verilator(self) -> None:
        for workflow in HOSTED_WORKFLOWS:
            with self.subTest(workflow=workflow.name):
                tools = re.findall(r"^\s+tool: (\S+)$", workflow.read_text(), re.M)
                self.assertTrue(tools)
                self.assertEqual(set(tools), {"verilator"})

    def test_every_hosted_row_defaults_to_the_hosted_image(self) -> None:
        for workflow in HOSTED_WORKFLOWS:
            with self.subTest(workflow=workflow.name):
                labels = re.findall(r"^\s+runner: (.+)$", workflow.read_text(), re.M)
                self.assertTrue(labels)
                for label in labels:
                    self.assertRegex(label, HOSTED_RUNNER_RE)


class ToolRegistryBoundaryTest(unittest.TestCase):
    """The open tree names one license-free simulator and one license-free formal backend."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.simulators = load_simulators(REPO_ROOT)

    def test_registry_names_the_documented_tools(self) -> None:
        self.assertEqual(set(self.simulators), REGISTRY_TOOLS)

    def test_license_free_tools_are_the_open_pair(self) -> None:
        free = {name for name, cfg in self.simulators.items() if not cfg["license_env"]}
        self.assertEqual(free, LICENSE_FREE_TOOLS)

    def test_every_licensed_tool_names_its_license_variables(self) -> None:
        for name in REGISTRY_TOOLS - LICENSE_FREE_TOOLS:
            with self.subTest(tool=name):
                self.assertTrue(self.simulators[name]["license_env"])


if __name__ == "__main__":
    unittest.main()
