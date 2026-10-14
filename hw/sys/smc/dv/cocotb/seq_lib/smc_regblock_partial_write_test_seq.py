# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Byte writes that leave a set field alone, and writes that must not clear or fire.

Each PeakRDL field updates as `(value & ~biten) | (data & biten)`, and a W1C
field clears as `value & ~(data & biten)`. This sequence drives the half of
each term that keeps a set field -- a one held while a write strobes other
lanes, a W1C one held across a write that carries a zero on it -- and a write
of zero into a `singlepulse` trigger. Every field and mask here comes from the
block's generated header.

* **Held across a byte write on another lane.** `I2C_CTRL.SMBUS_EN` on all
  three instances (set by a byte write to its own lane, then held across a byte
  write to lane 0) and I2C0 `SMBUS_CTRL.SMBALERT` (held across a byte write to
  an empty lane). Each is read back after every step and restored.
* **W1C held across a zero, then cleared.** Six I2C0 `INTR_STATE` events and the
  log engine's `INTR_STATUS.LOG_FETCH_ERR` are raised through their `INTR_TEST`
  registers, survive a full write of zero, and clear on a write of one.
* **Zero into a trigger or a status.** A full write of zero to log-engine
  `INTR_TEST`, OCTS `TIMER_START` (`singlepulse`) and telemetry-receiver
  `INTR_STATUS` changes nothing that reads back.
* **Writes whose only effect is documented.** OCTS `CREDIT_EXPIRED` is an
  external register that `system_timer_octs.rdl` resets on any write, so a
  write must leave it reading 0. I2C0 `TARGET_NACK_COUNT` is `rclr` and holds 0
  at idle, so a read returns 0.
* **A flush held across a partial write.** Telemetry-receiver
  `CTRL.TELEMETRY_TX_FLUSH` is `hwclr` and clears on the ATB flush handshake,
  AFREADY with AFVALID. With receiver 0's AFREADY held low by the bench, the flush
  stays set, so a byte write to lane 0 must leave it set, and so must a
  full-word write of 1 to it. Raising AFREADY then clears it.
* **A byte write at FCR+1.** The UART sends a write to the write-only block only
  when its address is exactly THR or FCR (`uart_16550.sv`). A byte write at
  FCR+1 therefore reaches the main block, where it lands on the read-only IIR
  word. `IIR` must read the same afterwards, FIFOs still off.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import _REPO, _field_mask, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_log_engine_utils import FCR_OFFSET, IIR_FIFOS_ENABLED, uart_base, uart_reg

_I2C_H = _REPO / "hw" / "ip" / "i2c" / "regs" / "gen" / "c" / "i2c.h"
_I2C_CTRL_H = _REPO / "hw" / "ip" / "i2c" / "regs" / "gen" / "c" / "i2c_ctrl.h"
_LOG_H = _REPO / "hw" / "ip" / "uart" / "log_engine" / "regs" / "gen" / "c" / "log_engine.h"
_TEL_H = _REPO / "hw" / "ip" / "telemetry_receiver" / "regs" / "gen" / "c" / "telemetry_receiver.h"

SMBUS_EN = _field_mask(_I2C_CTRL_H, "I2C_CTRL__I2C_CTRL__SMBUS_EN_bm")
SMBALERT_OUT = _field_mask(_I2C_H, "I2C__SMBUS_CTRL__SMBALERT_bm")
_I2C_EVENTS = (
    "RX_OVERFLOW",
    "SDA_UNSTABLE",
    "UNEXP_STOP",
    "SMBALERT",
    "CONTROLLER_RX_FIFO_ERROR",
    "TARGET_RX_FIFO_ERROR",
)
I2C_EVENT_MASK = 0
for _name in _I2C_EVENTS:
    assert _field_mask(_I2C_H, f"I2C__INTR_TEST__{_name}_bm") == _field_mask(
        _I2C_H, f"I2C__INTR_STATE__{_name}_bm"
    ), f"INTR_TEST and INTR_STATE place {_name} differently"
    I2C_EVENT_MASK |= _field_mask(_I2C_H, f"I2C__INTR_STATE__{_name}_bm")
LOG_FETCH_ERR = _field_mask(_LOG_H, "LOG_ENGINE__INTR_STATUS__LOG_FETCH_ERR_bm")
assert LOG_FETCH_ERR == _field_mask(_LOG_H, "LOG_ENGINE__INTR_TEST__LOG_FETCH_ERR_bm")
MISSING_LAST = _field_mask(_TEL_H, "TELEMETRY_RECEIVER__INTR_STATUS__MISSING_LAST_bm")
TEL_CTRL = smc_indexed_addr(
    "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_CTRL_BASE_ADDR", 0
)
TX_FLUSH = _field_mask(_TEL_H, "TELEMETRY_RECEIVER__CTRL__TELEMETRY_TX_FLUSH_bm")
CTRL_PULSES = _field_mask(_TEL_H, "TELEMETRY_RECEIVER__CTRL__BUFFER_POP_bm") | _field_mask(
    _TEL_H, "TELEMETRY_RECEIVER__CTRL__TELEMETRY_RX_FLUSH_bm"
)
CREDIT_EXPIRED = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_CREDIT_EXPIRED_BASE_ADDR")

NUM_I2C_CTRL = smc_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_NUM")


def i2c_ctrl(i: int) -> int:
    return smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", i)


def i2c(reg: str) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_I2C_WRAP_I2C_{reg}_BASE_ADDR", 0)


def log_engine(reg: str) -> int:
    return smc_indexed_addr(
        f"SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_{reg}_BASE_ADDR", 0
    )


TIMER_START = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_START_BASE_ADDR")
TEL_INTR_STATUS = smc_indexed_addr(
    "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_INTR_STATUS_BASE_ADDR", 0
)


def _byte(value: int, lane: int) -> int:
    return (value >> (8 * lane)) & 0xFF


class smc_regblock_partial_write_test_seq(SmcCsrSeq):
    """Partial and zero writes that must leave set fields and triggers alone."""

    def __init__(self, name: str = "smc_regblock_partial_write_test_seq") -> None:
        super().__init__(name)
        self.held = 0
        self.w1c_held = 0
        self.zero_writes = 0
        self.documented = 0

    async def _smbus_en(self, i: int) -> None:
        addr = i2c_ctrl(i)
        lane = (SMBUS_EN.bit_length() - 1) // 8
        assert lane != 0, "SMBUS_EN shares lane 0 with I2C_EN"
        base = await self.csr_read(f"I2C_CTRL{i}_BASE", addr)
        assert not base & SMBUS_EN, f"I2C_CTRL[{i}] reads 0x{base:x} with SMBUS_EN already set"
        on = base | SMBUS_EN
        await self.csr_write(f"I2C_CTRL{i}_SET", addr + lane, _byte(on, lane), length=1)
        await self.csr_read(f"I2C_CTRL{i}_SET_RB", addr, expected=on)
        await self.csr_write(f"I2C_CTRL{i}_LANE0", addr, _byte(on, 0), length=1)
        await self.csr_read(f"I2C_CTRL{i}_HELD_RB", addr, expected=on)
        await self.csr_write(f"I2C_CTRL{i}_RESTORE", addr + lane, _byte(base, lane), length=1)
        await self.csr_read(f"I2C_CTRL{i}_RESTORE_RB", addr, expected=base)
        self.held += 1

    async def _smbalert_out(self) -> None:
        addr = i2c("SMBUS_CTRL")
        base = await self.csr_read("SMBUS_CTRL_BASE", addr)
        assert not base & SMBALERT_OUT, f"SMBUS_CTRL reads 0x{base:x} with SMBALERT set"
        await self.csr_write("SMBUS_CTRL_SET", addr, base | SMBALERT_OUT)
        await self.csr_read("SMBUS_CTRL_SET_RB", addr, expected=base | SMBALERT_OUT)
        # Lane 1 holds no SMBUS_CTRL field; a byte write there strobes none of them.
        await self.csr_write("SMBUS_CTRL_LANE1", addr + 1, 0, length=1)
        await self.csr_read("SMBUS_CTRL_HELD_RB", addr, expected=base | SMBALERT_OUT)
        await self.csr_write("SMBUS_CTRL_RESTORE", addr, base)
        await self.csr_read("SMBUS_CTRL_RESTORE_RB", addr, expected=base)
        self.held += 1

    async def _w1c_held(self, tag: str, test: int, state: int, mask: int) -> None:
        # Clear what is already latched (I2C0's SMBALERT event follows the SMBALERT
        # output driven above) so the raise below is this leaf's own.
        await self.csr_write(f"{tag}_PRECLEAR", state, mask)
        before = await self.csr_read(f"{tag}_BEFORE_RB", state)
        assert not before & mask, f"{tag}: 0x{before:x} still has bits of 0x{mask:x} set"
        await self.csr_write(f"{tag}_TEST", test, mask)
        raised = await self.csr_read(f"{tag}_RAISED", state)
        assert raised & mask == mask, f"{tag}: INTR_TEST 0x{mask:x} raised only 0x{raised & mask:x}"
        await self.csr_write(f"{tag}_ZERO", state, 0)
        kept = await self.csr_read(f"{tag}_KEPT", state)
        assert kept & mask == mask, (
            f"{tag}: a write of zero cleared 0x{mask & ~kept:x}; these fields clear on a one"
        )
        await self.csr_write(f"{tag}_CLEAR", state, mask)
        cleared = await self.csr_read(f"{tag}_CLEARED", state)
        assert not cleared & mask, f"{tag}: a write of 0x{mask:x} left 0x{cleared & mask:x} set"
        self.w1c_held += 1

    async def _zero(self, tag: str, addr: int) -> None:
        before = await self.csr_read(f"{tag}_BEFORE", addr)
        await self.csr_write(f"{tag}_ZERO", addr, 0)
        await self.csr_read(f"{tag}_AFTER", addr, expected=before)
        self.zero_writes += 1

    async def _documented_writes(self) -> None:
        await self.csr_write("OCTS_CREDIT_EXPIRED_WRITE", CREDIT_EXPIRED, 0)
        await self.csr_read("OCTS_CREDIT_EXPIRED_RB", CREDIT_EXPIRED, expected=0)
        await self.csr_read("I2C0_TARGET_NACK_COUNT", i2c("TARGET_NACK_COUNT"), expected=0)

        self.documented += 2

    async def _flush_held(self) -> None:
        dut = cocotb.top
        lane = (TX_FLUSH.bit_length() - 1) // 8
        assert lane != 0, "TELEMETRY_TX_FLUSH shares lane 0 with the pulse fields"
        base = await self.csr_read("TEL_CTRL_BASE", TEL_CTRL)
        assert not base & (TX_FLUSH | CTRL_PULSES), f"telemetry CTRL 0x{base:x} not idle"
        dut.tb_telemetry0_afready.value = 0
        try:
            await self.csr_write("TEL_CTRL_FLUSH", TEL_CTRL, base | TX_FLUSH)
            await self.csr_read("TEL_CTRL_FLUSH_HELD", TEL_CTRL, expected=base | TX_FLUSH)
            await self.csr_write("TEL_CTRL_LANE0", TEL_CTRL, base & 0xFF, length=1)
            await self.csr_read("TEL_CTRL_FLUSH_KEPT", TEL_CTRL, expected=base | TX_FLUSH)
            await self.csr_write("TEL_CTRL_FLUSH_AGAIN", TEL_CTRL, base | TX_FLUSH)
            await self.csr_read("TEL_CTRL_FLUSH_AGAIN_KEPT", TEL_CTRL, expected=base | TX_FLUSH)
        finally:
            dut.tb_telemetry0_afready.value = 1
        await ClockCycles(dut.clk_smc_i, 8)
        await self.csr_read("TEL_CTRL_FLUSH_DONE", TEL_CTRL, expected=base)
        self.documented += 1

    async def _fcr_plus_one(self) -> None:
        iir = uart_reg(0, "IIR")
        before = await self.csr_read("UART0_IIR_BEFORE", iir)
        assert not before & IIR_FIFOS_ENABLED, f"UART0 IIR 0x{before:x} with FIFOs enabled"
        await self.csr_write("UART0_FCR_PLUS_1", uart_base(0) + FCR_OFFSET + 1, 0xFF, length=1)
        await self.csr_read("UART0_IIR_AFTER", iir, expected=before)
        self.documented += 1

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        for i in range(NUM_I2C_CTRL):
            await self._smbus_en(i)
        await self._smbalert_out()
        cocotb.log.info(
            "CHK-REGBLOCK-PARTIAL-HOLD: SMBUS_EN on %d I2C_CTRL instances and I2C0 "
            "SMBUS_CTRL.SMBALERT each read back set after a byte write to another lane, "
            "and each was restored and read back",
            NUM_I2C_CTRL,
        )

        await self.csr_read("I2C0_INTR_ENABLE", i2c("INTR_ENABLE"), expected=0)
        await self.csr_read("LOG_INTR_ENABLE", log_engine("INTR_ENABLE"), expected=0)
        await self._w1c_held("I2C0_INTR", i2c("INTR_TEST"), i2c("INTR_STATE"), I2C_EVENT_MASK)
        await self._w1c_held(
            "LOG_INTR", log_engine("INTR_TEST"), log_engine("INTR_STATUS"), LOG_FETCH_ERR
        )
        cocotb.log.info(
            "CHK-REGBLOCK-W1C-HOLD: I2C0 INTR_STATE 0x%x and log-engine INTR_STATUS 0x%x, "
            "raised through INTR_TEST, survived a write of zero and cleared on a write of one",
            I2C_EVENT_MASK,
            LOG_FETCH_ERR,
        )

        await self._zero("LOG_INTR_TEST", log_engine("INTR_TEST"))
        await self._zero("OCTS_TIMER_START", TIMER_START)
        before = await self.csr_read("TEL_INTR_STATUS_PRE", TEL_INTR_STATUS)
        assert not before & MISSING_LAST, f"telemetry INTR_STATUS 0x{before:x} has MISSING_LAST"
        await self._zero("TEL_INTR_STATUS", TEL_INTR_STATUS)
        cocotb.log.info(
            "CHK-REGBLOCK-ZERO-WRITE: full writes of zero to log-engine INTR_TEST, OCTS "
            "TIMER_START and telemetry INTR_STATUS left each reading what it read before"
        )

        await self._documented_writes()
        await self._flush_held()
        await self._fcr_plus_one()
        cocotb.log.info(
            "CHK-REGBLOCK-DOCUMENTED-WRITE: a write reset OCTS CREDIT_EXPIRED to 0, I2C0 "
            "TARGET_NACK_COUNT read 0 at idle, telemetry TX_FLUSH held across a lane-0 byte "
            "write and a full-word rewrite of 1 while AFREADY was low and cleared once it rose, and a byte write at UART0 "
            "FCR+1 left IIR unchanged with the FIFOs off"
        )
