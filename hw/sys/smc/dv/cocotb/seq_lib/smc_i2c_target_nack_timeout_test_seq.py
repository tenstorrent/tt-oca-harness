# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Each I2C target gives up on a stretch it is not released from.

`TARGET_TIMEOUT_CTRL` is the cumulative limit on how long this target may
stretch within one transaction. `i2c.rdl` states the consequence: past that
limit the target "will NACK incoming data bytes or release the SDA line for
outgoing data bytes". Every stretch leaf so far is released by software before
any limit applies, so the expiry had never been reached.

Both halves of that sentence are driven, one per direction, with the limit set
short enough that nothing has to wait for it:

* **Incoming.** ACK Control Mode is used to stop the target at the first data
  byte without filling the acquisition FIFO first, which is the same hold
  `smc_i2c_target_ack_ctrl_test` answers -- except that nothing answers it
  here, so the limit expires and the byte is NACKed.
* **Outgoing.** A read from an empty transmit FIFO leaves the target with
  nothing to send, so it holds the clock; the limit expires and it releases
  SDA, which the bench reads as all ones.

Every instance is driven. `+smc_i2c_shared_bus` puts all three on one
open-drain bus, so the bench controller on I2C0's pads reaches each of them by
address, and only the instance under test is enabled while a leg runs.

`TARGET_NACK_COUNT` is the register witness for both. `i2c_core.sv` increments
it on the edge where the target decides to NACK the transaction, and the field
is read-to-clear, so each leg reads it clear beforehand and requires exactly
one afterwards. The acquisition FIFO carries the other half: the NACK-stop
entry the target appends so software can see the transaction ended badly.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, Timer

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_ACQ_SIGNAL_ERROR,
    I2C_ACQDATA_SIGNAL,
    I2C_ACQDATA_SIGNAL_BP,
    I2C_CTRL_ACK_CTRL_EN,
    I2C_CTRL_ACQ_START_STOP_EN,
    I2C_CTRL_ENABLETARGET,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_STATUS_ACQEMPTY,
    I2C_TARGET_FIFO_STATUS_ACQLVL_BM,
    I2C_TARGET_FIFO_STATUS_ACQLVL_BP,
    I2C_TARGET_TIMEOUT_CTRL_EN,
    I2C_WRAP_CTRL_TARGET,
)
from .smc_i2c_protocol_vip import SmcI2cMasterVip
from .smc_i2c_target_smbus_test_seq import (
    _pack_target_id,
    _pack_timing0,
    _pack_timing1,
    _pack_timing2,
    _pack_timing3,
    _pack_timing4,
)

#: Every instance is driven. `+smc_i2c_shared_bus` puts all three on one
#: open-drain bus, so the bench controller on I2C0's pads reaches each of them
#: by address, and only the instance under test is enabled as a target.
INSTANCES = (0, 1, 2)
#: One address per instance, so a leg cannot be answered by the wrong one.
TARGET_ADDR = {0: 0x25, 1: 0x26, 2: 0x27}
VIP_SPEED = 2_000_000

#: Cumulative stretch allowance, in the target's own clock periods. Short
#: enough that the limit is reached within one held byte.
NACK_TIMEOUT_CYCLES = 64
WRITE_PAYLOAD = bytes((0x70 + i) & 0xFF for i in range(2))
READ_BYTES = 2
NACK_COUNT_BM = 0xFF

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

_REGS = {
    "wrap": "SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR",
    "ovrd": "SMC_TOP_SMC_I2C_WRAP_I2C_OVRD_BASE_ADDR",
    "ctrl": "SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR",
    "status": "SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR",
    "fifo_ctrl": "SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR",
    "target_id": "SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ID_BASE_ADDR",
    "timeout": "SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_TIMEOUT_CTRL_BASE_ADDR",
    "nack_count": "SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_NACK_COUNT_BASE_ADDR",
    "fifo_status": "SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR",
    "acqdata": "SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR",
    "timing0": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING0_BASE_ADDR",
    "timing1": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING1_BASE_ADDR",
    "timing2": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING2_BASE_ADDR",
    "timing3": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING3_BASE_ADDR",
    "timing4": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING4_BASE_ADDR",
}


def _regs(idx: int) -> dict[str, int]:
    return {key: smc_indexed_addr(sym, idx) for key, sym in _REGS.items()}


_ABYTE_BM = 0xFF
POLL_CYCLES = 100
FINISH_POLLS = 4000
#: Dwell between the bench's last edge and the drain. The target writes its
#: closing entry once it has detected the STOP, which `i2c_bus_monitor.sv`
#: makes take `TIMING3.THD_DAT` -- short here, but the entry is what each leg
#: is reading for.
STOP_DETECT_DWELL_NS = 2_000


class smc_i2c_target_nack_timeout_test_seq(SmcCsrSeq):
    """A stretch nobody releases must end in the target's own NACK."""

    def __init__(self, name: str = "smc_i2c_target_nack_timeout_test_seq") -> None:
        super().__init__(name)
        self.results: dict[tuple[int, str], tuple[list[int], list[tuple[int, int]], int]] = {}

    async def _pop_all(self, r: dict[str, int], into: list[tuple[int, int]]) -> None:
        await Timer(STOP_DETECT_DWELL_NS, unit="ns")
        fifo = await self.csr_read("I2C_TARGET_FIFO_STATUS", r["fifo_status"])
        level = (fifo & I2C_TARGET_FIFO_STATUS_ACQLVL_BM) >> I2C_TARGET_FIFO_STATUS_ACQLVL_BP
        for _ in range(level):
            word = await self.csr_read("I2C_ACQDATA", r["acqdata"])
            into.append(((word & I2C_ACQDATA_SIGNAL) >> I2C_ACQDATA_SIGNAL_BP, word & _ABYTE_BM))

    async def _disable_others(self, idx: int) -> None:
        """Only the instance under test answers, so a leg cannot be mis-attributed."""
        for other in INSTANCES:
            if other != idx:
                await self.csr_write(f"I2C{other}_OFF", _regs(other)["ctrl"], 0)

    async def _bring_up(self, idx: int, label: str, ack_ctrl: bool) -> dict[str, int]:
        r = _regs(idx)
        ctrl = I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN
        if ack_ctrl:
            ctrl |= I2C_CTRL_ACK_CTRL_EN
        await self.csr_write(f"I2C{idx}_DISABLE_{label}", r["ctrl"], 0)
        await self.csr_write(f"I2C{idx}_WRAP_TARGET", r["wrap"], I2C_WRAP_CTRL_TARGET)
        await self.arm_i2c_gpio_lsio(idx, f"I2C{idx}_NACK_TIMEOUT_{label}")
        await self.csr_write(f"I2C{idx}_OVRD_OFF", r["ovrd"], 0)
        await self.csr_write(f"I2C{idx}_TIMING0", r["timing0"], _pack_timing0(0x1A, 0x32))
        await self.csr_write(f"I2C{idx}_TIMING1", r["timing1"], _pack_timing1(2, 2))
        await self.csr_write(f"I2C{idx}_TIMING2", r["timing2"], _pack_timing2(5, 4))
        await self.csr_write(f"I2C{idx}_TIMING3", r["timing3"], _pack_timing3(2, 5))
        await self.csr_write(f"I2C{idx}_TIMING4", r["timing4"], _pack_timing4(4, 5))
        await self.csr_write(
            f"I2C{idx}_FIFO_RST",
            r["fifo_ctrl"],
            I2C_FIFO_CTRL_RXRST_FMTRST | I2C_FIFO_CTRL_TXRST,
        )
        await self.csr_write(
            f"I2C{idx}_TARGET_ID", r["target_id"], _pack_target_id(TARGET_ADDR[idx], 0x7F, 0, 0)
        )
        timeout = I2C_TARGET_TIMEOUT_CTRL_EN | NACK_TIMEOUT_CYCLES
        await self.csr_write(f"I2C{idx}_TARGET_TIMEOUT_{label}", r["timeout"], timeout)
        await self.csr_read(f"I2C{idx}_TARGET_TIMEOUT_{label}_RB", r["timeout"], expected=timeout)
        await self.csr_write(f"I2C{idx}_CTRL_{label}", r["ctrl"], ctrl)
        await ClockCycles(cocotb.top.clk_smc_i, 20)
        status = await self.csr_read(f"I2C{idx}_STATUS_{label}_ENTRY", r["status"])
        assert status & I2C_STATUS_ACQEMPTY, (
            f"I2C{idx} {label}: the acquisition FIFO is not empty before the leg starts "
            f"(STATUS=0x{status:08x})"
        )
        count = await self.csr_read(f"I2C{idx}_NACK_COUNT_{label}_CLEAR", r["nack_count"])
        again = await self.csr_read(f"I2C{idx}_NACK_COUNT_{label}_ENTRY", r["nack_count"])
        assert again & NACK_COUNT_BM == 0, (
            f"I2C{idx} {label}: TARGET_NACK_COUNT reads {again & NACK_COUNT_BM} straight after "
            f"a read cleared it from {count & NACK_COUNT_BM}"
        )
        return r

    async def _await_task(self, label: str, task) -> None:
        for _ in range(FINISH_POLLS):
            if task.done():
                task.result()
                return
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        raise AssertionError(
            f"{label}: the transfer never finished, so the target never gave up on its stretch"
        )

    async def _incoming_leg(self, idx: int) -> None:
        label = f"I2C{idx}_INCOMING"
        r = await self._bring_up(idx, "INCOMING", ack_ctrl=True)
        master = SmcI2cMasterVip(speed=VIP_SPEED, name=f"smc_i2c{idx}_nack_timeout_write")
        acks: list[int] = []

        async def run() -> None:
            await master.send_start()
            acks.append(await master.send_byte((TARGET_ADDR[idx] & 0x7F) << 1))
            for value in WRITE_PAYLOAD:
                acks.append(await master.send_byte(value))
            await master.send_stop()

        task = cocotb.start_soon(run())
        await self._await_task(label, task)
        entries: list[tuple[int, int]] = []
        await self._pop_all(r, entries)
        count = (await self.csr_read(f"{label}_COUNT", r["nack_count"])) & NACK_COUNT_BM

        assert acks[0] == 0, f"{label}: the target NACKed its own address (ACK bits {acks})"
        assert any(a == 1 for a in acks[1:]), (
            f"{label}: every data byte was acknowledged although the target was left holding "
            f"the bus past its {NACK_TIMEOUT_CYCLES}-cycle allowance (ACK bits {acks})"
        )
        assert count == 1, (
            f"{label}: TARGET_NACK_COUNT reads {count} after one transaction the target gave "
            f"up on; the counter takes the edge on which the target decides to NACK"
        )
        assert entries and entries[-1][0] == I2C_ACQ_SIGNAL_ERROR, (
            f"{label}: the acquisition FIFO does not end with the NACK-stop entry that tells "
            f"software the transaction ended badly (acquired {entries})"
        )
        self.results[(idx, "rx")] = (acks, entries, count)

    async def _outgoing_leg(self, idx: int) -> None:
        label = f"I2C{idx}_OUTGOING"
        r = await self._bring_up(idx, "OUTGOING", ack_ctrl=False)
        master = SmcI2cMasterVip(speed=VIP_SPEED, name=f"smc_i2c{idx}_nack_timeout_read")
        data = bytearray()

        async def run() -> None:
            data.extend(await master.read(TARGET_ADDR[idx], READ_BYTES))

        task = cocotb.start_soon(run())
        await self._await_task(label, task)
        entries: list[tuple[int, int]] = []
        await self._pop_all(r, entries)
        count = (await self.csr_read(f"{label}_COUNT", r["nack_count"])) & NACK_COUNT_BM

        assert bytes(data) == bytes([0xFF] * READ_BYTES), (
            f"{label}: the bench read {bytes(data).hex()} from a target whose transmit FIFO "
            f"was empty for longer than its allowance; a released SDA line reads as all ones"
        )
        assert count == 1, (
            f"{label}: TARGET_NACK_COUNT reads {count} after one read the target gave up on"
        )
        assert entries and entries[-1][0] == I2C_ACQ_SIGNAL_ERROR, (
            f"{label}: the acquisition FIFO does not end with the NACK-stop entry "
            f"(acquired {entries})"
        )
        self.results[(idx, "tx")] = ([], entries, count)

    async def body(self) -> None:
        assert "smc_i2c_shared_bus" in cocotb.plusargs, (
            "smc_i2c_target_nack_timeout_test needs +smc_i2c_shared_bus; without it only "
            "I2C0's pads are on the bench bus and the other two instances cannot be reached"
        )
        await self.prove_dut_i2c0_pins()
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        for idx in INSTANCES:
            await self._disable_others(idx)
            await self._incoming_leg(idx)
            await self._outgoing_leg(idx)

        rx = [i for (i, kind) in self.results if kind == "rx"]
        tx = [i for (i, kind) in self.results if kind == "tx"]
        cocotb.log.info(
            "CHK-I2C-TGT-NACK-TIMEOUT-RX: held at a data byte with nothing to release it, each "
            "of I2C%s ran out its %d-cycle allowance and NACKed the incoming byte, counted the "
            "transaction once in TARGET_NACK_COUNT and closed the acquisition stream with a "
            "NACK-stop entry: %s",
            ", I2C".join(str(i) for i in sorted(rx)),
            NACK_TIMEOUT_CYCLES,
            {f"I2C{i}": self.results[(i, "rx")][0] for i in sorted(rx)},
        )
        cocotb.log.info(
            "CHK-I2C-TGT-NACK-TIMEOUT-TX: asked to transmit with an empty transmit FIFO, each "
            "of I2C%s held the clock, ran out its allowance and released SDA so the bench read "
            "all ones, counted the transaction once and closed the stream with a NACK-stop "
            "entry: %s",
            ", I2C".join(str(i) for i in sorted(tx)),
            {f"I2C{i}": self.results[(i, "tx")][1][-1] for i in sorted(tx)},
        )
