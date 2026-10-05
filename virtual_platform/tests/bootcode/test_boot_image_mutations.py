# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import boot_image_mutations as bim
import oca_layout as L
import pytest

pytestmark = pytest.mark.hostonly


def _spec(tmp_path, text, name="m"):
    (tmp_path / f"{name}.toml").write_text(text)
    return bim.load_mutations(tmp_path)[name]


def test_fill_blanks_only_the_declared_span():
    base = bytes(range(16))

    patched = bim.apply_patches(base, (bim.Fill(4, 8, 0xFF),))

    assert patched == base[:4] + b"\xff" * 4 + base[8:]
    assert base == bytes(range(16))


def test_fill_to_end_covers_the_image_tail():
    base = bytes(range(16))

    patched = bim.apply_patches(base, (bim.Fill(12, None, 0xFF),))

    assert patched == base[:12] + b"\xff" * 4


def test_rejects_a_fill_that_changes_nothing():
    with pytest.raises(ValueError, match="no-op"):
        bim.apply_patches(b"\xff" * 8, (bim.Fill(0, 4, 0xFF),))


def test_rejects_a_fill_past_the_end_of_the_image():
    with pytest.raises(ValueError, match="out of bounds"):
        bim.apply_patches(bytes(8), (bim.Fill(4, 16, 0xFF),))


def test_byte_patches_set_and_xor_one_byte():
    base = bytes(range(8))

    assert bim.apply_patches(base, (bim.SetByte(2, 0xAA),))[2] == 0xAA
    assert bim.apply_patches(base, (bim.XorByte(2, 0xFF),))[2] == 0xFD


def test_a_little_endian_field_write_touches_only_the_bytes_that_differ():
    # payload_offset as the packer writes it: 0x1000 over eight little-endian bytes.
    base = bytes([0x00, 0x10, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]) + b"\xaa"

    patched = bim.apply_patches(base, (bim.SetInt(0, 0x100, 8),))

    assert patched[:8] == bytes([0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
    assert patched[8] == 0xAA, "the write must not run past the field"


def test_a_field_write_rejects_a_value_too_wide_for_its_size():
    with pytest.raises(ValueError, match="does not fit"):
        bim.apply_patches(bytes(8), (bim.SetInt(0, 0x10000, 2),))


def test_a_field_write_that_changes_nothing_is_rejected():
    base = bytes([0x00, 0x10, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])

    with pytest.raises(ValueError, match="no-op"):
        bim.apply_patches(base, (bim.SetInt(0, 0x1000, 8),))


def test_a_field_write_rejects_a_field_running_past_the_image():
    with pytest.raises(ValueError, match="out of bounds"):
        bim.apply_patches(bytes(4), (bim.SetInt(0, 1, 8),))


def test_rejects_byte_patches_that_change_nothing():
    base = bytes(range(8))

    with pytest.raises(ValueError, match="no-op"):
        bim.apply_patches(base, (bim.SetByte(2, 0x02),))
    with pytest.raises(ValueError, match="no-op"):
        bim.apply_patches(base, (bim.XorByte(2, 0x00),))


def test_byte_patch_spec(tmp_path):
    m = _spec(tmp_path, 'base = "signed"\npatch = [{ fill = [0x1000, 0x41000], value = 0xFF }]\n')
    assert m.base == "signed"
    assert m.patch == (bim.Fill(0x1000, 0x41000, 0xFF),)
    assert m.pack_config is None and m.set == () and m.pin == () and m.ops == ()


def test_repack_edits_are_slot_aware(tmp_path):
    m = _spec(
        tmp_path,
        'pack_config = "oca_secure_boot"\n'
        'set = [{ target = "bundle", slot = "backup", path = "manifest_identifier", '
        'value = "X" },\n'
        '       { target = "image", path = "combos.1.payload_offset", value = 0x43000 }]\n',
    )
    assert m.set[0] == bim.PackEdit("bundle", "backup", "manifest_identifier", "X")
    assert m.set[1].slot is None
    assert m.base is None


def test_repack_may_not_rewrite_combo_config_paths(tmp_path):
    with pytest.raises(ValueError, match="combos"):
        _spec(
            tmp_path,
            'pack_config = "oca_secure_boot"\n'
            'set = [{ target = "image", path = "combos.0.config", value = "x" }]\n',
        )


def test_an_image_end_value_moves_a_payload_image(tmp_path):
    m = _spec(
        tmp_path,
        'pack_config = "oca_toc_cap_boot"\n'
        'set = [{ target = "bundle", slot = "primary", path = "payload_images.0.offset", '
        'value = "4092 - {image_len}" }]\n',
    )
    assert m.set[0].value == "4092 - {image_len}"


@pytest.mark.parametrize(
    "edit",
    [
        'target = "bundle", slot = "primary", path = "payload_images.0.load_addr", '
        'value = "4092 - {image_len}"',
        'target = "image", path = "payload_images.0.offset", value = "4092 - {image_len}"',
        'target = "bundle", slot = "primary", path = "payload_images.0.offset", '
        'value = "4092-{image_len}"',
        'target = "bundle", slot = "primary", path = "payload_images.0.offset", '
        'value = "{image_len} - 4092"',
    ],
)
def test_an_image_end_value_is_refused_outside_a_payload_image_offset(tmp_path, edit):
    with pytest.raises(ValueError, match="image_len"):
        _spec(tmp_path, f'pack_config = "oca_toc_cap_boot"\nset = [{{ {edit} }}]\n')


def test_bundle_edit_needs_a_slot(tmp_path):
    with pytest.raises(ValueError, match="slot"):
        _spec(
            tmp_path,
            'pack_config = "oca_secure_boot"\n'
            'set = [{ target = "bundle", path = "secure_boot", value = 0 }]\n',
        )


def test_ops_spec(tmp_path):
    m = _spec(
        tmp_path,
        'base = "signed"\n'
        'ops = [{ op = "set_toc_image_count", slot = "primary", args = { value = 0 } }]\n',
    )
    assert m.ops == (bim.OcaOp("set_toc_image_count", "primary", {"value": 0}),)
    assert m.patch == ()


def test_ops_args_default_to_empty(tmp_path):
    m = _spec(tmp_path, 'base = "signed"\nops = [{ op = "clear_secure_boot", slot = "backup" }]\n')
    assert m.ops == (bim.OcaOp("clear_secure_boot", "backup", {}),)


def test_field_patch_resolves_to_the_slot_offset(tmp_path):
    m = _spec(
        tmp_path,
        'base = "signed"\n'
        'patch = [{ field = "OFF_DEMOTION_CONTROL", slot = "backup", le = 5, size = 2 }]\n',
    )
    assert m.patch[0] == bim.SetInt(L.BACKUP_OFFSET + L.C.OFF_DEMOTION_CONTROL, 5, 2)


def test_field_patch_resolves_the_primary_slot_for_xor(tmp_path):
    m = _spec(
        tmp_path,
        'base = "signed"\npatch = [{ field = "OFF_MANIFEST_HASH", slot = "primary", xor = 1 }]\n',
    )
    assert m.patch[0] == bim.XorByte(L.PRIMARY_OFFSET + L.C.OFF_MANIFEST_HASH, 1)


def test_pack_config_and_ops_are_exclusive(tmp_path):
    with pytest.raises(ValueError, match="pack_config"):
        _spec(
            tmp_path,
            'pack_config = "oca_secure_boot"\nops = [{ op = "x", slot = "primary" }]\n'
            'set = [{ target = "image", path = "total_size", value = 1 }]\n',
        )


def test_both_counts_as_primary_and_backup_for_duplicates(tmp_path):
    with pytest.raises(ValueError, match="twice"):
        _spec(
            tmp_path,
            'pack_config = "oca_secure_boot"\n'
            'set = [{ target = "bundle", slot = "both", path = "secure_boot", value = 0 }]\n'
            'pin = [{ target = "bundle", slot = "backup", path = "secure_boot", value = 1 }]\n',
        )


_REPACK = 'pack_config = "oca_secure_boot"\n'
_SET_OK = 'set = [{ target = "bundle", slot = "primary", path = "secure_boot", value = 0 }]\n'


@pytest.mark.parametrize(
    "body, message",
    [
        ("", "must be a byte patch"),
        ('base = "signed"', "at least one patch"),
        ("patch = [{ fill = [0, 16], value = 0xFF }]", "base"),
        ('base = "signed"\ntier = "T2"\npatch = [{ fill = [0, 16], value = 0xFF }]', "unknown"),
        ('base = "signed"\npatch = [{ fill = [16, 16], value = 0xFF }]', "range is empty"),
        ('base = "signed"\npatch = [{ fill = [0, 16], value = 256 }]', "value must be a byte"),
        ('base = "signed"\npatch = [{ offset = 4 }]', "value, xor or le"),
        ('base = "signed"\npatch = [{ offset = 4, le = 1 }]', "needs a size"),
        ('base = "signed"\npatch = [{ offset = 4, le = 1, size = 3 }]', "size must be"),
        ('base = "signed"\npatch = [{ offset = 4, le = -1, size = 4 }]', "non-negative"),
        ('base = "signed"\npatch = [{ fill = [0, 16], offset = 4, value = 1 }]', "exactly one"),
        ('base = "signed"\npatch = [{ size = 4, value = 1 }]', "exactly one"),
        ('base = "signed"\npatch = [{ field = "OFF_MANIFEST_LENGTH", value = 1 }]', "slot"),
        (
            'base = "signed"\npatch = [{ field = "OFF_TOC_MAGIC", slot = "primary", value = 1 }]',
            "OFF_TOC_",
        ),
        (
            'base = "signed"\npatch = [{ field = "PAYLOAD", slot = "primary", value = 1 }]',
            "OFF_",
        ),
        (
            'base = "signed"\npatch = [{ field = "OFF_NOPE", slot = "primary", value = 1 }]',
            "no OCA field",
        ),
        (
            'base = "signed"\npatch = [{ field = "OFF_MANIFEST_LENGTH", slot = "middle", value = 1 }]',
            "slot",
        ),
        ('base = "signed"\npatch = [{ offset = 4, slot = "primary", value = 1 }]', "slot"),
        (_REPACK + 'base = "signed"\n' + _SET_OK, "pack_config"),
        (_REPACK, "at least one set"),
        (
            _REPACK + 'pin = [{ target = "image", path = "total_size", value = 1 }]\n',
            "at least one set",
        ),
        ('pack_config = "secure_boot_test.yaml"\n' + _SET_OK, "oca_"),
        ('pack_config = "oca_secure_boot.yaml"\n' + _SET_OK, "oca_"),
        ('pack_config = "oca_x/oca_y"\n' + _SET_OK, "oca_"),
        ('pack_config = "oca_no_such_config"\n' + _SET_OK, "no packer config"),
        (_REPACK + 'set = [{ slot = "primary", path = "a", value = 1 }]\n', "target"),
        (_REPACK + 'set = [{ target = "flash", path = "a", value = 1 }]\n', "target"),
        (
            _REPACK + 'set = [{ target = "image", slot = "primary", path = "a", value = 1 }]\n',
            "slot",
        ),
        (
            _REPACK + 'set = [{ target = "bundle", slot = "middle", path = "a", value = 1 }]\n',
            "slot",
        ),
        (_REPACK + 'set = [{ target = "image", path = "", value = 1 }]\n', "path"),
        (_REPACK + 'set = [{ target = "image", path = "a..b", value = 1 }]\n', "path"),
        (_REPACK + 'set = [{ target = "image", path = "a" }]\n', "value"),
        (_REPACK + 'set = [{ target = "image", path = "a", value = true }]\n', "value"),
        (_REPACK + 'set = [{ target = "image", path = "a", value = 1.5 }]\n', "value"),
        (_REPACK + 'set = [{ target = "image", path = "a", value = 1, x = 1 }]\n', "unknown"),
        (
            _REPACK + 'set = [{ target = "image", path = "a", value = 1 },\n'
            '       { target = "image", path = "a", value = 2 }]\n',
            "twice",
        ),
        ('base = "signed"\n' + _SET_OK, "pack_config"),
        ('base = "signed"\npin = [{ target = "image", path = "a", value = 1 }]\n', "pack_config"),
        ('base = "signed"\nops = []\n', "at least one op"),
        ('base = "signed"\nops = [{ op = "", slot = "primary" }]\n', "op"),
        ('base = "signed"\nops = [{ op = "x", slot = "both" }]\n', "slot"),
        ('base = "signed"\nops = [{ op = "x" }]\n', "slot"),
        ('base = "signed"\nops = [{ op = "x", slot = "primary", args = 1 }]\n', "args"),
        ('base = "signed"\nops = [{ op = "x", slot = "primary", kind = 1 }]\n', "unknown"),
        ('ops = [{ op = "x", slot = "primary" }]\n', "base"),
    ],
)
def test_rejects_invalid_mutation_specs(tmp_path, body, message):
    with pytest.raises(ValueError, match=message):
        _spec(tmp_path, body)


_SPEC = """
base = "signed"
patch = [{ fill = [0x1000, "end"], value = 0xFF }]
"""


def test_spec_dir_follows_the_testlist_dir_override(tmp_path, monkeypatch):
    (tmp_path / "boot_image_mutations").mkdir()
    (tmp_path / "boot_image_mutations" / "only_here.toml").write_text(_SPEC)
    monkeypatch.setenv("SEPVP_TESTLIST_DIR", str(tmp_path))
    assert bim.spec_dir() == tmp_path / "boot_image_mutations"
    assert set(bim.load_mutations()) == {"only_here"}


def test_spec_dir_defaults_to_the_in_tree_testlist(monkeypatch):
    monkeypatch.delenv("SEPVP_TESTLIST_DIR", raising=False)
    assert bim.spec_dir().parts[-2:] == ("testlist", "boot_image_mutations")
