# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Rebuild an OCA SPI image from a prebuilt packer config plus field edits.

The ROM tree's derive_pack_config.py and packer recompute hashes and signatures over every
edited field, as `make oca-images` does.
"""

import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

import untrusted_signing_key
import yaml
from sepvp import paths

_SLOT_COMBOS = ("primary", "backup")
_UNTRUSTED_KEY = "{untrusted_signing_key}"
_UNTRUSTED_KEY_NAME = "{untrusted_signing_key_name}"
PLACEHOLDERS = {
    _UNTRUSTED_KEY: lambda: str(untrusted_signing_key.ensure()),
    _UNTRUSTED_KEY_NAME: lambda: untrusted_signing_key.KEY_NAME,
}
_VENV_SETUP = (
    "UV_PROJECT_ENVIRONMENT=$PWD/virtual_platform/local/manifest-venv uv sync --project $PWD "
    "--locked --no-default-groups --group manifest [--python-platform <manylinux tag>]"
)
_LOG_TAIL = 2000


def _manifest_python() -> Path:
    python = paths.MANIFEST_VENV_PYTHON
    if not python.is_file():
        raise RuntimeError(
            f"manifest venv interpreter {python} not found. Create it from the repo root with:\n"
            f"  {_VENV_SETUP}\n"
            "or point SEPVP_MANIFEST_PYTHON at an interpreter that imports "
            "tt_boot_manifest.pack_images and ruamel.yaml"
        )
    return python


def pack(config: Path, out: Path, log: Path) -> Path:
    """Run the official packer; raise RuntimeError with the log tail on failure or no image."""
    python = _manifest_python()
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [str(python), "-m", "tt_boot_manifest.pack_images"]
    cmd += ["--config", str(config), "--out", str(out), "-v"]
    result = subprocess.run(cmd, cwd=paths.BOOTCODE_DIR, capture_output=True, text=True)
    text = f"$ {' '.join(cmd)}\n{result.stdout}{result.stderr}"
    log.write_text(text)
    if result.returncode != 0 or not out.is_file():
        raise RuntimeError(f"packer failed on {config} (see {log}):\n{text[-_LOG_TAIL:]}")
    return out


def _lookup(config: object, dotted: str, where: str) -> object:
    node = config
    for step in dotted.split("."):
        if isinstance(node, list) and step.isdigit() and int(step) < len(node):
            node = node[int(step)]
        elif isinstance(node, dict) and step in node:
            node = node[step]
        else:
            raise ValueError(f"{where} has no such field: {dotted}")
    return node


def _slots(edit) -> tuple[str | None, ...]:
    return _SLOT_COMBOS if edit.slot == "both" else (edit.slot,)


def _value(value: int | str) -> int | str:
    if isinstance(value, str) and value in PLACEHOLDERS:
        return PLACEHOLDERS[value]()
    return value


def _derive(base: Path, out: Path, edits: Sequence[tuple[str, int | str]]) -> Path:
    cmd = [str(_manifest_python()), str(paths.DERIVE_PACK_CONFIG), "--base", str(base)]
    cmd += ["--out", str(out)]
    for path, value in edits:
        if isinstance(value, int):
            cmd += ["--set-int", f"{path}={value:#x}"]
        else:
            cmd += ["--set-str", f"{path}={value}"]
    result = subprocess.run(cmd, cwd=paths.BOOTCODE_DIR, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"derive_pack_config refused {base.name} -> {out.name}:\n"
            f"{result.stdout}{result.stderr}".rstrip()
        )
    return out


def _combos(image_cfg: Path) -> Mapping[str, tuple[int, Path]]:
    config = yaml.safe_load(image_cfg.read_text())
    combos = config.get("combos") if isinstance(config, dict) else None
    names = [c.get("name") for c in combos or [] if isinstance(c, dict)]
    if names[:2] != list(_SLOT_COMBOS):
        raise ValueError(
            f"{image_cfg.name} combos must start with primary then backup, got {names}; "
            "a slot edit would otherwise land in the wrong slot"
        )
    return {
        slot: (index, paths.BOOTCODE_DIR / combos[index]["config"])
        for index, slot in enumerate(_SLOT_COMBOS)
    }


def repack(
    name: str,
    pack_config: str,
    edits: Sequence,
    pins: Sequence,
    output_dir: Path,
) -> Path:
    """Pack ``<pack_config>_image.yaml`` with *edits* applied, after checking every pin."""
    image_cfg = paths.BOOTCODE_CONFIGS / f"{pack_config}_image.yaml"
    combos = _combos(image_cfg)
    configs = {None: yaml.safe_load(image_cfg.read_text())}
    for slot, (_index, bundle) in combos.items():
        configs[slot] = yaml.safe_load(bundle.read_text())

    for pin in pins:
        for slot in _slots(pin):
            where = image_cfg.name if slot is None else f"{slot} bundle {combos[slot][1].name}"
            held = _lookup(configs[slot], pin.path, where)
            if held != pin.value:
                raise ValueError(
                    f"{where} {pin.path} no longer holds {pin.value!r}; it is {held!r}, so "
                    f"mutation {name!r} no longer tests what it names"
                )

    by_slot: dict[str | None, list[tuple[str, int | str]]] = {}
    for edit in edits:
        for slot in _slots(edit):
            by_slot.setdefault(slot, []).append((edit.path, _value(edit.value)))

    output_dir.mkdir(parents=True, exist_ok=True)
    image_edits = list(by_slot.pop(None, []))
    for slot, slot_edits in by_slot.items():
        index, bundle = combos[slot]
        derived = _derive(bundle, output_dir / f"{name}.{slot}.yaml", slot_edits)
        image_edits.append((f"combos.{index}.config", str(derived.resolve())))
    combined = _derive(image_cfg, output_dir / f"{name}.image.yaml", image_edits)
    return pack(combined, output_dir / f"{name}.bin", output_dir / f"{name}.pack.log")
