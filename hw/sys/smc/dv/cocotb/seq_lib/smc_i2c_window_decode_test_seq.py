# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C window decode: instance blocks, I2C_CTRL, reset state, the unclaimed gap, aligned access.

Sources: hw/ip/i2c/regs/i2c.rdl, hw/ip/i2c/regs/i2c_wrap.rdl, hw/ip/i2c/regs/i2c_ctrl.rdl,
hw/ip/i2c/doc/memmap.adoc, hw/ip/i2c/doc/index.adoc.

Every access is a 32-bit aligned SEP_IN frontdoor access straight after bring-up. The reset
reads run before any write to an I2C register; the GPIO pad-select writes of the I2C pad groups
come first so that SMBUS_STATUS senses the idle SMBus pads. Offsets of I2C_CTRL,
reserved bits, registers without a reset literal and the FIFO read ports, the access
latency and VAL: the specification does not state the values;
they are logged without a compare, as are the
responses of the four gap writes.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import _parse_simple_defines, reg_reset_word, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_CTRL_ENABLEHOST,
    I2C_CTRL_ENABLETARGET,
    I2C_WRAP_SMBUS_EN,
)
from .smc_i2c_master_target_test_seq import _I2C_CTRL_H, _I2C_H, _i2c_u32

INSTANCES = (0, 1, 2)
WORD_BYTES = 4
AXI_DECERR = 3
ERR_SIGNATURE = SmcCsrSeq.ERR_SLAVE_SIGNATURE
STATUS_RESET = 0x33C
GAP_WRITE_DATA = 0xA5A5_5A5A
ALTERNATIONS = 32
CLOCK_EDGE_BOUND = 64

WINDOW_BASE = smc_addr("SMC_TOP_SMC_I2C_WRAP_BASE_ADDR")
INSTANCES_END = smc_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TOTAL_SIZE")
CTRL_REGS_BASE = smc_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_BASE_ADDR")
GAP_FIRST = WINDOW_BASE + INSTANCES_END
GAP_LAST = CTRL_REGS_BASE - WORD_BYTES
GAP_MIDDLE = (GAP_FIRST + GAP_LAST) // 2 // WORD_BYTES * WORD_BYTES
GAP_WORDS = (
    ("first", GAP_FIRST),
    ("middle", GAP_MIDDLE),
    ("last", GAP_LAST),
    ("quarter", (GAP_FIRST + GAP_MIDDLE) // 2 // WORD_BYTES * WORD_BYTES),
)

_I2C_DEFINES = _parse_simple_defines(_I2C_H)
_CTRL_DEFINES = _parse_simple_defines(_I2C_CTRL_H)


def _reg(register: str, idx: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_I2C_WRAP_I2C_{register}_BASE_ADDR", idx)


def _wrap_ctrl(idx: int) -> int:
    return smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", idx)


def _declared_mask(register: str) -> int:
    prefix = f"I2C__{register}__"
    mask = 0
    for name, value in _I2C_DEFINES.items():
        if name.startswith(prefix) and name.endswith("_bm"):
            mask |= value
    assert mask, f"no fields of {register} in the generated i2c.h"
    return mask


def _reset(register: str) -> int:
    return reg_reset_word(_I2C_H, "I2C", register)


def _offset(register: str) -> int:
    return _reg(register, 0) - WINDOW_BASE


WRAP_CTRL_MASK = 0
for _name, _value in _CTRL_DEFINES.items():
    if _name.startswith("I2C_CTRL__I2C_CTRL__") and _name.endswith("_bm"):
        WRAP_CTRL_MASK |= _value
WRAP_CTRL_RESET = reg_reset_word(_I2C_CTRL_H, "I2C_CTRL", "I2C_CTRL")

RESET_REGISTERS = (
    "INTR_ENABLE",
    "SMBUS_CTRL",
    "CTRL",
    "HOST_FIFO_CONFIG",
    "TARGET_FIFO_CONFIG",
    "TARGET_FIFO_STATUS",
    "OVRD",
    "TIMING0",
    "TIMING1",
    "TIMING2",
    "TIMING3",
    "TIMING4",
    "TIMEOUT_CTRL",
    "TARGET_ID",
    "HOST_TIMEOUT_CTRL",
    "TARGET_TIMEOUT_CTRL",
    "TARGET_ACK_CTRL",
    "ACQ_FIFO_NEXT_DATA",
    "HOST_NACK_HANDLER_TIMEOUT",
    "CONTROLLER_EVENTS",
    "TARGET_EVENTS",
    "SMBUS_STATUS",
)
STATUS_TYPE_INTR = (
    "FMT_THRESHOLD",
    "RX_THRESHOLD",
    "ACQ_THRESHOLD",
    "CONTROLLER_HALT",
    "TX_STRETCH",
    "TX_THRESHOLD",
    "ACQ_STRETCH",
)
STATUS_TYPE_MASK = 0
for _field in STATUS_TYPE_INTR:
    STATUS_TYPE_MASK |= _i2c_u32(f"I2C__INTR_STATE__{_field}_bm")
INTR_EVENT_MASK = _declared_mask("INTR_STATE") & ~STATUS_TYPE_MASK

SIDE_REGISTERS = ("HOST_FIFO_STATUS", "RDATA", "ACQDATA", "TARGET_NACK_COUNT", "VAL")

WRITABLE_MASKS = {
    "INTR_ENABLE": _declared_mask("INTR_ENABLE"),
    "SMBUS_CTRL": _declared_mask("SMBUS_CTRL"),
    "CTRL": _declared_mask("CTRL") & ~(I2C_CTRL_ENABLEHOST | I2C_CTRL_ENABLETARGET),
    "HOST_FIFO_CONFIG": _declared_mask("HOST_FIFO_CONFIG"),
    "TARGET_FIFO_CONFIG": _declared_mask("TARGET_FIFO_CONFIG"),
    "OVRD": _i2c_u32("I2C__OVRD__SCLVAL_bm") | _i2c_u32("I2C__OVRD__SDAVAL_bm"),
    "TIMING0": _declared_mask("TIMING0"),
    "TIMING1": _declared_mask("TIMING1"),
    "TIMING2": _declared_mask("TIMING2"),
    "TIMING3": _declared_mask("TIMING3"),
    "TIMING4": _declared_mask("TIMING4"),
    "TIMEOUT_CTRL": _declared_mask("TIMEOUT_CTRL"),
    "TARGET_ID": _declared_mask("TARGET_ID"),
    "HOST_TIMEOUT_CTRL": _declared_mask("HOST_TIMEOUT_CTRL"),
    "TARGET_TIMEOUT_CTRL": _declared_mask("TARGET_TIMEOUT_CTRL"),
    "HOST_NACK_HANDLER_TIMEOUT": _declared_mask("HOST_NACK_HANDLER_TIMEOUT"),
}
OFFSET_GROUPS = ((0x00, 0x2C), (0x30, 0x5C), (0x60, 0x80))

RX_OVERFLOW = _i2c_u32("I2C__INTR_STATE__RX_OVERFLOW_bm")
RX_OVERFLOW_TEST = _i2c_u32("I2C__INTR_TEST__RX_OVERFLOW_bm")

FENCE_STEPS = tuple(f"S{n}" for n in range(1, 11))
CHK_STEPS = {
    "CHK-I2C-RESET-STATUS": ("S2",),
    "CHK-I2C-RESET-LITERALS": ("S2",),
    "CHK-I2C-RESERVED-OBS": ("S3",),
    "CHK-I2C-RESET-SIDE-OBS": ("S4",),
    "CHK-I2C-CTRL-RESET": ("S5",),
    "CHK-I2C-GAP-READ-DECERR": ("S6",),
    "CHK-I2C-DECODE-IDENTITY": ("S7",),
    "CHK-I2C-DECODE-ALTERNATE": ("S8",),
    "CHK-I2C-GAP-NO-SIDE-EFFECT": ("S9",),
    "CHK-I2C-ACCESS-ALIGNED": ("S10",),
}


def _pattern(instance: int, register: str, mask: int, salt: int = 0) -> int:
    """A nonzero value inside `mask`, different for every (instance, register, salt)."""
    seed = (instance + 1 + 4 * salt) * 0x9E3779B1 + (_offset(register) + 1) * 0x85EBCA6B
    x = seed & 0xFFFFFFFF
    x ^= x >> 15
    x = (x * 0x2C1B3C6D) & 0xFFFFFFFF
    x ^= x >> 12
    value = x & mask
    return value or mask & -mask


class smc_i2c_window_decode_test_seq(SmcCsrSeq):
    """Decode, reset state, gap response and aligned access of the I2C window."""

    def __init__(self, name: str = "smc_i2c_window_decode_test_seq") -> None:
        super().__init__(name)
        self.fence: list[tuple[str, int]] = []
        self.chk_stamps: dict[str, int] = {}
        self.deferred: list[str] = []
        self.reset_reads: dict[tuple[int, str], int] = {}

    def _mark(self, step: str) -> None:
        self.fence.append((step, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, text: str, *args) -> None:
        self.chk_stamps[chk_id] = int(get_sim_time("ps"))
        cocotb.log.info(f"{chk_id}: {text}", *args)

    @staticmethod
    def _irq_word() -> int:
        sig = cocotb.top.tb_i2c_irq
        assert sig.value.is_resolvable, f"tb_i2c_irq = {sig.value} is X/Z"
        return int(sig.value)

    async def _observe(
        self, name: str, addr: int, write: bool = False, data: int = 0, *, error: bool = True
    ) -> tuple[int, int]:
        item = SmcSysAxiItem(f"{'wr' if write else 'rd'}_{name}")
        item.op = SmcSysAxiOp.WRITE if write else SmcSysAxiOp.READ
        item.addr = addr
        item.wdata = data
        item.allow_error = True
        item.expect_error = error
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None, f"{name} @ 0x{addr:08x}: no response code"
        return item.resp_code, item.rdata

    async def _clock_period_ns(self) -> float:
        clk = cocotb.top.clk_smc_i
        await RisingEdge(clk)
        first = get_sim_time("ns")
        await RisingEdge(clk)
        period = get_sim_time("ns") - first
        assert period > 0, f"clk_smc_i period measured {period} ns"
        return period

    async def _step_s2(self) -> None:
        for n in INSTANCES:
            status = await self.csr_read(f"STATUS{n}", _reg("STATUS", n))
            assert status == STATUS_RESET, (
                f"STATUS[{n}] reads 0x{status:08x}, reset literals compose 0x{STATUS_RESET:03x}"
            )
            assert _reset("STATUS") == STATUS_RESET
            self.reset_reads[(n, "STATUS")] = status
        for n in INSTANCES:
            for register in RESET_REGISTERS:
                value = await self.csr_read(f"{register}{n}", _reg(register, n))
                declared = _declared_mask(register)
                assert value & declared == _reset(register), (
                    f"{register}[{n}] reads 0x{value:08x}; declared fields 0x{declared:08x} "
                    f"hold 0x{value & declared:08x}, RDL reset 0x{_reset(register):08x}"
                )
                self.reset_reads[(n, register)] = value
            state = await self.csr_read(f"INTR_STATE{n}", _reg("INTR_STATE", n))
            assert state & INTR_EVENT_MASK == 0, (
                f"INTR_STATE[{n}] event bits read 0x{state & INTR_EVENT_MASK:08x} at reset"
            )
            self.reset_reads[(n, "INTR_STATE")] = state
        self._mark("S2")
        self._chk(
            "CHK-I2C-RESET-STATUS",
            "STATUS of instances 0,1,2 read OKAY with %s (bits 2,3,4,5,8,9)",
            ",".join(f"0x{self.reset_reads[(n, 'STATUS')]:03x}" for n in INSTANCES),
        )
        status_type = ",".join(
            f"INTR_STATE[{n}]=0x{self.reset_reads[(n, 'INTR_STATE')] & STATUS_TYPE_MASK:05x}"
            for n in INSTANCES
        )
        self._chk(
            "CHK-I2C-RESET-LITERALS",
            "%d registers x %d instances read OKAY with their RDL reset 0x0 in every declared "
            "field, INTR_STATE event bits 0x%05x read 0x0; status-type INTR_STATE bits logged "
            "%s; reset-value-only proof",
            len(RESET_REGISTERS),
            len(INSTANCES),
            INTR_EVENT_MASK,
            status_type,
        )

    async def _step_s3(self) -> None:
        residues = []
        for n in INSTANCES:
            for register in ("STATUS", *RESET_REGISTERS, "INTR_STATE"):
                value = self.reset_reads[(n, register)]
                residue = value & ~_declared_mask(register) & 0xFFFFFFFF
                if residue:
                    residues.append(f"{register}[{n}]=0x{residue:08x}")
        ctrl = []
        for n in INSTANCES:
            value = await self.csr_read(f"I2C_CTRL_RESERVED{n}", _wrap_ctrl(n))
            ctrl.append(f"I2C_CTRL[{n}]=0x{value & ~WRAP_CTRL_MASK & 0xFFFFFFFF:08x}")
        self._mark("S3")
        self._chk(
            "CHK-I2C-RESERVED-OBS",
            "reserved-bit residue (value & ~declared_mask) of %d register reads, nonzero: %s; "
            "%s (observation, not specified, measured)",
            len(INSTANCES) * (len(RESET_REGISTERS) + 2),
            " ".join(residues) or "none",
            " ".join(ctrl),
        )

    async def _step_s4(self) -> None:
        seen = []
        for n in INSTANCES:
            for register in SIDE_REGISTERS:
                resp, value = await self._observe(f"{register}{n}", _reg(register, n), error=False)
                seen.append(f"{register}[{n}]:resp={resp},val=0x{value:08x}")
            status = await self.csr_read(f"STATUS_REREAD{n}", _reg("STATUS", n))
            assert status == STATUS_RESET, (
                f"STATUS[{n}] reads 0x{status:08x} after the {len(SIDE_REGISTERS)} reads"
            )
        self._mark("S4")
        self._chk(
            "CHK-I2C-RESET-SIDE-OBS",
            "%s; STATUS re-read 0x%03x on all instances (observation, not specified, measured)",
            " ".join(seen),
            STATUS_RESET,
        )

    async def _step_s5(self) -> None:
        words = []
        for n in INSTANCES:
            value = await self.csr_read(f"I2C_CTRL{n}", _wrap_ctrl(n))
            assert value == WRAP_CTRL_RESET, (
                f"I2C_CTRL[{n}] @ 0x{_wrap_ctrl(n):08x} reads 0x{value:08x}, "
                f"reset 0x{WRAP_CTRL_RESET:08x}"
            )
            words.append(value)
        spacing = [_wrap_ctrl(n + 1) - _wrap_ctrl(n) for n in (0, 1)]
        self._mark("S5")
        self._chk(
            "CHK-I2C-CTRL-RESET",
            "I2C_CTRL[0..2] at 0x%08x,0x%08x,0x%08x read OKAY with %s; element spacing %s "
            "(not specified, measured); reset-value-only proof",
            _wrap_ctrl(0),
            _wrap_ctrl(1),
            _wrap_ctrl(2),
            ",".join(f"0x{w:x}" for w in words),
            ",".join(f"0x{s:x}" for s in spacing),
        )

    async def _gap_read(self, label: str, addr: int, expect: bool) -> str:
        resp, rdata = await self._observe(f"GAP_{label}", addr)
        if expect and (resp != AXI_DECERR or rdata != ERR_SIGNATURE):
            self.deferred.append(
                f"gap read {label} @ 0x{addr:08x} gave resp={resp} rdata=0x{rdata:08x}, "
                f"the expected response is DECERR ({AXI_DECERR}) with 0x{ERR_SIGNATURE:08x}"
            )
        return f"{label}@0x{addr:08x}:resp={resp},rdata=0x{rdata:08x}"

    async def _step_s6(self) -> None:
        seen = []
        controls = (
            ("STATUS2", _reg("STATUS", 2), STATUS_RESET),
            ("I2C_CTRL0", _wrap_ctrl(0), WRAP_CTRL_RESET),
        )
        for label, addr in GAP_WORDS[:3]:
            for cname, caddr, cvalue in controls[:1]:
                got = await self.csr_read(f"PRE_{label}_{cname}", caddr)
                assert got == cvalue, f"{cname} positive control reads 0x{got:08x}"
            seen.append(await self._gap_read(label, addr, True))
            for cname, caddr, cvalue in controls[1:]:
                got = await self.csr_read(f"POST_{label}_{cname}", caddr)
                assert got == cvalue, f"{cname} positive control reads 0x{got:08x}"
        self._mark("S6")
        if self.deferred:
            return
        self._chk(
            "CHK-I2C-GAP-READ-DECERR",
            "%s each DECERR (3) with 0x%08x between OKAY reads of STATUS[2]=0x%03x and "
            "I2C_CTRL[0]=0x%x",
            " ".join(seen),
            ERR_SIGNATURE,
            STATUS_RESET,
            WRAP_CTRL_RESET,
        )

    async def _step_s7(self) -> None:
        readable = ("STATUS", "INTR_STATE", *RESET_REGISTERS)
        patterns = {
            (n, reg): _pattern(n, reg, mask)
            for n in INSTANCES
            for reg, mask in WRITABLE_MASKS.items()
        }
        wide = [p for (n, reg), p in patterns.items() if bin(WRITABLE_MASKS[reg]).count("1") >= 8]
        assert len(set(wide)) == len(wide), "write patterns of the wide registers collide"
        for n in INSTANCES:
            for reg in WRITABLE_MASKS:
                await self.csr_write(f"{reg}{n}_PAT", _reg(reg, n), patterns[(n, reg)])
            for reg in readable:
                value = await self.csr_read(f"{reg}{n}_PAT_RB", _reg(reg, n))
                if reg in WRITABLE_MASKS:
                    want, mask = patterns[(n, reg)], WRITABLE_MASKS[reg]
                elif reg == "STATUS":
                    want, mask = STATUS_RESET, 0xFFFFFFFF
                elif reg == "INTR_STATE":
                    want, mask = _reset(reg), INTR_EVENT_MASK
                else:
                    want, mask = _reset(reg), _declared_mask(reg)
                assert value & mask == want, (
                    f"{reg}[{n}] reads 0x{value:08x} after the pattern writes, expected "
                    f"0x{want:08x} under mask 0x{mask:08x}"
                )
            for other in INSTANCES:
                if other != n:
                    for reg in ("TARGET_ID", "INTR_ENABLE", "TIMING0"):
                        value = await self.csr_read(f"{reg}{other}_ISO", _reg(reg, other))
                        assert value == self.reset_reads[(other, reg)], (
                            f"{reg}[{other}] reads 0x{value:08x} while instance {n} holds "
                            f"its pattern"
                        )
            for reg in WRITABLE_MASKS:
                await self.csr_write(f"{reg}{n}_RST", _reg(reg, n), _reset(reg))
            for reg in readable:
                value = await self.csr_read(f"{reg}{n}_RST_RB", _reg(reg, n))
                mask = INTR_EVENT_MASK if reg == "INTR_STATE" else _declared_mask(reg)
                want = STATUS_RESET if reg == "STATUS" else _reset(reg)
                assert value & mask == want, (
                    f"{reg}[{n}] reads 0x{value:08x} after the restore, reset 0x{want:08x}"
                )
        groups = [
            sum(1 for reg in WRITABLE_MASKS if lo <= _offset(reg) <= hi) for lo, hi in OFFSET_GROUPS
        ]
        self._mark("S7")
        self._chk(
            "CHK-I2C-DECODE-IDENTITY",
            "%d rw registers per instance on instances 0,1,2 each read their own pattern and no "
            "unwritten register changed, restore returned the reset; written registers per "
            "offset group 0x00-0x2c/0x30-0x5c/0x60-0x80: %s",
            len(WRITABLE_MASKS),
            "/".join(str(g) for g in groups),
        )

    async def _step_s8(self) -> None:
        period = float(self.cfg.smc_clk_period_ns)
        tid_mask = WRITABLE_MASKS["TARGET_ID"]
        self.tid = {n: _pattern(n, "TARGET_ID", tid_mask, salt=1) for n in INSTANCES}
        assert len(set(self.tid.values())) == len(INSTANCES)
        for n in INSTANCES:
            await self.csr_write(f"TARGET_ID{n}_ALT", _reg("TARGET_ID", n), self.tid[n])
        await self.csr_write("I2C_CTRL0_ALT", _wrap_ctrl(0), I2C_WRAP_SMBUS_EN)
        targets = [(_reg("TARGET_ID", n), self.tid[n], tid_mask) for n in INSTANCES]
        wrap = (_wrap_ctrl(0), I2C_WRAP_SMBUS_EN, WRAP_CTRL_MASK)
        pairs = ((targets[0], targets[1]), (targets[2], wrap))
        worst_ns = 0.0
        for pair in pairs:
            for i in range(ALTERNATIONS):
                addr, want, mask = pair[i % 2]
                start = get_sim_time("ns")
                value = await self.csr_read(f"ALT{i}_{addr:x}", addr)
                worst_ns = max(worst_ns, get_sim_time("ns") - start)
                assert value & mask == want, (
                    f"alternating read {i} @ 0x{addr:08x} returned 0x{value:08x}, "
                    f"the addressed block holds 0x{want:08x}"
                )
        self._mark("S8")
        self._chk(
            "CHK-I2C-DECODE-ALTERNATE",
            "%d alternating reads (instance 0/1 and instance 2/I2C_CTRL[0]) returned the pattern "
            "of the addressed block; max access time %.0f ns = %.1f clk_smc_i cycles of %.2f ns "
            "(not specified, measured)",
            2 * ALTERNATIONS,
            worst_ns,
            worst_ns / period,
            period,
        )

    async def _snapshot(self, tag: str) -> dict[str, int]:
        snap = {}
        for n in INSTANCES:
            for reg in ("STATUS", "TARGET_ID", "INTR_STATE", "CTRL"):
                snap[f"{reg}{n}"] = await self.csr_read(f"SNAP_{tag}_{reg}{n}", _reg(reg, n))
            snap[f"I2C_CTRL{n}"] = await self.csr_read(f"SNAP_{tag}_I2C_CTRL{n}", _wrap_ctrl(n))
        return snap

    async def _step_s9(self) -> None:
        before = await self._snapshot("PRE")
        irq_samples = [self._irq_word()]
        gap_reads, gap_writes = [], []
        for i in range(8):
            _, rdata = await self._observe(f"BURST_GAP_RD{i}", GAP_WORDS[i % 4][1])
            gap_reads.append(rdata)
            irq_samples.append(self._irq_word())
            n = i % 3
            status = await self.csr_read(f"BURST_STATUS{i}", _reg("STATUS", n))
            assert status == STATUS_RESET, f"STATUS[{n}] reads 0x{status:08x} inside the burst"
            irq_samples.append(self._irq_word())
            if i % 2:
                resp, _ = await self._observe(
                    f"BURST_GAP_WR{i}", GAP_WORDS[(i // 2) % 4][1], True, GAP_WRITE_DATA
                )
                gap_writes.append(resp)
                irq_samples.append(self._irq_word())
                await self.csr_write(f"BURST_TID{i}", _reg("TARGET_ID", n), self.tid[n])
                got = await self.csr_read(f"BURST_TID_RB{i}", _reg("TARGET_ID", n))
                assert got & WRITABLE_MASKS["TARGET_ID"] == self.tid[n], (
                    f"TARGET_ID[{n}] reads 0x{got:08x} inside the burst"
                )
                irq_samples.append(self._irq_word())
        after = await self._snapshot("POST")
        moved = [
            f"{k}:0x{before[k]:08x}->0x{after[k]:08x}" for k in before if before[k] != after[k]
        ]
        assert not moved, f"snapshot changed across the gap burst: {' '.join(moved)}"
        assert set(irq_samples) == {0}, f"tb_i2c_irq samples during the burst: {irq_samples}"
        self._mark("S9")
        self._chk(
            "CHK-I2C-GAP-NO-SIDE-EFFECT",
            "%d gap reads and %d gap writes (write resp codes %s, logged, not specified) "
            "interleaved "
            "with OKAY accesses left all %d snapshot words equal; tb_i2c_irq 0b000 on %d samples",
            len(gap_reads),
            len(gap_writes),
            ",".join(str(r) for r in gap_writes),
            len(before),
            len(irq_samples),
        )

    async def _step_s10(self) -> None:
        reg = _reg("TARGET_ID", 0)
        mask = WRITABLE_MASKS["TARGET_ID"]
        word = _pattern(0, "TARGET_ID", mask, salt=2)
        assert word != self.tid[0]
        await self.csr_write_strobed("ALIGNED_TID", reg, word, 0xF)
        got = await self.csr_read("ALIGNED_TID_RB", reg)
        assert got & mask == word, f"TARGET_ID[0] reads 0x{got:08x}, written 0x{word:08x}"
        status = await self.csr_read("ALIGNED_STATUS", _reg("STATUS", 0))
        assert status == STATUS_RESET, f"STATUS[0] reads 0x{status:08x}"
        await self.csr_write_strobed("ALIGNED_TEST", _reg("INTR_TEST", 0), RX_OVERFLOW_TEST, 0xF)
        state = await self.csr_read("ALIGNED_STATE_SET", _reg("INTR_STATE", 0))
        assert state & RX_OVERFLOW, f"INTR_STATE[0] reads 0x{state:08x}, bit 3 is clear"
        await self.csr_write_strobed("ALIGNED_W1C", _reg("INTR_STATE", 0), RX_OVERFLOW, 0xF)
        cleared = await self.csr_read("ALIGNED_STATE_CLR", _reg("INTR_STATE", 0))
        assert cleared & RX_OVERFLOW == 0, f"INTR_STATE[0] reads 0x{cleared:08x}, bit 3 is set"
        self._mark("S10")
        self._chk(
            "CHK-I2C-ACCESS-ALIGNED",
            "strobe 0xf write of TARGET_ID[0]=0x%08x read back 0x%08x, STATUS[0]=0x%03x; "
            "lifecycle set=INTR_TEST[0] RX_OVERFLOW observed=INTR_STATE[0]=0x%08x "
            "cleared=INTR_STATE[0] W1C bit 3 checked_cleared=INTR_STATE[0]=0x%08x",
            word,
            got & mask,
            status,
            state,
            cleared,
        )

    async def body(self) -> None:
        dut = cocotb.top
        assert hasattr(dut, "tb_i2c_irq"), "tb_i2c_irq is not exported by tb_top"
        self.env.axi_monitor.expected_decerr_addrs.update(addr for _, addr in GAP_WORDS)
        assert self._irq_word() == 0, "tb_i2c_irq is not 0b000 after bring-up"
        period = await self._clock_period_ns()
        assert abs(period - float(self.cfg.smc_clk_period_ns)) < 1e-6, (
            f"clk_smc_i period {period} ns, configured {self.cfg.smc_clk_period_ns} ns"
        )
        for n in INSTANCES:
            await self.arm_i2c_gpio_lsio(n, f"PAD_ARM{n}")
        self._mark("S1")
        await self._step_s2()
        await self._step_s3()
        await self._step_s4()
        await self._step_s5()
        await self._step_s6()
        await self._step_s7()
        await self._step_s8()
        await self._step_s9()
        await self._step_s10()
        assert not self.deferred, "; ".join(self.deferred)

        order = [step for step, _ in self.fence]
        assert order == list(FENCE_STEPS), f"fence order {order}"
        stamps = [stamp for _, stamp in self.fence]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"fence stamps {stamps}"
        at = dict(self.fence)
        for chk_id, steps in CHK_STEPS.items():
            assert chk_id in self.chk_stamps, f"{chk_id} never printed"
            assert all(self.chk_stamps[chk_id] >= at[s] for s in steps), (
                f"{chk_id} printed before its step"
            )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s ps",
            ",".join(order),
            ",".join(CHK_STEPS),
            ",".join(str(s) for s in stamps),
        )
