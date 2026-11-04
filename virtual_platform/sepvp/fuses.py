# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Turn a fuse-map into the sep-vp eFuse configuration.

The two formats configure the eFuse model differently, and the platform derives the
lifecycle controller's inputs from the sensed eFuse in both cases:

* **``.yaml`` / ``.yml``** — the VP-native, hand-friendly fuse-map: a flat mapping
  keyed by sep-vp fuse-field name, applied as ``och_sep_ss1.sep_efuse.*`` CCI
  parameters (see :func:`overrides_from_map`)::

      lc_state: PROD          # symbolic (see _LC_STATES) or an int (raw code)
      sboot_dis: 1
      locks_lo: 0xA800
      chiplet_uid: [1, 2, 3, 4, 5, 6, 7, 8]

  Scalar values become ``[uint]`` overrides; 8-word (256-bit) values become
  ``[string]`` array overrides — matching how the base ``efuse_vp.ini`` types them.

* **``.toml``** — the RTL DV eFuse configuration, loaded by the RTL loader into the
  complete 256-word image (see :func:`load_toml_image`). The harness stages that image
  for the model's ``fuse_preload_file``, so a VP run senses the same array as RTL.
"""

import sys
from pathlib import Path
from typing import List

import yaml

from sepvp import paths
from sepvp.inifile import Override

# LC-state encoding (see lifecycle_ctrl_vp.ini / efuse_vp.ini headers).
_LC_STATES = {
    "TEST_DEV": 0x0,
    "PROD": 0x1,
    "RMA_SIP": 0x2,
    "RMA_CHIPLET": 0x6,
    "INVALID": 0x4,
    "PROD_END": 0x8,
}

_EFUSE_PREFIX = "och_sep_ss1.sep_efuse."


def parse_lc_state(value) -> int:
    """Accept a symbolic LC-state name (case-insensitive) or an int/hex string."""
    if isinstance(value, str):
        key = value.strip().upper()
        if key in _LC_STATES:
            return _LC_STATES[key]
        return int(value, 0)  # allow "0x1" / "1"
    return int(value)


def _to_int(value) -> int:
    if isinstance(value, str):
        return int(value, 0)
    return int(value)


# --------------------------------------------------------------------------- #
# YAML fuse-map (VP-native, hand-friendly)
# --------------------------------------------------------------------------- #
def overrides_from_map(fuse_map: dict) -> List[Override]:
    """Turn a parsed YAML fuse-map dict into a list of ini overrides."""
    overrides: List[Override] = []
    for field, value in fuse_map.items():
        if field == "lc_state":
            overrides.append(("uint", _EFUSE_PREFIX + "lc_state", parse_lc_state(value)))
            continue
        key = _EFUSE_PREFIX + field
        if isinstance(value, (list, tuple)):
            overrides.append(("string", key, [_to_int(x) for x in value]))
        else:
            overrides.append(("uint", key, _to_int(value)))
    return overrides


# --------------------------------------------------------------------------- #
# TOML: the RTL DV eFuse image
# --------------------------------------------------------------------------- #
_DV_ENV_DIR = paths.OCAH_ROOT / "hw" / "sys" / "sep" / "dv" / "cocotb" / "env"


def load_toml_image(path: str | Path):
    """Load an RTL eFuse-config TOML as the complete 256-word ``SepEfuseImage``.

    The RTL loader starts from an erased array, so an omitted register is zero, and it
    rejects unknown registers, fields and lock keys. The lifecycle byte must be a legal
    canonical ``{~raw, raw}`` pair, because the platform senses it as given.
    """
    if str(_DV_ENV_DIR) not in sys.path:
        sys.path.append(str(_DV_ENV_DIR))
    from sep_efuse_image import LEGAL_LC_RAW, SepEfuseImage, lc_encode

    image = SepEfuseImage().load(path)
    stored = image.words[image.field("LC_STATE").word] & 0xFF
    raw = stored & 0xF
    if lc_encode(raw) != stored:
        raise ValueError(
            f"LC_STATE is not canonically differential-encoded: {path} stores "
            f"{stored:#04x}, expected {lc_encode(raw):#04x} for raw {raw:#x}"
        )
    if raw not in LEGAL_LC_RAW:
        raise ValueError(f"LC_STATE raw {raw:#x} is not a legal lifecycle state in {path}")
    return image


def is_toml(otp_path) -> bool:
    return Path(otp_path).suffix.lower() == ".toml"


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #
def load_yaml(otp_path) -> List[Override]:
    """Load a YAML fuse-map file and return ini overrides."""
    path = Path(otp_path)
    if not path.is_file():
        raise FileNotFoundError(f"fuse-map not found: {path}")
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"fuse-map {path} must be a YAML mapping of field: value")
    return overrides_from_map(data)


def load(otp_path) -> List[Override]:
    """Per-field overrides for a fuse-map.

    A ``.toml`` contributes none: the harness stages it as a complete image (see
    :func:`load_toml_image`). Anything else is a YAML map.
    """
    if not is_toml(otp_path):
        return load_yaml(otp_path)
    if not Path(otp_path).is_file():
        raise FileNotFoundError(f"fuse-map not found: {otp_path}")
    return []
