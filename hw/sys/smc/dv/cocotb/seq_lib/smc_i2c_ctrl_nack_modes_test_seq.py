# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 controller NACK reactions beyond the first-byte cases.

Contract SMC_I2C_CTRL_002, anchor smc_i2c_ctrl_nack_modes_test.
Scenarios: I2CC-ADDR-NACK.S2, I2CC-DATA-NACK.S2, I2CC-NAKOK.S2, I2CC-NAKOK.S3,
I2CC-HALT-RECOVERY.S1, I2CC-NACK-TIMEOUT.S1, I2CC-NACK-TIMEOUT.S2, I2CC-NACK-TIMEOUT.S3,
I2CC-STATUS-FLAGS.S6.
Sources: hw/ip/i2c/regs/i2c.rdl (CONTROLLER_EVENTS.NACK, INTR_STATE.CONTROLLER_HALT,
FDATA.NAKOK, HOST_NACK_HANDLER_TIMEOUT, STATUS.HOSTIDLE).

Bench targets on the I2C0 pads answer for the controller: 0x10 NACKs its address, 0x12
NACKs one chosen data byte, 0x50 is an EEPROM. A passive wire monitor frames every
transfer. Each leg ends with CTRL cleared before the events. The handler-timeout effect on
the bus (SF-010) and HOSTIDLE while halted (SF-015) are logged and not compared.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import I2C_CG_EN, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_fw_i2c_wire_monitor import I2cWireFrame, SmcFwI2cWireMonitor
from .smc_i2c_field_masks import (
    I2C_CONTROLLER_EVENTS_NACK,
    I2C_CONTROLLER_EVENTS_UNHANDLED_NACK_TIMEOUT,
    I2C_NACK_HANDLER_TIMEOUT_EN,
    I2C_STATUS_FMTEMPTY,
    I2C_WRAP_CONTROLLER_MODE,
    I2C_WRAP_EN,
)
from .smc_i2c_master_target_test_seq import (
    CLOCK_GATE_CONTROL,
    I2C0_CONTROLLER_EVENTS,
    I2C0_CTRL,
    I2C0_FDATA,
    I2C0_FIFO_CTRL,
    I2C0_OVRD,
    I2C0_STATUS,
    I2C0_TIMING0,
    I2C0_TIMING1,
    I2C0_TIMING2,
    I2C0_TIMING3,
    I2C0_TIMING4,
    I2C0_WRAP_CTRL,
    I2C_CONTROLLER_EVENTS_ALL,
    I2C_CTRL_ENABLEHOST,
    I2C_FDATA_READB,
    I2C_FDATA_START,
    I2C_FDATA_STOP,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_OVRD_OFF,
    I2C_STATUS_HOSTIDLE,
    _fdata,
    _i2c_u32,
    _pack_timing0,
    _pack_timing1,
    _pack_timing2,
    _pack_timing3,
    _pack_timing4,
)
from .smc_i2c_protocol_vip import (
    _SCL_LOW,
    _SDA_LOW,
    SmcI2cEepromSlave,
    SmcI2cNackSlave,
    _pads,
    _set_ext_low,
)


def _i2c0(register: str) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_I2C_WRAP_I2C_{register}_BASE_ADDR", 0)


I2C0_INTR_STATE = _i2c0("INTR_STATE")
I2C0_HOST_NACK_HANDLER_TIMEOUT = _i2c0("HOST_NACK_HANDLER_TIMEOUT")
I2C_INTR_CONTROLLER_HALT = _i2c_u32("I2C__INTR_STATE__CONTROLLER_HALT_bm")
I2C_FDATA_NAKOK = _i2c_u32("I2C__FDATA__NAKOK_bm")

NACK_ADDR = 0x10
DATA_NACK_ADDR = 0x12
EEPROM_ADDR = 0x50
EV_NACK = I2C_CONTROLLER_EVENTS_NACK
EV_UNHANDLED = I2C_CONTROLLER_EVENTS_UNHANDLED_NACK_TIMEOUT

HALT_READS = 3
HALT_GAP_CYCLES = 300
NTO_ENABLED_VAL = 256
NTO_CLEAR_VAL = 4096
CLEAR_DEADLINE_CYCLES = 400
S8_READ_CYCLES = 200
S9_WINDOW_CYCLES = 8192
S9_SAMPLE_CYCLES = 1024

BUS_RELEASE_POLLS = 2000
BUS_RELEASE_STEP = 4
EVENT_POLLS = 3000
EVENT_STEP = 8
FINE_POLLS = 6000
IDLE_POLLS = 3000
IDLE_STEP = 8
STOP_POLLS = 3000
STOP_STEP = 8
QUIET_POLLS = 24
QUIET_SAMPLES = 64
QUIET_STEP = 4

FENCE_ORDER = [
    "BRINGUP",
    "ADDR_NACK_READ",
    "HALT_LEVEL",
    "DATA_NACK_LATER",
    "NAKOK_DATA",
    "NAKOK_CONTROL",
    "NTO_ENABLED",
    "NTO_DISABLED",
    "NTO_CLEAR_OBS",
]
CHECKER_AFTER = {
    "CHK-ADDR-NACK-READ": "HALT_LEVEL",
    "CHK-HALT-LEVEL": "HALT_LEVEL",
    "CHK-DATA-NACK-LATER": "DATA_NACK_LATER",
    "CHK-NAKOK-DATA": "NAKOK_DATA",
    "CHK-NAKOK-CONTROL": "NAKOK_CONTROL",
    "CHK-NTO-ENABLED": "NTO_ENABLED",
    "CHK-NTO-DISABLED": "NTO_DISABLED",
    "CHK-NTO-CLEAR-OBS": "NTO_CLEAR_OBS",
    "CHK-STATUS-HALT-OBS": "NTO_CLEAR_OBS",
}


class _NthDataNackTarget:
    """Write target at ``addr`` that NACKs data byte ``nack_index`` of each frame.

    Every other byte is acknowledged, including the bytes after the NACKed one.
    """

    def __init__(self, addr: int, name: str) -> None:
        self.addr = addr & 0x7F
        self.nack_index: int | None = None
        self.addr_acks = 0
        self.data_acks = 0
        self.data_nacks = 0
        self.name = name
        sda, sda_ext, scl, scl_ext, clk = _pads()
        self._sda, self._sda_ext, self._scl, self._scl_ext, self._clk = (
            sda,
            sda_ext,
            scl,
            scl_ext,
            clk,
        )
        self._id = id(self)
        self._pull_sda(False)
        _set_ext_low(self._scl_ext, _SCL_LOW, self._id, False)
        self._task = cocotb.start_soon(self._run())

    def stop(self) -> None:
        self._task.cancel()
        self._pull_sda(False)

    def _pull_sda(self, low: bool) -> None:
        _set_ext_low(self._sda_ext, _SDA_LOW, self._id, low)

    async def _run(self) -> None:
        prev_scl = prev_sda = 1
        phase = "idle"
        bit_i = 0
        shift = 0
        index = 0
        while True:
            await RisingEdge(self._clk)
            if not (self._scl.value.is_resolvable and self._sda.value.is_resolvable):
                continue
            scl = int(self._scl.value)
            sda = int(self._sda.value)
            rose = (not prev_scl) and scl
            fell = prev_scl and (not scl)
            start = prev_scl and scl and prev_sda and (not sda)
            stop = prev_scl and scl and (not prev_sda) and sda
            if start:
                phase, bit_i, shift, index = "addr", 0, 0, 0
                self._pull_sda(False)
            elif stop:
                phase = "idle"
                self._pull_sda(False)
            elif phase in ("addr", "wdata") and rose:
                shift = ((shift << 1) | sda) & 0xFF
                bit_i += 1
                if bit_i >= 8:
                    phase = "aack" if phase == "addr" else "wack"
                    bit_i = 0
            elif phase == "aack" and fell:
                if ((shift >> 1) & 0x7F) != self.addr:
                    phase = "idle"
                    self._pull_sda(False)
                else:
                    self._pull_sda(True)
                    self.addr_acks += 1
                    phase = "ack_hold"
                    shift = 0
            elif phase == "wack" and fell:
                if index == self.nack_index:
                    self._pull_sda(False)
                    self.data_nacks += 1
                else:
                    self._pull_sda(True)
                    self.data_acks += 1
                index += 1
                phase = "ack_hold"
                shift = 0
            elif phase == "ack_hold" and rose:
                phase = "ack_rel"
            elif phase == "ack_rel" and fell:
                self._pull_sda(False)
                phase = "wdata"
            prev_scl, prev_sda = scl, sda


class smc_i2c_ctrl_nack_modes_test_seq(SmcCsrSeq):
    """Run the NACK legs on I2C0 against bench targets and log every measured state."""

    def __init__(self, name: str = "smc_i2c_ctrl_nack_modes_test_seq") -> None:
        super().__init__(name)
        self.monitor: SmcFwI2cWireMonitor | None = None
        self.nack_target: SmcI2cNackSlave | None = None
        self.data_target: _NthDataNackTarget | None = None
        self.eeprom: SmcI2cEepromSlave | None = None
        self.cycle = 0
        self.stamps: list[tuple[str, int]] = []
        self.chk_lines: list[tuple[str, int]] = []
        self.waits: list[tuple[str, str, str]] = []
        self.frame_start = 0
        self.stop_base = 0

    async def _count_cycles(self) -> None:
        clk = cocotb.top.clk_smc_i
        while True:
            await RisingEdge(clk)
            self.cycle += 1

    def _stamp(self, term: str) -> None:
        self.stamps.append((term, int(get_sim_time("ps"))))
        cocotb.log.info("FENCE %s @ %dps", term, self.stamps[-1][1])

    def _chk(self, name: str, line: str) -> None:
        cocotb.log.info("%s: %s", name, line)
        self.chk_lines.append((name, len(self.stamps)))

    @staticmethod
    def _bit(handle, name: str) -> int:
        value = handle.value
        assert value.is_resolvable, f"{name} sampled X/Z ({value})"
        return int(value) & 1

    def _pad_levels(self) -> str:
        dut = cocotb.top
        return " ".join(
            f"{n}={self._bit(getattr(dut, f'tb_i2c0_{n}'), f'tb_i2c0_{n}')}"
            for n in ("scl", "sda", "scl_dut_low", "sda_dut_low")
        )

    async def _poll(self, name: str, polls: int, step: int, probe) -> int:
        """Run ``probe`` up to ``polls`` times, ``step`` cycles apart; raise on expiry."""
        state = "never sampled"
        for _ in range(polls):
            done, state = await probe()
            if done:
                self.waits.append((name, f"{polls}x{step}cyc", state))
                return self.cycle
            await ClockCycles(cocotb.top.clk_smc_i, step)
        self.waits.append((name, f"{polls}x{step}cyc", f"EXPIRED {state}"))
        raise AssertionError(f"{name}: not satisfied within {polls}x{step} cycles; last {state}")

    async def _events(self, label: str) -> int:
        return await self.csr_read(label, I2C0_CONTROLLER_EVENTS)

    async def _halt(self, label: str) -> int:
        intr = await self.csr_read(label, I2C0_INTR_STATE)
        return int(bool(intr & I2C_INTR_CONTROLLER_HALT))

    async def _wait_events(
        self, name: str, mask: int, polls: int = EVENT_POLLS, step: int = EVENT_STEP
    ) -> tuple[int, int]:
        """Poll CONTROLLER_EVENTS until ``mask`` reads set; return (cycle seen, events)."""
        seen = [0]

        async def probe() -> tuple[bool, str]:
            seen[0] = await self._events(f"{name}_EVENTS")
            return bool(seen[0] & mask), f"events=0x{seen[0]:08x} want=0x{mask:08x}"

        cycle = await self._poll(name, polls, step, probe)
        return cycle, seen[0]

    def _frame(self, addr7: int, *, label: str) -> I2cWireFrame:
        frames = [f for f in self.monitor.frames[self.frame_start :] if f.addr7 == addr7]
        assert frames, f"{label}: no wire frame for 0x{addr7:02x}; {self.monitor.summary()}"
        return frames[0]

    def _stops(self) -> int:
        return self.monitor.stops - self.stop_base

    async def _bring_up_i2c0(self) -> None:
        dut = cocotb.top
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self.csr_write(
            "I2C0_WRAP_HOST", I2C0_WRAP_CTRL, I2C_WRAP_EN | I2C_WRAP_CONTROLLER_MODE
        )
        await self.arm_i2c_gpio_lsio(0, "I2C0_NACK_MODES")

        async def released() -> tuple[bool, str]:
            scl = self._bit(dut.tb_i2c0_scl, "tb_i2c0_scl")
            sda = self._bit(dut.tb_i2c0_sda, "tb_i2c0_sda")
            scl_i = self._bit(dut.tb_i2c0_scl_i, "tb_i2c0_scl_i")
            return (scl, sda, scl_i) == (1, 1, 1), f"scl={scl} sda={sda} scl_i={scl_i}"

        await self._poll("bus_released", BUS_RELEASE_POLLS, BUS_RELEASE_STEP, released)
        await self.csr_write("I2C0_TIMING0", I2C0_TIMING0, _pack_timing0(0x1A, 0x32))
        await self.csr_write("I2C0_TIMING1", I2C0_TIMING1, _pack_timing1(2, 2))
        await self.csr_write("I2C0_TIMING2", I2C0_TIMING2, _pack_timing2(5, 4))
        await self.csr_write("I2C0_TIMING3", I2C0_TIMING3, _pack_timing3(2, 5))
        await self.csr_write("I2C0_TIMING4", I2C0_TIMING4, _pack_timing4(4, 5))
        await self.csr_write("I2C0_OVRD_OFF", I2C0_OVRD, I2C_OVRD_OFF)
        await self.csr_write("I2C0_CTRL_OFF", I2C0_CTRL, 0)
        self.monitor = SmcFwI2cWireMonitor(name="smc_i2c0_nack_modes_wire")
        self.nack_target = SmcI2cNackSlave(
            addr=NACK_ADDR, nack_at_address=True, name="smc_i2c0_nack_addr"
        )
        self.data_target = _NthDataNackTarget(DATA_NACK_ADDR, "smc_i2c0_nack_data")
        self.eeprom = SmcI2cEepromSlave(addr=EEPROM_ADDR, name="smc_i2c0_nack_eeprom")
        self._stamp("BRINGUP")

    async def _leg_start(self, label: str) -> None:
        await self.csr_write(f"{label}_CTRL_OFF", I2C0_CTRL, 0)
        await self.csr_write(f"{label}_FIFO_RST", I2C0_FIFO_CTRL, I2C_FIFO_CTRL_RXRST_FMTRST)
        await self.csr_write(
            f"{label}_EVENTS_CLR", I2C0_CONTROLLER_EVENTS, I2C_CONTROLLER_EVENTS_ALL
        )
        await self.csr_write(f"{label}_INTR_CLR", I2C0_INTR_STATE, 0xFFFF_FFFF)
        await self.csr_write(f"{label}_ENABLEHOST", I2C0_CTRL, I2C_CTRL_ENABLEHOST)
        self.frame_start = len(self.monitor.frames)
        self.stop_base = self.monitor.stops

    async def _recover(self, label: str, clear_mask: int) -> tuple[int, int]:
        """CTRL first, bounded wait for the clock to stop, clear, read events and halt back."""
        dut = cocotb.top
        await self.csr_write(f"{label}_CTRL_OFF", I2C0_CTRL, 0)

        async def quiet() -> tuple[bool, str]:
            prev = self._bit(dut.tb_i2c0_scl, "tb_i2c0_scl")
            edges = 0
            for _ in range(QUIET_SAMPLES):
                await ClockCycles(dut.clk_smc_i, QUIET_STEP)
                cur = self._bit(dut.tb_i2c0_scl, "tb_i2c0_scl")
                edges += int(cur != prev)
                prev = cur
            return edges == 0, f"scl_edges={edges} {self._pad_levels()}"

        await self._poll(f"{label}_stop_clocking", QUIET_POLLS, 1, quiet)
        await self.csr_write(f"{label}_EVENTS_CLR", I2C0_CONTROLLER_EVENTS, clear_mask)
        events = await self._events(f"{label}_EVENTS_AFTER_CLR")
        halt = await self._halt(f"{label}_INTR_AFTER_CLR")
        return events, halt

    async def _queue(self, words: list[int]) -> None:
        for i, word in enumerate(words):
            await self.csr_write(f"FDATA_{i}", I2C0_FDATA, word)

    async def _nack_leg(self, label: str, target_words: list[int]) -> dict:
        await self._leg_start(label)
        await self._queue(target_words)
        cycle, events = await self._wait_events(f"{label}_nack", EV_NACK)
        halt = await self._halt(f"{label}_INTR_HALT")
        return {"cycle": cycle, "events": events, "halt": halt}

    async def _s2_addr_nack_read(self) -> dict:
        got = await self._nack_leg(
            "S2",
            [
                _fdata((NACK_ADDR << 1) | 1, I2C_FDATA_START),
                _fdata(1, I2C_FDATA_READB | I2C_FDATA_STOP),
            ],
        )
        assert got["events"] & EV_NACK and got["halt"] == 1, (
            f"S2: NACK/HALT not both set: events=0x{got['events']:08x} halt={got['halt']}"
        )
        frame = self._frame(NACK_ADDR, label="S2")
        assert frame.read is True and frame.addr_acked is False, (
            f"S2: wire frame for 0x{NACK_ADDR:02x} is {frame}, expected a NACKed read"
        )
        got["frame"] = str(frame)
        got["addr_nacks"] = self.nack_target.addr_nacks
        self._stamp("ADDR_NACK_READ")
        return got

    async def _s3_halt_level(self, s2: dict) -> None:
        rows = []
        prev_cycle = self.cycle
        for i in range(HALT_READS):
            await ClockCycles(cocotb.top.clk_smc_i, HALT_GAP_CYCLES)
            halt = await self._halt(f"S3_HALT_{i}")
            events = await self._events(f"S3_EVENTS_{i}")
            gap = self.cycle - prev_cycle
            prev_cycle = self.cycle
            assert gap >= HALT_GAP_CYCLES, f"S3 read {i}: gap {gap} < {HALT_GAP_CYCLES} cycles"
            assert events & EV_NACK, f"S3 read {i}: NACK cleared without a write (0x{events:08x})"
            assert halt == 1, f"S3 read {i}: CONTROLLER_HALT reads 0 with NACK set"
            rows.append(f"read{i}: halt={halt} nack=1 gap={gap}cyc")
        ev, halt = await self._recover("S3", EV_NACK)
        assert ev & EV_NACK == 0 and halt == 0, (
            f"S3: after CTRL=0 and clear, events=0x{ev:08x} halt={halt}"
        )
        self._stamp("HALT_LEVEL")
        self._chk(
            "CHK-ADDR-NACK-READ",
            f"set: read to 0x{NACK_ADDR:02x} NACKed by the target (addr_nacks="
            f"{s2['addr_nacks']}); observed: poll read events=0x{s2['events']:08x} "
            f"CONTROLLER_HALT={s2['halt']} wire frame {s2['frame']}; cleared: CTRL=0 then 1 "
            f"written to NACK; checked_cleared: events=0x{ev:08x} CONTROLLER_HALT={halt}",
        )
        self._chk(
            "CHK-HALT-LEVEL",
            f"set: CONTROLLER_HALT with NACK; observed: {'; '.join(rows)} with no clear "
            f"written; cleared: CTRL=0 then 1 written to NACK; checked_cleared: "
            f"CONTROLLER_HALT={halt}",
        )

    async def _s4_data_nack_later(self) -> None:
        self.data_target.nack_index = 1
        got = await self._nack_leg(
            "S4",
            [
                _fdata(DATA_NACK_ADDR << 1, I2C_FDATA_START),
                _fdata(0xC1),
                _fdata(0xC2),
                _fdata(0xC3, I2C_FDATA_STOP),
            ],
        )
        frame = self._frame(DATA_NACK_ADDR, label="S4")
        data = frame.data
        assert frame.addr_acked is True and frame.read is False, f"S4: frame {frame}"
        assert len(data) >= 2 and data[0] == (0xC1, True) and data[1] == (0xC2, False), (
            f"S4: wire frame {frame}, expected 0xC1 acknowledged and 0xC2 not acknowledged"
        )
        ev, halt = await self._recover("S4", EV_NACK)
        assert ev & EV_NACK == 0, f"S4: NACK still set after the clear (0x{ev:08x})"
        self._stamp("DATA_NACK_LATER")
        self._chk(
            "CHK-DATA-NACK-LATER",
            f"set: target 0x{DATA_NACK_ADDR:02x} NACKed data byte index 1 (data_nacks="
            f"{self.data_target.data_nacks}); observed: poll read events=0x{got['events']:08x}, "
            f"wire frame {frame}; cleared: CTRL=0 then 1 written to NACK; checked_cleared: "
            f"events=0x{ev:08x} halt={halt}",
        )

    @staticmethod
    def _nakok_words(nakok: int) -> list[int]:
        return [
            _fdata(DATA_NACK_ADDR << 1, I2C_FDATA_START),
            _fdata(0xD1, nakok),
            _fdata(0xD2),
            _fdata(0xD3, I2C_FDATA_STOP),
        ]

    async def _s5_nakok_data(self) -> None:
        self.data_target.nack_index = 0
        await self._leg_start("S5")
        await self._queue(self._nakok_words(I2C_FDATA_NAKOK))
        status = [0]

        async def idle() -> tuple[bool, str]:
            status[0] = await self.csr_read("S5_STATUS", I2C0_STATUS)
            want = I2C_STATUS_HOSTIDLE | I2C_STATUS_FMTEMPTY
            return status[0] & want == want, f"STATUS=0x{status[0]:08x}"

        await self._poll("s5_hostidle_fmtempty", IDLE_POLLS, IDLE_STEP, idle)
        stop_base = self.stop_base

        async def stopped() -> tuple[bool, str]:
            return self.monitor.stops > stop_base, self.monitor.summary()

        await self._poll("s5_wire_stop", STOP_POLLS, STOP_STEP, stopped)
        events = await self._events("S5_EVENTS")
        halt = await self._halt("S5_INTR_HALT")
        frame = self._frame(DATA_NACK_ADDR, label="S5")
        data = frame.data
        assert events == 0 and halt == 0, f"S5: events=0x{events:08x} halt={halt}"
        assert frame.addr_acked is True and [b for b, _ in data[:3]] == [0xD1, 0xD2, 0xD3], (
            f"S5: wire frame {frame}, expected 0xD1 0xD2 0xD3"
        )
        assert data[0][1] is False, f"S5: 0xD1 was acknowledged in {frame}"
        ev, hlt = await self._recover("S5", I2C_CONTROLLER_EVENTS_ALL)
        self._stamp("NAKOK_DATA")
        self._chk(
            "CHK-NAKOK-DATA",
            f"NAKOK on 0xD1 NACKed by 0x{DATA_NACK_ADDR:02x}: events=0x{events:08x} "
            f"CONTROLLER_HALT={halt} STATUS=0x{status[0]:08x} (HOSTIDLE and FMTEMPTY set); "
            f"wire frame {frame}; recovery readback events=0x{ev:08x} halt={hlt}",
        )

    async def _s6_nakok_control(self) -> None:
        self.data_target.nack_index = 0
        got = await self._nack_leg("S6", self._nakok_words(0))
        assert got["events"] & EV_NACK and got["halt"] == 1, (
            f"S6: NACK/HALT not both set: events=0x{got['events']:08x} halt={got['halt']}"
        )
        ev, halt = await self._recover("S6", EV_NACK)
        assert ev & EV_NACK == 0 and halt == 0, f"S6: after the clear events=0x{ev:08x} halt={halt}"
        self._stamp("NAKOK_CONTROL")
        self._chk(
            "CHK-NAKOK-CONTROL",
            f"set: 0xD1 NACKed without NAKOK; observed: events=0x{got['events']:08x} "
            f"CONTROLLER_HALT={got['halt']}; cleared: CTRL=0 then 1 written to NACK; "
            f"checked_cleared: events=0x{ev:08x} halt={halt}",
        )

    async def _s7_nto_enabled(self) -> int:
        await self.csr_write(
            "S7_HNH_TIMEOUT",
            I2C0_HOST_NACK_HANDLER_TIMEOUT,
            I2C_NACK_HANDLER_TIMEOUT_EN | NTO_ENABLED_VAL,
        )
        await self._leg_start("S7")
        await self._queue([_fdata(NACK_ADDR << 1, I2C_FDATA_START), _fdata(0x5A, I2C_FDATA_STOP)])
        first: dict[str, int] = {}
        last = [0]

        async def probe() -> tuple[bool, str]:
            last[0] = await self._events("S7_EVENTS")
            for name, mask in (("NACK", EV_NACK), ("UNHANDLED_NACK_TIMEOUT", EV_UNHANDLED)):
                if last[0] & mask and name not in first:
                    first[name] = self.cycle
            return "UNHANDLED_NACK_TIMEOUT" in first, f"events=0x{last[0]:08x} first={first}"

        await self._poll("s7_nack_then_timeout", FINE_POLLS, 1, probe)
        assert "NACK" in first, f"S7: UNHANDLED_NACK_TIMEOUT seen without NACK (0x{last[0]:08x})"
        latency = first["UNHANDLED_NACK_TIMEOUT"] - first["NACK"]

        async def stopped() -> tuple[bool, str]:
            return self._stops() >= 1, self.monitor.summary()

        await self._poll("s7_wire_stop", STOP_POLLS, STOP_STEP, stopped)
        stops = self._stops()
        order = "NACK first" if latency > 0 else "NACK and UNHANDLED_NACK_TIMEOUT on one read"
        assert stops == 1, f"S7: wire monitor counted {stops} STOPs, expected exactly 1"
        ev, halt = await self._recover("S7", EV_NACK | EV_UNHANDLED)
        assert ev == 0, f"S7: events read 0x{ev:08x} after the clear"
        self._stamp("NTO_ENABLED")
        self._chk(
            "CHK-NTO-ENABLED",
            f"set: HOST_NACK_HANDLER_TIMEOUT=EN|{NTO_ENABLED_VAL}, NACK at cycle "
            f"{first['NACK']}; observed: UNHANDLED_NACK_TIMEOUT=1 at cycle "
            f"{first['UNHANDLED_NACK_TIMEOUT']} (latency {latency} cycles, {order}), wire "
            f"STOPs={stops}; cleared: CTRL=0 then 1 written to NACK and "
            f"UNHANDLED_NACK_TIMEOUT; checked_cleared: events=0x{ev:08x} halt={halt}",
        )
        return latency

    async def _s8_nto_disabled(self, latency: int) -> None:
        assert latency > 0, f"S7 latency {latency} gives no observation window"
        window = 4 * latency
        await self.csr_write("S8_HNH_TIMEOUT", I2C0_HOST_NACK_HANDLER_TIMEOUT, 0)
        await self._leg_start("S8")
        await self._queue([_fdata(NACK_ADDR << 1, I2C_FDATA_START), _fdata(0x5A, I2C_FDATA_STOP)])
        cycle, events = await self._wait_events("s8_nack", EV_NACK)
        end = cycle + window
        rows = []
        while True:
            await ClockCycles(cocotb.top.clk_smc_i, S8_READ_CYCLES)
            events = await self._events("S8_EVENTS_WINDOW")
            rows.append(f"0x{events:08x}")
            assert events & EV_NACK, f"S8: NACK cleared without a write (0x{events:08x})"
            assert not events & EV_UNHANDLED, f"S8: UNHANDLED_NACK_TIMEOUT set (0x{events:08x})"
            if self.cycle >= end:
                break
        stops = self._stops()
        assert stops == 0, f"S8: {stops} STOPs counted on the wire in the window"
        observed = self.cycle - cycle
        assert observed >= window, f"S8: window {observed} cycles < 4 x L = {window}"
        self.waits.append(("s8_window", f"{window}cyc (4 x L={latency})", f"observed {observed}"))
        ev, halt = await self._recover("S8", EV_NACK | EV_UNHANDLED)
        self._stamp("NTO_DISABLED")
        self._chk(
            "CHK-NTO-DISABLED",
            f"HOST_NACK_HANDLER_TIMEOUT=0: window {observed} cycles >= 4 x L={latency} "
            f"(L from CHK-NTO-ENABLED), {len(rows)} reads every {S8_READ_CYCLES} cycles "
            f"events {','.join(rows)} (NACK stays 1, UNHANDLED_NACK_TIMEOUT stays 0), wire "
            f"STOPs={stops}; recovery readback events=0x{ev:08x} halt={halt}",
        )

    async def _s9_clear_before_expiry(self) -> None:
        await self.csr_write(
            "S9_HNH_TIMEOUT",
            I2C0_HOST_NACK_HANDLER_TIMEOUT,
            I2C_NACK_HANDLER_TIMEOUT_EN | NTO_CLEAR_VAL,
        )
        await self._leg_start("S9")
        await self._queue([_fdata(NACK_ADDR << 1, I2C_FDATA_START), _fdata(0x5A, I2C_FDATA_STOP)])
        cycle, events = await self._wait_events("s9_nack", EV_NACK)
        status = await self.csr_read("S9_STATUS_HALTED", I2C0_STATUS)
        await self.csr_write("S9_NACK_CLR", I2C0_CONTROLLER_EVENTS, EV_NACK)
        used = self.cycle - cycle
        assert used <= CLEAR_DEADLINE_CYCLES, (
            f"S9: NACK clear completed {used} cycles after the NACK, limit {CLEAR_DEADLINE_CYCLES}"
        )
        assert used < NTO_CLEAR_VAL, f"S9: NACK clear at {used} cycles, after the timeout expiry"
        end = self.cycle + S9_WINDOW_CYCLES
        rows = []
        while self.cycle < end:
            await ClockCycles(cocotb.top.clk_smc_i, S9_SAMPLE_CYCLES)
            st = await self.csr_read("S9_STATUS_WINDOW", I2C0_STATUS)
            ev = await self._events("S9_EVENTS_WINDOW")
            rows.append(
                f"t+{self.cycle - cycle}: HOSTIDLE={int(bool(st & I2C_STATUS_HOSTIDLE))} "
                f"events=0x{ev:08x} stops={self._stops()} {self._pad_levels()}"
            )
        self.waits.append(
            ("s9_window", f"{S9_WINDOW_CYCLES}cyc", f"{len(rows)} samples every {S9_SAMPLE_CYCLES}")
        )
        ev, halt = await self._recover("S9", EV_NACK | EV_UNHANDLED)
        self._stamp("NTO_CLEAR_OBS")
        self._chk(
            "CHK-STATUS-HALT-OBS",
            f"STATUS=0x{status:08x} HOSTIDLE={int(bool(status & I2C_STATUS_HOSTIDLE))} read "
            f"with NACK set (events=0x{events:08x}); no compare (SF-015)",
        )
        self._chk(
            "CHK-NTO-CLEAR-OBS",
            f"HOST_NACK_HANDLER_TIMEOUT=EN|{NTO_CLEAR_VAL}; NACK clear completed {used} cycles "
            f"after the NACK (limit {CLEAR_DEADLINE_CYCLES}, before expiry); {len(rows)} "
            f"samples over {S9_WINDOW_CYCLES} cycles, no compare (SF-010): {'; '.join(rows)}; "
            f"recovery readback events=0x{ev:08x} halt={halt}",
        )

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
        axi = ("sep_in_access", f"{cfg.axi_timeout_ns}ns", f"{self.accesses} accesses completed")
        waits = inherited + self.waits + [axi]
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits, each raising AssertionError with its last "
            "state on expiry; %s",
            len(waits),
            "; ".join(f"{n} bound={b} last={s}" for n, b, s in waits),
        )
        self.chk_lines.append(("CHK-TIMEOUT-PATHS", len(self.stamps)))

    def _emit_nonvac(self) -> None:
        order = [term for term, _ in self.stamps]
        assert order == FENCE_ORDER, f"fence order {order}, expected {FENCE_ORDER}"
        times = [ps for _, ps in self.stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        printed = dict(self.chk_lines)
        for name, term in CHECKER_AFTER.items():
            assert name in printed, f"{name} never printed"
            assert printed[name] > order.index(term), f"{name} printed before {term}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s ps",
            " < ".join(f"{t}={ps}" for t, ps in self.stamps),
            ",".join(name for name, _ in self.chk_lines),
            ",".join(str(ps) for ps in times),
        )

    async def body(self) -> None:
        counter = cocotb.start_soon(self._count_cycles())
        try:
            await self._bring_up_i2c0()
            s2 = await self._s2_addr_nack_read()
            await self._s3_halt_level(s2)
            await self._s4_data_nack_later()
            await self._s5_nakok_data()
            await self._s6_nakok_control()
            latency = await self._s7_nto_enabled()
            await self._s8_nto_disabled(latency)
            await self._s9_clear_before_expiry()
        finally:
            counter.cancel()
            self.nack_target.stop()
            self.data_target.stop()
            self.monitor.stop()
        self._emit_timeout_paths()
        self._emit_nonvac()
