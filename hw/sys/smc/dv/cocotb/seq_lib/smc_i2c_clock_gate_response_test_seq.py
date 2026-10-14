# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C window answers while CLOCK_GATE_CONTROL.i2c_cg_en is set, and state kept across it.

Sources: hw/sys/smc/regs/blocks/smc_base_config/smc_base_config.rdl (i2c_cg_en),
hw/sys/smc/doc/clk_rst.adoc, hw/ip/i2c/regs/i2c.rdl, hw/sys/smc/doc/interrupts.adoc.

While the gate is set every read of the I2C window completes with SLVERR and 0xBADCAB1E;
after it is cleared the window answers OKAY and every register and event written before
the gate reads back unchanged. Writes under the gate complete with SLVERR. The answers at gap
and past-extent addresses and the interrupt levels: the specification does not state the
values; they are logged without a compare.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import I2C_CG_EN, reg_reset_word, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import I2C_WRAP_CONTROLLER_MODE, I2C_WRAP_SMBUS_EN
from .smc_i2c_master_target_test_seq import _I2C_H, _i2c_u32
from .smc_i2c_target_smbus_test_seq import _pack_target_id

INSTANCES = (0, 1, 2)
AXI_SLVERR = 2
ERR_SIGNATURE = SmcCsrSeq.ERR_SLAVE_SIGNATURE
TARGET_TIMEOUT_PATTERN = 0x1234
NACK_HANDLER_PATTERN = 0x321
GATE_POLL_CYCLES = 2000
IRQ_POLL_CYCLES = 2000
IRQ_LATER_CYCLES = 256
EXTRA_CYCLES = 3
APERTURE_BYTES = 0x1000
WORD_BYTES = 4
SLAVE_WRITE_PATTERN = 0xA5A5_5A5A
IRQ_INDEX = 1
PERIPHERAL_IRQ_BIT = 24
CPU_IRQ_BIT = 280

STATUS_RESET = reg_reset_word(_I2C_H, "I2C", "STATUS")
CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
WINDOW_BASE = smc_addr("SMC_TOP_SMC_I2C_WRAP_BASE_ADDR")
WINDOW_EXTENT = smc_addr("SMC_TOP_SMC_I2C_WRAP_SIZE")
INSTANCES_END = smc_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TOTAL_SIZE")
CTRL_REGS_BASE = smc_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_BASE_ADDR")

GAP_LOW = WINDOW_BASE + INSTANCES_END
GAP_HIGH = CTRL_REGS_BASE - WORD_BYTES
PAST_FIRST = WINDOW_BASE + WINDOW_EXTENT
PAST_LAST = WINDOW_BASE + APERTURE_BYTES - WORD_BYTES


def _reg(register: str, idx: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_I2C_WRAP_I2C_{register}_BASE_ADDR", idx)


def _wrap_ctrl(idx: int) -> int:
    return smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", idx)


RX_OVERFLOW = _i2c_u32("I2C__INTR_STATE__RX_OVERFLOW_bm")
RX_OVERFLOW_TEST = _i2c_u32("I2C__INTR_TEST__RX_OVERFLOW_bm")
CMD_COMPLETE = _i2c_u32("I2C__INTR_STATE__CMD_COMPLETE_bm")
CMD_COMPLETE_ENABLE = _i2c_u32("I2C__INTR_ENABLE__CMD_COMPLETE_bm")
CMD_COMPLETE_TEST = _i2c_u32("I2C__INTR_TEST__CMD_COMPLETE_bm")
INTR_ENABLE_PATTERN = (
    _i2c_u32("I2C__INTR_ENABLE__SCL_INTERFERENCE_bm")
    | _i2c_u32("I2C__INTR_ENABLE__SDA_INTERFERENCE_bm")
    | _i2c_u32("I2C__INTR_ENABLE__HOST_TIMEOUT_bm")
)

FENCE_STEPS = tuple(f"S{n}" for n in (1, 2, 3, 4, 5, 6, 7, 8, 10, 11))
CHK_STEPS = {
    "CHK-I2C-GATE-READ-SLVERR": ("S2", "S4"),
    "CHK-I2C-GATE-WRITE-SLVERR": ("S5",),
    "CHK-I2C-GATE-GAP-OBS": ("S6",),
    "CHK-I2C-GATE-UNGATE-OKAY": ("S8",),
    "CHK-I2C-GATE-IRQ-OBS": ("S3", "S7"),
    "CHK-I2C-RETAIN-REGS": ("S3", "S8"),
    "CHK-I2C-RETAIN-INTR": ("S3", "S8", "S10"),
    "CHK-I2C-RETAIN-GATED-WRITE-OBS": ("S5", "S11"),
    "CHK-I2C-RETAIN-CYCLES": ("S10",),
}


class smc_i2c_clock_gate_response_test_seq(SmcCsrSeq):
    """Set and clear i2c_cg_en around window accesses and check what the gate answers."""

    def __init__(self, name: str = "smc_i2c_clock_gate_response_test_seq") -> None:
        super().__init__(name)
        self.fence: list[tuple[str, int]] = []
        self.chk_stamps: dict[str, int] = {}
        self.entry: dict[str, int] = {}
        self.target_ids = tuple(_pack_target_id(0x21 + n, 0x7F) for n in INSTANCES)
        self.ctrl_words = (I2C_WRAP_SMBUS_EN, I2C_WRAP_CONTROLLER_MODE)

    @staticmethod
    def _sample(sig, label: str, bit: int = 0) -> int:
        assert sig.value.is_resolvable, f"{label} = {sig.value} is X/Z"
        return (int(sig.value) >> bit) & 1

    def _irq_levels(self) -> tuple[int, int, int]:
        dut = cocotb.top
        return (
            self._sample(dut.tb_i2c_irq, "tb_i2c_irq", IRQ_INDEX),
            self._sample(
                dut.tb_peripheral_interrupts, "tb_peripheral_interrupts", PERIPHERAL_IRQ_BIT
            ),
            self._sample(dut.tb_cpu_interrupts, "tb_cpu_interrupts", CPU_IRQ_BIT),
        )

    def _mark(self, step: str) -> None:
        self.fence.append((step, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, text: str, *args) -> None:
        self.chk_stamps[chk_id] = int(get_sim_time("ps"))
        cocotb.log.info(f"{chk_id}: {text}", *args)

    async def _poll(self, label: str, sig, want: int, cycles: int, bit: int = 0) -> int:
        clk = cocotb.top.clk_smc_i
        last = None
        for n in range(cycles + 1):
            last = self._sample(sig, label, bit)
            if last == want:
                return n
            await RisingEdge(clk)
        raise AssertionError(f"{label} never read {want} in {cycles} clk_smc_i cycles; last {last}")

    async def _set_gate(self, on: bool) -> int:
        word = self.entry["cg"] | I2C_CG_EN if on else self.entry["cg"] & ~I2C_CG_EN
        await self.csr_write("CG_SET" if on else "CG_CLEAR", CLOCK_GATE_CONTROL, word)
        return await self._poll(
            f"tb_i2c_cg_en->{int(on)}", cocotb.top.tb_i2c_cg_en, int(on), GATE_POLL_CYCLES
        )

    async def _observe(self, name: str, addr: int, write: bool = False, data: int = 0):
        item = SmcSysAxiItem(f"{'wr' if write else 'rd'}_{name}")
        item.op = SmcSysAxiOp.WRITE if write else SmcSysAxiOp.READ
        item.addr = addr
        item.wdata = data
        item.allow_error = True
        item.expect_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None and item.resp_code > 1, (
            f"{name} @ 0x{addr:08x}: expected an error response under the gate, "
            f"got resp={item.resp_code} (rdata=0x{item.rdata:x})"
        )
        return item.resp_code, item.rdata

    async def _read_retained(self, tag: str) -> dict[str, int]:
        got = {}
        for n in INSTANCES:
            got[f"TARGET_ID{n}"] = await self.csr_read(f"{tag}_TID{n}", _reg("TARGET_ID", n))
        for n in (0, 1):
            got[f"I2C_CTRL{n}"] = await self.csr_read(f"{tag}_CTRL{n}", _wrap_ctrl(n))
        got["INTR_ENABLE0"] = await self.csr_read(f"{tag}_IE0", _reg("INTR_ENABLE", 0))
        got["INTR_STATE0"] = await self.csr_read(f"{tag}_IS0", _reg("INTR_STATE", 0))
        return got

    def _expect_retained(self, tag: str, got: dict[str, int]) -> None:
        want = {f"TARGET_ID{n}": self.target_ids[n] for n in INSTANCES}
        want["I2C_CTRL0"] = self.ctrl_words[0]
        want["I2C_CTRL1"] = self.ctrl_words[1]
        want["INTR_ENABLE0"] = INTR_ENABLE_PATTERN
        for key, value in want.items():
            assert got[key] == value, (
                f"{tag}: {key} reads 0x{got[key]:08x} after the gate cycle, "
                f"0x{value:08x} was written before it"
            )

    async def body(self) -> None:
        dut = cocotb.top
        for probe in (
            "tb_i2c_cg_en",
            "tb_i2c_irq",
            "tb_peripheral_interrupts",
            "tb_cpu_interrupts",
        ):
            assert hasattr(dut, probe), f"{probe} is not exported by tb_top"

        # S1
        self.entry["cg"] = await self.csr_read("CG_ENTRY", CLOCK_GATE_CONTROL)
        for n in INSTANCES:
            self.entry[f"tid{n}"] = await self.csr_read(f"TID_ENTRY{n}", _reg("TARGET_ID", n))
            self.entry[f"ctrl{n}"] = await self.csr_read(f"CTRL_ENTRY{n}", _wrap_ctrl(n))
            self.entry[f"ie{n}"] = await self.csr_read(f"IE_ENTRY{n}", _reg("INTR_ENABLE", n))
            self.entry[f"is{n}"] = await self.csr_read(f"IS_ENTRY{n}", _reg("INTR_STATE", n))
        self.entry["ttc2"] = await self.csr_read("TTC_ENTRY2", _reg("TARGET_TIMEOUT_CTRL", 2))
        probe0 = self._sample(dut.tb_i2c_cg_en, "tb_i2c_cg_en")
        assert probe0 == 0, f"tb_i2c_cg_en = {probe0} at entry"
        self._mark("S1")

        # S2
        cg = await self.csr_read("CG_RESET_BIT", CLOCK_GATE_CONTROL)
        probe_s2 = self._sample(dut.tb_i2c_cg_en, "tb_i2c_cg_en")
        assert not cg & I2C_CG_EN and probe_s2 == 0, (
            f"CLOCK_GATE_CONTROL=0x{cg:08x} tb_i2c_cg_en={probe_s2} before any write; "
            f"i2c_cg_en resets to 0"
        )
        self._mark("S2")

        # S3
        for n in INSTANCES:
            await self.csr_write(f"TID_SET{n}", _reg("TARGET_ID", n), self.target_ids[n])
        for n, word in enumerate(self.ctrl_words):
            await self.csr_write(f"CTRL_SET{n}", _wrap_ctrl(n), word)
        await self.csr_write("IE0_SET", _reg("INTR_ENABLE", 0), INTR_ENABLE_PATTERN)
        await self.csr_write("IT0_RXOVF", _reg("INTR_TEST", 0), RX_OVERFLOW_TEST)
        is0 = await self.csr_read("IS0_FORCED", _reg("INTR_STATE", 0))
        assert is0 & RX_OVERFLOW, f"INTR_STATE[0]=0x{is0:08x}: RX_OVERFLOW not forced"
        await self.csr_write("IE1_SET", _reg("INTR_ENABLE", 1), CMD_COMPLETE_ENABLE)
        await self.csr_write("IT1_CMDC", _reg("INTR_TEST", 1), CMD_COMPLETE_TEST)
        pre_cycles = await self._poll(
            "tb_i2c_irq[1]->1", dut.tb_i2c_irq, 1, IRQ_POLL_CYCLES, IRQ_INDEX
        )
        self._mark("S3")

        # S4
        gate_cycles = await self._set_gate(True)
        reads = []
        for n in INSTANCES:
            await self.csr_read_err_signature(
                f"GATED_STATUS{n}", _reg("STATUS", n), resp=AXI_SLVERR
            )
            reads.append(f"STATUS[{n}]")
        for n in INSTANCES:
            await self.csr_read_err_signature(f"GATED_CTRL{n}", _wrap_ctrl(n), resp=AXI_SLVERR)
            reads.append(f"I2C_CTRL[{n}]")
        self._mark("S4")
        self._chk(
            "CHK-I2C-GATE-READ-SLVERR",
            "i2c_cg_en read 0 and tb_i2c_cg_en=%d before the write; tb_i2c_cg_en read 1 after %d "
            "cycles; %s each completed resp=%d rdata=0x%08x",
            probe_s2,
            gate_cycles,
            ", ".join(reads),
            AXI_SLVERR,
            ERR_SIGNATURE,
        )

        # S5
        nack_resp = await self.csr_write_expect_error(
            "GATED_NACK_TIMEOUT",
            _reg("HOST_NACK_HANDLER_TIMEOUT", 0),
            NACK_HANDLER_PATTERN,
            resp=AXI_SLVERR,
        )
        ctrl2_resp = await self.csr_write_expect_error(
            "GATED_CTRL2", _wrap_ctrl(2), I2C_WRAP_SMBUS_EN, resp=AXI_SLVERR
        )
        self._mark("S5")
        self._chk(
            "CHK-I2C-GATE-WRITE-SLVERR",
            "HOST_NACK_HANDLER_TIMEOUT[0]_resp=%d I2C_CTRL[2]_resp=%d (both SLVERR, clk_rst.adoc)",
            nack_resp,
            ctrl2_resp,
        )

        # S6
        gap = []
        for label, addr in (
            ("gap_0x600", GAP_LOW),
            ("gap_0xdfc", GAP_HIGH),
            ("past_first", PAST_FIRST),
            ("past_last", PAST_LAST),
        ):
            resp, rdata = await self._observe(f"GAP_{label}", addr)
            gap.append(f"rd_{label}_resp={resp} rd_{label}_rdata=0x{rdata:08x}")
        for label, addr in (("gap_0x600", GAP_LOW), ("past_last", PAST_LAST)):
            resp, _ = await self._observe(f"GAPW_{label}", addr, True, SLAVE_WRITE_PATTERN)
            gap.append(f"wr_{label}_resp={resp}")
        self._mark("S6")
        self._chk(
            "CHK-I2C-GATE-GAP-OBS", "%s (observation, not specified, measured)", " ".join(gap)
        )

        # S7
        irq_now = self._irq_levels()
        await ClockCycles(dut.clk_smc_i, IRQ_LATER_CYCLES)
        irq_later = self._irq_levels()
        self._mark("S7")
        self._chk(
            "CHK-I2C-GATE-IRQ-OBS",
            "precondition tb_i2c_irq[1]=1 after %d cycles; gated tb_i2c_irq[1]=%d "
            "tb_peripheral_interrupts[24]=%d tb_cpu_interrupts[280]=%d; after %d cycles "
            "tb_i2c_irq[1]=%d tb_peripheral_interrupts[24]=%d tb_cpu_interrupts[280]=%d "
            "(observation, not specified, measured)",
            pre_cycles,
            *irq_now,
            IRQ_LATER_CYCLES,
            *irq_later,
        )

        # S8
        ungate_cycles = await self._set_gate(False)
        for n in INSTANCES:
            status = await self.csr_read(f"STATUS{n}", _reg("STATUS", n))
            assert status == STATUS_RESET, (
                f"STATUS[{n}] reads 0x{status:08x} after ungating, expected 0x{STATUS_RESET:03x}"
            )
        await self.csr_write("TTC2_SET", _reg("TARGET_TIMEOUT_CTRL", 2), TARGET_TIMEOUT_PATTERN)
        ttc = await self.csr_read("TTC2_RB", _reg("TARGET_TIMEOUT_CTRL", 2))
        assert ttc == TARGET_TIMEOUT_PATTERN, (
            f"TARGET_TIMEOUT_CTRL[2] reads 0x{ttc:08x}, wrote 0x{TARGET_TIMEOUT_PATTERN:04x}"
        )
        retained = await self._read_retained("AFTER_GATE")
        self._expect_retained("first gate cycle", retained)
        assert retained["INTR_STATE0"] & RX_OVERFLOW, (
            f"INTR_STATE[0]=0x{retained['INTR_STATE0']:08x}: RX_OVERFLOW lost across the gate"
        )
        irq_s8 = self._irq_levels()[0]
        self._mark("S8")
        self._chk(
            "CHK-I2C-GATE-UNGATE-OKAY",
            "tb_i2c_cg_en read 0 after %d cycles; STATUS[0..2]=0x%03x OKAY; "
            "TARGET_TIMEOUT_CTRL[2] wrote 0x%04x read 0x%04x; tb_i2c_irq[1]=%d",
            ungate_cycles,
            STATUS_RESET,
            TARGET_TIMEOUT_PATTERN,
            ttc,
            irq_s8,
        )
        self._chk(
            "CHK-I2C-RETAIN-REGS",
            "TARGET_ID[0..2]=0x%08x/0x%08x/0x%08x I2C_CTRL[0]=0x%03x I2C_CTRL[1]=0x%03x "
            "read back equal to the words written before the gate",
            retained["TARGET_ID0"],
            retained["TARGET_ID1"],
            retained["TARGET_ID2"],
            retained["I2C_CTRL0"],
            retained["I2C_CTRL1"],
        )

        # S10
        for cycle in range(EXTRA_CYCLES):
            await self._set_gate(True)
            await self._set_gate(False)
            got = await self._read_retained(f"CYCLE{cycle}")
            self._expect_retained(f"extra gate cycle {cycle + 1}", got)
            assert got["INTR_STATE0"] & RX_OVERFLOW, (
                f"INTR_STATE[0]=0x{got['INTR_STATE0']:08x} after extra gate cycle {cycle + 1}"
            )
        await self.csr_write("IS0_W1C", _reg("INTR_STATE", 0), RX_OVERFLOW)
        cleared = await self.csr_read("IS0_CLEARED", _reg("INTR_STATE", 0))
        assert not cleared & RX_OVERFLOW, f"INTR_STATE[0]=0x{cleared:08x}: W1C left RX_OVERFLOW"
        self._mark("S10")
        self._chk(
            "CHK-I2C-RETAIN-INTR",
            "INTR_ENABLE[0]=0x%08x equal after the gate cycle; set: INTR_TEST[0] RX_OVERFLOW; "
            "observed: INTR_STATE[0]=0x%08x bit3=1 after the gate was set and cleared; "
            "cleared: INTR_STATE[0] W1C bit3; checked_cleared: INTR_STATE[0]=0x%08x bit3=0",
            retained["INTR_ENABLE0"],
            retained["INTR_STATE0"],
            cleared,
        )
        self._chk(
            "CHK-I2C-RETAIN-CYCLES",
            "%d further set/clear cycles each read back TARGET_ID[0..2], I2C_CTRL[0..1] and "
            "INTR_ENABLE[0] equal to the values written before the gate",
            EXTRA_CYCLES,
        )

        # S11
        nack_rb = await self.csr_read("NACK_TIMEOUT_AFTER", _reg("HOST_NACK_HANDLER_TIMEOUT", 0))
        ctrl2_rb = await self.csr_read("CTRL2_AFTER", _wrap_ctrl(2))
        await self.csr_restore("NACK_TIMEOUT", _reg("HOST_NACK_HANDLER_TIMEOUT", 0), 0)
        await self.csr_restore("CTRL2", _wrap_ctrl(2), 0)
        await self.csr_restore("TTC2", _reg("TARGET_TIMEOUT_CTRL", 2), self.entry["ttc2"])
        await self.csr_write("IS1_W1C", _reg("INTR_STATE", 1), CMD_COMPLETE)
        for n in INSTANCES:
            await self.csr_restore(f"TID{n}", _reg("TARGET_ID", n), self.entry[f"tid{n}"])
            await self.csr_restore(f"CTRL{n}", _wrap_ctrl(n), self.entry[f"ctrl{n}"])
            await self.csr_restore(f"IE{n}", _reg("INTR_ENABLE", n), self.entry[f"ie{n}"])
        await self.csr_restore("CG", CLOCK_GATE_CONTROL, self.entry["cg"])
        self._mark("S11")
        self._chk(
            "CHK-I2C-RETAIN-GATED-WRITE-OBS",
            "HOST_NACK_HANDLER_TIMEOUT[0]=0x%08x %s; I2C_CTRL[2]=0x%08x %s "
            "(observation, not specified, measured)",
            nack_rb,
            "landed" if nack_rb == NACK_HANDLER_PATTERN else "dropped",
            ctrl2_rb,
            "landed" if ctrl2_rb == I2C_WRAP_SMBUS_EN else "dropped",
        )

        self._finish_fence()

    def _finish_fence(self) -> None:
        order = [step for step, _ in self.fence]
        assert order == list(FENCE_STEPS), f"NONVAC fence order {order}, expected {FENCE_STEPS}"
        stamps = [ps for _, ps in self.fence]
        assert all(a < b for a, b in zip(stamps, stamps[1:])), (
            f"fence stamps not increasing {stamps}"
        )
        by_step = dict(self.fence)
        for chk_id, steps in CHK_STEPS.items():
            assert chk_id in self.chk_stamps, f"{chk_id} was not printed"
            assert self.chk_stamps[chk_id] >= max(by_step[s] for s in steps), (
                f"{chk_id} printed before its step {steps} completed"
            )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s ps",
            " < ".join(order),
            ",".join(CHK_STEPS),
            stamps,
        )
