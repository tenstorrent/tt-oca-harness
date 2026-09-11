# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for runlib.config run-mode / overlay validation and runlib.duts resolution.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib.cli import (  # noqa: E402
    expand_items,
    target_plan,
    validate_item_tools,
    validate_target_plan,
)
from runlib.config import (  # noqa: E402
    OverlayFrameworkMismatch,
    _merge_framework_config,
    apply_adopter_overlay,
    load_dut,
    load_test_catalog,
    selected_run_mode,
    target_flags,
    validate_run_mode_request,
)
from runlib.duts import load_dut_registry  # noqa: E402
from runlib.models import ConfigError, Dut, TestCatalog, TestEntry  # noqa: E402


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
        # A framework view that never runs the scenario has no business rejecting the
        # tools it would need -- and a framework overlay may declare a narrower tool list
        # than the scenario names. This is the sep (uvm) view over a cocotb-only test.
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
            '[target_defaults.default.tools.vcs]\nflags = ["-ntb_opts", "svt"]\n',
        )
        target = data["target_defaults"]["default"]
        self.assertEqual(target["defines"], ["UVM", "OCAH_JTAG_VENDOR_IF"])
        self.assertEqual(target["tools"]["vcs"]["flags"], ["-x", "-ntb_opts", "svt"])

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
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConfigError) as ctx:
                self.load(Path(tmp), 'adopter_overlay = "sneaky.toml"\n')
            self.assertIn("--overlay", str(ctx.exception))

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
    # still fail with ConfigError, never a raw KeyError (the #431 reproduce).
    def test_expand_items_rejects_phantom_group_member(self):
        catalog = TestCatalog(None, {}, {"smoke": ["missing_test"]})
        with self.assertRaises(ConfigError) as ctx:
            expand_items(catalog, ["smoke"], True)
        self.assertIn("missing_test", str(ctx.exception))

    def test_target_plan_rejects_unknown_item(self):
        catalog = TestCatalog(None, {}, {})
        with self.assertRaises(ConfigError) as ctx:
            target_plan(catalog, {}, ["missing_test"])
        self.assertIn("missing_test", str(ctx.exception))

    def test_target_override_wins_over_test_target(self):
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
        by_item, ordered = target_plan(catalog, sim_cfg, ["t_stub", "t_cpu"], override="default")
        self.assertEqual(by_item, {"t_stub": "default", "t_cpu": "default"})
        self.assertEqual(ordered, ["default"])

    def test_unknown_target_override_is_rejected(self):
        catalog = TestCatalog(
            None,
            {"t1": TestEntry(name="t1", module="m", target="default")},
            {},
        )
        sim_cfg = {"targets": {"default": {"build_dir": "build/default"}}}
        _by_item, ordered = target_plan(catalog, sim_cfg, ["t1"], override="nope")
        with self.assertRaises(ConfigError) as ctx:
            validate_target_plan(sim_cfg, ordered)
        self.assertIn("nope", str(ctx.exception))


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
