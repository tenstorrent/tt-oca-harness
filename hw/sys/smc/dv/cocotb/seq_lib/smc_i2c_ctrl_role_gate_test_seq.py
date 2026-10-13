# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 controller role gate, queue occupancy and pad-control readback.

Contract SMC_I2C_CTRL_001, anchor smc_i2c_ctrl_role_gate_test.
Scenarios: I2CC-ROLE-ENABLE.S1, I2CC-ROLE-ENABLE.S3, I2CC-PAD-PATH.S3, I2CC-PAD-PATH.S5,
I2CC-STATUS-FLAGS.S3.
Sources: hw/ip/i2c/regs/i2c.rdl (CTRL.ENABLEHOST, FDATA, STATUS.FMTEMPTY, VAL),
hw/ip/i2c/regs/i2c_ctrl.rdl (I2C_CTRL.I2C_EN).

Three FDATA entries are queued with both core roles off; the pads stay idle and the
bench EEPROM sees no START. Setting `CTRL.ENABLEHOST` then runs the queued stream, which
the EEPROM frames as one START, one STOP and one data byte. Clearing `I2C_CTRL.I2C_EN`
leaves the core role enables where they were. `VAL` is read with the lines released and
pulled low and the words are logged without a compare while the oversampling rate is open
(SF-018).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, Timer
from cocotb.utils import get_sim_time

from .smc_addr_map import I2C_CG_EN, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_CTRL_ENABLETARGET,
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
    I2C_FDATA_START,
    I2C_FDATA_STOP,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_OVRD_OFF,
    _fdata,
    _pack_timing0,
    _pack_timing1,
    _pack_timing2,
    _pack_timing3,
    _pack_timing4,
)
from .smc_i2c_protocol_vip import SmcI2cEepromSlave, SmcI2cMasterVip


def _i2c0(register: str) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_I2C_WRAP_I2C_{register}_BASE_ADDR", 0)


I2C0_INTR_STATE = _i2c0("INTR_STATE")
I2C0_VAL = _i2c0("VAL")

EEPROM_ADDR = 0x50
MEM_OFFSET = 0x10
DATA_BYTE = 0xA7
WINDOW_CYCLES = 4000
SAMPLE_CYCLES = 16
PULL_CYCLES = 2000
CLEAR_WINDOW_SAMPLES = 16

BUS_RELEASE_POLLS = 2000
BUS_RELEASE_STEP = 4
START_POLLS = 8000
STOP_POLLS = 2500
STOP_STEP = 16
DRAIN_POLLS = 400
DRAIN_STEP = 20
VAL_AGREE_POLLS = 50
VAL_AGREE_STEP = 4
LEVEL_POLLS = 500
LEVEL_STEP = 4

FENCE_ORDER = [
    "BRINGUP",
    "QUEUE_DISABLED",
    "DISABLED_WINDOW",
    "ENABLE",
    "TARGET_STOP",
    "IEN_TOGGLE",
    "VAL_OBS",
]
CHECKER_AFTER = {
    "CHK-ROLE-OFF-IDLE": "ENABLE",
    "CHK-FMTEMPTY-TRACK": "TARGET_STOP",
    "CHK-ROLE-ON-RUNS": "TARGET_STOP",
    "CHK-IEN-ROLE-INDEP": "IEN_TOGGLE",
    "CHK-VAL-OBS": "VAL_OBS",
}


class smc_i2c_ctrl_role_gate_test_seq(SmcCsrSeq):
    """Queue FDATA with the roles off, enable the controller, observe the gate."""

    def __init__(self, name: str = "smc_i2c_ctrl_role_gate_test_seq") -> None:
        super().__init__(name)
        self.slave: SmcI2cEepromSlave | None = None
        self.stamps: list[tuple[str, int]] = []
        self.chk_lines: list[tuple[str, int]] = []
        self.waits: list[tuple[str, str, str]] = []

    def _stamp(self, term: str) -> None:
        self.stamps.append((term, int(get_sim_time("ps"))))
        cocotb.log.info("FENCE %s @ %dps", term, self.stamps[-1][1])

    def _chk(self, name: str, line: str) -> None:
        cocotb.log.info("%s: %s", name, line)
        self.chk_lines.append((name, len(self.stamps)))

    @staticmethod
    def _bit(handle, name: str, index: int = 0) -> int:
        value = handle.value
        assert value.is_resolvable, f"{name} sampled X/Z ({value})"
        return (int(value) >> index) & 1

    def _pads(self) -> dict[str, int]:
        dut = cocotb.top
        return {
            name: self._bit(getattr(dut, f"tb_i2c0_{name}"), f"tb_i2c0_{name}")
            for name in ("scl", "sda", "scl_dut_low", "sda_dut_low")
        }

    async def _poll(self, name: str, polls: int, step: int, probe) -> int:
        """Run ``probe`` up to ``polls`` times, ``step`` cycles apart; raise on expiry."""
        state = "never sampled"
        for waited in range(polls):
            done, state = await probe()
            if done:
                self.waits.append((name, f"{polls}x{step}cyc", state))
                return waited * step
            await ClockCycles(cocotb.top.clk_smc_i, step)
        self.waits.append((name, f"{polls}x{step}cyc", f"EXPIRED {state}"))
        raise AssertionError(f"{name}: not satisfied within {polls}x{step} cycles; last {state}")

    async def _level_wait(self, name: str, line: str, level: int) -> None:
        dut = cocotb.top

        async def probe() -> tuple[bool, str]:
            value = self._bit(getattr(dut, f"tb_i2c0_{line}"), f"tb_i2c0_{line}")
            return value == level, f"tb_i2c0_{line}={value}"

        await self._poll(name, LEVEL_POLLS, LEVEL_STEP, probe)

    async def _status(self, label: str) -> int:
        return await self.csr_read(label, I2C0_STATUS)

    async def _bring_up_i2c0(self) -> None:
        dut = cocotb.top
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self.csr_write(
            "I2C0_WRAP_HOST", I2C0_WRAP_CTRL, I2C_WRAP_EN | I2C_WRAP_CONTROLLER_MODE
        )
        await self.arm_i2c_gpio_lsio(0, "I2C0_ROLE_GATE")

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
        await self.csr_write("I2C0_FIFO_RST", I2C0_FIFO_CTRL, I2C_FIFO_CTRL_RXRST_FMTRST)
        await self.csr_write("I2C0_EVENTS_CLR", I2C0_CONTROLLER_EVENTS, I2C_CONTROLLER_EVENTS_ALL)
        await self.csr_write("I2C0_INTR_CLR", I2C0_INTR_STATE, 0xFFFF_FFFF)
        await self.csr_write("I2C0_CTRL_OFF", I2C0_CTRL, 0)
        ctrl = await self.csr_read("I2C0_CTRL_ENTRY", I2C0_CTRL)
        assert ctrl & (I2C_CTRL_ENABLEHOST | I2C_CTRL_ENABLETARGET) == 0, (
            f"CTRL reads 0x{ctrl:08x} after it was written to 0"
        )
        self.slave = SmcI2cEepromSlave(addr=EEPROM_ADDR, name="smc_i2c0_role_gate_eeprom")
        await Timer(1, unit="us")
        self._stamp("BRINGUP")

    async def _disabled_window(self) -> dict[str, int]:
        await self.csr_write("FDATA_ADDR", I2C0_FDATA, _fdata(EEPROM_ADDR << 1, I2C_FDATA_START))
        first = await self._status("STATUS_AFTER_FIRST")
        await self.csr_write("FDATA_OFFSET", I2C0_FDATA, _fdata(MEM_OFFSET))
        await self.csr_write("FDATA_DATA", I2C0_FDATA, _fdata(DATA_BYTE, I2C_FDATA_STOP))
        third = await self._status("STATUS_AFTER_THIRD")
        assert not first & I2C_STATUS_FMTEMPTY and not third & I2C_STATUS_FMTEMPTY, (
            f"STATUS.FMTEMPTY set with entries queued (after first 0x{first:08x}, "
            f"after third 0x{third:08x})"
        )
        self._stamp("QUEUE_DISABLED")

        samples = 0
        bad: list[dict[str, int]] = []
        for _ in range(WINDOW_CYCLES // SAMPLE_CYCLES):
            pads = self._pads()
            samples += 1
            if pads != {"scl": 1, "sda": 1, "scl_dut_low": 0, "sda_dut_low": 0}:
                bad.append(pads)
            await ClockCycles(cocotb.top.clk_smc_i, SAMPLE_CYCLES)
        starts = self.slave.starts
        end = await self._status("STATUS_WINDOW_END")
        assert samples > 0 and not bad, f"pad samples left idle during the window: {bad[:3]}"
        assert starts == 0, f"the target framed {starts} START(s) with ENABLEHOST clear"
        assert not end & I2C_STATUS_FMTEMPTY, (
            f"STATUS.FMTEMPTY set at the end of the disabled window (0x{end:08x})"
        )
        self._stamp("DISABLED_WINDOW")
        self.fmtempty = {"first": first, "third": third, "end": end}
        return {"samples": samples, "starts": starts}

    async def _enable_and_run(self, window: dict[str, int]) -> dict[str, int]:
        slave = self.slave
        await self.csr_write("CTRL_ENABLEHOST", I2C0_CTRL, I2C_CTRL_ENABLEHOST)
        dut = cocotb.top

        async def started() -> tuple[bool, str]:
            sda = self._bit(dut.tb_i2c0_sda, "tb_i2c0_sda")
            return sda == 0 or slave.starts > 0, f"sda={sda} target_starts={slave.starts}"

        latency = await self._poll("start_latency", START_POLLS, 1, started)
        assert WINDOW_CYCLES >= 4 * latency, (
            f"the disabled window ({WINDOW_CYCLES} cycles) is shorter than 4 x L ({latency})"
        )
        self._stamp("ENABLE")
        self._chk(
            "CHK-ROLE-OFF-IDLE",
            f"{window['samples']} samples every {SAMPLE_CYCLES} cycles over {WINDOW_CYCLES} "
            f"cycles with ENABLEHOST=0 ENABLETARGET=0 and three entries queued read scl=1 sda=1 "
            f"scl_dut_low=0 sda_dut_low=0; target starts={window['starts']}; "
            f"window={WINDOW_CYCLES} >= 4 x L={latency} cycles",
        )

        async def stopped() -> tuple[bool, str]:
            return slave.stops >= 1, f"starts={slave.starts} stops={slave.stops}"

        await self._poll("stop_frame", STOP_POLLS, STOP_STEP, stopped)

        async def drained() -> tuple[bool, str]:
            status = await self._status("STATUS_DRAIN")
            return bool(status & I2C_STATUS_FMTEMPTY), f"STATUS=0x{status:08x}"

        await self._poll("fmtempty_drain", DRAIN_POLLS, DRAIN_STEP, drained)
        self._stamp("TARGET_STOP")
        self._chk(
            "CHK-FMTEMPTY-TRACK",
            "STATUS.FMTEMPTY=0 after the first FDATA write "
            f"(STATUS=0x{self.fmtempty['first']:08x}), after the third "
            f"(0x{self.fmtempty['third']:08x}) and at the window end "
            f"(0x{self.fmtempty['end']:08x}); FMTEMPTY=1 after the target STOP",
        )
        return {"latency": latency}

    def _observe_target(self) -> dict[str, int]:
        slave = self.slave
        seen = {
            "starts": slave.starts,
            "stops": slave.stops,
            "bytes": slave.bytes,
            "mem": slave.read_mem(MEM_OFFSET, 1)[0],
        }
        return seen

    async def _ien_toggle(self) -> list[str]:
        dut = cocotb.top
        rows: list[str] = []
        for want in (0, 1):
            wrap = I2C_WRAP_CONTROLLER_MODE | (I2C_WRAP_EN if want else 0)
            await self.csr_write(f"I2C_EN_{want}", I2C0_WRAP_CTRL, wrap)
            wrap_rb = await self.csr_read(f"I2C_CTRL_RB_{want}", I2C0_WRAP_CTRL)
            ctrl = await self.csr_read(f"CTRL_RB_{want}", I2C0_CTRL)
            host = self._bit(dut.tb_i2c_host_enable, "tb_i2c_host_enable")
            target = self._bit(dut.tb_i2c_target_enable, "tb_i2c_target_enable")
            got = int(bool(wrap_rb & I2C_WRAP_EN))
            en_host = int(bool(ctrl & I2C_CTRL_ENABLEHOST))
            en_target = int(bool(ctrl & I2C_CTRL_ENABLETARGET))
            assert got == want, f"I2C_CTRL.I2C_EN reads {got} after writing {want}"
            assert (en_host, en_target) == (1, 0), (
                f"CTRL reads ENABLEHOST={en_host} ENABLETARGET={en_target} with I2C_EN={want}"
            )
            assert (host, target) == (1, 0), (
                f"core enables host={host} target={target} with I2C_EN={want}"
            )
            rows.append(
                f"I2C_EN={want}: I2C_CTRL=0x{wrap_rb:08x} ENABLEHOST={en_host} "
                f"ENABLETARGET={en_target} host_enable={host} target_enable={target}"
            )
        self._stamp("IEN_TOGGLE")
        self._chk("CHK-IEN-ROLE-INDEP", "; ".join(rows))
        return rows

    async def _val_stable(self, label: str) -> int:
        last = [None]

        async def agree() -> tuple[bool, str]:
            word = await self.csr_read(label, I2C0_VAL)
            previous, last[0] = last[0], word
            return previous == word, f"VAL=0x{word:08x} previous={previous}"

        await self._poll(f"val_agree_{label}", VAL_AGREE_POLLS, VAL_AGREE_STEP, agree)
        return last[0]

    async def _val_obs(self) -> None:
        master = SmcI2cMasterVip(name="smc_i2c0_role_gate_pull")
        words: list[str] = []
        released = await self._val_stable("VAL_RELEASED_A")
        pads = self._pads()
        words.append(f"released_a=0x{released:08x} scl={pads['scl']} sda={pads['sda']}")
        for line, pull in (("scl", master._pull_scl), ("sda", master._pull_sda)):
            pull(True)
            await self._level_wait(f"{line}_pulled_low", line, 0)
            await ClockCycles(cocotb.top.clk_smc_i, PULL_CYCLES)
            word = await self.csr_read(f"VAL_{line.upper()}_LOW", I2C0_VAL)
            pads = self._pads()
            words.append(f"{line}_low=0x{word:08x} scl={pads['scl']} sda={pads['sda']}")
            pull(False)
            await self._level_wait(f"{line}_released", line, 1)
        final = await self.csr_read("VAL_RELEASED_B", I2C0_VAL)
        pads = self._pads()
        words.append(f"released_b=0x{final:08x} scl={pads['scl']} sda={pads['sda']}")
        self._stamp("VAL_OBS")
        self._chk("CHK-VAL-OBS", "; ".join(words))

    async def _clear_leg(self, seen: dict[str, int]) -> None:
        before = self._observe_target()
        await self.csr_write("CTRL_CLEAR", I2C0_CTRL, 0)
        ctrl = await self.csr_read("CTRL_CLEARED", I2C0_CTRL)
        assert ctrl & I2C_CTRL_ENABLEHOST == 0, (
            f"CTRL.ENABLEHOST reads set after clear (0x{ctrl:08x})"
        )
        for _ in range(CLEAR_WINDOW_SAMPLES):
            pads = self._pads()
            assert pads["scl_dut_low"] == 0 and pads["sda_dut_low"] == 0, (
                f"a dut_low probe is set after CTRL was cleared: {pads}"
            )
            await ClockCycles(cocotb.top.clk_smc_i, SAMPLE_CYCLES)
        after = self._observe_target()
        assert after == before, f"target counters moved after the clear: {before} -> {after}"
        self._chk(
            "CHK-ROLE-ON-RUNS",
            f"set: ENABLEHOST written with three entries queued, start latency L="
            f"{self.latency} cycles; observed: starts={seen['starts']} stops={seen['stops']} "
            f"mem[0x{MEM_OFFSET:02x}]=0x{seen['mem']:02x} data_bytes={seen['bytes']}; "
            f"cleared: CTRL written to 0; checked_cleared: dut_low probes 0 over "
            f"{CLEAR_WINDOW_SAMPLES} samples and target counters unchanged {after}",
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
        await self._bring_up_i2c0()
        window = await self._disabled_window()
        run = await self._enable_and_run(window)
        self.latency = run["latency"]
        seen = self._observe_target()
        assert seen == {"starts": 1, "stops": 1, "bytes": 1, "mem": DATA_BYTE}, (
            f"the target framed {seen}; expected 1 START, 1 STOP, 1 data byte, "
            f"mem[0x{MEM_OFFSET:02x}]=0x{DATA_BYTE:02x}"
        )
        await self._ien_toggle()
        await self._val_obs()
        await self._clear_leg(seen)
        self._emit_timeout_paths()
        self._emit_nonvac()
