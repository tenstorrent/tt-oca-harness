# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared PyUVM base test for SMC OSS (`--dut smc`).

Builds `SmcEnv`, runs power-good + cold-reset bring-up, and delegates scenario
work to `run_scenario()`.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
import shlex
import subprocess
import sys
import tomllib
from datetime import date, datetime, timezone
from pathlib import Path
from typing import NoReturn

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles
from pyuvm import ConfigDB, uvm_test

_COCOTB_ROOT = Path(__file__).resolve().parents[1]
_OSS_HW_ROOT = Path(__file__).resolve().parents[5]
for _path in (_COCOTB_ROOT, _OSS_HW_ROOT / "common" / "dv" / "vip"):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.insert(0, _path_str)

from env.smc_env import SmcEnv
from env.smc_env_cfg import SYS_OUT_AXI_GEOMETRY, SYS_OUT_MEM_SIZE, SmcEnvCfg
from env.smc_probe_liveness import reset_probe_ledger, watch_probe_liveness
from env.smc_protocol_vip_item import SmcProtocolVipItem, SmcProtocolVipKind
from env.smc_virt_console import VirtConsole
from ocah_axi_vip import OcahAxiSlaveAgent
from seq_lib._one_shot import _OneShot

# Test-class-name -> protocol VIP kind for the auto-record at the end of
# run_phase. A test may instead set the ``protocol_vip_kind`` class attribute
# (see smc_base_test.run_phase), which keeps the kind next to the test; a typo
# in this map silently skips the auto-record.
_PROTOCOL_VIP_TESTS = {
    "smc_i2c_master_target_test": SmcProtocolVipKind.I2C,
    "smc_i2c_p1_rdwr_protocol_test": SmcProtocolVipKind.I2C,
    "smc_i2c_error_fifo_depth_test": SmcProtocolVipKind.I2C,
    "smc_smbus_pmbus_test": SmcProtocolVipKind.I2C,
    "smc_smbus_hostnotify_test": SmcProtocolVipKind.I2C,
    "smc_i3c_to_fabric_test": SmcProtocolVipKind.I3C,
    "smc_ijtag_basic_test": SmcProtocolVipKind.JTAG,
    "smc_efuse_jtag_lc_negative_test": SmcProtocolVipKind.JTAG,
    "smc_efuse_jtag_lc_access_matrix_test": SmcProtocolVipKind.JTAG,
    "smc_jtag_reset_proxy_test": SmcProtocolVipKind.JTAG,
    "smc_input_output_fabric_wr_rd_test": SmcProtocolVipKind.OUTPUT_FABRIC,
    "smc_output_filter_remap_security_test": SmcProtocolVipKind.OUTPUT_FABRIC,
    "smc_output_fabric_wr_rd_responder_test": SmcProtocolVipKind.OUTPUT_FABRIC,
    "smc_output_fabric_slverr_inject_test": SmcProtocolVipKind.OUTPUT_FABRIC,
    "smc_mailbox_irq_test": SmcProtocolVipKind.MAILBOX,
    "smc_mailbox_data_error_test": SmcProtocolVipKind.MAILBOX,
    "smc_mailbox_event_irq_test": SmcProtocolVipKind.MAILBOX,
    "smc_efuse_otp_clock_test": SmcProtocolVipKind.EFUSE,
    "smc_efuse_otp_clock_config_depth_test": SmcProtocolVipKind.EFUSE,
    "smc_efuse_permission_boundary_test": SmcProtocolVipKind.EFUSE,
    "smc_efuse_chip_config_read_test": SmcProtocolVipKind.EFUSE,
    "smc_static_cg_sanity_test": SmcProtocolVipKind.CLOCK,
    "smc_gpio_irq_active_test": SmcProtocolVipKind.GPIO_IRQ,
    "smc_uart_spi_log_engine_test": SmcProtocolVipKind.UART_LOG,
    "smc_uart_log_engine_reg_rw_test": SmcProtocolVipKind.UART_LOG,
    "smc_uart_log_engine_error_boundary_test": SmcProtocolVipKind.UART_LOG,
    "smc_uart_loopback_test": SmcProtocolVipKind.UART_LOG,
    "smc_spi_pad_bfm_test": SmcProtocolVipKind.UART_LOG,
    "smc_sideband_protocol_smoke_test": SmcProtocolVipKind.SIDEBAND,
    "smc_octs_dual_sync_test": SmcProtocolVipKind.SIDEBAND,
    "smc_octs_sanity_test": SmcProtocolVipKind.SIDEBAND,
    "smc_avsbus_sanity_test": SmcProtocolVipKind.SIDEBAND,
    "smc_avsbus_status_depth_test": SmcProtocolVipKind.SIDEBAND,
    "smc_avsbus_clock_config_proxy_test": SmcProtocolVipKind.SIDEBAND,
    "smc_zeroer_dma_timeout_test": SmcProtocolVipKind.ZEROER_DMA,
    "smc_zeroer_sanity_test": SmcProtocolVipKind.ZEROER_DMA,
    "smc_dma_sanity_test": SmcProtocolVipKind.ZEROER_DMA,
    "smc_ecc_dfd_dbs_sanity_test": SmcProtocolVipKind.DIAGNOSTIC,
    "smc_dfd_sanity_test": SmcProtocolVipKind.DIAGNOSTIC,
    "smc_cpu_ecc_lint_pint_depth_test": SmcProtocolVipKind.DIAGNOSTIC,
    "smc_dbs_idle_test": SmcProtocolVipKind.DIAGNOSTIC,
    "smc_cpu_to_sep_axi_test": SmcProtocolVipKind.CPU,
    "smc_cpu_sanity_test": SmcProtocolVipKind.CPU,
    "smc_cpu_firmware_boot_test": SmcProtocolVipKind.CPU,
    "smc_occp_sanity_secure_error_test": SmcProtocolVipKind.CPU,
    "smc_efuse_otp_burn_shadow_test": SmcProtocolVipKind.EFUSE,
    "smc_ecc_fault_inject_test": SmcProtocolVipKind.DIAGNOSTIC,
    "smc_cpu_ctrl_map_depth_test": SmcProtocolVipKind.CPU,
    "smc_cpu_ctrl_scratch_window_test": SmcProtocolVipKind.CPU,
    "smc_mailbox_inbound_test": SmcProtocolVipKind.MAILBOX,
    "smc_i2c_multi_instance_test": SmcProtocolVipKind.I2C,
    "smc_efuse_map_read_test": SmcProtocolVipKind.EFUSE,
    "smc_efuse_shim_ctrl_test": SmcProtocolVipKind.EFUSE,
    "smc_gpio_ctrl_full_sweep_test": SmcProtocolVipKind.GPIO_IRQ,
    "smc_telemetry_receiver_csr_test": SmcProtocolVipKind.SIDEBAND,
    "smc_remap_cla_test": SmcProtocolVipKind.OUTPUT_FABRIC,
    "smc_mailbox_multi_instance_test": SmcProtocolVipKind.MAILBOX,
    "smc_filter_multi_entry_test": SmcProtocolVipKind.OUTPUT_FABRIC,
    "smc_gpio_intf_full_sweep_test": SmcProtocolVipKind.GPIO_IRQ,
    "smc_mailbox_field_sweep_test": SmcProtocolVipKind.MAILBOX,
    "smc_filter_field_sweep_test": SmcProtocolVipKind.OUTPUT_FABRIC,
    "smc_xvisor_remap_test": SmcProtocolVipKind.OUTPUT_FABRIC,
    "smc_cluster_beu_test": SmcProtocolVipKind.CPU,
}


# ==================================================== build-model identity ====
# `[BUILD-MODEL-IDENTITY]`. The SMC sim stage runs with `do_build: False` and
# reuses a prebuilt model out of the directory run_dv.py exports as
# OCAH_SIM_BUILD_DIR: `<target build_dir>/<tool>`, `<tool>-coverage` for a
# `--cov` run, `<tool>/<target>` for VCS, and a fingerprint leaf below any of
# those when the build cache is on. The run's own hdl_compile log records only
# "Nothing to be done for 'default'", and the build directory is overwritten in
# place by the next `--rebuild`, so an identity recovered by hand afterwards is
# unverifiable.
#
# So every run records, from the cocotb side, into its kept log, at
# start-of-simulation:
#   * the commit of the checkout the compile sources come from
#     (`checkout_rev=`), and whether anything that feeds the model or the
#     bench was uncommitted at run time (`dirty=`): the compile sources and
#     include directories, every Bender manifest and lockfile (they choose
#     the sources), the shared DV configuration and the runner (they choose
#     the defines and flags), the SMC DV package entries the flow reads --
#     the paths smc_sim_cfg.toml names (tb/, models/, cov/, assets/,
#     efuse_preload/, the .vlt scope files), the testlists, the cocotb bench,
#     the firmware image sources under fw/, smc_sim.core and the configuration
#     itself -- and the in-repo PYTHONPATH entries. docs/ and the signoff
#     records under hw/sys/smc/doc are read by people, not by the flow, and
#     are outside the scope;
#   * whether the model was built from the sources now in the tree. A
#     prebuilt binary carries nothing that names the tree it came from, so
#     the checkout's commit describes the model only if no source has changed
#     since the model was built. Verilator's build record keeps a content
#     hash of every file it read; the run recomputes them
#     (`model_sources_match=`, `model_sources_checked=`) and fails on any
#     difference. Every run also stamps `model_newer_than_sources=` from the
#     mtimes of the in-repo compile sources and include-directory files; for
#     a tool whose record keeps no hashes that comparison is the verdict, and
#     since `git checkout` sets the mtime of every file it writes to now, a
#     model built before a checkout of an identical tree fails there too --
#     rebuilding answers both cases;
#   * the smc_sim_cfg.toml target the exported build directory belongs to, and
#     the sha256 of the model artifact, of the resolved elaboration-dependency
#     list, and of the compile filelist the simulator was invoked with;
#   * the sha256 of the bench code under hw/sys/smc/dv/cocotb.
# If any of it cannot be determined the test FAILS -- a placeholder would be
# worse than nothing, because it would make an un-attributable run look
# attributed. A dirty tree fails too, unless SMC_DV_ALLOW_DIRTY=1 is exported
# or the test sets `require_clean_tree = False`, and a stale model fails
# unless SMC_DV_ALLOW_STALE_MODEL=1 is exported; the line then carries
# `dirty_allowed=true` / `model_stale_allowed=true`, so such a log can never
# pass as evidence unnoticed.
_SIM_CFG_REL = Path("hw") / "sys" / "smc" / "dv" / "smc_sim_cfg.toml"
_DV_REL = Path("hw") / "sys" / "smc" / "dv"
_BENCH_REL = _DV_REL / "cocotb"
_BUILD_DIR_ENV = "OCAH_SIM_BUILD_DIR"
_ALLOW_DIRTY_ENV = "SMC_DV_ALLOW_DIRTY"
_ALLOW_STALE_ENV = "SMC_DV_ALLOW_STALE_MODEL"

# DV package entries in the dirty scope that no filelist or configuration
# string names: the configuration itself, the core file, the bench, and the
# sources the firmware images are built from (fw/build is ignored output and
# never appears in `git status`). Everything else under hw/sys/smc/dv enters
# the scope through the filelist closure, the paths smc_sim_cfg.toml names,
# the [testlist] path and the [frameworks.cocotb] roots -- see `_config_scope`.
_DV_SCOPE_FILES_REL = (_SIM_CFG_REL, _DV_REL / "smc_sim.core")
_DV_SCOPE_DIRS_REL = (_BENCH_REL, _DV_REL / "fw")
# Documentation and signoff records: read by people, not by the flow. A
# configuration string pointing into one of these does not enter the scope.
_DV_SCOPE_EXCLUDED_REL = (
    _DV_REL / "docs",
    _DV_REL / "README.md",
    Path("hw") / "sys" / "smc" / "doc",
)
# A DV-package path inside a configuration string -- a plusarg with a
# `{repo_root}/` prefix, an argv fragment, a bare path value.
_DV_PATH_IN_CONFIG = re.compile(r"hw/sys/smc/dv/[A-Za-z0-9_./-]+")

# tool -> (model artifact, resolved-compile-input list, simulator build record),
# all relative to OCAH_SIM_BUILD_DIR. The model artifact is the thing the
# simulator actually ran. The build record is the simulator's own note of the
# command line that produced the model; the compile filelist is read from its
# `-f` arguments, so the digest is of the filelist that built the model and not
# of whichever generated filelist happens to be lying in the work directory.
# Verilator's record also carries a content hash of every file it read (see
# `_record_source_hashes`). VCS keeps no such record, so its filelist comes
# from the target's configuration instead (see `_compile_filelists`).
_MODEL_ARTIFACTS: dict[str, tuple[str, str | None, str | None]] = {
    "verilator": ("smc_uvm_top", "Vtop__ver.d", "Vtop__verFiles.dat"),
    "vcs": ("simv", None, None),
    "xcelium": ("xrun_snapshot", "xrun_build.log", "xrun_build.history"),
}

# Files of a directory-shaped model (an Xcelium snapshot library) whose
# contents enter the fingerprint: the compiled units and the elaborated
# snapshot live in the library's .pak files and shared objects. Every other
# file enters by path, size and mtime.
_SNAPSHOT_CONTENT_SUFFIXES = frozenset({".pak", ".so", ".lnx86"})

# A simulator reports the name of its executable, which is not always the tool
# key above: Xcelium runs as `xmsim`. Map the reported names onto keys instead of
# loosening the substring match below, so a simulator nobody has registered still
# fails rather than resolving to whichever key happens to share a few letters.
_SIM_NAME_ALIASES: dict[str, str] = {
    "xmsim": "xcelium",
    "ncsim": "xcelium",
}

# `sN(<stamp>):  xrun ...` -- one entry per invocation in xrun's history file.
_XRUN_HISTORY_ENTRY = re.compile(r"^s\d+\([^)]*\):\s+(xrun\b.*)$")

# Verilator writes each input's SHA-256 into its build record as the first 40
# characters of the base64 digest with `+` and `/` replaced by `A` and `B`.
_VERILATOR_HASH_ALPHABET = str.maketrans("+/", "AB")
_VERILATOR_HASH_LENGTH = 40

# Beyond the filelist's own sources, what decides the model's contents:
# Bender manifests and lockfiles anywhere in the tree choose the sources of
# every target the generated filelist draws from; the shared DV configuration
# (profiles, simulators, DUT registry) and the runner choose the defines,
# flags and stage commands the simulator was invoked with. All are in the
# dirty scope, or an edit to one of them would build a different model from
# clean, committed sources and the line would still say dirty=false.
_MANIFEST_NAMES = frozenset({"Bender.yml", "Bender.lock"})
_FLOW_SCOPE_DIRS = (
    Path("hw") / "common" / "dv" / "configs",
    Path("tools") / "dv" / "runlib",
)
_FLOW_SCOPE_FILES = (Path("tools") / "dv" / "run_dv.py",)

# How many dirty paths the identity line names before abbreviating.
_DIRTY_PATHS_SHOWN = 8

_MODEL_IDENTITY_DONE: list[str] = []


def _fail(message: str) -> NoReturn:
    raise AssertionError(f"[BUILD-MODEL-IDENTITY] {message}")


def _repo_root() -> Path:
    root = os.environ.get("OCH_ROOT")
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parents[6]


def _sim_tool() -> str:
    """Simulator key for :data:`_MODEL_ARTIFACTS`, from the live simulator."""
    name = (getattr(cocotb, "SIM_NAME", "") or "").strip().lower()
    if not name:
        _fail(
            "cocotb.SIM_NAME is empty: the run cannot name the simulator it is "
            "executing in, so it cannot name the model either"
        )
    for alias, tool in _SIM_NAME_ALIASES.items():
        if alias in name:
            return tool
    for tool in _MODEL_ARTIFACTS:
        if tool in name:
            return tool
    _fail(
        f"simulator {name!r} has no entry in _MODEL_ARTIFACTS "
        f"({sorted(_MODEL_ARTIFACTS)}), so this run cannot state which elaborated "
        f"model it simulated. Add the tool's model artifact rather than letting "
        f"the kept log stay silent."
    )


def _digest(path: Path) -> tuple[str, int]:
    """(sha256, size) of a file, or a fingerprint of a directory-shaped model.

    An Xcelium snapshot is a library directory: the files named by
    :data:`_SNAPSHOT_CONTENT_SUFFIXES` are hashed by content, the rest by
    relative path, size and mtime, so two builds of the same sizes fingerprint
    differently.
    """
    digest = hashlib.sha256()
    if path.is_dir():
        total = 0
        entries = sorted(p for p in path.rglob("*") if p.is_file())
        if not entries:
            _fail(f"{path} is an empty directory: there is no model artifact to fingerprint")
        for entry in entries:
            stat = entry.stat()
            total += stat.st_size
            digest.update(str(entry.relative_to(path)).encode())
            digest.update(b"\0")
            if entry.suffix in _SNAPSHOT_CONTENT_SUFFIXES:
                with entry.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1 << 20), b""):
                        digest.update(chunk)
            else:
                digest.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode())
            digest.update(b"\0")
        return digest.hexdigest(), total
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _utc(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _mtime_utc(path: Path) -> str:
    return _utc(path.stat().st_mtime)


def _model_mtime(model: Path) -> float:
    """When the model was last written: the newest file inside a snapshot directory."""
    if model.is_dir():
        times = [p.stat().st_mtime for p in model.rglob("*") if p.is_file()]
        if times:
            return max(times)
    return model.stat().st_mtime


def _require(path: Path, what: str) -> Path:
    if not path.exists():
        _fail(
            f"{what} not found at {path}: this run cannot state which elaborated "
            f"model it simulated. Failing loudly instead of logging a placeholder "
            f"-- a kept log that names no model cannot support any claim about "
            f"the RTL that was in the DUT."
        )
    return path


def _git(args: list[str], cwd: Path, stdin: str | None = None) -> str:
    argv = ["git", *args]
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _fail(
            f"`{' '.join(argv[:3])}` could not run in {cwd} ({exc}): without git "
            f"this run cannot name the commit it simulated"
        )
    if proc.returncode != 0:
        _fail(
            f"`{' '.join(argv[:3])}` failed in {cwd} (rc={proc.returncode}): "
            f"{proc.stderr.strip()} -- this run cannot name the commit it simulated"
        )
    return proc.stdout


def _model_build_dir() -> Path:
    """The leaf directory the simulated model was elaborated into.

    run_dv.py exports it as OCAH_SIM_BUILD_DIR for every cocotb sim stage. There
    is no fixed-path fallback: a run that does not know where its model was
    built cannot say which model it simulated. The path is kept as exported --
    a build tree that lives on scratch behind a symlink stays addressable
    under the repo root that way.
    """
    exported = os.environ.get(_BUILD_DIR_ENV)
    if not exported:
        _fail(
            f"{_BUILD_DIR_ENV} is not set. run_dv.py exports the directory the "
            f"model was elaborated into; without it this run cannot state which "
            f"model it simulated."
        )
    return _require(Path(exported).absolute(), "elaborated model directory")


def _sim_cfg(root: Path) -> dict:
    path = _require(root / _SIM_CFG_REL, "SMC sim configuration")
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _target_for_build_dir(root: Path, cfg: dict, build_dir: Path) -> tuple[str, dict]:
    """Name and table of the ``[targets.<name>]`` whose ``build_dir`` holds ``build_dir``.

    The runner builds each target under its own ``build_dir`` (``build/cocotb``
    for ``default``, ``build_dual/cocotb`` for ``dual``), so the exported leaf
    identifies the target. The longest matching prefix wins.
    """
    targets = cfg.get("targets")
    if not isinstance(targets, dict) or not targets:
        _fail(f"{_SIM_CFG_REL} declares no [targets.*] table")
    matches: list[tuple[int, str, dict]] = []
    build_dirs = {build_dir, build_dir.resolve()}
    for name, target in targets.items():
        base = str(target.get("build_dir", "")) if isinstance(target, dict) else ""
        if not base:
            continue
        base_path = root / base
        for candidate in {base_path, base_path.resolve()}:
            if any(leaf == candidate or candidate in leaf.parents for leaf in build_dirs):
                matches.append((len(base_path.parts), name, target))
                break
    if not matches:
        _fail(
            f"{build_dir} lies under no [targets.*].build_dir of {_SIM_CFG_REL}: "
            f"this run cannot name the target whose model it simulated"
        )
    matches.sort(key=lambda item: item[0], reverse=True)
    _, name, target = matches[0]
    return name, target


def _record_command(tool: str, record: Path) -> list[str]:
    """Tokens of the simulator invocation its build record keeps."""
    text = record.read_text(encoding="utf-8", errors="replace")
    command = ""
    if tool == "verilator":
        # `C "<argv>"`: the command line Verilator compares for --skip-identical.
        for line in text.splitlines():
            if line.startswith('C "'):
                command = line[3:].rstrip().rstrip('"')
                break
    elif tool == "xcelium":
        for line in text.splitlines():
            match = _XRUN_HISTORY_ENTRY.match(line.rstrip())
            if match:
                command = match.group(1)
    if not command:
        _fail(
            f"{record} holds no {tool} command line: the filelist that built "
            f"this model cannot be recovered from the build"
        )
    return shlex.split(command)


def _compile_filelists(
    root: Path,
    tool: str,
    build_dir: Path,
    record_rel: str | None,
    cfg: dict,
    target_name: str,
    target: dict,
) -> tuple[list[Path], str, set[str] | None]:
    """(compile filelists, where they were resolved from, defines the build used).

    With a simulator build record the filelists are the ``-f`` arguments of the
    recorded command and the defines its ``+define+`` / ``-D`` tokens, so both
    describe the model that was actually built. Without one (VCS) the filelist
    is the one the runner hands the tool for this target; if the target
    declares none and both the shared filelist and a runner-derived per-target
    one exist, the run fails rather than guess which of the two built the model.
    """
    if record_rel is not None:
        tokens = _record_command(tool, _require(build_dir / record_rel, f"{tool} build record"))
        flists: list[Path] = []
        defines: set[str] = set()
        for index, token in enumerate(tokens):
            if token in ("-f", "-F") and index + 1 < len(tokens):
                flists.append(Path(tokens[index + 1]))
            elif token.startswith("+define+"):
                defines.update(part.split("=", 1)[0] for part in token[8:].split("+") if part)
            elif token.startswith("-D") and len(token) > 2:
                defines.add(token[2:].split("=", 1)[0])
        if not flists:
            _fail(
                f"the {tool} build record in {build_dir} names no -f filelist: "
                f"the compile inputs of this model cannot be identified"
            )
        return (
            [_require(path, "compile filelist the simulator was invoked with") for path in flists],
            f"{tool}-build-record",
            defines,
        )
    declared = target.get("filelist")
    if declared:
        candidates = [root / str(declared)]
    else:
        candidates = []
        shared = (cfg.get("build") or {}).get("filelist")
        if shared:
            candidates.append(root / str(shared))
        candidates.append(root / str(target["build_dir"]) / "filelists" / target_name / "files.f")
    existing = [path for path in candidates if path.is_file()]
    if len(existing) != 1:
        _fail(
            f"{len(existing)} of the candidate compile filelists for target "
            f"{target_name!r} exist ({', '.join(str(c) for c in candidates)}); "
            f"the {tool} build keeps no record of its own, so the run cannot tell "
            f"which filelist built the model"
        )
    return existing, "smc_sim_cfg.toml", None


def _filelist_closure(flists: list[Path]) -> tuple[set[Path], set[Path]]:
    """(source files, include directories) the filelists name, following nested -f/-F."""
    files: set[Path] = set()
    dirs: set[Path] = set()
    pending = list(flists)
    seen: set[Path] = set()
    while pending:
        flist = pending.pop()
        if flist in seen:
            continue
        seen.add(flist)
        for raw in flist.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith(("//", "#")):
                continue
            tokens = line.split()
            index = 0
            while index < len(tokens):
                token = tokens[index]
                if token in ("-f", "-F", "-v", "-y") and index + 1 < len(tokens):
                    target = Path(tokens[index + 1])
                    if not target.is_absolute():
                        target = flist.parent / target
                    if token in ("-f", "-F"):
                        pending.append(target)
                    elif token == "-v":
                        files.add(target)
                    else:
                        dirs.add(target)
                    index += 2
                    continue
                if token.startswith("+incdir+"):
                    dirs.update(Path(part) for part in token[8:].split("+") if part)
                elif not token.startswith(("+", "-")):
                    files.add(Path(token))
                index += 1
    return files, dirs


def _repo_relative(root: Path, path: Path) -> Path | None:
    """``path`` relative to ``root``, or None when it lies outside the checkout."""
    for candidate in (path, path.resolve()):
        try:
            return candidate.relative_to(root)
        except ValueError:
            continue
    return None


def _display(root: Path, path: Path) -> str:
    """Repo-relative form of ``path`` for the log line, absolute when outside."""
    rel = _repo_relative(root, path)
    return str(rel) if rel is not None else str(path)


def _dirty_paths(
    toplevel: Path, files: set[str], dirs: set[str], names: frozenset[str]
) -> list[str]:
    """``<XY>:<path>`` for every uncommitted change git reports inside the scope.

    The scope is the set of repo-relative ``files``, everything under ``dirs``,
    and every path whose basename is in ``names`` wherever it sits. It reaches
    git as pathspecs, so the status -- and the untracked-file walk in
    particular -- covers only the scope, and ``--no-optional-locks`` keeps the
    parallel leaves of a regression from each rewriting the index. Untracked
    files count (an unversioned bench file feeds the run as much as an edited
    one); ignored ones do not, which is what keeps the build outputs the runner
    writes under ``build/`` and ``fw/build/`` out of the verdict.
    """
    pathspecs = [
        *(f":(literal){path}" for path in sorted(files)),
        *(f":(literal){path}" for path in sorted(dirs)),
        *(f":(glob)**/{name}" for name in sorted(names)),
    ]
    out = _git(
        ["--no-optional-locks", "status", "--porcelain=v1", "-z", "--untracked-files=all", "--"]
        + pathspecs,
        toplevel,
    )
    prefixes = tuple(d.rstrip("/") + "/" for d in dirs)
    entries = out.split("\0")
    dirty: list[str] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4:
            continue
        status, path = entry[:2], entry[3:]
        if status[0] in "RC":
            # A rename or copy carries the original path as a second field.
            index += 1
        if path in files or path.startswith(prefixes) or path.rsplit("/", 1)[-1] in names:
            dirty.append(f"{status.strip() or '?'}:{path}")
    return sorted(dirty)


def _config_strings(node: object, key: str = "") -> list[tuple[str, str]]:
    """``(key, value)`` for every string in a TOML tree; array items carry the array's key."""
    if isinstance(node, str):
        return [(key, node)]
    out: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for child_key, child in node.items():
            out.extend(_config_strings(child, str(child_key)))
    elif isinstance(node, list):
        for child in node:
            out.extend(_config_strings(child, key))
    return out


def _config_scope(root: Path, cfg: dict) -> tuple[set[str], set[str]]:
    """(files, dirs), repo-relative: the DV package entries the flow reads.

    Every ``hw/sys/smc/dv/...`` path inside a configuration string (the .vlt
    scope files, the assets a run mode loads, the eFuse generator a c_build
    stage runs), the ``[testlist]`` directory, the ``[frameworks.cocotb]`` roots,
    and :data:`_DV_SCOPE_FILES_REL` / :data:`_DV_SCOPE_DIRS_REL`. The other
    ``[frameworks.*]`` overlays describe benches this process is not running.
    A path under a ``work_dir`` / ``build_dir`` / clean path is build output and
    a path under :data:`_DV_SCOPE_EXCLUDED_REL` is documentation; neither
    enters the scope.
    """
    cocotb_cfg = (cfg.get("frameworks") or {}).get("cocotb") or {}
    strings = _config_strings({key: value for key, value in cfg.items() if key != "frameworks"})
    strings.extend(_config_strings(cocotb_cfg, "cocotb"))
    clean = ((cfg.get("native") or {}).get("stages") or {}).get("clean") or {}
    dropped = {str(value).rstrip("/") for key, value in strings if key in ("work_dir", "build_dir")}
    dropped.update(str(path).rstrip("/") for path in clean.get("paths") or [])
    dropped.add(str(_DV_REL / "fw" / "build"))
    dropped.update(str(path) for path in _DV_SCOPE_EXCLUDED_REL)

    candidates: set[str] = set()
    for _key, value in strings:
        candidates.update(match.rstrip("/.") for match in _DV_PATH_IN_CONFIG.findall(value))
    testlist = (cfg.get("testlist") or {}).get("path")
    if testlist:
        candidates.add(str((_DV_REL / str(testlist)).parent))
    candidates.update(
        str(cocotb_cfg[key]) for key in ("python_root", "test_dir") if cocotb_cfg.get(key)
    )
    candidates.update(str(path) for path in (*_DV_SCOPE_FILES_REL, *_DV_SCOPE_DIRS_REL))

    files: set[str] = set()
    dirs: set[str] = set()
    for rel in candidates:
        if any(rel == prefix or rel.startswith(prefix + "/") for prefix in dropped):
            continue
        path = root / rel
        if path.is_dir():
            dirs.add(rel)
        elif path.is_file():
            files.add(rel)
    return files, dirs


def _dirty_scope(
    root: Path, cfg: dict, sources: set[Path], incdirs: set[Path]
) -> tuple[set[str], set[str], int]:
    """(files, dirs, compile inputs outside the checkout): what feeds the model or the bench.

    The compile sources and include directories, the DV package entries of
    :func:`_config_scope`, the configuration and runner code that chose the
    defines and flags (:data:`_FLOW_SCOPE_DIRS` / :data:`_FLOW_SCOPE_FILES`),
    and every in-repo PYTHONPATH entry the cocotb process imports from. The
    Bender manifests join by basename in :func:`_dirty_paths`.
    """
    files, dirs = _config_scope(root, cfg)
    files.update(str(path) for path in _FLOW_SCOPE_FILES)
    dirs.update(str(path) for path in _FLOW_SCOPE_DIRS)
    outside_repo = 0
    for path in sources:
        rel = _repo_relative(root, path)
        if rel is None:
            outside_repo += 1
        else:
            files.add(str(rel))
    for path in incdirs:
        rel = _repo_relative(root, path)
        if rel is None:
            outside_repo += 1
        else:
            dirs.add(str(rel))
    for entry in os.environ.get("PYTHONPATH", "").split(os.pathsep):
        rel = _repo_relative(root, Path(entry)) if entry else None
        if rel is not None:
            dirs.add(str(rel))
    return files, dirs, outside_repo


def _record_source_hashes(tool: str, record: Path) -> dict[Path, str]:
    """path -> content hash the build record keeps for every input the simulator read.

    Verilator writes one ``S`` line per input with the hash it compared for
    ``--skip-identical`` (``"unhashed"`` for a file it did not hash); its
    ``T`` lines are outputs. Empty for a tool whose record keeps no hashes.
    """
    if tool != "verilator":
        return {}
    hashes: dict[Path, str] = {}
    for line in record.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("S "):
            continue
        fields = line.split('"')
        if len(fields) < 4:
            continue
        digest, path = fields[1], fields[3]
        if digest and digest != "unhashed" and path:
            hashes[Path(path)] = digest
    return hashes


def _verilator_source_digest(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).digest()
    return (
        base64.b64encode(digest)
        .decode()
        .translate(_VERILATOR_HASH_ALPHABET)[:_VERILATOR_HASH_LENGTH]
    )


def _sources_differing_from_record(root: Path, hashes: dict[Path, str]) -> tuple[list[Path], int]:
    """(in-repo inputs whose contents differ from the record, in-repo inputs compared)."""
    changed: list[Path] = []
    checked = 0
    for path, recorded in hashes.items():
        if _repo_relative(root, path) is None:
            continue
        checked += 1
        try:
            current = _verilator_source_digest(path)
        except OSError:
            changed.append(path)
            continue
        if current != recorded:
            changed.append(path)
    return sorted(changed), checked


def _sources_newer_than(
    root: Path, model_mtime: float, sources: set[Path], incdirs: set[Path]
) -> list[tuple[float, Path]]:
    """``(mtime, path)`` of every in-repo compile input written after the model, newest first.

    The inputs are the compile sources and the files directly inside the
    include directories (``+incdir+`` is not recursive). The generated
    filelist and the bench are not among them: the flist stage rewrites the
    filelist on every run, and the bench is interpreted at run time and
    digested as ``bench_sha256`` -- neither is in the model.
    """
    inputs = {path for path in sources if _repo_relative(root, path) is not None}
    for directory in incdirs:
        if _repo_relative(root, directory) is not None and directory.is_dir():
            inputs.update(path for path in directory.iterdir() if path.is_file())
    newer: list[tuple[float, Path]] = []
    for path in inputs:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime > model_mtime:
            newer.append((mtime, path))
    newer.sort(key=lambda item: item[0], reverse=True)
    return newer


def _reject_sources_from_other_checkouts(root: Path, model_top: Path, sources: set[Path]) -> None:
    """Fail when any compile source lies in a git checkout other than the model's.

    A filelist can mix trees -- a Bender filelist generated in one checkout and
    a top-level one in another -- and the sources under ``root`` alone would
    then name a commit that supplied only part of the model. Sources outside
    any git checkout (a site library) are allowed and counted in the line as
    ``flist_sources_outside_repo``.
    """
    by_dir: dict[Path, Path] = {}
    for source in sources:
        if _repo_relative(root, source) is None and source.parent.is_dir():
            by_dir.setdefault(source.parent, source)
    for directory, example in sorted(by_dir.items()):
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if proc.returncode != 0:
            continue
        other = Path(proc.stdout.strip()).resolve()
        if other != model_top:
            _fail(
                f"compile source {example} lies in the git checkout {other}, not in "
                f"the model's checkout {model_top}: one identity cannot name two trees"
            )


def _bench_digest(root: Path) -> tuple[str, int]:
    """sha256 over the bench sources (path + content of every .py under cocotb/)."""
    bench = _require(root / _BENCH_REL, "bench source tree")
    sources = sorted(p for p in bench.rglob("*.py") if "__pycache__" not in p.parts)
    if not sources:
        _fail(f"{bench} holds no Python source: the bench cannot be fingerprinted")
    digest = hashlib.sha256()
    for source in sources:
        digest.update(str(source.relative_to(root)).encode())
        digest.update(b"\0")
        digest.update(source.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest(), len(sources)


def log_build_model_identity(
    *, require_clean_tree: bool = True, expect_target: str | None = None
) -> str:
    """Log (once per process) the identity of the model this run simulated.

    Returns the emitted line. Raises with a diagnostic if the identity cannot be
    determined, if ``expect_target`` names a target other than the one the
    exported build directory belongs to, if sources feeding the model or the
    bench are uncommitted and neither ``require_clean_tree=False`` nor
    ``SMC_DV_ALLOW_DIRTY=1`` allows that, or if the model was not built from the
    compile inputs now in the tree and ``SMC_DV_ALLOW_STALE_MODEL=1`` does not
    allow that; there is no placeholder branch.
    """
    if _MODEL_IDENTITY_DONE:
        return _MODEL_IDENTITY_DONE[0]
    root = _repo_root()
    tool = _sim_tool()
    model_rel, deps_rel, record_rel = _MODEL_ARTIFACTS[tool]
    build_dir = _model_build_dir()
    cfg = _sim_cfg(root)
    target_name, target = _target_for_build_dir(root, cfg, build_dir)
    if expect_target is not None and target_name != expect_target:
        _fail(
            f"this test needs the {expect_target!r} model but {build_dir} is the "
            f"{target_name!r} target's build: a log from another target's model "
            f"is not evidence about this one"
        )
    model = _require(build_dir / model_rel, f"{tool} elaborated model artifact")
    model_sha, model_size = _digest(model)

    flists, flist_source, build_defines = _compile_filelists(
        root, tool, build_dir, record_rel, cfg, target_name, target
    )
    if build_defines is not None:
        declared = [str(d).split("=", 1)[0] for d in (target.get("defines") or [])]
        missing = [d for d in declared if d not in build_defines]
        if missing:
            _fail(
                f"the model in {build_dir} was built without {'/'.join(missing)}, "
                f"which target {target_name!r} declares: it is not that target's model"
            )
    flist_digest = hashlib.sha256()
    flist_lines = 0
    for flist in flists:
        sha, _size = _digest(flist)
        flist_digest.update(sha.encode())
        flist_lines += len(flist.read_text(encoding="utf-8", errors="replace").splitlines())
    sources, incdirs = _filelist_closure(flists)

    # The commit is the checkout's: the tree the compile sources come from
    # (the generated filelist itself may sit in a build tree on scratch).
    # Whether the model was built from that tree is settled by the model
    # binding below: the content hashes the build record keeps, or the mtimes
    # for a tool that records none. The bench must come from the same
    # checkout, or the one line would name two trees.
    in_repo = sorted(p for p in sources if _repo_relative(root, p) is not None)
    if not in_repo:
        _fail(
            f"none of the {len(sources)} compile sources of {flists[0]} lies under "
            f"{root}: the checkout the model was built from cannot be named"
        )
    model_top = Path(_git(["rev-parse", "--show-toplevel"], in_repo[0].parent).strip()).resolve()
    bench_top = Path(
        _git(["rev-parse", "--show-toplevel"], Path(__file__).resolve().parent).strip()
    ).resolve()
    if not (model_top == bench_top == root):
        _fail(
            f"model checkout {model_top}, bench checkout {bench_top} and repo root "
            f"{root} differ: one identity cannot name three trees"
        )
    checkout_rev = _git(["rev-parse", "HEAD"], model_top).strip()
    _reject_sources_from_other_checkouts(root, model_top, sources)

    scope_files, scope_dirs, outside_repo = _dirty_scope(root, cfg, sources, incdirs)
    dirty = _dirty_paths(model_top, scope_files, scope_dirs, _MANIFEST_NAMES)
    dirty_allowed = os.environ.get(_ALLOW_DIRTY_ENV) == "1" or not require_clean_tree
    shown = ",".join(dirty[:_DIRTY_PATHS_SHOWN])
    if len(dirty) > _DIRTY_PATHS_SHOWN:
        shown += f",(+{len(dirty) - _DIRTY_PATHS_SHOWN} more)"

    # Model binding. With a content record the verdict is the recomputed
    # hashes; without one it is the mtimes, which a `git checkout` of an
    # identical tree also moves. Both are stamped either way.
    model_mtime = _model_mtime(model)
    newer = _sources_newer_than(root, model_mtime, sources, incdirs)
    recorded = _record_source_hashes(tool, build_dir / record_rel) if record_rel else {}
    changed, checked = _sources_differing_from_record(root, recorded)
    if checked:
        sources_match = "false" if changed else "true"
        stale = bool(changed)
    else:
        sources_match = "unchecked"
        stale = bool(newer)
    stale_allowed = os.environ.get(_ALLOW_STALE_ENV) == "1"

    bench_sha, bench_files = _bench_digest(root)

    deps_part = "deps=none"
    if deps_rel is not None:
        deps = _require(build_dir / deps_rel, f"{tool} elaboration input list")
        deps_sha, _deps_size = _digest(deps)
        deps_part = (
            f"deps={_display(root, deps)} deps_sha256={deps_sha} deps_mtime={_mtime_utc(deps)}"
        )
    line = (
        "CHK-BUILD-MODEL-IDENTITY: this run simulated "
        f"tool={tool} sim={getattr(cocotb, 'SIM_NAME', '?')} "
        f"version={getattr(cocotb, 'SIM_VERSION', '?')} "
        f"checkout_rev={checkout_rev} dirty={'true' if dirty else 'false'} "
        f"dirty_allowed={'true' if dirty_allowed else 'false'} "
        f"dirty_paths={shown or '-'} "
        f"target={target_name} model={_display(root, model)} model_sha256={model_sha} "
        f"model_bytes={model_size} model_mtime={_utc(model_mtime)} "
        f"model_newer_than_sources={'false' if newer else 'true'} "
        f"model_sources_match={sources_match} model_sources_checked={checked} "
        f"model_stale_allowed={'true' if stale_allowed else 'false'} "
        f"{deps_part} "
        f"flist={','.join(_display(root, f) for f in flists)} "
        f"flist_source={flist_source} flist_sha256={flist_digest.hexdigest()} "
        f"flist_lines={flist_lines} flist_mtime={_utc(max(f.stat().st_mtime for f in flists))} "
        f"flist_sources={len(sources)} flist_sources_outside_repo={outside_repo} "
        f"bench={_BENCH_REL} bench_py_files={bench_files} bench_sha256={bench_sha} "
        f"seed={os.environ.get('RANDOM_SEED', 'unset')}"
    )
    cocotb.log.info(line)
    if dirty:
        if not dirty_allowed:
            _fail(
                f"the working tree at {checkout_rev[:12]} has {len(dirty)} uncommitted "
                f"change(s) on inputs of this model or bench ({shown}): compile sources "
                f"and include directories, Bender manifests, the DV configuration and "
                f"runner, and the SMC DV package entries the flow reads. A log whose "
                f"sources cannot be named is no evidence. Commit or stash them; to run "
                f"anyway export {_ALLOW_DIRTY_ENV}=1, which stamps dirty_allowed=true "
                f"into the log."
            )
        cocotb.log.warning(
            "[BUILD-MODEL-IDENTITY] dirty tree allowed: %d uncommitted change(s) on "
            "the model or bench inputs (%s); this log cannot serve as evidence",
            len(dirty),
            shown,
        )
    if stale:
        if changed:
            reason = (
                f"was built from other contents of {len(changed)} of its {checked} "
                f"recorded compile source(s), e.g. {_display(root, changed[0])}"
            )
        else:
            newest_mtime, newest = newer[0]
            reason = (
                f"is older than {len(newer)} compile source(s), newest "
                f"{_display(root, newest)} {_utc(newest_mtime)}, and the {tool} build keeps "
                f"no content record to compare against; a `git checkout` after the build "
                f"rewrites source mtimes and counts the same way"
            )
        if not stale_allowed:
            _fail(
                f"model {_display(root, model)} (built {_utc(model_mtime)}) {reason}: "
                f"rebuild (run_dv.py --rebuild / drop --stage sim). To run anyway export "
                f"{_ALLOW_STALE_ENV}=1, which stamps model_stale_allowed=true into the log."
            )
        cocotb.log.warning(
            "[BUILD-MODEL-IDENTITY] stale model allowed: %s %s; this log cannot serve as evidence",
            _display(root, model),
            reason,
        )
    _MODEL_IDENTITY_DONE.append(line)
    return line


class _EvidenceRecorder:
    """Collect the named evidence a run emits, by watching every log record.

    Sequences report each graded contract as a ``CHK-<ID>: ...`` line. Most log
    it through ``cocotb.log``; tests and env components log through their pyuvm
    logger, which does not propagate to the root handler, so a filter on any one
    logger would miss part of the run. The log-record factory sees every record
    regardless of logger, so that is where the IDs are read. Reading them from
    the records keeps the log line the single source of the ID -- a separate
    registration call could drift from what the log actually carries.

    Only a token at the start of the message counts: prose that mentions a
    check ("... the byte verdict is CHK-I2C-...") is not an emission.
    """

    _CHK = re.compile(r"^\s*(CHK-[A-Za-z0-9][A-Za-z0-9_-]*)\b")

    # Emitted by every run's bring-up (smc_base_test and SmcDualHarness), before
    # the scenario: the model identity line and the probe positive controls
    # ``run_phase`` executes. Counted in ``observed`` but excluded from ``own``,
    # so a leaf cannot satisfy the gate on bring-up alone.
    BASE_IDS = frozenset({"CHK-BUILD-MODEL-IDENTITY"})
    BASE_PREFIXES = ("CHK-PROBE-",)

    # Leaves that emit no CHK-* line of their own, with the channel each one
    # grades through instead. Every entry is a LOGGING gap, not a verification
    # gap: each grades through sequence-level asserts, the scoreboard's
    # ``expected=`` compares, or a protocol-VIP record with a stimulus floor,
    # and none is a clean exit that checks nothing. Naming them is what lets the
    # gate below be unconditional for every other leaf.
    #
    # owner: SMC DV. opened: 2026-09-13, from the leaves that emitted no token
    # of their own at introduction. review_date: NO_OWN_EVIDENCE_REVIEW_DATE.
    # Closes when empty. Keys must stay inside NO_OWN_EVIDENCE_CEILING (the
    # set at introduction); a new name fails the run. To remove an entry, make
    # the check that already runs log a ``CHK-<ID>:`` line where it happens --
    # in the sequence, not here.
    NO_OWN_EVIDENCE = {
        # Scoreboard protocol-VIP record with a stimulus floor, plus expected=
        # compares on every CSR read the sequence issues.
        "smc_filter_field_sweep_test": "protocol-VIP floor and scoreboard compares",
        "smc_gpio_ctrl_full_sweep_test": "protocol-VIP floor and scoreboard compares",
        "smc_gpio_intf_full_sweep_test": "protocol-VIP floor and scoreboard compares",
        "smc_i2c_multi_instance_test": "protocol-VIP floor and scoreboard compares",
        "smc_mailbox_inbound_test": "protocol-VIP floor and scoreboard compares",
        "smc_occp_sanity_secure_error_test": "protocol-VIP floor and sequence asserts",
        "smc_register_boundary_depth_test": "protocol-VIP floor and scoreboard compares",
        "smc_register_sanity_test": "protocol-VIP floor and scoreboard compares",
        "smc_spi_pad_bfm_test": "protocol-VIP floor and sequence asserts",
        "smc_uart_loopback_test": "protocol-VIP floor and sequence asserts",
        "smc_xvisor_remap_test": "protocol-VIP floor and scoreboard compares",
        # Asserts in the sequence the leaf starts; the log line carries no ID.
        "smc_flr_sanity_test": "sequence asserts, unlabelled",
        "smc_gpio_irq_type_matrix_test": "sequence asserts, unlabelled",
        "smc_gpio_output_driveback_test": "sequence asserts, unlabelled",
        "smc_smbus_alert_ara_test": "in-leaf asserts on sequence flags, unlabelled",
        # Asserts in the leaf on the scoreboard's memory-model compare counters.
        "smc_output_fabric_wr_rd_responder_test": "in-leaf asserts, unlabelled",
        # Sequence asserts; the protocol-VIP record it books is an activity
        # stamp (csr_accesses=0, auto_evidence=True) and is not evidence.
        "smc_octs_dual_sync_test": "sequence asserts, unlabelled",
    }

    # Past this date, ``_finalize_evidence`` warns on every run while the set is
    # non-empty. Move it only after re-reading each entry that remains.
    NO_OWN_EVIDENCE_REVIEW_DATE = "2026-10-15"

    # Set at introduction. ``NO_OWN_EVIDENCE`` may lose keys, never gain them.
    NO_OWN_EVIDENCE_CEILING = frozenset(
        {
            "smc_dma_sanity_test",
            "smc_filter_field_sweep_test",
            "smc_flr_sanity_test",
            "smc_gpio_ctrl_full_sweep_test",
            "smc_gpio_intf_full_sweep_test",
            "smc_gpio_irq_type_matrix_test",
            "smc_gpio_output_driveback_test",
            "smc_i2c_multi_instance_test",
            "smc_mailbox_inbound_test",
            "smc_mailbox_multi_instance_test",
            "smc_occp_sanity_secure_error_test",
            "smc_octs_dual_sync_test",
            "smc_output_fabric_slverr_inject_test",
            "smc_output_fabric_wr_rd_responder_test",
            "smc_register_boundary_depth_test",
            "smc_register_sanity_test",
            "smc_smbus_alert_ara_test",
            "smc_spi_pad_bfm_test",
            "smc_uart_loopback_test",
            "smc_xvisor_remap_test",
        }
    )

    def __init__(self) -> None:
        self.seen: set[str] = set()
        self._previous_factory = logging.getLogRecordFactory()

    def install(self) -> None:
        logging.setLogRecordFactory(self._factory)

    def _factory(self, *args, **kwargs) -> logging.LogRecord:
        record = self._previous_factory(*args, **kwargs)
        try:
            message = record.getMessage()
        except Exception:  # a broken format string is the caller's failure, not ours
            return record
        match = self._CHK.match(message)
        if match:
            self.seen.add(match.group(1))
        return record

    @classmethod
    def is_base(cls, check_id: str) -> bool:
        return check_id in cls.BASE_IDS or check_id.startswith(cls.BASE_PREFIXES)


class smc_base_test(uvm_test):
    """Shared SMC OSS test: env build, clock/reset bring-up, scenario hook.

    A concrete test may set the class attribute ``protocol_vip_kind`` (a
    ``SmcProtocolVipKind``) to auto-stamp a protocol VIP activity record after
    ``run_scenario``; this is preferred over adding the test to the
    ``_PROTOCOL_VIP_TESTS`` map below. Set ``auto_protocol_vip = False`` to skip.

    The auto stamp is an *activity record*, never protocol evidence: it carries
    only the SYS-AXI transaction count the scoreboard measured and is booked in
    the scoreboard's separate ``protocol_vip_auto`` bin. A scenario that wants a
    real protocol VIP record sets ``auto_protocol_vip = False`` and calls
    ``record_protocol_vip(..., csr_accesses=<measured>,
    min_csr_accesses=<stimulus floor>, details=<scenario specific>)``.
    ``min_csr_accesses`` is **mandatory** on that path -- see
    :meth:`record_protocol_vip`.

    A test whose proof path contains an idle-zero compare on a ``tb_top``
    observability probe declares the matching positive control(s) in
    ``probe_positive_controls``; ``run_phase`` runs them before
    ``run_scenario`` so the scoreboard's idle legs in this test are backed by a
    same-run observation of the same probe at 1
    (``[NEGATIVE-NEEDS-POSITIVE-CONTROL]``). Legal names are the keys of
    ``seq_lib.smc_probe_positive_control.PROBE_CONTROLS``.
    """

    # Optional per-test override; None => fall back to the name map.
    protocol_vip_kind = None

    # Probe positive controls to run before run_scenario (see class docstring).
    probe_positive_controls: tuple[str, ...] = ()

    # Evidence gate. A clean exit is not a pass: a scenario whose stimulus
    # stopped reaching the DUT compares nothing, asserts nothing, and returns
    # normally. Every graded contract is reported as a ``CHK-<ID>:`` line, so
    # the base class counts what this run actually emitted and fails a silent
    # one (see ``_finalize_evidence``).
    #
    #   required_evidence -- IDs this test must emit. Missing any one fails.
    #   min_evidence      -- fewest distinct IDs of the test's OWN (lines the
    #                        base class emits do not count). 0 disables it.
    required_evidence: tuple[str, ...] = ()
    min_evidence = 0

    # Provenance gate. The identity line names the commit of the checkout the
    # run's sources come from; with uncommitted changes on the inputs of the
    # model or the bench that commit does not describe what ran, so the run
    # fails. A test may set this False; the operator may export
    # SMC_DV_ALLOW_DIRTY=1. Either way the line then carries
    # ``dirty_allowed=true``. The model-staleness gate has no per-test switch;
    # SMC_DV_ALLOW_STALE_MODEL=1 is the only opt-out.
    require_clean_tree = True

    @staticmethod
    def random_seed() -> int:
        return int(os.environ.get("RANDOM_SEED", "1"), 0)

    def build_phase(self) -> None:
        self._evidence = _EvidenceRecorder()
        self._evidence.install()
        self.cfg = SmcEnvCfg("cfg")
        self.cfg.randomize_timing(self.random_seed())
        self.logger.info(
            "SMC timing: ref=%dns smc=%dns periph=%dns (seed=%d)",
            self.cfg.ref_clk_period_ns,
            self.cfg.smc_clk_period_ns,
            self.cfg.periph_clk_period_ns,
            self.random_seed(),
        )
        ConfigDB().set(None, "*", "cfg", self.cfg)
        self.env = SmcEnv("env", self)

    async def start_seq(self, seq, sequencer=None) -> None:
        seq.cfg = self.env.cfg
        seq.env = self.env
        if sequencer is None:
            sequencer = self.env.i2c_agent.sequencer
        await seq.start(sequencer)

    async def record_protocol_vip(
        self,
        kind: SmcProtocolVipKind,
        scenario: str,
        *,
        csr_accesses: int = 0,
        timeouts: int | None = None,
        proxy: bool = True,
        details: str = "",
        expected_bytes: bytes | None = None,
        observed_bytes: bytes | None = None,
        min_csr_accesses: int | None = None,
        fabric_accesses: int | None = None,
        min_fabric_accesses: int = 0,
        fabric_access_label: str = "",
        fabric_bus: str = "JTAG AXI",
        auto_evidence: bool = False,
    ) -> None:
        """Record a protocol VIP evidence item.

        ``min_csr_accesses`` turns ``csr_accesses`` from a printed statistic
        into a fail-capable floor: pass the number of CSR accesses the
        scenario's stimulus must have issued and the scoreboard fails the record
        when the measured count falls short.

        It is **mandatory** for a scenario-recorded item (``auto_evidence`` left
        False). Without a floor every assert the scoreboard applies to the
        record reduces to a constant (``N >= 0``), yet the item is still logged
        as "protocol VIP check #k", books a ``protocol_vip`` coverage bin, and
        can single-handedly satisfy ``check_phase``'s minimum-activity gate --
        i.e. a record that cannot fail presented as a check
        (``[NO-ALWAYS-PASS-CHECKER]`` / ``[NO-ZERO-ACTIVITY-PASS]``). Omitting
        it raises here, and the scoreboard refuses the item independently.

        The floor must be an independent constant written out at the call site,
        **not** read back from the sequence's own counter: a floor that shrinks
        with the sequence cannot catch a sequence that silently stops short.

        Non-CSR fabric traffic (JTAG-AXI writes and reads, output-fabric beats)
        is reported separately from ``csr_accesses`` so it is never mislabelled
        as CSR traffic, with its own ``min_fabric_accesses`` floor and a
        ``fabric_access_label`` naming what it is. **The observed count is
        measured here, not passed in**: it is read from the scoreboard's per-bus
        tally for ``fabric_bus`` (``SmcScoreboard.axi_accesses_by_bus``, stamped
        by the driver that completed each access). A call site that passes the
        floor constant as its own observation makes the scoreboard's
        ``fabric_accesses >= min_fabric_accesses`` assert a constant relation
        (``C >= C``) while the kept log advertises a measured-vs-minimum compare
        (``[NO-ALWAYS-PASS-CHECKER]``); measuring it here means no call site can
        reintroduce that shape.

        ``fabric_accesses`` is consequently an *optional exact expectation*, not
        the observation: when given, the measured count must equal it exactly, so
        a literal ``fabric_accesses=4`` at a call site becomes a real
        expectation-vs-measurement compare instead of a tautology.

        ``timeouts`` defaults to **None** = "not measured on this path" and
        prints as ``n/a``. Printing 0 for an unmeasured counter manufactures a
        clean-looking statistic and makes the scoreboard's
        ``timeouts <= csr_accesses`` relation a second constant, so a literal 0
        must be passed explicitly and only by a path that really measured zero
        timeouts (``[EXACT-EXPECTATION]``).
        """
        if auto_evidence:
            # An auto stamp is booked in the scoreboard's activity bin, never as
            # a check, so it carries no floor by construction.
            assert min_csr_accesses is None, (
                "auto_evidence records are activity stamps and must not carry min_csr_accesses"
            )
            min_csr_accesses = 0
        else:
            assert min_csr_accesses is not None, (
                f"record_protocol_vip({kind.value}, {scenario!r}): a "
                f"scenario-recorded protocol VIP item needs an explicit "
                f"min_csr_accesses. Without a floor every assert on the record "
                f"reduces to a constant while the item is still logged and "
                f"counted as a protocol VIP *check* ([NO-ALWAYS-PASS-CHECKER]). "
                f"Pass the CSR-access floor this scenario's stimulus must "
                f"issue, or set auto_evidence=True to book it as an activity "
                f"stamp instead."
            )
            assert min_csr_accesses > 0 or expected_bytes is not None, (
                f"record_protocol_vip({kind.value}, {scenario!r}): "
                f"min_csr_accesses=0 is only legal together with a byte golden "
                f"(expected_bytes), which is then what makes the record "
                f"fail-capable. A scenario with neither CSR-access floor nor "
                f"golden has nothing on the record that can fail and must be "
                f"booked with auto_evidence=True instead."
            )
        assert min_fabric_accesses >= 0, "fabric access floor must be non-negative"
        assert not (min_fabric_accesses and not fabric_access_label), (
            "min_fabric_accesses needs fabric_access_label naming the traffic"
        )
        # MEASURE the fabric-access count here (see docstring): the observed
        # left-hand side of the scoreboard's floor assert must come from what the
        # DUT completed, never from the same constant as the floor.
        measured_fabric = self.env.scoreboard.axi_accesses_by_bus.get(fabric_bus, 0)
        if auto_evidence and not fabric_access_label:
            # An activity stamp makes no fabric claim; leave the field out of the
            # record rather than printing an unlabelled count beside min=0.
            measured_fabric = 0
        if min_fabric_accesses or fabric_accesses is not None:
            known_buses = sorted(self.env.scoreboard.axi_accesses_by_bus)
            assert fabric_bus in self.env.scoreboard.axi_accesses_by_bus, (
                f"record_protocol_vip({kind.value}, {scenario!r}): "
                f"fabric_bus={fabric_bus!r} completed no AXI access in this run "
                f"(buses seen: {known_buses or 'none'}). A fabric floor cannot be "
                f"checked against a port the scoreboard never observed."
            )
        if fabric_accesses is not None:
            assert measured_fabric == fabric_accesses, (
                f"record_protocol_vip({kind.value}, {scenario!r}): the scenario "
                f"declared {fabric_accesses} {fabric_access_label or 'fabric'} "
                f"access(es) but the scoreboard measured {measured_fabric} "
                f"completed access(es) on {fabric_bus}. `fabric_accesses` is an "
                f"exact expectation checked against the measurement, not the "
                f"observation itself."
            )
        item = SmcProtocolVipItem(f"{kind.value}_{scenario}")
        item.kind = kind
        item.scenario = scenario
        item.proxy = proxy
        item.csr_accesses = csr_accesses
        item.timeouts = timeouts
        item.details = details
        item.expected_bytes = expected_bytes
        item.observed_bytes = observed_bytes
        item.min_csr_accesses = min_csr_accesses
        item.fabric_accesses = measured_fabric
        item.min_fabric_accesses = min_fabric_accesses
        item.fabric_access_label = fabric_access_label
        item.fabric_access_source = f"measured: SmcScoreboard.axi_accesses_by_bus[{fabric_bus!r}]"
        item.auto_evidence = auto_evidence
        await _OneShot(item, "protocol_vip_os").start(self.env.protocol_vip_agent.sequencer)

    async def _bring_up(self) -> None:
        dut = cocotb.top
        self.logger.info("Bringing up SMC clocks and cold reset")
        # Run-scoped probe-liveness ledger. The watcher is passive (reads only)
        # and records which tb_top observability probes this run's DUT actually
        # drove to 1; SmcScoreboard consults it to decide whether an idle-zero
        # leg is a real compare or an OBSERVED-ONLY diagnostic
        # ([NEGATIVE-NEEDS-POSITIVE-CONTROL]). It exits as soon as every watched
        # probe has been credited.
        reset_probe_ledger()
        dut.powergood_i.value = 0
        dut.rst_cold_ni.value = 0
        if hasattr(dut, "tb_i2c0_scl_ext_low"):
            dut.tb_i2c0_scl_ext_low.value = 0
        if hasattr(dut, "tb_i2c0_sda_ext_low"):
            dut.tb_i2c0_sda_ext_low.value = 0
        if hasattr(dut, "tb_i3c0_scl_ext_low"):
            dut.tb_i3c0_scl_ext_low.value = 0
        if hasattr(dut, "tb_i3c0_sda_ext_low"):
            dut.tb_i3c0_sda_ext_low.value = 0
        # DFT test_en defaults deasserted (functional mode).
        if hasattr(dut, "tb_test_en_i"):
            dut.tb_test_en_i.value = 0
        for name in (
            "tb_zeroer_state_inject_en",
            "tb_efuse_program_state_inject_en",
            "tb_efuse_read_state_inject_en",
        ):
            if hasattr(dut, name):
                getattr(dut, name).value = 0
        for name in (
            "tb_zeroer_state_inject",
            "tb_efuse_program_state_inject",
            "tb_efuse_read_state_inject",
            "tb_efuse_read_error_inject",
        ):
            if hasattr(dut, name):
                getattr(dut, name).value = 0
        if hasattr(dut, "tb_cpu_jtag_tck"):
            dut.tb_cpu_jtag_tck.value = 0
            dut.tb_cpu_jtag_tms.value = 1
            dut.tb_cpu_jtag_tdi.value = 0
            dut.tb_cpu_jtag_reset.value = 1
        if hasattr(dut, "tb_sep_mailbox_interrupts"):
            dut.tb_sep_mailbox_interrupts.value = 0
        if hasattr(dut, "tb_gpio_ext_drive_en"):
            dut.tb_gpio_ext_drive_en.value = 0
            dut.tb_gpio_ext_drive_value.value = 0
        if hasattr(dut, "tb_boot_stall_jtag_ovrd_i"):
            dut.tb_boot_stall_jtag_ovrd_i.value = 0
            dut.tb_boot_stall_jtag_val_i.value = 0
        if hasattr(dut, "tb_sep_wdt_reset_n"):
            dut.tb_sep_wdt_reset_n.value = 1
        if hasattr(dut, "tb_ndmreset_request"):
            dut.tb_ndmreset_request.value = 0
        if hasattr(dut, "tb_cfg_flr_pf_active"):
            dut.tb_cfg_flr_pf_active.value = 0
        if hasattr(dut, "tb_temp_interrupt_i"):
            dut.tb_temp_interrupt_i.value = 0
        if hasattr(dut, "tb_ext_interrupt_0_i"):
            dut.tb_ext_interrupt_0_i.value = 0
        if hasattr(dut, "tb_captured_straps"):
            dut.tb_captured_straps.value = 0
        if hasattr(dut, "tb_ss_reset_complete"):
            dut.tb_ss_reset_complete.value = 0xFFFFFFFF
        if hasattr(dut, "tb_jtag_reset_ctrl"):
            dut.tb_jtag_reset_ctrl.value = 0
        if hasattr(dut, "tb_sep_axi_b_hold"):
            dut.tb_sep_axi_b_hold.value = 0
        if hasattr(dut, "tb_sep_axi_r_hold"):
            dut.tb_sep_axi_r_hold.value = 0
        if hasattr(dut, "tb_sep_axi_r_drop"):
            dut.tb_sep_axi_r_drop.value = 0
        if hasattr(dut, "tb_sys_axi_r_hold"):
            dut.tb_sys_axi_r_hold.value = 0
        if hasattr(dut, "tb_sys_axi_r_drop"):
            dut.tb_sys_axi_r_drop.value = 0
        if hasattr(dut, "tb_output_axi_resp_hold"):
            dut.tb_output_axi_resp_hold.value = 0
        if hasattr(dut, "tb_mem_repair_abort"):
            dut.tb_mem_repair_abort.value = 0
        if hasattr(dut, "tb_mbist_abort"):
            dut.tb_mbist_abort.value = 0
        if hasattr(dut, "tb_uart0_rx_ext_drive"):
            dut.tb_uart0_rx_ext_drive.value = 1  # UART idle-high
        # Product lc_state_i idle = complementary TEST_DEV ({~0, 0} = 0xF0).
        if hasattr(dut, "tb_lc_state"):
            dut.tb_lc_state.value = 0xF0
        # SPI octal pads (U2-1): idle-safe — enable off, CS deasserted, OE/IE
        # negated high (pads not driving). OcahSpiFlash adapter is U2-2.
        if hasattr(dut, "tb_spi_enable"):
            dut.tb_spi_enable.value = 0
            dut.tb_spi_clk.value = 0
            dut.tb_spi_txd.value = 0
            dut.tb_spi_cs_n.value = 1
            dut.tb_spi_cs_oe_n.value = 1
            dut.tb_spi_cs_ie_n.value = 1
            dut.tb_spi_clk_ie_n.value = 1
            dut.tb_spi_clk_oe_n.value = 1
            dut.tb_spi_dqs_ie_n.value = 1
            dut.tb_spi_dqs_oe_n.value = 1
            dut.tb_spi_dq_ie_n.value = 0xFF
            dut.tb_spi_dq_oe_n.value = 0xFF
            if hasattr(dut, "tb_spi_miso_ext"):
                dut.tb_spi_miso_ext.value = 0
        # Telemetry ATB (U4-6): every lifted receiver idles quiet, receiver 0
        # with AFREADY high. These are the values the tie-offs they replaced
        # presented, so a test that drives none of them is unaffected.
        if hasattr(dut, "tb_telemetry0_atvalid"):
            dut.tb_telemetry0_atdata.value = 0
            dut.tb_telemetry0_atid.value = 0
            dut.tb_telemetry0_atvalid.value = 0
            dut.tb_telemetry0_afready.value = 1
        for telem_rx in (1, 2):
            if hasattr(dut, f"tb_telemetry{telem_rx}_atvalid"):
                getattr(dut, f"tb_telemetry{telem_rx}_atdata").value = 0
                getattr(dut, f"tb_telemetry{telem_rx}_atid").value = 0
                getattr(dut, f"tb_telemetry{telem_rx}_atvalid").value = 0
        # AVSBus sdata (pad 51): idle-high (pull-up / no ACK).
        if hasattr(dut, "tb_avs_sdata_ext"):
            dut.tb_avs_sdata_ext.value = 1
        # OCTS dual-chiplet: default PRIMARY; secondary pad inject idle-low.
        if hasattr(dut, "tb_chiplet_is_primary"):
            dut.tb_chiplet_is_primary.value = 1
        if hasattr(dut, "tb_octs_sync_load_ext"):
            dut.tb_octs_sync_load_ext.value = 0
        if hasattr(dut, "tb_octs_cnt_credit_ext"):
            dut.tb_octs_cnt_credit_ext.value = 0
        # Cool reset starts deasserted (released) so the cool-domain logic
        # does not block the cold-reset bring-up. Tests can drive it low via
        # the reset agent COOL_RST_LO op.
        dut.rst_cool_ni.value = 1
        cocotb.start_soon(watch_probe_liveness(dut))
        # Firmware virtual console (scratch 2); decoded lines go to the log as
        # they complete.
        self.virt_console = VirtConsole(dut.tb_cpu_scratch2, "smc-fw")
        cocotb.start_soon(self.virt_console.run())
        # The SYS_OUT responder exists before the first clock edge so the
        # boundary's READY signals are driven from time zero. It follows the
        # SMC primary reset: a cool reset drops the outstanding responses
        # instead of returning them into the reset CPU cluster.
        self.cfg.sys_out_mem = OcahAxiSlaveAgent(
            SYS_OUT_AXI_GEOMETRY.bus(dut.u_output_axi_if),
            dut.clk_smc_i,
            dut.rst_primary_smc_clk_no,
            reset_active_level=False,
            size=SYS_OUT_MEM_SIZE,
            name="smc_sys_out",
        ).sequence
        cocotb.start_soon(Clock(dut.clk_ref_i, self.cfg.ref_clk_period_ns, units="ns").start())
        cocotb.start_soon(Clock(dut.clk_smc_i, self.cfg.smc_clk_period_ns, units="ns").start())
        cocotb.start_soon(
            Clock(dut.clk_periph_i, self.cfg.periph_clk_period_ns, units="ns").start()
        )

        await ClockCycles(dut.clk_ref_i, 10)
        self.logger.info("Asserting powergood")
        dut.powergood_i.value = 1
        await ClockCycles(dut.clk_ref_i, 10)
        self.logger.info("Releasing cold reset")
        dut.rst_cold_ni.value = 1
        # Completion gate = the observed reset chain releasing, not a delay.
        released_at = await self._await_cold_reset_release()
        # Post-release quiet margin: the handshake above is the gate, this is
        # the remainder of the same window, and downstream tests' timing depends
        # on its length. Tests needing the warm/fuse domain wait on it explicitly
        # via smc_base_test_seq.wait_fuse_sense_done.
        remaining = self.cfg.post_reset_settle_cycles - released_at
        if remaining > 0:
            await ClockCycles(dut.clk_ref_i, remaining)
        self.cfg.reset_done.set()

    # Top-level reset observables whose release ends cold bring-up.
    _COLD_RELEASE_PROBES = (
        "powergood_stable_o",
        "rst_cold_stable_ref_clk_no",
        "rst_primary_ref_clk_no",
        "rst_primary_smc_clk_no",
    )

    async def _await_cold_reset_release(self) -> int:
        """Bounded wait until the cold reset chain is observed released.

        Bring-up is not gated by a bare
        ``ClockCycles(clk_ref_i, post_reset_settle_cycles)``: a magic count
        passes on luck of sim timing and silently lets every later SAMPLE run
        against a still-asserted reset chain ([NO-BLIND-DELAY-SYNC]). Expiry
        here is a testcase failure with last-state diagnostics
        ([TIMEOUT-MUST-FAIL]). Returns the number of ``clk_ref_i`` cycles waited.
        """
        dut = cocotb.top
        bound = max(self.cfg.post_reset_settle_cycles, 2000)
        for cycle in range(bound + 1):
            vals = [getattr(dut, p).value for p in self._COLD_RELEASE_PROBES]
            if all(v.is_resolvable and int(v) == 1 for v in vals):
                self.logger.info(
                    "Cold reset chain released %d clk_ref_i cycles after rst_cold_ni=1 (%s)",
                    cycle,
                    ", ".join(f"{p}={int(v)}" for p, v in zip(self._COLD_RELEASE_PROBES, vals)),
                )
                return cycle
            await ClockCycles(dut.clk_ref_i, 1)
        last = ", ".join(f"{p}={getattr(dut, p).value}" for p in self._COLD_RELEASE_PROBES)
        raise AssertionError(
            f"cold reset chain not released within {bound} clk_ref_i cycles of "
            f"rst_cold_ni=1; last observed {last}"
        )

    async def run_scenario(self) -> None:
        raise NotImplementedError

    async def run_probe_positive_controls(self) -> None:
        """Run this test's declared probe positive controls (see class doc).

        Each control drives real frontdoor stimulus, requires the probe to be
        observed at 1 inside a bounded window (expiry = failure), restores idle
        and requires the probe back at 0. It runs before ``run_scenario`` so
        every idle-zero leg the scenario books already has its liveness credit.
        The controls dispatch no agent SAMPLE items, so per-type scoreboard
        counter gates in the scenarios are unaffected.
        """
        if not self.probe_positive_controls:
            return
        from seq_lib.smc_probe_positive_control import SmcProbePositiveControlSeq

        seq = SmcProbePositiveControlSeq("probe_positive_control_seq", self.probe_positive_controls)
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)

    async def run_phase(self) -> None:
        self.raise_objection()
        # First line of every kept log's run phase: what RTL this run simulated
        # ([BUILD-MODEL-IDENTITY]). Raises rather than logging a placeholder.
        log_build_model_identity(require_clean_tree=self.require_clean_tree)
        await self._bring_up()
        try:
            await self.run_probe_positive_controls()
            await self.run_scenario()
        except Exception:  # noqa: BLE001 -- re-raised once the CPU state is in the log
            self.virt_console.flush()
            self.env.cpu_trace_mon.dump_diagnostics(logging.ERROR)
            raise
        test_name = type(self).__name__
        # Prefer the per-test class attribute; fall back to the name map.
        kind = self.protocol_vip_kind or _PROTOCOL_VIP_TESTS.get(test_name)
        if getattr(self, "auto_protocol_vip", True) and kind is not None:
            # Auto stamp, NOT evidence of protocol behaviour. It carries only
            # measured numbers (the SYS-AXI transaction count the scoreboard
            # observed), declares `auto_evidence=True` so the scoreboard books
            # it as an activity stamp in its own coverage bin rather than a
            # check, and reports timeouts as "not measured". A stamp with a
            # canned count could not fail ([NO-ALWAYS-PASS-CHECKER]).
            #
            # A scenario that wants a real protocol VIP record sets
            # `auto_protocol_vip = False` and calls record_protocol_vip() with
            # its own measured counts plus `min_csr_accesses=<stimulus floor>`.
            observed_sys_axi = self.env.scoreboard.sys_axi_checks_seen
            await self.record_protocol_vip(
                kind,
                test_name,
                csr_accesses=observed_sys_axi,
                timeouts=None,
                auto_evidence=True,
                details=(
                    f"auto activity stamp: {observed_sys_axi} SYS-AXI "
                    "transactions observed by the scoreboard during this "
                    "scenario; no protocol-level assertion performed here"
                ),
            )
        self._finalize_evidence()
        self.drop_objection()

    def _finalize_evidence(self) -> None:
        """Report the evidence this run produced, and grade it.

        Runs only after run_scenario() returns normally. A test that already
        failed raised, and this must not turn that into a different complaint.

        ``own`` excludes the lines smc_base_test emits itself (the model
        identity line and the probe positive controls), so the gate grades what
        the leaf proved rather than what bring-up logged.
        """
        recorder = getattr(self, "_evidence", None)
        seen = sorted(recorder.seen) if recorder else []
        own = [check_id for check_id in seen if not _EvidenceRecorder.is_base(check_id)]
        required = tuple(self.required_evidence)
        missing = [check_id for check_id in required if check_id not in seen]
        test_name = type(self).__name__
        extra = set(_EvidenceRecorder.NO_OWN_EVIDENCE) - _EvidenceRecorder.NO_OWN_EVIDENCE_CEILING
        if extra:
            raise AssertionError(
                "NO_OWN_EVIDENCE grew: "
                + ", ".join(sorted(extra))
                + " -- this list may only shrink"
            )
        review_date = date.fromisoformat(_EvidenceRecorder.NO_OWN_EVIDENCE_REVIEW_DATE)
        if _EvidenceRecorder.NO_OWN_EVIDENCE and datetime.now(tz=timezone.utc).date() > review_date:
            self.logger.warning(
                "NO_OWN_EVIDENCE review date %s has passed with %d leaves still exempt; "
                "re-read each entry, then close it or move the date",
                review_date,
                len(_EvidenceRecorder.NO_OWN_EVIDENCE),
            )

        self.logger.info(
            "EVIDENCE_SUMMARY test=%s observed=%d own=%d required=%d missing=%d ids=%s",
            test_name,
            len(seen),
            len(own),
            len(required),
            len(missing),
            ",".join(seen) or "-",
        )

        problems: list[str] = []
        if not own and test_name not in _EvidenceRecorder.NO_OWN_EVIDENCE:
            problems.append(
                "no CHK-* line of its own -- a run that grades nothing cannot be a "
                "pass. If this leaf's checks live in its sequence, log them there; "
                "if it genuinely checks nothing, that is the finding"
            )
        if self.min_evidence and len(own) < self.min_evidence:
            problems.append(
                f"{len(own)} distinct CHK-* line(s) of its own, "
                f"expected at least {self.min_evidence}"
            )
        if missing:
            problems.append("never emitted: " + ", ".join(missing))
        if problems:
            raise AssertionError(
                f"EVIDENCE FAIL {test_name}: "
                + "; ".join(problems)
                + " -- the run exited cleanly without grading what it claims to grade"
            )
