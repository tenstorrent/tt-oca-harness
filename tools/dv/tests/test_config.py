# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for runlib.config run-mode reference validation and the adopter overlay layer.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib.cli import expand_items, target_plan, validate_coverage_tool  # noqa: E402
from runlib.config import (  # noqa: E402
    OverlayFrameworkMismatch,
    _merge_framework_config,
    apply_adopter_overlay,
    load_dut,
    load_test_catalog,
    selected_run_mode,
    validate_native_config_shape,
    validate_run_mode_request,
)
from runlib.models import ConfigError, Dut, TestCatalog  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()


class CoverageToolAllowlist(unittest.TestCase):
    """`[coverage].tools` narrows which simulators `--cov` may be requested on."""

    # `Flow` is an alias of `Dut`; the guard only reads `.path` for the message.
    flow = make_dut({})

    @staticmethod
    def args(cov: bool = True) -> Namespace:
        return Namespace(cov=cov)

    def test_disallowed_tool_is_a_config_error(self):
        cfg = {"coverage": {"tools": ["vcs"], "vcs": {}, "verilator": {}}}
        with self.assertRaises(ConfigError) as ctx:
            validate_coverage_tool(cfg, "verilator", self.args(), self.flow)
        # The message has to name the fix, not just the refusal: the whole point is
        # that the verilator run would otherwise have produced a plausible number.
        self.assertIn("--tool vcs", str(ctx.exception))

    def test_allowed_tool_passes(self):
        cfg = {"coverage": {"tools": ["vcs"], "vcs": {}}}
        validate_coverage_tool(cfg, "vcs", self.args(), self.flow)

    def test_no_allowlist_leaves_every_backend_open(self):
        cfg = {"coverage": {"vcs": {}, "verilator": {}}}
        validate_coverage_tool(cfg, "verilator", self.args(), self.flow)

    def test_guard_is_inert_without_cov(self):
        # A non-coverage run on verilator stays legal under a VCS-only allowlist;
        # the allowlist constrains coverage, not simulation.
        cfg = {"coverage": {"tools": ["vcs"]}}
        validate_coverage_tool(cfg, "verilator", self.args(cov=False), self.flow)

    def test_padded_entry_still_matches_the_tool(self):
        # A stray space in the TOML must not silently match nothing and block every
        # --cov run; the entry is stripped on read.
        cfg = {"coverage": {"tools": [" vcs "], "vcs": {}}}
        validate_coverage_tool(cfg, "vcs", self.args(), self.flow)

    def test_malformed_allowlist_is_rejected(self):
        for bad in ([], "vcs", [""], ["   "], [1]):
            with self.subTest(bad=bad):
                dut = make_dut({"coverage": {"tools": bad}})
                with self.assertRaises(ConfigError):
                    validate_native_config_shape(dut, Path("."))

    def test_reserved_key_is_not_read_as_a_backend_table(self):
        # Before `tools` was reserved, a non-table key under [coverage] tripped the
        # "[coverage.<tool>] must be a table" check.
        dut = make_dut({"coverage": {"tools": ["vcs"], "vcs": {}}})
        validate_native_config_shape(dut, Path("."))


class SepCoverageIsVcsOnly(unittest.TestCase):
    """The shipped SEP config declares the VCS-only coverage policy."""

    def test_sep_cfg_allows_vcs_only(self):
        import tomllib

        path = Path(__file__).resolve().parents[3] / "hw/sys/sep/dv/sep_sim_cfg.toml"
        cfg = tomllib.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(cfg["coverage"]["tools"], ["vcs"])
        # The scope file is what makes VCS the only backend whose number is scoped.
        self.assertTrue(cfg["coverage"]["vcs"]["scope_file"])
