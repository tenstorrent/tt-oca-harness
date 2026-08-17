"""DUT registry + directory-convention resolution for the native DV runner.

A run selects its device-under-test with ``--dut <name>``. The name is resolved against
``hw/common/dv/configs/duts.toml`` first; if it is not registered there, it falls back to the
directory convention (``hw/<name>/dv``, ``hw/{sys,ip,comp,periph}/<name>/dv``, or
``hw/common/prim/<name>/dv`` under the active DV root). Either way the resolved DUT DV root must contain
a ``<name>_sim_cfg.toml``, which is loaded (and merged with its ``profile``) into a :class:`Dut`.

Registry entries may set ``alias_of = "<canonical>"`` so a short or component-local name
(e.g. ``smc``) resolves to an existing DUT (e.g. ``smc_wrapper``) without duplicating configs.

The convention rules deliberately mirror ``tools/dv/sync_python_namespace.py`` so the import-name
bridge and the runner agree on what counts as a DUT root.
"""

from __future__ import annotations

from pathlib import Path

from .config import load_dut, load_toml
from .models import ConfigError, Dut
from .paths import configs_root, dv_path, dv_root as active_dv_root, repo_path, repo_rel

# Direct children of hw/ that are namespaces, not DUTs.
_DIRECT_HW_EXCLUDES = {"common", "dv", "ip", "comp", "periph", "sys"}
# Grouping dirs whose children may carry a dv/ root.
_NESTED_HW_GROUPS = ("sys", "ip", "comp", "periph")
_REGISTRY_KEYS = {"root", "sim_cfg", "formal_cfg", "alias_of"}


def registry_path(root: Path) -> Path:
    return configs_root(root) / "duts.toml"


def load_dut_registry(root: Path) -> dict[str, dict]:
    """Return the ``[duts.<name>]`` table from duts.toml (empty if the file is absent)."""
    path = registry_path(root)
    if not path.is_file():
        return {}
    data = load_toml(path)
    duts = data.get("duts", {})
    if not isinstance(duts, dict):
        raise ConfigError(f"{path}: [duts] must be a table")
    out: dict[str, dict] = {}
    for name, entry in duts.items():
        if not isinstance(entry, dict):
            raise ConfigError(f"{path}: [duts.{name}] must be a table")
        unknown = sorted(set(entry) - _REGISTRY_KEYS)
        if unknown:
            raise ConfigError(f"{path}: [duts.{name}] unsupported key(s): {', '.join(unknown)}")
        alias_of = entry.get("alias_of")
        if alias_of is not None:
            if not isinstance(alias_of, str) or not alias_of:
                raise ConfigError(f"{path}: [duts.{name}].alias_of must be a non-empty string")
            if alias_of == name:
                raise ConfigError(f"{path}: [duts.{name}].alias_of cannot refer to itself")
            extras = sorted(set(entry) - {"alias_of"})
            if extras:
                raise ConfigError(
                    f"{path}: [duts.{name}] alias_of entry cannot also set {', '.join(extras)}"
                )
        elif not isinstance(entry.get("root"), str):
            raise ConfigError(f"{path}: [duts.{name}] needs a string `root` (or `alias_of`)")
        out[name] = entry
    return out


def discover_dut_roots(root: Path) -> dict[str, Path]:
    """Map ``<name> -> <dut-dv-root>`` for every DV root found by the directory convention."""
    hw = active_dv_root(root) / "hw"
    found: dict[str, Path] = {}
    if not hw.is_dir():
        return found

    def add(name: str, dv_root: Path) -> None:
        existing = found.get(name)
        if existing is not None and existing != dv_root:
            raise ConfigError(f"DUT name collision `{name}`: {existing} vs {dv_root}")
        found[name] = dv_root

    for child in sorted(hw.iterdir()):
        if child.is_dir() and child.name not in _DIRECT_HW_EXCLUDES:
            dv_root = child / "dv"
            if dv_root.is_dir():
                add(child.name, dv_root)

    for group in _NESTED_HW_GROUPS:
        group_dir = hw / group
        if group_dir.is_dir():
            for child in sorted(group_dir.iterdir()):
                dv_root = child / "dv"
                if child.is_dir() and dv_root.is_dir():
                    add(child.name, dv_root)

    prim_dir = hw / "common" / "prim"
    if prim_dir.is_dir():
        for child in sorted(prim_dir.iterdir()):
            dv_root = child / "dv"
            if child.is_dir() and dv_root.is_dir():
                add(child.name, dv_root)

    return found


def _cfg_for(dv_root: Path, name: str, mode: str, entry: dict, root: Path) -> Path:
    if mode not in {"sim", "formal"}:
        raise ConfigError(f"unsupported verification mode `{mode}`")
    override_key = "formal_cfg" if mode == "formal" else "sim_cfg"
    override = entry.get(override_key)
    if override:
        return dv_path(root, override)
    suffix = "formal_cfg" if mode == "formal" else "sim_cfg"
    return dv_root / f"{name}_{suffix}.toml"


def resolve_dut(root: Path, name: str, mode: str = "sim", *, _seen: frozenset[str] | None = None) -> Dut:
    """Resolve ``--dut <name>`` to a loaded :class:`Dut` (registry first, then convention).

    Registry ``alias_of`` entries redirect to the canonical DUT name so callers can use a
    component-local name (e.g. ``smc``) without a separate sim_cfg.
    """
    registry = load_dut_registry(root)
    seen = _seen or frozenset()
    if name in seen:
        cycle = " -> ".join([*sorted(seen), name])
        raise ConfigError(f"DUT alias cycle involving `{name}` ({cycle})")
    if name in registry:
        entry = registry[name]
        alias_of = entry.get("alias_of")
        if isinstance(alias_of, str):
            return resolve_dut(root, alias_of, mode=mode, _seen=seen | {name})
        dv_root = dv_path(root, entry["root"])
        cfg = _cfg_for(dv_root, name, mode, entry, root)
    else:
        discovered = discover_dut_roots(root)
        if name not in discovered:
            known = ", ".join(sorted(set(registry) | set(discovered))) or "<none>"
            raise ConfigError(f"unknown DUT `{name}` (known: {known})")
        dv_root = discovered[name]
        cfg = _cfg_for(dv_root, name, mode, {}, root)
    if not cfg.is_file():
        raise ConfigError(f"DUT `{name}`: {mode} config not found: {cfg}")
    return load_dut(cfg, configs_root(root), name=name, root_rel=str(repo_rel(root, dv_root)))


def list_dut_names(root: Path) -> list[str]:
    """All selectable DUT names: registry entries plus convention roots that carry a sim_cfg."""
    registry = load_dut_registry(root)
    names = set(registry)
    for name, dv_root in discover_dut_roots(root).items():
        if (dv_root / f"{name}_sim_cfg.toml").is_file():
            names.add(name)
    return sorted(names)


def load_duts(root: Path) -> dict[str, Dut]:
    """Resolve and load every selectable DUT (used by --list / --validate-configs / --doctor)."""
    return {name: resolve_dut(root, name) for name in list_dut_names(root)}
