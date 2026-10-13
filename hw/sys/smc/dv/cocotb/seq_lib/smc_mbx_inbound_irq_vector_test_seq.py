# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Inbound mailbox interrupts at raw tb_cpu_interrupts bits 319:288.

Contract SMC_IRQ_013, anchor smc_mbx_inbound_irq_vector_test.
Allocated scenarios: IRQ-MBX-INBOUND.S1, IRQ-MBX-INBOUND.S2, IRQ-MBX-INBOUND.S3.
Spec sources: interrupts.adoc SMC indexed interrupt map table; axi_lite_mailbox_unit
SMC mailbox wrapper and interrupt routing; open SF-006.
"""

from __future__ import annotations

import os

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import _REPO, _field_mask, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

_AXIL_MAILBOX_H = (
    _REPO / "hw" / "ip" / "axi_lite_mailbox_unit" / "regs" / "gen" / "c" / "axil_mailbox.h"
)
CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
MAILBOX_CG_EN = _field_mask(
    _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "smc_base_config.h",
    "SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__MAILBOX_CG_EN_bm",
)
WTIRQ = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__IRQS__WTIRQ_bm")
RTIRQ = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__IRQS__RTIRQ_bm")
EIRQ = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__IRQS__EIRQ_bm")
WFLUSH = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__CTRL__WFLUSH_bm")
RFLUSH = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__CTRL__RFLUSH_bm")
IRQ_ALL = WTIRQ | RTIRQ | EIRQ

FUSE_SENSE_RISES = 200_000
AXI_TIMEOUT_NS = 50_000
POLL_CAP = 128
SINGLES = (0, 1, 15, 16, 30, 31)
PAIRS = ((0, 1), (0, 31))
ALL32 = tuple(range(32))
WORD = 0x1111_2222_3333_4444
_STEPS = ("S1", "S2", "S3", "S4", "S5")
_CHECKERS = (
    ("CHK-MBXIN-POSITION-LOG", "S2"),
    ("CHK-MBXIN-MULTI-LOG", "S3"),
    ("CHK-MBXIN-CLEAR-LOG", "S4"),
)


def _mask(members) -> int:
    return sum(1 << m for m in members)


def _bits(vec: int) -> str:
    return "{" + ",".join(str(288 + b) for b in range(32) if vec >> b & 1) + "}"


class smc_mbx_inbound_irq_vector_test_seq(SmcCsrSeq):
    """Push inbound mailboxes and log the raw 319:288 vector against the expected bits."""

    def __init__(self, name: str = "smc_mbx_inbound_irq_vector_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: dict[str, list] = {}

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    @staticmethod
    def _probe(name: str) -> int:
        raw = getattr(cocotb.top, name).value
        assert raw.is_resolvable, f"{name} is X/Z: {raw}"
        return int(raw)

    def _vectors(self) -> tuple[int, int]:
        """Return (raw bits 319:288, tb_mailbox_interrupts) sampled now."""
        return (self._probe("tb_cpu_interrupts") >> 288) & 0xFFFF_FFFF, self._probe(
            "tb_mailbox_interrupts"
        )

    async def _poll(self, tag: str, want: int, rising: bool) -> tuple[int, int, int]:
        """Sample each clk_smc_i rise until the wanted bits are all 1 (or the vector is 0)."""
        for n in range(POLL_CAP + 1):
            raw, mbx = self._vectors()
            self._waits[tag] = [POLL_CAP, n, raw, mbx]
            if (raw & want) == want if rising else raw == 0 and mbx == 0:
                return n, raw, mbx
            await ClockCycles(cocotb.top.clk_smc_i, 1)
        raise AssertionError(
            f"{tag}: want {'rise of' if rising else 'baseline'} 0x{want:08x} within {POLL_CAP} "
            f"rises, last raw=0x{raw:08x} mailbox=0x{mbx:08x}"
        )

    async def _acc(self, name: str, op, m: int, reg: str, data: int = 0) -> int | None:
        item = SmcSysAxiItem(f"{op.value[0]}_{name}")
        item.op = op
        item.addr = smc_addr(f"SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_{m}_{reg}_BASE_ADDR")
        item.length, item.wdata, item.expected = 8, data, None
        item.allow_error = False
        item.expect_error, item.expected_resp = False, None
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code == 0, f"{item.name}: resp {item.resp_code}"
        return item.rdata

    async def _arm(self, tag: str, m: int) -> None:
        await self._acc(f"{tag}_EN{m}", SmcSysAxiOp.WRITE, m, "IRQEN", WTIRQ)
        await self._acc(f"{tag}_PUSH{m}", SmcSysAxiOp.WRITE, m, "WRITE_DATA", WORD)

    async def _disarm(self, tag: str, m: int, enable_off: bool = True) -> None:
        if enable_off:
            await self._acc(f"{tag}_EN0_{m}", SmcSysAxiOp.WRITE, m, "IRQEN", 0)
        await self._acc(f"{tag}_FLUSH{m}", SmcSysAxiOp.WRITE, m, "CTRL", WFLUSH | RFLUSH)
        await self._acc(f"{tag}_ACK{m}", SmcSysAxiOp.WRITE, m, "IRQS", IRQ_ALL)

    async def _settle_group(self, tag: str, members) -> str:
        """Arm and push the members, wait for their raw bits, log the set, then clear."""
        want = _mask(members)
        for m in members:
            await self._arm(tag, m)
        n, raw, mbx = await self._poll(f"{tag}_rise", want, True)
        row = (
            f"mailboxes {list(members)}: expected {_bits(want)} observed {_bits(raw)} "
            f"mailbox=0x{mbx:08x} rise@{n} extra={_bits(raw & ~want)}"
        )
        for m in members:
            await self._disarm(tag, m)
        await self._poll(f"{tag}_fall", 0, False)
        return row

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        seed = int(os.environ.get("RANDOM_SEED", "1"))
        cocotb.log.info("SEED RANDOM_SEED=%d", seed)
        base_raw, base_mbx = self._vectors()
        base_full = self._probe("tb_cpu_interrupts")
        assert base_raw == 0 and base_mbx == 0, (
            f"baseline raw 319:288=0x{base_raw:08x} mailbox=0x{base_mbx:08x}"
        )
        cocotb.log.info(
            "BASELINE tb_cpu_interrupts=0x%x tb_mailbox_interrupts=0x%08x", base_full, base_mbx
        )
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_CONTROL_EN", CLOCK_GATE_CONTROL, cg | MAILBOX_CG_EN)
        await self.csr_read(
            "CLOCK_GATE_CONTROL_RB", CLOCK_GATE_CONTROL, expected=cg | MAILBOX_CG_EN
        )
        self._mark_step("S1")

        rows = []
        for m in SINGLES:
            row = await self._settle_group(f"S2_M{m}", (m,))
            rows.append(row)
        self._mark_step("S2")
        self._log_chk("CHK-MBXIN-POSITION-LOG", "observe-and-log (SF-006): " + "; ".join(rows))

        rows = [await self._settle_group(f"S3_G{i}", g) for i, g in enumerate(PAIRS)]
        for m in ALL32:
            await self._arm("S3_ALL", m)
        want = _mask(ALL32)
        n, raw, mbx = await self._poll("S3_ALL_rise", want, True)
        rows.append(
            f"mailboxes all 32: expected {_bits(want)} observed {_bits(raw)} mailbox=0x{mbx:08x} "
            f"rise@{n}"
        )
        self._mark_step("S3")
        self._log_chk("CHK-MBXIN-MULTI-LOG", "observe-and-log (SF-006): " + "; ".join(rows))

        await self._acc("S4_EN0_5", SmcSysAxiOp.WRITE, 5, "IRQEN", 0)
        want5 = want & ~(1 << 5)
        seen, after = None, (raw, mbx)
        for n5 in range(POLL_CAP + 1):
            after = self._vectors()
            self._waits["S4_clear5_window"] = [POLL_CAP, n5, *after]
            if after[0] != want:
                seen = n5
                break
            await ClockCycles(cocotb.top.clk_smc_i, 1)
        only5 = after[0] == want5
        for m in ALL32:
            await self._disarm("S4_ALL", m, enable_off=m != 5)
        n, raw, mbx = await self._poll("S4_all_fall", 0, False)
        self._mark_step("S4")
        self._log_chk(
            "CHK-MBXIN-CLEAR-LOG",
            f"observe-and-log (SF-006): after IRQEN=0 on mailbox 5 raw {_bits(after[0])} "
            f"mailbox=0x{after[1]:08x} first change@{seen} expected all-but-293 "
            f"{_bits(want5)} only_293_fell={only5}; after clear and flush of all 32 raw "
            f"{_bits(raw)} mailbox=0x{mbx:08x} baseline 0x{base_raw:08x} reached@{n}",
        )

        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, cg)
        await self.csr_read("CLOCK_GATE_CONTROL_RESTORED", CLOCK_GATE_CONTROL, expected=cg)
        self._mark_step("S5")
        self._nonvac_fence()
        self._log_timeout_paths()

    def _nonvac_fence(self) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t in self._stamps]
        assert all(y > x for x, y in zip(times, times[1:])), f"stamps not increasing: {times}"
        chk_ids = tuple(c for c, _ in self._chk_marks)
        assert chk_ids == tuple(c for c, _ in _CHECKERS), f"checker lines {chk_ids}"
        stamp_of = dict(self._stamps)
        for (chk_id, when), (_, step) in zip(self._chk_marks, _CHECKERS):
            assert when >= stamp_of[step], f"{chk_id} printed before its step {step} stamp"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence BASELINE<SINGLE-SWEEP<GROUPS<CLEAR-ONE<CLEAR-ALL; "
            "checker lines %s; stamps %s",
            ",".join(chk_ids),
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )

    @staticmethod
    def _level(name: str) -> str:
        sig = getattr(cocotb.top, name, None)
        return "absent" if sig is None else str(int(sig.value))

    def _log_timeout_paths(self) -> None:
        subs = ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n")
        fuse = "; ".join(
            f"fuse sense wait {sig} (AssertionError on expiry) bound={FUSE_SENSE_RISES} rises "
            f"last[{sig}={self._level(sig)}]"
            for sig in subs
        )
        window = "S4_clear5_window"

        def fmt(tag, cap, used, raw, mbx):
            return f"{tag} bound={cap} rises last[rises={used} raw=0x{raw:08x} mailbox=0x{mbx:08x}]"

        own = "; ".join(fmt(t, *v) for t, v in self._waits.items() if t != window)
        obs = fmt(window, *self._waits[window])
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: waits that raise AssertionError on expiry: %s; %d own probe "
            "waits per clk_smc_i rise: %s; SEP_IN CSR accesses (CLOCK_GATE_CONTROL, mailbox "
            "IRQEN, WRITE_DATA, CTRL, IRQS) x%d bound=%d ns allow_timeout False last[%d "
            "accesses completed]; observation window, cap %d rises, no expiry failure: %s",
            fuse,
            len(self._waits) - 1,
            own,
            self.accesses,
            AXI_TIMEOUT_NS,
            self.accesses,
            POLL_CAP,
            obs,
        )
