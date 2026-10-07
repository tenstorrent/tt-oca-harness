# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP_IN accesses to the documented BEU window answer DECERR at the reset aperture.

The address map places one Bus Error Unit per core at
``0xC801_0000 + core*0x1000``. At the generated resets -- ``LOCAL_BASE``
``0xC000_0000``, ``GLOBAL_BASE`` ``0x4000_0000``, ``REGION_SIZE`` 16 MiB,
none written here -- those addresses lie outside both the local and the global
aperture (``fabric.adoc``, Local and Remote Resource Access), and the input
fabric answers an inbound SEP_IN access outside both apertures with DECERR.

The sequence reads and writes each core's BEU base and the ``PLIC_ENABLE`` word
of core 0 (``0xC801_0018``). Every access must answer DECERR. The writes carry
a word that differs from the reset of every register below, so a write that
reached any of them would show. Afterwards, the ``0xC001_xxxx`` registers that
share those addresses' low bits must still read their generated resets:
``SMC_BASE_CONFIG`` ``GLOBAL_BASE``, ``REGION_SIZE`` and ``CLOCK_GATE_CONTROL``,
alias-remap region 0 ``region_start`` and ``region_attrs``, and M-mode remap
entry 0 ``region_attrs``.
"""

from __future__ import annotations

import cocotb

from .smc_addr_map import CG_HYST_MASK, CG_HYST_SHIFT, CLOCK_GATE_CONTROL_RESET
from .smc_decode_probe_utils import AXI_RESP_DECERR, SmcDecodeProbeSeq
from .smc_rdl_regmap import rdl_contract, rdl_register

BEU_CORE_BASE = 0xC801_0000
BEU_CORE_STRIDE = 0x1000
BEU_CORES = 4
BEU_PLIC_ENABLE_OFFSET = 0x18

BEU_ADDRS = tuple(BEU_CORE_BASE + core * BEU_CORE_STRIDE for core in range(BEU_CORES)) + (
    BEU_CORE_BASE + BEU_PLIC_ENABLE_OFFSET,
)

# CLOCK_GATE_CONTROL's reset with its hysteresis field changed: it differs from
# every reset in UNTOUCHED, and every CG_EN bit stays 0, so it arms no clock gate
# even on a path that should not have taken it.
_CG_HYST_PROBE = 0x2A
WRITE_WORD = (CLOCK_GATE_CONTROL_RESET & ~CG_HYST_MASK) | (
    (_CG_HYST_PROBE << CG_HYST_SHIFT) & CG_HYST_MASK
)

UNTOUCHED = (
    rdl_register("smc_base_config/GLOBAL_BASE"),
    rdl_register("smc_base_config/REGION_SIZE"),
    rdl_register("smc_base_config/CLOCK_GATE_CONTROL"),
    rdl_contract("smc_alias_remap/REGION/region_start"),
    rdl_contract("smc_alias_remap/REGION/region_attrs"),
    rdl_contract("smc_mmode_remap/REGION/region_attrs"),
)
assert all(reg.reset_word & 0xFFFF_FFFF != WRITE_WORD for reg in UNTOUCHED), (
    "the written word must differ from every reset it is checked against"
)


class smc_cluster_beu_test_seq(SmcDecodeProbeSeq):
    """Reads and writes at the BEU addresses answer DECERR and change nothing below."""

    def __init__(self, name: str = "smc_cluster_beu_test_seq") -> None:
        super().__init__(name)
        #: (address, read response, write response) per BEU address
        self.refused: list[tuple[int, int, int]] = []
        #: CLOCK_GATE_CONTROL as read after every BEU access
        self.restored_word: int | None = None

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        self.env.axi_monitor.expected_decerr_addrs.update(BEU_ADDRS)
        for addr in BEU_ADDRS:
            await self.read_decerr(f"BEU_RD_0x{addr:08x}", addr)
            read_resp = AXI_RESP_DECERR
            write_resp = await self.csr_write_expect_error(f"BEU_WR_0x{addr:08x}", addr, WRITE_WORD)
            assert read_resp == AXI_RESP_DECERR and write_resp == AXI_RESP_DECERR, (
                f"0x{addr:08x}: read answered resp={read_resp} and write resp={write_resp}; an "
                f"inbound access outside the local and global apertures must answer DECERR"
            )
            self.refused.append((addr, read_resp, write_resp))

        for reg in UNTOUCHED:
            got = await self.csr_read(
                f"UNTOUCHED_{reg.path}", reg.addr, expected=reg.reset_word, length=reg.width_bytes
            )
            if reg.path.endswith("CLOCK_GATE_CONTROL"):
                self.restored_word = got & 0xFFFF_FFFF

        self.assert_all_reachable(2 * len(BEU_ADDRS) + len(UNTOUCHED), "CLUSTER_BEU")
        cocotb.log.info(
            "CHK-BEU-WINDOW-DECERR: %d documented BEU addresses (%s) each answered DECERR on "
            "a read and on a write of 0x%08x at the REGION_SIZE reset, and %d registers that "
            "share their low address bits (%s) still read their generated resets. This "
            "testcase proves NO BEU property, because no access reaches a BEU.",
            len(self.refused),
            ", ".join(f"0x{addr:08x}" for addr in BEU_ADDRS),
            WRITE_WORD,
            len(UNTOUCHED),
            ", ".join(reg.path for reg in UNTOUCHED),
        )
