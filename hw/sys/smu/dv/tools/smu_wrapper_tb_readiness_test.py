#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Fast source/filelist/artifact readiness gate for the SMU wrapper OSS flow."""

from __future__ import annotations

import argparse
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path


DV_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = DV_ROOT.parents[5]
OSS_DV_TOOLS = REPO_ROOT / "dv" / "oss" / "tools" / "dv"

if str(OSS_DV_TOOLS) not in sys.path:
    sys.path.insert(0, str(OSS_DV_TOOLS))

from check_no_vendor_paths import (  # noqa: E402
    _check_tokens,
    _collect_filelist_paths,
    _load_config,
)


SIM_CFG = "smu_wrapper_sim_cfg.toml"
CATALOG = "testlists/wrapper.toml"
TARGET_NO_SEP = "compile_smu_chiplet_no_sep"
TARGET_SEP_RTL = "compile_smu_chiplet_sep_rtl"
SMOKE_TESTS = {
    "smu_wrapper_elaboration_no_sep_test": TARGET_NO_SEP,
    "smu_wrapper_elaboration_sep_rtl_test": TARGET_SEP_RTL,
    "smu_smc_smoke_test": TARGET_NO_SEP,
    "smu_sep_smoke_test": TARGET_SEP_RTL,
}

REQUIRED_SOURCES = (
    SIM_CFG,
    "tb/tb_wrapper_top.sv",
    "tb/smu_wrapper_public_scope.vlt",
    "shims/bus/tb_smu_axi_responder.sv",
    "shims/mem/sep_tcm_wrapper.sv",
    "shims/wrapper/smu_wrapper.sv",
    "shims/wrapper/smc_padring_ext.sv",
    "fw/build_firmware.py",
    "fw/tests/smu_smc_smoke/main.c",
    "fw/tests/smu_sep_arm/main.c",
    "fw/tests/smu_sep_smoke/main.c",
    "cocotb_wrapper/tests/smu_base_test.py",
    "cocotb_wrapper/tests/smu_wrapper_elaboration_test.py",
    "cocotb_wrapper/tests/smu_smc_smoke_test.py",
    "cocotb_wrapper/tests/smu_sep_smoke_test.py",
    "cocotb_wrapper/seq_lib/smu_wrapper_elaboration_seq.py",
    "cocotb_wrapper/seq_lib/smu_smc_smoke_seq.py",
    "cocotb_wrapper/seq_lib/smu_sep_smoke_seq.py",
    "cocotb_wrapper/env/smu_env_cfg.py",
    "cocotb_wrapper/env/smu_boot_scoreboard.py",
    CATALOG,
)

REQUIRED_REFERENCE_ROOTS = (
    "hw/sys/smc/dv",
    "hw/sys/sep/dv",
    "hw/common/dv/vip",
    "hw/.bos/wrapper/smu",
)

FORBIDDEN_ENV_REFERENCES = (
    "dv/smu/tb/tb_uvm",
    "testlist_smu_chiplet.yaml",
    "project_smu_chiplet.yaml",
)


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


class Readiness:
    """Collect readiness checks and print a stable CI-friendly report."""

    def __init__(self) -> None:
        self.checks: list[Check] = []

    def record(self, name: str, passed: bool, detail: str) -> None:
        self.checks.append(Check(name=name, passed=passed, detail=detail))

    def require_file(self, relative: str) -> None:
        path = DV_ROOT / relative
        self.record(
            f"source:{relative}",
            path.is_file(),
            str(path) if path.is_file() else "missing",
        )

    def report(self) -> int:
        for check in self.checks:
            status = "PASS" if check.passed else "FAIL"
            print(f"{status}: {check.name}: {check.detail}")
        failures = [check for check in self.checks if not check.passed]
        print(
            f"SMU WRAPPER OSS TB READINESS: {'PASS' if not failures else 'FAIL'} "
            f"({len(self.checks) - len(failures)}/{len(self.checks)} checks)"
        )
        return 0 if not failures else 1


def _read_toml(path: Path) -> dict:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def _load_catalog(root: Path) -> tuple[dict[str, dict], dict[str, list[str]]]:
    root_data = _read_toml(root)
    tests: dict[str, dict] = {}
    groups: dict[str, list[str]] = {}
    for include in root_data.get("includes", []):
        leaf = _read_toml(root.parent / include)
        for test in leaf.get("tests", []):
            tests[str(test["name"])] = test
        for group in leaf.get("groups", []):
            groups[str(group["name"])] = list(group.get("tests", []))
    for test in root_data.get("tests", []):
        tests[str(test["name"])] = test
    for group in root_data.get("groups", []):
        groups[str(group["name"])] = list(group.get("tests", []))
    return tests, groups


def check_sources(result: Readiness) -> None:
    """Verify that every authored source and config contract is present."""
    for relative in REQUIRED_SOURCES:
        result.require_file(relative)

    for relative in REQUIRED_REFERENCE_ROOTS:
        path = REPO_ROOT / relative
        result.record(
            f"reference:{relative}",
            path.is_dir(),
            "available" if path.is_dir() else "missing",
        )

    config_path = DV_ROOT / SIM_CFG
    if not config_path.is_file():
        return
    config = _read_toml(config_path)
    targets = config.get("targets", {})
    for target in (TARGET_NO_SEP, TARGET_SEP_RTL):
        result.record(
            f"target:{target}",
            target in targets,
            "defined" if target in targets else f"missing from {SIM_CFG}",
        )

    bender_targets = [
        str(value) for value in config.get("build", {}).get("bender_targets", [])
    ]
    result.record(
        "dut:smu_oss_wrapper_bender_target",
        "smu_oss_wrapper" in bender_targets,
        "selected" if "smu_oss_wrapper" in bender_targets else "not selected",
    )

    catalog_path = DV_ROOT / CATALOG
    if catalog_path.is_file():
        tests, groups = _load_catalog(catalog_path)
        for test_name, target in SMOKE_TESTS.items():
            test = tests.get(test_name)
            passed = test is not None and test.get("target") == target
            detail = (
                f"target={test.get('target')}"
                if test is not None
                else "missing from catalog"
            )
            result.record(f"catalog:{test_name}", passed, detail)
        expected_group = set(SMOKE_TESTS)
        smoke_group = set(groups.get("smoke", []))
        result.record(
            "catalog:smoke_group",
            smoke_group == expected_group,
            f"tests={sorted(smoke_group)}",
        )

    authored = (
        config_path,
        DV_ROOT / CATALOG,
        DV_ROOT / "tb" / "tb_wrapper_top.sv",
    )
    bad_refs: list[str] = []
    for path in authored:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for forbidden in FORBIDDEN_ENV_REFERENCES:
            if forbidden in text:
                bad_refs.append(f"{path.relative_to(REPO_ROOT)} -> {forbidden}")
    result.record(
        "isolation:no_legacy_tb_dependency",
        not bad_refs,
        "clean" if not bad_refs else "; ".join(bad_refs),
    )


def check_filelists(result: Readiness, filelists: list[Path]) -> None:
    """Verify generated filelists contain the OSS DUT and no vendor paths."""
    forbidden, allowed, extensions = _load_config(
        OSS_DV_TOOLS / "check_no_vendor_paths.yaml",
        None,
    )
    required_tokens = (
        "hw/smu/rtl/smu.sv",
        "hw/.bos/wrapper/smc/smc_ip_integration.sv",
        "hw/.bos/wrapper/sep/sep_ip_integration.sv",
        "hw/sys/smu/dv/tb/tb_wrapper_top.sv",
        "hw/sys/smu/dv/shims/mem/sep_tcm_wrapper.sv",
        # DV shadow of the OSS wrapper (duplicate rst_cold_n declaration fix).
        "hw/sys/smu/dv/shims/wrapper/smu_wrapper.sv",
    )
    forbidden_tokens = (
        # Production wrapper and foundry TCM macros must not leak into the
        # OSS wrapper build (Bender not(smu_oss_wrapper) + exclude_files),
        # and the hw/.bos wrapper copy is shadowed by the DV shim.
        "hw/smu/smu_wrappers/rtl/smu_wrapper.sv",
        "hw/sep/sep_tcm_wrapper.sv",
        "hw/.bos/wrapper/smu/smu_wrapper.sv",
        "hw/.bos/wrapper/smc/smc_padring_ext.sv",
    )
    for raw_path in filelists:
        path = raw_path if raw_path.is_absolute() else REPO_ROOT / raw_path
        label = str(path)
        exists = path.is_file() and path.stat().st_size > 0
        result.record(
            f"filelist:{label}:nonempty",
            exists,
            "present" if exists else "missing/empty",
        )
        if not exists:
            continue
        tokens = _collect_filelist_paths(path, extensions)
        text = "\n".join(path_token for path_token, _source, _line in tokens)
        for token in required_tokens:
            result.record(
                f"filelist:{label}:{token}",
                token in text,
                "present" if token in text else "missing",
            )
        for token in forbidden_tokens:
            result.record(
                f"filelist:{label}:excludes:{token}",
                token not in text,
                "absent" if token not in text else "unexpectedly present",
            )
        violations = _check_tokens(tokens, forbidden, allowed)
        detail = (
            "vendor-free" if not violations else ", ".join(v.path for v in violations)
        )
        result.record(f"filelist:{label}:vendor_free", not violations, detail)


def check_artifacts(result: Readiness, tests: list[str]) -> None:
    """Verify firmware outputs declared by the test catalog and sim config."""
    config_path = DV_ROOT / SIM_CFG
    catalog_path = DV_ROOT / CATALOG
    if not config_path.is_file() or not catalog_path.is_file():
        result.record("artifacts:config", False, "missing sim config or test catalog")
        return
    config = _read_toml(config_path)
    catalog, _groups = _load_catalog(catalog_path)
    selected = tests or sorted(
        name for name, entry in catalog.items() if entry.get("firmware") is not None
    )
    for test_name in selected:
        test = catalog.get(test_name)
        if not isinstance(test, dict):
            result.record(f"artifacts:{test_name}", False, "missing test entry")
            continue
        firmware = test.get("firmware")
        if isinstance(firmware, dict):
            mode = str(firmware.get("mode", "default"))
            fw_target = str(firmware.get("name", test_name))
        elif isinstance(firmware, str):
            mode = "default"
            fw_target = firmware
        else:
            result.record(f"artifacts:{test_name}", False, "missing firmware mapping")
            continue
        c_build = config.get("c_build", {}).get(mode)
        if not isinstance(c_build, dict):
            result.record(
                f"artifacts:{test_name}",
                False,
                f"missing c_build.{mode}",
            )
            continue
        outputs = c_build.get("outputs", [])
        for raw_output in outputs:
            relative = str(raw_output).replace("{fw_target}", fw_target)
            path = REPO_ROOT / str(relative)
            allow_empty = path.name == "smu_sep_smoke.dtcm.hex"
            passed = path.is_file() and (allow_empty or path.stat().st_size > 0)
            expected = "present" if allow_empty else "present/nonempty"
            result.record(
                f"artifact:{test_name}:{relative}",
                passed,
                expected if passed else "missing/empty",
            )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        choices=("source", "filelist", "artifacts", "generated", "all"),
        default="source",
        help="Readiness phase to check",
    )
    parser.add_argument(
        "--filelist",
        action="append",
        type=Path,
        default=[],
        help="Generated final filelist to inspect; repeat for both targets",
    )
    parser.add_argument(
        "--test",
        action="append",
        default=[],
        help="Catalog test whose c_build outputs are checked; defaults to all firmware tests",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = Readiness()
    if args.phase in ("source", "all"):
        check_sources(result)
    if args.phase in ("filelist", "generated", "all"):
        if not args.filelist:
            result.record("filelist:argument", False, "--filelist is required")
        else:
            check_filelists(result, args.filelist)
    if args.phase in ("artifacts", "generated", "all"):
        check_artifacts(result, args.test)
    return result.report()


if __name__ == "__main__":
    raise SystemExit(main())
