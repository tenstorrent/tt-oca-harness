# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CTM routing model from the cross-trigger matrix register contract.

The SV-UVM twin is ``uvm/env/dtp_xtrig_ctm_model.svh``.
"""

from __future__ import annotations

from .dtp_xtrig_types import XTRIG_CTM_SELECT_MASK, XTRIG_NUM_CTM_PORTS, check_ctm_port

__all__ = ["DtpXtrigCtmModel"]


class DtpXtrigCtmModel:
    """CTM routing model from the register contract.

    ``CT_SRC[k].CONFIG_0.CT_DST_SELECT`` (cross_trigger_matrix.rdl) holds one
    bit per CT_Dst input port; the pulses of the selected inputs are OR'd onto
    CT_Src output ``k``. ``route`` returns the output vector a set of input
    pulses reaches.
    """

    def __init__(self) -> None:
        self.select = [0 for _ in range(XTRIG_NUM_CTM_PORTS)]

    def program(self, output_port: int, input_mask: int) -> None:
        check_ctm_port(output_port, "CTM output port")
        self.select[output_port] = input_mask & XTRIG_CTM_SELECT_MASK

    def route(self, input_pulses: int) -> int:
        input_pulses &= XTRIG_CTM_SELECT_MASK
        routed = 0
        for output_port, input_mask in enumerate(self.select):
            if input_pulses & input_mask:
                routed |= 1 << output_port
        return routed & XTRIG_CTM_SELECT_MASK
