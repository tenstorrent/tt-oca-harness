# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMBUS_CTRL.SMBALERT hardware clear by address match versus no clear on another address.

Contract SMC_I2C_SMBUS_011, anchor smc_smbus_alert_self_clear_test.
Scenarios: SMBALERT-SELF-CLEAR.S2, SMBALERT-SELF-CLEAR.S3.
Sources: hw/ip/i2c/regs/i2c.rdl (SMBUS_CTRL.SMBALERT hwclr, when the controller addresses this
target), open finding SF-008 for the race between a software write and the hardware clear.

A transfer to 0x55, which matches no TARGET_ID address, leaves the request bit set and the
alert pad asserted. A transfer to the own address 0x10 in the same run clears the bit and
releases the pad. A software write that lands while such a transfer is in flight is logged
without a compare.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import Timer
from cocotb.utils import get_sim_time

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_CTRL_ENABLETARGET,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_SMBUS_CTRL_SMBALERT,
    I2C_WRAP_CTRL_TARGET_SMBUS,
)
from .smc_i2c_protocol_vip import SmcI2cBusMonitor, SmcI2cMasterVip
from .smc_i2c_target_smbus_test_seq import (
    _pack_target_id,
    _pack_timing0,
    _pack_timing1,
    _pack_timing2,
    _pack_timing3,
    _pack_timing4,
)

I2C0 = 0
OWN_ADDR = 0x10
OTHER_ADDR = 0x55
VIP_SPEED = 100_000

POLLS = 500
POLL_US = 10
STABLE_POLLS = 8
START_POLLS = 2000
START_POLL_US = 1
TASK_POLLS = 2000
TASK_POLL_US = 10

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

FENCE_ORDER = ["SETUP", "OTHER_ADDR", "OWN_ADDR_CONTROL", "RACE", "TEARDOWN"]
CHECKER_AFTER = {
    "CHK-SELFCLEAR-OTHER-ADDR": "OWN_ADDR_CONTROL",
    "CHK-SELFCLEAR-RACE-LOG": "RACE",
    "CHK-TIMEOUT-PATHS": "TEARDOWN",
}


def _reg(name: str) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_I2C_WRAP_I2C_{name}_BASE_ADDR", I2C0)


I2C0_WRAP_CTRL = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", I2C0)
I2C0_OVRD = _reg("OVRD")
I2C0_CTRL = _reg("CTRL")
I2C0_FIFO_CTRL = _reg("FIFO_CTRL")
I2C0_TARGET_ID = _reg("TARGET_ID")
I2C0_SMBUS_CTRL = _reg("SMBUS_CTRL")
I2C0_TIMING = tuple(_reg(f"TIMING{n}") for n in range(5))


class smc_smbus_alert_self_clear_test_seq(SmcCsrSeq):
    """Other-address transfer, own-address control and an observe-only race leg."""

    def __init__(self, name: str = "smc_smbus_alert_self_clear_test_seq") -> None:
        super().__init__(name)
        self.stamps: list[tuple[str, int]] = []
        self.chk_lines: list[tuple[str, int]] = []
        self.waits: list[tuple[str, str, str]] = []
        self.monitor: SmcI2cBusMonitor | None = None
        self.master: SmcI2cMasterVip | None = None
        self.other: dict[str, int] = {}
        self.own: dict[str, int] = {}
        self.race: dict[str, int] = {}

    def _stamp(self, term: str) -> None:
        self.stamps.append((term, int(get_sim_time("ps"))))
        cocotb.log.info("FENCE %s @ %dps", term, self.stamps[-1][1])

    def _chk(self, name: str, line: str) -> None:
        cocotb.log.info("%s: %s", name, line)
        self.chk_lines.append((name, len(self.stamps)))

    @staticmethod
    def _pad() -> int:
        value = cocotb.top.tb_i2c0_smbalert.value
        assert value.is_resolvable, f"tb_i2c0_smbalert sampled X/Z ({value})"
        return int(value)

    async def _alert(self, label: str) -> int:
        word = await self.csr_read(label, I2C0_SMBUS_CTRL)
        return 1 if word & I2C_SMBUS_CTRL_SMBALERT else 0

    def _starts(self) -> int:
        assert self.monitor is not None
        return sum(1 for t in self.monitor.transactions if t["ev"] == "START")

    async def _wait_pad(self, name: str, want: int) -> int:
        """Bounded poll of the alert pad level; returns the polls taken."""
        last = "never sampled"
        for polls in range(POLLS):
            got = self._pad()
            last = f"tb_i2c0_smbalert={got}"
            if got == want:
                self.waits.append((name, f"{POLLS}x{POLL_US}us", last))
                return polls
            await Timer(POLL_US, unit="us")
        self.waits.append((name, f"{POLLS}x{POLL_US}us", f"EXPIRED {last}"))
        raise AssertionError(f"{name}: tb_i2c0_smbalert not {want} in {POLLS} polls; {last}")

    async def _join(self, name: str, task) -> None:
        for _ in range(TASK_POLLS):
            if task.done():
                task.result()
                self.waits.append((name, f"{TASK_POLLS}x{TASK_POLL_US}us", "transfer returned"))
                return
            await Timer(TASK_POLL_US, unit="us")
        self.waits.append((name, f"{TASK_POLLS}x{TASK_POLL_US}us", "EXPIRED transfer running"))
        raise AssertionError(f"{name}: transfer still running after {TASK_POLLS} polls")

    async def _setup(self) -> int:
        cg = await self.csr_read("I2C_CG", CLOCK_GATE_CONTROL)
        await self.csr_write("I2C_UNGATE", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self.csr_write("I2C0_DISABLE", I2C0_CTRL, 0)
        await self.csr_write("I2C0_WRAP_TARGET_SMBUS", I2C0_WRAP_CTRL, I2C_WRAP_CTRL_TARGET_SMBUS)
        await self.wait_i2c0_lsio_ready("I2C0_SELF_CLEAR")
        await self.arm_i2c_gpio_lsio(I2C0, "I2C0_SELF_CLEAR")
        await self.csr_write("I2C0_OVRD_OFF", I2C0_OVRD, 0)
        packers = (
            _pack_timing0(0x1A, 0x32),
            _pack_timing1(2, 2),
            _pack_timing2(5, 4),
            _pack_timing3(2, 5),
            _pack_timing4(4, 5),
        )
        for n, (addr, val) in enumerate(zip(I2C0_TIMING, packers)):
            await self.csr_write(f"I2C0_TIMING{n}", addr, val)
        await self.csr_write(
            "I2C0_FIFO_RST", I2C0_FIFO_CTRL, I2C_FIFO_CTRL_RXRST_FMTRST | I2C_FIFO_CTRL_TXRST
        )
        await self.csr_write(
            "I2C0_TARGET_ID", I2C0_TARGET_ID, _pack_target_id(OWN_ADDR, 0x7F, 0, 0)
        )
        await self.csr_write("I2C0_CTRL_TARGET", I2C0_CTRL, I2C_CTRL_ENABLETARGET)
        self.monitor = SmcI2cBusMonitor(name="smc_i2c0_self_clear_monitor")
        self.master = SmcI2cMasterVip(speed=VIP_SPEED, name="smc_i2c0_self_clear_master")
        self._stamp("SETUP")
        return cg

    async def _other_addr(self) -> None:
        assert self.master is not None
        await self.csr_write("SMBALERT_SET_OTHER", I2C0_SMBUS_CTRL, I2C_SMBUS_CTRL_SMBALERT)
        pad_polls = await self._wait_pad("alert_pad_low_other", 0)
        starts_before = self._starts()
        data = await self.master.read(OTHER_ADDR, 1)
        starts_new = self._starts() - starts_before
        assert starts_new >= 1, f"no START witnessed on the bus for the 0x{OTHER_ADDR:02x} read"
        assert data == bytes([0xFF]), f"read of 0x{OTHER_ADDR:02x} returned {data!r}, expected FF"
        bit = await self._alert("SMBALERT_AFTER_OTHER")
        pad = self._pad()
        assert bit == 1, f"SMBUS_CTRL.SMBALERT cleared by a transfer to 0x{OTHER_ADDR:02x}"
        assert pad == 0, f"tb_i2c0_smbalert={pad} after a transfer to 0x{OTHER_ADDR:02x}"
        self.other = {"pad_polls": pad_polls, "starts": starts_new, "bit": bit, "pad": pad}
        self._stamp("OTHER_ADDR")

    async def _own_addr_control(self) -> None:
        assert self.master is not None
        await self.master.write(OWN_ADDR, b"")
        bit = 1
        for polls in range(POLLS):
            bit = await self._alert("SMBALERT_POLL_OWN")
            if bit == 0:
                break
            await Timer(POLL_US, unit="us")
        else:
            self.waits.append(("alert_bit_clear_own", f"{POLLS}x{POLL_US}us", "EXPIRED bit=1"))
            raise AssertionError(f"SMBUS_CTRL.SMBALERT still 1 {POLLS} polls after 0x10 write")
        self.waits.append(("alert_bit_clear_own", f"{POLLS}x{POLL_US}us", f"bit=0 at {polls}"))
        pad_polls = await self._wait_pad("alert_pad_high_own", 1)
        self.own = {"bit_polls": polls, "pad_polls": pad_polls, "bit": bit, "pad": self._pad()}
        self._stamp("OWN_ADDR_CONTROL")
        self._chk(
            "CHK-SELFCLEAR-OTHER-ADDR",
            f"set: SMBUS_CTRL.SMBALERT written 1; observed: after a read of 0x{OTHER_ADDR:02x} "
            f"with {self.other['starts']} new START witnessed SMBUS_CTRL.SMBALERT="
            f"{self.other['bit']} and tb_i2c0_smbalert={self.other['pad']}; cleared: write to "
            f"own address 0x{OWN_ADDR:02x}; checked_cleared: SMBUS_CTRL.SMBALERT="
            f"{self.own['bit']} after {polls} polls and tb_i2c0_smbalert={self.own['pad']} "
            f"after {pad_polls} polls",
        )

    async def _race(self) -> None:
        assert self.master is not None
        await self.csr_write("SMBALERT_SET_RACE", I2C0_SMBUS_CTRL, I2C_SMBUS_CTRL_SMBALERT)
        starts_before = self._starts()
        task = cocotb.start_soon(self.master.write(OWN_ADDR, b""))
        for _ in range(START_POLLS):
            if self._starts() > starts_before:
                break
            await Timer(START_POLL_US, unit="us")
        else:
            self.waits.append(("race_start", f"{START_POLLS}x{START_POLL_US}us", "EXPIRED"))
            raise AssertionError(f"race: no START within {START_POLLS} polls")
        self.waits.append(("race_start", f"{START_POLLS}x{START_POLL_US}us", "START logged"))
        await self.csr_write("SMBALERT_SET_RACE_AGAIN", I2C0_SMBUS_CTRL, I2C_SMBUS_CTRL_SMBALERT)
        await self._join("race_transfer", task)

        last = (-1, -1)
        run = 0
        for polls in range(POLLS):
            pair = (await self._alert("SMBALERT_RACE_POLL"), self._pad())
            run = run + 1 if pair == last else 1
            last = pair
            if run >= STABLE_POLLS:
                break
            await Timer(POLL_US, unit="us")
        else:
            self.waits.append(
                ("race_stable_pair", f"{POLLS}x{POLL_US}us", f"EXPIRED last bit,pad={last}")
            )
            raise AssertionError(f"race: no stable pair in {POLLS} polls; last bit,pad={last}")
        self.waits.append(("race_stable_pair", f"{POLLS}x{POLL_US}us", f"bit,pad={last}"))
        self.race = {"bit": last[0], "pad": last[1], "polls": polls + 1}
        self._stamp("RACE")
        self._chk(
            "CHK-SELFCLEAR-RACE-LOG",
            f"final_smbalert_bit={last[0]} final_tb_i2c0_smbalert={last[1]} stable_in_"
            f"{STABLE_POLLS}_consecutive_polls after {polls + 1} polls; second write landed after "
            f"the transfer START; logged only, no value compared (SF-008)",
        )

    async def _teardown(self, cg: int) -> None:
        await self.csr_write("SMBALERT_CLEAR", I2C0_SMBUS_CTRL, 0)
        await self.csr_write("I2C0_CTRL_OFF", I2C0_CTRL, 0)
        await self.csr_write("I2C0_WRAP_OFF", I2C0_WRAP_CTRL, 0)
        await self.csr_write("I2C_CG_RESTORE", CLOCK_GATE_CONTROL, cg)
        self._stamp("TEARDOWN")

    def _emit_timeout_paths(self) -> None:
        cfg = self.cfg
        inherited = [
            (
                "cold_reset_release",
                f"{max(cfg.post_reset_settle_cycles, 2000)} clk_ref_i cycles",
                "chain released before bring-up returned",
            ),
            ("pll_period_measure", "5 rising edges per clock", "periods within tolerance"),
            ("i2c0_lsio_ready", "wait_i2c0_lsio_ready bound", "ready before setup continued"),
            ("vip_scl_release", "100000 half periods per wait", "no hold expired"),
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
        cg = await self._setup()
        await self._other_addr()
        await self._own_addr_control()
        await self._race()
        await self._teardown(cg)
        self._emit_timeout_paths()
        self._emit_nonvac()
