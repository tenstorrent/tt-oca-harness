# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC_CPU_CTRL_017 / smc_cpu_ctrl_access_rules_test: CPU_CTRL access rules.

Scenarios: CPUCTRL-ACCESS.S4, CPUCTRL-ACCESS.S5, CPUCTRL-ACCESS.S6, CPUCTRL-ACCESS.S9.
Sources: hw/sys/smc/regs/blocks/cpu_ctrl/cpu_ctrl.rdl, hw/sys/smc/doc/memmap.adoc.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import cpu_ctrl_u32, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

FUSE_SENSE_MAX_CYCLES = 200_000
WORD64 = 0xFFFF_FFFF_FFFF_FFFF
PROT_SECURE = 0b000
PROT_NONSECURE = 0b010
RESP_NAMES = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}
STEP_ORDER = ("S1", "S2", "S3", "S4", "S5")
FENCE_TERMS = {
    "S1": "BRINGUP_DONE",
    "S2": "ZERO_WRITES_COMPARED",
    "S3": "READ_ONLY_WRITES_COMPARED",
    "S4": "RESERVED_BITS_COMPARED",
    "S5": "PROT_MEASURED",
}
CHK_STEP = {
    "CHK-ACCR-ZERO": "S2",
    "CHK-ACCR-RO-RESP": "S3",
    "CHK-ACCR-RESERVED": "S4",
    "CHK-ACCR-PROT": "S5",
}
CHK_ORDER = tuple(CHK_STEP)


class smc_cpu_ctrl_access_rules_test_seq(SmcCsrSeq):
    """Drive zero, all-ones, reserved-bit and AxPROT accesses at CPU_CTRL over SEP_IN."""

    def __init__(self, name: str = "smc_cpu_ctrl_access_rules_test_seq") -> None:
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

    async def _acc(
        self, op: SmcSysAxiOp, name: str, addr: int, data: int = 0, length: int = 8, prot: int = 0
    ) -> tuple[int, str]:
        """One SEP_IN access whose response is returned, not required to be OKAY."""
        item = SmcSysAxiItem(f"{op.value}_{name}")
        item.op = op
        item.addr = addr
        item.length = length
        item.wdata = data
        item.prot = prot
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        resp = RESP_NAMES.get(item.resp_code, f"resp={item.resp_code}")
        shown = data if op is SmcSysAxiOp.WRITE else item.rdata
        self._last_access = f"{op.value} {name}@0x{addr:08x} data=0x{shown:x} resp={resp}"
        assert not item.timed_out, f"access timed out: {self._last_access}"
        assert item.resp_code is not None, f"no response: {self._last_access}"
        return item.rdata, resp

    async def _rd(self, name: str, addr: int, length: int = 8, prot: int = 0) -> int:
        data, resp = await self._acc(SmcSysAxiOp.READ, name, addr, length=length, prot=prot)
        assert resp == "OKAY", f"read answered {resp}: {self._last_access}"
        return data

    async def _wr(self, name: str, addr: int, data: int, length: int = 8, prot: int = 0) -> str:
        _, resp = await self._acc(SmcSysAxiOp.WRITE, name, addr, data, length, prot)
        return resp

    async def _wr_ok(self, name: str, addr: int, data: int, length: int = 8) -> None:
        resp = await self._wr(name, addr, data, length)
        assert resp == "OKAY", f"read-write register write answered {resp}: {self._last_access}"

    async def _expect(self, name: str, addr: int, expected: int, length: int = 8) -> int:
        got = await self._rd(name, addr, length)
        assert got == expected, (
            f"{name}@0x{addr:08x}: read 0x{got:x}, expected 0x{expected:x} "
            f"(last access: {self._last_access})"
        )
        return got

    async def body(self) -> None:
        dut = cocotb.top
        assert hasattr(dut, "tb_fuse_sense_done"), "tb_fuse_sense_done not exported"
        axi_bound = self.cfg.axi_timeout_ns
        cnt = smc_addr("SMC_TOP_SMC_CPU_CTRL_CORE_RESET_PULSE_COUNT_BASE_ADDR")
        rto = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_TIMEOUT_BASE_ADDR")
        wdt = smc_addr("SMC_TOP_SMC_CPU_CTRL_WDT_TIMEOUT_BASE_ADDR")
        wdt_rst = smc_addr("SMC_TOP_SMC_CPU_CTRL_WDT_TIMEOUT_RESET_BASE_ADDR")
        test_ctrl = smc_addr("SMC_TOP_SMC_CPU_CTRL_TEST_CTRL_BASE_ADDR")
        attrs = smc_addr("SMC_TOP_SMC_CPU_CTRL_SMC_ATTRIBUTES_BASE_ADDR")
        local_base = smc_addr("SMC_TOP_SMC_BASE_CONFIG_LOCAL_BASE_BASE_ADDR")
        wb_pc = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_WB_PC_CORE0_BASE_ADDR", 0)
        scratch1 = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", 1)
        rvec1 = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_RESET_VECTOR_BASE_ADDR", 1)
        rctrl = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_CTRL_BASE_ADDR")

        done_bm = cpu_ctrl_u32("CPU_CTRL__CORE_RESET_PULSE_COUNT__CORE_RESETS_DONE_bm")
        done_bp = cpu_ctrl_u32("CPU_CTRL__CORE_RESET_PULSE_COUNT__CORE_RESETS_DONE_bp")
        done_reset = cpu_ctrl_u32("CPU_CTRL__CORE_RESET_PULSE_COUNT__CORE_RESETS_DONE_reset")
        pre_reset = cpu_ctrl_u32("CPU_CTRL__CORE_RESET_PULSE_COUNT__PRE_RESET_COUNT_reset")
        post_reset = cpu_ctrl_u32("CPU_CTRL__CORE_RESET_PULSE_COUNT__POST_RESET_COUNT_reset")
        post_bp = cpu_ctrl_u32("CPU_CTRL__CORE_RESET_PULSE_COUNT__POST_RESET_COUNT_bp")
        mode_bp = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__TIMEOUT_MODE_bp")
        done_field = done_reset << done_bp
        count_reset = pre_reset | (post_reset << post_bp) | done_field
        scratch_bm = cpu_ctrl_u32("CPU_CTRL__SCRATCH__DATA_bm")
        vec_bm = cpu_ctrl_u32("CPU_CTRL__RESET_VECTOR__VECTOR_bm")
        pc_bm = cpu_ctrl_u32("CPU_CTRL__WB_PC__PC_bm")
        wdt_bm = cpu_ctrl_u32("CPU_CTRL__WDT_TIMEOUT__DATA_bm")
        ctrl_named = 0
        for sym in (
            "CORE0_RESET_N_N0_SCAN",
            "CORE1_RESET_N_N0_SCAN",
            "CORE2_RESET_N_N0_SCAN",
            "CORE3_RESET_N_N0_SCAN",
            "CORE0_RESET_PULSE_START_N0_SCAN",
            "CORE1_RESET_PULSE_START_N0_SCAN",
            "CORE2_RESET_PULSE_START_N0_SCAN",
            "CORE3_RESET_PULSE_START_N0_SCAN",
            "UNCORE_RESET_N_N0_SCAN",
            "DEBUG_RESET_N_N0_SCAN",
        ):
            ctrl_named |= cpu_ctrl_u32(f"CPU_CTRL__RESET_CTRL__{sym}_bm")

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
        pre_set, post_set, tmo_set = 0x0123, 0x0456, 0xBEEF
        count_set = pre_set | (post_set << post_bp)
        rto_set = tmo_set | (1 << mode_bp)
        await self._wr_ok("CORE_RESET_PULSE_COUNT_SET", cnt, count_set)
        await self._wr_ok("RESET_TIMEOUT_SET", rto, rto_set)
        await self._expect("CORE_RESET_PULSE_COUNT_SET_RB", cnt, count_set | done_field)
        await self._expect("RESET_TIMEOUT_SET_RB", rto, rto_set)
        await self._wr_ok("CORE_RESET_PULSE_COUNT_ZERO", cnt, 0)
        await self._wr_ok("RESET_TIMEOUT_ZERO", rto, 0)
        count_zero = await self._expect("CORE_RESET_PULSE_COUNT_ZERO_RB", cnt, done_field)
        rto_zero = await self._expect("RESET_TIMEOUT_ZERO_RB", rto, 0)
        await self._wr_ok("WDT_TIMEOUT_RESET_ZERO", wdt_rst, 0, length=4)
        wdt_zero = await self._expect("WDT_TIMEOUT_RESET_ZERO_RB", wdt_rst, 0, length=4)
        await self._wr_ok("CORE_RESET_PULSE_COUNT_RESTORE", cnt, count_reset & ~done_field)
        await self._expect("CORE_RESET_PULSE_COUNT_RESTORE_RB", cnt, count_reset)
        self._stamp("S2")
        self._chk(
            "CHK-ACCR-ZERO",
            f"after full-width 0: CORE_RESET_PULSE_COUNT 0x{count_set:x}->0x{count_zero:x} "
            f"(core_resets_done 0x{done_reset:x}), RESET_TIMEOUT 0x{rto_set:x}->0x{rto_zero:x} "
            f"(reset_applied 0, reset_timeout 0), WDT_TIMEOUT_RESET read 0x{wdt_zero:x}; "
            f"CORE_RESET_PULSE_COUNT restored 0x{count_reset:x}",
        )

        # S3
        rows = []
        targets = [
            ("TEST_CTRL", test_ctrl),
            ("WB_PC_CORE0_0", wb_pc),
            ("SMC_ATTRIBUTES", attrs),
            ("LOCAL_BASE", local_base),
        ]
        for label, addr in targets:
            before = await self._rd(f"{label}_BEFORE", addr)
            resp = await self._wr(f"{label}_ALL_ONES", addr, WORD64)
            after = await self._expect(f"{label}_AFTER", addr, before)
            rows.append(f"{label}:wr=0x{WORD64:x},resp={resp},read=0x{after:x}")
        before = await self._rd("CORE_RESETS_DONE_BEFORE", cnt)
        assert before == count_reset, f"pulse count read 0x{before:x} != 0x{count_reset:x}"
        for label, word in (("ONES", before | done_bm), ("ZERO", before & ~done_bm)):
            resp = await self._wr(f"CORE_RESETS_DONE_{label}", cnt, word)
            after = await self._expect(f"CORE_RESETS_DONE_{label}_AFTER", cnt, before)
            rows.append(f"core_resets_done_{label}:wr=0x{word:x},resp={resp},read=0x{after:x}")
        self._stamp("S3")
        self._chk(
            "CHK-ACCR-RO-RESP",
            "each read-only register read its pre-write word after the write "
            "(write responses printed, SF-003 open): " + " ".join(rows),
        )

        # S4
        rows = []

        async def reserved_leg(label: str, addr: int, declared: int, length: int = 8) -> None:
            full = (1 << (length * 8)) - 1
            gap = full & ~declared
            before = await self._rd(f"{label}_BEFORE", addr, length)
            resp = await self._wr(f"{label}_GAP_ONES", addr, (before & declared) | gap, length)
            after = await self._rd(f"{label}_AFTER", addr, length)
            assert after & declared == before & declared, (
                f"{label}: named fields 0x{before & declared:x} -> 0x{after & declared:x} "
                f"after ones over reserved bits 0x{gap:x} (last access: {self._last_access})"
            )
            await self._wr_ok(f"{label}_RESTORE", addr, before, length)
            restored = await self._rd(f"{label}_RESTORE_RB", addr, length)
            assert restored == before, (
                f"{label}: restore read 0x{restored:x}, expected 0x{before:x} "
                f"(last access: {self._last_access})"
            )
            rows.append(
                f"{label}:resp={resp},reserved_read=0x{after & gap:x}/mask=0x{gap:x},"
                f"named=0x{after & declared:x}"
            )

        await reserved_leg("SCRATCH1", scratch1, scratch_bm)
        await reserved_leg("RESET_VECTOR1", rvec1, vec_bm)
        await reserved_leg("RESET_CTRL", rctrl, ctrl_named)
        await reserved_leg("WDT_TIMEOUT", wdt, wdt_bm)

        before = await self._rd("WB_PC_CORE0_0_RSV_BEFORE", wb_pc)
        gap = WORD64 & ~pc_bm
        resp = await self._wr("WB_PC_CORE0_0_RSV_ONES", wb_pc, (before & pc_bm) | gap)
        after = await self._rd("WB_PC_CORE0_0_RSV_AFTER", wb_pc)
        assert after & pc_bm == before & pc_bm, (
            f"WB_PC_CORE0[0]: pc 0x{before & pc_bm:x} -> 0x{after & pc_bm:x} "
            f"(last access: {self._last_access})"
        )
        rows.append(
            f"WB_PC_CORE0_0:resp={resp},reserved_read=0x{after & gap:x}/mask=0x{gap:x},"
            f"named=0x{after & pc_bm:x}"
        )
        self._stamp("S4")
        self._chk(
            "CHK-ACCR-RESERVED",
            "named fields held after ones over undeclared bits; reserved bits as read "
            "(SF-002 open): " + " ".join(rows),
        )

        # S5
        rows = []
        orig = await self._rd("SCRATCH1_PROT_ORIG", scratch1)
        for label, prot, pat in (
            ("SECURE", PROT_SECURE, 0x0000_0000_A5A5_5A5A),
            ("NONSECURE", PROT_NONSECURE, 0x0000_0000_5A5A_A5A5),
        ):
            wresp = await self._wr(f"SCRATCH1_{label}", scratch1, pat, prot=prot)
            data, rresp = await self._acc(
                SmcSysAxiOp.READ, f"SCRATCH1_{label}_RB", scratch1, prot=prot
            )
            rows.append(
                f"{label}(prot=0b{prot:03b}):wr=0x{pat:x},wresp={wresp},rd=0x{data:x},rresp={rresp}"
            )
        await self._wr_ok("SCRATCH1_PROT_RESTORE", scratch1, orig)
        await self._expect("SCRATCH1_PROT_RESTORE_RB", scratch1, orig)
        self._waits.append(("sep_in_access", f"{axi_bound}ns", self._last_access))
        self._stamp("S5")
        self._chk(
            "CHK-ACCR-PROT",
            "secure and non-secure SCRATCH[1] accesses completed (SF-027 open): " + " ".join(rows),
        )

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
        assert tuple(order[: len(CHK_ORDER)]) == CHK_ORDER, f"checker order {order}"
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
