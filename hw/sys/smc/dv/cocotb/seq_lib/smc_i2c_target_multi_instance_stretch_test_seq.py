# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Target-side transmit, address mismatch and both stretch paths on I2C1 and I2C2.

`+smc_i2c_shared_bus` puts all three I2C instances on one open-drain bus, so one
enabled controller reaches any enabled target by address. Every leg below uses a
DUT instance as the controller and another as the target, the shape
`smc_i2c_p0_multictrl_test_seq` and `smc_i2c_p0_stretch_test_seq` already use,
so both ends of each check are DUT-produced.

Four behaviours, on I2C1 and I2C2:

* **Transmit** -- the target sources a byte the controller reads back.
* **Transmit stretch** -- with `CTRL.TX_STRETCH_CTRL_EN` set and the transmit
  FIFO empty, the target holds the bus and raises
  `TARGET_EVENTS.TX_PENDING` until software supplies the byte.
* **Address mismatch** -- an address no enabled target matches leaves the target
  acquiring nothing and the controller reporting `CONTROLLER_EVENTS.NACK`.
* **Acquisition stretch** -- the controller writes past the acquisition FIFO's
  capacity with nothing draining it, and the target holds the controller off
  until software reads `ACQDATA`.

The acquisition-stretch hold is measured through the controller rather than on
the bus. Both ends are DUT instances here, so a low SCL net does not say which
of the two is holding it; what does say so is that the controller cannot
finish while `STATUS.ACQFULL` is set on the target and finishes once software
drains `ACQDATA`. The bench-side variant of the same check, where the bench
controller releases SCL and only the target can be pulling it, is
`smc_i2c_target_acq_stretch_test` on I2C0.

The address-phase stretch (`STRETCH_ADDR_ACK`, `STRETCH_ADDR_ACK_SETUP`), which
needs the acquisition FIFO still full when a later transaction starts, is driven
by `smc_i2c_target_addr_stretch_test_seq`.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_ACQ_SIGNAL_NONE,
    I2C_CONTROLLER_EVENTS_ALL,
    I2C_CONTROLLER_EVENTS_NACK,
    I2C_CTRL_ACQ_START_STOP_EN,
    I2C_CTRL_ENABLEHOST,
    I2C_CTRL_ENABLETARGET,
    I2C_CTRL_TX_STRETCH_CTRL_EN,
    I2C_FDATA_READB,
    I2C_FDATA_START,
    I2C_FDATA_STOP,
    I2C_FIFO_CTRL_ACQRST,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_STATUS_ACQEMPTY,
    I2C_STATUS_ACQFULL,
    I2C_STATUS_FMTEMPTY,
    I2C_STATUS_FMTFULL,
    I2C_STATUS_HOSTIDLE,
    I2C_STATUS_RXEMPTY,
    I2C_TARGET_EVENTS_TX_PENDING,
    I2C_WRAP_CTRL_HOST,
    I2C_WRAP_CTRL_TARGET,
    acq_abyte,
    acq_signal,
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
# Controller for every leg; I2C1 and I2C2 are the targets.
HOST = 0
# Target addresses, one per instance, so a transfer cannot be answered by the
# instance it was not aimed at.
TARGET_ADDR = {1: 0x34, 2: 0x35}
# An address no target is programmed to match.
UNMATCHED_ADDR = 0x57
# Byte each target sources on the transmit leg; distinct per instance so the
# controller's readback cannot be satisfied by the other target's data.
TX_BYTE = {1: 0x5A, 2: 0xA5}

# Payload for the acquisition-stretch leg. The acquisition FIFO stops accepting
# entries with a couple of slots left, so the count only has to exceed the
# depth; the depth itself is read from the DUT rather than assumed.
ACQ_PAYLOAD = bytes((0x10 + i) & 0xFF for i in range(70))

# Bounds on the DUT-side observations, counted in clk_smc_i cycles so they
# scale with the randomised clock rather than against it. Expiry is a failure,
# never a pass.
POLL_CYCLES = 200
EVENT_POLL_LIMIT = 400
IDLE_POLL_LIMIT = 400
NACK_POLL_LIMIT = 400
FEED_POLL_LIMIT = 8000
DRAIN_LIMIT = 8000
SETTLE_CYCLES = 200
# Polls over which the controller must make no progress while the target
# reports its acquisition FIFO full.
STALL_POLLS = 8


class smc_i2c_target_multi_instance_stretch_test_seq(SmcCsrSeq):
    """Drive the target transmit, mismatch and stretch paths on I2C1 and I2C2."""

    def __init__(self, name: str = "smc_i2c_target_multi_instance_stretch_test_seq") -> None:
        super().__init__(name)
        self.tx_bytes: dict[int, int] = {}
        self.tx_stretch_events: dict[int, int] = {}
        self.acq_depth: dict[int, int] = {}
        self.acq_stalls: dict[int, int] = {}
        self.nack_events = 0

    # --- addressing ------------------------------------------------------
    @staticmethod
    def _addr(symbol: str, idx: int) -> int:
        return smc_indexed_addr(f"SMC_TOP_SMC_I2C_WRAP_I2C_{symbol}_BASE_ADDR", idx)

    @staticmethod
    def _wrap_addr(idx: int) -> int:
        return smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", idx)

    # --- bring-up --------------------------------------------------------
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

    async def _enable_target(self, idx: int, ctrl: int) -> None:
        await self.csr_write(f"I2C{idx}_WRAP_TGT", self._wrap_addr(idx), I2C_WRAP_CTRL_TARGET)
        await self._program_timing(idx)
        await self.csr_write(
            f"I2C{idx}_TARGET_ID",
            self._addr("TARGET_ID", idx),
            _pack_target_id(TARGET_ADDR[idx], 0x7F, 0, 0),
        )
        await self.csr_write(
            f"I2C{idx}_TGT_FIFO",
            self._addr("FIFO_CTRL", idx),
            I2C_FIFO_CTRL_RXRST_FMTRST | I2C_FIFO_CTRL_TXRST | I2C_FIFO_CTRL_ACQRST,
        )
        await self.csr_write(f"I2C{idx}_TGT_CTRL", self._addr("CTRL", idx), ctrl)

    async def _enable_host(self) -> None:
        await self.csr_write("HOST_WRAP", self._wrap_addr(HOST), I2C_WRAP_CTRL_HOST)
        await self._program_timing(HOST)
        await self.csr_write("HOST_OVRD", self._addr("OVRD", HOST), 0)
        await self.csr_write("HOST_FIFO", self._addr("FIFO_CTRL", HOST), I2C_FIFO_CTRL_RXRST_FMTRST)
        await self.csr_write(
            "HOST_CEVENTS", self._addr("CONTROLLER_EVENTS", HOST), I2C_CONTROLLER_EVENTS_ALL
        )
        await self.csr_write("HOST_CTRL", self._addr("CTRL", HOST), I2C_CTRL_ENABLEHOST)

    async def _wait_hostidle(self, label: str) -> int:
        status_addr = self._addr("STATUS", HOST)
        status = 0
        for _ in range(IDLE_POLL_LIMIT):
            status = await self.csr_read(f"{label}_IDLE", status_addr)
            if status & I2C_STATUS_HOSTIDLE and status & I2C_STATUS_FMTEMPTY:
                return status
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        raise AssertionError(
            f"{label}: controller I2C{HOST} never returned idle with its format FIFO drained "
            f"(STATUS=0x{status:08x})"
        )

    # --- leg: target transmit, with the transmit-FIFO stretch in front ----
    async def _transmit_leg(self, tgt: int) -> None:
        await self._disconnect_all()
        await self._enable_target(
            tgt, I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN | I2C_CTRL_TX_STRETCH_CTRL_EN
        )
        await self._enable_host()

        fdata = self._addr("FDATA", HOST)
        addr_r = (TARGET_ADDR[tgt] << 1) | 1
        await self.csr_write(f"I2C{tgt}_FDATA_START", fdata, I2C_FDATA_START | addr_r)
        await self.csr_write(f"I2C{tgt}_FDATA_READB", fdata, I2C_FDATA_READB | I2C_FDATA_STOP | 1)

        events_addr = self._addr("TARGET_EVENTS", tgt)
        events = 0
        for _ in range(EVENT_POLL_LIMIT):
            events = await self.csr_read(f"I2C{tgt}_TX_PENDING", events_addr)
            if events & I2C_TARGET_EVENTS_TX_PENDING:
                break
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        else:
            raise AssertionError(
                f"I2C{tgt} target never raised TARGET_EVENTS.TX_PENDING on a read with "
                f"CTRL.TX_STRETCH_CTRL_EN set and its transmit FIFO empty "
                f"(TARGET_EVENTS=0x{events:08x})"
            )
        self.tx_stretch_events[tgt] = events
        cocotb.log.info(
            "CHK-I2C%d-TGT-TX-STRETCH: the target held the read with TARGET_EVENTS=0x%08x "
            "(TX_PENDING) while its transmit FIFO was empty and CTRL.TX_STRETCH_CTRL_EN was set",
            tgt,
            events,
        )

        await self.csr_write(f"I2C{tgt}_TXDATA", self._addr("TXDATA", tgt), TX_BYTE[tgt])
        await self.csr_write(f"I2C{tgt}_CLR_TX_PENDING", events_addr, I2C_TARGET_EVENTS_TX_PENDING)

        status_addr = self._addr("STATUS", HOST)
        rdata_addr = self._addr("RDATA", HOST)
        got = -1
        for _ in range(EVENT_POLL_LIMIT):
            status = await self.csr_read(f"I2C{tgt}_HOST_RX", status_addr)
            if not status & I2C_STATUS_RXEMPTY:
                got = int(await self.csr_read(f"I2C{tgt}_RDATA", rdata_addr)) & 0xFF
                break
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        else:
            raise AssertionError(
                f"controller I2C{HOST} received no byte from target I2C{tgt} after the "
                f"transmit FIFO was supplied"
            )
        self.tx_bytes[tgt] = got
        assert got == TX_BYTE[tgt], (
            f"controller read 0x{got:02x} from target I2C{tgt}, expected the "
            f"0x{TX_BYTE[tgt]:02x} written to its TXDATA"
        )
        await self._wait_hostidle(f"I2C{tgt}_TX")
        cocotb.log.info(
            "CHK-I2C%d-TGT-READ: the target sourced 0x%02x onto the bus and the controller "
            "read exactly that byte back, then returned idle with its format FIFO drained",
            tgt,
            got,
        )

    # --- leg: address the bus at an address no target matches -------------
    async def _address_mismatch_leg(self, tgt: int) -> None:
        await self.csr_write(
            "HOST_CEVENTS_CLR", self._addr("CONTROLLER_EVENTS", HOST), I2C_CONTROLLER_EVENTS_ALL
        )
        await self.csr_write(
            f"I2C{tgt}_FIFO_RST_MISMATCH",
            self._addr("FIFO_CTRL", tgt),
            I2C_FIFO_CTRL_RXRST_FMTRST | I2C_FIFO_CTRL_TXRST | I2C_FIFO_CTRL_ACQRST,
        )
        entry = await self.csr_read(f"I2C{tgt}_STATUS_MISMATCH_ENTRY", self._addr("STATUS", tgt))
        assert entry & I2C_STATUS_ACQEMPTY, (
            f"I2C{tgt} acquisition FIFO is not empty before the unmatched-address transfer "
            f"(STATUS=0x{entry:08x})"
        )

        fdata = self._addr("FDATA", HOST)
        addr_w = (UNMATCHED_ADDR << 1) | 0
        await self.csr_write("MISMATCH_FDATA_START", fdata, I2C_FDATA_START | addr_w)
        await self.csr_write("MISMATCH_FDATA_STOP", fdata, I2C_FDATA_STOP | 0x00)
        # An unanswered address halts the controller with its format FIFO still
        # loaded, so what settles here is the event, not an idle controller.
        events_addr = self._addr("CONTROLLER_EVENTS", HOST)
        events = 0
        for _ in range(NACK_POLL_LIMIT):
            events = await self.csr_read("MISMATCH_CEVENTS", events_addr)
            if events & I2C_CONTROLLER_EVENTS_NACK:
                break
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        else:
            raise AssertionError(
                f"controller I2C{HOST} reported no NACK for address 0x{UNMATCHED_ADDR:02x}, "
                f"which no enabled target is programmed to match "
                f"(CONTROLLER_EVENTS=0x{events:08x})"
            )
        self.nack_events = events
        status = await self.csr_read(f"I2C{tgt}_STATUS_MISMATCH", self._addr("STATUS", tgt))
        assert status & I2C_STATUS_ACQEMPTY, (
            f"I2C{tgt} acquired an entry for address 0x{UNMATCHED_ADDR:02x}, which its "
            f"TARGET_ID (0x{TARGET_ADDR[tgt]:02x}) does not match (STATUS=0x{status:08x})"
        )
        cocotb.log.info(
            "CHK-I2C%d-TGT-ADDR-MISMATCH: address 0x%02x left the target's acquisition FIFO "
            "empty and the controller reporting CONTROLLER_EVENTS=0x%08x (NACK); the transmit "
            "leg above is the matching-address control on this same instance",
            tgt,
            UNMATCHED_ADDR,
            events,
        )

    # --- leg: fill the acquisition FIFO and hold the controller off -------
    async def _acq_stretch_leg(self, tgt: int) -> None:
        await self._disconnect_all()
        await self._enable_target(tgt, I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN)
        await self._enable_host()

        fdata = self._addr("FDATA", HOST)
        host_status = self._addr("STATUS", HOST)
        tgt_status = self._addr("STATUS", tgt)
        tgt_fifo = self._addr("TARGET_FIFO_STATUS", tgt)
        addr_w = (TARGET_ADDR[tgt] << 1) | 0
        await self.csr_write(f"I2C{tgt}_ACQ_FDATA_START", fdata, I2C_FDATA_START | addr_w)

        # Feed the controller until the target reports no room. A full format
        # FIFO is not a stop condition on its own: the controller drains it onto
        # the bus, so the loop simply waits for space.
        sent = 0
        full = 0
        for _ in range(FEED_POLL_LIMIT):
            full = await self.csr_read(f"I2C{tgt}_ACQ_STATUS", tgt_status)
            if full & I2C_STATUS_ACQFULL:
                break
            if sent >= len(ACQ_PAYLOAD) - 1:
                # The last byte carries the STOP and is held back for the drain
                # phase, so the transaction cannot end while the acquisition
                # FIFO is still full.
                await ClockCycles(cocotb.top.clk_smc_i, SETTLE_CYCLES)
                continue
            host = await self.csr_read(f"I2C{tgt}_ACQ_HOST_STATUS", host_status)
            if host & I2C_STATUS_FMTFULL:
                await ClockCycles(cocotb.top.clk_smc_i, SETTLE_CYCLES)
                continue
            await self.csr_write(f"I2C{tgt}_ACQ_FDATA", fdata, ACQ_PAYLOAD[sent])
            sent += 1
        else:
            raise AssertionError(
                f"I2C{tgt} never reported STATUS.ACQFULL after {sent} of {len(ACQ_PAYLOAD)} "
                f"payload bytes were queued with nothing draining ACQDATA "
                f"(STATUS=0x{full:08x})"
            )

        fifo = await self.csr_read(f"I2C{tgt}_ACQ_LEVEL", tgt_fifo)
        self.acq_depth[tgt] = (fifo >> 16) & 0xFFF
        assert self.acq_depth[tgt] > 0, (
            f"I2C{tgt} reports STATUS.ACQFULL with TARGET_FIFO_STATUS.ACQLVL 0 "
            f"(TARGET_FIFO_STATUS=0x{fifo:08x})"
        )

        # The hold: while the target has no room, the controller must still have
        # queued work and must not have finished.
        stalled = 0
        for _ in range(STALL_POLLS):
            await ClockCycles(cocotb.top.clk_smc_i, SETTLE_CYCLES)
            host = await self.csr_read(f"I2C{tgt}_STALL_HOST", host_status)
            tgt_now = await self.csr_read(f"I2C{tgt}_STALL_TGT", tgt_status)
            if (
                tgt_now & I2C_STATUS_ACQFULL
                and not host & I2C_STATUS_HOSTIDLE
                and not host & I2C_STATUS_FMTEMPTY
            ):
                stalled += 1
        self.acq_stalls[tgt] = stalled
        assert stalled == STALL_POLLS, (
            f"the controller made progress on {STALL_POLLS - stalled} of {STALL_POLLS} polls "
            f"taken while I2C{tgt} reported its acquisition FIFO full; a target that is "
            f"holding the bus leaves the controller busy with its format FIFO non-empty"
        )
        cocotb.log.info(
            "CHK-I2C%d-TGT-ACQ-STRETCH: STATUS.ACQFULL set with ACQLVL=%d, and on all %d polls "
            "taken while it stayed set the controller was still busy with queued format "
            "entries -- the target is holding it off",
            tgt,
            self.acq_depth[tgt],
            stalled,
        )

        # Release: drain ACQDATA and feed the rest, until the controller finishes.
        acquired: list[int] = []
        acq_addr = self._addr("ACQDATA", tgt)
        for _ in range(DRAIN_LIMIT):
            status = await self.csr_read(f"I2C{tgt}_DRAIN_STATUS", tgt_status)
            if not status & I2C_STATUS_ACQEMPTY:
                word = await self.csr_read(f"I2C{tgt}_ACQDATA", acq_addr)
                acquired.append(int(word) & 0xFFFF)
                continue
            if sent < len(ACQ_PAYLOAD):
                host = await self.csr_read(f"I2C{tgt}_DRAIN_HOST", host_status)
                if not host & I2C_STATUS_FMTFULL:
                    last = sent == len(ACQ_PAYLOAD) - 1
                    await self.csr_write(
                        f"I2C{tgt}_ACQ_FDATA_TAIL",
                        fdata,
                        (I2C_FDATA_STOP | ACQ_PAYLOAD[sent]) if last else ACQ_PAYLOAD[sent],
                    )
                    sent += 1
                continue
            host = await self.csr_read(f"I2C{tgt}_DRAIN_HOST_IDLE", host_status)
            if host & I2C_STATUS_HOSTIDLE and host & I2C_STATUS_FMTEMPTY:
                break
            await ClockCycles(cocotb.top.clk_smc_i, SETTLE_CYCLES)
        else:
            raise AssertionError(
                f"controller I2C{HOST} never finished the {len(ACQ_PAYLOAD)}-byte write to "
                f"I2C{tgt} after ACQDATA was drained ({sent} bytes queued, "
                f"{len(acquired)} entries acquired)"
            )
        await self._wait_hostidle(f"I2C{tgt}_ACQ")
        for _ in range(DRAIN_LIMIT):
            status = await self.csr_read(f"I2C{tgt}_TAIL_STATUS", tgt_status)
            if status & I2C_STATUS_ACQEMPTY:
                break
            word = await self.csr_read(f"I2C{tgt}_ACQDATA_TAIL", acq_addr)
            acquired.append(int(word) & 0xFFFF)
        else:
            raise AssertionError(f"I2C{tgt} acquisition FIFO never drained to empty")

        data = [acq_abyte(w) for w in acquired if acq_signal(w) == I2C_ACQ_SIGNAL_NONE]
        wanted = list(ACQ_PAYLOAD)
        assert len(data) == len(wanted), (
            f"I2C{tgt} acquired {len(data)} data bytes for the {len(wanted)} the controller wrote"
        )
        assert data == wanted, (
            f"I2C{tgt} acquired a different byte stream than the controller wrote; first "
            f"difference at index "
            f"{next(i for i, (a, b) in enumerate(zip(data, wanted)) if a != b)}"
        )
        released = await self.csr_read(f"I2C{tgt}_RELEASED", tgt_status)
        assert not released & I2C_STATUS_ACQFULL, (
            f"I2C{tgt} STATUS.ACQFULL still set after its acquisition FIFO drained to empty "
            f"(STATUS=0x{released:08x})"
        )
        cocotb.log.info(
            "CHK-I2C%d-TGT-ACQ-DRAIN: draining ACQDATA released the controller, which then "
            "completed the write; the target acquired all %d payload bytes in order and "
            "STATUS.ACQFULL is clear",
            tgt,
            len(data),
        )

    async def body(self) -> None:
        assert "smc_i2c_shared_bus" in cocotb.plusargs, (
            "smc_i2c_target_multi_instance_stretch_test needs +smc_i2c_shared_bus; without it "
            "only I2C0's pads are on the bench bus and I2C1/I2C2 cannot be addressed"
        )
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        for idx in INSTANCES:
            await self.arm_i2c_gpio_lsio(idx, f"I2C{idx}_LSIO")
        await self.wait_i2c_bus_released("I2C_SHARED_BUS")

        for tgt in (1, 2):
            await self._transmit_leg(tgt)
        await self._address_mismatch_leg(2)
        for tgt in (1, 2):
            await self._acq_stretch_leg(tgt)
        await self._disconnect_all()
