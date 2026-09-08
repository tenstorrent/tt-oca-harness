# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shadow-register readout checker for the SEP eFuse OSS flow.

After fuse-sense, reads the software-visible shadow-register block field-by-field
over AXI and checks each word against the golden ``SepEfuseImage`` (which applies
the LC_STATE differential-encode and reads every other readable field verbatim).
A mismatch is caught by the scoreboard value-check (uvm_error). Fails when a
shadow word does not match the golden field placement.
"""

from __future__ import annotations

from typing import List, Optional

from env.sep_axi_agent import SepAxiItem, SepAxiOp
from env.sep_efuse_image import SEP_FUSE_SENSE_STATUS, SepEfuseImage
from pyuvm import uvm_sequence


class sep_efuse_shadow_check_seq(uvm_sequence):
    def __init__(
        self,
        image: SepEfuseImage,
        name: str = "sep_efuse_shadow_check_seq",
        *,
        fields: Optional[List[str]] = None,
        check_sense_status: bool = True,
    ) -> None:
        super().__init__(name)
        self.image = image
        self.field_names = fields if fields is not None else image.check_fields()
        self.check_sense_status = check_sense_status

    async def _read_expect(self, addr: int, expected: int, label: str) -> None:
        item = SepAxiItem(f"rd_{label}_0x{addr:08x}")
        item.op = SepAxiOp.READ
        item.addr = addr
        item.length = 4
        item.expected = expected
        await self.start_item(item)
        await self.finish_item(item)

    async def body(self) -> None:
        if self.check_sense_status:
            await self._read_expect(SEP_FUSE_SENSE_STATUS, 1, "fuse_sense_status")
        for name in self.field_names:
            for addr, expected in self.image.expected_field(name):
                await self._read_expect(addr, expected, name.lower())
