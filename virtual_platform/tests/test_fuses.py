# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Unit tests for sepvp.fuses — YAML and RTL-TOML fuse-map ingestion.

Pure translation logic; no sep-vp build or run required, so these are fast and
run in any environment (unlike the bootcode/fw_sep integration suites).
"""

import warnings

import pytest
from sepvp import fuses

EF = "och_sep_ss1.sep_efuse."
LC = "och_sep_ss1.lc_ctrl.lc_state"


def _by_key(overrides):
    """Collapse (section, key, value) overrides to {key: (section, value)} (last wins)."""
    return {key: (section, val) for section, key, val in overrides}


# --------------------------------------------------------------------------- #
# YAML path (VP-native, hand-friendly) — unchanged behavior
# --------------------------------------------------------------------------- #
def test_yaml_symbolic_lc_state_mirrors_lc_ctrl():
    ov = _by_key(fuses.overrides_from_map({"lc_state": "PROD"}))
    assert ov[EF + "lc_state"] == ("uint", 0x1)
    assert ov[LC] == ("int", 0x1)


def test_yaml_scalar_and_array_typing():
    ov = _by_key(
        fuses.overrides_from_map(
            {"sboot_dis": 1, "locks_lo": "0xA800", "chiplet_uid": [1, 2, 3, 4, 5, 6, 7, 8]}
        )
    )
    assert ov[EF + "sboot_dis"] == ("uint", 1)
    assert ov[EF + "locks_lo"] == ("uint", 0xA800)  # hex string parsed
    assert ov[EF + "chiplet_uid"] == ("string", [1, 2, 3, 4, 5, 6, 7, 8])


# --------------------------------------------------------------------------- #
# TOML path (RTL/UVM eFuse config) — the new ingestion
# --------------------------------------------------------------------------- #
def _reg(value, fieldname="v", **flags):
    body = {
        "read_locked": "False",
        "write_locked": "False",
        "fields": {fieldname: {"value": value}},
    }
    body.update(flags)
    return body


@pytest.mark.parametrize(
    "enc, raw",
    [
        (0xF0, 0x0),  # TEST_DEV
        (0xE1, 0x1),  # PROD
        (0xD2, 0x2),  # RMA_SIP
    ],
)
def test_toml_lc_state_differential_decode(enc, raw):
    ov = _by_key(fuses.overrides_from_toml({"LC_STATE": _reg(enc, "lc_state")}))
    assert ov[EF + "lc_state"] == ("uint", raw)
    assert ov[LC] == ("int", raw)  # both models set from one entry


def test_toml_lc_state_non_differential_warns_but_uses_low_nibble():
    with pytest.warns(UserWarning, match="differential"):
        ov = _by_key(fuses.overrides_from_toml({"LC_STATE": _reg(0x01, "lc_state")}))
    assert ov[EF + "lc_state"] == ("uint", 0x1)


def test_toml_256bit_field_splits_little_endian():
    # word[0] must be the least-significant 32 bits (matches RTL bit-packer + VP load).
    val = 0x54E01F1D0EB208A04DBD502A53BDA99B
    ov = _by_key(fuses.overrides_from_toml({"CLASS_KEY": _reg(val, "key")}))
    section, words = ov[EF + "class_key"]
    assert section == "string"
    assert words == [0x53BDA99B, 0x4DBD502A, 0x0EB208A0, 0x54E01F1D, 0, 0, 0, 0]


def test_toml_64bit_field_splits_lo_hi():
    ov = _by_key(fuses.overrides_from_toml({"SiP_DIS": _reg(0xDEADBEEF_0000000F, "sip_dis")}))
    assert ov[EF + "sip_dis_lo"] == ("uint", 0x0000000F)
    assert ov[EF + "sip_dis_hi"] == ("uint", 0xDEADBEEF)


def test_toml_locks_derived_from_read_lock_flags():
    # Read-locking the 6th/7th/8th non-LOCKS registers (idx 5,6,7) => bits 11,13,15 = 0xA800,
    # exactly what generate_efuse_preload.py packs and what efuse_vp.ini uses for bl1_pass.
    order = [
        "LC_STATE",
        "SBOOT_DIS",
        "TRANSIENT_RMA_EN",
        "SiP_DIS",
        "SYS_DIS",
        "RMA_SIP_TOKEN",
        "RMA_CHIPLET_TOKEN",
        "CLASS_KEY",
    ]
    field = {
        "LC_STATE": "lc_state",
        "SBOOT_DIS": "disable_secure_boot",
        "TRANSIENT_RMA_EN": "transient_rma_en",
        "SiP_DIS": "sip_dis",
        "SYS_DIS": "sys_dis",
        "RMA_SIP_TOKEN": "token",
        "RMA_CHIPLET_TOKEN": "token",
        "CLASS_KEY": "key",
    }
    locked = {"RMA_SIP_TOKEN", "RMA_CHIPLET_TOKEN", "CLASS_KEY"}
    cfg = {
        r: _reg(
            0xE1 if r == "LC_STATE" else 0, field[r], read_locked="True" if r in locked else "False"
        )
        for r in order
    }
    ov = _by_key(fuses.overrides_from_toml(cfg))
    assert ov[EF + "locks_lo"] == ("uint", 0xA800)


def test_toml_write_lock_bit_positions():
    # write-lock at bit 2*i; LC_STATE is idx 0 -> bit 0, SBOOT_DIS idx 1 -> bit 2.
    cfg = {
        "LC_STATE": _reg(0xF0, "lc_state", write_locked="True"),
        "SBOOT_DIS": _reg(0, "disable_secure_boot", write_locked="True"),
    }
    ov = _by_key(fuses.overrides_from_toml(cfg))
    assert ov[EF + "locks_lo"] == ("uint", (1 << 0) | (1 << 2))


def test_toml_no_lock_flags_emits_no_locks_override():
    # A partial hand-TOML with no lock flags must not clobber the base locks_lo default.
    ov = _by_key(
        fuses.overrides_from_toml({"SBOOT_DIS": {"fields": {"disable_secure_boot": {"value": 1}}}})
    )
    assert EF + "locks_lo" not in ov
    assert ov[EF + "sboot_dis"] == ("uint", 1)


def test_toml_sysclk_freq_mhz_maps_to_the_vp_param():
    cfg = {"SYSCLK_FREQ_MHZ": {"fields": {"sysclk_freq_mhz": {"value": 800}}}}
    ov = _by_key(fuses.overrides_from_toml(cfg))
    assert ov[EF + "sysclk_freq_mhz"] == ("uint", 800)


def test_toml_rom_ctrl_combines_endianness_and_swap():
    cfg = {
        "SEP_ROM_CTRL": {
            "fields": {"rom_endianness_ctrl": {"value": 1}, "rom_swap_ctrl": {"value": 0b10101}}
        }
    }
    ov = _by_key(fuses.overrides_from_toml(cfg))
    assert ov[EF + "sep_rom_ctrl"] == ("uint", 1 | (0b10101 << 1))


def test_toml_unmapped_register_warns():
    with pytest.warns(UserWarning, match="no sep-vp param"):
        fuses.overrides_from_toml({"MADE_UP_REG": {"fields": {"x": {"value": 1}}}})


def test_toml_reserved_registers_ignored_without_warning():
    # No lock flags => nothing at all (RESERVED value dropped, no locks_lo, no warning).
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # any warning fails the test
        ov = _by_key(
            fuses.overrides_from_toml({"RESERVED_0": {"fields": {"rsvd": {"value": 0xDEAD}}}})
        )
    assert ov == {}


def test_toml_multiple_value_fields_is_an_error():
    bad = {"SBOOT_DIS": {"fields": {"a": {"value": 1}, "b": {"value": 2}}}}
    with pytest.raises(ValueError, match="multiple value-bearing fields"):
        fuses.overrides_from_toml(bad)


# --------------------------------------------------------------------------- #
# load() dispatch + parity
# --------------------------------------------------------------------------- #
def test_load_dispatches_toml_by_extension(tmp_path):
    p = tmp_path / "cfg.toml"
    p.write_text(
        "[LC_STATE]\nwrite_locked='False'\nread_locked='False'\n"
        "  [LC_STATE.fields.lc_state]\n  value = 0xE1\n"
    )
    ov = _by_key(fuses.load(p))
    assert ov[EF + "lc_state"] == ("uint", 0x1)


def test_load_dispatches_yaml_by_extension(tmp_path):
    p = tmp_path / "map.yaml"
    p.write_text("lc_state: PROD\nsboot_dis: 1\n")
    ov = _by_key(fuses.load(p))
    assert ov[EF + "lc_state"] == ("uint", 0x1)
    assert ov[EF + "sboot_dis"] == ("uint", 1)


def test_toml_and_yaml_agree_for_equivalent_prod_config(tmp_path):
    # The same intent expressed two ways must yield the same sep_efuse.lc_state/sboot_dis.
    toml_p = tmp_path / "c.toml"
    toml_p.write_text(
        "[LC_STATE]\n  [LC_STATE.fields.lc_state]\n  value = 0xE1\n"
        "[SBOOT_DIS]\n  [SBOOT_DIS.fields.disable_secure_boot]\n  value = 0x0\n"
    )
    from_toml = _by_key(fuses.load(toml_p))
    from_yaml = _by_key(fuses.overrides_from_map({"lc_state": "PROD", "sboot_dis": 0}))
    assert from_toml[EF + "lc_state"] == from_yaml[EF + "lc_state"]
    assert from_toml[EF + "sboot_dis"] == from_yaml[EF + "sboot_dis"]
    assert from_toml[LC] == from_yaml[LC]


def test_load_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        fuses.load("/no/such/fuse_map.toml")
