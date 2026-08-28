# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shadow-word AXI driver for sep_locked_field_access_irq_path_test.

Config lives in ``env/sep_locked_field_irq.py`` so the pre-sim staging hook
can import it without cocotb.
"""

from __future__ import annotations

from env.sep_axi_agent import SepAxiOp
from env.sep_efuse_image import SepEfuseImage
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver


class SepLockedFieldIrq(SepAxiRegDriver):
    """32-bit shadow-word access that returns the live AXI sequence."""

    _DRIVER_TAG = "LOCKIRQ"

    def _addr(self, name: str) -> int:
        return SepEfuseImage.field(name).shadow_addr

    async def access(
        self,
        name: str,
        *,
        write: bool = False,
        wdata: int = 0,
    ) -> SepAxiAccessSeq:
        seq = SepAxiAccessSeq(
            f"lockirq_{'wr' if write else 'rd'}_{name}",
            op=SepAxiOp.WRITE if write else SepAxiOp.READ,
            addr=self._addr(name),
            wdata=wdata,
            size=2,
        )
        await self.test.start_seq(seq)
        return seq
