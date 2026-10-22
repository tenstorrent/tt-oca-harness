# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Scratchpad access over SEP_IN while CPU cores are held in reset.

SEP_IN reaches the scratchpad through the cluster's front port and its broadcast
coherence hub, which probes every core's L1 before it completes an access. A core
held in reset cannot answer that probe itself, so the cluster has to answer it on
the core's behalf, or the access never completes.

Each core is held in reset alone through its `RESET_CTRL.coreN_reset_n_n0_scan`
field, then all four together, with `RESET_TIMEOUT` in force mode so the hold is
applied whether or not the cluster drains. Each hold is confirmed on the
cluster's core reset pins before a 64-bit pattern is written to its own
scratchpad word and read back. The scratch RAM write counter has to advance, so
the write is known to have reached the RAM and not a different responder.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import SPM_MEMORY_BASE, cpu_ctrl_u32, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

RESET_CTRL = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_CTRL_BASE_ADDR")
RESET_TIMEOUT = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_TIMEOUT_BASE_ADDR")
CORE_N = tuple(
    cpu_ctrl_u32(f"CPU_CTRL__RESET_CTRL__CORE{core}_RESET_N_N0_SCAN_bm") for core in range(4)
)
VALUE_BP = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__TIMEOUT_VALUE_bp")
MODE_BM = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__TIMEOUT_MODE_bm")
FORCE_AFTER_32 = (32 << VALUE_BP) | MODE_BM

ALL_CORES = 0b1111
# Each hold touches its own word, so a read cannot pass on a value an earlier hold left.
HOLDS = tuple((f"core{core}", 1 << core) for core in range(4)) + (("all_cores", ALL_CORES),)
_WORD = 8
WORD_STRIDE = 0x1000
PATTERN_BASE = 0x5C4A_7C00_0000_0000

_PIN_BOUND = 256


class smc_spm_access_core_reset_test_seq(SmcCsrSeq):
    """Write and read the scratchpad over SEP_IN with each core, then every core, in reset."""

    def __init__(self, name: str = "smc_spm_access_core_reset_test_seq") -> None:
        super().__init__(name)
        self.completed: list[str] = []

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

    async def _access(self, tag: str, index: int) -> tuple[int, int, int]:
        addr = SPM_MEMORY_BASE + index * WORD_STRIDE
        pattern = PATTERN_BASE | (index << 16) | addr & 0xFFFF
        writes_before = int(cocotb.top.tb_cpu_scratch_write_count.value)
        await self.csr_write(f"{tag}_SPM_WR", addr, pattern, length=_WORD)
        writes = int(cocotb.top.tb_cpu_scratch_write_count.value) - writes_before
        assert writes > 0, (
            f"{tag}: the SEP_IN write to 0x{addr:08x} completed, but the scratch RAM write "
            "counter did not advance"
        )
        await self.csr_read(f"{tag}_SPM_RD", addr, expected=pattern, length=_WORD)
        return addr, pattern, writes

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        ctrl = await self.csr_read("RESET_CTRL_IDLE", RESET_CTRL, length=8)
        timeout = await self.csr_read("RESET_TIMEOUT_IDLE", RESET_TIMEOUT, length=8)
        all_core_n = CORE_N[0] | CORE_N[1] | CORE_N[2] | CORE_N[3]
        assert ctrl & all_core_n == all_core_n, (
            f"RESET_CTRL 0x{ctrl:x}: every core is expected released at idle"
        )
        await self._await_core_resets_n(ALL_CORES, "at idle")

        addr, pattern, writes = await self._access("RELEASED", 0)
        cocotb.log.info(
            "CHK-SPM-ACCESS-CORES-RELEASED: with every core released, scratchpad 0x%08x "
            "took 0x%016x (%d scratch RAM writes) and read it back",
            addr,
            pattern,
            writes,
        )

        await self.csr_write("TIMEOUT_FORCE", RESET_TIMEOUT, FORCE_AFTER_32, length=8)
        for index, (name, held) in enumerate(HOLDS, start=1):
            tag = name.upper()
            held_n = sum(CORE_N[core] for core in range(4) if held >> core & 1)
            await self.csr_write(f"{tag}_HOLD", RESET_CTRL, ctrl & ~held_n, length=8)
            await self._await_core_resets_n(ALL_CORES & ~held, f"after holding {name}")
            addr, pattern, writes = await self._access(tag, index)
            cocotb.log.info(
                "CHK-SPM-ACCESS-CORE-RESET-%s: with core reset pins 0b%s, scratchpad "
                "0x%08x took 0x%016x (%d scratch RAM writes) and read it back",
                tag,
                f"{self._core_resets_n():04b}",
                addr,
                pattern,
                writes,
            )
            await self.csr_write(f"{tag}_RELEASE", RESET_CTRL, ctrl, length=8)
            await self._await_core_resets_n(ALL_CORES, f"after releasing {name}")
            self.completed.append(name)

        await self.csr_write("RESET_TIMEOUT_RESTORE", RESET_TIMEOUT, timeout, length=8)
        await self.csr_read("RESET_TIMEOUT_RESTORE_RB", RESET_TIMEOUT, length=8, expected=timeout)
        await self.csr_read("RESET_CTRL_RESTORE_RB", RESET_CTRL, length=8, expected=ctrl)
