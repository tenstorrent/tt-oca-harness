# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for the formal launch templates: registry defaults, app-table overrides, optional
groups, the routing of --proof-depth and --formal-arg, template validation, and the dry-run
command line.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

from __future__ import annotations

import copy
import io
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib import stages  # noqa: E402
from runlib.config import (  # noqa: E402
    load_simulators,
    render_formal_argv,
    validate_formal_argv_template,
    validate_native_config_shape,
)
from runlib.models import ConfigError, Dut, TestCatalog, TestEntry  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
DTP_DV_ROOT = REPO_ROOT / "hw/sys/dtp/dv"
RUN_DIR = Path("/runs/unit")


def formal_flow(tool: str, raw: dict | None = None) -> Dut:
    return Dut(
        name="dtp",
        kind="fv",
        description="unit-test formal flow",
        framework="formal",
        visibility="public",
        runnability="contributor",
        license="none",
        root="hw/sys/dtp/dv",
        default_tool=tool,
        tools=[tool],
        path=DTP_DV_ROOT / "dtp_formal_cfg.toml",
        raw=raw or {},
        frameworks=["formal"],
        default_framework="formal",
    )


def sim_cfg_for(tool: str, **tool_cfg) -> dict:
    table = {"cwd": "formal/fpv/sby", "script": "dtp.sby", "args": ["bmc", "cover"]}
    table.update(tool_cfg)
    return {"formal": {"apps": {"fpv": {tool: table}}}}


def catalog() -> TestCatalog:
    return TestCatalog(
        path=None, tests={"dtp_fpv": TestEntry(name="dtp_fpv", module="fpv")}, groups={}
    )


def make_args(**overrides) -> Namespace:
    values = {
        "dry_run": True,
        "quiet": True,
        "verbose": False,
        "timeout": None,
        "proof_depth": None,
        "formal_arg": None,
        "app": None,
        "ui": "plain",
    }
    values.update(overrides)
    return Namespace(**values)


class FormalLaunchBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.simulators = load_simulators(REPO_ROOT)
        cls.licensed_tool = next(
            name
            for name, cfg in sorted(cls.simulators.items())
            if cfg.get("kind") == "formal" and cfg["license_env"]
        )

    def launch(
        self, tool: str, sim_cfg: dict, args: Namespace, simulators: dict | None = None
    ) -> tuple[list[str], Path]:
        ctx = {"run_dir": str(RUN_DIR), "item": "dtp_fpv", "tool": tool}
        with mock.patch.object(stages, "run_subprocess", return_value=0) as run:
            rc = stages.formal_run_stage(
                formal_flow(tool),
                REPO_ROOT,
                sim_cfg,
                catalog(),
                "dtp_fpv",
                args,
                tool,
                simulators if simulators is not None else self.simulators,
                ctx,
                RUN_DIR / "stages/formal/logs/dtp_fpv.log",
                RUN_DIR / "stages/formal/scripts/formal.dtp_fpv.sh",
                RUN_DIR / "stages/formal/env/formal.env",
            )
        self.assertEqual(rc, 0)
        return list(run.call_args.args[0]), run.call_args.kwargs["cwd"]


class SbyTemplateTest(FormalLaunchBase):
    def test_registry_template_launches_from_the_task_file_directory(self) -> None:
        argv, cwd = self.launch("sby", sim_cfg_for("sby"), make_args())
        self.assertEqual(
            argv,
            [
                "sby",
                "-f",
                "--prefix",
                f"{RUN_DIR}/stages/formal/dtp_fpv",
                "dtp.sby",
                "bmc",
                "cover",
            ],
        )
        self.assertEqual(cwd, DTP_DV_ROOT / "formal/fpv/sby")

    def test_formal_args_splice_after_the_tasks(self) -> None:
        argv, _ = self.launch("sby", sim_cfg_for("sby"), make_args(formal_arg=["--sequential"]))
        self.assertEqual(argv[-3:], ["bmc", "cover", "--sequential"])

    def test_proof_depth_is_rejected_because_the_template_carries_none(self) -> None:
        with self.assertRaises(ConfigError) as ctx:
            self.launch("sby", sim_cfg_for("sby"), make_args(proof_depth=20))
        self.assertIn("{proof_depth}", str(ctx.exception))
        self.assertIn("--proof-depth", str(ctx.exception))

    def test_dry_run_prints_the_rendered_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            out = io.StringIO()
            with redirect_stdout(out):
                rc = stages.formal_run_stage(
                    formal_flow("sby"),
                    REPO_ROOT,
                    sim_cfg_for("sby"),
                    catalog(),
                    "dtp_fpv",
                    make_args(quiet=False),
                    "sby",
                    self.simulators,
                    {"run_dir": str(run_dir), "item": "dtp_fpv"},
                    run_dir / "logs/dtp_fpv.log",
                    run_dir / "scripts/formal.dtp_fpv.sh",
                    run_dir / "env/formal.env",
                )
        self.assertEqual(rc, 0)
        self.assertIn(
            f"CMD  : sby -f --prefix {run_dir}/stages/formal/dtp_fpv dtp.sby bmc cover",
            out.getvalue(),
        )


class LicensedTemplateTest(FormalLaunchBase):
    def test_registry_template_keeps_the_generic_shape(self) -> None:
        tool = self.licensed_tool
        binary = self.simulators[tool]["binary"]
        argv, _ = self.launch(tool, sim_cfg_for(tool), make_args(formal_arg=["-x"]))
        self.assertEqual(argv, [binary, "bmc", "cover", "dtp.sby", "-x"])

    def test_app_override_with_an_optional_group(self) -> None:
        tool = self.licensed_tool
        binary = self.simulators[tool]["binary"]
        template = ["{binary}", ["-depth", "{proof_depth}"], "{script}", "{formal_args}"]
        without, _ = self.launch(tool, sim_cfg_for(tool, argv=template), make_args())
        self.assertEqual(without, [binary, "dtp.sby"])
        with_depth, _ = self.launch(
            tool, sim_cfg_for(tool, argv=template), make_args(proof_depth=24)
        )
        self.assertEqual(with_depth, [binary, "-depth", "24", "dtp.sby"])

    def test_formal_arg_is_rejected_without_its_placeholder(self) -> None:
        tool = self.licensed_tool
        with self.assertRaises(ConfigError) as ctx:
            self.launch(
                tool,
                sim_cfg_for(tool, argv=["{binary}", "{script}"]),
                make_args(formal_arg=["-x"]),
            )
        self.assertIn("{formal_args}", str(ctx.exception))


class TemplateSourceTest(FormalLaunchBase):
    def test_script_placeholder_requires_a_script(self) -> None:
        with self.assertRaises(ConfigError) as ctx:
            self.launch("sby", sim_cfg_for("sby", script=""), make_args())
        self.assertIn("{script}", str(ctx.exception))

    def test_missing_template_is_a_config_error(self) -> None:
        simulators = copy.deepcopy(self.simulators)
        del simulators["sby"]["argv"]
        with self.assertRaises(ConfigError) as ctx:
            self.launch("sby", sim_cfg_for("sby"), make_args(), simulators)
        self.assertIn("no launch template", str(ctx.exception))

    def test_cwd_placeholder_renders_the_resolved_directory(self) -> None:
        argv, cwd = self.launch(
            "sby", sim_cfg_for("sby", argv=["{binary}", "{cwd}", "{item}"]), make_args()
        )
        self.assertEqual(argv, ["sby", str(cwd), "dtp_fpv"])


class TemplateValidationTest(unittest.TestCase):
    def reject(self, template: object, fragment: str) -> None:
        with self.assertRaises(ConfigError) as ctx:
            validate_formal_argv_template(template, "unit")
        self.assertIn(fragment, str(ctx.exception))

    def test_registry_formal_tools_carry_valid_templates(self) -> None:
        simulators = load_simulators(REPO_ROOT)
        formal = [name for name, cfg in simulators.items() if cfg.get("kind") == "formal"]
        self.assertIn("sby", formal)
        for name in formal:
            validate_formal_argv_template(simulators[name]["argv"], name)

    def test_unknown_placeholder(self) -> None:
        self.reject(["{binary}", "{depth}"], "{depth}")

    def test_list_placeholder_must_stand_alone(self) -> None:
        self.reject(["{binary}", "--tasks={args}"], "element on its own")

    def test_optional_placeholder_needs_a_group(self) -> None:
        self.reject(["{binary}", "--depth={proof_depth}"], "optional group")

    def test_group_must_reference_an_optional_placeholder(self) -> None:
        self.reject(["{binary}", ["-quiet"]], "optional placeholder")

    def test_group_cannot_hold_a_list_placeholder(self) -> None:
        self.reject(["{binary}", ["{args}", "{proof_depth}"]], "inside an optional group")

    def test_nested_group_and_non_string_elements(self) -> None:
        self.reject(["{binary}", [["-depth", "{proof_depth}"]]], "non-empty list of strings")
        self.reject(["{binary}", 3], "strings or optional groups")

    def test_empty_template(self) -> None:
        self.reject([], "non-empty")

    def test_render_drops_a_group_without_a_value(self) -> None:
        template = validate_formal_argv_template(
            ["{binary}", ["-depth", "{proof_depth}"], "{args}"], "unit"
        )
        argv = render_formal_argv(
            template,
            scalars={"binary": "tool"},
            lists={"args": ["a", "b"]},
            optional={"proof_depth": None},
        )
        self.assertEqual(argv, ["tool", "a", "b"])


class FormalConfigShapeTest(unittest.TestCase):
    def test_app_template_placeholders_pass_config_validation(self) -> None:
        raw = sim_cfg_for("sby", argv=["{binary}", ["-d", "{proof_depth}"], "{script}", "{args}"])
        validate_native_config_shape(formal_flow("sby", raw), REPO_ROOT)

    def test_bad_app_template_fails_config_validation(self) -> None:
        raw = sim_cfg_for("sby", argv=["{binary}", "{proof_depth}"])
        with self.assertRaises(ConfigError) as ctx:
            validate_native_config_shape(formal_flow("sby", raw), REPO_ROOT)
        self.assertIn("[formal.apps.fpv.sby].argv", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
