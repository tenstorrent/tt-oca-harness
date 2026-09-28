# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""An I2C target abandons a transaction a controller drives too fast for it.

`TIMING3.THD_DAT` is the data hold time the target keeps before it drives an
acknowledge, counted in its own clock periods. The target waits out that count
with SCL low; if the controller releases SCL first, the acknowledge would land
outside the bit it belongs to, and the design abandons the transaction instead
of driving it late.

The threshold is a relation between two numbers, so the leaf sets both. The
target is programmed with a data hold time far longer than any other leaf uses
and the bench controller is run at two rates around it: one whose SCL low
period is well over the hold, and one whose low period is well under it.
Nothing else changes between them.

Both places the target makes that decision are driven -- the acknowledge of
the address byte, and the acknowledge of a data byte -- and both change rate
part-way through the transfer, after the START. The same hold count governs
both acknowledges, so at one rate the address would always be the first to
go; and the bus monitor takes the same `THD_DAT` as its threshold for
detecting a START (`i2c_bus_monitor.sv`), so a start clocked fast enough to
violate the hold is not seen as a start at all. The START therefore goes out
at the slow rate in every leg, and only the bits after it change.

A transfer at the slow rate runs before and after, so the abandons are the
difference the rate makes rather than a target that never works.

One instance is driven per simulation. The hold relation needs a bus slow
enough that the whole leaf is dominated by it, and three instances of that do
not fit in the time one simulation is given, so the instance is a parameter of
the sequence and the package carries one entry per instance. The register
witness is `TARGET_NACK_COUNT`, which `i2c_core.sv` increments on the edge
where the target decides to NACK the transaction; it is read-to-clear, so each
leg requires exactly its own.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, Timer

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_ACQ_SIGNAL_ERROR,
    I2C_ACQ_SIGNAL_NONE,
    I2C_ACQ_SIGNAL_START,
    I2C_ACQ_SIGNAL_STOP,
    I2C_ACQDATA_SIGNAL,
    I2C_ACQDATA_SIGNAL_BP,
    I2C_CTRL_ACQ_START_STOP_EN,
    I2C_CTRL_ENABLETARGET,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_STATUS_ACQEMPTY,
    I2C_TARGET_FIFO_STATUS_ACQLVL_BM,
    I2C_TARGET_FIFO_STATUS_ACQLVL_BP,
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

#: The instances this sequence can be pointed at. `+smc_i2c_shared_bus` puts
#: all three on one open-drain bus, so the bench controller on I2C0's pads
#: reaches each of them by address, and only the instance under test is
#: enabled while a leg runs. One instance is driven per simulation: the hold
#: relation needs a bus rate slow enough that three instances of it run past
#: the time a single run is given.
INSTANCES = (0, 1, 2)
TARGET_ADDR = {0: 0x26, 1: 0x2A, 2: 0x2B}

#: Data hold time in the target's own clock periods. The bench clocks
#: `clk_periph_i` at 10 ns, so this is a hold of 2 us -- far longer than a
#: real target would use, and chosen only so both bench rates below sit clear
#: of it -- and below half the slow rate's low period, so the target always
#: finishes driving an acknowledge before the clock rises again.
TARGET_HOLD_CYCLES = 200
#: The VIP holds SCL low for one bit period between bits, so the low period is
#: 5 us at the slow rate and 1 us at the fast one: either side of the 2 us
#: hold. Both are ordinary bus rates, well within what the target samples
#: reliably.
SLOW_SPEED = 200_000
FAST_SPEED = 1_000_000
PAYLOAD = bytes((0x80 + i) & 0xFF for i in range(1))
#: Bus park before the data byte of the mid-transfer rate change, so the
#: target's own hold on the address acknowledge has finished before the rate
#: changes.
PARK_NS = 8_000
#: Rounds of waiting for the acquisition FIFO to settle after a STOP. The
#: closing entry is written as the STOP is detected, which is after the
#: bench's last bus edge.
SETTLE_ROUNDS = 20
SETTLE_CYCLES = 100
#: Dwell after the bench's last edge before the acquisition FIFO is read.
#: The target writes its closing entry only once it has detected the STOP,
#: and `i2c_bus_monitor.sv` makes that detection take `THD_DAT`, which this
#: leaf programs long. Ten times the hold leaves no doubt.
STOP_DETECT_DWELL_NS = 10 * TARGET_HOLD_CYCLES * 10
NACK_COUNT_BM = 0xFF

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

_REGS = {
    "wrap": "SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR",
    "ovrd": "SMC_TOP_SMC_I2C_WRAP_I2C_OVRD_BASE_ADDR",
    "ctrl": "SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR",
    "status": "SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR",
    "fifo_ctrl": "SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR",
    "target_id": "SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ID_BASE_ADDR",
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


class smc_i2c_target_fast_controller_test_seq(SmcCsrSeq):
    """A controller faster than the target's hold time must be refused."""

    def __init__(self, name: str = "smc_i2c_target_fast_controller_test_seq", idx: int = 0) -> None:
        super().__init__(name)
        assert idx in INSTANCES, f"I2C instance {idx} is not one of {INSTANCES}"
        self.idx = idx
        self.results: dict[str, tuple[list[int], list[tuple[int, int]], int]] = {}

    @staticmethod
    def _addr_byte(idx: int) -> int:
        return (TARGET_ADDR[idx] & 0x7F) << 1

    async def _pop_all(self, r: dict[str, int]) -> list[tuple[int, int]]:
        out: list[tuple[int, int]] = []
        fifo = await self.csr_read("I2C_TARGET_FIFO_STATUS", r["fifo_status"])
        level = (fifo & I2C_TARGET_FIFO_STATUS_ACQLVL_BM) >> I2C_TARGET_FIFO_STATUS_ACQLVL_BP
        for _ in range(level):
            word = await self.csr_read("I2C_ACQDATA", r["acqdata"])
            out.append(((word & I2C_ACQDATA_SIGNAL) >> I2C_ACQDATA_SIGNAL_BP, word & _ABYTE_BM))
        return out

    async def _clear_nack_count(self, r: dict[str, int], label: str) -> None:
        first = await self.csr_read(f"{label}_NACK_CLEAR", r["nack_count"])
        again = await self.csr_read(f"{label}_NACK_ENTRY", r["nack_count"])
        assert again & NACK_COUNT_BM == 0, (
            f"{label}: TARGET_NACK_COUNT reads {again & NACK_COUNT_BM} straight after a read "
            f"cleared it from {first & NACK_COUNT_BM}"
        )

    async def _disable_others(self, idx: int) -> None:
        for other in INSTANCES:
            if other != idx:
                await self.csr_write(f"I2C{other}_OFF", _regs(other)["ctrl"], 0)

    async def _bring_up(self, idx: int) -> dict[str, int]:
        r = _regs(idx)
        await self.csr_write(f"I2C{idx}_DISABLE", r["ctrl"], 0)
        await self.csr_write(f"I2C{idx}_WRAP_TARGET", r["wrap"], I2C_WRAP_CTRL_TARGET)
        await self.arm_i2c_gpio_lsio(idx, f"I2C{idx}_FAST_CONTROLLER")
        await self.csr_write(f"I2C{idx}_OVRD_OFF", r["ovrd"], 0)
        await self.csr_write(f"I2C{idx}_TIMING0", r["timing0"], _pack_timing0(0x1A, 0x32))
        await self.csr_write(f"I2C{idx}_TIMING1", r["timing1"], _pack_timing1(2, 2))
        await self.csr_write(f"I2C{idx}_TIMING2", r["timing2"], _pack_timing2(5, 4))
        timing3 = _pack_timing3(2, TARGET_HOLD_CYCLES)
        await self.csr_write(f"I2C{idx}_TIMING3", r["timing3"], timing3)
        await self.csr_read(f"I2C{idx}_TIMING3_RB", r["timing3"], expected=timing3)
        await self.csr_write(f"I2C{idx}_TIMING4", r["timing4"], _pack_timing4(4, 5))
        await self.csr_write(
            f"I2C{idx}_FIFO_RST",
            r["fifo_ctrl"],
            I2C_FIFO_CTRL_RXRST_FMTRST | I2C_FIFO_CTRL_TXRST,
        )
        await self.csr_write(
            f"I2C{idx}_TARGET_ID", r["target_id"], _pack_target_id(TARGET_ADDR[idx], 0x7F, 0, 0)
        )
        await self.csr_write(
            f"I2C{idx}_CTRL", r["ctrl"], I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN
        )
        await ClockCycles(cocotb.top.clk_smc_i, 20)
        status = await self.csr_read(f"I2C{idx}_STATUS_ENTRY", r["status"])
        assert status & I2C_STATUS_ACQEMPTY, (
            f"I2C{idx}: the acquisition FIFO is not empty before the first transfer "
            f"(STATUS=0x{status:08x})"
        )
        return r

    async def _settled_entries(self, r: dict[str, int]) -> list[tuple[int, int]]:
        """Drain once the acquisition level is non-zero and has stopped moving.

        Every leg ends with an entry -- a stop for the ones the target
        acknowledges, a NACK-stop for the ones it abandons -- and the target
        writes it only once it has detected the STOP, and that detection
        takes `THD_DAT`, which this leaf programs long. Draining before it
        lands would hand the entry to the next leg.
        """
        await Timer(STOP_DETECT_DWELL_NS, unit="ns")
        level = -1
        for _ in range(SETTLE_ROUNDS):
            await ClockCycles(cocotb.top.clk_smc_i, SETTLE_CYCLES)
            fifo = await self.csr_read("I2C_TARGET_FIFO_STATUS", r["fifo_status"])
            now = (fifo & I2C_TARGET_FIFO_STATUS_ACQLVL_BM) >> I2C_TARGET_FIFO_STATUS_ACQLVL_BP
            if now > 0 and now == level:
                return await self._pop_all(r)
            level = now
        raise AssertionError(
            f"the acquisition FIFO never settled above empty in {SETTLE_ROUNDS} rounds "
            f"(last level {level}); every leg closes with an entry of its own"
        )

    async def _run_leg(self, idx: int, r: dict[str, int], label: str, change_at: str | None):
        """One transfer: START, address, one data byte, STOP.

        Every leg starts at the slow rate. ``change_at`` names the byte whose
        acknowledge is clocked at the fast rate instead.
        """
        await self._clear_nack_count(r, label)
        master = SmcI2cMasterVip(speed=SLOW_SPEED, name=f"smc_i2c{idx}_fast_ctrl")
        acks: list[int] = []
        await master.send_start()
        if change_at == "address":
            master.set_speed(FAST_SPEED)
        acks.append(await master.send_byte(self._addr_byte(idx)))
        if change_at == "data":
            await Timer(PARK_NS, unit="ns")
            master.set_speed(FAST_SPEED)
        for value in PAYLOAD:
            acks.append(await master.send_byte(value))
        await master.send_stop()
        entries = await self._settled_entries(r)
        count = (await self.csr_read(f"{label}_NACK", r["nack_count"])) & NACK_COUNT_BM
        self.results[label] = (acks, entries, count)

    async def _instance(self, idx: int) -> None:
        await self._disable_others(idx)
        r = await self._bring_up(idx)
        for name, change_at in (
            ("BEFORE", None),
            ("ADDR", "address"),
            ("DATA", "data"),
            ("AFTER", None),
        ):
            await self._run_leg(idx, r, f"I2C{idx}_{name}", change_at)

        wanted = [
            (I2C_ACQ_SIGNAL_START, self._addr_byte(idx)),
            *[(I2C_ACQ_SIGNAL_NONE, v) for v in PAYLOAD],
        ]
        for name in ("BEFORE", "AFTER"):
            label = f"I2C{idx}_{name}"
            acks, entries, count = self.results[label]
            assert all(a == 0 for a in acks), (
                f"{label}: the target refused a transfer whose SCL low period is well over "
                f"its {TARGET_HOLD_CYCLES}-cycle hold time (ACK bits {acks}); the two legs "
                f"between these are supposed to be the difference the rate makes"
            )
            assert [e[0] for e in entries] == [e[0] for e in wanted] + [I2C_ACQ_SIGNAL_STOP], (
                f"{label}: the acquired signals are {entries}, not a start, the payload and a stop"
            )
            assert entries[: len(wanted)] == wanted, (
                f"{label}: the acquired bytes do not match the transfer ({entries})"
            )
            assert count == 0, (
                f"{label}: TARGET_NACK_COUNT reads {count} after a transfer the target "
                f"acknowledged throughout"
            )

        acks, entries, count = self.results[f"I2C{idx}_ADDR"]
        assert acks[0] == 1, (
            f"I2C{idx}_ADDR: the target acknowledged its address to a controller whose SCL "
            f"low period is under its {TARGET_HOLD_CYCLES}-cycle hold time (ACK bits {acks})"
        )
        assert count == 1, (
            f"I2C{idx}_ADDR: TARGET_NACK_COUNT reads {count} after one transaction the target "
            f"abandoned at the address acknowledge"
        )
        assert [e[0] for e in entries] == [I2C_ACQ_SIGNAL_ERROR], (
            f"I2C{idx}_ADDR: the acquired stream is {entries}; a transaction abandoned before "
            f"the address was acknowledged records nothing for the address itself and closes "
            f"with the NACK-stop entry"
        )

        acks, entries, count = self.results[f"I2C{idx}_DATA"]
        assert acks[0] == 0, (
            f"I2C{idx}_DATA: the address was not acknowledged although it was clocked at the "
            f"slow rate (ACK bits {acks})"
        )
        assert acks[1] == 1, (
            f"I2C{idx}_DATA: the target acknowledged a data byte clocked faster than its "
            f"{TARGET_HOLD_CYCLES}-cycle hold time (ACK bits {acks})"
        )
        assert count == 1, (
            f"I2C{idx}_DATA: TARGET_NACK_COUNT reads {count} after one transaction the target "
            f"abandoned at a data acknowledge"
        )
        assert all(e[0] != I2C_ACQ_SIGNAL_NONE for e in entries), (
            f"I2C{idx}_DATA: a data entry reached the acquisition FIFO from the byte the "
            f"target abandoned on ({entries})"
        )

    async def body(self) -> None:
        idx = self.idx
        assert "smc_i2c_shared_bus" in cocotb.plusargs, (
            f"the I2C{idx} fast-controller leaf needs +smc_i2c_shared_bus; without it only "
            f"I2C0's pads are on the bench bus and the other two instances cannot be reached"
        )
        await self.prove_dut_i2c0_pins()
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self._instance(idx)

        cocotb.log.info(
            "CHK-I2C%d-TGT-FAST-CTRL-CONTROL: at a bit rate whose SCL low period is well over "
            "the target's programmed hold of %d cycles, the transfer before the two fast legs "
            "and the transfer after them were acknowledged throughout, acquired in full and "
            "counted no NACK",
            idx,
            TARGET_HOLD_CYCLES,
        )
        cocotb.log.info(
            "CHK-I2C%d-TGT-FAST-CTRL-ADDR: a controller whose SCL low period is under the "
            "target's %d-cycle hold time got no acknowledge for its address, the transaction "
            "was counted once in TARGET_NACK_COUNT, and the only thing acquired was the "
            "NACK-stop entry closing it (%s)",
            idx,
            TARGET_HOLD_CYCLES,
            self.results[f"I2C{idx}_ADDR"][1],
        )
        cocotb.log.info(
            "CHK-I2C%d-TGT-FAST-CTRL-DATA: with the address clocked slowly and acknowledged, "
            "the same transfer sped up for its data byte got no acknowledge for it, was "
            "counted once in TARGET_NACK_COUNT and left no data entry behind (ACK bits %s)",
            idx,
            self.results[f"I2C{idx}_DATA"][0],
        )
