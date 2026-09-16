# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for the formal stage: app resolution (item module, --app, default_tool
fallback, cwd), the launch templates (registry defaults, app-table overrides, optional groups,
the routing of --proof-depth and --formal-arg, template validation), and the dry-run stage.

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

from runlib import cli, site, stages  # noqa: E402
from runlib.config import (  # noqa: E402
    load_simulators,
    render_formal_argv,
    validate_formal_argv_template,
    validate_native_config_shape,
)
from runlib.duts import resolve_dut  # noqa: E402
from runlib.logparse import validate_parser_registry  # noqa: E402
from runlib.models import ConfigError, Dut, TestCatalog, TestEntry  # noqa: E402
from runlib.site import load_site_layer, merged_simulators  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
DTP_DV_ROOT = REPO_ROOT / "hw/sys/dtp/dv"

# A licensed formal backend reaches the runner as a complete tool table in the site layer; this
# one carries the generic launch template a Tcl-driven tool uses.
LICENSED_SITE = """
schema_version = 1
[simulators.fvtool]
kind = "formal"
binary = "fvtool"
frameworks = ["formal"]
license_env = ["FVTOOL_LICENSE_FILE"]
supports_waves = []
supports_cov = ["formal"]
default_waves = ""
argv = ["{binary}", "{args}", "{script}", "{formal_args}"]
"""


def registry_with_site_backend() -> dict:
    """The checked-in registry with the site-added licensed backend `fvtool` merged in."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "site.toml"
        path.write_text(LICENSED_SITE)
        layer = load_site_layer(REPO_ROOT, {site.SITE_ENV: str(path)})
    assert layer is not None
    return merged_simulators(load_simulators(REPO_ROOT), layer)


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
        cls.simulators = registry_with_site_backend()
        cls.licensed_tool = "fvtool"

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


class FormalAppResolutionTest(unittest.TestCase):
    """`resolve_formal_app`: which `[formal.apps.<app>.<tool>]` table an item launches."""

    def resolve(self, raw: dict, item: str = "dtp_fpv", tool: str = "sby", **args):
        flow = formal_flow(tool, raw)
        return stages.resolve_formal_app(
            flow, REPO_ROOT, raw, catalog(), item, make_args(**args), tool
        )

    def test_item_module_names_the_app(self) -> None:
        app = self.resolve(sim_cfg_for("sby"))
        self.assertEqual((app.name, app.tool), ("fpv", "sby"))
        self.assertEqual(app.table["script"], "dtp.sby")
        self.assertEqual(app.cwd, DTP_DV_ROOT / "formal/fpv/sby")

    def test_app_flag_overrides_the_module(self) -> None:
        raw = {
            "formal": {
                "apps": {"fpv": {"sby": {"script": "a.sby"}}, "conn": {"sby": {"script": "c.sby"}}}
            }
        }
        self.assertEqual(self.resolve(raw, app="conn").table["script"], "c.sby")

    def test_item_without_a_catalog_entry_uses_its_own_name(self) -> None:
        raw = {"formal": {"apps": {"solo": {"sby": {"script": "s.sby"}}}}}
        self.assertEqual(self.resolve(raw, item="solo").name, "solo")

    def test_default_tool_fallback_when_the_selected_tool_has_no_table(self) -> None:
        raw = {"formal": {"apps": {"fpv": {"default_tool": "sby", "sby": {"script": "d.sby"}}}}}
        app = self.resolve(raw, tool="fvtool")
        self.assertEqual((app.tool, app.table["script"]), ("sby", "d.sby"))

    def test_missing_app_and_missing_backend_are_config_errors(self) -> None:
        with self.assertRaises(ConfigError) as ctx:
            self.resolve({"formal": {"apps": {}}})
        self.assertIn("formal app `fpv` is not defined", str(ctx.exception))
        raw = {"formal": {"apps": {"fpv": {"sby": {"script": "a.sby"}}}}}
        with self.assertRaises(ConfigError) as ctx:
            self.resolve(raw, tool="fvtool")
        self.assertIn("has no `fvtool` backend", str(ctx.exception))

    def test_cwd_resolves_repo_relative_then_dut_relative(self) -> None:
        repo_relative = self.resolve(sim_cfg_for("sby", cwd="hw/sys/dtp/dv/formal/fpv/sby"))
        self.assertEqual(repo_relative.cwd, REPO_ROOT / "hw/sys/dtp/dv/formal/fpv/sby")
        dut_relative = self.resolve(sim_cfg_for("sby", cwd="formal/fpv/sby"))
        self.assertEqual(dut_relative.cwd, DTP_DV_ROOT / "formal/fpv/sby")
        absent = self.resolve(sim_cfg_for("sby", cwd="no/such/dir"))
        self.assertEqual(absent.cwd, DTP_DV_ROOT / "no/such/dir")


class FormalDryRunStageTest(unittest.TestCase):
    """`run_stage` on a formal item in dry-run: renders the command, grades nothing."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.simulators = load_simulators(REPO_ROOT)
        cls.policies = validate_parser_registry(REPO_ROOT)

    def test_dry_run_prints_the_command_and_skips_grading(self) -> None:
        raw = {"native": {"stages": {"formal": {"kind": "formal_run"}}}, **sim_cfg_for("sby")}
        args = make_args(quiet=False, seed=None, sim_jobs=1, cov=False, waves=None)
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(out):
            result = stages.run_stage(
                formal_flow("sby", raw),
                REPO_ROOT,
                raw,
                catalog(),
                "formal",
                "dtp_fpv",
                args,
                "sby",
                Path(tmp),
                self.simulators,
                self.policies,
            )
            cmd = next(line for line in out.getvalue().splitlines() if line.startswith("CMD  :"))
            self.assertEqual(
                cmd,
                f"CMD  : sby -f --prefix {tmp}/stages/formal/dtp_fpv dtp.sby bmc cover",
            )
        self.assertEqual((result.stage, result.item, result.status), ("formal", "dtp_fpv", "PASS"))
        self.assertIsNone(result.formal)
        self.assertIsNone(result.parser)


class FormalStageSelectionTest(unittest.TestCase):
    """`selected_stages` on a formal flow: the filelist stage precedes the proof when declared."""

    def stages(self, raw: dict, **overrides) -> list[str]:
        values = {
            "cov": False,
            "stage": None,
            "build_only": False,
            "run_only": False,
            "regress": False,
        }
        values.update(overrides)
        return cli.selected_stages(formal_flow("sby", raw), Namespace(**values))

    def test_declared_filelist_stage_runs_before_the_proof(self) -> None:
        raw = {
            "native": {"stages": {"flist": {"kind": "filelist"}, "formal": {"kind": "formal_run"}}}
        }
        self.assertEqual(self.stages(raw), ["flist", "formal"])
        self.assertEqual(self.stages(raw, build_only=True), ["flist"])
        self.assertEqual(self.stages(raw, run_only=True), ["formal"])

    def test_profile_without_a_filelist_stage_runs_the_proof_alone(self) -> None:
        raw = {"native": {"stages": {"formal": {"kind": "formal_run"}}}}
        self.assertEqual(self.stages(raw), ["formal"])

    def test_checked_in_dtp_formal_config_plans_both_stages(self) -> None:
        flow = resolve_dut(REPO_ROOT, "dtp", mode="formal")
        self.assertEqual(flow.kind, "fv")
        self.assertEqual(
            cli.selected_stages(
                flow,
                Namespace(cov=False, stage=None, build_only=False, run_only=False, regress=False),
            ),
            ["flist", "formal"],
        )


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
