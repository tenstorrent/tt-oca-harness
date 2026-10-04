# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A 64 KiB payload staged in the SMC SRAM window is accepted and boots.

With ``flag_args`` bit 29 clear the ROM stages in the window SMC publishes in
scratch[13]/[14]; both that window and the SEP SRAM bound must pass.
"""

from __future__ import annotations

import pyuvm
from rom_fw import sep_payload_size_base as psb

_PAYLOAD_BYTES = 64 * 1024
_REQUIRED, _FORBIDDEN = psb.accepted_markers(_PAYLOAD_BYTES, smc=True)


@pyuvm.test()
class sep_firmware_payload_correct_smc_64kb_test(psb.PayloadSizeAcceptedTest):
    """64 KiB payload, SMC SRAM staging, accepted."""

    payload_bytes = _PAYLOAD_BYTES
    stage_in_smc = True
    required_markers = psb.PayloadSizeAcceptedTest.required_markers + _REQUIRED
    forbidden_markers = psb.PayloadSizeAcceptedTest.forbidden_markers + _FORBIDDEN
