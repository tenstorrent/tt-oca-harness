# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD_END + BL1 demotion flag set -> the flag is IGNORED, both registers locked.

The manifest requests BL1 demotion and permits PROD_END only. Needs
``+sep_crypto_edn_force``: PROD_END enforces secure boot, so RSA-3072 runs on OTBN.
"""

from __future__ import annotations

import pyuvm

from env import sep_manifest_mutate as mm
from rom_fw.sep_demotion_decision_base import (
    EFUSE_DIR,
    narrow_life_cycle_states,
    sep_demotion_decision_base,
)
from rom_fw.sep_rom_ot_dma_boot_test import sep_rom_ot_dma_boot_test

_LC_PROD_END = "LC=PROD_END"
_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"

_LC_RAW_PROD_END = 0x8
_LC_STATES_PROD_END_ONLY = 1 << mm.LC_STATES_BIT_PROD_END


@pyuvm.test()
class sep_firmware_demotion_decision_auth_flag_0_prod_end_test(
        sep_demotion_decision_base):
    """PROD_END overrides a set BL1 demotion flag: no demotion, both registers locked."""

    efuse_preload = EFUSE_DIR / "sep_efuse_lc_prod_end.toml"
    expected_lc_raw = _LC_RAW_PROD_END
    expected_sboot_dis = 0

    expect_demote_1 = (0, 1)
    expect_demote_2 = (0, 1)

    demotion_required = ("DEMOTE: PROD_END lock", "DEMOTE_LOCKED")
    demotion_values = ()

    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _LC_PROD_END, _PRIMARY_SRC, "RSA_VERIFY_START", "SIG_VALID",
        "CRYPTO_VALIDATE_OK", "BL1_COPIED", "BL1_JUMP=",
    )
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        "LC_USAGE_CONSTRAINT_FAIL", "SBOOT_OFF", "FUSE: SBOOT_DIS: 1", _BACKUP_SRC,
        "MANIFEST_ERR=", "MANIFEST_ALL_FAILED", "CRYPTO_FAIL=", "RSA_VERIFY_FAIL",
        "VERSION_ROLLBACK", "KEY_REVOKED", "BAD_SIG_TYPE=", "BAD_KEY_SEL",
        "BAD_KEY_IDX", "ROM_KEY_EMPTY", "FUSE_KEY_EMPTY", "PUBK_HASH_MISMATCH",
    )

    def mutate_manifest(self, buf: bytearray) -> None:
        mm.set_usage_flags_bit(buf, "primary",
                               mm.USAGE_CONSTRAINTS_FLAGS_BIT_BL1_DEMOTION, True)
        # Last in-TBS write: it re-seals both slots, which covers the flag write above.
        narrow_life_cycle_states(self, buf, _LC_STATES_PROD_END_ONLY,
                                 reseal_slots=("primary", "backup"))

    def check_manifest_stimulus(self, buf: bytearray) -> None:
        flags = mm.usage_flags(buf, "primary")
        bit = (flags >> mm.USAGE_CONSTRAINTS_FLAGS_BIT_BL1_DEMOTION) & 1
        assert bit == 1, (
            f"primary usage_constraints.flags is 0x{flags:08x} with the BL1 demotion "
            f"bit clear. This testcase's entire content is 'the manifest REQUESTS "
            f"demotion and PROD_END refuses it', and the ROM never echoes this field "
            f"on the PROD_END path (rom_main.c:383 returns before :395), so a "
            f"stimulus that failed to land would produce exactly the log a correct "
            f"run produces"
        )
        sel = mm.selector_bits(buf, "primary")
        sel_bit = (sel >> mm.SELECTOR_BIT_BL1_DEMOTION) & 1
        bl2 = (mm.get_flag_args(buf, "primary") >> mm.FLAG_ARGS_BIT_BL2_DEMOTION) & 1
        assert sel_bit == 0 and bl2 == 0, (
            f"primary selector_bits[{mm.SELECTOR_BIT_BL1_DEMOTION}]={sel_bit} and "
            f"flag_args[{mm.FLAG_ARGS_BIT_BL2_DEMOTION}]={bl2}; both must be 0 so "
            f"this run drives the AUTH flag alone, as the tracker row names it"
        )
        lcs = mm.life_cycle_states(buf, "primary")
        assert lcs == _LC_STATES_PROD_END_ONLY, (
            f"primary life_cycle_states is 0x{lcs:08x}, expected "
            f"0x{_LC_STATES_PROD_END_ONLY:08x} (PROD_END only)"
        )
        self.logger.info(
            "CHK-STIMULUS-DEMOTION: primary usage_constraints.flags bit %d = 1 "
            "(BL1 demotion REQUESTED), selector_bits[%d] = 0, flag_args[%d] = 0, "
            "life_cycle_states = 0x%08x. The ROM must ignore all three because the "
            "part is at PROD_END",
            mm.USAGE_CONSTRAINTS_FLAGS_BIT_BL1_DEMOTION, mm.SELECTOR_BIT_BL1_DEMOTION,
            mm.FLAG_ARGS_BIT_BL2_DEMOTION, lcs,
        )
