# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for runlib.config run-mode / overlay validation and runlib.duts resolution.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

import os
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib.cli import (  # noqa: E402
    expand_items,
    regression_reseed_count,
    requested_targets,
    target_plan,
    validate_item_tools,
    validate_target_plan,
)
from runlib.config import (  # noqa: E402
    OverlayFrameworkMismatch,
    _merge_framework_config,
    activate_adopter_overlay_env,
    apply_adopter_overlay,
    load_dut,
    load_test_catalog,
    rerun_selection,
    selected_run_mode,
    target_flags,
    validate_native_config_shape,
    validate_run_mode_request,
    validate_target_redirects,
    with_target_instances,
)
from runlib.duts import load_dut_registry  # noqa: E402
from runlib.models import ConfigError, Dut, TestCatalog, TestEntry  # noqa: E402
from runlib.results import result_payload  # noqa: E402


def make_dut(raw: dict, path: Path = Path("test_sim_cfg.toml")) -> Dut:
    return Dut(
        name="unit",
        kind="sim",
        description="unit-test DUT",
        framework="cocotb",
        visibility="public",
        runnability="runnable",
        license="Apache-2.0",
        root=".",
        default_tool="verilator",
        tools=["verilator"],
        path=path,
        raw=raw,
        frameworks=["cocotb"],
        default_framework="cocotb",
    )


def inline_raw(run_modes: dict, tests: list, defaults: dict | None = None) -> dict:
    raw = {"run_modes": run_modes, "tests": tests}
    if defaults is not None:
        raw["defaults"] = defaults
    return raw


SMOKE = {"smoke": {"timeout_sec": 60, "args": []}}


class TestlistToolValidation(unittest.TestCase):
    """Per-test `tools`: names checked against the DUT's own list at catalog load."""

    def test_unknown_tool_rejected(self):
        flow = make_dut(inline_raw(SMOKE, [{"name": "t1", "tools": ["verilatro"]}]))
        with self.assertRaises(ConfigError) as ctx:
            load_test_catalog(flow, Path("."))
        message = str(ctx.exception)
        self.assertIn("t1", message)
        self.assertIn("verilatro", message)
        self.assertIn("verilator", message)  # the declared set is listed

    def test_declared_tool_passes(self):
        flow = make_dut(inline_raw(SMOKE, [{"name": "t1", "tools": ["verilator"]}]))
        catalog = load_test_catalog(flow, Path("."))
        self.assertEqual(catalog.tests["t1"].tools, ["verilator"])

    def test_absent_key_means_every_tool(self):
        flow = make_dut(inline_raw(SMOKE, [{"name": "t1"}]))
        catalog = load_test_catalog(flow, Path("."))
        self.assertEqual(catalog.tests["t1"].tools, [])

    def test_explicitly_empty_rejected(self):
        # An absent key and `tools = []` both reach TestEntry as [], so the difference is
        # caught at parse time where the raw entry is still visible.
        flow = make_dut(inline_raw(SMOKE, [{"name": "t1", "tools": []}]))
        with self.assertRaises(ConfigError) as ctx:
            load_test_catalog(flow, Path("."))
        self.assertIn("empty", str(ctx.exception))

    def test_unbound_scenario_is_not_gated_by_this_view(self):
        # A view with no binding for the scenario never runs it, so it does not check the
        # scenario's `tools`: a framework overlay may declare a narrower tool list than the
        # scenario names. Here the cocotb view sees a scenario bound only to uvm.
        flow = make_dut(
            inline_raw(SMOKE, [{"name": "t1", "module": {"uvm": "m"}, "tools": ["vcs"]}])
        )
        flow.frameworks = ["cocotb", "uvm"]
        catalog = load_test_catalog(flow, Path("."))
        self.assertEqual(catalog.tests["t1"].module, "")
        self.assertEqual(catalog.tests["t1"].tools, ["vcs"])


class TestlistRunModeValidation(unittest.TestCase):
    def test_unknown_testlist_run_mode_rejected(self):
        flow = make_dut(inline_raw(SMOKE, [{"name": "t1", "run_modes": ["smoke", "typo_mode"]}]))
        with self.assertRaises(ConfigError) as ctx:
            load_test_catalog(flow, Path("."))
        message = str(ctx.exception)
        self.assertIn("t1", message)
        self.assertIn("typo_mode", message)
        self.assertIn("smoke", message)  # the allowed set is listed

    def test_known_testlist_run_modes_pass(self):
        flow = make_dut(inline_raw(SMOKE, [{"name": "t1", "run_modes": ["smoke"]}]))
        catalog = load_test_catalog(flow, Path("."))
        self.assertEqual(list(catalog.tests), ["t1"])

    def test_unknown_reference_in_included_file_names_that_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "leaf.toml").write_text(
                'schema_version = 1\n[[tests]]\nname = "t_leaf"\nrun_modes = ["typo_mode"]\n'
            )
            (root / "all.toml").write_text('schema_version = 1\nincludes = ["leaf.toml"]\n')
            flow = make_dut({"run_modes": SMOKE, "testlist": {"path": str(root / "all.toml")}})
            with self.assertRaises(ConfigError) as ctx:
                load_test_catalog(flow, root)
            self.assertIn("leaf.toml", str(ctx.exception))

    def test_unknown_defaults_run_mode_rejected(self):
        flow = make_dut(inline_raw(SMOKE, [], defaults={"run_mode": "typo_mode"}))
        with self.assertRaises(ConfigError) as ctx:
            load_test_catalog(flow, Path("."))
        self.assertIn("[defaults].run_mode", str(ctx.exception))


class CliRunModeValidation(unittest.TestCase):
    def test_unknown_cli_run_mode_rejected(self):
        with self.assertRaises(ConfigError) as ctx:
            validate_run_mode_request({"run_modes": SMOKE}, "typo_mode", "--run-mode")
        message = str(ctx.exception)
        self.assertIn("--run-mode", message)
        self.assertIn("typo_mode", message)
        self.assertIn("smoke", message)

    def test_no_modes_defined_reports_none(self):
        with self.assertRaises(ConfigError) as ctx:
            validate_run_mode_request({}, "anything", "--run-mode")
        self.assertIn("none defined", str(ctx.exception))


class SelectedRunModeResolution(unittest.TestCase):
    def test_explicit_cli_typo_raises(self):
        flow = make_dut(inline_raw(SMOKE, [{"name": "t1", "run_modes": ["smoke"]}]))
        catalog = load_test_catalog(flow, Path("."))
        with self.assertRaises(ConfigError):
            selected_run_mode(flow.raw, catalog.tests["t1"], Namespace(run_mode="typo_mode"))

    def test_test_reference_resolves(self):
        flow = make_dut(inline_raw(SMOKE, [{"name": "t1", "run_modes": ["smoke"]}]))
        catalog = load_test_catalog(flow, Path("."))
        mode = selected_run_mode(flow.raw, catalog.tests["t1"], Namespace(run_mode=None))
        self.assertEqual(mode["timeout_sec"], 60)

    def test_implicit_smoke_fallback_stays_optional(self):
        # A DUT without a `smoke` mode (e.g. sep) must resolve to no mode, not error,
        # when neither the CLI, the test, nor [defaults] names one.
        sim_cfg = {"run_modes": {"cpu": {"timeout_sec": 60}}}
        self.assertEqual(selected_run_mode(sim_cfg, None, Namespace(run_mode=None)), {})


class InheritedProfileRunModes(unittest.TestCase):
    def test_profile_run_mode_counts_as_defined(self):
        profile = {
            "frameworks": {"cocotb": {}},
            "run_modes": {"inherited": {"timeout_sec": 120, "args": []}},
        }
        dut = {
            "frameworks": {"cocotb": {}},
            "tests": [{"name": "t1", "run_modes": ["inherited"]}],
        }
        merged, selected, _, _ = _merge_framework_config(
            profile, dut, Path("unit_sim_cfg.toml"), "unit_profile"
        )
        self.assertEqual(selected, "cocotb")
        flow = make_dut(merged)
        catalog = load_test_catalog(flow, Path("."))
        mode = selected_run_mode(merged, catalog.tests["t1"], Namespace(run_mode=None))
        self.assertEqual(mode["timeout_sec"], 120)

    def test_dut_entry_overrides_profile_entry(self):
        profile = {
            "frameworks": {"cocotb": {}},
            "run_modes": {"shared": {"timeout_sec": 120}},
        }
        dut = {
            "frameworks": {"cocotb": {}},
            "run_modes": {"shared": {"timeout_sec": 30}},
        }
        merged, _, _, _ = _merge_framework_config(
            profile, dut, Path("unit_sim_cfg.toml"), "unit_profile"
        )
        self.assertEqual(merged["run_modes"]["shared"]["timeout_sec"], 30)


class AdopterOverlayLayer(unittest.TestCase):
    """The --overlay/OCAH_DV_OVERLAY layer: append-only merge, guard, and activation rules."""

    def apply(self, data: dict, overlay_toml: str) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            overlay = root / "adopter_overlay.toml"
            overlay.write_text(overlay_toml)
            apply_adopter_overlay(data, root, overlay)
        return data

    def test_build_and_sim_lists_append_after_dut_entries(self):
        data = {
            "framework": "uvm",
            "build": {"incdirs": ["dut/inc"], "sources": ["dut/tb.sv"]},
            "sim": {"args": ["+dut_arg"]},
        }
        self.apply(
            data,
            '[build]\nincdirs = ["vendor/inc", "dut/inc"]\nsources = ["vendor/pkg.sv"]\n'
            '[sim]\nargs = ["+uvm_set_type_override=ocah_axi_master_env,vendor_axi_env"]\n',
        )
        self.assertEqual(
            data["build"]["incdirs"], ["dut/inc", "vendor/inc"]
        )  # dedup keeps DUT order
        self.assertEqual(data["build"]["sources"], ["dut/tb.sv", "vendor/pkg.sv"])
        self.assertEqual(
            data["sim"]["args"],
            ["+dut_arg", "+uvm_set_type_override=ocah_axi_master_env,vendor_axi_env"],
        )

    def test_target_defines_and_tool_flags_dedup_append(self):
        data = {
            "framework": "uvm",
            "target_defaults": {
                "default": {"defines": ["UVM"], "tools": {"vcs": {"flags": ["-x"]}}}
            },
        }
        self.apply(
            data,
            '[target_defaults.default]\ndefines = ["OCAH_JTAG_VENDOR_IF", "UVM"]\n'
            '[target_defaults.default.tools.vcs]\nflags = ["-assert", "svaext"]\n',
        )
        target = data["target_defaults"]["default"]
        self.assertEqual(target["defines"], ["UVM", "OCAH_JTAG_VENDOR_IF"])
        self.assertEqual(target["tools"]["vcs"]["flags"], ["-x", "-assert", "svaext"])

    def test_missing_target_table_is_created(self):
        data = {"framework": "uvm"}
        self.apply(data, '[targets.default]\ndefines = ["OCAH_AXI_VENDOR_IF"]\n')
        self.assertEqual(data["targets"]["default"]["defines"], ["OCAH_AXI_VENDOR_IF"])

    def test_reapplication_is_idempotent_for_dedup_keys(self):
        data = {"framework": "uvm", "build": {"incdirs": ["dut/inc"]}}
        toml = '[build]\nincdirs = ["vendor/inc"]\n'
        self.apply(data, toml)
        self.apply(data, toml)
        self.assertEqual(data["build"]["incdirs"], ["dut/inc", "vendor/inc"])

    def test_frameworks_guard_mismatch_raises_distinct_error(self):
        data = {"framework": "cocotb"}
        with self.assertRaises(OverlayFrameworkMismatch) as ctx:
            self.apply(data, 'frameworks = ["uvm"]\n[sim]\nargs = ["+x"]\n')
        self.assertIn("cocotb", str(ctx.exception))

    def test_frameworks_guard_match_applies(self):
        data = {"framework": "uvm", "sim": {"args": []}}
        self.apply(data, 'frameworks = ["uvm"]\n[sim]\nargs = ["+x"]\n')
        self.assertEqual(data["sim"]["args"], ["+x"])

    def test_unsupported_keys_rejected(self):
        for toml, named in (
            ('default_tool = "vcs"\n', "default_tool"),  # replacement keys are not appendable
            ('[build]\nfilelist = "x.f"\n', "filelist"),
            ('[target_defaults.default]\nbuild_dir = "x"\n', "build_dir"),
            ('[targets.default.tools.vcs]\nrun_on = "stub"\n', "run_on"),
        ):
            with self.assertRaises(ConfigError) as ctx:
                self.apply({"framework": "uvm"}, toml)
            self.assertNotIsInstance(ctx.exception, OverlayFrameworkMismatch)
            self.assertIn(named, str(ctx.exception))

    def test_missing_overlay_file_rejected(self):
        with self.assertRaises(ConfigError) as ctx:
            apply_adopter_overlay({"framework": "uvm"}, Path("."), Path("no_such_overlay.toml"))
        self.assertIn("not found", str(ctx.exception))

    def test_applied_path_is_recorded(self):
        data = {"framework": "uvm"}
        self.apply(data, '[sim]\nargs = ["+x"]\n')
        self.assertEqual(data["adopter_overlay"], "adopter_overlay.toml")

    def test_build_paths_expand_environment_variables(self):
        data = {"framework": "uvm", "build": {"incdirs": ["dut/inc"]}}
        with mock.patch.dict(os.environ, {"VENDOR_VIP_HOME": "/opt/vip", "VIP_MANIFEST": "vip"}):
            self.apply(
                data,
                '[build]\nincdirs = ["$VENDOR_VIP_HOME/include"]\n'
                'sources = ["${VENDOR_VIP_HOME}/src/vip_pkg.sv"]\n'
                'source_lists = ["$VENDOR_VIP_HOME/${VIP_MANIFEST}/sources.toml"]\n',
            )
        self.assertEqual(data["build"]["incdirs"], ["dut/inc", "/opt/vip/include"])
        self.assertEqual(data["build"]["sources"], ["/opt/vip/src/vip_pkg.sv"])
        self.assertEqual(data["build"]["source_lists"], ["/opt/vip/vip/sources.toml"])

    def test_unset_environment_variable_names_variable_and_overlay(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("OCAH_UNSET_VIP_HOME", None)
            with self.assertRaises(ConfigError) as ctx:
                self.apply(
                    {"framework": "uvm"}, '[build]\nincdirs = ["$OCAH_UNSET_VIP_HOME/include"]\n'
                )
        self.assertNotIsInstance(ctx.exception, OverlayFrameworkMismatch)
        message = str(ctx.exception)
        self.assertIn("OCAH_UNSET_VIP_HOME", message)
        self.assertIn("adopter_overlay.toml", message)
        self.assertIn("build.incdirs", message)

    def test_paths_without_variables_pass_through_unchanged(self):
        data = {"framework": "uvm"}
        self.apply(data, '[build]\nincdirs = ["vendor/inc", "/abs/inc", "~/inc"]\n')
        self.assertEqual(data["build"]["incdirs"], ["vendor/inc", "/abs/inc", "~/inc"])

    def test_expanded_path_dedups_against_dut_entry(self):
        data = {"framework": "uvm", "build": {"incdirs": ["/opt/vip/include"]}}
        with mock.patch.dict(os.environ, {"VENDOR_VIP_HOME": "/opt/vip"}):
            self.apply(data, '[build]\nincdirs = ["$VENDOR_VIP_HOME/include"]\n')
        self.assertEqual(data["build"]["incdirs"], ["/opt/vip/include"])

    def test_env_table_is_recorded_and_feeds_path_expansion(self):
        data = {"framework": "uvm"}
        with mock.patch.dict(os.environ, {"VENDOR_VIP_HOME": "/ambient/vip"}):
            self.apply(
                data,
                '[env]\nVENDOR_VIP_HOME = "/opt/vip"\nVENDOR_VIP_LOG = "quiet"\n'
                '[build]\nincdirs = ["$VENDOR_VIP_HOME/include"]\n',
            )
            # Loading records the table and resolves paths against it, and leaves the
            # process environment to the run path.
            self.assertEqual(os.environ["VENDOR_VIP_HOME"], "/ambient/vip")
            self.assertNotIn("VENDOR_VIP_LOG", os.environ)
        self.assertEqual(data["build"]["incdirs"], ["/opt/vip/include"])
        self.assertEqual(
            data["adopter_overlay_env"],
            {"VENDOR_VIP_HOME": "/opt/vip", "VENDOR_VIP_LOG": "quiet"},
        )

    def test_env_table_absent_or_empty_leaves_no_record(self):
        for toml in ('[sim]\nargs = ["+x"]\n', "[env]\n"):
            data = {"framework": "uvm"}
            self.apply(data, toml)
            self.assertNotIn("adopter_overlay_env", data)

    def test_env_table_rejects_bad_names_and_non_string_values(self):
        for toml, named in (
            ("[env]\nPORT = 5\n", "PORT"),
            ('[env]\n"BAD NAME" = "x"\n', "BAD NAME"),
            ('[env]\n"1ST" = "x"\n', "1ST"),
            ('[env.nested]\nX = "x"\n', "nested"),
            ('env = "VENDOR_VIP_HOME=/opt/vip"\n', "[env]"),
        ):
            with self.assertRaises(ConfigError) as ctx:
                self.apply({"framework": "uvm"}, toml)
            self.assertNotIsInstance(ctx.exception, OverlayFrameworkMismatch)
            self.assertIn(named, str(ctx.exception))


class AdopterOverlayEnvActivation(unittest.TestCase):
    """The run-path step that puts an overlay's [env] into the process environment."""

    def test_overlay_values_replace_ambient_ones(self):
        environ = {"KEEP": "1", "VENDOR_VIP_HOME": "/ambient/vip"}
        table = {"VENDOR_VIP_HOME": "/opt/vip", "VENDOR_VIP_LOG": "quiet"}
        applied = activate_adopter_overlay_env({"adopter_overlay_env": table}, environ)
        self.assertEqual(applied, table)
        self.assertEqual(
            environ, {"KEEP": "1", "VENDOR_VIP_HOME": "/opt/vip", "VENDOR_VIP_LOG": "quiet"}
        )

    def test_view_without_overlay_env_is_a_no_op(self):
        environ = {"KEEP": "1"}
        for data in ({}, {"adopter_overlay": "adopter_overlay.toml"}, {"adopter_overlay_env": {}}):
            self.assertEqual(activate_adopter_overlay_env(data, environ), {})
        self.assertEqual(environ, {"KEEP": "1"})

    def test_defaults_to_the_process_environment(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("OCAH_UNIT_PROBE", None)
            activate_adopter_overlay_env({"adopter_overlay_env": {"OCAH_UNIT_PROBE": "on"}})
            self.assertEqual(os.environ["OCAH_UNIT_PROBE"], "on")


class AdopterOverlayResultRecording(unittest.TestCase):
    """result.json carries the overlay path and its [env] table side by side."""

    def payload(self, raw: dict) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            return result_payload(
                flow=make_dut(raw),
                root=root,
                tool="verilator",
                run_dir=root / "run",
                stages=[],
                dry_run=True,
                versions={},
                git_metadata={},
            )

    def test_overlay_env_recorded_beside_overlay_path(self):
        payload = self.payload(
            {
                "adopter_overlay": "adopter_overlay.toml",
                "adopter_overlay_env": {"VENDOR_VIP_HOME": "/opt/vip"},
            }
        )
        self.assertEqual(payload["overlay"], "adopter_overlay.toml")
        self.assertEqual(payload["overlay_env"], {"VENDOR_VIP_HOME": "/opt/vip"})

    def test_no_overlay_means_no_overlay_keys(self):
        payload = self.payload({})
        self.assertNotIn("overlay", payload)
        self.assertNotIn("overlay_env", payload)


class AdopterOverlayLoadDut(unittest.TestCase):
    """load_dut integration: explicit activation only, and source_lists expansion ordering."""

    def load(self, root: Path, extra_cfg: str = "", overlay: Path | None = None) -> Dut:
        cfg = root / "unit_sim_cfg.toml"
        cfg.write_text(
            'schema_version = 1\nname = "unit"\nkind = "dv"\n'
            'default_tool = "verilator"\ntools = ["verilator"]\n' + extra_cfg
        )
        return load_dut(cfg, root, root=root, name="unit", root_rel=".", adopter_overlay=overlay)

    def test_config_set_reserved_key_rejected(self):
        for line in ('adopter_overlay = "sneaky.toml"\n', 'adopter_overlay_env = { X = "1" }\n'):
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(ConfigError) as ctx:
                    self.load(Path(tmp), line)
                self.assertIn("--overlay", str(ctx.exception))

    def test_overlay_env_survives_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            overlay = root / "adopter_overlay.toml"
            overlay.write_text('[env]\nVENDOR_VIP_HOME = "/opt/vip"\n')
            with mock.patch.dict(os.environ):
                os.environ.pop("VENDOR_VIP_HOME", None)
                flow = self.load(root, overlay=overlay)
                self.assertNotIn("VENDOR_VIP_HOME", os.environ)
            self.assertEqual(flow.raw["adopter_overlay_env"], {"VENDOR_VIP_HOME": "/opt/vip"})

    def test_overlay_source_lists_expand_after_dut_own_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "vendor_inc").mkdir()
            (root / "vendor_pkg.sv").write_text("// vendor\n")
            (root / "vendor_sources.toml").write_text(
                'incdirs = ["vendor_inc"]\nsources = ["vendor_pkg.sv"]\n'
            )
            (root / "dut_tb.sv").write_text("// dut\n")
            overlay = root / "adopter_overlay.toml"
            overlay.write_text('[build]\nsource_lists = ["vendor_sources.toml"]\n')
            flow = self.load(root, '[build]\nsources = ["dut_tb.sv"]\n', overlay=overlay)
            # The overlay manifest expands like a DUT-owned one: fragment entries land AHEAD
            # of the DUT's direct sources (component layer compiles first).
            self.assertEqual(flow.raw["build"]["sources"], ["vendor_pkg.sv", "dut_tb.sv"])
            self.assertEqual(flow.raw["build"]["incdirs"], ["vendor_inc"])
            self.assertEqual(flow.raw["adopter_overlay"], "adopter_overlay.toml")

    def test_no_overlay_means_no_layer(self):
        with tempfile.TemporaryDirectory() as tmp:
            flow = self.load(Path(tmp))
            self.assertNotIn("adopter_overlay", flow.raw)

    def test_overlay_manifest_path_expands_environment_variable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vendor = root / "vendor_install"
            (vendor / "inc").mkdir(parents=True)
            (vendor / "vip_pkg.sv").write_text("// vendor\n")
            # Entries inside the manifest stay literal, so a manifest outside the checkout
            # lists its own files by absolute path.
            (vendor / "sources.toml").write_text(
                f'incdirs = ["{vendor / "inc"}"]\nsources = ["{vendor / "vip_pkg.sv"}"]\n'
            )
            overlay = root / "adopter_overlay.toml"
            overlay.write_text('[build]\nsource_lists = ["$VENDOR_VIP_HOME/sources.toml"]\n')
            with mock.patch.dict(os.environ, {"VENDOR_VIP_HOME": str(vendor)}):
                flow = self.load(root, overlay=overlay)
            self.assertEqual(flow.raw["build"]["sources"], [str(vendor / "vip_pkg.sv")])
            self.assertEqual(flow.raw["build"]["incdirs"], [str(vendor / "inc")])

    def test_checked_in_config_paths_stay_literal(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"VENDOR_VIP_HOME": "/opt/vip"}):
                flow = self.load(Path(tmp), '[build]\nincdirs = ["$VENDOR_VIP_HOME/include"]\n')
            self.assertEqual(flow.raw["build"]["incdirs"], ["$VENDOR_VIP_HOME/include"])


class GroupMemberValidation(unittest.TestCase):
    def test_local_members_pass(self):
        raw = inline_raw(SMOKE, [{"name": "t1", "run_modes": ["smoke"]}])
        raw["groups"] = [{"name": "g1", "tests": ["t1"]}]
        catalog = load_test_catalog(make_dut(raw), Path("."))
        self.assertEqual(catalog.groups["g1"], ["t1"])

    def test_missing_member_rejected_with_source_group_and_test(self):
        raw = inline_raw(SMOKE, [{"name": "t1", "run_modes": ["smoke"]}])
        raw["groups"] = [{"name": "g1", "tests": ["t1", "missing_test"]}]
        flow = make_dut(raw)
        with self.assertRaises(ConfigError) as ctx:
            load_test_catalog(flow, Path("."))
        message = str(ctx.exception)
        self.assertIn(str(flow.path), message)
        self.assertIn("g1", message)
        self.assertIn("missing_test", message)

    def test_group_may_reference_tests_from_included_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "leaf.toml").write_text(
                'schema_version = 1\n[[tests]]\nname = "t_leaf"\nrun_modes = ["smoke"]\n'
            )
            (root / "all.toml").write_text(
                'schema_version = 1\nincludes = ["leaf.toml"]\n'
                '[[groups]]\nname = "g_root"\ntests = ["t_leaf"]\n'
            )
            flow = make_dut({"run_modes": SMOKE, "testlist": {"path": str(root / "all.toml")}})
            catalog = load_test_catalog(flow, root)
            self.assertEqual(catalog.groups["g_root"], ["t_leaf"])

    def test_missing_member_in_included_group_names_that_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "leaf.toml").write_text(
                "schema_version = 1\n"
                '[[tests]]\nname = "t_leaf"\nrun_modes = ["smoke"]\n'
                '[[groups]]\nname = "g_leaf"\ntests = ["t_gone"]\n'
            )
            (root / "all.toml").write_text('schema_version = 1\nincludes = ["leaf.toml"]\n')
            flow = make_dut({"run_modes": SMOKE, "testlist": {"path": str(root / "all.toml")}})
            with self.assertRaises(ConfigError) as ctx:
                load_test_catalog(flow, root)
            message = str(ctx.exception)
            self.assertIn("leaf.toml", message)
            self.assertIn("g_leaf", message)
            self.assertIn("t_gone", message)

    def test_membership_in_multiple_groups_is_legal(self):
        raw = inline_raw(SMOKE, [{"name": "t1", "run_modes": ["smoke"]}])
        raw["groups"] = [
            {"name": "g1", "tests": ["t1"]},
            {"name": "g2", "tests": ["t1"]},
        ]
        catalog = load_test_catalog(make_dut(raw), Path("."))
        # Selecting both groups runs the shared member once (first-seen order).
        self.assertEqual(expand_items(catalog, ["g1", "g2"], True), ["t1"])


class ItemToolSelection(unittest.TestCase):
    """validate_item_tools: group selections drop, explicit --items errors."""

    def catalog(self):
        raw = inline_raw(
            SMOKE,
            [
                {"name": "t_any", "run_modes": ["smoke"]},
                {"name": "t_veri", "run_modes": ["smoke"], "tools": ["verilator"]},
            ],
        )
        return load_test_catalog(make_dut(raw), Path("."))

    def test_group_selection_drops_and_records(self):
        catalog = self.catalog()
        args = Namespace(items=None)
        kept = validate_item_tools(catalog, ["t_any", "t_veri"], "vcs", args)
        self.assertEqual(kept, ["t_any"])
        self.assertEqual(getattr(args, "_skipped_wrong_tool"), ["t_veri"])

    def test_explicitly_named_item_errors_instead(self):
        catalog = self.catalog()
        args = Namespace(items=["t_veri"])
        with self.assertRaises(ConfigError) as ctx:
            validate_item_tools(catalog, ["t_veri"], "vcs", args)
        message = str(ctx.exception)
        self.assertIn("t_veri", message)
        self.assertIn("vcs", message)
        self.assertIn("verilator", message)  # the tool it does run on

    def test_matching_tool_keeps_everything(self):
        catalog = self.catalog()
        args = Namespace(items=None)
        kept = validate_item_tools(catalog, ["t_any", "t_veri"], "verilator", args)
        self.assertEqual(kept, ["t_any", "t_veri"])
        self.assertIsNone(getattr(args, "_skipped_wrong_tool", None))

    def test_empty_result_is_an_error_not_a_vacuous_pass(self):
        catalog = self.catalog()
        args = Namespace(items=None)
        with self.assertRaises(ConfigError) as ctx:
            validate_item_tools(catalog, ["t_veri"], "vcs", args)
        self.assertIn("no selected scenario", str(ctx.exception))


class RuntimeSelectionDefenses(unittest.TestCase):
    # Directly constructed catalogs bypass load_test_catalog; selection must
    # still fail with ConfigError, never a raw KeyError.
    def test_expand_items_rejects_phantom_group_member(self):
        catalog = TestCatalog(None, {}, {"smoke": ["missing_test"]})
        with self.assertRaises(ConfigError) as ctx:
            expand_items(catalog, ["smoke"], True)
        self.assertIn("missing_test", str(ctx.exception))

    def test_target_plan_rejects_unknown_item(self):
        catalog = TestCatalog(None, {}, {})
        with self.assertRaises(ConfigError) as ctx:
            target_plan(catalog, {}, ["missing_test"], tool="vcs")
        self.assertIn("missing_test", str(ctx.exception))

    def test_force_target_wins_over_test_target(self):
        catalog = TestCatalog(
            None,
            {
                "t_stub": TestEntry(name="t_stub", module="m", target="lsu_stub_all_live"),
                "t_cpu": TestEntry(name="t_cpu", module="m"),
            },
            {},
        )
        sim_cfg = {
            "defaults": {"target": "default"},
            "targets": {
                "default": {"build_dir": "build/default"},
                "lsu_stub_all_live": {"build_dir": "build/stub"},
            },
        }
        plan = target_plan(catalog, sim_cfg, ["t_stub", "t_cpu"], force="default", tool="vcs")
        self.assertEqual(
            plan.target_by_item, {"t_stub@default": "default", "t_cpu@default": "default"}
        )
        self.assertEqual(plan.targets, ["default"])

    def test_unknown_force_target_is_rejected(self):
        catalog = TestCatalog(
            None,
            {"t1": TestEntry(name="t1", module="m", target="default")},
            {},
        )
        sim_cfg = {"targets": {"default": {"build_dir": "build/default"}}}
        plan = target_plan(catalog, sim_cfg, ["t1"], force="nope", tool="vcs")
        with self.assertRaises(ConfigError) as ctx:
            validate_target_plan(sim_cfg, plan.targets)
        self.assertIn("nope", str(ctx.exception))


class TargetRunOn(unittest.TestCase):
    """`[targets.<name>.tools.<tool>].run_on` runs a target's tests on another target."""

    CATALOG = TestCatalog(
        None,
        {
            "t_stub": TestEntry(name="t_stub", module="m", target="stub"),
            "t_cpu": TestEntry(name="t_cpu", module="m"),
        },
        {},
    )

    def sim_cfg(self, **tools: dict) -> dict:
        """`default`, `stub` and `other` targets, with ``tools`` tables keyed by target name."""
        targets = {name: {"build_dir": f"build/{name}"} for name in ("default", "stub", "other")}
        for name, table in tools.items():
            targets[name]["tools"] = table
        return {"defaults": {"target": "default"}, "targets": targets}

    def plan(self, sim_cfg: dict, tool: str, *targets: str, **kwargs) -> tuple[dict, list]:
        plan = target_plan(
            self.CATALOG, sim_cfg, ["t_stub", "t_cpu"], list(targets), tool=tool, **kwargs
        )
        return plan.target_by_item, plan.targets

    def test_a_target_runs_its_tests_on_the_target_run_on_names_for_that_tool(self):
        sim_cfg = self.sim_cfg(stub={"vcs": {"run_on": "default"}})
        self.assertEqual(
            self.plan(sim_cfg, "vcs"),
            ({"t_stub@default": "default", "t_cpu@default": "default"}, ["default"]),
        )
        self.assertEqual(
            self.plan(sim_cfg, "verilator"),
            ({"t_stub@stub": "stub", "t_cpu@default": "default"}, ["stub", "default"]),
        )

    def test_a_listed_target_overrides_the_redirect_and_force_target_overrides_both(self):
        sim_cfg = self.sim_cfg(stub={"vcs": {"run_on": "default"}})
        self.assertEqual(
            self.plan(sim_cfg, "vcs", "stub"),
            ({"t_stub@stub": "stub", "t_cpu@stub": "stub"}, ["stub"]),
        )
        self.assertEqual(
            self.plan(sim_cfg, "vcs", force="other"),
            ({"t_stub@other": "other", "t_cpu@other": "other"}, ["other"]),
        )

    def test_the_default_target_redirects_unpinned_tests_and_an_itemless_plan(self):
        sim_cfg = self.sim_cfg(default={"verilator": {"run_on": "stub"}})
        self.assertEqual(
            self.plan(sim_cfg, "verilator"),
            ({"t_stub@stub": "stub", "t_cpu@stub": "stub"}, ["stub"]),
        )
        self.assertEqual(target_plan(self.CATALOG, sim_cfg, [], tool="verilator").targets, ["stub"])

    def test_a_redirect_must_name_another_defined_target_that_does_not_redirect(self):
        for tools, error in (
            (
                {"stub": {"vcs": {"run_on": " "}}},
                r"targets\.stub\.tools\.vcs\.run_on must be a target name",
            ),
            (
                {"stub": {"vcs": {"run_on": "stub"}}},
                r"targets\.stub\.tools\.vcs\.run_on names its own",
            ),
            (
                {"stub": {"vcs": {"run_on": "nope"}}},
                r"names `nope`, which is not defined in \[targets\]",
            ),
            (
                {"stub": {"vcs": {"run_on": "other"}}, "other": {"vcs": {"run_on": "default"}}},
                r"names `other`, which redirects its own tests on vcs",
            ),
            (
                {"stub": {"vcs": {"run_on": "other"}}, "other": {"vcs": {"run_on": "stub"}}},
                r"names `other`, which redirects its own tests on vcs",
            ),
        ):
            with self.subTest(tools=tools), self.assertRaisesRegex(ConfigError, error):
                self.plan(self.sim_cfg(**tools), "vcs")

    def test_validation_resolves_every_redirect_on_each_of_the_tools(self):
        sim_cfg = self.sim_cfg(other={"vcs": {"run_on": "nope"}})
        validate_target_redirects(sim_cfg, ["verilator"])
        with self.assertRaisesRegex(
            ConfigError, r"targets\.other\.tools\.vcs\.run_on names `nope`"
        ):
            validate_target_redirects(sim_cfg, ["verilator", "vcs"])
        validate_target_redirects(self.sim_cfg(stub={"vcs": {"run_on": "default"}}), ["vcs"])

    def test_target_defaults_refuse_run_on(self):
        target = {"build_dir": "build/stub", "tools": {"vcs": {"run_on": "default"}}}
        validate_native_config_shape(make_dut({"targets": {"stub": target}}), Path("."))
        with self.assertRaisesRegex(ConfigError, r"unsupported key\(s\): run_on"):
            validate_native_config_shape(make_dut({"target_defaults": {"stub": target}}), Path("."))


class TargetLists(unittest.TestCase):
    """`--target A,B` runs each selected test on every listed target it can run on."""

    CATALOG = TestCatalog(
        None,
        {
            "t_stub": TestEntry(name="t_stub", module="m", target="stub"),
            "t_other": TestEntry(name="t_other", module="m", target="other"),
            "t_cpu": TestEntry(name="t_cpu", module="m"),
        },
        {},
    )
    SIM_CFG = {
        "defaults": {"target": "default"},
        "targets": {
            "default": {"build_dir": "build/default"},
            "stub": {"build_dir": "build/stub", "tools": {"vcs": {"run_on": "default"}}},
            "other": {"build_dir": "build/other"},
        },
    }

    def plan(self, items: list[str], targets: list[str], tool: str = "verilator", **kwargs):
        return target_plan(self.CATALOG, self.SIM_CFG, items, targets, tool=tool, **kwargs)

    def test_an_unpinned_test_runs_on_every_listed_target_under_a_name_for_each(self):
        plan = self.plan(["t_stub", "t_cpu"], ["default", "stub"])
        self.assertEqual(plan.groups, [["t_stub@stub"], ["t_cpu@default", "t_cpu@stub"]])
        self.assertEqual(plan.items, ["t_stub@stub", "t_cpu@default", "t_cpu@stub"])
        self.assertEqual(plan.targets, ["stub", "default"])
        self.assertEqual(
            plan.instances,
            {"t_stub@stub": "stub", "t_cpu@default": "default", "t_cpu@stub": "stub"},
        )
        self.assertEqual(plan.skipped, [])

    def test_every_leaf_is_named_after_its_target_unless_the_flow_has_none(self):
        for targets, force, named in (
            ([], None, {"t_cpu@default": "default", "t_stub@default": "default"}),
            (["stub"], None, {"t_cpu@stub": "stub", "t_stub@stub": "stub"}),
            ([], "other", {"t_cpu@other": "other", "t_stub@other": "other"}),
        ):
            with self.subTest(targets=targets, force=force):
                plan = self.plan(["t_cpu", "t_stub"], targets, tool="vcs", force=force)
                self.assertEqual(plan.target_by_item, named)
                self.assertEqual(plan.instances, named)
        plain = self.plan(["t_cpu", "t_stub"], [], tool="vcs", by_target=False)
        self.assertEqual(plain.target_by_item, {"t_cpu": "default", "t_stub": "default"})
        self.assertEqual(plain.instances, {})

    def test_a_pinned_only_target_runs_only_the_tests_that_reach_it(self):
        sim_cfg = {
            **self.SIM_CFG,
            "targets": {
                **self.SIM_CFG["targets"],
                "stub": {"build_dir": "build/stub", "pinned_only": True},
            },
        }

        def plan(items, targets, **kwargs):
            return target_plan(self.CATALOG, sim_cfg, items, targets, tool="verilator", **kwargs)

        both = plan(["t_stub", "t_cpu"], ["default", "stub"])
        self.assertEqual(both.target_by_item, {"t_stub@stub": "stub", "t_cpu@default": "default"})
        stub_only = plan(["t_stub", "t_cpu"], ["stub"])
        self.assertEqual(stub_only.target_by_item, {"t_stub@stub": "stub"})
        self.assertEqual(stub_only.skipped, [{"name": "t_cpu", "target": "default"}])
        self.assertEqual(plan(["t_cpu"], [], force="stub").target_by_item, {"t_cpu@stub": "stub"})

    def test_pinned_only_is_a_flag_of_one_target_and_not_of_the_default(self):
        validate_native_config_shape(
            make_dut({"targets": {"stub": {"build_dir": "b", "pinned_only": True}}}), Path(".")
        )
        for raw, error in (
            ({"targets": {"stub": {"build_dir": "b", "pinned_only": "yes"}}}, "true or false"),
            (
                {"target_defaults": {"default": {"pinned_only": True}}},
                r"unsupported key\(s\): pinned_only",
            ),
        ):
            with self.subTest(raw=raw), self.assertRaisesRegex(ConfigError, error):
                validate_native_config_shape(make_dut(raw), Path("."))
        sim_cfg = {"targets": {"default": {"build_dir": "b", "pinned_only": True}}}
        with self.assertRaisesRegex(
            ConfigError, r"`default` runs the tests that name no target on vcs"
        ):
            validate_target_redirects(sim_cfg, ["vcs"])

    def test_a_pinned_test_runs_only_where_its_target_or_its_redirect_is_listed(self):
        plan = self.plan(["t_stub", "t_other", "t_cpu"], ["default"], tool="vcs")
        self.assertEqual(
            plan.target_by_item, {"t_stub@default": "default", "t_cpu@default": "default"}
        )
        self.assertEqual(plan.skipped, [{"name": "t_other", "target": "other"}])
        plan = self.plan(["t_stub", "t_cpu"], ["default"])
        self.assertEqual(plan.target_by_item, {"t_cpu@default": "default"})
        self.assertEqual(plan.skipped, [{"name": "t_stub", "target": "stub"}])

    def test_a_list_that_runs_none_of_the_selected_tests_is_refused(self):
        with self.assertRaisesRegex(
            ConfigError,
            r"no selected test runs on --target default: each names another target"
            r" \(other, stub\)",
        ):
            self.plan(["t_stub", "t_other"], ["default"])

    def test_a_plan_without_tests_plans_the_listed_or_the_forced_targets(self):
        self.assertEqual(self.plan([], ["stub", "other"]).targets, ["stub", "other"])
        self.assertEqual(self.plan([], [], force="other").targets, ["other"])
        self.assertEqual(self.plan([], []).targets, ["default"])

    def test_the_option_names_each_listed_target_once(self):
        self.assertEqual(requested_targets(" a, b,,a "), ["a", "b"])
        self.assertEqual(requested_targets(None), [])

    def test_a_name_for_one_of_several_targets_is_its_test_pinned_to_that_target(self):
        catalog = with_target_instances(self.CATALOG, {"t_cpu@stub": "stub"})
        entry = catalog.tests["t_cpu@stub"]
        self.assertEqual((entry.name, entry.module, entry.target), ("t_cpu", "m", "stub"))
        self.assertIsNone(catalog.tests["t_cpu"].target)
        with self.assertRaisesRegex(ConfigError, "`nope@stub` names no test"):
            with_target_instances(self.CATALOG, {"nope@stub": "stub"})

    def test_a_rerun_selects_the_test_and_the_target_its_leaf_ran_on(self):
        def args(target=None, force_target=None):
            return Namespace(target=target, force_target=force_target)

        self.assertEqual(
            rerun_selection("t_cpu@stub", "stub", args("default,stub")),
            ["--items", "t_cpu", "--target", "stub"],
        )
        self.assertEqual(rerun_selection("t_cpu", "default", args()), ["--items", "t_cpu"])
        self.assertEqual(
            rerun_selection("t_stub", "stub", args("stub")),
            ["--items", "t_stub", "--target", "stub"],
        )
        self.assertEqual(
            rerun_selection("t_stub", "other", args(force_target="other")),
            ["--items", "t_stub", "--force-target", "other"],
        )

    def test_test_and_target_names_cannot_contain_the_separator(self):
        with self.assertRaisesRegex(ConfigError, r"test name `t@a` contains `@`"):
            load_test_catalog(make_dut(inline_raw(SMOKE, [{"name": "t@a"}])), Path("."))
        with self.assertRaisesRegex(ConfigError, r"target name `a@b` contains `@`"):
            validate_native_config_shape(
                make_dut({"targets": {"a@b": {"build_dir": "build"}}}), Path(".")
            )


class RegressionReseedCount(unittest.TestCase):
    """`--reseed` sets every selected test's seed count; a testlist `reseed` is the default."""

    CATALOG = TestCatalog(
        None,
        {
            "pinned_test": TestEntry(name="pinned_test", module="m", reseed=10),
            "pinned_once_test": TestEntry(name="pinned_once_test", module="m", reseed=1),
            "unpinned_test": TestEntry(name="unpinned_test", module="m"),
        },
        {},
    )

    def count(self, item: str, reseed: int | None) -> int:
        return regression_reseed_count(self.CATALOG, Namespace(reseed=reseed), item)

    def test_testlist_count_applies_without_reseed(self):
        self.assertEqual(self.count("pinned_test", None), 10)
        self.assertEqual(self.count("unpinned_test", None), 1)

    def test_reseed_overrides_a_testlist_count_down_and_up(self):
        self.assertEqual(self.count("pinned_test", 1), 1)
        self.assertEqual(self.count("pinned_once_test", 3), 3)
        self.assertEqual(self.count("unpinned_test", 3), 3)

    def test_testlist_count_below_one_names_the_test(self):
        catalog = TestCatalog(
            None, {"zero_test": TestEntry(name="zero_test", module="m", reseed=0)}, {}
        )
        with self.assertRaises(ConfigError) as ctx:
            regression_reseed_count(catalog, Namespace(reseed=None), "zero_test")
        self.assertIn("zero_test", str(ctx.exception))


class TargetFlagsTokens(unittest.TestCase):
    """Every flag item is one argv token; an embedded space is a config error, not a no-op."""

    def test_shared_then_tool_flags(self):
        target = {"flags": ["+define+X"], "tools": {"vcs": {"flags": ["-assert", "svaext"]}}}
        self.assertEqual(target_flags(target, "vcs"), ["+define+X", "-assert", "svaext"])

    def test_whitespace_in_a_flag_is_rejected(self):
        target = {"tools": {"vcs": {"flags": ["-assert svaext"]}}}
        with self.assertRaises(ConfigError) as ctx:
            target_flags(target, "vcs")
        self.assertIn("-assert svaext", str(ctx.exception))


class DutRegistryAliases(unittest.TestCase):
    """`alias_of` gives one DUT a second selectable name (see runlib.duts)."""

    def _registry(self, body: str) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg_dir = root / "hw" / "common" / "dv" / "configs"
            cfg_dir.mkdir(parents=True)
            (cfg_dir / "duts.toml").write_text(body)
            return load_dut_registry(root)

    def test_alias_entry_is_accepted(self):
        reg = self._registry(
            "schema_version = 1\n"
            '[duts.widget]\nroot = "hw/sys/widget/dv"\n'
            '[duts.widget_alt]\nroot = "hw/sys/widget/dv"\nalias_of = "widget"\n'
        )
        self.assertEqual(reg["widget_alt"]["alias_of"], "widget")
        self.assertNotIn("alias_of", reg["widget"])

    def test_self_alias_is_rejected(self):
        with self.assertRaises(ConfigError) as ctx:
            self._registry(
                "schema_version = 1\n"
                '[duts.widget]\nroot = "hw/sys/widget/dv"\nalias_of = "widget"\n'
            )
        self.assertIn("cannot point at itself", str(ctx.exception))

    def test_alias_chain_is_rejected(self):
        with self.assertRaises(ConfigError) as ctx:
            self._registry(
                "schema_version = 1\n"
                '[duts.a]\nroot = "hw/sys/a/dv"\n'
                '[duts.b]\nroot = "hw/sys/a/dv"\nalias_of = "a"\n'
                '[duts.c]\nroot = "hw/sys/a/dv"\nalias_of = "b"\n'
            )
        self.assertIn("itself an alias", str(ctx.exception))

    def test_empty_alias_is_rejected(self):
        with self.assertRaises(ConfigError) as ctx:
            self._registry(
                'schema_version = 1\n[duts.widget]\nroot = "hw/sys/widget/dv"\nalias_of = ""\n'
            )
        self.assertIn("non-empty string", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
