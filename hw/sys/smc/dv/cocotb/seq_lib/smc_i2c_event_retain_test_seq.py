# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 event and counter fields as registers: what a write must and must not change.

`i2c.rdl` makes the `INTR_STATE` event bits, and the `TARGET_EVENTS` start and
stop flags, `woclr`: a written one clears them and nothing else does. Leaves
that raise these events clear them at once, so for most of them the write that
must *not* clear a set bit had never been made. This leaf makes it, and then
the one that must:

* **INTR_STATE.** Six event bits no leaf had held across a write are forced
  through `INTR_TEST` (`sw = w`, `singlepulse`: "Writing `1` forces the ...
  interrupt"): `RX_OVERFLOW`, `SDA_UNSTABLE`, `UNEXP_STOP`, `SMBALERT`,
  `CONTROLLER_RX_FIFO_ERROR` and `TARGET_RX_FIFO_ERROR`. Each is written a word
  of zeros and must read back set, then written its own one and must read
  back clear, with every other bit left as it was.
* **TARGET_EVENTS.** With the target enabled, a transfer from the bench
  controller sets `START_DETECT` and `STOP_DETECT` ("set to 1 by hardware when
  a START ... is detected"). Each is cleared by its own written one, and the
  other must survive that write.
* **SMBUS_CTRL.SMBALERT.** `hwclr`: "clears itself when the controller
  addresses this target". It is written set twice -- a write of the bit over
  itself must leave it set -- and must read clear after the transfer that
  addresses the target.
* **TARGET_NACK_COUNT.** `sw = rw`, `rclr`: a written value must read back
  once and then read zero.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, Timer

from .smc_addr_map import I2C_CG_EN, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_CTRL_ENABLETARGET,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_SMBUS_CTRL_SMBALERT,
    I2C_WRAP_CTRL_TARGET,
)
from .smc_i2c_master_target_test_seq import _i2c_u32
from .smc_i2c_protocol_vip import SmcI2cMasterVip
from .smc_i2c_target_ack_ctrl_test_seq import (
    CLOCK_GATE_CONTROL,
    I2C0_CTRL,
    I2C0_FIFO_CTRL,
    I2C0_OVRD,
    I2C0_TARGET_ID,
    I2C0_TIMING0,
    I2C0_TIMING1,
    I2C0_TIMING2,
    I2C0_TIMING3,
    I2C0_TIMING4,
    I2C0_WRAP_CTRL,
    _pack_target_id,
    _pack_timing0,
    _pack_timing1,
    _pack_timing2,
    _pack_timing3,
    _pack_timing4,
)


def _i2c0(register: str) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_I2C_WRAP_I2C_{register}_BASE_ADDR", 0)


I2C0_INTR_STATE = _i2c0("INTR_STATE")
I2C0_INTR_TEST = _i2c0("INTR_TEST")
I2C0_TARGET_EVENTS = _i2c0("TARGET_EVENTS")
I2C0_SMBUS_CTRL = _i2c0("SMBUS_CTRL")
I2C0_TARGET_NACK_COUNT = _i2c0("TARGET_NACK_COUNT")

INTR_BITS = tuple(
    (name, _i2c_u32(f"I2C__INTR_STATE__{name}_bm"), _i2c_u32(f"I2C__INTR_TEST__{name}_bm"))
    for name in (
        "RX_OVERFLOW",
        "SDA_UNSTABLE",
        "UNEXP_STOP",
        "SMBALERT",
        "CONTROLLER_RX_FIFO_ERROR",
        "TARGET_RX_FIFO_ERROR",
    )
)
START_DETECT = _i2c_u32("I2C__TARGET_EVENTS__START_DETECT_bm")
STOP_DETECT = _i2c_u32("I2C__TARGET_EVENTS__STOP_DETECT_bm")
ACQRST = _i2c_u32("I2C__FIFO_CTRL__ACQRST_bm")
NACK_COUNT_BM = _i2c_u32("I2C__TARGET_NACK_COUNT__TARGET_NACK_COUNT_bm")

TARGET_ADDR = 0x2C
VIP_SPEED = 2_000_000
PAYLOAD = bytes((0x4D,))
NACK_COUNT_VALUE = 0x5A
SETTLE_CYCLES = 200


class smc_i2c_event_retain_test_seq(SmcCsrSeq):
    """Hold I2C0 event bits across writes that must not clear them, then clear them."""

    def __init__(self, name: str = "smc_i2c_event_retain_test_seq") -> None:
        super().__init__(name)
        self.held: list[str] = []

    async def _intr_state_leg(self) -> None:
        await self.csr_write("INTR_CLR_ALL", I2C0_INTR_STATE, 0xFFFF_FFFF)
        baseline = await self.csr_read("INTR_BASELINE", I2C0_INTR_STATE)
        for name, state_bit, test_bit in INTR_BITS:
            assert not baseline & state_bit, (
                f"INTR_STATE.{name} is set before it is forced (0x{baseline:08x})"
            )
            await self.csr_write(f"{name}_TEST", I2C0_INTR_TEST, test_bit)
            forced = await self.csr_read(f"{name}_FORCED", I2C0_INTR_STATE)
            assert forced & state_bit and forced & ~state_bit == baseline & ~state_bit, (
                f"INTR_TEST.{name} left INTR_STATE at 0x{forced:08x} (baseline "
                f"0x{baseline:08x}); only its own bit may be set"
            )
            await self.csr_write(f"{name}_ZERO", I2C0_INTR_STATE, 0)
            kept = await self.csr_read(f"{name}_KEPT", I2C0_INTR_STATE)
            assert kept == forced, (
                f"INTR_STATE.{name}: a word of zeros changed the register from "
                f"0x{forced:08x} to 0x{kept:08x}; the bit clears only on a written one"
            )
            await self.csr_write(f"{name}_W1C", I2C0_INTR_STATE, state_bit)
            cleared = await self.csr_read(f"{name}_CLEARED", I2C0_INTR_STATE)
            assert cleared == forced & ~state_bit, (
                f"INTR_STATE.{name}: its written one left 0x{cleared:08x}, not "
                f"0x{forced & ~state_bit:08x}"
            )
            self.held.append(name)
        cocotb.log.info(
            "CHK-I2C-INTR-STATE-RETAIN: each of %s, forced through INTR_TEST, survived a word "
            "of zeros written over INTR_STATE and cleared on its own written one with every "
            "other bit unchanged",
            ", ".join(self.held),
        )

    async def _nack_count_leg(self) -> None:
        await self.csr_read("NACK_COUNT_ENTRY", I2C0_TARGET_NACK_COUNT)
        await self.csr_write("NACK_COUNT_WRITE", I2C0_TARGET_NACK_COUNT, NACK_COUNT_VALUE)
        first = await self.csr_read("NACK_COUNT_FIRST", I2C0_TARGET_NACK_COUNT)
        second = await self.csr_read("NACK_COUNT_SECOND", I2C0_TARGET_NACK_COUNT)
        assert first & NACK_COUNT_BM == NACK_COUNT_VALUE and second & NACK_COUNT_BM == 0, (
            f"TARGET_NACK_COUNT read 0x{first:02x} then 0x{second:02x} after a write of "
            f"0x{NACK_COUNT_VALUE:02x}; sw = rw with rclr reads the value once, then zero"
        )
        cocotb.log.info(
            "CHK-I2C-NACK-COUNT-WRITE: TARGET_NACK_COUNT read back the 0x%02x written to it "
            "once and zero on the read after",
            NACK_COUNT_VALUE,
        )

    async def _target_leg(self) -> None:
        await self.csr_write("I2C0_DISABLE", I2C0_CTRL, 0)
        await self.csr_write("I2C0_WRAP_TARGET", I2C0_WRAP_CTRL, I2C_WRAP_CTRL_TARGET)
        await self.wait_i2c0_lsio_ready("I2C0_EVENT_RETAIN")
        await self.csr_write("I2C0_OVRD_OFF", I2C0_OVRD, 0)
        await self.csr_write("I2C0_TIMING0", I2C0_TIMING0, _pack_timing0(0x1A, 0x32))
        await self.csr_write("I2C0_TIMING1", I2C0_TIMING1, _pack_timing1(2, 2))
        await self.csr_write("I2C0_TIMING2", I2C0_TIMING2, _pack_timing2(5, 4))
        await self.csr_write("I2C0_TIMING3", I2C0_TIMING3, _pack_timing3(2, 5))
        await self.csr_write("I2C0_TIMING4", I2C0_TIMING4, _pack_timing4(4, 5))
        await self.csr_write(
            "I2C0_FIFO_RST", I2C0_FIFO_CTRL, I2C_FIFO_CTRL_RXRST_FMTRST | I2C_FIFO_CTRL_TXRST
        )
        await self.csr_write(
            "I2C0_TARGET_ID", I2C0_TARGET_ID, _pack_target_id(TARGET_ADDR, 0x7F, 0, 0)
        )
        await self.csr_write("I2C0_CTRL_TARGET", I2C0_CTRL, I2C_CTRL_ENABLETARGET)
        await self.csr_write("EVENTS_CLR", I2C0_TARGET_EVENTS, START_DETECT | STOP_DETECT)
        events = await self.csr_read("EVENTS_ENTRY", I2C0_TARGET_EVENTS)
        assert not events & (START_DETECT | STOP_DETECT), (
            f"TARGET_EVENTS start or stop flag set before any transfer (0x{events:08x})"
        )

        for write in ("FIRST", "AGAIN"):
            await self.csr_write(f"SMBALERT_{write}", I2C0_SMBUS_CTRL, I2C_SMBUS_CTRL_SMBALERT)
            alert = await self.csr_read(f"SMBALERT_{write}_RB", I2C0_SMBUS_CTRL)
            assert alert & I2C_SMBUS_CTRL_SMBALERT, (
                f"SMBUS_CTRL.SMBALERT reads clear after write {write} (0x{alert:08x})"
            )

        master = SmcI2cMasterVip(speed=VIP_SPEED, name="smc_i2c0_retain_master")
        await Timer(1, unit="us")
        await master.write(TARGET_ADDR, PAYLOAD)
        await ClockCycles(cocotb.top.clk_smc_i, SETTLE_CYCLES)

        alert = await self.csr_read("SMBALERT_AFTER", I2C0_SMBUS_CTRL)
        assert not alert & I2C_SMBUS_CTRL_SMBALERT, (
            f"SMBUS_CTRL.SMBALERT still set after the controller addressed the target "
            f"(0x{alert:08x}); the RDL makes it clear itself on that address match"
        )
        events = await self.csr_read("EVENTS_SET", I2C0_TARGET_EVENTS)
        assert events & START_DETECT and events & STOP_DETECT, (
            f"TARGET_EVENTS=0x{events:08x} after a transfer to the target; both the start "
            f"and the stop flag must be set"
        )
        await self.csr_write("EVENTS_ZERO", I2C0_TARGET_EVENTS, 0)
        kept = await self.csr_read("EVENTS_KEPT", I2C0_TARGET_EVENTS)
        assert kept == events, (
            f"TARGET_EVENTS changed from 0x{events:08x} to 0x{kept:08x} on a word of zeros"
        )
        await self.csr_write("START_W1C", I2C0_TARGET_EVENTS, START_DETECT)
        after_start = await self.csr_read("EVENTS_AFTER_START", I2C0_TARGET_EVENTS)
        await self.csr_write("STOP_W1C", I2C0_TARGET_EVENTS, STOP_DETECT)
        after_stop = await self.csr_read("EVENTS_AFTER_STOP", I2C0_TARGET_EVENTS)
        assert not after_start & START_DETECT and after_start & STOP_DETECT, (
            f"after START_DETECT's written one TARGET_EVENTS reads 0x{after_start:08x}; the "
            f"start flag clears and the stop flag stays"
        )
        assert not after_stop & (START_DETECT | STOP_DETECT), (
            f"after STOP_DETECT's written one TARGET_EVENTS reads 0x{after_stop:08x}"
        )

        await self.csr_write("I2C0_CTRL_OFF", I2C0_CTRL, 0)
        await self.csr_write("ACQ_RESET", I2C0_FIFO_CTRL, ACQRST)
        cocotb.log.info(
            "CHK-I2C-TARGET-EVENTS-CLEAR: a transfer to the target set TARGET_EVENTS start and "
            "stop flags, a word of zeros left both set, and each cleared on its own written "
            "one while the other stayed"
        )
        cocotb.log.info(
            "CHK-I2C-SMBALERT-HWCLR: SMBUS_CTRL.SMBALERT stayed set when written over itself "
            "and cleared when the controller addressed the target"
        )

    async def body(self) -> None:
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self._intr_state_leg()
        await self._nack_count_leg()
        await self._target_leg()
