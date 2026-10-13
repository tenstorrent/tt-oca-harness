# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""STATUS_SMU independence, reserved bits, pulses, resets and read-only writes.

Contract SMC_JTAG_DM_020, anchor smc_dfx_status_smu_pulse_reset_test.
Scenarios JDM-DFX-STATUS-STICKY.S6, S9 .. S13 and JDM-DFX-STATUS-RO.S1 .. S4.
Spec: dfx_ctrl_status.rdl STATUS, memmap.adoc DFX Status, clk_rst.adoc.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import FallingEdge, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_reset_item import SmcResetOp
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import (
    DFX_MBIST_ABORT,
    DFX_MEM_REPAIR_ABORT,
    DFX_STATUS_IDLE,
    DFX_STATUS_SMU,
    reset_unit_u32,
    smc_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_reset_seq_base import SmcResetSeqBase

MAX_STATUS_POLLS = 4
FUSE_SENSE_MAX_CYCLES = 200_000
AR_HANDSHAKE_MAX_CYCLES = 64
SS_WARM = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_WARM_RESET_N_BASE_ADDR")
SS_WARM_RESET_VALUE = reset_unit_u32("RESET_UNIT__SS_WARM_RESET_N__RESET_N_N0_SCAN_reset")
DEFINED_BITS = DFX_STATUS_IDLE | DFX_MEM_REPAIR_ABORT | DFX_MBIST_ABORT
ALL_ONES_64 = (1 << 64) - 1
IDLE_MBIST = DFX_STATUS_IDLE | DFX_MBIST_ABORT
IDLE_REPAIR = DFX_STATUS_IDLE | DFX_MEM_REPAIR_ABORT
IDLE_BOTH = DFX_STATUS_IDLE | DFX_MEM_REPAIR_ABORT | DFX_MBIST_ABORT
STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9")
FENCE_TERMS = (
    "BRINGUP_CLEAN_IDLE",
    "RO_CLEAN_UNCHANGED",
    "MBIST_ALONE",
    "STAGGER_TWO_WORDS",
    "RESERVED_ZERO",
    "RO_WRITES_IGNORED",
    "PULSE_CAPTURED",
    "RESETS_PRINTED",
    "HELD_THROUGH_RESET_PRINTED",
)
CHK_ORDER = (
    ("CHK-DFX-STATUS-RO-CLEAN", "S2"),
    ("CHK-DFX-STATUS-MBIST-ALONE", "S3"),
    ("CHK-DFX-STATUS-STAGGER", "S3"),
    ("CHK-DFX-STATUS-RESERVED", "S4"),
    ("CHK-DFX-STATUS-RO-SET", "S5"),
    ("CHK-DFX-STATUS-WRITE-RESP", "S5"),
    ("CHK-DFX-STATUS-PULSE", "S6"),
    ("CHK-DFX-STATUS-RESET-CLEARS", "S7"),
    ("CHK-DFX-STATUS-HIGH-THROUGH-RESET", "S8"),
    ("CHK-TIMEOUT-PATHS", "S9"),
)
RESP_NAMES = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR", None: "none"}


def _bit(word: int, mask: int) -> int:
    return int(word & mask != 0)


class smc_dfx_status_smu_pulse_reset_test_seq(SmcResetSeqBase, SmcCsrSeq):
    """Abort pins into STATUS_SMU: independence, reserved bits, RO writes, pulses, resets."""

    def __init__(self, name: str = "smc_dfx_status_smu_pulse_reset_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: set[str] = set()
        self._stamps: list[tuple[str, int]] = []
        self._chk_order: list[tuple[str, int]] = []
        self._waits: list[tuple[str, str, str]] = []
        self._last = "none"

    def _stamp(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_order.append((chk_id, len(self._stamps)))
        self.chk_seen.add(chk_id)

    async def _dispatch_reset_item(self, item) -> None:
        await _OneShot(item, "reset_os").start(self.env.reset_agent.sequencer)

    @staticmethod
    def _pins(repair: int, mbist: int) -> None:
        cocotb.top.tb_mem_repair_abort.value = repair
        cocotb.top.tb_mbist_abort.value = mbist

    async def _sense_wait(self, label: str) -> None:
        await self.wait_fuse_sense_done(FUSE_SENSE_MAX_CYCLES)
        sense = int(cocotb.top.tb_fuse_sense_done.value)
        assert sense == 1, f"{label}: tb_fuse_sense_done low after the wait returned"
        self._waits.append(
            (
                f"{label}_fuse_sense",
                f"{FUSE_SENSE_MAX_CYCLES}cyc(enforced-by=seq_lib/smc_base_test_seq.py)",
                f"tb_fuse_sense_done={sense}",
            )
        )

    async def _read(self, label: str, expected: int | None = None) -> int:
        got = await self.csr_read(label, DFX_STATUS_SMU, expected=expected, length=8)
        assert isinstance(got, int), f"{label}: STATUS_SMU read data not resolvable"
        self._last = f"{label} STATUS_SMU=0x{got:x}"
        return got

    async def _poll(self, label: str, accept, allowed: tuple[int, ...] = ()) -> tuple[int, int]:
        last = -1
        for n in range(1, MAX_STATUS_POLLS + 1):
            last = await self._read(f"{label}_P{n}")
            if accept(last):
                self._waits.append(
                    (label, f"{MAX_STATUS_POLLS}reads(leaf loop)", f"matched poll {n} 0x{last:x}")
                )
                return last, n
            assert not allowed or last in allowed, f"{label}: torn word 0x{last:x} (poll {n})"
        raise AssertionError(
            f"{label}: STATUS_SMU=0x{last:x} not reached within {MAX_STATUS_POLLS} reads"
        )

    async def _write(self, label: str, data: int, wstrb: int | None) -> int | None:
        item = SmcSysAxiItem(f"wr_{label}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = DFX_STATUS_SMU
        item.length = 8
        item.wdata = data
        item.wstrb = wstrb
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None, f"{label}: no AXI write response"
        cocotb.log.info(
            "STATUS_SMU write %s data=0x%x wstrb=%s resp=%s",
            label,
            data,
            "default" if wstrb is None else f"0x{wstrb:02x}",
            RESP_NAMES.get(item.resp_code),
        )
        return item.resp_code

    async def _cold_reset(self) -> None:
        await self._send(SmcResetOp.COLD_RST_LO)
        item = await self._wait_state(
            "cold assert",
            expect_powergood_stable=1,
            expect_rst_cold_stable_ref_clk_n=0,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        self._waits.append(
            (
                "cold_assert",
                f"{self.ASSERT_BOUND_REF_CYCLES}ref_cyc(enforced-by=smc_reset_seq_base.py)",
                f"matched after {item.wait_ref_cycles}ref_cyc",
            )
        )
        await self._send(SmcResetOp.COLD_RST_HI)
        item = await self._wait_released("cold release")
        self._waits.append(
            (
                "cold_release",
                f"{self.RELEASE_BOUND_REF_CYCLES}ref_cyc(enforced-by=smc_reset_seq_base.py)",
                f"matched after {item.wait_ref_cycles}ref_cyc",
            )
        )
        await self._sense_wait("post_cold")

    async def _primary_reset(self) -> None:
        await self._send(SmcResetOp.COOL_RST_LO)
        item = await self._wait_state(
            "primary assert",
            expect_powergood_stable=1,
            expect_rst_cold_stable_ref_clk_n=1,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        self._waits.append(
            (
                "primary_assert",
                f"{self.ASSERT_BOUND_REF_CYCLES}ref_cyc(enforced-by=smc_reset_seq_base.py)",
                f"matched after {item.wait_ref_cycles}ref_cyc",
            )
        )
        await self._send(SmcResetOp.COOL_RST_HI)
        item = await self._wait_released("primary release")
        self._waits.append(
            (
                "primary_release",
                f"{self.RELEASE_BOUND_REF_CYCLES}ref_cyc(enforced-by=smc_reset_seq_base.py)",
                f"matched after {item.wait_ref_cycles}ref_cyc",
            )
        )
        await self._sense_wait("post_primary")

    async def _warm_reset(self) -> None:
        await self.csr_write("SS_WARM_ASSERT", SS_WARM, SS_WARM_RESET_VALUE & ~0x1)
        asserted = await self.csr_read("SS_WARM_ASSERTED", SS_WARM)
        assert asserted & 0x1 == 0, f"SS_WARM_RESET_N bit 0 still 1: 0x{asserted:x}"
        await self.csr_write("SS_WARM_RELEASE", SS_WARM, SS_WARM_RESET_VALUE)
        released = await self.csr_read("SS_WARM_RELEASED", SS_WARM)
        assert released & 0x1 == 1, f"SS_WARM_RESET_N bit 0 still 0: 0x{released:x}"

    async def _pulse_pin(self) -> int:
        clk = cocotb.top.clk_smc_i
        await RisingEdge(clk)
        self._pins(1, 0)
        start = int(get_sim_time("ps"))
        await RisingEdge(clk)
        self._pins(0, 0)
        return start

    async def _set_both_bits(self, label: str) -> None:
        self._pins(1, 1)
        await self._poll(label, lambda w: w == IDLE_BOTH)
        self._pins(0, 0)

    async def body(self) -> None:
        dut = cocotb.top
        axi_bound = self.env.cfg.axi_timeout_ns
        for pin in ("tb_mem_repair_abort", "tb_mbist_abort", "s_axi_arvalid", "s_axi_arready"):
            assert hasattr(dut, pin), f"{pin} is not a signal of the testbench top"
        assert DFX_MEM_REPAIR_ABORT == 1 << 2, f"repair abort mask 0x{DFX_MEM_REPAIR_ABORT:x}"
        assert DFX_MBIST_ABORT == 1 << 12, f"mbist abort mask 0x{DFX_MBIST_ABORT:x}"

        # S1
        await self._sense_wait("bringup")
        self._pins(0, 0)
        base = await self._read("S1_BASELINE", expected=DFX_STATUS_IDLE)
        assert base == DFX_STATUS_IDLE, f"baseline 0x{base:x} want 0x{DFX_STATUS_IDLE:x}"
        self._stamp("S1")

        # S2
        await self._write("S2_ONES_CLEAN", ALL_ONES_64, None)
        clean = await self._read("S2_AFTER_ONES", expected=DFX_STATUS_IDLE)
        assert clean == DFX_STATUS_IDLE, f"after all-ones write 0x{clean:x}"
        self._stamp("S2")
        self._chk(
            "CHK-DFX-STATUS-RO-CLEAN",
            f"STATUS_SMU=0x{clean:x} (DFX_STATUS_IDLE) after an 8-byte all-ones write on the "
            "clean status",
        )

        # S3
        self._pins(0, 1)
        mbist, mbist_polls = await self._poll("S3_MBIST", lambda w: w == IDLE_MBIST)
        assert mbist & DFX_MEM_REPAIR_ABORT == 0, f"bit 2 set with mbist alone: 0x{mbist:x}"
        self._pins(1, 1)
        both, both_polls = await self._poll("S3_BOTH", lambda w: w == IDLE_BOTH)
        self._stamp("S3")
        self._chk(
            "CHK-DFX-STATUS-MBIST-ALONE",
            f"tb_mbist_abort alone: STATUS_SMU=0x{mbist:x} (idle + bit 12, bit 2 = 0) after "
            f"{mbist_polls} poll(s), bound {MAX_STATUS_POLLS}",
        )
        self._chk(
            "CHK-DFX-STATUS-STAGGER",
            f"STATUS_SMU 0x{mbist:x} (idle + bit 12) then 0x{both:x} (idle + bits 12 and 2) "
            f"after {both_polls} poll(s); done-then-success and all-six cells are not drivable "
            "(SF-037)",
        )

        # S4
        self._pins(0, 0)
        word = await self._read("S4_PINS_LOW", expected=IDLE_BOTH)
        reserved = word & ALL_ONES_64 & ~DEFINED_BITS
        assert word == IDLE_BOTH, f"STATUS_SMU 0x{word:x} want 0x{IDLE_BOTH:x}"
        assert reserved == 0, f"reserved bits read 1: 0x{reserved:x} (word 0x{word:x})"
        self._stamp("S4")
        self._chk(
            "CHK-DFX-STATUS-RESERVED",
            f"STATUS_SMU=0x{word:x} with both aborts set and both pins 0; bits 3, 5-7, 9-11 and "
            f"13-63 read 0 (reserved slice 0x{reserved:x}, a 2-state zero cannot fail on X/Z)",
        )

        # S5
        resps = []
        for label, data, strb in (
            ("S5_ZERO", 0, None),
            ("S5_ONES_STRB01", ALL_ONES_64, 0x01),
            ("S5_ONES_STRB10", ALL_ONES_64, 0x10),
        ):
            resps.append((label, await self._write(label, data, strb)))
            held = await self._read(f"{label}_RB", expected=IDLE_BOTH)
            assert held == IDLE_BOTH, f"{label}: STATUS_SMU 0x{held:x} want 0x{IDLE_BOTH:x}"
        self._stamp("S5")
        self._chk(
            "CHK-DFX-STATUS-RO-SET",
            f"STATUS_SMU stayed 0x{IDLE_BOTH:x} (idle + bits 12 and 2) after a zero write and "
            "all-ones writes with strobes 0x01 and 0x10",
        )
        self._chk(
            "CHK-DFX-STATUS-WRITE-RESP",
            "AXI write responses "
            + ", ".join(f"{lbl}={RESP_NAMES.get(r)}" for lbl, r in resps)
            + " (defined response is SF-029; printed, not asserted)",
        )

        # S6
        await self._cold_reset()
        pre = await self._read("S6_AFTER_COLD", expected=DFX_STATUS_IDLE)
        assert pre == DFX_STATUS_IDLE, f"STATUS_SMU 0x{pre:x} after cold reset, want idle"
        start = await self._pulse_pin()
        pulse, p_polls = await self._poll(
            "S6_PULSE", lambda w: w == IDLE_REPAIR, (DFX_STATUS_IDLE, IDLE_REPAIR)
        )
        latency_ps = int(get_sim_time("ps")) - start
        hold = await self._read("S6_PULSE_HOLD", expected=IDLE_REPAIR)
        assert hold == IDLE_REPAIR, f"bit 2 dropped after the pulse: 0x{hold:x}"
        await self._cold_reset()
        pre2 = await self._read("S6_AFTER_COLD2", expected=DFX_STATUS_IDLE)
        assert pre2 == DFX_STATUS_IDLE, f"STATUS_SMU 0x{pre2:x} after cold reset, want idle"
        rd = SmcSysAxiItem("rd_S6_INFLIGHT")
        rd.op = SmcSysAxiOp.READ
        rd.addr = DFX_STATUS_SMU
        rd.length = 8
        reader = cocotb.start_soon(
            _OneShot(rd, "s6_inflight_os").start(self.env.sys_axi_agent.sequencer)
        )
        for cycle in range(1, AR_HANDSHAKE_MAX_CYCLES + 1):
            await FallingEdge(dut.clk_smc_i)
            if int(dut.s_axi_arvalid.value) and int(dut.s_axi_arready.value):
                break
        else:
            raise AssertionError(f"no AR handshake within {AR_HANDSHAKE_MAX_CYCLES} cycles")
        self._waits.append(
            ("ar_handshake", f"{AR_HANDSHAKE_MAX_CYCLES}clk_smc(leaf loop)", f"cycle {cycle}")
        )
        r_pending = not int(dut.s_axi_rvalid.value)
        assert r_pending, "the read data phase had already started when the pulse began"
        start2 = await self._pulse_pin()
        await reader
        self.accesses += 1
        inflight = rd.rdata
        assert inflight in (DFX_STATUS_IDLE, IDLE_REPAIR), f"torn in-flight word 0x{inflight:x}"
        pulse2, p2_polls = await self._poll(
            "S6_PULSE_INFLIGHT", lambda w: w == IDLE_REPAIR, (DFX_STATUS_IDLE, IDLE_REPAIR)
        )
        latency2_ps = int(get_sim_time("ps")) - start2
        hold2 = await self._read("S6_INFLIGHT_HOLD", expected=IDLE_REPAIR)
        assert hold2 == IDLE_REPAIR, f"bit 2 dropped after the in-flight pulse: 0x{hold2:x}"
        self._stamp("S6")
        self._chk(
            "CHK-DFX-STATUS-PULSE",
            f"one-clk_smc pulse on tb_mem_repair_abort: STATUS_SMU 0x{pre:x} -> 0x{pulse:x} "
            f"at poll {p_polls} of {MAX_STATUS_POLLS} ({latency_ps}ps after the pulse start), "
            f"held 0x{hold:x}; pulse started after the AR handshake with R pending: in-flight "
            f"read returned 0x{inflight:x}, then 0x{pulse2:x} at poll {p2_polls} "
            f"({latency2_ps}ps), held 0x{hold2:x}; latency spec is SF-031",
        )

        # S7
        legs = []
        for name, action in (
            ("cold", self._cold_reset),
            ("warm", self._warm_reset),
            ("primary", self._primary_reset),
        ):
            await self._set_both_bits(f"S7_{name}_SET")
            await action()
            after = await self._read(f"S7_{name}_AFTER")
            legs.append(
                f"{name}: bit2 1->{_bit(after, DFX_MEM_REPAIR_ABORT)} "
                f"bit12 1->{_bit(after, DFX_MBIST_ABORT)} word=0x{after:x}"
            )
        self._stamp("S7")
        self._chk(
            "CHK-DFX-STATUS-RESET-CLEARS",
            "; ".join(legs) + " (a bit that reads 0 after a reset was cleared by it; the "
            "clearing reset is SF-030)",
        )

        # S8
        self._pins(1, 0)
        await self._cold_reset()
        held_word = await self._read("S8_AFTER_RESET_HELD")
        self._pins(0, 0)
        self._stamp("S8")
        self._chk(
            "CHK-DFX-STATUS-HIGH-THROUGH-RESET",
            f"tb_mem_repair_abort held 1 through a cold reset: STATUS_SMU=0x{held_word:x}, "
            f"bit 2 {'set' if held_word & DFX_MEM_REPAIR_ABORT else 'clear'} after release "
            "(expected capture is SF-030)",
        )

        # S9
        self._waits.append(("sep_in_access", f"{axi_bound}ns(enforced-by=env cfg)", self._last))
        await RisingEdge(dut.clk_smc_i)
        self._stamp("S9")
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
        assert tuple(steps) == STEPS, f"step order {steps}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing {times}"
        order = [c for c, _ in self._chk_order]
        assert order == [c for c, _ in CHK_ORDER], f"checker order {order}"
        for chk_id, n_stamps in self._chk_order:
            step = dict(CHK_ORDER)[chk_id]
            assert n_stamps == STEPS.index(step) + 1, f"{chk_id} printed before {step}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(FENCE_TERMS),
            ",".join(order),
            ",".join(f"{s}={t}ps" for s, t in self._stamps),
        )
        self.chk_seen.add("CHK-NONVAC")
