# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Per-run SMC eFuse image for the single- and dual-instance production-ROM tests."""

from __future__ import annotations

import logging
import re
import subprocess
import sys
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

_EFUSE_DIR = Path(__file__).resolve().parents[2] / "efuse_preload"
_BASE_CONFIG = _EFUSE_DIR / "configurations" / "default_efuse.toml"

# SMC_CONFIG.dft_ignore_error in smc_efuse_map.rdl.
SMC_CONFIG_DFT_IGNORE_ERROR_BIT = 15

_I2C_ID_RE = re.compile(r"I2C_I3C_ID\[(\d)\]=(0x[0-9a-fA-F]+)")


@dataclass(frozen=True)
class SmcEfuseStimulus:
    """What the regenerated image programs; empty when the run names no image."""

    image: Path | None = None
    i2c_ids: dict[int, int] = field(default_factory=dict)
    smc_config: int | None = None

    @property
    def dft_ignore_error(self) -> int | None:
        if self.smc_config is None:
            return None
        return (self.smc_config >> SMC_CONFIG_DFT_IGNORE_ERROR_BIT) & 1


def _plusarg_int(plusargs: Mapping[str, object], name: str) -> int | None:
    value = plusargs.get(name)
    return None if value is None else int(str(value), 0)


def _run(cmd: list[str], seed: int) -> str:
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    except subprocess.CalledProcessError as exc:
        # Otherwise the stale image from the build stage runs under a seed it does not match.
        raise AssertionError(
            f"eFuse image regeneration failed for seed {seed}:\n"
            f"  {exc.cmd}\n  stdout: {exc.stdout}\n  stderr: {exc.stderr}"
        ) from exc


def regenerate_efuse_image(seed: int, plusargs: Mapping[str, object]) -> SmcEfuseStimulus:
    """Rewrite the image +smc_efuse_hex names for this seed and the fuse plusargs.

    Call before the bank model leaves reset: it reads the file once, at its first reset release.
    """
    img = plusargs.get("smc_efuse_hex")
    if img is None:
        return SmcEfuseStimulus()
    img_path = Path(str(img))
    assert not img_path.is_absolute(), (
        f"+smc_efuse_hex={img} is absolute; this run rewrites the image it senses, "
        "so the plusarg must name a file in the run directory"
    )
    randomized = img_path.parent / "efuse_config_randomized.toml"

    timeout = _plusarg_int(plusargs, "fuse_transport_timeout")
    dft_ignore = _plusarg_int(plusargs, "fuse_dft_ignore_error")
    args = [] if timeout is None else ["--transport-timeout", str(timeout)]
    if plusargs.get("fuse_i2c_ids") is not None:
        args.append("--i2c-ids")
    if dft_ignore is not None:
        args += ["--dft-ignore-error", str(dft_ignore)]

    # The generator needs Python 3.11+ (tomllib); a PATH python3 may be older than the venv.
    stdout = _run(
        [
            sys.executable,
            str(_EFUSE_DIR / "randomize_efuse.py"),
            str(_BASE_CONFIG),
            "--output_file",
            str(randomized),
            "--seed",
            str(seed),
            *args,
        ],
        seed,
    )
    _run(
        [
            sys.executable,
            str(_EFUSE_DIR / "generate_efuse_preload.py"),
            str(randomized),
            "--output_file",
            str(img_path),
        ],
        seed,
    )

    config = tomllib.loads(randomized.read_text())
    smc_config = int(config["SMC_CONFIG"]["fields"]["smc_config"]["value"])
    stim = SmcEfuseStimulus(
        image=img_path,
        i2c_ids={int(slot): int(addr, 0) for slot, addr in _I2C_ID_RE.findall(stdout)},
        smc_config=smc_config,
    )
    if dft_ignore is not None and stim.dft_ignore_error != dft_ignore:
        raise AssertionError(
            f"{randomized} carries SMC_CONFIG={smc_config:#x}, so dft_ignore_error="
            f"{stim.dft_ignore_error}, but +fuse_dft_ignore_error={dft_ignore} was requested"
        )
    logging.getLogger("cocotb").info(
        "eFuse image regenerated for RANDOM_SEED=%d -> %s (%s; SMC_CONFIG=%#x)",
        seed,
        img_path,
        stdout.strip(),
        smc_config,
    )
    return stim
