# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import boot_image_mutations as bim
import oca_layout as L
import oca_repack
import pytest
import untrusted_signing_key
from sepvp import paths

pytestmark = pytest.mark.hostonly


@pytest.fixture(scope="module")
def ready():
    if not paths.MANIFEST_VENV_PYTHON.is_file() or not paths.OCA_IMAGE_PATHS["signed"].is_file():
        pytest.skip("manifest venv or oca-images missing (P0.0)")


def test_identity_pack_is_byte_identical_to_the_make_build(ready, tmp_path):
    out = oca_repack.pack(
        paths.BOOTCODE_CONFIGS / "oca_secure_boot_image.yaml",
        tmp_path / "id.bin",
        tmp_path / "id.log",
    )
    assert out.read_bytes() == paths.OCA_IMAGE_PATHS["signed"].read_bytes()


def test_backup_bundle_edit_leaves_the_primary_slot_untouched(ready, tmp_path):
    out = oca_repack.repack(
        "lc",
        "oca_secure_boot",
        [bim.PackEdit("bundle", "backup", "manifest_identifier", "OCAHBAD")],
        [bim.PackEdit("bundle", "backup", "manifest_identifier", "OCAHSEP")],
        tmp_path,
    )
    golden = paths.OCA_IMAGE_PATHS["signed"].read_bytes()
    data = out.read_bytes()
    assert data[: L.BACKUP_OFFSET] == golden[: L.BACKUP_OFFSET]
    backup = slice(L.BACKUP_OFFSET, L.BACKUP_OFFSET + L.BODY_SIZE)
    assert data[backup] != golden[backup]
    ident = L.BACKUP_OFFSET + L.C.OFF_MANIFEST_IDENTIFIER
    assert data[ident : ident + 8] == b"OCAHBAD\x00"


def test_both_edits_each_slot_bundle(ready, tmp_path):
    out = oca_repack.repack(
        "both",
        "oca_secure_boot",
        [bim.PackEdit("bundle", "both", "manifest_identifier", "OCAHBAD")],
        [],
        tmp_path,
    )
    data = out.read_bytes()
    for base in (L.PRIMARY_OFFSET, L.BACKUP_OFFSET):
        ident = base + L.C.OFF_MANIFEST_IDENTIFIER
        assert data[ident : ident + 8] == b"OCAHBAD\x00"
    assert (tmp_path / "both.primary.yaml").is_file()
    assert (tmp_path / "both.backup.yaml").is_file()


def test_an_image_edit_reaches_the_combined_layout(ready, tmp_path):
    out = oca_repack.repack(
        "size",
        "oca_secure_boot",
        [bim.PackEdit("image", None, "total_size", 0x60000)],
        [],
        tmp_path,
    )
    golden = paths.OCA_IMAGE_PATHS["signed"].read_bytes()
    data = out.read_bytes()
    assert len(data) == 0x60000
    assert data[: len(golden)] == golden


def test_a_stale_pin_is_refused(ready, tmp_path):
    with pytest.raises(ValueError, match="no longer holds"):
        oca_repack.repack(
            "p",
            "oca_secure_boot",
            [bim.PackEdit("bundle", "primary", "secure_boot", 0)],
            [bim.PackEdit("bundle", "primary", "public_key_select_classic", 2)],
            tmp_path,
        )


def test_a_pin_on_a_missing_field_is_refused(ready, tmp_path):
    with pytest.raises(ValueError, match="no such field"):
        oca_repack.repack(
            "p",
            "oca_secure_boot",
            [bim.PackEdit("bundle", "primary", "secure_boot", 0)],
            [bim.PackEdit("image", None, "combos.5.manifest_offset", 0)],
            tmp_path,
        )


def test_an_unknown_key_is_refused(ready, tmp_path):
    with pytest.raises(RuntimeError, match="unknown key"):
        oca_repack.repack(
            "u",
            "oca_secure_boot",
            [bim.PackEdit("bundle", "primary", "no_such_field", 1)],
            [],
            tmp_path,
        )


def test_a_set_to_the_value_already_there_is_refused(ready, tmp_path):
    with pytest.raises(RuntimeError, match="changes nothing"):
        oca_repack.repack(
            "n",
            "oca_secure_boot",
            [bim.PackEdit("bundle", "primary", "secure_boot", 1)],
            [],
            tmp_path,
        )


def test_untrusted_key_placeholder(ready, tmp_path):
    out = oca_repack.repack(
        "k",
        "oca_secure_boot",
        [
            bim.PackEdit("bundle", "primary", "signing_key_file", "{untrusted_signing_key}"),
            bim.PackEdit("bundle", "primary", "signing_key_name", "{untrusted_signing_key_name}"),
        ],
        [],
        tmp_path,
    )
    derived = (tmp_path / "k.primary.yaml").read_text()
    assert str(untrusted_signing_key.ensure()) in derived
    assert untrusted_signing_key.KEY_NAME in derived
    golden = paths.OCA_IMAGE_PATHS["signed"].read_bytes()
    data = out.read_bytes()
    key = L.PRIMARY_OFFSET + L.C.OFF_PUBLIC_KEY_CLASSIC
    assert data[key : key + 384] != golden[key : key + 384]
    assert data[L.BACKUP_OFFSET :] == golden[L.BACKUP_OFFSET :]


def test_a_missing_manifest_venv_names_the_setup_command(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "MANIFEST_VENV_PYTHON", tmp_path / "no-venv" / "python")
    with pytest.raises(RuntimeError, match="uv sync"):
        oca_repack.pack(tmp_path / "x.yaml", tmp_path / "x.bin", tmp_path / "x.log")


def test_a_pack_config_without_primary_and_backup_combos_is_refused(ready, tmp_path, monkeypatch):
    (tmp_path / "oca_odd_image.yaml").write_text(
        "combos:\n  - name: backup\n    config: a.yaml\n  - name: primary\n    config: b.yaml\n"
    )
    monkeypatch.setattr(paths, "BOOTCODE_CONFIGS", tmp_path)
    with pytest.raises(ValueError, match="primary"):
        oca_repack.repack(
            "o", "oca_odd", [bim.PackEdit("bundle", "primary", "x", 1)], [], tmp_path / "out"
        )


def _payload_image_end(target: str):
    return [bim.PackEdit("bundle", "primary", "payload_images.0.offset", target)]


def test_an_image_end_value_ends_the_payload_at_the_target(ready, tmp_path):
    bundle = paths.BOOTCODE_CONFIGS / "oca_toc_cap_boot_test.yaml"
    bl1 = paths.BOOTCODE_DIR / oca_repack._lookup(
        oca_repack.yaml.safe_load(bundle.read_text()), "payload_images.0.path", bundle.name
    )
    out = oca_repack.repack(
        "end", "oca_toc_cap_boot", _payload_image_end("4092 - {image_len}"), [], tmp_path
    )
    data = out.read_bytes()
    slot = L.PRIMARY_OFFSET
    payload = slot + int.from_bytes(data[slot + L.OFF_PAYLOAD_OFFSET :][:8], "little")
    entry = payload + L.TOC_HEADER_SIZE
    assert int.from_bytes(data[slot + L.OFF_PAYLOAD_LENGTH :][:8], "little") == 4092
    assert int.from_bytes(data[entry + L.C.OFF_TOC_ENTRY_OFFSET :][:8], "little") == (
        4092 - bl1.stat().st_size
    )


def test_an_image_end_before_the_image_fits_is_refused(ready, tmp_path):
    with pytest.raises(ValueError, match="longer than the payload"):
        oca_repack.repack(
            "short", "oca_toc_cap_boot", _payload_image_end("100 - {image_len}"), [], tmp_path
        )
