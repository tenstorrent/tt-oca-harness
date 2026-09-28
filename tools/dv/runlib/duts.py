# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""DUT registry + directory-convention resolution for the native DV runner.

A run selects its device-under-test with ``--dut <name>``. The name is resolved against
``hw/common/dv/configs/duts.toml`` first; if it is not registered there, it falls back to the
directory convention (``hw/<name>/dv``, ``hw/{sys,ip,comp,periph}/<name>/dv``, or
``hw/common/prim/<name>/dv`` under the active DV root). Either way the resolved DUT DV root must contain
a ``<name>_sim_cfg.toml``, which is loaded (and merged with its ``profile``) into a :class:`Dut`.
The active site layer may name a DUT's simulation or formal config in its place, and may add
simulation tools to the DUT's allowlist (see :func:`resolve_dut`).

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

from dataclasses import dataclass, replace
from pathlib import Path

from .config import as_str_list, load_dut, load_simulators, load_toml
from .models import ConfigError, Dut
from .paths import configs_root, dv_path, repo_rel
from .paths import dv_root as active_dv_root
from .site import SiteLayer

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


# Where a config path came from: the site layer's `[duts.<name>]` pointer, the registry's
# `sim_cfg`/`formal_cfg` override, or the `<name>_<mode>_cfg.toml` naming convention.
_SOURCE_LABEL = {"site": "the site layer", "registry": "duts.toml", "convention": "convention"}


@dataclass(frozen=True)
class ConfigView:
    """The config one DUT loads in one ``mode`` (``sim`` or ``formal``), and the pointer that
    named it.

    ``flow`` is the loaded config once resolved; a view whose file is absent stays unavailable
    with ``flow`` None.
    """

    name: str
    mode: str
    path: Path
    source: str
    flow: Dut | None = None

    @property
    def available(self) -> bool:
        return self.path.is_file()

    @property
    def reason(self) -> str:
        return f"{self.mode} config not found: {self.path} (named by {_SOURCE_LABEL[self.source]})"


def _cfg_for(
    dv_root: Path,
    name: str,
    mode: str,
    entry: dict,
    root: Path,
    site_cfg: str | None = None,
) -> tuple[Path, str]:
    """(config path, source) for ``mode``; the path may not exist."""
    if mode not in {"sim", "formal"}:
        raise ConfigError(f"unsupported verification mode `{mode}`")
    if site_cfg:
        return dv_path(root, site_cfg), "site"
    override_key = "formal_cfg" if mode == "formal" else "sim_cfg"
    override = entry.get(override_key)
    if override:
        return dv_path(root, override), "registry"
    suffix = "formal_cfg" if mode == "formal" else "sim_cfg"
    return dv_root / f"{name}_{suffix}.toml", "convention"


def _locate(root: Path, name: str) -> tuple[str, Path, dict]:
    """(canonical name, DUT DV root, registry entry) for a selectable DUT name."""
    registry = load_dut_registry(root)
    # An `alias_of` entry is a second selectable name for one DUT, not a second
    # DUT: it resolves to the canonical config and identity, so the two names
    # share one build cache and one build manifest instead of compiling the
    # same model twice under different names.
    canonical = str(registry.get(name, {}).get("alias_of") or name)
    if name in registry:
        entry = registry[name]
        return canonical, dv_path(root, entry["root"]), entry
    discovered = discover_dut_roots(root)
    if name not in discovered:
        known = ", ".join(sorted(set(registry) | set(discovered))) or "<none>"
        raise ConfigError(f"unknown DUT `{name}` (known: {known})")
    return canonical, discovered[name], {}


def _site_cfg(site: SiteLayer | None, names: tuple[str, str], mode: str) -> str | None:
    """The config the site layer names for ``mode``; the canonical name's entry serves an alias."""
    if site is None:
        return None
    return site.formal_cfg(names) if mode == "formal" else site.sim_cfg(names)


def _site_tools(root: Path, site: SiteLayer, names: tuple[str, str], framework: str) -> list[str]:
    """The site-added tools that serve ``framework``.

    A tool whose registry table names no frameworks serves every framework, as in the
    framework check of flow validation, and a view without a framework takes every tool.
    """
    tools = site.dut_tools(names)
    if not tools or not framework:
        return tools
    checked_in = load_simulators(root)

    def serves(tool: str) -> bool:
        table = checked_in.get(tool) or site.simulators.get(tool) or {}
        frameworks = as_str_list(table.get("frameworks"), f"{tool}.frameworks")
        return not frameworks or framework in frameworks

    return [tool for tool in tools if serves(tool)]


def resolve_dut(
    root: Path,
    name: str,
    mode: str = "sim",
    framework: str | None = None,
    adopter_overlay: Path | None = None,
    site: SiteLayer | None = None,
) -> Dut:
    """Resolve ``--dut <name>`` to a loaded :class:`Dut` (registry first, then convention).

    ``framework`` is the CLI ``--framework`` request; ``None`` selects the DUT's default.
    ``adopter_overlay`` is the resolved ``--overlay``/``OCAH_DV_OVERLAY`` path applied on top
    of the merged view (see :func:`runlib.config.apply_adopter_overlay`); ``None`` when the
    layer is inactive. ``site`` is the active site layer: its ``[duts.<name>]`` ``sim_cfg`` or
    ``formal_cfg`` wins over the registry's override and the ``<name>_<mode>_cfg.toml``
    convention, and in ``sim`` mode its ``tools`` append to the view's allowlist, each tool
    only where it serves the view's framework.
    """
    canonical, dv_root, entry = _locate(root, name)
    names = (name, canonical)
    cfg, source = _cfg_for(dv_root, canonical, mode, entry, root, _site_cfg(site, names, mode))
    if not cfg.is_file():
        named = "" if source == "convention" else f" (named by {_SOURCE_LABEL[source]})"
        raise ConfigError(f"DUT `{name}`: {mode} config not found: {cfg}{named}")
    flow = load_dut(
        cfg,
        configs_root(root),
        root=root,
        name=canonical,
        root_rel=str(repo_rel(root, dv_root)),
        framework=framework,
        adopter_overlay=adopter_overlay,
    )
    if mode == "sim" and site is not None:
        added = [
            tool
            for tool in _site_tools(root, site, names, flow.framework)
            if tool not in flow.tools
        ]
        if added:
            flow = replace(flow, tools=[*flow.tools, *added])
    return flow


def list_dut_names(root: Path) -> list[str]:
    """All selectable DUT names: registry entries plus convention roots that carry a sim_cfg."""
    registry = load_dut_registry(root)
    names = set(registry)
    for name, dv_root in discover_dut_roots(root).items():
        if (dv_root / f"{name}_sim_cfg.toml").is_file():
            names.add(name)
    return sorted(names)


def config_view(
    root: Path, name: str, mode: str, site: SiteLayer | None = None
) -> ConfigView | None:
    """The ``mode`` view of one selectable DUT, or None when nothing names a config for it.

    A site or registry pointer yields a view whether or not its file exists; the naming
    convention yields one only for a file that exists.
    """
    canonical, dv_root, entry = _locate(root, name)
    site_cfg = _site_cfg(site, (name, canonical), mode)
    path, source = _cfg_for(dv_root, canonical, mode, entry, root, site_cfg)
    if source == "convention" and not path.is_file():
        return None
    return ConfigView(name=name, mode=mode, path=path, source=source)


def unavailable_sim_views(root: Path, site: SiteLayer | None = None) -> dict[str, ConfigView]:
    """Simulation views whose site-named config is absent.

    The site file may point into a checkout this machine lacks, so such a view is listed as
    unavailable and is an error only when its DUT is selected.
    """
    if site is None:
        return {}
    views: dict[str, ConfigView] = {}
    for name in list_dut_names(root):
        view = config_view(root, name, "sim", site)
        if view is not None and view.source == "site" and not view.available:
            views[name] = view
    return views


def load_duts(root: Path, site: SiteLayer | None = None) -> dict[str, Dut]:
    """Resolve and load every selectable DUT's simulation view (used by --list /
    --validate-configs / --doctor).

    A DUT whose site-named simulation config is absent is left out; :func:`unavailable_sim_views`
    reports it.
    """
    absent = unavailable_sim_views(root, site)
    return {
        name: resolve_dut(root, name, site=site)
        for name in list_dut_names(root)
        if name not in absent
    }


def formal_view(root: Path, name: str, site: SiteLayer | None = None) -> ConfigView | None:
    """The formal view of one selectable DUT, or None when nothing names a formal config."""
    return config_view(root, name, "formal", site)


def discover_formal_views(root: Path, site: SiteLayer | None = None) -> dict[str, ConfigView]:
    """Every selectable DUT's formal view, unloaded (used by --validate-configs)."""
    views: dict[str, ConfigView] = {}
    for name in list_dut_names(root):
        view = formal_view(root, name, site)
        if view is not None:
            views[name] = view
    return views


def load_formal_views(root: Path, site: SiteLayer | None = None) -> dict[str, ConfigView]:
    """Every formal view with the available ones loaded; an absent file stays unavailable."""
    return {
        name: (
            replace(view, flow=resolve_dut(root, name, mode="formal", site=site))
            if view.available
            else view
        )
        for name, view in discover_formal_views(root, site).items()
    }
