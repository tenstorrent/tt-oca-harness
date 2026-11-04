# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Unit tests for sepvp.fuses — YAML fuse-maps and the RTL DV TOML image.

No sep-vp build or run required, so these are fast and
run in any environment (unlike the bootcode/fw_sep integration suites).
"""

from pathlib import Path

import pytest
from sepvp import fuses, paths

pytestmark = pytest.mark.hostonly

EF = "och_sep_ss1.sep_efuse."


def _by_key(overrides):
    """Collapse (section, key, value) overrides to {key: (section, value)} (last wins)."""
    return {key: (section, val) for section, key, val in overrides}


def test_yaml_scalar_and_array_typing():
    ov = _by_key(
        fuses.overrides_from_map(
            {"sboot_dis": 1, "locks_lo": "0xA800", "chiplet_uid": [1, 2, 3, 4, 5, 6, 7, 8]}
        )
    )
    assert ov[EF + "sboot_dis"] == ("uint", 1)
    assert ov[EF + "locks_lo"] == ("uint", 0xA800)  # hex string parsed
    assert ov[EF + "chiplet_uid"] == ("string", [1, 2, 3, 4, 5, 6, 7, 8])


def test_load_dispatches_yaml_by_extension(tmp_path):
    p = tmp_path / "map.yaml"
    p.write_text("lc_state: PROD\nsboot_dis: 1\n")
    ov = _by_key(fuses.load(p))
    assert ov[EF + "lc_state"] == ("uint", 0x1)
    assert ov[EF + "sboot_dis"] == ("uint", 1)


def test_load_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        fuses.load("/no/such/fuse_map.toml")


# --------------------------------------------------------------------------- #
# TOML through the RTL DV eFuse image
# --------------------------------------------------------------------------- #
CONFIGS = paths.OCAH_ROOT / "hw/sys/sep/dv/tb/efuse_preloads/efuse_configurations"
FUSE_MAPS = Path(__file__).parent / "fuse_maps"

# Expected non-zero words per real DV configuration, from the specification-anchored
# layout: LC_STATE is word 3, SIP_DIS words 6-7, SYS_DIS words 8-9, chiplet_dbg is bit 1.
TOML_CASES = [
    ("prod", "sep_efuse_lc_prod.toml", {3: 0xE1}),
    ("test_dev_sip", "sep_efuse_lc_test_dev_chiplet_dbg_sip.toml", {3: 0xF0, 6: 0x2}),
    ("rma_sip_sip", "sep_efuse_lc_rma_sip_chiplet_dbg_sip.toml", {3: 0xD2, 6: 0x2}),
    ("rma_sip_sys", "sep_efuse_lc_rma_sip_chiplet_dbg_sys.toml", {3: 0xD2, 8: 0x2}),
    ("rma_sip_open", "sep_efuse_lc_rma_sip.toml", {3: 0xD2}),
    ("rma_chiplet_sip", "sep_efuse_lc_rma_chiplet_chiplet_dbg_sip.toml", {3: 0x96, 6: 0x2}),
]
TOML_IDS = [case[0] for case in TOML_CASES]

# prod_secure.yaml, the VP-native PROD map, sets a UID the RTL PROD configuration leaves
# erased; every other policy fuse agrees.
PROD_YAML = FUSE_MAPS / "prod_secure.yaml"


def _toml(tmp_path, lc_state):
    path = tmp_path / "lc.toml"
    path.write_text(f"[LC_STATE]\n  [LC_STATE.fields.lc_state]\n  value = {lc_state:#x}\n")
    return path


def test_yaml_symbolic_lc_state_targets_efuse_only():
    ov = _by_key(fuses.overrides_from_map({"lc_state": "PROD"}))
    assert ov == {EF + "lc_state": ("uint", 0x1)}


@pytest.mark.parametrize("name, config, nonzero", TOML_CASES, ids=TOML_IDS)
def test_real_toml_complete_image(name, config, nonzero):
    image = fuses.load_toml_image(CONFIGS / config)
    assert len(image.words) == 256
    assert image.words == [nonzero.get(index, 0) for index in range(256)]
    assert image.lc_raw() == nonzero[3] & 0xF
    assert image.field_int("SBOOT_DIS") == 0
    assert image.field_int("SIP_DIS") == nonzero.get(6, 0)
    assert image.field_int("SYS_DIS") == nonzero.get(8, 0)
    assert image.field_int("LOCKS") == 0
    assert image.field_int("LOCKS_SPARE") == 0
    assert image.field_int("CHIPLET_UID") == 0


def test_real_yaml_toml_profile_delta():
    yaml_ov = {
        key[len(EF) :]: value for key, (_, value) in _by_key(fuses.load_yaml(PROD_YAML)).items()
    }
    image = fuses.load_toml_image(CONFIGS / "sep_efuse_lc_prod.toml")
    assert set(yaml_ov) == {"lc_state", "sboot_dis", "locks_lo", "chiplet_uid"}
    assert yaml_ov["lc_state"] == image.lc_raw()
    assert yaml_ov["sboot_dis"] == image.field_int("SBOOT_DIS")
    assert yaml_ov["locks_lo"] == image.field_int("LOCKS")
    assert yaml_ov["chiplet_uid"] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert image.field_int("CHIPLET_UID") == 0


def test_nonzero_lock_words_survive_round_trip(tmp_path):
    image = fuses.load_toml_image(CONFIGS / "sep_efuse_lc_test_dev_sip_dis_read_locked.toml")
    assert image.field_int("LOCKS") != 0
    out = image.write_hex(tmp_path / "efuse.hex")
    reloaded = type(image)().load(out)
    assert reloaded.field_int("LOCKS") == image.field_int("LOCKS")
    assert reloaded.field_int("LOCKS_SPARE") == image.field_int("LOCKS_SPARE")
    assert reloaded.words == image.words


@pytest.mark.parametrize("name, config, nonzero", TOML_CASES, ids=TOML_IDS)
def test_toml_write_hex_exact(tmp_path, name, config, nonzero):
    image = fuses.load_toml_image(CONFIGS / config)
    out = image.write_hex(tmp_path / "efuse.hex")
    words = out.read_text().splitlines()
    assert len(words) == 256
    assert words == [f"{word:08x}" for word in image.words]
    assert type(image)().load(out).words == image.words


@pytest.mark.parametrize(
    "lc_state, raw",
    [(0xF0, 0x0), (0xE1, 0x1), (0xD2, 0x2), (0x96, 0x6)],
    ids=["test_dev", "prod", "rma_sip", "rma_chiplet"],
)
def test_lifecycle_validation_accepts(tmp_path, lc_state, raw):
    assert fuses.load_toml_image(_toml(tmp_path, lc_state)).lc_raw() == raw


@pytest.mark.parametrize(
    "lc_state, message",
    [
        (0x01, "LC_STATE is not canonically differential-encoded"),
        (0xB4, "LC_STATE raw 0x4 is not a legal lifecycle state"),
    ],
    ids=["noncanonical", "illegal"],
)
def test_lifecycle_validation_rejects(tmp_path, lc_state, message):
    with pytest.raises(ValueError, match=message):
        fuses.load_toml_image(_toml(tmp_path, lc_state))


def test_unknown_toml_register_is_rejected(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text("[NOT_A_REGISTER]\nvalue = 1\n")
    with pytest.raises(KeyError, match="unknown eFuse register 'NOT_A_REGISTER'"):
        fuses.load_toml_image(path)


@pytest.mark.parametrize(
    "body, error, message",
    [
        ("[SiP_DIS]\nvalue = 2\n", KeyError, "unknown eFuse register 'SiP_DIS'"),
        (
            "[SIP_DIS]\nwrite_locked = 'True'\nvalue = 2\n",
            ValueError,
            "lock bits are not implemented",
        ),
    ],
    ids=["stale_sip_dis_spelling", "per_register_lock_key"],
)
def test_stale_vp_toml_schema_is_rejected(tmp_path, body, error, message):
    path = tmp_path / "stale.toml"
    path.write_text(f"[LC_STATE]\nvalue = 0xE1\n{body}")
    with pytest.raises(error, match=message):
        fuses.load_toml_image(path)
