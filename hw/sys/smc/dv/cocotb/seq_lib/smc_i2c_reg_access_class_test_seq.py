# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C register access classes with both engines disabled, on all three instances.

Contract SMC_I2C_CSR_IRQ_016, anchor smc_i2c_reg_access_class_test.
Scenarios: I2C-REG-RW-READBACK.S1-S5, I2C-REG-RO-WO-ACCESS.S1-S4, I2C-CTRL-REGS.S2-S4,
I2C-INSTANCE-ISOLATION.S1.
Sources: hw/ip/i2c/regs/i2c.rdl, hw/ip/i2c/regs/i2c_wrap.rdl, hw/ip/i2c/regs/i2c_ctrl.rdl,
hw/ip/i2c/doc/index.adoc.

Every access is a SEP_IN frontdoor word access with CTRL.ENABLEHOST and CTRL.ENABLETARGET
held at 0 and no I2C bus traffic. The seed (RANDOM_SEED) picks the instance walked per
register. The response codes of read-only writes and write-only reads (SF-006), the read
value of write-only registers (SF-007), reserved-bit residue (SF-009), the threshold
readbacks (SF-024, SF-026), TIMING0 THIGH/TLOW below 2 (SF-027) and the role bits (SF-025)
are logged without a compare.
"""

from __future__ import annotations

import os
import random

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import I2C_CG_EN
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_CTRL_ENABLEHOST,
    I2C_CTRL_ENABLETARGET,
    I2C_FIFO_CTRL_ACQRST,
    I2C_FIFO_CTRL_FMTRST,
    I2C_FIFO_CTRL_RXRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_SMBUS_CTRL_SMBALERT,
    I2C_WRAP_CONTROLLER_MODE,
    I2C_WRAP_EN,
    I2C_WRAP_SMBUS_EN,
)
from .smc_i2c_master_target_test_seq import _i2c_u32
from .smc_i2c_target_ack_ctrl_test_seq import CLOCK_GATE_CONTROL
from .smc_i2c_window_decode_test_seq import (
    INSTANCES,
    INTR_EVENT_MASK,
    STATUS_RESET,
    WRAP_CTRL_MASK,
    _declared_mask,
    _reg,
    _reset,
    _wrap_ctrl,
)

TXOVRDEN = _i2c_u32("I2C__OVRD__TXOVRDEN_bm")
SCLVAL = _i2c_u32("I2C__OVRD__SCLVAL_bm")
SDAVAL = _i2c_u32("I2C__OVRD__SDAVAL_bm")
SMBSUS = _i2c_u32("I2C__SMBUS_CTRL__SMBSUS_bm")
ROLE_BITS = I2C_CTRL_ENABLEHOST | I2C_CTRL_ENABLETARGET
THIGH = _i2c_u32("I2C__TIMING0__THIGH_bm")
TLOW = _i2c_u32("I2C__TIMING0__TLOW_bm")
TIMING_MIN = 2
ALL_ONES = 0xFFFF_FFFF
POLLS = 8
FENCE_STEPS = tuple(f"S{n}" for n in range(1, 12))

RW_FAMILIES = (
    "INTR_ENABLE",
    "CTRL",
    "TIMING0",
    "TIMING1",
    "TIMING2",
    "TIMING3",
    "TIMING4",
    "HOST_FIFO_CONFIG",
    "TARGET_FIFO_CONFIG",
    "TIMEOUT_CTRL",
    "HOST_TIMEOUT_CTRL",
    "TARGET_TIMEOUT_CTRL",
    "HOST_NACK_HANDLER_TIMEOUT",
    "TARGET_ID",
    "OVRD",
    "SMBUS_CTRL",
)
RW_MASKS = {
    **{reg: _declared_mask(reg) for reg in RW_FAMILIES},
    "CTRL": _declared_mask("CTRL") & ~ROLE_BITS,
    "SMBUS_CTRL": SMBSUS,
}
FIELD_FAMILIES = {
    "TARGET_ID": ("ADDRESS0", "MASK0", "ADDRESS1", "MASK1"),
    "HOST_FIFO_CONFIG": ("RX_THRESH", "FMT_THRESH"),
    "TIMEOUT_CTRL": ("VAL", "MODE", "EN"),
    "TIMING0": ("THIGH", "TLOW"),
}
MATRIX_FAMILIES = ("TARGET_ID", "INTR_ENABLE", "TIMING0")
RO_REGISTERS = (
    "STATUS",
    "HOST_FIFO_STATUS",
    "TARGET_FIFO_STATUS",
    "VAL",
    "SMBUS_STATUS",
    "ACQ_FIFO_NEXT_DATA",
)
ZERO_RESET_RO = ("HOST_FIFO_STATUS", "TARGET_FIFO_STATUS", "SMBUS_STATUS", "ACQ_FIFO_NEXT_DATA")
WO_REGISTERS = ("FIFO_CTRL", "FDATA", "TXDATA", "INTR_TEST")
ALL_REGISTERS = (
    "INTR_STATE",
    "INTR_ENABLE",
    "INTR_TEST",
    "SMBUS_CTRL",
    "CTRL",
    "STATUS",
    "RDATA",
    "FDATA",
    "FIFO_CTRL",
    "HOST_FIFO_CONFIG",
    "TARGET_FIFO_CONFIG",
    "HOST_FIFO_STATUS",
    "TARGET_FIFO_STATUS",
    "OVRD",
    "VAL",
    "TIMING0",
    "TIMING1",
    "TIMING2",
    "TIMING3",
    "TIMING4",
    "TIMEOUT_CTRL",
    "TARGET_ID",
    "ACQDATA",
    "TXDATA",
    "HOST_TIMEOUT_CTRL",
    "TARGET_TIMEOUT_CTRL",
    "TARGET_ACK_CTRL",
    "ACQ_FIFO_NEXT_DATA",
    "HOST_NACK_HANDLER_TIMEOUT",
    "CONTROLLER_EVENTS",
    "TARGET_EVENTS",
    "SMBUS_STATUS",
)
FIFO_RESETS = (
    I2C_FIFO_CTRL_RXRST | I2C_FIFO_CTRL_FMTRST | I2C_FIFO_CTRL_ACQRST | I2C_FIFO_CTRL_TXRST
)
CTRL_FIELDS = (
    ("I2C_EN", I2C_WRAP_EN),
    ("I2C_CONTROLLER_MODE_EN", I2C_WRAP_CONTROLLER_MODE),
    ("SMBUS_EN", I2C_WRAP_SMBUS_EN),
)
CTRL_FIELD_BITS = I2C_WRAP_EN | I2C_WRAP_CONTROLLER_MODE | I2C_WRAP_SMBUS_EN
CTRL_PATTERNS = (
    *CTRL_FIELDS,
    ("ALL_THREE", CTRL_FIELD_BITS),
    ("NONE", 0),
)
THRESHOLD_VALUES = (0x40, 0x41, 0x100, 0xFFF)
NBYTES_VALUE = 0x5
NACK_COUNT_VALUE = 0x5A
FIELD_BG_SEED = 0x9E37


def guard(register: str, word: int) -> int:
    """Clamp a written word to the bench guards: no role bits, no half-driven override."""
    if register == "CTRL":
        return word & ~ROLE_BITS
    if register == "SMBUS_CTRL":
        return word & ~I2C_SMBUS_CTRL_SMBALERT
    if register == "OVRD" and word & TXOVRDEN:
        return word | SCLVAL | SDAVAL
    return word


def compare_mask(register: str, word: int) -> int:
    """Software-writable bits compared for a written word (THIGH/TLOW below 2 excluded)."""
    mask = RW_MASKS[register]
    if register == "TIMING0":
        for field in (THIGH, TLOW):
            if (word & field) >> (field & -field).bit_length() - 1 < TIMING_MIN:
                mask &= ~field
    return mask


def field_value(mask: int, word: int) -> int:
    return (word & mask) >> ((mask & -mask).bit_length() - 1)


def with_field(word: int, mask: int, value: int) -> int:
    pos = (mask & -mask).bit_length() - 1
    return (word & ~mask) | ((value << pos) & mask)


class smc_i2c_reg_access_class_test_seq(SmcCsrSeq):
    """Access classes of the I2C instance registers and I2C_CTRL with the engines disabled."""

    def __init__(self, name: str = "smc_i2c_reg_access_class_test_seq") -> None:
        super().__init__(name)
        self.fence: list[tuple[str, int]] = []
        self.chk_stamps: dict[str, int] = {}
        self.seed = int(os.environ.get("RANDOM_SEED", "1"), 0)
        self.rng = random.Random(self.seed)
        self.instance_of: dict[str, int] = {}

    def _mark(self, step: str) -> None:
        self.fence.append((step, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, text: str, *args) -> None:
        self.chk_stamps[chk_id] = int(get_sim_time("ps"))
        cocotb.log.info(f"{chk_id}: {text}", *args)

    async def _observe(
        self, name: str, addr: int, write: bool = False, data: int = 0
    ) -> tuple[int, int]:
        item = SmcSysAxiItem(f"{'wr' if write else 'rd'}_{name}")
        item.op = SmcSysAxiOp.WRITE if write else SmcSysAxiOp.READ
        item.addr = addr
        item.wdata = data
        item.allow_error = True
        item.expect_error = False
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None, f"{name} @ 0x{addr:08x}: no response code"
        return item.resp_code, item.rdata

    async def _write_check(self, label: str, register: str, n: int, word: int) -> int:
        """Write a guarded full word and compare the readback under the writable mask."""
        word = guard(register, word)
        await self.csr_write(f"{label}_WR", _reg(register, n), word)
        got = await self.csr_read(f"{label}_RB", _reg(register, n))
        mask = compare_mask(register, word)
        assert got & mask == word & mask, (
            f"{register}[{n}] {label}: wrote 0x{word:08x}, read 0x{got:08x}, "
            f"compared under writable mask 0x{mask:08x}"
        )
        return got

    async def _restore(self, registers, n: int) -> None:
        for register in registers:
            await self.csr_write(f"{register}{n}_RESTORE", _reg(register, n), _reset(register))

    @staticmethod
    def _sample(name: str) -> int:
        sig = getattr(cocotb.top, name)
        assert sig.value.is_resolvable, f"{name} = {sig.value} is X/Z"
        return int(sig.value)

    async def _step_s1(self) -> None:
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        for n in INSTANCES:
            status = await self.csr_read(f"STATUS{n}", _reg("STATUS", n))
            assert status == STATUS_RESET, f"STATUS[{n}] reads 0x{status:08x} after bring-up"
        await self.arm_i2c_gpio_lsio(0, "PAD_ARM0")
        self._mark("S1")

    async def _step_s2(self) -> None:
        compares = 0
        low_points = []
        walk = {}
        for register in RW_FAMILIES:
            mask = RW_MASKS[register]
            for n in INSTANCES:
                for label, word in (("ONES", ALL_ONES), ("ZERO", 0)):
                    got = await self._write_check(f"{register}{n}_{label}", register, n, word)
                    compares += 1
                    if register == "TIMING0":
                        low_points.append(f"{label}[{n}]=0x{got:08x}")
            n = self.rng.choice(INSTANCES)
            self.instance_of[register] = n
            bits = [1 << i for i in range(32) if mask >> i & 1]
            for bit in bits:
                for label, word in (("WALK1", bit), ("WALK0", mask & ~bit)):
                    got = await self._write_check(
                        f"{register}{n}_{label}_{bit:x}", register, n, word
                    )
                    compares += 1
                    if (
                        register == "TIMING0"
                        and compare_mask(register, guard(register, word)) != mask
                    ):
                        low_points.append(f"{label}_{bit:x}=0x{got:08x}")
            walk[register] = (n, len(bits))
            await self._restore((register,), n)
            for m in INSTANCES:
                if m != n:
                    await self._restore((register,), m)
        self._mark("S2")
        cocotb.log.info("RANDOM_SEED=%d", self.seed)
        self._chk(
            "CHK-I2C-RW-PATTERNS",
            "RANDOM_SEED=%d; %d readbacks equal the written word under the writable mask "
            "over %d families (all-ones and all-zero on instances 0,1,2; walking-one and "
            "walking-zero per family on seeded instance: %s); TIMING0 THIGH/TLOW below 2 "
            "logged without compare (SF-027): %s",
            self.seed,
            compares,
            len(RW_FAMILIES),
            " ".join(f"{r}:inst{n}x{b}bits" for r, (n, b) in walk.items()),
            " ".join(low_points),
        )

    def _background(self, register: str) -> tuple[int, dict[str, int]]:
        word = 0
        values = {}
        for k, name in enumerate(FIELD_FAMILIES[register]):
            mask = _i2c_u32(f"I2C__{register}__{name}_bm")
            width = bin(mask).count("1")
            maxv = (1 << width) - 1
            value = 1 if width == 1 else ((FIELD_BG_SEED * (k + 1) + 0x5A) & maxv)
            if width > 1 and not TIMING_MIN <= value < maxv:
                value = (maxv >> 1) | 1
            values[name] = value
            word = with_field(word, mask, value)
        return word, values

    async def _step_s3(self) -> None:
        changes = 0
        n = self.rng.choice(INSTANCES)
        for register, names in FIELD_FAMILIES.items():
            background, values = self._background(register)
            for name in names:
                mask = _i2c_u32(f"I2C__{register}__{name}_bm")
                maxv = mask >> ((mask & -mask).bit_length() - 1)
                new_values = []
                for new in (values[name] ^ maxv, values[name] ^ 1):
                    if new != values[name] and new not in new_values:
                        new_values.append(new)
                for new in new_values:
                    await self.csr_write(f"{register}_BG", _reg(register, n), background)
                    word = with_field(background, mask, new)
                    await self.csr_write(f"{register}_{name}_CHG", _reg(register, n), word)
                    got = await self.csr_read(f"{register}_{name}_RB", _reg(register, n))
                    want = word & RW_MASKS[register]
                    assert got & RW_MASKS[register] == want, (
                        f"{register}[{n}].{name}: background 0x{background:08x} with the field "
                        f"changed to 0x{new:x} reads 0x{got:08x}, expected 0x{want:08x}"
                    )
                    changes += 1
            await self._restore((register,), n)
        self._mark("S3")
        self._chk(
            "CHK-I2C-RW-FIELD-INDEP",
            "%d single-field changes on instance %d across %s each read the background word "
            "with only that field replaced",
            changes,
            n,
            ",".join(f"{r}({len(f)})" for r, f in FIELD_FAMILIES.items()),
        )

    def _pattern(self, register: str, salt: int) -> int:
        mask = RW_MASKS[register]
        word = ((0x6B5AC3A5 * (salt + 1)) ^ 0xA5C35A69) & mask
        word = guard(register, word or mask & -mask)
        if register == "TIMING0":
            word = (word & ~(THIGH | TLOW)) | 0x56A | (0xA59 << 16)
        return word

    async def _step_s4(self) -> None:
        n = self.rng.choice(INSTANCES)
        others = [m for m in INSTANCES if m != n]
        patterns = {r: self._pattern(r, i) for i, r in enumerate(RW_FAMILIES)}
        for register, word in patterns.items():
            await self.csr_write(f"{register}_PAT", _reg(register, n), word)
        unrelated = (
            lambda i: (f"CG{i}", CLOCK_GATE_CONTROL),
            lambda i: (f"STATUS_O{i}", _reg("STATUS", others[i % 2])),
            lambda i: (f"WRAP_CTRL_O{i}", _wrap_ctrl(others[i % 2])),
        )
        scl_sda = []
        for i in range(POLLS):
            name, addr = unrelated[i % 3](i)
            await self.csr_read(f"UNRELATED_{name}", addr)
            status = await self.csr_read(f"STATUS_POLL{i}", _reg("STATUS", n))
            assert status == STATUS_RESET, f"STATUS[{n}] poll {i} reads 0x{status:08x}"
            scl, sda = self._sample("tb_i2c0_scl"), self._sample("tb_i2c0_sda")
            assert scl == 1 and sda == 1, f"poll {i}: tb_i2c0_scl={scl} tb_i2c0_sda={sda}"
            scl_sda.append(f"{scl}{sda}")
        for register, word in patterns.items():
            got = await self.csr_read(f"{register}_PERSIST", _reg(register, n))
            mask = compare_mask(register, word)
            assert got & mask == word & mask, (
                f"{register}[{n}] changed from 0x{word:08x} to 0x{got:08x} after 8 accesses "
                f"and 8 STATUS polls"
            )
        await self._restore(RW_FAMILIES, n)
        self._mark("S4")
        self._chk(
            "CHK-I2C-RW-PERSIST",
            "%d patterns on instance %d unchanged after %d unrelated accesses and %d STATUS "
            "polls reading 0x%03x with tb_i2c0_scl,tb_i2c0_sda (scl,sda per poll) %s",
            len(patterns),
            n,
            POLLS,
            POLLS,
            STATUS_RESET,
            ",".join(scl_sda),
        )

    async def _step_s5(self) -> None:
        n = 0
        seen = []
        nbytes_mask = _i2c_u32("I2C__TARGET_ACK_CTRL__NBYTES_bm")
        await self.csr_write("NBYTES", _reg("TARGET_ACK_CTRL", n), NBYTES_VALUE & nbytes_mask)
        got = await self.csr_read("NBYTES_RB", _reg("TARGET_ACK_CTRL", n))
        seen.append(f"TARGET_ACK_CTRL.NBYTES(0x{NBYTES_VALUE:x})=0x{got:08x}")
        await self.csr_write("SMBALERT", _reg("SMBUS_CTRL", n), I2C_SMBUS_CTRL_SMBALERT)
        got = await self.csr_read("SMBALERT_RB", _reg("SMBUS_CTRL", n))
        seen.append(f"SMBUS_CTRL.SMBALERT(0x1)=0x{got:08x}")
        acq = _i2c_u32("I2C__TARGET_FIFO_CONFIG__ACQ_THRESH_bm")
        rx = _i2c_u32("I2C__HOST_FIFO_CONFIG__RX_THRESH_bm")
        fmt = _i2c_u32("I2C__HOST_FIFO_CONFIG__FMT_THRESH_bm")
        for value in THRESHOLD_VALUES:
            await self.csr_write(
                "ACQ_THRESH", _reg("TARGET_FIFO_CONFIG", n), with_field(0, acq, value)
            )
            got = await self.csr_read("ACQ_THRESH_RB", _reg("TARGET_FIFO_CONFIG", n))
            seen.append(f"ACQ_THRESH(0x{value:x})=0x{field_value(acq, got):x}")
            word = with_field(with_field(0, rx, value), fmt, value)
            await self.csr_write("HOST_THRESH", _reg("HOST_FIFO_CONFIG", n), word)
            got = await self.csr_read("HOST_THRESH_RB", _reg("HOST_FIFO_CONFIG", n))
            seen.append(
                f"HOST_RX/FMT_THRESH(0x{value:x})="
                f"0x{field_value(rx, got):x}/0x{field_value(fmt, got):x}"
            )
        await self._restore(("TARGET_ACK_CTRL", "SMBUS_CTRL"), n)
        await self._restore(("TARGET_FIFO_CONFIG", "HOST_FIFO_CONFIG"), n)
        self._mark("S5")
        self._chk(
            "CHK-I2C-RW-OBSERVED",
            "instance %d readbacks logged, none compared (SF-024, SF-026): %s",
            n,
            " ".join(seen),
        )

    async def _step_s6(self) -> None:
        n = 0
        codes = []
        for register in RO_REGISTERS:
            for word in (ALL_ONES, 0):
                resp, _ = await self._observe(
                    f"{register}_W{word:x}", _reg(register, n), True, word
                )
                codes.append(f"{register}<=0x{word:x}:resp={resp}")
            status = await self.csr_read(f"{register}_AFTER_STATUS", _reg("STATUS", n))
            assert status == STATUS_RESET, (
                f"STATUS[{n}] reads 0x{status:08x} after writing {register}"
            )
        values = {}
        for register in RO_REGISTERS:
            values[register] = await self.csr_read(f"{register}_FINAL", _reg(register, n))
        assert values["STATUS"] == STATUS_RESET, f"STATUS reads 0x{values['STATUS']:08x}"
        for register in ZERO_RESET_RO:
            assert values[register] == 0, f"{register}[{n}] reads 0x{values[register]:08x}"
        self._mark("S6")
        self._chk(
            "CHK-I2C-RO-IGNORED",
            "instance %d write response codes %s; after both writes STATUS=0x%03x and "
            "%s read 0x0 (reset-value-only proof); VAL=0x%08x logged",
            n,
            " ".join(codes),
            values["STATUS"],
            ",".join(ZERO_RESET_RO),
            values["VAL"],
        )

    async def _step_s7(self) -> None:
        n = 1
        events = INTR_EVENT_MASK
        before = await self.csr_read("INTR_STATE_BEFORE", _reg("INTR_STATE", n))
        seen = []
        for register in WO_REGISTERS:
            resp, value = await self._observe(f"{register}_RD", _reg(register, n))
            seen.append(f"{register}:resp={resp},val=0x{value:08x}")
        status = await self.csr_read("STATUS_AFTER_WO_READS", _reg("STATUS", n))
        state = await self.csr_read("INTR_STATE_AFTER_WO_READS", _reg("INTR_STATE", n))
        assert status == STATUS_RESET, f"STATUS[{n}] reads 0x{status:08x} after write-only reads"
        assert state & events == before & events, (
            f"INTR_STATE[{n}] event bits 0x{state & events:x} differ from 0x{before & events:x} "
            f"after write-only reads"
        )
        writes = []
        for register in ALL_REGISTERS:
            word = guard(register, ALL_ONES)
            resp, _ = await self._observe(f"{register}_ALLONES", _reg(register, n), True, word)
            writes.append(f"{register}:{resp}")
        residue = []
        for register in ALL_REGISTERS:
            resp, value = await self._observe(f"{register}_RESIDUE", _reg(register, n))
            declared = _declared_mask(register)
            residue.append(
                f"{register}:resp={resp},val=0x{value:08x},res=0x{value & ~declared & ALL_ONES:08x}"
            )
        await self.csr_write("INTR_STATE_CLEAR", _reg("INTR_STATE", n), ALL_ONES)
        await self.csr_write("EVENTS_CLEAR_C", _reg("CONTROLLER_EVENTS", n), ALL_ONES)
        await self.csr_write("EVENTS_CLEAR_T", _reg("TARGET_EVENTS", n), ALL_ONES)
        await self._restore(RW_FAMILIES, n)
        await self._restore(("TARGET_ACK_CTRL",), n)
        await self.csr_write("FIFO_RESET", _reg("FIFO_CTRL", n), FIFO_RESETS)
        count = _reg("TARGET_NACK_COUNT", n)
        nack = [await self.csr_read(f"NACK_RESET{i}", count) for i in range(2)]
        await self.csr_write("NACK_WRITE", count, NACK_COUNT_VALUE)
        nack += [await self.csr_read(f"NACK_WRITTEN{i}", count) for i in range(2)]
        status = await self.csr_read("STATUS_FINAL", _reg("STATUS", n))
        state = await self.csr_read("INTR_STATE_FINAL", _reg("INTR_STATE", n))
        assert status == STATUS_RESET, f"STATUS[{n}] reads 0x{status:08x} after the sweep"
        assert state & events == before & events, (
            f"INTR_STATE[{n}] event bits 0x{state & events:x} differ from 0x{before & events:x}"
        )
        self._mark("S7")
        self._chk(
            "CHK-I2C-ROWO-OBSERVED",
            "instance %d write-only reads %s; all-ones write responses %s; readback residue %s; "
            "TARGET_NACK_COUNT reads at reset,reset,after 0x%x,after: %s; STATUS=0x%03x and "
            "INTR_STATE event bits 0x%x unchanged (SF-006, SF-007, SF-008, SF-009)",
            n,
            " ".join(seen),
            " ".join(writes),
            " ".join(residue),
            NACK_COUNT_VALUE,
            ",".join(f"0x{v:x}" for v in nack),
            status,
            state & events,
        )

    async def _step_s8(self) -> None:
        residues = []
        compares = 0
        for n in INSTANCES:
            for label, word in CTRL_PATTERNS:
                await self.csr_write(f"I2C_CTRL{n}_{label}", _wrap_ctrl(n), word)
                got = await self.csr_read(f"I2C_CTRL{n}_{label}_RB", _wrap_ctrl(n))
                assert got & CTRL_FIELD_BITS == word, (
                    f"I2C_CTRL[{n}] {label}: wrote 0x{word:x}, "
                    f"field bits read 0x{got & CTRL_FIELD_BITS:x}"
                )
                compares += 1
                residues.append(f"{n}/{label}=0x{got & ~CTRL_FIELD_BITS & ALL_ONES:x}")
            await self.csr_write(f"I2C_CTRL{n}_RESTORE", _wrap_ctrl(n), 0)
        self._mark("S8")
        self._chk(
            "CHK-I2C-CTRL-FIELDS",
            "%d readbacks of I2C_CTRL[0..2] bits 0,4,8 equal the written bits for I2C_EN, "
            "I2C_CONTROLLER_MODE_EN, SMBUS_EN, all three and none; reserved residue "
            "(mask 0x%x excluded) logged inst/pattern=value: %s",
            compares,
            WRAP_CTRL_MASK,
            " ".join(residues),
        )

    async def _step_s9(self) -> None:
        patterns = (I2C_WRAP_EN, I2C_WRAP_CONTROLLER_MODE, I2C_WRAP_SMBUS_EN | I2C_WRAP_EN)
        previous = {n: await self.csr_read(f"I2C_CTRL{n}_PREV", _wrap_ctrl(n)) for n in INSTANCES}
        neighbours = 0
        for n in INSTANCES:
            await self.csr_write(f"I2C_CTRL{n}_PATTERN", _wrap_ctrl(n), patterns[n])
            for other in INSTANCES:
                got = await self.csr_read(f"I2C_CTRL{other}_AFTER{n}", _wrap_ctrl(other))
                if other == n:
                    assert got & CTRL_FIELD_BITS == patterns[n], (
                        f"I2C_CTRL[{n}] reads 0x{got:x} after writing 0x{patterns[n]:x}"
                    )
                    previous[n] = got
                else:
                    assert got == previous[other], (
                        f"I2C_CTRL[{other}] changed from 0x{previous[other]:x} to 0x{got:x} "
                        f"when I2C_CTRL[{n}] was written"
                    )
                    neighbours += 1
        for n in INSTANCES:
            await self.csr_write(f"I2C_CTRL{n}_RESTORE", _wrap_ctrl(n), 0)
        self._mark("S9")
        self._chk(
            "CHK-I2C-CTRL-NEIGHBOURS",
            "writes of patterns %s to I2C_CTRL[0,1,2] in turn left the other two registers at "
            "their previous word (%d neighbour reads)",
            ",".join(f"0x{p:x}" for p in patterns),
            neighbours,
        )

    async def _step_s10(self) -> None:
        neighbours = 0
        for register in MATRIX_FAMILIES:
            mask = RW_MASKS[register]
            previous = {
                n: await self.csr_read(f"{register}{n}_ENTRY", _reg(register, n)) for n in INSTANCES
            }
            for n in INSTANCES:
                word = guard(register, self._pattern(register, 7 + 3 * n + len(register)))
                await self.csr_write(f"{register}{n}_ISO", _reg(register, n), word)
                for m in INSTANCES:
                    got = await self.csr_read(f"{register}{m}_ISO{n}", _reg(register, m))
                    if m == n:
                        assert got & mask == word & mask, (
                            f"{register}[{n}] reads 0x{got:08x}, written 0x{word:08x}"
                        )
                        previous[n] = got
                    else:
                        assert got == previous[m], (
                            f"{register}[{m}] changed from 0x{previous[m]:08x} to 0x{got:08x} "
                            f"when instance {n} was written"
                        )
                        neighbours += 1
            await self._restore((register,), 0)
            await self._restore((register,), 1)
            await self._restore((register,), 2)
        self._mark("S10")
        self._chk(
            "CHK-I2C-ISOLATION-MATRIX",
            "%s: 9 writes (instance 0,1,2 each) and %d neighbour reads each read the written "
            "instance at its pattern and the other two at their previous word",
            ",".join(MATRIX_FAMILIES),
            neighbours,
        )

    async def _step_s11(self) -> None:
        probes = []
        for n in INSTANCES:
            for label, word in CTRL_FIELDS:
                await self.csr_write(f"I2C_CTRL{n}_{label}", _wrap_ctrl(n), word)
                ctrl = await self.csr_read(f"CTRL{n}_{label}", _reg("CTRL", n))
                status = await self.csr_read(f"STATUS{n}_{label}", _reg("STATUS", n))
                host = self._sample("tb_i2c_host_enable") >> n & 1
                target = self._sample("tb_i2c_target_enable") >> n & 1
                assert ctrl & ROLE_BITS == 0, f"CTRL[{n}] reads 0x{ctrl:08x} with {label} set"
                assert status == STATUS_RESET, f"STATUS[{n}] reads 0x{status:08x} with {label} set"
                probes.append(f"{n}/{label}:host={host},target={target}")
            await self.csr_write(f"I2C_CTRL{n}_RESTORE", _wrap_ctrl(n), 0)
        self._mark("S11")
        self._chk(
            "CHK-I2C-CTRL-NO-ENGINE",
            "with each I2C_CTRL field set on instances 0,1,2 CTRL role bits read 0 and STATUS "
            "reads 0x%03x; tb_i2c_host_enable/target_enable sampled (observed only): %s",
            STATUS_RESET,
            " ".join(probes),
        )

    async def body(self) -> None:
        assert hasattr(cocotb.top, "tb_i2c_host_enable"), "tb_i2c_host_enable is not exported"
        await self._step_s1()
        for step in (
            self._step_s2,
            self._step_s3,
            self._step_s4,
            self._step_s5,
            self._step_s6,
            self._step_s7,
            self._step_s8,
            self._step_s9,
            self._step_s10,
            self._step_s11,
        ):
            await step()
        order = [step for step, _ in self.fence]
        assert order == list(FENCE_STEPS), f"fence order {order}"
        stamps = [stamp for _, stamp in self.fence]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"fence stamps {stamps}"
        at = dict(self.fence)
        chk_steps = {
            "CHK-I2C-RW-PATTERNS": "S2",
            "CHK-I2C-RW-FIELD-INDEP": "S3",
            "CHK-I2C-RW-PERSIST": "S4",
            "CHK-I2C-RW-OBSERVED": "S5",
            "CHK-I2C-RO-IGNORED": "S6",
            "CHK-I2C-ROWO-OBSERVED": "S7",
            "CHK-I2C-CTRL-FIELDS": "S8",
            "CHK-I2C-CTRL-NEIGHBOURS": "S9",
            "CHK-I2C-ISOLATION-MATRIX": "S10",
            "CHK-I2C-CTRL-NO-ENGINE": "S11",
        }
        for chk_id, step in chk_steps.items():
            assert chk_id in self.chk_stamps, f"{chk_id} never printed"
            assert self.chk_stamps[chk_id] >= at[step], f"{chk_id} printed before {step}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s ps",
            ",".join(order),
            ",".join(chk_steps),
            ",".join(str(s) for s in stamps),
        )
