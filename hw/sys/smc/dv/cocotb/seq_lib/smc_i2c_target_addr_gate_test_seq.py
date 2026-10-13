# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 target address gate: ENABLETARGET, TARGET_ID match, non-match and role select.

Contract SMC_I2C_TARGET_015, anchor smc_i2c_target_addr_gate_test.
Scenarios: TGT-ROLE-SELECT.S1, S2, S4, S5, S6, TGT-ADDR-MATCH.S1, S2, S4, S5, S6,
TGT-ACQ-REPSTART.S3, TGT-ACQ-WRITE.S3.
Sources: hw/ip/i2c/regs/i2c.rdl (CTRL, TARGET_ID, ACQDATA, STATUS, FIFO_CTRL).

The bench controller on the I2C0 pads sends START and a 7-bit address to the target; the ACK bit
it reads and the ACQ FIFO entries software pops are the evidence. Every compare uses mask 0x7F
or 0x00. The STOP entry sequence after an address ACK (SF-021, SF-029) and ENABLETARGET cleared
or ACQRST written mid-transfer (SF-027) are measured and logged, not compared.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_ACQ_SIGNAL_NONE,
    I2C_ACQ_SIGNAL_RESTART,
    I2C_ACQ_SIGNAL_START,
    I2C_ACQ_SIGNAL_STOP,
    I2C_ACQDATA_ABYTE,
    I2C_ACQDATA_SIGNAL,
    I2C_ACQDATA_SIGNAL_BP,
    I2C_CTRL_ACQ_START_STOP_EN,
    I2C_CTRL_ENABLEHOST,
    I2C_CTRL_ENABLETARGET,
    I2C_FIFO_CTRL_ACQRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_STATUS_ACQEMPTY,
    I2C_STATUS_TARGETIDLE,
    I2C_STATUS_TXEMPTY,
    I2C_TARGET_FIFO_STATUS_ACQLVL_BM,
    I2C_TARGET_FIFO_STATUS_ACQLVL_BP,
    I2C_WRAP_CTRL_TARGET,
)
from .smc_i2c_master_target_test_seq import _i2c_u32
from .smc_i2c_protocol_vip import SmcI2cMasterVip
from .smc_i2c_slot_utils import drive_to_slot, release_bus
from .smc_i2c_target_smbus_test_seq import (
    _pack_target_id,
    _pack_timing0,
    _pack_timing1,
    _pack_timing2,
    _pack_timing3,
    _pack_timing4,
)

I2C0 = 0
ADDR0 = 0x23
ADDR1 = 0x35
ADDR_OTHER_A = 0x2A
ADDR_OTHER_B = 0x3C
VIP_SPEED = 2_000_000

INTR_UNEXP_STOP = _i2c_u32("I2C__INTR_STATE__UNEXP_STOP_bm")

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
_REGS = {
    "wrap": "SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR",
    "ctrl": "SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR",
    "status": "SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR",
    "fifo_ctrl": "SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR",
    "target_id": "SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ID_BASE_ADDR",
    "txdata": "SMC_TOP_SMC_I2C_WRAP_I2C_TXDATA_BASE_ADDR",
    "acqdata": "SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR",
    "fifo_status": "SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR",
    "intr_state": "SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR",
    "timing0": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING0_BASE_ADDR",
    "timing1": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING1_BASE_ADDR",
    "timing2": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING2_BASE_ADDR",
    "timing3": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING3_BASE_ADDR",
    "timing4": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING4_BASE_ADDR",
}
R = {key: smc_indexed_addr(sym, I2C0) for key, sym in _REGS.items()}

CTRL_TARGET = I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN
CTRL_HYBRID = I2C_CTRL_ENABLEHOST | CTRL_TARGET

ACQ_SETTLE_ROUNDS = 20
ACQ_SETTLE_GAP = 100
FLAT_READS = 5
FLAT_GAP = 100
IDLE_ROUNDS = 400
IDLE_GAP = 100
BUS_RELEASE_POLLS = 2000
BUS_RELEASE_STEP = 4
BUS_SAMPLE_CYCLES = 200

FENCE_ORDER = [f"S{n}" for n in range(1, 11)]
CHECKER_AFTER = {
    "CHK-I2C-TGT-GATE-PAIR0": "S2",
    "CHK-I2C-TGT-GATE-PAIR1": "S3",
    "CHK-I2C-TGT-GATE-NONMATCH": "S4",
    "CHK-I2C-TGT-GATE-MASKZERO": "S5",
    "CHK-I2C-TGT-GATE-REWRITE": "S6",
    "CHK-I2C-TGT-ROLE-GATE": "S8",
    "CHK-I2C-TGT-ADDR-ONLY": "S9",
    "CHK-I2C-TGT-RESTART-ADDRESS": "S9",
    "CHK-I2C-TGT-ROLE-MIDTRANSFER-LOG": "S10",
    "CHK-I2C-TGT-ROLE-MIDTRANSFER-RECOVER": "S10",
    "CHK-TIMEOUT-PATHS": "S10",
}

Entry = tuple[int, int]


def _fmt(entries: list[Entry]) -> str:
    return "[" + ", ".join(f"({s:#x},{b:#04x})" for s, b in entries) + "]"


class smc_i2c_target_addr_gate_test_seq(SmcCsrSeq):
    """Address the I2C0 target from the bench controller under changing CTRL and TARGET_ID."""

    def __init__(self, name: str = "smc_i2c_target_addr_gate_test_seq") -> None:
        super().__init__(name)
        self.stamps: list[tuple[str, int]] = []
        self.chk_lines: list[tuple[str, str, int]] = []
        self.waits: list[tuple[str, str, str]] = []
        self.vips: list[SmcI2cMasterVip] = []
        self.s2_ack = -1

    # ------------------------------------------------------------ plumbing --
    def _stamp(self, term: str) -> None:
        self.stamps.append((term, int(get_sim_time("ps"))))
        cocotb.log.info("FENCE %s @ %dps", term, self.stamps[-1][1])

    def _chk(self, name: str, line: str) -> None:
        self.chk_lines.append((name, line, len(self.stamps)))

    @staticmethod
    async def _cycles(count: int) -> None:
        await ClockCycles(cocotb.top.clk_smc_i, count)

    @staticmethod
    def _probe(name: str) -> int:
        value = getattr(cocotb.top, name).value
        assert value.is_resolvable, f"{name} sampled X/Z ({value})"
        return int(value)

    def _pad_levels(self) -> str:
        names = ("scl", "sda", "scl_dut_low", "sda_dut_low")
        return " ".join(f"{n}={self._probe(f'tb_i2c0_{n}')}" for n in names)

    def _vip(self) -> SmcI2cMasterVip:
        vip = SmcI2cMasterVip(speed=VIP_SPEED, name=f"smc_i2c0_addr_gate_master{len(self.vips)}")
        self.vips.append(vip)
        return vip

    async def _diag(self) -> str:
        status = await self.csr_read("DIAG_STATUS", R["status"])
        fifo = await self.csr_read("DIAG_FIFO_STATUS", R["fifo_status"])
        return f"STATUS=0x{status:08x} ACQLVL={self._level(fifo)} {self._pad_levels()}"

    @staticmethod
    def _level(fifo_status: int) -> int:
        return (fifo_status & I2C_TARGET_FIFO_STATUS_ACQLVL_BM) >> I2C_TARGET_FIFO_STATUS_ACQLVL_BP

    async def _poll(self, name: str, rounds: int, gap: int, probe) -> None:
        """Run ``probe`` up to ``rounds`` times ``gap`` cycles apart; expiry fails the leaf."""
        bound = f"{rounds}x{gap}cyc clk_smc_i"
        state = "never sampled"
        for _ in range(rounds):
            done, state = await probe()
            if done:
                self.waits.append((name, bound, state))
                return
            await self._cycles(gap)
        self.waits.append((name, bound, f"EXPIRED {state}"))
        raise AssertionError(
            f"{name}: not satisfied within {bound}; last {state}; {await self._diag()}"
        )

    async def _wait_released(self, name: str) -> None:
        async def probe() -> tuple[bool, str]:
            scl = self._probe("tb_i2c0_scl")
            sda = self._probe("tb_i2c0_sda")
            return (scl, sda) == (1, 1), f"scl={scl} sda={sda}"

        await self._poll(name, BUS_RELEASE_POLLS, BUS_RELEASE_STEP, probe)

    async def _acq_reset(self, label: str) -> None:
        await self.csr_write(f"{label}_ACQRST", R["fifo_ctrl"], I2C_FIFO_CTRL_ACQRST)

    async def _fifo_reset(self, label: str) -> None:
        await self.csr_write(
            f"{label}_FIFO_RST", R["fifo_ctrl"], I2C_FIFO_CTRL_ACQRST | I2C_FIFO_CTRL_TXRST
        )

    async def _set_target_id(self, label: str, a0: int, m0: int, a1: int, m1: int) -> None:
        await self.csr_write(label, R["target_id"], _pack_target_id(a0, m0, a1, m1))

    async def _settle_acq(self, name: str, allow_zero: bool = False) -> int:
        """ACQLVL reads ``ACQ_SETTLE_GAP`` cycles apart until two agree (and are non-zero)."""
        bound = f"{ACQ_SETTLE_ROUNDS}x{ACQ_SETTLE_GAP}cyc clk_smc_i"
        prev = -1
        state = "never sampled"
        for _ in range(ACQ_SETTLE_ROUNDS):
            fifo = await self.csr_read(f"{name}_ACQLVL", R["fifo_status"])
            level = self._level(fifo)
            state = f"acqlvl={level} previous={prev}"
            if level == prev and (level != 0 or allow_zero):
                self.waits.append((name, bound, state))
                return level
            prev = level
            await self._cycles(ACQ_SETTLE_GAP)
        self.waits.append((name, bound, f"EXPIRED {state}"))
        raise AssertionError(
            f"{name}: ACQLVL did not settle within {bound}; last {state}; {await self._diag()}"
        )

    async def _pop(self, label: str, level: int) -> list[Entry]:
        entries: list[Entry] = []
        for i in range(level):
            word = await self.csr_read(f"{label}_ACQDATA{i}", R["acqdata"])
            signal = (word & I2C_ACQDATA_SIGNAL) >> I2C_ACQDATA_SIGNAL_BP
            entries.append((signal, word & I2C_ACQDATA_ABYTE))
        return entries

    async def _collect(self, name: str, allow_zero: bool = False) -> list[Entry]:
        level = await self._settle_acq(name, allow_zero)
        return await self._pop(name, level)

    async def _flat_acq(self, label: str) -> list[int]:
        """``FLAT_READS`` ACQLVL reads ``FLAT_GAP`` cycles apart; returns the levels."""
        levels = []
        for i in range(FLAT_READS):
            await self._cycles(FLAT_GAP)
            fifo = await self.csr_read(f"{label}_FLAT{i}", R["fifo_status"])
            levels.append(self._level(fifo))
        status = await self.csr_read(f"{label}_FLAT_STATUS", R["status"])
        levels.append(int(bool(status & I2C_STATUS_ACQEMPTY)))
        return levels

    # --------------------------------------------------------- bus traffic --
    @staticmethod
    async def _write(vip: SmcI2cMasterVip, addr7: int, data: list[int]) -> list[int]:
        """START, address (write), payload while ACKed, STOP; returns every ACK bit."""
        await vip.send_start()
        acks = [await vip.send_byte((addr7 & 0x7F) << 1)]
        if acks[0] == 0:
            for byte in data:
                acks.append(await vip.send_byte(byte))
                if acks[-1]:
                    break
        await vip.send_stop()
        return acks

    @staticmethod
    async def _read(vip: SmcI2cMasterVip, addr7: int) -> tuple[int, int | None]:
        """START, address (read), one byte with NACK, STOP; returns (address ACK, byte)."""
        await vip.send_start()
        ack = await vip.send_byte(((addr7 & 0x7F) << 1) | 1)
        byte = await vip.recv_byte(ack=False) if ack == 0 else None
        await vip.send_stop()
        return ack, byte

    async def _pair_leg(
        self, label: str, addr7: int, wdata: int, txbyte: int
    ) -> tuple[list[int], list[Entry], int, int | None, list[Entry]]:
        vip = self._vip()
        await self._fifo_reset(f"{label}_W")
        acks = await self._write(vip, addr7, [wdata])
        wentries = await self._collect(f"{label}_write_acq")
        await self._fifo_reset(f"{label}_R")
        await self.csr_write(f"{label}_TXDATA", R["txdata"], txbyte)
        rack, byte = await self._read(vip, addr7)
        rentries = await self._collect(f"{label}_read_acq")
        wr = (addr7 & 0x7F) << 1
        assert acks == [0, 0], f"{label}: write to 0x{addr7:02x} ACK bits {acks}, expected [0, 0]"
        assert len(wentries) == 3, f"{label}: write entries {_fmt(wentries)}, expected three"
        assert wentries[0] == (I2C_ACQ_SIGNAL_START, wr), f"{label}: write {_fmt(wentries)}"
        assert wentries[1] == (I2C_ACQ_SIGNAL_NONE, wdata), f"{label}: write {_fmt(wentries)}"
        assert wentries[2][0] == I2C_ACQ_SIGNAL_STOP, f"{label}: write {_fmt(wentries)}"
        assert rack == 0, f"{label}: read address 0x{wr | 1:02x} NACKed"
        assert byte == txbyte, f"{label}: read returned {byte}, TXDATA held {txbyte:#04x}"
        assert rentries and rentries[0] == (I2C_ACQ_SIGNAL_START, wr | 1), (
            f"{label}: first read entry {_fmt(rentries)}, expected (0x1,{wr | 1:#04x})"
        )
        return acks, wentries, rack, byte, rentries

    # ---------------------------------------------------------------- steps --
    async def _s1_setup(self) -> None:
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self.arm_i2c_gpio_lsio(I2C0, "I2C0_ADDR_GATE")
        await self.csr_write("I2C0_WRAP_TARGET", R["wrap"], I2C_WRAP_CTRL_TARGET)
        await self._wait_released("bus_released")
        await self.csr_write("I2C0_TIMING0", R["timing0"], _pack_timing0(0x1A, 0x32))
        await self.csr_write("I2C0_TIMING1", R["timing1"], _pack_timing1(2, 2))
        await self.csr_write("I2C0_TIMING2", R["timing2"], _pack_timing2(5, 4))
        await self.csr_write("I2C0_TIMING3", R["timing3"], _pack_timing3(2, 5))
        await self.csr_write("I2C0_TIMING4", R["timing4"], _pack_timing4(4, 5))
        await self._fifo_reset("I2C0")
        await self._set_target_id("I2C0_TARGET_ID", ADDR0, 0x7F, ADDR1, 0x7F)
        await self.csr_write("I2C0_CTRL_TARGET", R["ctrl"], CTRL_TARGET)
        status = await self.csr_read("S1_STATUS", R["status"])
        assert status & I2C_STATUS_ACQEMPTY, f"S1: STATUS.ACQEMPTY clear (0x{status:08x})"
        assert status & I2C_STATUS_TXEMPTY, f"S1: STATUS.TXEMPTY clear (0x{status:08x})"
        levels = self._pad_levels()
        assert self._probe("tb_i2c0_scl") == 1 and self._probe("tb_i2c0_sda") == 1, levels
        assert self._probe("tb_i2c0_sda_dut_low") == 0, f"S1: the DUT pulls SDA low; {levels}"
        cocotb.log.info("S1: instance 0 target enabled; STATUS=0x%08x %s", status, levels)
        self._stamp("S1")

    async def _s2_pair0(self) -> None:
        acks, went, rack, byte, rent = await self._pair_leg("S2", ADDR0, 0x11, 0x6E)
        self.s2_ack = acks[0]
        self._stamp("S2")
        self._chk(
            "CHK-I2C-TGT-GATE-PAIR0",
            f"ENABLETARGET=1: ACK bits 0x46={acks[0]} 0x47={rack}; write entries {_fmt(went)}; "
            f"read byte {byte:#04x}; read entries {_fmt(rent)}",
        )

    async def _s3_pair1(self) -> None:
        acks, went, rack, byte, rent = await self._pair_leg("S3", ADDR1, 0x12, 0x6F)
        vip = self._vip()
        await self._acq_reset("S3_P0")
        p0 = await self._write(vip, ADDR0, [])
        p0_entries = await self._collect("s3_pair0_acq")
        assert p0 == [0], f"S3: pair 0 address 0x46 ACK bits {p0}"
        assert p0_entries and p0_entries[0] == (I2C_ACQ_SIGNAL_START, 0x46), (
            f"S3: pair 0 entries {_fmt(p0_entries)}"
        )
        self._stamp("S3")
        self._chk(
            "CHK-I2C-TGT-GATE-PAIR1",
            f"pair 1=0x35 mask 0x7F: ACK bits 0x6A={acks[0]} 0x6B={rack}; write entries "
            f"{_fmt(went)}; read byte {byte:#04x}; read entries {_fmt(rent)}; pair 0 0x46 ACK "
            f"bit {p0[0]} entries {_fmt(p0_entries)}",
        )

    async def _probe_addr(self, label: str, vip: SmcI2cMasterVip, addr7: int) -> tuple[int, str]:
        """Address-only write; ACKed addresses leave entries that are drained and logged."""
        await self._acq_reset(label)
        acks = await self._write(vip, addr7, [])
        ack = acks[0]
        if ack == 0:
            entries = await self._collect(f"{label.lower()}_acq")
            await self._acq_reset(f"{label}_DRAIN")
            return ack, f"ack={ack} acqlvl={len(entries)} entries {_fmt(entries)}"
        levels = await self._flat_acq(label)
        assert levels[:FLAT_READS] == [0] * FLAT_READS and levels[FLAT_READS] == 1, (
            f"{label}: NACKed address 0x{addr7:02x} left ACQLVL {levels[:FLAT_READS]} "
            f"ACQEMPTY {levels[FLAT_READS]}"
        )
        return ack, f"ack={ack} acqlvl={levels[:FLAT_READS]} acqempty={levels[FLAT_READS]}"

    async def _s4_nonmatch(self) -> None:
        vip = self._vip()
        parts = []
        for addr7 in (ADDR_OTHER_A, ADDR_OTHER_B):
            ack, text = await self._probe_addr(f"S4_{addr7:02X}", vip, addr7)
            assert ack == 1, f"S4: non-matching address 0x{addr7:02x} ACKed ({text})"
            parts.append(f"0x{addr7:02x} {text}")
        self._stamp("S4")
        self._chk(
            "CHK-I2C-TGT-GATE-NONMATCH",
            f"{'; '.join(parts)}; positive control: 0x23 ACK bit {self.s2_ack} in S2",
        )

    async def _s5_masks(self) -> None:
        vip = self._vip()
        legs = (
            ("a", 0, 0x7F, (1, 0)),
            ("b", 0x7F, 0, (0, 1)),
            ("c", 0, 0, (1, 1)),
        )
        parts = []
        for tag, m0, m1, (exp0, exp1) in legs:
            await self._acq_reset(f"S5{tag}")
            await self._set_target_id(f"S5{tag}_TARGET_ID", ADDR0, m0, ADDR1, m1)
            ack0, text0 = await self._probe_addr(f"S5{tag}_A0", vip, ADDR0)
            ack1, text1 = await self._probe_addr(f"S5{tag}_A1", vip, ADDR1)
            assert (ack0, ack1) == (exp0, exp1), (
                f"S5{tag}: MASK0={m0:#x} MASK1={m1:#x} gave ACK bits 0x23={ack0} 0x35={ack1}, "
                f"expected {exp0} {exp1}"
            )
            parts.append(f"({tag}) MASK0={m0:#x} MASK1={m1:#x}: 0x23 {text0}; 0x35 {text1}")
        self._stamp("S5")
        self._chk("CHK-I2C-TGT-GATE-MASKZERO", "; ".join(parts))

    async def _s6_rewrite(self) -> None:
        vip = self._vip()
        await self._set_target_id("S6_RESTORE", ADDR0, 0x7F, ADDR1, 0x7F)
        await self._acq_reset("S6_BEFORE")
        before = await self._write(vip, ADDR0, [0x15])
        before_entries = await self._collect("s6_before_acq")
        assert before == [0, 0], f"S6: 0x23 before the rewrite ACK bits {before}"
        assert before_entries[0] == (I2C_ACQ_SIGNAL_START, 0x46), _fmt(before_entries)
        await self._set_target_id("S6_REWRITE", ADDR_OTHER_B, 0x7F, ADDR1, 0x7F)
        await self._acq_reset("S6_OLD")
        old = await self._write(vip, ADDR0, [0x15])
        flat = await self._flat_acq("S6_OLD")
        assert old == [1], f"S6: old address 0x23 ACK bits {old} after the rewrite"
        assert flat[:FLAT_READS] == [0] * FLAT_READS, f"S6: old address left ACQLVL {flat}"
        await self._acq_reset("S6_NEW")
        new = await self._write(vip, ADDR_OTHER_B, [0x16])
        new_entries = await self._collect("s6_new_acq")
        assert new == [0, 0], f"S6: new address 0x3c ACK bits {new}"
        assert len(new_entries) == 3, f"S6: 0x3c entries {_fmt(new_entries)}, expected three"
        assert new_entries[0] == (I2C_ACQ_SIGNAL_START, 0x78), _fmt(new_entries)
        assert new_entries[1][0] == I2C_ACQ_SIGNAL_NONE, _fmt(new_entries)
        assert new_entries[2][0] == I2C_ACQ_SIGNAL_STOP, _fmt(new_entries)
        self._stamp("S6")
        self._chk(
            "CHK-I2C-TGT-GATE-REWRITE",
            f"before: 0x23 ACK bit {before[0]} entries {_fmt(before_entries)}; ADDRESS0 -> 0x3c: "
            f"0x23 ACK bit {old[0]} ACQLVL {flat[:FLAT_READS]}, 0x3c ACK bits {new} entries "
            f"{_fmt(new_entries)}",
        )

    async def _role_nack(self, label: str, ctrl: int, vip: SmcI2cMasterVip) -> str:
        await self.csr_write(f"{label}_CTRL", R["ctrl"], ctrl)
        await self._acq_reset(label)
        acks = await self._write(vip, ADDR0, [])
        flat = await self._flat_acq(label)
        assert acks == [1], f"{label}: CTRL=0x{ctrl:x} ACK bits {acks}, expected NACK"
        assert flat[:FLAT_READS] == [0] * FLAT_READS and flat[FLAT_READS] == 1, (
            f"{label}: CTRL=0x{ctrl:x} left ACQLVL {flat[:FLAT_READS]} ACQEMPTY {flat[FLAT_READS]}"
        )
        return f"CTRL=0x{ctrl:x} 0x46 ACK bit {acks[0]} ACQLVL {flat[:FLAT_READS]}"

    async def _s7_roles(self) -> str:
        vip = self._vip()
        await self._set_target_id("S7_RESTORE", ADDR0, 0x7F, ADDR1, 0x7F)
        monitor = await self._role_nack("S7_MONITOR", 0, vip)
        controller = await self._role_nack("S7_CONTROLLER", I2C_CTRL_ENABLEHOST, vip)
        self._stamp("S7")
        return f"Monitor {monitor}; Controller {controller}"

    async def _s8_hybrid(self, s7_text: str) -> None:
        vip = self._vip()
        await self.csr_write("S8_CTRL_HYBRID", R["ctrl"], CTRL_HYBRID)
        await self._acq_reset("S8")
        acks = await self._write(vip, ADDR0, [0x13])
        entries = await self._collect("s8_acq")
        assert acks == [0, 0], f"S8: Hybrid role ACK bits {acks}"
        assert len(entries) == 3, f"S8: Hybrid entries {_fmt(entries)}, expected three"
        assert entries[0] == (I2C_ACQ_SIGNAL_START, 0x46), _fmt(entries)
        assert entries[1] == (I2C_ACQ_SIGNAL_NONE, 0x13), _fmt(entries)
        assert entries[2][0] == I2C_ACQ_SIGNAL_STOP, _fmt(entries)
        self._stamp("S8")
        self._chk(
            "CHK-I2C-TGT-ROLE-GATE",
            f"I2C_EN=1: {s7_text}; Hybrid ACK bits 0x46={acks[0]} 0x13={acks[1]} entries "
            f"{_fmt(entries)}; positive control 0x23 ACK bit {self.s2_ack} in S2",
        )

    async def _s9_framing(self) -> None:
        vip = self._vip()
        await self._acq_reset("S9")
        await self.csr_write("S9_CTRL_TARGET", R["ctrl"], CTRL_TARGET)
        await self.csr_write("S9_INTR_CLR", R["intr_state"], INTR_UNEXP_STOP)

        await self._acq_reset("S9A")
        a_acks = await self._write(vip, ADDR0, [])
        a_entries = await self._collect("s9a_acq")
        a_intr = await self.csr_read("S9A_INTR_STATE", R["intr_state"])
        await self.csr_write("S9A_INTR_CLR", R["intr_state"], INTR_UNEXP_STOP)
        assert a_acks == [0], f"S9a: address-only write ACK bits {a_acks}"
        assert a_entries and a_entries[0] == (I2C_ACQ_SIGNAL_START, 0x46), (
            f"S9a: first entry {_fmt(a_entries)}, expected (0x1,0x46)"
        )

        await self._acq_reset("S9B")
        await vip.send_start()
        b_acks = [await vip.send_byte(0x46), await vip.send_byte(0x21)]
        await vip.send_start()
        b_acks += [await vip.send_byte(0x6A), await vip.send_byte(0x22)]
        await vip.send_stop()
        b_entries = await self._collect("s9b_acq")
        assert b_acks == [0, 0, 0, 0], f"S9b: ACK bits {b_acks}"
        assert len(b_entries) >= 5, f"S9b: entries {_fmt(b_entries)}"
        assert b_entries[:4] == [
            (I2C_ACQ_SIGNAL_START, 0x46),
            (I2C_ACQ_SIGNAL_NONE, 0x21),
            (I2C_ACQ_SIGNAL_RESTART, 0x6A),
            (I2C_ACQ_SIGNAL_NONE, 0x22),
        ], f"S9b: entries {_fmt(b_entries)}"
        assert b_entries[-1][0] == I2C_ACQ_SIGNAL_STOP, f"S9b: entries {_fmt(b_entries)}"

        await self._acq_reset("S9C")
        await vip.send_start()
        c_acks = [await vip.send_byte(0x46), await vip.send_byte(0x23)]
        await vip.send_start()
        c_acks.append(await vip.send_byte(0x54))
        await vip.send_stop()
        c_entries = await self._collect("s9c_acq")
        assert c_acks == [0, 0, 1], f"S9c: ACK bits {c_acks}"
        assert (I2C_ACQ_SIGNAL_RESTART, 0x54) not in c_entries, f"S9c: entries {_fmt(c_entries)}"
        self._stamp("S9")
        self._chk(
            "CHK-I2C-TGT-ADDR-ONLY",
            f"address-only write ACK bit {a_acks[0]}; first entry {_fmt(a_entries[:1])} compared; "
            f"all entries {_fmt(a_entries)} logged; INTR_STATE=0x{a_intr:08x} "
            f"UNEXP_STOP={int(bool(a_intr & INTR_UNEXP_STOP))} logged (SF-029, SF-021)",
        )
        self._chk(
            "CHK-I2C-TGT-RESTART-ADDRESS",
            f"(b) ACK bits {b_acks} entries {_fmt(b_entries)}; (c) ACK bits {c_acks} entries "
            f"{_fmt(c_entries)} with no (0x3,0x54)",
        )

    async def _sample_bus(self, name: str) -> str:
        scl_low = sda_low = 0
        scl = sda = -1
        for _ in range(BUS_SAMPLE_CYCLES):
            await self._cycles(1)
            scl = self._probe("tb_i2c0_scl")
            sda = self._probe("tb_i2c0_sda")
            scl_low += int(scl == 0)
            sda_low += int(sda == 0)
        text = f"scl_low={scl_low}/{BUS_SAMPLE_CYCLES} sda_low={sda_low}/{BUS_SAMPLE_CYCLES}"
        text += f" last scl={scl} sda={sda}"
        self.waits.append((name, f"{BUS_SAMPLE_CYCLES}cyc clk_smc_i", text))
        return text

    async def _measure_case(self, case: str) -> str:
        await self._wait_released(f"s10_{case}_release")
        bus = await self._sample_bus(f"s10_{case}_bus_sample")
        status = await self.csr_read(f"S10_{case}_STATUS", R["status"])
        entries = await self._collect(f"s10_{case}_acq", allow_zero=True)
        await self._acq_reset(f"S10_{case}_DRAIN")
        idle = int(bool(status & I2C_STATUS_TARGETIDLE))
        return (
            f"{case}: bus after release {bus}; TARGETIDLE={idle}"
            f" STATUS=0x{status:08x} ACQLVL={len(entries)} entries {_fmt(entries)}"
        )

    async def _s10_midtransfer(self) -> None:
        rows = []

        vip = self._vip()
        await self._acq_reset("S10_ADDR")
        await drive_to_slot(vip, ADDR0, 0, "addr", 4)
        await self.csr_write("S10_ADDR_CTRL_OFF", R["ctrl"], 0)
        await self.csr_write("S10_ADDR_CTRL_ON", R["ctrl"], CTRL_TARGET)
        await release_bus(vip)
        rows.append(await self._measure_case("addr4"))

        vip = self._vip()
        await drive_to_slot(vip, ADDR0, 0x5A, "data", 4)
        await self.csr_write("S10_DATA_CTRL_OFF", R["ctrl"], 0)
        await self.csr_write("S10_DATA_CTRL_ON", R["ctrl"], CTRL_TARGET)
        await release_bus(vip)
        rows.append(await self._measure_case("data4"))

        vip = self._vip()
        await self.csr_write("S10_BEFORE_CTRL_OFF", R["ctrl"], 0)
        await vip.send_start()
        ack = await vip.send_byte(0x46)
        await self.csr_write("S10_AFTER_ACK_CTRL_ON", R["ctrl"], CTRL_TARGET)
        await release_bus(vip)
        row = await self._measure_case("before_start")
        rows.append(f"{row}; address ACK bit while disabled {ack}")
        self._stamp("S10")
        self._chk(
            "CHK-I2C-TGT-ROLE-MIDTRANSFER-LOG",
            "; ".join(rows) + "; no compare (SF-027)",
        )

        await self._fifo_reset("S10_RECOVER")
        await self.csr_write("S10_RECOVER_CTRL", R["ctrl"], CTRL_TARGET)
        pre = await self.csr_read("S10_RECOVER_STATUS", R["status"])
        vip = self._vip()
        acks = await self._write(vip, ADDR0, [0x14])
        entries = await self._collect("s10_clean_acq")

        async def idle() -> tuple[bool, str]:
            status = await self.csr_read("S10_IDLE_STATUS", R["status"])
            return bool(status & I2C_STATUS_TARGETIDLE), f"status=0x{status:08x}"

        await self._poll("s10_targetidle", IDLE_ROUNDS, IDLE_GAP, idle)
        assert acks == [0, 0], f"S10: clean write ACK bits {acks}"
        assert len(entries) == 3, f"S10: clean write entries {_fmt(entries)}"
        assert entries[0] == (I2C_ACQ_SIGNAL_START, 0x46), _fmt(entries)
        assert entries[1] == (I2C_ACQ_SIGNAL_NONE, 0x14), _fmt(entries)
        assert entries[2][0] == I2C_ACQ_SIGNAL_STOP, _fmt(entries)
        self._chk(
            "CHK-I2C-TGT-ROLE-MIDTRANSFER-RECOVER",
            f"after ACQRST|TXRST and CTRL restored (STATUS=0x{pre:08x} before the write) the "
            f"clean write ACK bits {acks} popped {_fmt(entries)}; TARGETIDLE=1 within "
            f"{IDLE_ROUNDS}x{IDLE_GAP} cycles",
        )

    # --------------------------------------------------------------- tokens --
    def _emit_timeout_paths(self) -> None:
        cfg = self.cfg
        inherited = [
            (
                "cold_reset_release",
                f"{max(cfg.post_reset_settle_cycles, 2000)} clk_ref_i cycles",
                "chain released before bring-up returned",
            ),
            ("pll_period_measure", "5 rising edges per clock", "periods within tolerance"),
        ]
        vip_waits = [
            (
                "vip_scl_release",
                f"{vip.scl_timeout_ns}ns",
                f"longest SCL hold {vip.last_scl_hold_ns}ns",
            )
            for vip in self.vips
        ]
        axi = ("sep_in_access", f"{cfg.axi_timeout_ns}ns", f"{self.accesses} accesses completed")
        waits = inherited + self.waits + vip_waits + [axi]
        self._chk(
            "CHK-TIMEOUT-PATHS",
            f"{len(waits)} bounded waits, each raising AssertionError with its last state on "
            f"expiry; " + "; ".join(f"{n} bound={b} last={s}" for n, b, s in waits),
        )

    def _emit_checks(self) -> None:
        order = [term for term, _ in self.stamps]
        assert order == FENCE_ORDER, f"fence order {order}, expected {FENCE_ORDER}"
        times = [ps for _, ps in self.stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        printed = {name: idx for name, _, idx in self.chk_lines}
        for name, term in CHECKER_AFTER.items():
            assert name in printed, f"{name} never recorded"
            assert printed[name] > order.index(term), f"{name} recorded before {term}"
        for name, line, _ in self.chk_lines:
            cocotb.log.info("%s: %s", name, line)
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s ps",
            " < ".join(f"{t}={ps}" for t, ps in self.stamps),
            ",".join(name for name, _, _ in self.chk_lines),
            ",".join(str(ps) for ps in times),
        )

    async def body(self) -> None:
        await self._s1_setup()
        await self._s2_pair0()
        await self._s3_pair1()
        await self._s4_nonmatch()
        await self._s5_masks()
        await self._s6_rewrite()
        s7_text = await self._s7_roles()
        await self._s8_hybrid(s7_text)
        await self._s9_framing()
        await self._s10_midtransfer()
        self._emit_timeout_paths()
        self._emit_checks()
