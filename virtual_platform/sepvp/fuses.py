# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Translate a fuse-map into sep-vp ``och_sep_ss1.sep_efuse.*`` ini overrides.

sep-vp has no OTP image loader; every fuse is a CCI parameter applied at
end_of_elaboration. :func:`load` accepts two source formats, dispatched by file
extension, and returns the same list of ini overrides for either:

* **``.yaml`` / ``.yml``** — the VP-native, hand-friendly fuse-map: a flat mapping
  keyed by sep-vp fuse-field name (see :func:`overrides_from_map`)::

      lc_state: PROD          # symbolic (see _LC_STATES) or an int (raw code)
      sboot_dis: 1
      locks_lo: 0xA800
      chiplet_uid: [1, 2, 3, 4, 5, 6, 7, 8]

* **``.toml``** — the *same* RTL/UVM eFuse config format the SEP testbench's
  efuse-preload generator consumes (and that tt-oca-manifest's
  ``SepEfuseConfig`` emits). It is keyed by hardware REGISTER name with nested
  ``fields.<name>.value`` and per-register ``write_locked``/``read_locked`` flags
  (see :func:`overrides_from_toml`). This lets one config drive both RTL sim
  (via the ``.preload`` binary) and the VP (via CCI params).

Scalar values become ``[uint]`` overrides; 8-word (256-bit) values become
``[string]`` array overrides — matching how the base ``efuse_vp.ini`` types them.

Two encodings differ between the friendly YAML and the RTL TOML and are handled
per-format:

* ``lc_state``: the RTL register stores the *differentially* encoded byte
  (``{~raw[3:0], raw[3:0]}``, e.g. PROD=0xE1); sep-vp wants the raw nibble
  (PROD=0x1). The TOML path decodes it; the YAML path takes the raw code directly.
* Wide registers: the RTL 64-bit ``SiP_DIS``/``SYS_DIS`` map to sep-vp ``*_lo``/``*_hi``
  param pairs, and 256-bit tokens/keys map to 8x32-bit little-endian word arrays
  (word[0] = bits[31:0], matching both the RTL bit-packer and the VP model's
  ``arr[i] = word i`` load order).

``lc_state`` is also special because the eFuse model and the LC controller model are
not wired together: both ``sep_efuse.lc_state`` and ``lc_ctrl.lc_state`` must be set,
so we emit BOTH from a single source entry.
"""

import warnings
from pathlib import Path
from typing import List

import yaml

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
_LC_CTRL_LC_STATE = "och_sep_ss1.lc_ctrl.lc_state"


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
            lc = parse_lc_state(value)
            # eFuse field is [uint]; the lc_ctrl mirror is [int] (per the base configs).
            overrides.append(("uint", _EFUSE_PREFIX + "lc_state", lc))
            overrides.append(("int", _LC_CTRL_LC_STATE, lc))
            continue
        key = _EFUSE_PREFIX + field
        if isinstance(value, (list, tuple)):
            overrides.append(("string", key, [_to_int(x) for x in value]))
        else:
            overrides.append(("uint", key, _to_int(value)))
    return overrides


# --------------------------------------------------------------------------- #
# TOML fuse-map (the RTL/UVM eFuse config; generate_efuse_preload.py schema)
# --------------------------------------------------------------------------- #
# RTL register name -> (kind, sep-vp target). Registers absent here (RESERVED_*,
# a bare LOCKS value) are handled specially or intentionally ignored. Kinds:
#   uint32     : single field -> one uint param (low 32 bits)
#   uint_lohi  : single 64-bit field -> (lo, hi) uint params
#   array8     : single field -> 8-word [string] array param (little-endian words)
#   lc_state   : differential-decode + emit sep_efuse + lc_ctrl mirror
#   rom_ctrl   : combine endianness(bit0)+swap(5:1) -> one uint param
_TOML_REG_MAP = {
    "LC_STATE": ("lc_state", None),
    "SBOOT_DIS": ("uint32", "sboot_dis"),
    "TRANSIENT_RMA_EN": ("uint32", "transient_rma_en"),
    "SiP_DIS": ("uint_lohi", ("sip_dis_lo", "sip_dis_hi")),
    "SYS_DIS": ("uint_lohi", ("sys_dis_lo", "sys_dis_hi")),
    "RMA_SIP_TOKEN": ("array8", "rma_sip_token"),
    "RMA_CHIPLET_TOKEN": ("array8", "rma_chiplet_token"),
    "CLASS_KEY": ("array8", "class_key"),
    "CHIPLET_PUBK_REVOKE": ("uint32", "chiplet_pubk_revoke"),
    "BL1_VERSION": ("array8", "bl1_version"),
    "BL2_VERSION": ("array8", "bl2_version"),
    "CHIPLET_UID": ("array8", "chiplet_uid"),
    "SiP_PUBK": ("array8", "sip_pubk_hash0"),
    "SiP_UID": ("array8", "sip_uid"),
    "SYS_PUBK": ("array8", "sys_pubk_hash"),
    "SYS_UID": ("array8", "sys_uid"),
    "STATUS_RPT": ("uint32", "status_rpt"),
    "SEP_ROM_CTRL": ("rom_ctrl", "sep_rom_ctrl"),
    "SYSCLK_FREQ_MHZ": ("uint32", "sysclk_freq_mhz"),
    # CHIPLET_PUBK_HASH0/1 is the RDL's name, PUBLIC_KEY_0/1 the model's; both
    # spellings map to the same fuses.
    "CHIPLET_PUBK_HASH0": ("array8", "chiplet_pubk_hash0"),
    "CHIPLET_PUBK_HASH1": ("array8", "chiplet_pubk_hash1"),
    "PUBLIC_KEY_0": ("array8", "chiplet_pubk_hash0"),
    "PUBLIC_KEY_1": ("array8", "chiplet_pubk_hash1"),
    "SIP_PUBK_HASH1": ("array8", "sip_pubk_hash1"),
    # Identity fuses. Reachable only since the model gained these registers --
    # they were inside a generic RESERVED block before, so a manifest with
    # identity usage constraints could not be tested at all.
    "SEP_CHIPLET_ID": ("array8", "sep_chiplet_id"),
    "SEP_SIP_ID": ("array8", "sep_sip_id"),
    "SEP_SYS_ID": ("array8", "sep_sys_id"),
}

_TOML_IGNORE_PREFIX = "RESERVED_"


def _fields(reg_body) -> dict:
    """Return a register's ``fields`` sub-table (empty if malformed)."""
    if isinstance(reg_body, dict) and isinstance(reg_body.get("fields"), dict):
        return reg_body["fields"]
    return {}


def _field_value(fields: dict, name: str, default: int = 0) -> int:
    body = fields.get(name)
    if not isinstance(body, dict) or "value" not in body:
        return default
    return _to_int(body["value"])


def _sole_field_value(reg: str, fields: dict) -> int:
    """Value of a register's single meaningful (non-``rsvd``) field; 0 if none."""
    named = [
        (n, b["value"])
        for n, b in fields.items()
        if n != "rsvd" and isinstance(b, dict) and "value" in b
    ]
    if not named:
        return 0
    if len(named) > 1:
        raise ValueError(
            f"register {reg} has multiple value-bearing fields "
            f"{[n for n, _ in named]}; expected exactly one"
        )
    return _to_int(named[0][1])


def _split_words(value: int, n: int = 8) -> List[int]:
    """Split an integer into *n* little-endian 32-bit words (word[0] = bits 31:0)."""
    value = _to_int(value)
    if value >> (32 * n):
        warnings.warn(f"fuse value {value:#x} exceeds {32 * n} bits; truncating to {n} words")
    return [(value >> (32 * i)) & 0xFFFFFFFF for i in range(n)]


def _lc_state_from_diff(enc) -> int:
    """Decode the RTL differential LC_STATE byte ({~raw,raw}) to the raw sep-vp code."""
    enc = _to_int(enc) & 0xFF
    raw = enc & 0xF
    if (enc >> 4) != ((~raw) & 0xF):
        warnings.warn(
            f"LC_STATE value {enc:#04x} is not cleanly differential-encoded "
            f"({{~raw,raw}}); using low nibble {raw:#x} as the sep-vp lc_state code"
        )
    return raw


def overrides_from_toml(config: dict) -> List[Override]:
    """Turn a parsed RTL eFuse-config TOML into sep-vp ini overrides.

    Field *values* are mapped per :data:`_TOML_REG_MAP`. The ``LOCKS`` vector is
    reconstructed from each register's ``write_locked``/``read_locked`` flags using
    the same field-index scheme as ``generate_efuse_preload.py`` (write-lock at bit
    ``2*i``, read-lock at ``2*i+1``, where ``i`` is the register's position among the
    non-LOCKS registers, LC_STATE=0), so the emitted ``locks_lo`` matches the
    ``.preload`` the RTL flow would build from the same file.
    """
    overrides: List[Override] = []
    unmapped: List[str] = []

    # Ordered non-LOCKS registers — the enumeration `generate_efuse_preload.py` uses
    # to place lock bits. LOCKS itself never carries a value in real configs.
    ordered = [(name, body) for name, body in config.items() if name != "LOCKS"]

    derived_locks = 0
    saw_lock_flags = False
    for i, (reg, body) in enumerate(ordered):
        if isinstance(body, dict):
            if "write_locked" in body or "read_locked" in body:
                saw_lock_flags = True
            if str(body.get("write_locked", "")).lower() == "true":
                derived_locks |= 1 << (2 * i)
            if str(body.get("read_locked", "")).lower() == "true":
                derived_locks |= 1 << (2 * i + 1)

        if reg.startswith(_TOML_IGNORE_PREFIX):
            continue
        spec = _TOML_REG_MAP.get(reg)
        if spec is None:
            unmapped.append(reg)
            continue

        kind, target = spec
        fields = _fields(body)
        if kind == "uint32":
            v = _sole_field_value(reg, fields)
            if v >> 32:
                warnings.warn(
                    f"register {reg} value {v:#x} exceeds 32 bits; "
                    f"sep-vp param {target} takes the low 32 bits only"
                )
            overrides.append(("uint", _EFUSE_PREFIX + target, v & 0xFFFFFFFF))
        elif kind == "uint_lohi":
            v = _sole_field_value(reg, fields)
            lo_name, hi_name = target
            overrides.append(("uint", _EFUSE_PREFIX + lo_name, v & 0xFFFFFFFF))
            overrides.append(("uint", _EFUSE_PREFIX + hi_name, (v >> 32) & 0xFFFFFFFF))
        elif kind == "array8":
            v = _sole_field_value(reg, fields)
            overrides.append(("string", _EFUSE_PREFIX + target, _split_words(v)))
        elif kind == "lc_state":
            lc = _lc_state_from_diff(_sole_field_value(reg, fields))
            overrides.append(("uint", _EFUSE_PREFIX + "lc_state", lc))
            overrides.append(("int", _LC_CTRL_LC_STATE, lc))
        elif kind == "rom_ctrl":
            end = _field_value(fields, "rom_endianness_ctrl")
            swap = _field_value(fields, "rom_swap_ctrl")
            overrides.append(("uint", _EFUSE_PREFIX + target, (end & 0x1) | ((swap & 0x1F) << 1)))

    # An explicit [LOCKS] value (rare) ORs into the flag-derived vector.
    if "LOCKS" in config:
        explicit = _sole_field_value("LOCKS", _fields(config["LOCKS"]))
        derived_locks |= explicit
        saw_lock_flags = saw_lock_flags or explicit != 0

    if saw_lock_flags:
        if derived_locks >> 32:
            warnings.warn(
                f"LOCKS vector {derived_locks:#x} sets bits above 31; sep-vp exposes "
                f"only locks_lo (low 32 bits), so higher lock bits are dropped"
            )
        overrides.append(("uint", _EFUSE_PREFIX + "locks_lo", derived_locks & 0xFFFFFFFF))

    if unmapped:
        warnings.warn(
            "fuse-map TOML has registers with no sep-vp param (ignored): "
            + ", ".join(sorted(set(unmapped)))
        )
    return overrides


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


def load_toml(otp_path) -> List[Override]:
    """Load an RTL eFuse-config TOML file and return ini overrides."""
    path = Path(otp_path)
    if not path.is_file():
        raise FileNotFoundError(f"fuse-map not found: {path}")
    try:
        import toml  # stdlib tomllib rejects the >64-bit key/token literals RTL uses.
    except ImportError as e:
        raise RuntimeError(
            "reading a .toml fuse-map requires the 'toml' package "
            "(uv sync --group vp; it is in pyproject.toml's vp dependency group)"
        ) from e
    with open(path) as f:
        data = toml.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"fuse-map {path} must be a TOML table of REGISTER.fields.<name>.value")
    return overrides_from_toml(data)


def load(otp_path) -> List[Override]:
    """Load a fuse-map (``.toml`` RTL config or ``.yaml`` VP-native map) -> overrides.

    Dispatch is by file extension; anything other than ``.toml`` is treated as YAML
    (the historical default).
    """
    if Path(otp_path).suffix.lower() == ".toml":
        return load_toml(otp_path)
    return load_yaml(otp_path)
