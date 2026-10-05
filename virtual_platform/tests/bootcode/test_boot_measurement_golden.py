# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import importlib.util

import boot_measurement_golden as g
import dv_env
import oca_layout as L
import pytest
from sepvp import paths

pytestmark = pytest.mark.hostonly

_DV = paths.OCAH_ROOT / "hw/sys/sep/dv/cocotb/tests/rom_fw/sep_measurement_golden.py"


def _dv():
    spec = importlib.util.spec_from_file_location("dv_measurement_golden", _DV)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_matches_the_dv_known_answer():
    dv = _dv()
    assert g.boot_pcr(dv._KAT_MANIFEST_HASH, **dv._KAT_INPUTS) == dv._KAT_PCR


@pytest.mark.parametrize(
    "field, flip", [("lc_state", 1), ("demotion_decision", 4), ("secure_boot", 1), ("sboot_dis", 1)]
)
def test_every_record_field_reaches_the_digest(field, flip):
    dv = _dv()
    inputs = dict(dv._KAT_INPUTS, **{field: dv._KAT_INPUTS[field] ^ flip})
    assert g.boot_pcr(dv._KAT_MANIFEST_HASH, **inputs) != dv._KAT_PCR


def test_token_format():
    assert g.pcr_token(bytes(range(32))) == "BL0S_BOOT_PCR=" + bytes(range(32)).hex().upper()


@pytest.mark.parametrize("slot, base", [("primary", L.PRIMARY_OFFSET), ("backup", L.BACKUP_OFFSET)])
def test_manifest_hash_reads_the_slot_digest(slot, base):
    image = bytearray(L.BACKUP_OFFSET + L.BODY_SIZE)
    image[base : base + 4] = L.OCAC_MAGIC
    digest = bytes(range(1, 33))
    image[base + L.C.OFF_MANIFEST_HASH : base + L.C.OFF_MANIFEST_HASH + 32] = digest
    assert g.manifest_hash(bytes(image), slot) == digest


def test_manifest_hash_refuses_a_slot_that_is_not_oca_classic():
    image = bytes(L.BACKUP_OFFSET + L.BODY_SIZE)
    with pytest.raises(ValueError, match="OCAC"):
        g.manifest_hash(image, "primary")


@pytest.mark.parametrize(
    "inputs",
    [
        {"lc_state": 0x10, "demotion_decision": 0, "secure_boot": 0, "sboot_dis": 0},
        {"lc_state": 0, "demotion_decision": 8, "secure_boot": 0, "sboot_dis": 0},
        {"lc_state": 0, "demotion_decision": 0, "secure_boot": 2, "sboot_dis": 0},
        {"lc_state": 0, "demotion_decision": 0, "secure_boot": 0, "sboot_dis": 2},
    ],
)
def test_out_of_range_record_fields_are_refused(inputs):
    with pytest.raises(ValueError):
        g.boot_pcr(bytes(32), **inputs)


@pytest.mark.parametrize("slot", ["primary", "backup"])
def test_manifest_hash_is_the_field_the_dv_helper_reads_on_the_secure_boot_image(slot):
    signed = paths.OCA_IMAGE_PATHS["signed"]
    if not signed.is_file():
        pytest.skip("oca-images not built")
    dv = _dv()
    mm = dv_env.load("sep_manifest_mutate")
    image = signed.read_bytes()
    digest = g.manifest_hash(image, slot)
    # Only the real manifest_hash field holds the SHA-256 of the signed region.
    assert digest == mm.manifest_hash(image, slot) == mm.signed_region_hash(image, slot)
    assert g.boot_pcr(digest, **dv._KAT_INPUTS) == dv.calculate_boot_pcr(digest, **dv._KAT_INPUTS)
