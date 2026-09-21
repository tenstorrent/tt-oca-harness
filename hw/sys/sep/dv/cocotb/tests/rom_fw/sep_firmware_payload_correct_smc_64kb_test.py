# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A 64 KiB payload staged in the SMC SRAM window is accepted and boots.

The smallest of the three SMC sizes. ``flag_args`` bit 29 is cleared, so the ROM
waits for SRAM_INIT, reads the window SMC published in scratch[13]/[14], and
stages there instead of in its own SRAM (``manifest_load.c``). The size decision
moves with it: the capacity the payload is measured against is now the window
length, not ``SRAM_BASE + SRAM_SIZE - payload_dest``.

BOTH bounds still apply, and this member is where that stops being obvious.
``validate_manifest_header`` runs before the destination is chosen, so
``payload_offset + payload_length`` is checked against SEP SRAM even for a
payload that will never be staged there -- 0x1000 + 0x10000 passes. The window
check then passes on its own terms. A member that only satisfied one of the two
would be refused by the other, so the accepted verdict here is evidence about
both.

``SMC_WIN_OFF=``/``SMC_WIN_LEN=`` are required so the window the ROM acted on is
the one the testlist published; without them a window that failed to reach the DUT
would leave the ROM using whatever ``u_smc_mem`` happened to hold. The window is
wider than any payload this group can declare, so its own capacity check is out of
reach here on purpose -- see the scope limit in ``sep_payload_size_base``.

No failover: the slot is re-signed and bit 29 sits outside the signed TBS, so it
is still a genuinely signed image asking for SMC staging.
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
