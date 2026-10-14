# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smc_cpu_ctrl_wb_pc_test: CPU_CTRL WB_PC read decode and idle values.

Sources: hw/sys/smc/regs/blocks/cpu_ctrl/cpu_ctrl.rdl, hw/sys/smc/doc/cpu.adoc.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

CORES = 4
ENTRIES = 8
WORD_BYTES = 8
OKAY = 0
FUSE_SENSE_MAX_CYCLES = 200_000
STEP_ORDER = ("S1", "S2", "S3")
FENCE_TERMS = {"S1": "BRINGUP_DONE", "S2": "WB_PC_DECODED", "S3": "IDLE_VALUES_MEASURED"}
CHK_STEP = {"CHK-WBPC-DECODE": "S2", "CHK-WBPC-IDLE": "S3"}


def _wb_pc_addr(core: int, entry: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_CPU_CTRL_WB_PC_CORE{core}_BASE_ADDR", entry)


class smc_cpu_ctrl_wb_pc_test_seq(SmcCsrSeq):
    """Read every WB_PC word over SEP_IN and print the idle values beside the probes."""

    def __init__(self, name: str = "smc_cpu_ctrl_wb_pc_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: set[str] = set()
        self._stamps: list[tuple[str, int]] = []
        self._chk_order: list[tuple[str, int]] = []
        self._waits: list[tuple[str, str, str]] = []
        self._last_access = "none"

    def _stamp(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_order.append((chk_id, len(self._stamps)))
        self.chk_seen.add(chk_id)

    def _probe(self, core: int) -> int:
        sig = getattr(cocotb.top, f"tb_cpu_wb_pc{core}")
        assert sig.value.is_resolvable, f"tb_cpu_wb_pc{core} is X/Z: {sig.value}"
        return int(sig.value)

    async def _read(self, core: int, entry: int) -> tuple[int, int, int]:
        """One bounded 64-bit read: (address, data, response code)."""
        addr = _wb_pc_addr(core, entry)
        item = SmcSysAxiItem(f"rd_WB_PC_CORE{core}_{entry}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = WORD_BYTES
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self._last_access = (
            f"WB_PC_CORE{core}[{entry}]@0x{addr:08x} resp={item.resp_code} rdata=0x{item.rdata:x}"
        )
        assert item.resp_code == OKAY, f"WB_PC read not OKAY: {self._last_access}"
        return addr, item.rdata, item.resp_code

    async def body(self) -> None:
        dut = cocotb.top
        for core in range(CORES):
            assert hasattr(dut, f"tb_cpu_wb_pc{core}"), f"tb_cpu_wb_pc{core} not exported"
        axi_bound = self.cfg.axi_timeout_ns

        # S1
        await self.wait_fuse_sense_done(FUSE_SENSE_MAX_CYCLES)
        sense = int(dut.tb_fuse_sense_done.value)
        assert sense == 1, "tb_fuse_sense_done low after the wait returned"
        self._waits.append(
            (
                "fuse_sense_done",
                f"{FUSE_SENSE_MAX_CYCLES}cyc(enforced-by=seq_lib/smc_base_test_seq.py)",
                f"tb_fuse_sense_done={sense}",
            )
        )
        self._stamp("S1")

        # S2
        addrs: list[int] = []
        for core in range(CORES):
            for entry in range(ENTRIES):
                addr, data, resp = await self._read(core, entry)
                assert resp == OKAY
                addrs.append(addr)
        assert len(set(addrs)) == CORES * ENTRIES, f"WB_PC addresses not distinct: {addrs}"
        for core in range(CORES):
            last = _wb_pc_addr(core, ENTRIES - 1)
            assert last in addrs, f"last entry of core {core} @0x{last:08x} not answered"
        self._stamp("S2")
        self._chk(
            "CHK-WBPC-DECODE",
            f"{len(addrs)} WB_PC words answered OKAY at {len(set(addrs))} distinct addresses "
            f"0x{min(addrs):08x}..0x{max(addrs):08x}, none DECERR; last entries "
            + ",".join(f"0x{_wb_pc_addr(c, ENTRIES - 1):08x}" for c in range(CORES)),
        )

        # S3
        rows = []
        for core in range(CORES):
            for entry in range(ENTRIES):
                _, d1, _ = await self._read(core, entry)
                p1 = self._probe(core)
                _, d2, _ = await self._read(core, entry)
                p2 = self._probe(core)
                assert d1 == d2, f"idle WB_PC_CORE{core}[{entry}] disagrees: 0x{d1:x} vs 0x{d2:x}"
                rows.append(f"c{core}[{entry}]=0x{d1:x}/0x{d2:x}@probe0x{p1:x}/0x{p2:x}")
        self._waits.append(("sep_in_access", f"{axi_bound}ns", self._last_access))
        self._stamp("S3")
        self._chk(
            "CHK-WBPC-IDLE",
            f"{len(rows)} entries read twice, reads agree, printed beside tb_cpu_wb_pc<n> "
            "(owner value pending: meaning and idle value measured, not asserted): "
            + " ".join(rows),
        )

        self.assert_all_reachable(len(addrs) + 2 * len(rows), "CPU_CTRL_WB_PC")
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s",
            len(self._waits),
            " ".join(f"{n}={b} last={s}" for n, b, s in self._waits),
        )
        self._chk_order.append(("CHK-TIMEOUT-PATHS", len(self._stamps)))
        self.chk_seen.add("CHK-TIMEOUT-PATHS")
        self._fence()

    def _fence(self) -> None:
        steps = [s for s, _ in self._stamps]
        assert tuple(steps) == STEP_ORDER, f"step order {steps}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing {times}"
        order = [c for c, _ in self._chk_order]
        assert order[:2] == ["CHK-WBPC-DECODE", "CHK-WBPC-IDLE"], f"checker order {order}"
        for chk_id, n_stamps in self._chk_order:
            step = CHK_STEP.get(chk_id)
            if step:
                assert n_stamps == STEP_ORDER.index(step) + 1, f"{chk_id} printed before {step}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(FENCE_TERMS[s] for s in steps),
            ",".join(order),
            ",".join(f"{s}={t}ps" for s, t in self._stamps),
        )
        self.chk_seen.add("CHK-NONVAC")
