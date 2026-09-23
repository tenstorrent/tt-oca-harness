# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A bus timeout expiring in every phase of a target transaction.

`hw/ip/i2c/regs/i2c.rdl` describes `TIMEOUT_CTRL.MODE` 1 as a bus timeout that
fires "if SCL is LOW for more time than `TIMEOUT_CTRL.VAL`", and
`doc/architecture.adoc` adds that the count "accumulates across all sources,
including this IP's Controller Module", that "the counter resets when SCL goes
high, so this count only accumulates during a single bit transfer", and that
"if a bus timeout occurs while the Target Module was addressed in the current
transaction, a `NACK_STOP` signal is added to the ACQ FIFO".

That makes the timeout the one interruption this bench can land anywhere. It
is a counter rather than a bus event, so unlike a STOP or a repeated START it
does not need the bus to be in a state where a control symbol can be driven --
parking SCL low at a chosen slot is enough, including in the acknowledge slots
and while the target itself is stretching.

Three legs per instance:

* **Slot sweep** -- park SCL low past the timeout at each slot of an addressed
  transaction, and require the acquisition FIFO to record the abnormal-ending
  entry the RDL defines.
* **Stretch timeout** -- let the acquisition FIFO fill so the target stretches,
  and let the timeout expire against the target's own SCL hold. Nothing on the
  bus is driven for this one; the target is holding SCL low itself.
* **Address-phase stretch** -- with the acquisition FIFO left full by that leg,
  start another transaction. Its address can no longer be deposited, which is
  the condition the target stretches the address phase for.

The acquisition FIFO entry is the observable throughout: `SIGNAL` 6 is what the
RDL defines for a transaction that "ended abnormally, for example, due to ...
a Bus or Stretch Timeout". Each leg opens and closes with a clean transaction,
the opening one as the positive control for reachability.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_ACQ_SIGNAL_ERROR,
    I2C_ACQ_SIGNAL_NONE,
    I2C_CTRL_ACQ_START_STOP_EN,
    I2C_CTRL_ENABLETARGET,
    I2C_FIFO_CTRL_ACQRST,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_STATUS_ACQEMPTY,
    I2C_STATUS_ACQFULL,
    I2C_STATUS_TARGETIDLE,
    I2C_TIMEOUT_CTRL_EN,
    I2C_TIMEOUT_MODE_BUS,
    I2C_WRAP_CTRL_TARGET,
    acq_abyte,
    acq_signal,
)
from .smc_i2c_protocol_vip import SmcI2cMasterVip
from .smc_i2c_slot_utils import (
    POST_ADDR_SLOTS,
    drive_to_slot,
    park_scl_low,
    release_bus,
)
from .smc_i2c_target_smbus_test_seq import (
    _pack_target_id,
    _pack_timing0,
    _pack_timing1,
    _pack_timing2,
    _pack_timing3,
    _pack_timing4,
)

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

INSTANCES = (0, 1, 2)
TARGET_ADDR = {0: 0x3C, 1: 0x3D, 2: 0x3E}
CLEAN_BYTE = 0x4B
SWEEP_BYTE = 0xD2
VIP_SPEED = 2_000_000

# Timeout value in core clock cycles. The VIP holds SCL low for about one bit
# period between bits, so the value sits well above that and the deliberate
# park sits well above the value: the timeout must fire only where this leaf
# puts it, never on ordinary bit timing.
TIMEOUT_VAL = 400
SCL_PARK_NS = 20_000

# Payload long enough to fill the acquisition FIFO, whose depth is read from
# the DUT rather than assumed.
FILL_PAYLOAD = bytes((0x60 + i) & 0xFF for i in range(70))

POLL_CYCLES = 200
POLL_LIMIT = 400
DRAIN_LIMIT = 600
SETTLE_CYCLES = 40
FILL_POLL_LIMIT = 4000


class smc_i2c_target_bus_timeout_test_seq(SmcCsrSeq):
    """Expire the bus timeout in every phase of a target transaction."""

    def __init__(self, name: str = "smc_i2c_target_bus_timeout_test_seq") -> None:
        super().__init__(name)
        self.slot_injections: dict[int, int] = {}
        self.stretch_timeouts: dict[int, int] = {}
        self.addr_stretch_depth: dict[int, int] = {}

    @staticmethod
    def _addr(symbol: str, idx: int) -> int:
        return smc_indexed_addr(f"SMC_TOP_SMC_I2C_WRAP_I2C_{symbol}_BASE_ADDR", idx)

    @staticmethod
    def _wrap_addr(idx: int) -> int:
        return smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", idx)

    async def _program_timing(self, idx: int) -> None:
        for reg, value in (
            ("TIMING0", _pack_timing0(0x1A, 0x32)),
            ("TIMING1", _pack_timing1(2, 2)),
            ("TIMING2", _pack_timing2(5, 4)),
            ("TIMING3", _pack_timing3(2, 5)),
            ("TIMING4", _pack_timing4(4, 5)),
        ):
            await self.csr_write(f"I2C{idx}_{reg}", self._addr(reg, idx), value)

    async def _disconnect_all(self) -> None:
        for idx in INSTANCES:
            await self.csr_write(f"I2C{idx}_WRAP_OFF", self._wrap_addr(idx), 0)
            await self.csr_write(f"I2C{idx}_CTRL_OFF", self._addr("CTRL", idx), 0)

    async def _reset_fifos(self, idx: int) -> None:
        await self.csr_write(
            f"I2C{idx}_TGT_FIFO",
            self._addr("FIFO_CTRL", idx),
            I2C_FIFO_CTRL_RXRST_FMTRST | I2C_FIFO_CTRL_TXRST | I2C_FIFO_CTRL_ACQRST,
        )

    async def _enable_target(self, idx: int, timeout: bool) -> None:
        await self.csr_write(f"I2C{idx}_WRAP_TGT", self._wrap_addr(idx), I2C_WRAP_CTRL_TARGET)
        await self._program_timing(idx)
        await self.csr_write(
            f"I2C{idx}_TGT_ID",
            self._addr("TARGET_ID", idx),
            _pack_target_id(TARGET_ADDR[idx], 0x7F, 0, 0),
        )
        timeout_word = (I2C_TIMEOUT_CTRL_EN | I2C_TIMEOUT_MODE_BUS | TIMEOUT_VAL) if timeout else 0
        await self.csr_write(
            f"I2C{idx}_TIMEOUT_CTRL", self._addr("TIMEOUT_CTRL", idx), timeout_word
        )
        await self.csr_read(
            f"I2C{idx}_TIMEOUT_CTRL_RB", self._addr("TIMEOUT_CTRL", idx), expected=timeout_word
        )
        await self._reset_fifos(idx)
        await self.csr_write(
            f"I2C{idx}_TGT_CTRL",
            self._addr("CTRL", idx),
            I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN,
        )

    async def _wait_target_idle(self, idx: int, label: str) -> None:
        status = 0
        for _ in range(POLL_LIMIT):
            status = await self.csr_read(f"{label}_TIDLE", self._addr("STATUS", idx))
            if status & I2C_STATUS_TARGETIDLE:
                return
            await ClockCycles(cocotb.top.clk_smc_i, SETTLE_CYCLES)
        raise AssertionError(f"{label}: I2C{idx} never reported TARGETIDLE (STATUS=0x{status:08x})")

    async def _drain_acq(self, idx: int, label: str) -> list[int]:
        words: list[int] = []
        for _ in range(DRAIN_LIMIT):
            status = await self.csr_read(f"{label}_ACQ_ST", self._addr("STATUS", idx))
            if status & I2C_STATUS_ACQEMPTY:
                return words
            words.append(int(await self.csr_read(f"{label}_ACQ", self._addr("ACQDATA", idx))))
        raise AssertionError(f"{label}: I2C{idx} acquisition FIFO never drained")

    async def _clean_transaction(self, vip: SmcI2cMasterVip, idx: int, label: str) -> None:
        await self._reset_fifos(idx)
        await vip.write(TARGET_ADDR[idx], bytes([CLEAN_BYTE]))
        await self._wait_target_idle(idx, label)
        words = await self._drain_acq(idx, label)
        data = [acq_abyte(w) for w in words if acq_signal(w) == I2C_ACQ_SIGNAL_NONE]
        assert data == [CLEAN_BYTE], (
            f"{label}: I2C{idx} acquired {[hex(b) for b in data]} for a clean one-byte write "
            f"of 0x{CLEAN_BYTE:02x}"
        )

    # --- leg: park SCL low past the timeout at every slot -----------------
    async def _slot_sweep(self, vip: SmcI2cMasterVip, idx: int) -> None:
        await self._clean_transaction(vip, idx, f"I2C{idx}_TO_CONTROL")
        injections = 0
        for phase, k in POST_ADDR_SLOTS:
            slot = f"I2C{idx}_TO_{phase}{k}"
            await self._reset_fifos(idx)
            await drive_to_slot(vip, TARGET_ADDR[idx], SWEEP_BYTE, phase, k)
            await park_scl_low(vip, SCL_PARK_NS)
            await release_bus(vip)
            await self._wait_target_idle(idx, slot)
            words = await self._drain_acq(idx, slot)
            errors = sum(1 for w in words if acq_signal(w) == I2C_ACQ_SIGNAL_ERROR)
            assert errors >= 1, (
                f"I2C{idx} recorded no abnormal-ending entry (SIGNAL "
                f"{I2C_ACQ_SIGNAL_ERROR}) after the bus timeout expired at {phase}{k} of an "
                f"addressed transaction (acquisition FIFO held {[hex(w) for w in words]})"
            )
            injections += 1
        self.slot_injections[idx] = injections
        await self._clean_transaction(vip, idx, f"I2C{idx}_TO_RECOVER")
        cocotb.log.info(
            "CHK-I2C%d-BUSTO-SLOT-SWEEP: the bus timeout expired at each of %d slots of an "
            "addressed transaction, every one recorded as an abnormal ending in the "
            "acquisition FIFO, with a clean write before and after",
            idx,
            injections,
        )

    # --- leg: the target's own stretch trips the timeout -------------------
    async def _stretch_timeout(self, vip: SmcI2cMasterVip, idx: int) -> None:
        await self._reset_fifos(idx)
        task = cocotb.start_soon(vip.write(TARGET_ADDR[idx], FILL_PAYLOAD))
        full = 0
        for _ in range(FILL_POLL_LIMIT):
            full = await self.csr_read(f"I2C{idx}_TO_FILL_ST", self._addr("STATUS", idx))
            if full & I2C_STATUS_ACQFULL:
                break
            if task.done():
                break
            await ClockCycles(cocotb.top.clk_smc_i, SETTLE_CYCLES)
        assert full & I2C_STATUS_ACQFULL, (
            f"I2C{idx} never filled its acquisition FIFO from a {len(FILL_PAYLOAD)}-byte write "
            f"with nothing draining it (STATUS=0x{full:08x})"
        )
        fifo = await self.csr_read(f"I2C{idx}_TO_FILL_LVL", self._addr("TARGET_FIFO_STATUS", idx))
        self.addr_stretch_depth[idx] = (fifo >> 16) & 0xFFF

        # The target is holding SCL low itself now. Nothing is driven on the
        # bus; the timeout counts that hold and releases the target to idle.
        await self._wait_target_idle(idx, f"I2C{idx}_TO_STRETCH")
        self.stretch_timeouts[idx] = 1
        cocotb.log.info(
            "CHK-I2C%d-BUSTO-STRETCH: with the acquisition FIFO full at %d entries the target "
            "held SCL low itself, and the bus timeout counted that hold and returned the "
            "instance to idle with nothing driven on the bus",
            idx,
            self.addr_stretch_depth[idx],
        )

        # The filling write is abandoned before anything else drives the bus:
        # it and the address-phase transaction below share one VIP, so they
        # cannot be in flight together.
        if task.done():
            try:
                task.result()
            except Exception:  # noqa: BLE001 - the abandoned write's verdict is not the claim
                pass
        else:
            task.kill()
        await release_bus(vip)

        # The acquisition FIFO is still full, so the next transaction's address
        # cannot be deposited, which is what the address phase stretches for.
        await drive_to_slot(vip, TARGET_ADDR[idx], SWEEP_BYTE, "addr", 7)
        await park_scl_low(vip, SCL_PARK_NS)
        await release_bus(vip)
        await self._wait_target_idle(idx, f"I2C{idx}_TO_ADDR_STRETCH")
        await self._reset_fifos(idx)
        await self._clean_transaction(vip, idx, f"I2C{idx}_TO_STRETCH_RECOVER")
        cocotb.log.info(
            "CHK-I2C%d-BUSTO-ADDR-STRETCH: a transaction started while the acquisition FIFO "
            "was still full drove the address phase against a target with nowhere to deposit "
            "it, and the instance ran a clean write afterwards",
            idx,
        )

    async def body(self) -> None:
        assert "smc_i2c_shared_bus" in cocotb.plusargs, (
            "smc_i2c_target_bus_timeout_test needs +smc_i2c_shared_bus; without it only "
            "I2C0's pads are on the bench bus"
        )
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        for idx in INSTANCES:
            await self.arm_i2c_gpio_lsio(idx, f"I2C{idx}_LSIO")
        await self.wait_i2c_bus_released("I2C_SHARED_BUS")

        vip = SmcI2cMasterVip(speed=VIP_SPEED, name="smc_i2c_bus_timeout_master")
        for idx in INSTANCES:
            await self._disconnect_all()
            await self._enable_target(idx, timeout=True)
            await self._slot_sweep(vip, idx)
            await self._stretch_timeout(vip, idx)
        await self._disconnect_all()
