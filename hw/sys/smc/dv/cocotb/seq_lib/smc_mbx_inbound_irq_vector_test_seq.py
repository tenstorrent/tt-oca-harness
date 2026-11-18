# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Inbound mailbox interrupts at raw tb_cpu_interrupts bits 319:288 and PLIC sources 289 to 320.

Spec sources: interrupts.adoc SMC indexed interrupt map table, row [319:288] (mailbox channel m
drives raw bit 288 + m) and PLIC Sources and Contexts (raw bit N is PLIC source N + 1);
axil_mailbox.rdl IRQEN, IRQS and CTRL; plic.rdl PENDING.
"""

from __future__ import annotations

import os

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import _REPO, REGION_SIZE_RESET, _field_mask, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

_AXIL_MAILBOX_H = (
    _REPO / "hw" / "ip" / "axi_lite_mailbox_unit" / "regs" / "gen" / "c" / "axil_mailbox.h"
)
CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
REGION_SIZE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
REGION_SIZE_256M = 0x1000_0000
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
RAW_BASE = 288
# PLIC PENDING words 9 and 10 carry sources 288 to 351; mailbox m is source 289 + m.
PENDING_WORDS = (9, 10)
PLIC = "SMC_TOP_SMC_CLUSTER_PLIC_"
THRESHOLD0 = smc_addr(PLIC + "CORE0_MEIP_THRESHOLD_BASE_ADDR")
CLAIM0 = smc_addr(PLIC + "CORE0_MEIP_CLAIM_COMPLETE_BASE_ADDR")
CLAIM_CAP = 40
_STEPS = ("S1", "S2", "S3", "S4", "S5")
_CHECKERS = (
    ("CHK-MBXIN-POSITION", "S2"),
    ("CHK-MBXIN-MULTI", "S3"),
    ("CHK-MBXIN-CLEAR", "S4"),
)


def _mask(members) -> int:
    return sum(1 << m for m in members)


def _bits(vec: int) -> str:
    return "{" + ",".join(str(RAW_BASE + b) for b in range(32) if vec >> b & 1) + "}"


def _ids(vec: int) -> str:
    return "{" + ",".join(str(RAW_BASE + b) for b in range(64) if vec >> b & 1) + "}"


def _pending_ids(members) -> int:
    """Bit (289 + m - 288) of the PENDING words 9..10 view for each mailbox m."""
    return sum(1 << (m + 1) for m in members)


class smc_mbx_inbound_irq_vector_test_seq(SmcCsrSeq):
    """Push inbound mailboxes; raw bit 288 + m and PLIC source 289 + m must be the ones that rise."""

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
        return (self._probe("tb_cpu_interrupts") >> RAW_BASE) & 0xFFFF_FFFF, self._probe(
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

    async def _pending(self, tag: str) -> int:
        """PLIC PENDING words 9 and 10 as one value, bit k for source 288 + k."""
        words = [
            await self.csr_read(
                f"{tag}_PENDING{w}", smc_indexed_addr(PLIC + "PENDING_BASE_ADDR", w)
            )
            for w in PENDING_WORDS
        ]
        return words[0] | (words[1] << 32)

    async def _enable(self, tag: str, members) -> None:
        """Context 0 enable words 9 and 10 carry only the members' sources 289 + m."""
        bits = _pending_ids(members)
        for i, w in enumerate(PENDING_WORDS):
            await self.csr_write(
                f"{tag}_ENABLE{w}",
                smc_indexed_addr(PLIC + "CORE0_MEIP_ENABLE_BASE_ADDR", w),
                (bits >> (32 * i)) & 0xFFFF_FFFF,
            )

    async def _claim_members(self, chk: str, tag: str, members) -> list[int]:
        """Claim and complete each member's source on context 0 until the claim reads 0."""
        await self._enable(tag, members)
        expected = {RAW_BASE + 1 + m for m in members}
        claimed = []
        for _ in range(CLAIM_CAP):
            claim = await self.csr_read(f"{tag}_CLAIM{len(claimed)}", CLAIM0)
            if claim == 0:
                break
            assert claim in expected and claim not in claimed, (
                f"{chk}: mailboxes {list(members)}: context 0 claim read {claim}, expected one of "
                f"{sorted(expected - set(claimed))}"
            )
            claimed.append(claim)
            await self.csr_write(f"{tag}_COMPLETE{claim}", CLAIM0, claim)
        assert set(claimed) == expected, (
            f"{chk}: mailboxes {list(members)}: claims {claimed}, expected every source of "
            f"{sorted(expected)} exactly once"
        )
        await self._enable(f"{tag}_off", ())
        return claimed

    async def _arm(self, tag: str, m: int) -> None:
        await self._acc(f"{tag}_EN{m}", SmcSysAxiOp.WRITE, m, "IRQEN", WTIRQ)
        await self._acc(f"{tag}_PUSH{m}", SmcSysAxiOp.WRITE, m, "WRITE_DATA", WORD)

    async def _disarm(self, tag: str, m: int, enable_off: bool = True) -> None:
        if enable_off:
            await self._acc(f"{tag}_EN0_{m}", SmcSysAxiOp.WRITE, m, "IRQEN", 0)
        await self._acc(f"{tag}_FLUSH{m}", SmcSysAxiOp.WRITE, m, "CTRL", WFLUSH | RFLUSH)
        await self._acc(f"{tag}_ACK{m}", SmcSysAxiOp.WRITE, m, "IRQS", IRQ_ALL)

    @staticmethod
    def _require_exact(chk: str, members, raw: int, mbx: int, n: int) -> None:
        want = _mask(members)
        assert raw == want and mbx == want, (
            f"{chk}: mailboxes {list(members)}: expected raw {_bits(want)} and "
            f"tb_mailbox_interrupts 0x{want:08x}, observed raw {_bits(raw)} mailbox=0x{mbx:08x} "
            f"at rise {n} (extra {_bits(raw & ~want)}, missing {_bits(want & ~raw)})"
        )

    async def _require_pending(self, chk: str, tag: str, members, before: int) -> int:
        """The PLIC sources that newly pend after a push are exactly 289 + m of the members."""
        after = await self._pending(tag)
        want = _pending_ids(members)
        assert before & want == 0 and after & ~before == want, (
            f"{chk}: mailboxes {list(members)}: PLIC sources newly pending "
            f"{_ids(after & ~before)}, expected {_ids(want)} (pending before "
            f"{_ids(before)}, after {_ids(after)})"
        )
        return after

    async def _settle_group(self, chk: str, tag: str, members) -> str:
        """Arm and push the members; their raw bits and PLIC sources rise, then clear."""
        want = _mask(members)
        before = await self._pending(f"{tag}_before")
        for m in members:
            await self._arm(tag, m)
        n, raw, mbx = await self._poll(f"{tag}_rise", want, True)
        self._require_exact(chk, members, raw, mbx, n)
        after = await self._require_pending(chk, tag, members, before)
        for m in members:
            await self._disarm(tag, m)
        await self._poll(f"{tag}_fall", 0, False)
        claimed = await self._claim_members(chk, tag, members)
        return (
            f"mailboxes {list(members)}: raw {_bits(raw)} mailbox=0x{mbx:08x} rise@{n} "
            f"PLIC newly pending {_ids(after & ~before)}, claimed {claimed} after the clear"
        )

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
        await self.csr_write("REGION_SIZE_256M", REGION_SIZE, REGION_SIZE_256M)
        await self.csr_read("REGION_SIZE_256M_RB", REGION_SIZE, expected=REGION_SIZE_256M)
        saved_prio = {}
        for m in ALL32:
            addr = smc_indexed_addr(PLIC + "PRIORITY_BASE_ADDR", RAW_BASE + 1 + m)
            saved_prio[m] = await self.csr_read(f"PRIORITY{RAW_BASE + 1 + m}_SAVE", addr)
            await self.csr_write(f"PRIORITY{RAW_BASE + 1 + m}_ONE", addr, 1)
        saved_threshold = await self.csr_read("THRESHOLD0_SAVE", THRESHOLD0)
        await self.csr_write("THRESHOLD0_ZERO", THRESHOLD0, 0)
        idle = await self._pending("S1_idle") & _pending_ids(ALL32)
        assert idle == 0, f"PLIC sources {_ids(idle)} pending before any push"
        self._mark_step("S1")

        rows = []
        for m in SINGLES:
            row = await self._settle_group("CHK-MBXIN-POSITION", f"S2_M{m}", (m,))
            rows.append(row)
        self._mark_step("S2")
        self._log_chk(
            "CHK-MBXIN-POSITION",
            f"each single push raised exactly raw bit {RAW_BASE} + m, tb_mailbox_interrupts bit m "
            f"and PLIC source {RAW_BASE + 1} + m, claimed as that ID on context 0: "
            + "; ".join(rows),
        )

        rows = [
            await self._settle_group("CHK-MBXIN-MULTI", f"S3_G{i}", g) for i, g in enumerate(PAIRS)
        ]
        before = await self._pending("S3_ALL_before")
        for m in ALL32:
            await self._arm("S3_ALL", m)
        want = _mask(ALL32)
        n, raw, mbx = await self._poll("S3_ALL_rise", want, True)
        self._require_exact("CHK-MBXIN-MULTI", ALL32, raw, mbx, n)
        after = await self._require_pending("CHK-MBXIN-MULTI", "S3_ALL", ALL32, before)
        rows.append(
            f"mailboxes all 32: raw {_bits(raw)} mailbox=0x{mbx:08x} rise@{n} PLIC newly pending "
            f"{_ids(after & ~before)} (claimed after the clear of S4)"
        )
        self._mark_step("S3")
        self._log_chk(
            "CHK-MBXIN-MULTI",
            "pairs and all 32 together raised exactly their own raw bits, mailbox bits and PLIC "
            "sources, each claimed as its ID on context 0: " + "; ".join(rows),
        )

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
        assert seen is not None and after == (want5, want5), (
            f"CHK-MBXIN-CLEAR: after IRQEN=0 on mailbox 5 raw {_bits(after[0])} "
            f"mailbox=0x{after[1]:08x} (first change at rise {seen}), expected only raw bit "
            f"{RAW_BASE + 5} and mailbox bit 5 to fall: {_bits(want5)}"
        )
        for m in ALL32:
            await self._disarm("S4_ALL", m, enable_off=m != 5)
        n, raw, mbx = await self._poll("S4_all_fall", 0, False)
        claimed = await self._claim_members("CHK-MBXIN-CLEAR", "S4_ALL", ALL32)
        self._mark_step("S4")
        self._log_chk(
            "CHK-MBXIN-CLEAR",
            f"after IRQEN=0 on mailbox 5 only raw bit {RAW_BASE + 5} and mailbox bit 5 fell, raw "
            f"{_bits(after[0])} mailbox=0x{after[1]:08x} first change at rise {seen}; after clear "
            f"and flush of all 32 raw {_bits(raw)} mailbox=0x{mbx:08x} reached the baseline "
            f"0x{base_raw:08x} at rise {n}; context 0 then claimed the {len(claimed)} latched "
            f"sources {min(claimed)}..{max(claimed)} once each and read 0",
        )

        for m, value in saved_prio.items():
            addr = smc_indexed_addr(PLIC + "PRIORITY_BASE_ADDR", RAW_BASE + 1 + m)
            await self.csr_write(f"PRIORITY{RAW_BASE + 1 + m}_RESTORE", addr, value)
        await self.csr_write("THRESHOLD0_RESTORE", THRESHOLD0, saved_threshold)
        await self.csr_read("THRESHOLD0_RESTORE_RB", THRESHOLD0, expected=saved_threshold)
        await self.csr_write("REGION_SIZE_RESTORE", REGION_SIZE, REGION_SIZE_RESET)
        await self.csr_read("REGION_SIZE_RESTORE_RB", REGION_SIZE, expected=REGION_SIZE_RESET)
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
            "waits per clk_smc_i rise: %s; SEP_IN CSR accesses (CLOCK_GATE_CONTROL, REGION_SIZE, "
            "PLIC PRIORITY, THRESHOLD, ENABLE, PENDING, CLAIM_COMPLETE, mailbox IRQEN, WRITE_DATA, "
            "CTRL, IRQS) x%d bound=%d ns allow_timeout "
            "False last[%d accesses completed]; clear window, cap %d rises, graded by "
            "CHK-MBXIN-CLEAR: %s",
            fuse,
            len(self._waits) - 1,
            own,
            self.accesses,
            AXI_TIMEOUT_NS,
            self.accesses,
            POLL_CAP,
            obs,
        )
