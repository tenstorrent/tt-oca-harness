# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A 200 KiB payload staged in the SMC SRAM window is accepted and boots.

This is the largest accepted size, 52 KiB under the SEP SRAM bound that
``validate_manifest_header`` also applies to SMC-staged payloads.
"""

from __future__ import annotations

import pyuvm
from rom_fw import sep_payload_size_base as psb

_PAYLOAD_BYTES = 200 * 1024
_REQUIRED, _FORBIDDEN = psb.accepted_markers(_PAYLOAD_BYTES, smc=True)


@pyuvm.test()
class sep_firmware_payload_correct_smc_200kb_test(psb.PayloadSizeAcceptedTest):
    """200 KiB payload, SMC SRAM staging, accepted."""

    payload_bytes = _PAYLOAD_BYTES
    stage_in_smc = True
    required_markers = psb.PayloadSizeAcceptedTest.required_markers + _REQUIRED
    forbidden_markers = psb.PayloadSizeAcceptedTest.forbidden_markers + _FORBIDDEN
