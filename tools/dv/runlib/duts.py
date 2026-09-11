# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""DUT registry + directory-convention resolution for the native DV runner.

A run selects its device-under-test with ``--dut <name>``. The name is resolved against
``hw/common/dv/configs/duts.toml`` first; if it is not registered there, it falls back to the
directory convention (``hw/<name>/dv``, ``hw/{sys,ip,comp,periph}/<name>/dv``, or
``hw/common/prim/<name>/dv`` under the active DV root). Either way the resolved DUT DV root must contain
a ``<name>_sim_cfg.toml``, which is loaded (and merged with its ``profile``) into a :class:`Dut`.

A registry entry may instead carry ``alias_of = "<canonical>"``, which makes the
name a second way to select an existing DUT rather than a DUT of its own: the
canonical config is loaded and the resolved :class:`Dut` carries the canonical
identity, so both names share one build cache and one build manifest. Aliases
are one hop deep, and the ``sim_cfg``/``formal_cfg`` default path follows the
canonical name.

The convention rules mirror ``tools/dv/sync_python_namespace.py`` so the import-name bridge
and the runner agree on what counts as a DUT root.
"""

from __future__ import annotations

from pathlib import Path

from .config import load_dut, load_toml
from .models import ConfigError, Dut
from .paths import configs_root, dv_path, repo_rel
from .paths import dv_root as active_dv_root

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
        if not isinstance(entry, dict) or not isinstance(entry.get("root"), str):
            raise ConfigError(f"{path}: [duts.{name}] needs a string `root`")
        unknown = sorted(set(entry) - _REGISTRY_KEYS)
        if unknown:
            raise ConfigError(f"{path}: [duts.{name}] unsupported key(s): {', '.join(unknown)}")
        alias = entry.get("alias_of")
        if alias is not None and (not isinstance(alias, str) or not alias):
            raise ConfigError(f"{path}: [duts.{name}] `alias_of` must be a non-empty string")
        if alias == name:
            raise ConfigError(f"{path}: [duts.{name}] `alias_of` cannot point at itself")
        out[name] = entry
    for name, entry in out.items():
        alias = entry.get("alias_of")
        # One hop only: a chain would make the resolved identity depend on
        # traversal order.
        if alias is not None and out.get(alias, {}).get("alias_of") is not None:
            raise ConfigError(
                f"{path}: [duts.{name}] `alias_of` = `{alias}`, which is itself an alias; "
                "point both at the canonical DUT instead"
            )
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


def resolve_dut(
    root: Path,
    name: str,
    mode: str = "sim",
    framework: str | None = None,
    adopter_overlay: Path | None = None,
) -> Dut:
    """Resolve ``--dut <name>`` to a loaded :class:`Dut` (registry first, then convention).

    ``framework`` is the CLI ``--framework`` request; ``None`` selects the DUT's default.
    ``adopter_overlay`` is the resolved ``--overlay``/``OCAH_DV_OVERLAY`` path applied on top
    of the merged view (see :func:`runlib.config.apply_adopter_overlay`); ``None`` when the
    layer is inactive.
    """
    registry = load_dut_registry(root)
    # An `alias_of` entry is a second selectable name for one DUT, not a second
    # DUT: it resolves to the canonical config and identity, so the two names
    # share one build cache and one build manifest instead of compiling the
    # same model twice under different names.
    canonical = str(registry.get(name, {}).get("alias_of") or name)
    if name in registry:
        entry = registry[name]
        dv_root = dv_path(root, entry["root"])
        cfg = _cfg_for(dv_root, canonical, mode, entry, root)
    else:
        discovered = discover_dut_roots(root)
        if name not in discovered:
            known = ", ".join(sorted(set(registry) | set(discovered))) or "<none>"
            raise ConfigError(f"unknown DUT `{name}` (known: {known})")
        dv_root = discovered[name]
        cfg = _cfg_for(dv_root, name, mode, {}, root)
    if not cfg.is_file():
        raise ConfigError(f"DUT `{name}`: {mode} config not found: {cfg}")
    return load_dut(
        cfg,
        configs_root(root),
        root=root,
        name=canonical,
        root_rel=str(repo_rel(root, dv_root)),
        framework=framework,
        adopter_overlay=adopter_overlay,
    )


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
