# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import importlib.util

import boot_image_mutations as bim
import boot_images
import dv_env
import oca_layout as L
import pytest
from sepvp import paths
from testlist_loader import (
    MEASUREMENT_DIGEST_TOKEN,
    FieldAssert,
    ImageAssert,
    MeasurementGolden,
    RomTestCase,
    TocFieldAssert,
)

pytestmark = pytest.mark.hostonly

_IMAGES = paths.OCA_IMAGE_PATHS
_SIGNED_BYTE = L.PRIMARY_OFFSET + L.SIGNED_REGION_BYTE


@pytest.fixture(scope="module")
def golden():
    if not _IMAGES["signed"].is_file():
        pytest.skip("oca-images not built")
    return _IMAGES["signed"].read_bytes()


@pytest.fixture
def specs(tmp_path, monkeypatch):
    """Write TOML specs into a scratch directory and make them the module's mutations."""
    directory = tmp_path / "specs"
    directory.mkdir()

    def _install(**bodies):
        for name, body in bodies.items():
            (directory / f"{name}.toml").write_text(body)
        mutations = bim.load_mutations(directory)
        boot_images._validate(mutations)
        monkeypatch.setattr(boot_images, "MUTATIONS", mutations)
        return mutations

    return _install


def _case(**fields) -> RomTestCase:
    defaults = dict(
        name="t",
        family="f",
        classification="ported",
        image=None,
        base_ini=None,
        efuse={},
        observation="complete",
        boot="primary",
        rotate_update=False,
        recovery=False,
        timeout=60,
        tp_id=None,
        markers=(),
        pytest_markers=(),
        expect=(),
        forbid=(),
        expect_counts={},
        terminal_token=None,
        expect_silence=False,
        expect_status=(),
        forbid_status=(),
        expect_verdict=None,
        preloaded_test_programs=(),
        init_writes=(),
        spi_reads=(),
        spi_read_order=(),
        image_asserts=(),
        smc_sram_image=None,
        smc_sram_source=None,
        smc_sram_offset=None,
        smc_sram_manifest_at=None,
        measurement_golden=None,
    )
    defaults.update(fields)
    return RomTestCase(**defaults)


def _span(low, high, *, all_byte=None, same_as=None, differs_from=None, xor=None):
    return ImageAssert(low, high, all_byte, same_as, differs_from, xor=xor)


def _field(name, slot, size, value):
    return ImageAssert(0, None, None, None, None, field=FieldAssert(name, slot, size, value))


def _toc_field(name, slot, entry, size, value):
    check = TocFieldAssert(name, slot, entry, size, value)
    return ImageAssert(0, None, None, None, None, toc_field=check)


def test_a_base_name_resolves_to_the_prebuilt_image(tmp_path, specs):
    specs()
    assert boot_images.materialize_boot_image("signed", _IMAGES, tmp_path) == _IMAGES["signed"]


def test_known_images_cover_bases_and_specs(specs):
    specs(flip='base = "signed"\npatch = [{ offset = 24, xor = 1 }]\n')
    known = boot_images.known_images()
    assert set(_IMAGES) <= known and "flip" in known


def test_a_byte_patch_changes_only_the_named_byte(golden, tmp_path, specs):
    specs(flip=f'base = "signed"\npatch = [{{ offset = {_SIGNED_BYTE}, xor = 0x01 }}]\n')
    out = boot_images.materialize_boot_image("flip", _IMAGES, tmp_path)
    data = out.read_bytes()
    assert out == tmp_path / "flip.bin"
    assert [i for i, (a, b) in enumerate(zip(data, golden)) if a != b] == [_SIGNED_BYTE]
    assert data[_SIGNED_BYTE] == golden[_SIGNED_BYTE] ^ 0x01


def test_an_op_spec_changes_the_primary_slot_only(golden, tmp_path, specs):
    specs(
        sv='base = "signed"\n'
        'ops = [{ op = "set_security_version", slot = "primary", args = { value = 1 } }]\n'
    )
    data = boot_images.materialize_boot_image("sv", _IMAGES, tmp_path).read_bytes()
    assert data[L.BACKUP_OFFSET :] == golden[L.BACKUP_OFFSET :]
    assert data[L.PRIMARY_OFFSET : L.BACKUP_OFFSET] != golden[L.PRIMARY_OFFSET : L.BACKUP_OFFSET]
    assert dv_env.load("sep_manifest_mutate").security_version(data, "primary") == 1


def test_an_op_spec_patch_lands_after_the_op(golden, tmp_path, specs):
    hash_byte = L.PRIMARY_OFFSET + L.C.OFF_MANIFEST_HASH
    specs(
        sv='base = "signed"\n'
        'ops = [{ op = "set_security_version", slot = "primary", args = { value = 1 } }]\n'
        f"patch = [{{ offset = {hash_byte}, xor = 0x01 }}]\n"
    )
    data = boot_images.materialize_boot_image("sv", _IMAGES, tmp_path).read_bytes()
    mm = dv_env.load("sep_manifest_mutate")
    with pytest.raises(AssertionError, match="manifest_hash"):
        mm.verify_layout(data, "primary")


def test_same_as_fails_on_a_changed_region(golden, tmp_path, specs):
    specs(flip=f'base = "signed"\npatch = [{{ offset = {_SIGNED_BYTE}, xor = 0x01 }}]\n')
    out = boot_images.materialize_boot_image("flip", _IMAGES, tmp_path)
    ok = _case(image="flip", image_asserts=(_span(L.BACKUP_OFFSET, None, same_as="signed"),))
    boot_images.check_image_asserts(ok, out, _IMAGES)
    bad = _case(image="flip", image_asserts=(_span(0, L.BACKUP_OFFSET, same_as="signed"),))
    with pytest.raises(AssertionError, match="same_as"):
        boot_images.check_image_asserts(bad, out, _IMAGES)


def test_differs_from_fails_on_an_unchanged_region(golden, tmp_path, specs):
    specs(flip=f'base = "signed"\npatch = [{{ offset = {_SIGNED_BYTE}, xor = 0x01 }}]\n')
    out = boot_images.materialize_boot_image("flip", _IMAGES, tmp_path)
    ok = _case(
        image="flip",
        image_asserts=(_span(_SIGNED_BYTE, _SIGNED_BYTE + 1, differs_from="signed"),),
    )
    boot_images.check_image_asserts(ok, out, _IMAGES)
    bad = _case(image="flip", image_asserts=(_span(L.BACKUP_OFFSET, None, differs_from="signed"),))
    with pytest.raises(AssertionError, match="differs_from"):
        boot_images.check_image_asserts(bad, out, _IMAGES)


def test_a_byte_patch_compares_only_against_its_own_base(golden, tmp_path, specs):
    specs(flip=f'base = "signed"\npatch = [{{ offset = {_SIGNED_BYTE}, xor = 0x01 }}]\n')
    out = boot_images.materialize_boot_image("flip", _IMAGES, tmp_path)
    case = _case(image="flip", image_asserts=(_span(0, 16, same_as="unsigned"),))
    with pytest.raises(AssertionError, match="not a base image"):
        boot_images.check_image_asserts(case, out, _IMAGES)


def test_all_fails_on_a_byte_that_differs(golden, tmp_path, specs):
    specs(blank='base = "signed"\npatch = [{ fill = [0x1000, 0x41000], value = 0xFF }]\n')
    out = boot_images.materialize_boot_image("blank", _IMAGES, tmp_path)
    ok = _case(image="blank", image_asserts=(_span(0x1000, 0x41000, all_byte=0xFF),))
    boot_images.check_image_asserts(ok, out, _IMAGES)
    bad = _case(image="blank", image_asserts=(_span(0x1000, 0x41001, all_byte=0xFF),))
    with pytest.raises(AssertionError, match="0x41000"):
        boot_images.check_image_asserts(bad, out, _IMAGES)


def test_a_field_assert_reads_the_slot_field(golden, tmp_path, specs):
    shipped = dv_env.load("sep_manifest_mutate").demotion_control(golden, "backup")
    specs(
        dem='base = "signed"\n'
        'patch = [{ field = "OFF_DEMOTION_CONTROL", slot = "primary", le = 5, size = 2 }]\n'
    )
    out = boot_images.materialize_boot_image("dem", _IMAGES, tmp_path)
    ok = _case(
        image="dem",
        image_asserts=(
            _field("OFF_DEMOTION_CONTROL", "primary", 2, 5),
            _field("OFF_DEMOTION_CONTROL", "backup", 2, shipped),
        ),
    )
    boot_images.check_image_asserts(ok, out, _IMAGES)
    bad = _case(image="dem", image_asserts=(_field("OFF_DEMOTION_CONTROL", "primary", 2, 4),))
    with pytest.raises(AssertionError, match="OFF_DEMOTION_CONTROL"):
        boot_images.check_image_asserts(bad, out, _IMAGES)


def test_a_field_assert_on_an_unknown_field_fails(golden, tmp_path, specs):
    specs()
    case = _case(image="signed", image_asserts=(_field("OFF_NO_SUCH_FIELD", "primary", 2, 0),))
    with pytest.raises(AssertionError, match="OFF_NO_SUCH_FIELD"):
        boot_images.check_image_asserts(case, _IMAGES["signed"], _IMAGES)


def test_same_as_with_xor_requires_the_masked_reference_byte(golden, tmp_path, specs):
    specs(flip=f'base = "signed"\npatch = [{{ offset = {_SIGNED_BYTE}, xor = 0x5A }}]\n')
    out = boot_images.materialize_boot_image("flip", _IMAGES, tmp_path)
    byte = (_SIGNED_BYTE, _SIGNED_BYTE + 1)
    ok = _case(image="flip", image_asserts=(_span(*byte, same_as="signed", xor=0x5A),))
    boot_images.check_image_asserts(ok, out, _IMAGES)
    for wrong in (0xA5, 0xFF):
        bad = _case(image="flip", image_asserts=(_span(*byte, same_as="signed", xor=wrong),))
        with pytest.raises(AssertionError, match=f"xor 0x{wrong:02x}"):
            boot_images.check_image_asserts(bad, out, _IMAGES)
    # Bytes the patch left alone fail the mask, so it cannot be widened over them.
    wide = _case(
        image="flip",
        image_asserts=(_span(_SIGNED_BYTE, _SIGNED_BYTE + 2, same_as="signed", xor=0x5A),),
    )
    with pytest.raises(AssertionError, match="xor 0x5a"):
        boot_images.check_image_asserts(wide, out, _IMAGES)


def test_a_toc_field_assert_follows_the_producer_entry_layout(golden, tmp_path, specs):
    pm = dv_env.load("sep_payload_mutate")
    specs(
        moved='base = "signed"\n'
        'ops = [{ op = "set_toc_entry_offset", slot = "primary", '
        "args = { index = 0, value = 240 } }]\n"
    )
    out = boot_images.materialize_boot_image("moved", _IMAGES, tmp_path)
    data = out.read_bytes()
    shipped = pm.toc_entry(golden, "primary", 0)
    ok = _case(
        image="moved",
        image_asserts=(
            _toc_field("OFF_TOC_ENTRY_OFFSET", "primary", 0, 8, 240),
            _toc_field("OFF_TOC_ENTRY_OFFSET", "backup", 0, 8, shipped.offset),
            _toc_field("OFF_TOC_ENTRY_LENGTH", "primary", 0, 8, shipped.length),
        ),
    )
    boot_images.check_image_asserts(ok, out, _IMAGES)
    assert boot_images._toc_entry_field_at(ok, 0, data) == (
        pm.toc_entries(data, "primary")[0] + pm.E_OFFSET
    )
    bad = _case(
        image="moved",
        image_asserts=(_toc_field("OFF_TOC_ENTRY_OFFSET", "primary", 0, 8, shipped.offset),),
    )
    with pytest.raises(AssertionError, match="OFF_TOC_ENTRY_OFFSET entry 0"):
        boot_images.check_image_asserts(bad, out, _IMAGES)


def test_a_toc_field_assert_resolves_every_entry_of_a_multi_image_toc(specs):
    if not _IMAGES["multi"].is_file():
        pytest.skip("oca-images not built")
    pm = dv_env.load("sep_payload_mutate")
    specs()
    data = _IMAGES["multi"].read_bytes()
    entries = [pm.toc_entry(data, "backup", i) for i in range(3)]
    checks = tuple(
        _toc_field("OFF_TOC_ENTRY_OFFSET", "backup", i, 8, entry.offset)
        for i, entry in enumerate(entries)
    )
    case = _case(image="multi", image_asserts=checks)
    boot_images.check_image_asserts(case, _IMAGES["multi"], _IMAGES)
    assert [boot_images._toc_entry_field_at(case, i, data) for i in range(3)] == [
        entry + pm.E_OFFSET for entry in pm.toc_entries(data, "backup")
    ]


@pytest.mark.parametrize(
    "image, check, message",
    [
        ("signed", _toc_field("OFF_TOC_ENTRY_NO_SUCH", "primary", 0, 8, 0), "no OCA TOC entry"),
        ("signed", _toc_field("OFF_TOC_ENTRY_OFFSET", "primary", 1, 8, 0), "declares only 1"),
        ("encrypted", _toc_field("OFF_TOC_ENTRY_OFFSET", "primary", 0, 8, 0), "encrypted"),
    ],
)
def test_a_toc_field_assert_refuses_what_it_cannot_resolve(specs, image, check, message):
    if not _IMAGES[image].is_file():
        pytest.skip("oca-images not built")
    specs()
    case = _case(image=image, image_asserts=(check,))
    with pytest.raises(AssertionError, match=message):
        boot_images.check_image_asserts(case, _IMAGES[image], _IMAGES)


def test_a_toc_field_assert_refuses_a_payload_without_a_toc(golden, tmp_path, specs):
    toc = dv_env.load("sep_payload_mutate").payload_base(golden, "primary")
    specs(nomagic=f'base = "signed"\npatch = [{{ fill = [{toc}, {toc + 4}], value = 0 }}]\n')
    out = boot_images.materialize_boot_image("nomagic", _IMAGES, tmp_path)
    case = _case(
        image="nomagic", image_asserts=(_toc_field("OFF_TOC_ENTRY_OFFSET", "primary", 0, 8, 0),)
    )
    with pytest.raises(AssertionError, match="does not start with a TOC"):
        boot_images.check_image_asserts(case, out, _IMAGES)


def test_a_toc_field_assert_refuses_a_field_past_the_entry(golden, specs, monkeypatch):
    specs()
    monkeypatch.setattr(L.C, "OFF_TOC_ENTRY_PAST_END", L.TOC_ENTRY_SIZE - 4, raising=False)
    case = _case(
        image="signed", image_asserts=(_toc_field("OFF_TOC_ENTRY_PAST_END", "primary", 0, 8, 0),)
    )
    with pytest.raises(AssertionError, match="run past the TOC entry"):
        boot_images.check_image_asserts(case, _IMAGES["signed"], _IMAGES)


def _smc_case(manifest_at):
    return _case(
        image=None,
        boot="secondary",
        smc_sram_image="signed",
        smc_sram_source=(L.PRIMARY_OFFSET, L.BACKUP_OFFSET),
        smc_sram_offset=0,
        smc_sram_manifest_at=manifest_at,
    )


def test_the_smc_window_is_cut_from_the_base_image(golden, tmp_path, specs):
    specs()
    out = boot_images.materialize_smc_sram_image(_smc_case(0), _IMAGES, tmp_path)
    assert out == tmp_path / "t.smc_sram.bin"
    assert out.read_bytes() == golden[L.PRIMARY_OFFSET : L.BACKUP_OFFSET]


def test_the_smc_window_must_hold_a_manifest_where_the_case_says(golden, tmp_path, specs):
    specs()
    with pytest.raises(AssertionError, match="0x1000"):
        boot_images.materialize_smc_sram_image(_smc_case(0x1000), _IMAGES, tmp_path)


def test_the_smc_window_must_come_from_a_base_image(golden, tmp_path, specs):
    specs(flip=f'base = "signed"\npatch = [{{ offset = {_SIGNED_BYTE}, xor = 0x01 }}]\n')
    case = _case(
        boot="secondary",
        smc_sram_image="flip",
        smc_sram_source=(0, 0x1000),
        smc_sram_offset=0,
        smc_sram_manifest_at=0,
    )
    with pytest.raises(ValueError, match="base"):
        boot_images.materialize_smc_sram_image(case, _IMAGES, tmp_path)


def test_no_smc_window_when_the_case_declares_none(tmp_path, specs):
    specs()
    assert boot_images.materialize_smc_sram_image(_case(), _IMAGES, tmp_path) is None


def test_validate_refuses_an_unknown_base():
    mutations = {"m": bim.BootImageMutation("m", "golden_secure", (bim.SetByte(0, 1),))}
    with pytest.raises(ValueError, match="golden_secure"):
        boot_images._validate(mutations)


def test_validate_refuses_an_unknown_op():
    mutations = {
        "m": bim.BootImageMutation("m", "signed", (), ops=(bim.OcaOp("rehash", "primary", {}),))
    }
    with pytest.raises(ValueError, match="rehash"):
        boot_images._validate(mutations)


def test_validate_refuses_a_spec_that_shadows_a_base():
    mutations = {"signed": bim.BootImageMutation("signed", "unsigned", (bim.SetByte(0, 1),))}
    with pytest.raises(ValueError, match="shadows"):
        boot_images._validate(mutations)


def _dv_measurement():
    path = paths.OCAH_ROOT / "hw/sys/sep/dv/cocotb/tests/rom_fw/sep_measurement_golden.py"
    spec = importlib.util.spec_from_file_location("dv_measurement_golden", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_measurement_tokens_use_the_image_manifest_hash(golden):
    dv = _dv_measurement()
    mm = dv_env.load("sep_manifest_mutate")
    digest = mm.manifest_hash(golden, "primary")
    # Only the real manifest_hash field holds the SHA-256 of the signed region.
    assert digest == mm.signed_region_hash(golden, "primary")
    case = _case(image="signed", measurement_golden=MeasurementGolden("primary", **dv._KAT_INPUTS))
    tokens = boot_images.measurement_tokens(case, _IMAGES["signed"])
    pcr = dv.calculate_boot_pcr(digest, **dv._KAT_INPUTS)
    assert tokens == {MEASUREMENT_DIGEST_TOKEN: "BL0S_BOOT_PCR=" + pcr.hex().upper()}


@pytest.fixture
def packer():
    if not paths.MANIFEST_VENV_PYTHON.is_file():
        pytest.skip("manifest venv missing (P0.0)")


def test_a_patched_repack_writes_a_separate_file(golden, tmp_path, specs, packer):
    sig = L.BACKUP_OFFSET + L.C.OFF_SIGNATURE_CLASSIC
    specs(
        rp='pack_config = "oca_secure_boot"\n'
        'set = [{ target = "bundle", slot = "primary", path = "manifest_identifier", '
        'value = "OCAHBAD" }]\n'
        f"patch = [{{ offset = {sig}, xor = 0x01 }}]\n"
    )
    out = boot_images.materialize_boot_image("rp", _IMAGES, tmp_path)
    assert out == tmp_path / "rp.patched.bin"
    repacked = (tmp_path / "rp.bin").read_bytes()
    data = out.read_bytes()
    assert [i for i, (a, b) in enumerate(zip(data, repacked)) if a != b] == [sig]
    case = _case(
        image="rp",
        image_asserts=(
            _span(L.PRIMARY_OFFSET, L.PRIMARY_OFFSET + L.BODY_SIZE, differs_from="signed"),
            _span(L.BACKUP_OFFSET + L.BODY_SIZE, None, same_as="signed"),
            _span(0, L.PRIMARY_OFFSET, same_as="unsigned"),
        ),
    )
    boot_images.check_image_asserts(case, out, _IMAGES)


def test_boot_images_load_mutations_from_the_testlist_dir_override(tmp_path, monkeypatch):
    specs_dir = tmp_path / "boot_image_mutations"
    specs_dir.mkdir()
    (specs_dir / "only_here.toml").write_text(
        'base = "signed"\npatch = [{ fill = [0x1000, "end"], value = 0xFF }]\n'
    )
    monkeypatch.setenv("SEPVP_TESTLIST_DIR", str(tmp_path))
    try:
        assert set(importlib.reload(boot_images).MUTATIONS) == {"only_here"}
    finally:
        monkeypatch.undo()
        importlib.reload(boot_images)


def test_missing_prebuilt_names_only_the_images_the_case_reads(tmp_path, specs):
    specs(
        graft=(
            'base = "rom_key3"\n'
            'ops = [{ op = "graft_slot_from", slot = "backup", args = { image = "rom_key4" } }]\n'
        )
    )
    present = tmp_path / "present.bin"
    present.write_bytes(b"\0")
    absent = tmp_path / "absent.bin"
    images = {"rom_key3": present, "rom_key4": absent, "toc_cap": absent, "signed": present}

    case = _case(image="graft", image_asserts=(_span(0, 4, same_as="signed"),))
    assert boot_images.missing_prebuilt(case, images) == ["rom_key4"]
    assert boot_images.missing_prebuilt(_case(image="signed"), images) == []
    assert boot_images.missing_prebuilt(_case(image="toc_cap"), images) == ["toc_cap"]
    smc = _case(smc_sram_image="toc_cap", image_asserts=(_span(0, 4, differs_from="rom_key4"),))
    assert boot_images.missing_prebuilt(smc, images) == ["rom_key4", "toc_cap"]
