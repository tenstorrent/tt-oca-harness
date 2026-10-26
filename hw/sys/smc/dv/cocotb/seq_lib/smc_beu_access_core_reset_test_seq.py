# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Bus error unit access over SEP_IN while its core is held in reset.

Each core's BEU sits in that core's tile, so it is in the core's reset domain. The
cluster denies an access to a tile held in reset instead of letting it wait for a
tile that cannot answer, and the cluster's AXI front port returns a denied access
as SLVERR.

`REGION_SIZE` is widened to 256 MiB so SEP_IN reaches the BEU window. Each core
is held in reset alone through `RESET_CTRL.coreN_reset_n_n0_scan`, and the hold
is confirmed on the cluster's core reset pins. A read and a write of that core's
BEU `ENABLE` must each complete with SLVERR, and the next core's BEU `ENABLE`
must still read its reset value with OKAY. Once the core is released, its BEU
`ENABLE` must read its reset value with OKAY again.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import REGION_SIZE_RESET, cpu_ctrl_u32, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

RESET_CTRL = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_CTRL_BASE_ADDR")
REGION_SIZE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
REGION_SIZE_256M = 0x1000_0000
CORE_N = tuple(
    cpu_ctrl_u32(f"CPU_CTRL__RESET_CTRL__CORE{core}_RESET_N_N0_SCAN_bm") for core in range(4)
)
CORE_COUNT = 4
ALL_CORES = 0b1111
ENABLE_RESET = 0xE6
OKAY = 0
SLVERR = 2
_WORD = 8
_PIN_BOUND = 256


def beu_enable(core: int) -> int:
    return smc_addr(f"SMC_TOP_SMC_CLUSTER_CORE{core}_BEU_ENABLE_BASE_ADDR")


class smc_beu_access_core_reset_test_seq(SmcCsrSeq):
    """Access each core's BEU over SEP_IN with that core held in reset."""

    def __init__(self, name: str = "smc_beu_access_core_reset_test_seq") -> None:
        super().__init__(name)
        self.completed: list[int] = []

    @staticmethod
    def _core_resets_n() -> int:
        value = cocotb.top.tb_cpu_core_resets_n.value
        assert value.is_resolvable, f"tb_cpu_core_resets_n is not resolvable: {value}"
        return int(value)

    async def _await_core_resets_n(self, want: int, when: str) -> None:
        for _ in range(_PIN_BOUND):
            if self._core_resets_n() == want:
                return
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(
            f"tb_cpu_core_resets_n read 0b{self._core_resets_n():04b}, not 0b{want:04b}, "
            f"within {_PIN_BOUND} cycles {when}"
        )

    async def _access(self, name: str, op: SmcSysAxiOp, addr: int, resp: int) -> int:
        item = SmcSysAxiItem(f"{'rd' if op == SmcSysAxiOp.READ else 'wr'}_{name}")
        item.op = op
        item.addr = addr
        item.length = _WORD
        if resp != OKAY:
            item.allow_error = True
            item.expect_error = True
            item.expected_resp = resp
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code == resp, (
            f"{name} @ 0x{addr:08x}: expected resp={resp}, got resp={item.resp_code} "
            f"(rdata=0x{item.rdata:x})"
        )
        return item.rdata

    async def _read_enable(self, name: str, core: int) -> None:
        got = await self._access(name, SmcSysAxiOp.READ, beu_enable(core), OKAY)
        assert got == ENABLE_RESET, (
            f"{name}: BEU {core} ENABLE read 0x{got:x}, expected 0x{ENABLE_RESET:x}"
        )

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        ctrl = await self.csr_read("RESET_CTRL_IDLE", RESET_CTRL, length=8)
        all_core_n = CORE_N[0] | CORE_N[1] | CORE_N[2] | CORE_N[3]
        assert ctrl & all_core_n == all_core_n, (
            f"RESET_CTRL 0x{ctrl:x}: every core is expected released at idle"
        )
        await self._await_core_resets_n(ALL_CORES, "at idle")

        await self.csr_write("REGION_SIZE_256M", REGION_SIZE, REGION_SIZE_256M)
        await self.csr_read("REGION_SIZE_256M_RB", REGION_SIZE, expected=REGION_SIZE_256M)

        for core in range(CORE_COUNT):
            await self._read_enable(f"BEU{core}_RELEASED", core)
        cocotb.log.info(
            "CHK-BEU-ACCESS-CORES-RELEASED: with every core released, BEU 0..%d ENABLE read "
            "0x%x with OKAY",
            CORE_COUNT - 1,
            ENABLE_RESET,
        )

        for core in range(CORE_COUNT):
            other = (core + 1) % CORE_COUNT
            tag = f"CORE{core}"
            await self.csr_write(f"{tag}_HOLD", RESET_CTRL, ctrl & ~CORE_N[core], length=8)
            await self._await_core_resets_n(ALL_CORES & ~(1 << core), f"after holding core {core}")
            await self._access(f"{tag}_BEU_RD", SmcSysAxiOp.READ, beu_enable(core), SLVERR)
            await self._access(f"{tag}_BEU_WR", SmcSysAxiOp.WRITE, beu_enable(core), SLVERR)
            await self._read_enable(f"{tag}_OTHER_BEU{other}", other)
            cocotb.log.info(
                "CHK-BEU-ACCESS-CORE-RESET-%s: with core reset pins 0b%s, a read and a write of "
                "BEU %d ENABLE each completed with SLVERR, and BEU %d ENABLE read 0x%x with OKAY",
                tag,
                f"{self._core_resets_n():04b}",
                core,
                other,
                ENABLE_RESET,
            )
            await self.csr_write(f"{tag}_RELEASE", RESET_CTRL, ctrl, length=8)
            await self._await_core_resets_n(ALL_CORES, f"after releasing core {core}")
            await self._read_enable(f"{tag}_BEU_AFTER", core)
            cocotb.log.info(
                "CHK-BEU-ACCESS-CORE-RELEASED-%s: after core %d was released, BEU %d ENABLE "
                "read 0x%x with OKAY",
                tag,
                core,
                core,
                ENABLE_RESET,
            )
            self.completed.append(core)

        await self.csr_write("REGION_SIZE_RESTORE", REGION_SIZE, REGION_SIZE_RESET)
        await self.csr_read("REGION_SIZE_RESTORE_RB", REGION_SIZE, expected=REGION_SIZE_RESET)
        await self.csr_read("RESET_CTRL_RESTORE_RB", RESET_CTRL, length=8, expected=ctrl)
