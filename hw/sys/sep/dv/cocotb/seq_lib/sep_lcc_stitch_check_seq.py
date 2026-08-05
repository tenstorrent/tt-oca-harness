# SPDX-License-Identifier: Apache-2.0
"""LCC lc_state-stitch checker sequence for the SEP OSS flow.

After an eFuse image carrying a specific lifecycle state has been sensed, this
reads back -- over the CPU-LSU AXI bus -- (1) the software-visible LC_STATE
shadow register and (2) the lifecycle controller's FEAT_CTRL register, and
checks each against the golden reference:

  * LC_STATE shadow  == the differential-encoded ``{~raw, raw}`` for the state
    that was sensed (proves the sensed lc_state reached the software map).
  * FEAT_CTRL (64-bit, read as two 32-bit halves) == ``feat_ctrl_expected(...)``
    from the LCC golden model (proves eFuse lc_state -> LCC decode -> feature
    control, interconnect edge E4/E11).

Both checks are exact-value (caught by the scoreboard's value-check / uvm_error),
so each fails on a broken decode rather than merely "no X".
"""

from __future__ import annotations

import cocotb
from pyuvm import uvm_sequence

from env.sep_axi_agent import SepAxiItem, SepAxiOp
from env.sep_efuse_image import SepEfuseImage, SHADOW_BASE
from env.sep_lcc_golden import LCC_FEAT_CTRL, feat_ctrl_expected, lc_state_name

# SEP local fabric addresses (sep_local_axi_xbar / sep_addr.h). The LCC
# register map lives in env.sep_lcc_golden (single source of truth).
LC_STATE_SHADOW = SHADOW_BASE + 0x8     # 0x1093_0008, eFuse shadow word 2


class sep_lcc_stitch_check_seq(uvm_sequence):
    def __init__(
        self,
        image: SepEfuseImage,
        *,
        secure_tm: int = 0,
        sec_dis: int = 0,
        name: str = "sep_lcc_stitch_check_seq",
    ) -> None:
        super().__init__(name)
        self.image = image
        self.secure_tm = secure_tm
        self.sec_dis = sec_dis
        # Computed in body() and exposed for the test's transition checks/logging.
        self.observed_lc_raw: int | None = None

    async def _read_expect(self, addr: int, expected: int, label: str) -> int:
        item = SepAxiItem(f"rd_{label}_0x{addr:08x}")
        item.op = SepAxiOp.READ
        item.addr = addr
        item.length = 4
        item.expected = expected
        await self.start_item(item)
        await self.finish_item(item)
        return item.rdata

    async def body(self) -> None:
        lc_raw = self.image.lc_raw()
        self.observed_lc_raw = lc_raw
        sip_dis = self.image.field_int("SIP_DIS")
        sys_dis = self.image.field_int("SYS_DIS")
        feat = feat_ctrl_expected(
            lc_raw, sip_dis, sys_dis,
            secure_tm=self.secure_tm, sec_dis=self.sec_dis,
        )

        # (1) sensed lc_state reached the software-visible shadow map.
        await self._read_expect(
            LC_STATE_SHADOW, self.image.shadow_word(2), "lc_state_shadow"
        )

        # (2) LCC decoded that lc_state into the expected feature-control vector.
        await self._read_expect(LCC_FEAT_CTRL, feat & 0xFFFF_FFFF, "feat_ctrl_lo")
        await self._read_expect(
            LCC_FEAT_CTRL + 4, (feat >> 32) & 0xFFFF_FFFF, "feat_ctrl_hi"
        )

        cocotb.log.info(
            "[lcc] state %s (0x%x): SIP_DIS=0x%016x SYS_DIS=0x%016x -> FEAT_CTRL=0x%016x",
            lc_state_name(lc_raw), lc_raw, sip_dis, sys_dis, feat,
        )
