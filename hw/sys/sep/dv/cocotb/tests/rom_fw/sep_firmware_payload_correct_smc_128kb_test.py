# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A 128 KiB payload staged in the SMC SRAM window is accepted and boots.

The middle SMC size: half of SEP's whole SRAM, staged somewhere else entirely.
A ROM that ignored bit 29 would still fit 128 KiB in its own SRAM -- the EXT
capacity at the shipped ``payload_offset`` is 252 KiB -- so nothing about the size
would betray the wrong destination. What catches it is the destination itself:
``USING_SEP_SRAM`` is forbidden and ``PAYLOAD_DST=`` is required at the SMC
address.

``payload_offset + payload_length`` is 0x21000 against the 256 KiB SEP SRAM, so
``validate_manifest_header``'s bound -- which runs before the destination is
chosen and therefore applies to SMC-staged payloads too -- still passes with room
to spare. The window the testlist publishes is 256 KiB, wider than any payload
this group can declare, so its capacity check is out of reach here on purpose --
see the scope limit in ``sep_payload_size_base``.

No failover: the slot is re-signed and otherwise untouched.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_payload_size_base as psb

_PAYLOAD_BYTES = 128 * 1024
_REQUIRED, _FORBIDDEN = psb.accepted_markers(_PAYLOAD_BYTES, smc=True)


@pyuvm.test()
class sep_firmware_payload_correct_smc_128kb_test(psb.PayloadSizeAcceptedTest):
    """128 KiB payload, SMC SRAM staging, accepted."""

    payload_bytes = _PAYLOAD_BYTES
    stage_in_smc = True
    required_markers = psb.PayloadSizeAcceptedTest.required_markers + _REQUIRED
    forbidden_markers = psb.PayloadSizeAcceptedTest.forbidden_markers + _FORBIDDEN
