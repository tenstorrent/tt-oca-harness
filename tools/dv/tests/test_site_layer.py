# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for the site-local override layer: file discovery, validation, the merge over the
registries, tool launch resolution (binary, launcher, setup_hook, extra_env), and the --doctor,
run-path, DUT-resolution, and result.json views of it.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile
import textwrap
import unittest
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import test_coverage_closure as closure  # noqa: E402
from runlib import cli, site, stages  # noqa: E402
from runlib.config import load_executors, load_simulators  # noqa: E402
from runlib.duts import resolve_dut  # noqa: E402
from runlib.models import ConfigError, Dut, TestCatalog, TestEntry  # noqa: E402
from runlib.results import result_payload  # noqa: E402
from runlib.site import (  # noqa: E402
    SiteLayer,
    ToolLaunch,
    launch_argv,
    launch_env,
    load_site_layer,
    locate_tool,
    merged_executors,
    merged_simulators,
    site_layer_path,
    site_summary,
    tool_launch,
    tool_source,
    validate_site_duts,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = REPO_ROOT / "hw" / "common" / "dv" / "configs" / "site.local.example.toml"
LAUNCHER = ["podman", "exec", "-i", "eda"]
LAUNCHER_TOML = "[" + ", ".join(f'"{tok}"' for tok in LAUNCHER) + "]"


def which_from(found: dict[str, str]):
    """A `shutil.which` stand-in that answers from `found` whatever PATH it is asked to search."""

    def which(executable: str, mode: int = 0, path: str | None = None) -> str | None:
        return found.get(executable)

    return which


class SiteCase(unittest.TestCase):
    """A temp directory per test, a site file writer, and a clean setup_hook cache."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        site.reset_setup_hook_cache()

    def tearDown(self) -> None:
        self._tmp.cleanup()
        site.reset_setup_hook_cache()

    def write(self, name: str, text: str) -> Path:
        path = self.tmp / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text), encoding="utf-8")
        return path

    def hook(self, name: str, body: str) -> Path:
        return self.write(name, body)

    def load(self, text: str, root: Path = REPO_ROOT) -> SiteLayer:
        path = self.write("site.toml", text)
        layer = load_site_layer(root, {site.SITE_ENV: str(path)})
        assert layer is not None
        return layer

    def merged(self, text: str) -> dict:
        return merged_simulators(load_simulators(REPO_ROOT), self.load(text))


class SiteFileDiscoveryTest(SiteCase):
    def test_no_file_and_no_variable_means_no_layer(self) -> None:
        # A companion checkout beside the configs changes nothing.
        (self.tmp / "companion").mkdir()
        (self.tmp / "hw" / "common" / "dv" / "configs").mkdir(parents=True)
        self.assertIsNone(site_layer_path(self.tmp, {}))
        self.assertIsNone(load_site_layer(self.tmp, {}))

    def test_default_file_beside_the_registries_activates(self) -> None:
        default = self.write("hw/common/dv/configs/site.local.toml", "schema_version = 1\n")
        self.assertEqual(site_layer_path(self.tmp, {}), default)
        layer = load_site_layer(self.tmp, {})
        assert layer is not None
        self.assertEqual(layer.label, "hw/common/dv/configs/site.local.toml")

    def test_variable_wins_over_the_default_file(self) -> None:
        self.write("hw/common/dv/configs/site.local.toml", "schema_version = 1\n")
        named = self.write("elsewhere/eda.toml", "schema_version = 1\n")
        self.assertEqual(site_layer_path(self.tmp, {site.SITE_ENV: str(named)}), named.resolve())

    def test_variable_naming_a_missing_file_is_an_error(self) -> None:
        with self.assertRaises(ConfigError) as ctx:
            site_layer_path(self.tmp, {site.SITE_ENV: str(self.tmp / "nope.toml")})
        self.assertIn("OCAH_DV_SITE", str(ctx.exception))

    def test_default_file_is_git_ignored(self) -> None:
        rules = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("/hw/common/dv/configs/site.local.toml", rules)


class SiteFileValidationTest(SiteCase):
    def rejects(self, text: str, *needles: str) -> None:
        with self.assertRaises(ConfigError) as ctx:
            self.merged(text)
        for needle in needles:
            self.assertIn(needle, str(ctx.exception))

    def test_unknown_top_level_table(self) -> None:
        self.rejects("[frobnicate]\nx = 1\n", "unsupported key(s): frobnicate")

    def test_unsupported_schema_version(self) -> None:
        self.rejects("schema_version = 2\n", "schema_version must be 1")

    def test_unknown_key_on_a_checked_in_tool(self) -> None:
        self.rejects(
            '[simulators.verilator]\nframeworks = ["cocotb"]\n',
            "[simulators.verilator]",
            "unsupported key(s): frameworks",
        )

    def test_launcher_shape(self) -> None:
        self.rejects('[simulators.vcs]\nlauncher = "docker"\n', "launcher")
        self.rejects("[simulators.vcs]\nlauncher = []\n", "non-empty list")

    def test_binary_shape(self) -> None:
        self.rejects('[simulators.vcs]\nbinary = ""\n', "binary must be a non-empty string")

    def test_extra_env_names_and_values(self) -> None:
        self.rejects('[simulators.vcs]\nextra_env = { "1BAD" = "x" }\n', "1BAD")
        self.rejects("[simulators.vcs]\nextra_env = { GOOD = 1 }\n", "GOOD", "string")

    def test_setup_hook_must_exist(self) -> None:
        self.rejects('[simulators.vcs]\nsetup_hook = "missing.env"\n', "does not exist")

    def test_setup_hook_resolves_against_the_site_file(self) -> None:
        self.hook("env/vcs.env", "export VCS_HOME=/opt/vcs\n")
        merged = self.merged('[simulators.vcs]\nsetup_hook = "env/vcs.env"\n')
        self.assertEqual(merged["vcs"]["setup_hook"], str((self.tmp / "env" / "vcs.env").resolve()))

    def test_argv_is_for_formal_tools_only(self) -> None:
        self.rejects(
            '[simulators.verilator]\nargv = ["{binary}"]\n', "argv is a formal launch template"
        )

    def test_argv_is_validated_as_a_template(self) -> None:
        self.rejects('[simulators.sby]\nargv = ["{binary}", "{nope}"]\n', "nope")

    def test_dut_entry_keys_and_target(self) -> None:
        self.rejects('[duts.dtp]\nroot = "x"\n', "unsupported key(s): root")
        self.rejects(
            "[duts.dtp]\n", "[duts.dtp] sets none of: exclude_files, formal_cfg, sim_cfg, tools"
        )
        self.rejects("[duts.dtp]\nformal_cfg = 1\n", "formal_cfg must be a non-empty path")
        self.rejects('[duts.dtp]\nsim_cfg = ""\n', "sim_cfg must be a non-empty path")
        self.rejects('[duts.dtp]\ntools = "vcs"\n', "tools", "must be a list of strings")
        self.rejects("[duts.dtp]\ntools = []\n", "tools must be a non-empty list of tool names")
        self.rejects(
            '[duts.dtp]\nexclude_files = "x.sv"\n', "exclude_files", "must be a list of strings"
        )
        self.rejects(
            "[duts.dtp]\nexclude_files = []\n",
            "exclude_files must be a non-empty list of filelist patterns",
        )

    def test_site_exclude_files_append_to_the_build_drops(self) -> None:
        layer = self.load('[duts.dtp]\nexclude_files = ["site_vendor_only.sv", "meta/models/x"]\n')
        self.assertEqual(layer.dut_exclude_files(["dtp"]), ["site_vendor_only.sv", "meta/models/x"])
        flow = resolve_dut(REPO_ROOT, "dtp", site=layer)
        excludes = flow.raw.get("build", {}).get("exclude_files", [])
        self.assertIn("site_vendor_only.sv", excludes)
        self.assertIn("meta/models/x", excludes)

    def test_absent_sim_cfg_loads_and_fails_only_when_selected(self) -> None:
        layer = self.load('[duts.dtp]\nsim_cfg = "missing_sim_cfg.toml"\n')
        self.assertEqual(layer.sim_cfg(["dtp"]), "missing_sim_cfg.toml")
        self.assertIsNone(layer.formal_cfg(["dtp"]))
        resolve_dut(REPO_ROOT, "dtp", mode="formal", site=layer)
        with self.assertRaises(ConfigError) as ctx:
            resolve_dut(REPO_ROOT, "dtp", site=layer)
        self.assertIn("sim config not found", str(ctx.exception))
        self.assertIn("named by the site layer", str(ctx.exception))

    def test_absent_formal_cfg_loads_and_fails_only_when_selected(self) -> None:
        layer = self.load('[duts.dtp]\nformal_cfg = "missing_formal_cfg.toml"\n')
        self.assertEqual(layer.formal_cfg(["dtp"]), "missing_formal_cfg.toml")
        resolve_dut(REPO_ROOT, "dtp", site=layer)
        with self.assertRaises(ConfigError) as ctx:
            resolve_dut(REPO_ROOT, "dtp", mode="formal", site=layer)
        self.assertIn("formal config not found", str(ctx.exception))
        self.assertIn("named by the site layer", str(ctx.exception))

    def test_dut_entry_must_name_a_selectable_dut(self) -> None:
        cfg = self.write("x_formal_cfg.toml", "name = 'x'\n")
        layer = self.load(f'[duts.no_such_dut]\nformal_cfg = "{cfg}"\n')
        with self.assertRaises(ConfigError) as ctx:
            validate_site_duts(layer, ["dtp", "smu"])
        self.assertIn("no_such_dut", str(ctx.exception))
        validate_site_duts(layer, ["dtp", "no_such_dut"])

    def test_checked_in_registry_rejects_deployment_keys(self) -> None:
        registry = (REPO_ROOT / "hw/common/dv/configs/simulators.toml").read_text()
        marker = '[sby]\nkind = "formal"'
        self.assertIn(marker, registry)
        self.write(
            "hw/common/dv/configs/simulators.toml",
            registry.replace(marker, '[sby]\nlauncher = ["podman"]\nkind = "formal"'),
        )
        with self.assertRaises(ConfigError) as ctx:
            load_simulators(self.tmp)
        self.assertIn("launcher", str(ctx.exception))
        self.assertIn("site layer", str(ctx.exception))


class MergeTest(SiteCase):
    def test_override_keys_replace_the_checked_in_values_whole(self) -> None:
        base = load_simulators(REPO_ROOT)
        merged = self.merged(
            f"""
            [simulators.vcs]
            binary = "vcs-2026"
            license_env = ["SIMTOOL_LICENSE_FILE"]
            launcher = {LAUNCHER_TOML}
            extra_env = {{ VCS_HOME = "/opt/vcs" }}
            """
        )
        vcs = merged["vcs"]
        self.assertEqual(vcs["binary"], "vcs-2026")
        self.assertEqual(vcs["license_env"], ["SIMTOOL_LICENSE_FILE"])
        self.assertEqual(vcs["launcher"], LAUNCHER)
        self.assertEqual(vcs["extra_env"], {"VCS_HOME": "/opt/vcs"})
        self.assertEqual(vcs["frameworks"], base["vcs"]["frameworks"])
        self.assertEqual(vcs["coverage_defaults"], base["vcs"]["coverage_defaults"])
        # The checked-in registry is not mutated.
        self.assertEqual(base["vcs"]["binary"], "vcs")
        self.assertNotIn("launcher", base["vcs"])
        self.assertEqual(merged["verilator"], base["verilator"])

    def test_added_tool_table_passes_the_registry_schema(self) -> None:
        merged = self.merged(
            """
            [simulators.fvtool]
            kind = "formal"
            binary = "fvtool"
            frameworks = ["formal"]
            license_env = ["FV_LICENSE_FILE"]
            supports_waves = []
            supports_cov = ["formal"]
            default_waves = ""
            argv = ["{binary}", "-batch", "{script}", "{args}", "{formal_args}"]
            """
        )
        self.assertEqual(merged["fvtool"]["kind"], "formal")
        self.assertIn("sby", merged)

    def test_added_tool_table_is_validated(self) -> None:
        for body, needle in (
            ('kind = "formal"\nbinary = "x"\n', "frameworks"),
            ('kind = "formal"\nframeworks = ["formal"]\n', "license_env"),
            ('kind = "formal"\nframeworks = ["formal"]\nlicense_env = []\n', "argv"),
            ('kind = "other"\nframeworks = ["formal"]\nlicense_env = []\n', "kind"),
        ):
            with self.assertRaises(ConfigError) as ctx:
                self.merged("[simulators.fvtool]\n" + body)
            self.assertIn(needle, str(ctx.exception))
            self.assertIn("site layer", str(ctx.exception))

    def test_executor_overrides_and_additions(self) -> None:
        base = load_executors(REPO_ROOT)
        layer = self.load(
            """
            [executors.grid]
            kind = "cluster"
            binary = "qsub"
            submit_argv = ["qsub", "-q", "{queue}"]
            wait_mode = "poll"
            """
        )
        merged = merged_executors(base, layer)
        self.assertEqual(merged["grid"]["binary"], "qsub")
        self.assertEqual(merged["local"], base["local"])
        self.assertEqual(merged["lsf"], base["lsf"])
        with self.assertRaises(ConfigError) as ctx:
            merged_executors(base, self.load('[executors.lsf]\nkind = "local"\n'))
        self.assertIn("kind", str(ctx.exception))
        with self.assertRaises(ConfigError) as ctx:
            merged_executors(base, self.load('[executors.local]\nbinary = "x"\n'))
        self.assertIn("binary", str(ctx.exception))

    def test_tool_source_names_the_supplying_files(self) -> None:
        layer = self.load(
            f'[simulators.vcs]\nlauncher = {LAUNCHER_TOML}\nbinary = "vcs-2026"\n'
            '[simulators.fvtool]\nkind = "formal"\n'
        )
        self.assertEqual(tool_source(None, "vcs", True), "simulators.toml")
        self.assertEqual(tool_source(layer, "verilator", True), "simulators.toml")
        self.assertEqual(
            tool_source(layer, "vcs", True), f"simulators.toml + {layer.label} (binary, launcher)"
        )
        self.assertEqual(tool_source(layer, "fvtool", False), f"{layer.label} (added)")

    def test_site_summary_lists_every_change(self) -> None:
        cfg = self.write("dtp_formal_cfg.toml", "name = 'dtp'\n")
        layer = self.load(
            f"""
            [simulators.vcs]
            binary = "vcs-2026"
            [simulators.fvtool]
            kind = "formal"
            [duts.dtp]
            formal_cfg = "{cfg}"
            [duts.smc]
            sim_cfg = "smc_sim_cfg.toml"
            tools = ["vcs"]
            """
        )
        summary = site_summary(layer, {"vcs", "verilator"})
        self.assertIn(f"site={layer.label}", summary)
        self.assertIn("vcs(binary)", summary)
        self.assertIn("fvtool(added)", summary)
        self.assertIn("dtp(formal_cfg)", summary)
        self.assertIn("smc(sim_cfg, tools)", summary)


class ToolLaunchTest(SiteCase):
    def test_launch_from_a_merged_registry(self) -> None:
        hook = self.hook("vcs.env", "export VCS_HOME=/opt/vcs\n")
        merged = self.merged(
            f"""
            [simulators.vcs]
            binary = "vcs-2026"
            launcher = {LAUNCHER_TOML}
            extra_env = {{ VCS_HOME = "/opt/vcs" }}
            setup_hook = "{hook}"
            """
        )
        launch = tool_launch(merged, "vcs")
        self.assertEqual(launch.binary, "vcs-2026")
        self.assertEqual(launch.launcher, tuple(LAUNCHER))
        self.assertEqual(launch.executable, "podman")
        self.assertEqual(dict(launch.extra_env), {"VCS_HOME": "/opt/vcs"})
        self.assertEqual(launch.setup_hook, hook.resolve())
        self.assertEqual(
            launch_argv(launch, ["vcs-2026", "-full64"]), [*LAUNCHER, "vcs-2026", "-full64"]
        )
        bare = tool_launch(merged, "verilator")
        self.assertEqual((bare.binary, bare.launcher, bare.setup_hook), ("verilator", (), None))
        self.assertEqual(bare.executable, "verilator")
        self.assertEqual(tool_launch({}, "ghost").binary, "ghost")

    def test_locate_tool_probes_the_launcher_head(self) -> None:
        launch = ToolLaunch(tool="vcs", binary="vcs-2026", launcher=tuple(LAUNCHER))
        asked: list[str] = []

        def which(executable: str, mode: int = 0, path: str | None = None) -> str | None:
            asked.append(executable)
            return f"/usr/bin/{executable}"

        with mock.patch("shutil.which", side_effect=which):
            self.assertEqual(locate_tool(launch, {"PATH": "/usr/bin"}), "/usr/bin/podman")
            self.assertEqual(locate_tool(ToolLaunch(tool="sby", binary="sby"), {}), "/usr/bin/sby")
        self.assertEqual(asked, ["podman", "sby"])

    def test_launch_env_without_site_exports_is_the_stage_env(self) -> None:
        env = {"PATH": "/bin", "PYTHONPATH": "/x"}
        self.assertEqual(launch_env(ToolLaunch(tool="sby", binary="sby"), env), env)
        self.assertEqual(
            launch_env(ToolLaunch(tool="sby", binary="sby"), None, ambient={"A": "1"}), {"A": "1"}
        )

    def test_extra_env_applies_below_stage_owned_variables(self) -> None:
        ambient = {"PATH": "/bin", "PYTHONPATH": "/ambient"}
        stage = {"PATH": "/bin", "PYTHONPATH": "/stage", "RANDOM_SEED": "7"}
        launch = ToolLaunch(
            tool="sby",
            binary="sby",
            extra_env={"PYTHONPATH": "/site", "RANDOM_SEED": "0", "YOSYS": "/opt/yosys"},
        )
        env = launch_env(launch, stage, ambient=ambient)
        self.assertEqual(env["PYTHONPATH"], "/stage")
        self.assertEqual(env["RANDOM_SEED"], "7")
        self.assertEqual(env["YOSYS"], "/opt/yosys")

    def test_setup_hook_exports_apply_and_run_once(self) -> None:
        counter = self.tmp / "runs.txt"
        hook = self.hook(
            "eda.env",
            f"""
            echo run >> "{counter}"
            export EDA_HOME=/opt/eda
            export PATH="/opt/eda/bin:$PATH"
            export SEEN_EXTRA="$FROM_EXTRA"
            unset GONE
            """,
        )
        launch = ToolLaunch(
            tool="vcs", binary="vcs", extra_env={"FROM_EXTRA": "yes"}, setup_hook=hook
        )
        ambient = {"PATH": "/bin:/usr/bin", "GONE": "1", "KEEP": "k"}
        first = launch_env(launch, {**ambient, "GONE": "stage"}, ambient=ambient)
        second = launch_env(launch, None, ambient=ambient)
        self.assertEqual(first["EDA_HOME"], "/opt/eda")
        self.assertEqual(first["PATH"], "/opt/eda/bin:/bin:/usr/bin")
        self.assertEqual(first["SEEN_EXTRA"], "yes")
        self.assertEqual(first["FROM_EXTRA"], "yes")
        self.assertEqual(first["KEEP"], "k")
        # The stage set GONE itself, so the hook's unset does not take it away.
        self.assertEqual(first["GONE"], "stage")
        self.assertNotIn("GONE", second)
        self.assertNotIn("PWD", second)
        self.assertEqual(counter.read_text().count("run"), 1)

    def test_failing_setup_hook_is_a_config_error(self) -> None:
        hook = self.hook("bad.env", "echo module not found\nexit 3\n")
        launch = ToolLaunch(tool="vcs", binary="vcs", setup_hook=hook)
        with self.assertRaises(ConfigError) as ctx:
            launch_env(launch, None, ambient={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
        self.assertIn("exited 3", str(ctx.exception))
        self.assertIn("module not found", str(ctx.exception))


def formal_flow(raw: dict) -> Dut:
    return Dut(
        name="dtp",
        kind="fv",
        description="unit-test formal flow",
        framework="formal",
        visibility="public",
        runnability="contributor",
        license="none",
        root="hw/sys/dtp/dv",
        default_tool="sby",
        tools=["sby"],
        path=Path("dtp_formal_cfg.toml"),
        raw=raw,
        frameworks=["formal"],
        default_framework="formal",
    )


class StageLaunchTest(SiteCase):
    def run_dry(self, argv: list[str], launch: ToolLaunch) -> tuple[str, Path, Path]:
        script = self.tmp / "scripts" / "stage.sh"
        env_path = self.tmp / "env" / "stage.env"
        out = io.StringIO()
        with redirect_stdout(out):
            rc = stages.run_subprocess(
                argv,
                self.tmp,
                self.tmp / "logs" / "stage.log",
                True,
                script,
                env_path,
                True,
                launch=launch,
            )
        self.assertEqual(rc, 0)
        return out.getvalue(), script, env_path

    def test_run_subprocess_prefixes_the_launcher_and_exports_extra_env(self) -> None:
        launch = ToolLaunch(
            tool="vcs",
            binary="vcs-2026",
            launcher=tuple(LAUNCHER),
            extra_env={"VCS_HOME": "/opt/vcs"},
        )
        out, _script, _env = self.run_dry(["vcs-2026", "-full64", "-f", "a.f"], launch)
        self.assertIn("CMD  : podman exec -i eda vcs-2026 -full64 -f a.f", out)
        # A real run: `env` stands in for the container launcher, so the prefixed command
        # executes and the log, replay script, and env snapshot all show the layer.
        real = ToolLaunch(
            tool="vcs", binary="sh", launcher=("env",), extra_env={"VCS_HOME": "/opt/vcs"}
        )
        log, script, env_path = (self.tmp / "l.log", self.tmp / "s.sh", self.tmp / "e.env")
        rc = stages.run_subprocess(
            ["sh", "-c", 'printf "%s" "$VCS_HOME"'],
            self.tmp,
            log,
            False,
            script,
            env_path,
            True,
            launch=real,
        )
        self.assertEqual(rc, 0)
        self.assertEqual(log.read_text().splitlines()[-1], "/opt/vcs")
        self.assertTrue(log.read_text().startswith("# cmd: env sh -c "), log.read_text())
        self.assertIn("env sh -c ", script.read_text())
        self.assertIn("VCS_HOME=/opt/vcs", env_path.read_text())

    def test_formal_stage_renders_the_site_binary_behind_the_launcher(self) -> None:
        merged = self.merged(f'[simulators.sby]\nbinary = "sby-site"\nlauncher = {LAUNCHER_TOML}\n')
        raw = {
            "native": {"stages": {"formal": {"kind": "formal_run"}}},
            "formal": {
                "apps": {"fpv": {"sby": {"cwd": ".", "script": "dtp.sby", "args": ["bmc"]}}}
            },
        }
        catalog = TestCatalog(
            path=None, tests={"dtp_fpv": TestEntry(name="dtp_fpv", module="fpv")}, groups={}
        )
        args = Namespace(
            dry_run=True,
            quiet=True,
            verbose=False,
            timeout=None,
            proof_depth=None,
            formal_arg=None,
            app=None,
            ui="plain",
        )
        out = io.StringIO()
        with redirect_stdout(out):
            rc = stages.formal_run_stage(
                formal_flow(raw),
                REPO_ROOT,
                raw,
                catalog,
                "dtp_fpv",
                args,
                "sby",
                merged,
                {"run_dir": str(self.tmp), "item": "dtp_fpv", "tool": "sby"},
                self.tmp / "logs" / "dtp_fpv.log",
                self.tmp / "scripts" / "formal.sh",
                self.tmp / "env" / "formal.env",
            )
        self.assertEqual(rc, 0)
        cmd = next(line for line in out.getvalue().splitlines() if line.startswith("CMD  :"))
        self.assertTrue(
            cmd.startswith(
                f"CMD  : podman exec -i eda sby-site -f --prefix {self.tmp}/stages/formal/dtp_fpv"
            ),
            cmd,
        )

    def test_coverage_commands_run_behind_the_launcher(self) -> None:
        root = self.tmp
        closure.stage_fixture(root)
        run_dir = root / "run"
        args = closure.make_args()
        args.dry_run = True
        args._simulators = {
            closure.TOOL: {"supports_cov": closure.SUPPORTED_METRICS, "launcher": LAUNCHER}
        }
        out = io.StringIO()
        stage_dir = run_dir / "stages" / "cov_report"
        with redirect_stdout(out):
            rc = stages.coverage_stage(
                closure.make_flow(root),
                root,
                {"coverage": {closure.TOOL: closure.tool_coverage_cfg()}},
                closure.TOOL,
                run_dir,
                "report",
                args,
                stage_dir / "logs" / "cov_report.log",
                stage_dir / "scripts" / "cov_report.sh",
                stage_dir / "env" / "cov_report.env",
                True,
            )
        self.assertEqual(rc, 0)
        cmd = next(line for line in out.getvalue().splitlines() if line.startswith("CMD  :"))
        self.assertTrue(cmd.startswith("CMD  : podman exec -i eda "), cmd)

    def test_stage_tool_launch_reads_the_registry_run_stage_attaches(self) -> None:
        args = Namespace(_simulators={"vcs": {"binary": "vcs-2026", "launcher": ["podman"]}})
        launch = stages.stage_tool_launch(args, "vcs")
        self.assertEqual((launch.binary, launch.launcher), ("vcs-2026", ("podman",)))
        self.assertEqual(stages.stage_tool_launch(Namespace(), "vcs").binary, "vcs")

    def test_cocotb_path_rejects_a_launcher(self) -> None:
        with self.assertRaises(ConfigError) as ctx:
            stages.reject_cocotb_launcher(
                ToolLaunch(tool="verilator", binary="verilator", launcher=("podman",))
            )
        self.assertIn("cocotb", str(ctx.exception))
        stages.reject_cocotb_launcher(ToolLaunch(tool="verilator", binary="verilator-5"))

    def test_cocotb_binary_patch_renames_and_restores(self) -> None:
        try:
            from cocotb_tools import runner as cocotb_runner
        except ImportError:  # pragma: no cover - the dv dependency group supplies cocotb
            self.skipTest("cocotb_tools is not installed")
        original_probe = cocotb_runner.Vcs._simulator_in_path
        original_build = cocotb_runner.Vcs._build_command
        with stages.cocotb_tool_binary("vcs", "vcs-2026"):
            self.assertIsNot(cocotb_runner.Vcs._simulator_in_path, original_probe)
            renamed = stages._rename_commands(
                [["vcs", "-full64"], ["make"], "text"], "vcs", "vcs-2026"
            )
            self.assertEqual(renamed, [["vcs-2026", "-full64"], ["make"], "text"])
            with mock.patch("shutil.which", side_effect=which_from({})):
                with self.assertRaises(SystemExit):
                    cocotb_runner.Vcs._simulator_in_path(mock.Mock())
        self.assertIs(cocotb_runner.Vcs._simulator_in_path, original_probe)
        self.assertIs(cocotb_runner.Vcs._build_command, original_build)
        with stages.cocotb_tool_binary("vcs", "vcs"):
            self.assertIs(cocotb_runner.Vcs._simulator_in_path, original_probe)
        original_verilator = cocotb_runner.Verilator._simulator_in_path_build_only
        with stages.cocotb_tool_binary("verilator", "verilator-5.036"):
            holder = mock.Mock()
            with mock.patch(
                "shutil.which",
                side_effect=which_from({"verilator-5.036": "/opt/v/bin/verilator-5.036"}),
            ):
                cocotb_runner.Verilator._simulator_in_path_build_only(holder)
            self.assertEqual(holder.executable, "/opt/v/bin/verilator-5.036")
        self.assertIs(cocotb_runner.Verilator._simulator_in_path_build_only, original_verilator)


class CliViewsTest(SiteCase):
    def site_env(self, text: str) -> dict[str, str]:
        return {site.SITE_ENV: str(self.write("site.toml", text))}

    def run_doctor(self, tool: str, found: dict[str, str], site_toml: str) -> tuple[int, str]:
        args = Namespace(dut=None, tool=tool, mode="sim", framework=None, overlay=None)
        out = io.StringIO()
        bash = shutil.which("bash")
        assert bash is not None
        found = {"bash": bash, **found}
        with (
            mock.patch.dict(os.environ, self.site_env(site_toml)),
            mock.patch.object(cli, "load_duts", return_value={}),
            mock.patch.object(cli, "_doctor_python_environment", return_value=False),
            mock.patch("shutil.which", side_effect=which_from(found)),
            redirect_stdout(out),
        ):
            rc = cli.cmd_doctor(REPO_ROOT, args)
        return rc, out.getvalue()

    def test_load_registries_merges_the_layer_once(self) -> None:
        with mock.patch.dict(os.environ, self.site_env('[simulators.sby]\nbinary = "sby-site"\n')):
            registries = cli.load_registries(REPO_ROOT)
        assert registries.site is not None
        self.assertEqual(registries.simulators["sby"]["binary"], "sby-site")
        self.assertIn("sby", registries.checked_in_tools)
        self.assertEqual(
            registries.tool_source("sby"), f"simulators.toml + {registries.site.label} (binary)"
        )
        self.assertEqual(registries.tool_source("verilator"), "simulators.toml")
        self.assertIn("sby(binary)", registries.site_summary())
        with mock.patch.dict(os.environ, {site.SITE_ENV: ""}):
            self.assertIsNone(cli.load_registries(REPO_ROOT).site)

    def test_load_registries_rejects_an_unknown_site_dut(self) -> None:
        cfg = self.write("x_formal_cfg.toml", "name = 'x'\n")
        with (
            mock.patch.dict(
                os.environ, self.site_env(f'[duts.no_such_dut]\nformal_cfg = "{cfg}"\n')
            ),
            self.assertRaises(ConfigError) as ctx,
        ):
            cli.load_registries(REPO_ROOT)
        self.assertIn("no_such_dut", str(ctx.exception))

    def test_load_registries_checks_the_tools_a_dut_entry_adds(self) -> None:
        for body, needles in (
            ('tools = ["nosuch"]', ("[duts.dtp].tools names unknown tool `nosuch`",)),
            ('tools = ["sby"]', ("`sby`, a formal tool", "list simulation tools only")),
        ):
            with (
                mock.patch.dict(os.environ, self.site_env(f"[duts.dtp]\n{body}\n")),
                self.assertRaises(ConfigError) as ctx,
            ):
                cli.load_registries(REPO_ROOT)
            for needle in (*needles, "site layer"):
                self.assertIn(needle, str(ctx.exception))

    def test_selecting_a_dut_whose_site_sim_cfg_is_absent_names_the_pointer(self) -> None:
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch.dict(
                os.environ, self.site_env('[duts.dtp]\nsim_cfg = "/absent/dtp_sim_cfg.toml"\n')
            ),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            rc = cli.main(["--dut", "dtp", "--items", "smoke", "--dry-run"])
        text = out.getvalue() + err.getvalue()
        self.assertEqual(rc, 2, text)
        self.assertIn("sim config not found: /absent/dtp_sim_cfg.toml", text)
        self.assertIn("named by the site layer", text)
        self.assertNotIn("unknown DUT", text)

    def test_doctor_names_the_site_file_and_probes_the_launcher(self) -> None:
        rc, out = self.run_doctor(
            "sby",
            {"podman": "/usr/bin/podman"},
            f'[simulators.sby]\nbinary = "sby-site"\nlauncher = {LAUNCHER_TOML}\n',
        )
        self.assertEqual(rc, 0, out)
        label = str((self.tmp / "site.toml").resolve())
        self.assertIn(f"site    : {label}", out)
        row = next(line for line in out.splitlines() if line.split()[:1] == ["sby"])
        self.assertIn("sby-site", row)
        self.assertIn("launcher found: /usr/bin/podman", row)
        self.assertIn(f"simulators.toml + {label} (binary, launcher)", row)
        self.assertIn("Result: required tool `sby` is available", out)

    def test_doctor_reports_a_missing_launcher_and_a_failing_hook(self) -> None:
        rc, out = self.run_doctor(
            "sby", {"sby": "/usr/bin/sby"}, f"[simulators.sby]\nlauncher = {LAUNCHER_TOML}\n"
        )
        self.assertEqual(rc, 2)
        self.assertIn("launcher `podman` MISSING", out)
        hook = self.hook("bad.env", "echo no module\nexit 9\n")
        rc, out = self.run_doctor(
            "sby", {"sby": "/usr/bin/sby"}, f'[simulators.sby]\nsetup_hook = "{hook}"\n'
        )
        self.assertEqual(rc, 2)
        self.assertIn("setup_hook FAILED", out)
        self.assertIn("exited 9", out)

    def test_doctor_without_a_site_file_says_none(self) -> None:
        rc, out = self.run_doctor("sby", {"sby": "/usr/bin/sby"}, "schema_version = 1\n")
        self.assertEqual(rc, 0)
        self.assertIn("simulators.toml", out)
        with mock.patch.dict(os.environ, {site.SITE_ENV: ""}):
            args = Namespace(dut=None, tool="sby", mode="sim", framework=None, overlay=None)
            out2 = io.StringIO()
            with (
                mock.patch.object(cli, "load_duts", return_value={}),
                mock.patch.object(cli, "load_site_layer", return_value=None),
                mock.patch.object(cli, "_doctor_python_environment", return_value=False),
                mock.patch("shutil.which", side_effect=which_from({"sby": "/usr/bin/sby"})),
                redirect_stdout(out2),
            ):
                cli.cmd_doctor(REPO_ROOT, args)
        self.assertIn("site    : none", out2.getvalue())

    def test_selected_tool_probe_names_the_launcher(self) -> None:
        merged = self.merged(f"[simulators.sby]\nlauncher = {LAUNCHER_TOML}\n")
        flow = formal_flow({})
        with mock.patch("shutil.which", side_effect=which_from({"podman": "/usr/bin/podman"})):
            cli.validate_selected_tool_available("sby", merged, Namespace(dry_run=False), flow)
        with (
            mock.patch("shutil.which", side_effect=which_from({"sby": "/usr/bin/sby"})),
            self.assertRaises(ConfigError) as ctx,
        ):
            cli.validate_selected_tool_available("sby", merged, Namespace(dry_run=False), flow)
        self.assertIn("requires launcher `podman` in PATH", str(ctx.exception))

    def test_validate_configs_reports_the_site_layer(self) -> None:
        out = io.StringIO()
        with (
            mock.patch.dict(os.environ, self.site_env('[simulators.sby]\nbinary = "sby-site"\n')),
            mock.patch.object(cli, "load_duts", return_value={}),
            redirect_stdout(out),
        ):
            rc = cli.cmd_validate_configs(REPO_ROOT)
        self.assertEqual(rc, 0)
        self.assertIn("site layer       OK", out.getvalue())
        self.assertIn("sby(binary)", out.getvalue())
        out = io.StringIO()
        with (
            mock.patch.dict(os.environ, self.site_env("[simulators.sby]\nfrobnicate = 1\n")),
            redirect_stdout(out),
        ):
            rc = cli.cmd_validate_configs(REPO_ROOT)
        self.assertEqual(rc, 2)
        self.assertIn("registries       FAIL", out.getvalue())
        self.assertIn("frobnicate", out.getvalue())


class ResolveDutTest(SiteCase):
    def formal_cfg(self, name: str) -> Path:
        return self.write(
            f"{name}_formal_cfg.toml",
            f"""
            name = "{name}"
            kind = "fv"
            profile = "native-formal"
            [formal.apps.fpv.sby]
            cwd = "hw/sys/{name}/dv/formal/fpv/sby"
            script = "{name}.sby"
            """,
        )

    def test_site_formal_cfg_wins_for_formal_mode_only(self) -> None:
        cfg = self.formal_cfg("dtp")
        layer = self.load(f'[duts.dtp]\nformal_cfg = "{cfg}"\n')
        flow = resolve_dut(REPO_ROOT, "dtp", mode="formal", site=layer)
        self.assertEqual(flow.path, cfg)
        self.assertEqual((flow.kind, flow.default_tool, flow.framework), ("fv", "sby", "formal"))
        sim = resolve_dut(REPO_ROOT, "dtp", site=layer)
        self.assertEqual(sim.path.name, "dtp_sim_cfg.toml")
        # Without the site pointer the DUT's own formal config is the one loaded.
        own = resolve_dut(REPO_ROOT, "dtp", mode="formal")
        self.assertEqual(own.path, REPO_ROOT / "hw/sys/dtp/dv/dtp_formal_cfg.toml")

    def test_site_entry_for_the_canonical_dut_serves_its_alias(self) -> None:
        cfg = self.formal_cfg("smu")
        layer = self.load(f'[duts.smu]\nformal_cfg = "{cfg}"\n')
        flow = resolve_dut(REPO_ROOT, "smu_wrapper", mode="formal", site=layer)
        self.assertEqual(flow.path, cfg)
        self.assertEqual(flow.name, "smu")

    def test_site_sim_cfg_wins_for_sim_mode_only(self) -> None:
        cfg = self.tmp / "dtp_sim_cfg.toml"
        shutil.copy(REPO_ROOT / "hw/sys/dtp/dv/dtp_sim_cfg.toml", cfg)
        layer = self.load(f'[duts.dtp]\nsim_cfg = "{cfg}"\n')
        flow = resolve_dut(REPO_ROOT, "dtp", site=layer)
        own = resolve_dut(REPO_ROOT, "dtp")
        self.assertEqual(flow.path, cfg)
        self.assertEqual((flow.name, flow.root), (own.name, own.root))
        formal = resolve_dut(REPO_ROOT, "dtp", mode="formal", site=layer)
        self.assertEqual(formal.path, REPO_ROOT / "hw/sys/dtp/dv/dtp_formal_cfg.toml")

    def test_site_tools_join_the_views_whose_framework_they_serve(self) -> None:
        layer = self.load(
            """
            [simulators.simtool]
            kind = "simulation"
            frameworks = ["uvm"]
            license_env = ["SIMTOOL_LICENSE_FILE"]
            [duts.dtp]
            tools = ["simtool", "vcs"]
            """
        )
        for framework in (None, "uvm"):
            own = resolve_dut(REPO_ROOT, "dtp", framework=framework)
            flow = resolve_dut(REPO_ROOT, "dtp", framework=framework, site=layer)
            expected = [*own.tools, "simtool"] if own.framework == "uvm" else own.tools
            self.assertEqual(flow.tools, expected, own.framework)
            self.assertEqual(flow.default_tool, own.default_tool)
        formal = resolve_dut(REPO_ROOT, "dtp", mode="formal", site=layer)
        self.assertEqual(formal.tools, resolve_dut(REPO_ROOT, "dtp", mode="formal").tools)

    def test_site_tools_for_the_canonical_dut_serve_its_alias(self) -> None:
        layer = self.load(
            """
            [simulators.simtool]
            kind = "simulation"
            frameworks = ["cocotb"]
            license_env = []
            [duts.smu]
            tools = ["simtool"]
            """
        )
        flow = resolve_dut(REPO_ROOT, "smu_wrapper", site=layer)
        self.assertEqual(flow.tools[-1], "simtool")
        self.assertEqual(flow.name, "smu")


class ResultRecordingTest(SiteCase):
    def payload(self, args: Namespace | None) -> dict:
        return result_payload(
            flow=formal_flow({}),
            root=self.tmp,
            tool="sby",
            run_dir=self.tmp / "run",
            stages=[],
            dry_run=True,
            versions={},
            git_metadata={},
            args=args,
        )

    def test_site_file_recorded_when_applied(self) -> None:
        payload = self.payload(Namespace(_site_layer="hw/common/dv/configs/site.local.toml"))
        self.assertEqual(payload["site"], "hw/common/dv/configs/site.local.toml")

    def test_no_site_means_no_key(self) -> None:
        self.assertNotIn("site", self.payload(Namespace()))
        self.assertNotIn("site", self.payload(None))


class ExampleFileTest(SiteCase):
    def test_example_loads_and_merges_over_the_registries(self) -> None:
        layer = load_site_layer(REPO_ROOT, {site.SITE_ENV: str(EXAMPLE)})
        assert layer is not None
        simulators = merged_simulators(load_simulators(REPO_ROOT), layer)
        merged_executors(load_executors(REPO_ROOT), layer)
        self.assertTrue(layer.simulators, "the example overrides at least one tool")
        launched = [tool for tool, table in layer.simulators.items() if "launcher" in table]
        self.assertTrue(launched, "the example shows the container launcher case")
        for tool in launched:
            self.assertEqual(
                tool_launch(simulators, tool).launcher[0], layer.simulators[tool]["launcher"][0]
            )
        self.assertFalse(
            layer.duts, "a pointer into a companion checkout cannot resolve in this tree"
        )


if __name__ == "__main__":
    unittest.main()
