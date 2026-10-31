# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Secondary chiplet, SMC publishes the invalid manifest-offset marker: refused before any slot.

The SMC sets ``MANIFEST_READY`` with scratch[8] = 0xFFFFFFFF. The ROM must reject the marker
before it forms an SMC SRAM address, so no manifest slot is attempted and the boot ends.
"""

from __future__ import annotations

import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw.sep_secondary_chiplet_base import (
    DEFAULT_MANIFEST_OFFSET,
    MANIFEST_OK,
    SECONDARY_MARKER,
    SMC_MANIFEST_OFF_INVALID,
    SMC_MANIFEST_OFFSET_INVALID,
    STRAPS_LO_ECHO,
    WAIT_SMC,
    sep_secondary_chiplet_base,
)

_ERR_OFFSET_INVALID = mm.rom_boot_err("OCA_BOOT_ERR_MANIFEST_OFFSET_INVALID")

_OFFSET_INVALID = "MANIFEST_OFFSET_INVALID"
_BOOT_FAIL = f"MANIFEST_BOOT_FAIL=0x{_ERR_OFFSET_INVALID:08x}"
_DOWNSTREAM_TOKENS = (
    "MANIFEST_ERR=",
    "OCA_BODY=",
    "MFST_VER=",
    "PUBK_SEL=",
    "PUBK_AUTHORIZED",
    "RSA_EXEC",
    "SBOOT_OFF",
    "PAYLOAD_LOC_FAIL",
    "PAYLOAD_OK",
    MANIFEST_OK,
)
_BOOT_PROGRESS = ("PRE_JUMP", "BL1_COPIED", "BL1_JUMP=", "FUSE_SECRETS_LOCKED")


@pyuvm.test()
class sep_firmware_secondary_manifest_offset_invalid_test(sep_secondary_chiplet_base):
    """READY with scratch[8] = 0xFFFFFFFF -> OCA_BOOT_ERR_MANIFEST_OFFSET_INVALID, no slot, halt."""

    manifest_offset = SMC_MANIFEST_OFFSET_INVALID
    image_manifest_offset = DEFAULT_MANIFEST_OFFSET
    expect_manifest_attempt = False
    published_offset_in_image = False
    expect_boot = False
    expected_error = _ERR_OFFSET_INVALID
    extra_required = (SMC_MANIFEST_OFF_INVALID, _OFFSET_INVALID, _BOOT_FAIL)
    extra_forbidden = _DOWNSTREAM_TOKENS + _BOOT_PROGRESS

    def check_outcome(self, console, status_seq, fw_done, fw_pass) -> None:
        status_hex = [hex(v) for v in status_seq]
        order = (
            STRAPS_LO_ECHO,
            SECONDARY_MARKER,
            self.published_off_echo,
            SMC_MANIFEST_OFF_INVALID,
            WAIT_SMC,
            _OFFSET_INVALID,
            _BOOT_FAIL,
        )
        indices = [self._index_of(console, marker) for marker in order]
        chain = " -> ".join(f"{m}@{i}" for m, i in zip(order, indices))
        assert min(indices) >= 0 and indices == sorted(set(indices)), (
            f"invalid-offset sequence is out of order: {chain}. Console: {console}"
        )
        for marker in (_OFFSET_INVALID, _BOOT_FAIL):
            assert self._count(console, marker) == 1, (
                f"{marker} appeared {self._count(console, marker)} times, expected once: "
                f"the rejection is terminal. Console: {console}"
            )

        # The ROM's own 0x000301xx codes reach the ring only as the generic load failure.
        status_msg = mm.rom_status_for_result(self.expected_error)
        expected_status = 0x0F01_0000 | status_msg
        assert expected_status in status_seq, (
            f"cold_scratch[1] never held 0x{expected_status:08x}; observed {status_hex}"
        )
        assert fw_done, (
            f"ROM never signalled completion after rejecting the invalid offset marker. "
            f"cold_scratch[1]: {status_hex}"
        )
        assert not fw_pass, "ROM signalled PASS after SMC published the invalid offset marker"
        self.logger.info(
            "CHK-MANIFEST-INVALID-OFFSET PASS: %s; status 0x%08x, no manifest slot "
            "attempted, verdict FAIL",
            chain,
            expected_status,
        )
