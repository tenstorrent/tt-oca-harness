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
  SDA, which the bench reads as all ones. That leg also sets
  `CTRL.TX_STRETCH_CTRL_EN`, so the target records the read it stretched for
  in `TARGET_EVENTS.TX_PENDING`, and the register's own contract is checked
  there: a word of zeros and a word of ones that strobes only the top byte
  lane, so the field's lane carries a one it is not enabled to take, must
  both leave it set, and only a written one clears it.

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
from .smc_csr_seq_utils import ALL_ONES_WORD, TOP_BYTE_LANE, SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_ACQ_SIGNAL_ERROR,
    I2C_ACQ_SIGNAL_NONE,
    I2C_ACQ_SIGNAL_RESTART,
    I2C_ACQ_SIGNAL_START,
    I2C_ACQ_SIGNAL_STOP,
    I2C_ACQDATA_SIGNAL,
    I2C_ACQDATA_SIGNAL_BP,
    I2C_CTRL_ACK_CTRL_EN,
    I2C_CTRL_ACQ_START_STOP_EN,
    I2C_CTRL_ENABLETARGET,
    I2C_CTRL_NACK_ADDR_AFTER_TIMEOUT,
    I2C_CTRL_TX_STRETCH_CTRL_EN,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_STATUS_ACQEMPTY,
    I2C_TARGET_EVENTS_TX_PENDING,
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
#: `TARGET_NACK_COUNT` saturates rather than wrapping (`i2c.rdl`: "saturating at
#: 255"), so a preset at the top of its range has to hold there across a NACK.
NACK_COUNT_TOP = 0xFF
#: `VAL` holds the last sixteen oversampled levels of SCL and SDA, so an idle
#: bus, released high, reads all ones in both halves.
VAL_IDLE = 0xFFFF_FFFF
#: The instance the single-shot legs below run on; the counter, the sampler
#: and the address phase are the same logic on every instance.
DETAIL_INSTANCE = 0
RESTART_BYTE = 0x5B

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
    "target_events": "SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_EVENTS_BASE_ADDR",
    "fifo_status": "SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR",
    "acqdata": "SMC_TOP_SMC_I2C_WRAP_I2C_ACQDATA_BASE_ADDR",
    "timing0": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING0_BASE_ADDR",
    "timing1": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING1_BASE_ADDR",
    "timing2": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING2_BASE_ADDR",
    "timing3": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING3_BASE_ADDR",
    "timing4": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING4_BASE_ADDR",
    "val": "SMC_TOP_SMC_I2C_WRAP_I2C_VAL_BASE_ADDR",
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
        self.retained: list[str] = []
        self.val_idle: list[int] = []
        self.restarts: dict[str, list[int]] = {}

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

    async def _bring_up(
        self,
        idx: int,
        label: str,
        ack_ctrl: bool,
        tx_stretch: bool = False,
        nack_addr: bool = False,
        timeout: bool = True,
    ) -> dict[str, int]:
        r = _regs(idx)
        ctrl = I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN
        if ack_ctrl:
            ctrl |= I2C_CTRL_ACK_CTRL_EN
        if tx_stretch:
            ctrl |= I2C_CTRL_TX_STRETCH_CTRL_EN
        if nack_addr:
            ctrl |= I2C_CTRL_NACK_ADDR_AFTER_TIMEOUT
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
        await self._idle_samples(idx, r)
        master = SmcI2cMasterVip(speed=VIP_SPEED, name=f"smc_i2c{idx}_nack_timeout_write")
        acks = await self._nacking_write(idx, master, label)
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

    async def _nacking_write(
        self, idx: int, master: SmcI2cMasterVip, label: str, restart: bool = False
    ) -> list[int]:
        """A write the target gives up on at its first data byte.

        With ``restart`` the bench does not stop after the NACK: it issues a
        repeated START, the address again and one more byte, so the target
        meets a new address phase inside a transaction it has already refused.
        Returns every ACK bit the bench read, in order.
        """
        acks: list[int] = []

        async def run() -> None:
            await master.send_start()
            acks.append(await master.send_byte((TARGET_ADDR[idx] & 0x7F) << 1))
            for value in WRITE_PAYLOAD:
                acks.append(await master.send_byte(value))
            if restart:
                await master.send_start()
                acks.append(await master.send_byte((TARGET_ADDR[idx] & 0x7F) << 1))
                acks.append(await master.send_byte(RESTART_BYTE))
            await master.send_stop()

        task = cocotb.start_soon(run())
        await self._await_task(label, task)
        return acks

    async def _idle_samples(self, idx: int, r: dict[str, int]) -> None:
        val = await self.csr_read(f"I2C{idx}_VAL_IDLE", r["val"])
        assert val == VAL_IDLE, (
            f"I2C{idx}: VAL reads 0x{val:08x} with the bus idle; the last sixteen samples of "
            f"a released SCL and SDA are all ones"
        )
        self.val_idle.append(idx)

    async def _nack_count_saturates(self, idx: int) -> None:
        label = f"I2C{idx}_NACK_SATURATE"
        r = await self._bring_up(idx, "SATURATE", ack_ctrl=True)
        await self.csr_write(f"{label}_PRESET", r["nack_count"], NACK_COUNT_TOP)
        master = SmcI2cMasterVip(speed=VIP_SPEED, name=f"smc_i2c{idx}_nack_saturate")
        acks = await self._nacking_write(idx, master, label)
        assert any(a == 1 for a in acks[1:]), (
            f"{label}: the target did not give up on the write (ACK bits {acks}), so there "
            f"was no NACK for the counter to take"
        )
        held = (await self.csr_read(f"{label}_HELD", r["nack_count"])) & NACK_COUNT_BM
        after = (await self.csr_read(f"{label}_CLEARED", r["nack_count"])) & NACK_COUNT_BM
        assert held == NACK_COUNT_TOP, (
            f"{label}: TARGET_NACK_COUNT reads 0x{held:02x} after a NACK taken with the "
            f"counter preset to 0x{NACK_COUNT_TOP:02x}; it saturates rather than wrapping"
        )
        assert after == 0, (
            f"{label}: TARGET_NACK_COUNT reads 0x{after:02x} on the read after it returned "
            f"0x{held:02x}; the field clears on read"
        )
        await self._pop_all(r, [])

    async def _clean_restart(self, idx: int) -> None:
        """A repeated START with room in the FIFO is recorded as a restart."""
        label = f"I2C{idx}_RESTART_CLEAN"
        r = await self._bring_up(idx, "RESTART_CLEAN", ack_ctrl=False, timeout=False)
        master = SmcI2cMasterVip(speed=VIP_SPEED, name=f"smc_i2c{idx}_restart_clean")
        addr_byte = (TARGET_ADDR[idx] & 0x7F) << 1
        acks: list[int] = []
        await master.send_start()
        acks.append(await master.send_byte(addr_byte))
        acks.append(await master.send_byte(WRITE_PAYLOAD[0]))
        await master.send_start()
        acks.append(await master.send_byte(addr_byte))
        acks.append(await master.send_byte(RESTART_BYTE))
        await master.send_stop()
        entries: list[tuple[int, int]] = []
        await self._pop_all(r, entries)
        assert all(a == 0 for a in acks), (
            f"{label}: the target refused part of a healthy transaction (ACK bits {acks})"
        )
        wanted = [
            (I2C_ACQ_SIGNAL_START, addr_byte),
            (I2C_ACQ_SIGNAL_NONE, WRITE_PAYLOAD[0]),
            (I2C_ACQ_SIGNAL_RESTART, addr_byte),
            (I2C_ACQ_SIGNAL_NONE, RESTART_BYTE),
        ]
        assert entries[:4] == wanted and [s for s, _ in entries[4:]] == [I2C_ACQ_SIGNAL_STOP], (
            f"{label}: the acquired stream is {entries}, not a start, a byte, a restart, a "
            f"byte and a stop"
        )
        self.restarts["clean"] = acks

    async def _restart_after_nack(self, idx: int, nack_addr: bool) -> None:
        """A repeated START inside a transaction the target has already refused."""
        mode = "NACKADDR" if nack_addr else "ACKADDR"
        label = f"I2C{idx}_RESTART_{mode}"
        r = await self._bring_up(idx, f"RESTART_{mode}", ack_ctrl=True, nack_addr=nack_addr)
        master = SmcI2cMasterVip(speed=VIP_SPEED, name=f"smc_i2c{idx}_restart_{mode.lower()}")
        acks = await self._nacking_write(idx, master, label, restart=True)
        entries: list[tuple[int, int]] = []
        await self._pop_all(r, entries)
        count = (await self.csr_read(f"{label}_COUNT", r["nack_count"])) & NACK_COUNT_BM
        restart_addr_ack, restart_byte_ack = acks[-2], acks[-1]
        assert any(a == 1 for a in acks[1 : 1 + len(WRITE_PAYLOAD)]), (
            f"{label}: the target did not give up on the first write (ACK bits {acks})"
        )
        if nack_addr:
            assert restart_addr_ack == 1, (
                f"{label}: with CTRL.NACK_ADDR_AFTER_TIMEOUT set the target acknowledged a "
                f"repeated START's address inside a transaction it had already refused "
                f"(ACK bits {acks})"
            )
        else:
            assert restart_addr_ack == 0 and restart_byte_ack == 1, (
                f"{label}: with CTRL.NACK_ADDR_AFTER_TIMEOUT clear the target acknowledges "
                f"every address, but has already refused this transaction, so the byte "
                f"after the repeated START's address must go unacknowledged (ACK bits {acks})"
            )
        assert count == 1, (
            f"{label}: TARGET_NACK_COUNT reads {count} for one refused transaction; a "
            f"repeated START inside it is not a new transaction to count"
        )
        assert not any(s == I2C_ACQ_SIGNAL_RESTART for s, _ in entries), (
            f"{label}: a restart entry reached the acquisition FIFO from a transaction the "
            f"target had already refused (acquired {entries})"
        )
        self.restarts[mode] = acks

    async def _tx_pending_retain(self, r: dict[str, int], label: str) -> None:
        """TARGET_EVENTS.TX_PENDING clears on a written one and nothing else.

        The read above sets it: with `CTRL.TX_STRETCH_CTRL_EN` the target
        records the read command it stretched for. Two writes that must not
        clear it are made first -- a word of zeros over the set bit, and a word
        of ones that strobes only the top byte lane, so the lane carrying the
        bit is disabled while carrying a one -- and each is read back against
        the mask from the generated header.
        """
        set_by_dut = await self.csr_read(f"{label}_TXPEND", r["target_events"])
        assert set_by_dut & I2C_TARGET_EVENTS_TX_PENDING, (
            f"{label}: TARGET_EVENTS.TX_PENDING is not set although the target stretched a "
            f"read with TX_STRETCH_CTRL_EN set (0x{set_by_dut:08x})"
        )
        await self.csr_write(f"{label}_TXPEND_ZERO", r["target_events"], 0)
        after_zero = await self.csr_read(f"{label}_TXPEND_AFTER_ZERO", r["target_events"])
        assert after_zero & I2C_TARGET_EVENTS_TX_PENDING, (
            f"{label}: TX_PENDING cleared on a word of zeros (0x{after_zero:08x}); the field "
            f"clears on a written one"
        )
        await self.csr_write_strobed(
            f"{label}_TXPEND_LANE", r["target_events"], ALL_ONES_WORD, wstrb=TOP_BYTE_LANE
        )
        after_lane = await self.csr_read(f"{label}_TXPEND_AFTER_LANE", r["target_events"])
        assert after_lane & I2C_TARGET_EVENTS_TX_PENDING, (
            f"{label}: TX_PENDING cleared on a word of ones that strobed only the top byte "
            f"lane (0x{after_lane:08x}); its own lane was disabled, so the one it carried "
            f"must not land"
        )
        await self.csr_write(
            f"{label}_TXPEND_CLEAR", r["target_events"], I2C_TARGET_EVENTS_TX_PENDING
        )
        cleared = await self.csr_read(f"{label}_TXPEND_CLEARED", r["target_events"])
        assert cleared & I2C_TARGET_EVENTS_TX_PENDING == 0, (
            f"{label}: TX_PENDING survived a written one (0x{cleared:08x})"
        )
        self.retained.append(label)

    async def _outgoing_leg(self, idx: int) -> None:
        label = f"I2C{idx}_OUTGOING"
        r = await self._bring_up(idx, "OUTGOING", ack_ctrl=False, tx_stretch=True)
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
        await self._tx_pending_retain(r, label)
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

        await self._disable_others(DETAIL_INSTANCE)
        await self._nack_count_saturates(DETAIL_INSTANCE)
        await self._clean_restart(DETAIL_INSTANCE)
        await self._restart_after_nack(DETAIL_INSTANCE, nack_addr=False)
        await self._restart_after_nack(DETAIL_INSTANCE, nack_addr=True)
        cocotb.log.info(
            "CHK-I2C-VAL-IDLE: VAL read all ones on I2C%s with the bus idle, the last sixteen "
            "oversampled levels of a released SCL and SDA",
            ", I2C".join(str(i) for i in self.val_idle),
        )
        cocotb.log.info(
            "CHK-I2C-TGT-NACK-COUNT-SATURATES: on I2C%d a NACK taken with TARGET_NACK_COUNT "
            "preset to 0x%02x left it at 0x%02x rather than wrapping, and the read that "
            "returned it cleared it",
            DETAIL_INSTANCE,
            NACK_COUNT_TOP,
            NACK_COUNT_TOP,
        )
        cocotb.log.info(
            "CHK-I2C-TGT-RESTART: on I2C%d a repeated START in a healthy transaction was "
            "recorded as a restart entry (ACK bits %s); inside a transaction the target had "
            "already refused, it acknowledged the new address and nothing after it with "
            "CTRL.NACK_ADDR_AFTER_TIMEOUT clear (%s), refused the address with it set (%s), "
            "counted the transaction once and recorded no restart either way",
            DETAIL_INSTANCE,
            self.restarts["clean"],
            self.restarts["ACKADDR"],
            self.restarts["NACKADDR"],
        )

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
            "CHK-I2C-TGT-EVENTS-RETAIN: on %d instances TARGET_EVENTS.TX_PENDING, set by the "
            "target itself on the read it stretched for, survived a word of zeros written "
            "over it and a word of ones that strobed only the top byte lane, so its own lane "
            "carried a one it was not enabled to take, and cleared only on a "
            "written one: %s",
            len(self.retained),
            ", ".join(self.retained),
        )
        cocotb.log.info(
            "CHK-I2C-TGT-NACK-TIMEOUT-TX: asked to transmit with an empty transmit FIFO, each "
            "of I2C%s held the clock, ran out its allowance and released SDA so the bench read "
            "all ones, counted the transaction once and closed the stream with a NACK-stop "
            "entry: %s",
            ", I2C".join(str(i) for i in sorted(tx)),
            {f"I2C{i}": self.results[(i, "tx")][1][-1] for i in sorted(tx)},
        )
