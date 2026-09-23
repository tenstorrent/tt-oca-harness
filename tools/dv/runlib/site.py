# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Site-local override layer for the tool and executor registries.

One git-ignored ``hw/common/dv/configs/site.local.toml``, or the file named by ``OCAH_DV_SITE``,
merges over ``simulators.toml`` and ``executors.toml``: a deployment renames a tool binary,
wraps every tool command in a launcher (a container), sources an environment hook before the
tool starts, adds a tool table the checked-in registry lacks, or names the formal config a
companion checkout owns for one DUT. ``runlib.cli.load_registries`` applies the layer once, so
``--validate-configs``, ``--doctor``, ``--dry-run``, and the run path resolve one merged view.
Nothing but the site file itself, or the environment variable, activates the layer.

Layout of a site file::

    schema_version = 1

    [simulators.verilator]
    binary = "verilator-5.036"
    setup_hook = "verilator.env"          # relative to the site file

    [simulators.vcs]
    launcher = ["docker", "exec", "-i", "eda", "env", "-C", "/work"]
    extra_env = { VCS_HOME = "/opt/vcs" }

    [duts.dtp]
    formal_cfg = "nonfree/hw/sys/dtp/dv/dtp_formal_cfg.toml"

    [executors.lsf]                       # a complete schema-2 cluster table, or per-key
    kind = "cluster"                      # overrides on one the registry declares
    driver = "lsf"
    binaries = ["bsub", "bjobs", "bhist", "bkill"]
    submit_argv = ["bsub", ["-q", "{queue}"], "{script}"]
    query_argv = ["bjobs", "-json", "-o", "jobid stat exit_code", "{job_ids_argv}"]
    cancel_argv = ["bkill", "{job_ids_argv}"]
    setup_hook = "lsf.env"                # relative to the site file
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import (
    CLUSTER_EXECUTOR_KEYS,
    CLUSTER_EXECUTOR_V1_KEYS,
    SITE_ONLY_TOOL_KEYS,
    as_str_list,
    load_toml,
    validate_allowed_keys,
    validate_env_table,
    validate_executor_registry,
    validate_formal_argv_template,
    validate_simulator_registry,
)
from .models import ConfigError
from .paths import configs_root, repo_rel

SITE_FILE_NAME = "site.local.toml"
SITE_ENV = "OCAH_DV_SITE"
SITE_SCHEMA_VERSION = 1
SITE_TOP_KEYS = {"schema_version", "description", "simulators", "executors", "duts"}
# Keys a site may set on a tool table the checked-in registry declares; each replaces the
# checked-in value whole.
SITE_TOOL_KEYS = {"binary", "launcher", "argv", "license_env", "extra_env", "setup_hook"}
# Every data key of an executor table; `kind` stays with the registry.
SITE_EXECUTOR_KEYS = (CLUSTER_EXECUTOR_KEYS | CLUSTER_EXECUTOR_V1_KEYS) - {"kind"}
SITE_DUT_KEYS = {"formal_cfg"}
SETUP_HOOK_TIMEOUT_SEC = 120
# Shell bookkeeping a sourced hook changes without exporting anything.
_HOOK_NOISE_VARS = {"_", "SHLVL", "PWD", "OLDPWD"}
_DUMP_ENV = (
    "import json, os, sys\n"
    "with open(sys.argv[1], 'w', encoding='utf-8') as handle:\n"
    "    json.dump(dict(os.environ), handle)\n"
)


@dataclass(frozen=True)
class SiteLayer:
    """The validated content of one site file."""

    path: Path
    # Repo-relative when the file sits inside the checkout, absolute otherwise.
    label: str
    simulators: dict[str, dict[str, Any]]
    executors: dict[str, dict[str, Any]]
    duts: dict[str, dict[str, Any]]

    @property
    def where(self) -> str:
        return f"site layer {self.label}"

    def formal_cfg(self, names: Iterable[str]) -> str | None:
        """The formal config the site names for the first DUT name in ``names`` it lists."""
        for name in names:
            entry = self.duts.get(name)
            if entry is not None:
                return str(entry["formal_cfg"])
        return None


@dataclass(frozen=True)
class ToolLaunch:
    """How one tool starts on this machine after the site layer is applied."""

    tool: str
    binary: str
    launcher: tuple[str, ...] = ()
    extra_env: Mapping[str, str] = field(default_factory=dict)
    setup_hook: Path | None = None

    @property
    def executable(self) -> str:
        """The program PATH must supply: the launcher's head when set, else the binary."""
        return self.launcher[0] if self.launcher else self.binary


def site_layer_path(root: Path, environ: Mapping[str, str] | None = None) -> Path | None:
    """The active site file: ``OCAH_DV_SITE`` when set, else the default file when present."""
    env = os.environ if environ is None else environ
    text = env.get(SITE_ENV, "").strip()
    if text:
        path = Path(text).expanduser().resolve()
        if not path.is_file():
            raise ConfigError(f"{SITE_ENV} names a missing site file: {path}")
        return path
    default = configs_root(root) / SITE_FILE_NAME
    return default if default.is_file() else None


def _tables(data: dict[str, Any], key: str, where: str) -> dict[str, dict[str, Any]]:
    section = data.get(key)
    if section is None:
        return {}
    if not isinstance(section, dict):
        raise ConfigError(f"{where}: [{key}] must be a table of tables")
    out: dict[str, dict[str, Any]] = {}
    for name, table in section.items():
        if not isinstance(table, dict):
            raise ConfigError(f"{where}: [{key}.{name}] must be a table")
        out[str(name)] = dict(table)
    return out


def _site_tool_table(table: dict[str, Any], where: str, site_dir: Path) -> dict[str, Any]:
    """Shape-check the keys only a site supplies and the overridable scalars."""
    out = dict(table)
    if "binary" in table and (not isinstance(table["binary"], str) or not table["binary"]):
        raise ConfigError(f"{where}.binary must be a non-empty string")
    if "launcher" in table:
        launcher = as_str_list(table["launcher"], f"{where}.launcher")
        if not launcher or not all(launcher):
            raise ConfigError(f"{where}.launcher must be a non-empty list of argv tokens")
    if "license_env" in table:
        as_str_list(table["license_env"], f"{where}.license_env")
    if "extra_env" in table:
        out["extra_env"] = validate_env_table(table["extra_env"], f"{where}.extra_env")
    if "setup_hook" in table:
        text = table["setup_hook"]
        if not isinstance(text, str) or not text:
            raise ConfigError(f"{where}.setup_hook must be a non-empty path")
        hook = Path(text).expanduser()
        if not hook.is_absolute():
            hook = site_dir / hook
        hook = hook.resolve()
        if not hook.is_file():
            raise ConfigError(f"{where}.setup_hook does not exist: {hook}")
        out["setup_hook"] = str(hook)
    if "argv" in table:
        validate_formal_argv_template(table["argv"], f"{where}.argv")
    return out


def _site_executor_table(table: dict[str, Any], where: str, site_dir: Path) -> dict[str, Any]:
    """Resolve an executor table's ``setup_hook`` against the site file, as tool tables do."""
    out = dict(table)
    if "setup_hook" in table:
        text = table["setup_hook"]
        if not isinstance(text, str) or not text:
            raise ConfigError(f"{where}.setup_hook must be a non-empty path")
        hook = Path(text).expanduser()
        if not hook.is_absolute():
            hook = site_dir / hook
        hook = hook.resolve()
        if not hook.is_file():
            raise ConfigError(f"{where}.setup_hook does not exist: {hook}")
        out["setup_hook"] = str(hook)
    return out


def load_site_layer(root: Path, environ: Mapping[str, str] | None = None) -> SiteLayer | None:
    """Load and shape-check the active site file; None when no site file is active."""
    path = site_layer_path(root, environ)
    if path is None:
        return None
    label = repo_rel(root, path) or str(path)
    where = f"site layer {label}"
    data = load_toml(path)
    validate_allowed_keys(data, SITE_TOP_KEYS, where)
    if data.get("schema_version", SITE_SCHEMA_VERSION) != SITE_SCHEMA_VERSION:
        raise ConfigError(f"{where}: schema_version must be {SITE_SCHEMA_VERSION}")
    simulators = {
        tool: _site_tool_table(table, f"{where} [simulators.{tool}]", path.parent)
        for tool, table in _tables(data, "simulators", where).items()
    }
    executors = {
        name: _site_executor_table(table, f"{where} [executors.{name}]", path.parent)
        for name, table in _tables(data, "executors", where).items()
    }
    duts = _tables(data, "duts", where)
    for name, entry in duts.items():
        entry_where = f"{where} [duts.{name}]"
        validate_allowed_keys(entry, SITE_DUT_KEYS, entry_where)
        text = entry.get("formal_cfg")
        if not isinstance(text, str) or not text:
            raise ConfigError(f"{entry_where}.formal_cfg must be a non-empty path")
    return SiteLayer(path=path, label=label, simulators=simulators, executors=executors, duts=duts)


def validate_site_duts(site: SiteLayer, known: Iterable[str]) -> None:
    """Every ``[duts.<name>]`` entry names a selectable DUT."""
    names = set(known)
    unknown = sorted(name for name in site.duts if name not in names)
    if unknown:
        raise ConfigError(
            f"{site.where}: [duts] names unknown DUT(s): {', '.join(unknown)} "
            f"(known: {', '.join(sorted(names)) or '<none>'})"
        )


def merged_simulators(base: dict[str, Any], site: SiteLayer | None) -> dict[str, Any]:
    """The tool registry with the site's tables merged in and re-validated.

    A table the registry declares accepts :data:`SITE_TOOL_KEYS` only; a table it lacks must be
    complete, and the registry schema validates it.
    """
    if site is None:
        return base
    merged = {name: dict(table) for name, table in base.items()}
    for tool, table in site.simulators.items():
        where = f"{site.where} [simulators.{tool}]"
        if tool in merged:
            validate_allowed_keys(table, SITE_TOOL_KEYS, where)
            merged[tool].update(table)
        else:
            merged[tool] = dict(table)
    validate_simulator_registry(merged, f"{site.where} (merged registry)")
    return merged


def merged_executors(base: dict[str, Any], site: SiteLayer | None) -> dict[str, Any]:
    """The executor registry with the site's tables merged in and re-validated."""
    if site is None:
        return base
    merged = {name: dict(table) for name, table in base.items()}
    for name, table in site.executors.items():
        where = f"{site.where} [executors.{name}]"
        if name in merged:
            validate_allowed_keys(table, SITE_EXECUTOR_KEYS, where)
            merged[name].update(table)
        else:
            merged[name] = dict(table)
    validate_executor_registry(merged, f"{site.where} (merged registry)")
    return merged


def tool_source(site: SiteLayer | None, tool: str, checked_in: bool) -> str:
    """Which file(s) supplied ``tool``'s table, for --doctor."""
    if site is None or tool not in site.simulators:
        return "simulators.toml"
    if not checked_in:
        return f"{site.label} (added)"
    keys = ", ".join(sorted(site.simulators[tool]))
    return f"simulators.toml + {site.label} ({keys})"


def site_summary(site: SiteLayer, checked_in_tools: Iterable[str]) -> str:
    """One line naming what the site layer changes, for the run log."""
    known = set(checked_in_tools)
    parts: list[str] = []
    tools = [
        f"{tool}({', '.join(sorted(table))})" if tool in known else f"{tool}(added)"
        for tool, table in site.simulators.items()
    ]
    if tools:
        parts.append("simulators: " + ", ".join(tools))
    if site.executors:
        parts.append("executors: " + ", ".join(site.executors))
    if site.duts:
        parts.append("duts: " + ", ".join(f"{name}(formal_cfg)" for name in site.duts))
    return f"site={site.label} " + ("; ".join(parts) if parts else "(no overrides)")


def tool_launch(simulators: Mapping[str, Any], tool: str) -> ToolLaunch:
    """The launch of ``tool`` from a (site-merged) registry; bare defaults for an unknown tool."""
    cfg = simulators.get(tool)
    if not isinstance(cfg, dict):
        return ToolLaunch(tool=tool, binary=tool)
    hook = cfg.get("setup_hook")
    extra_env = cfg.get("extra_env") or {}
    return ToolLaunch(
        tool=tool,
        binary=str(cfg.get("binary", tool)),
        launcher=tuple(as_str_list(cfg.get("launcher"), f"{tool}.launcher")),
        extra_env={str(name): str(value) for name, value in dict(extra_env).items()},
        setup_hook=Path(str(hook)) if hook else None,
    )


def launch_argv(launch: ToolLaunch, argv: list[str]) -> list[str]:
    """``argv`` behind the launcher prefix."""
    return [*launch.launcher, *argv]


def locate_tool(launch: ToolLaunch, env: Mapping[str, str] | None = None) -> str | None:
    """Path of the program this machine runs for ``launch``, or None when PATH lacks it.

    With a launcher the binary lives behind it, so the launcher's head is what PATH must
    supply.
    """
    source = os.environ if env is None else env
    return shutil.which(launch.executable, path=source.get("PATH"))


def _hook_environment(hook: Path, base: Mapping[str, str], tool: str) -> dict[str, str]:
    """The environment a bash shell holds after sourcing ``hook`` under ``base``."""
    bash = shutil.which("bash", path=base.get("PATH")) or shutil.which("bash")
    if bash is None:
        raise ConfigError(f"setup_hook for `{tool}` needs `bash` on PATH")
    with tempfile.TemporaryDirectory(prefix="ocah-setup-hook-") as tmp:
        out = Path(tmp) / "env.json"
        argv = [
            bash,
            "-c",
            '. "$1" && exec "$2" -c "$3" "$4"',
            "ocah-setup-hook",
            str(hook),
            sys.executable,
            _DUMP_ENV,
            str(out),
        ]
        try:
            proc = subprocess.run(
                argv,
                cwd=hook.parent,
                env=dict(base),
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=SETUP_HOOK_TIMEOUT_SEC,
            )
        except subprocess.TimeoutExpired as exc:
            raise ConfigError(
                f"setup_hook {hook} for `{tool}` exceeded {SETUP_HOOK_TIMEOUT_SEC}s"
            ) from exc
        if proc.returncode != 0 or not out.is_file():
            tail = " | ".join(proc.stdout.strip().splitlines()[-5:])
            raise ConfigError(
                f"setup_hook {hook} for `{tool}` exited {proc.returncode}"
                + (f": {tail}" if tail else "")
            )
        data = json.loads(out.read_text(encoding="utf-8"))
    return {str(name): str(value) for name, value in data.items()}


_HOOK_DELTA_CACHE: dict[
    tuple[str, tuple[tuple[str, str], ...]], tuple[dict[str, str], frozenset[str]]
] = {}


def setup_hook_delta(
    launch: ToolLaunch, ambient: Mapping[str, str]
) -> tuple[dict[str, str], frozenset[str]]:
    """(variables the hook exports or changes, variables it unsets), one run per hook."""
    if launch.setup_hook is None:
        return {}, frozenset()
    key = (str(launch.setup_hook), tuple(sorted(launch.extra_env.items())))
    cached = _HOOK_DELTA_CACHE.get(key)
    if cached is not None:
        return cached
    base = {**ambient, **launch.extra_env}
    hooked = _hook_environment(launch.setup_hook, base, launch.tool)
    changed = {
        name: value
        for name, value in hooked.items()
        if base.get(name) != value and name not in _HOOK_NOISE_VARS
    }
    removed = frozenset(
        name for name in base if name not in hooked and name not in _HOOK_NOISE_VARS
    )
    _HOOK_DELTA_CACHE[key] = (changed, removed)
    return changed, removed


def launch_env(
    launch: ToolLaunch,
    env: Mapping[str, str] | None = None,
    *,
    ambient: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """The environment a tool process receives: ``env`` with the site's exports applied.

    ``env`` is the stage's environment (the process environment when None) and ``ambient`` the
    process environment it was derived from. ``extra_env`` applies first, then whatever the
    ``setup_hook`` exports, changes, or unsets. A variable the stage set to a value other than
    the ambient one keeps the stage's value.
    """
    ambient_env = dict(os.environ if ambient is None else ambient)
    out = dict(ambient_env if env is None else env)
    if not launch.extra_env and launch.setup_hook is None:
        return out
    stage_owned = {name for name, value in out.items() if ambient_env.get(name) != value}
    changed: dict[str, str] = dict(launch.extra_env)
    hook_changed, removed = setup_hook_delta(launch, ambient_env)
    changed.update(hook_changed)
    for name in removed:
        if name not in stage_owned:
            out.pop(name, None)
    for name, value in changed.items():
        if name not in stage_owned:
            out[name] = value
    return out


def reset_setup_hook_cache() -> None:
    _HOOK_DELTA_CACHE.clear()


__all__ = [
    "SETUP_HOOK_TIMEOUT_SEC",
    "SITE_DUT_KEYS",
    "SITE_ENV",
    "SITE_EXECUTOR_KEYS",
    "SITE_FILE_NAME",
    "SITE_ONLY_TOOL_KEYS",
    "SITE_TOOL_KEYS",
    "SiteLayer",
    "ToolLaunch",
    "launch_argv",
    "launch_env",
    "load_site_layer",
    "locate_tool",
    "merged_executors",
    "merged_simulators",
    "reset_setup_hook_cache",
    "setup_hook_delta",
    "site_layer_path",
    "site_summary",
    "tool_launch",
    "tool_source",
    "validate_site_duts",
]
