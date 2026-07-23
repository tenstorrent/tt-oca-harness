# SPDX-License-Identifier: Apache-2.0
"""Input/output fabric CSR precheck over real SEP_IN AXI."""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

# RDL-traceable reset constants (G3 spec-anchored; identical on Verilator/VCS):
# alias_remap.rdl -> ALIAS start/end/attrs = 0; filter_ctrl.rdl -> FILTER_CONFIG
# = 0x3000 (data_bus_width[14:12]=0x3), START_ADDR = 0, END_ADDR = 0x7 ("Defaults
# to 7 on reset"). Each read verifies remap/filter CSR decode AND the spec reset
# content, not merely an OKAY response.
FILTER_REMAP_REGS = [
    ("ALIAS0_START", 0xC001_2000, 0x0),
    ("ALIAS0_END", 0xC001_2008, 0x0),
    ("ALIAS0_ATTRS", 0xC001_2010, 0x0),
    ("INBOUND0_FILTER_CONFIG", 0xC001_5000, 0x0000_3000),
    ("INBOUND0_START", 0xC001_5008, 0x0),
    ("INBOUND0_END", 0xC001_5010, 0x7),
    ("OUTBOUND0_FILTER_CONFIG", 0xC001_6000, 0x0000_3000),
    ("OUTBOUND0_START", 0xC001_6008, 0x0),
    ("OUTBOUND0_END", 0xC001_6010, 0x7),
]


class smc_input_output_fabric_wr_rd_test_seq(SmcCsrSeq):
    """Prove fabric remap/filter CSR decode until a responder is available."""

    def __init__(self, name: str = "smc_input_output_fabric_wr_rd_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        await self.csr_read_many(FILTER_REMAP_REGS)
        assert self.accesses == len(FILTER_REMAP_REGS), "fabric CSR precheck mismatch"
