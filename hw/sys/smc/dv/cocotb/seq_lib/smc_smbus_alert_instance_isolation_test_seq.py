# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Per-instance SMBUS_EN isolation of the SMBALERT gate across the three I2C instances.

Sources: hw/ip/i2c/regs/i2c_ctrl.rdl (I2C_CTRL array), hw/ip/i2c/regs/i2c.rdl (SMBUS_STATUS),
hw/ip/i2c/doc/index.adoc (OCAH Modifications).
The specification does not state the padring reach.

With the three alert pads driven low, clearing SMBUS_EN on one instance leaves
SMBUS_STATUS.SMBALERT of the other two at 1 and masks its own SMBUS_STATUS.SMBALERT to 0.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import Timer
from cocotb.utils import get_sim_time

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_CTRL_ENABLEHOST,
    I2C_INTR_STATE_SMBALERT,
    I2C_SMBUS_STATUS_SMBALERT,
    I2C_WRAP_CTRL_HOST_SMBUS,
    I2C_WRAP_SMBUS_EN,
)
from .smc_pad_table import pad_index

INSTANCES = (0, 1, 2)
ALERT_PADS = tuple(pad_index(f"I2C[{i}] SMB_A") for i in INSTANCES)

POLLS = 500
POLL_US = 10
OBSERVE_POLLS = 16

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

FENCE_ORDER = ["SETUP", "GATE_ROUNDS", "TEARDOWN"]
CHECKER_AFTER = {
    "CHK-GATE-ALL-SEE-ALERT": "GATE_ROUNDS",
    "CHK-GATE-OTHERS-UNMASKED": "GATE_ROUNDS",
    "CHK-TIMEOUT-PATHS": "TEARDOWN",
}


def _reg(name: str, idx: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_I2C_WRAP_I2C_{name}_BASE_ADDR", idx)


def _wrap_ctrl(idx: int) -> int:
    return smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", idx)


class smc_smbus_alert_instance_isolation_test_seq(SmcCsrSeq):
    """Gate rounds on SMBUS_EN per instance."""

    def __init__(self, name: str = "smc_smbus_alert_instance_isolation_test_seq") -> None:
        super().__init__(name)
        self.stamps: list[tuple[str, int]] = []
        self.chk_lines: list[tuple[str, int]] = []
        self.waits: list[tuple[str, str, str]] = []
        self.gate: dict[int, dict[str, object]] = {}

    def _stamp(self, term: str) -> None:
        self.stamps.append((term, int(get_sim_time("ps"))))
        cocotb.log.info("FENCE %s @ %dps", term, self.stamps[-1][1])

    def _chk(self, name: str, line: str) -> None:
        cocotb.log.info("%s: %s", name, line)
        self.chk_lines.append((name, len(self.stamps)))

    def _drive_alert_low(self, low: bool) -> None:
        dut = cocotb.top
        mask = 0
        for pad in ALERT_PADS:
            mask |= 1 << pad
        en = int(dut.tb_gpio_ext_drive_en.value)
        val = int(dut.tb_gpio_ext_drive_value.value)
        if low:
            en |= mask
            val &= ~mask
        else:
            en &= ~mask
            val |= mask
        dut.tb_gpio_ext_drive_en.value = en
        dut.tb_gpio_ext_drive_value.value = val

    async def _status(self, label: str, idx: int) -> int:
        word = await self.csr_read(label, _reg("SMBUS_STATUS", idx))
        return 1 if word & I2C_SMBUS_STATUS_SMBALERT else 0

    async def _poll_all(self, name: str, want: int) -> int:
        """Bounded poll until SMBUS_STATUS.SMBALERT of all three instances equals ``want``."""
        last = "never sampled"
        for polls in range(POLLS):
            got = [await self._status(f"{name}_{i}", i) for i in INSTANCES]
            last = f"SMBUS_STATUS.SMBALERT={got}"
            if got == [want] * 3:
                self.waits.append((name, f"{POLLS}x{POLL_US}us", last))
                return polls + 1
            await Timer(POLL_US, unit="us")
        self.waits.append((name, f"{POLLS}x{POLL_US}us", f"EXPIRED {last}"))
        raise AssertionError(f"{name}: not all {want} in {POLLS} polls; {last}")

    async def _setup(self) -> int:
        cg = await self.csr_read("I2C_CG", CLOCK_GATE_CONTROL)
        await self.csr_write("I2C_UNGATE", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        for i in INSTANCES:
            await self.csr_write(f"I2C{i}_WRAP_HOST_SMBUS", _wrap_ctrl(i), I2C_WRAP_CTRL_HOST_SMBUS)
            await self.csr_write(f"I2C{i}_CTRL_HOST", _reg("CTRL", i), I2C_CTRL_ENABLEHOST)
            await self.csr_write(
                f"I2C{i}_INTR_STATE_W1C", _reg("INTR_STATE", i), I2C_INTR_STATE_SMBALERT
            )
        self._drive_alert_low(False)
        self._stamp("SETUP")
        return cg

    async def _gate_round(self, k: int) -> None:
        self._drive_alert_low(True)
        see_polls = await self._poll_all(f"gate{k}_all_see_alert", 1)
        await self.csr_write(
            f"I2C{k}_SMBUS_EN_CLR", _wrap_ctrl(k), I2C_WRAP_CTRL_HOST_SMBUS & ~I2C_WRAP_SMBUS_EN
        )
        others = [i for i in INSTANCES if i != k]
        for poll in range(OBSERVE_POLLS):
            for i in others:
                got = await self._status(f"gate{k}_other{i}_p{poll}", i)
                assert got == 1, (
                    f"k={k}: SMBUS_STATUS.SMBALERT of instance {i} read {got} in poll {poll} "
                    f"with SMBUS_EN cleared on instance {k} only"
                )
        own_status = await self._status(f"gate{k}_own_status", k)
        assert own_status == 0, (
            f"k={k}: SMBUS_STATUS.SMBALERT of the cleared instance reads {own_status}; "
            f"SMBUS_EN low masks smbalert_ni (index.adoc)"
        )
        own_intr = (
            await self.csr_read(f"gate{k}_own_intr", _reg("INTR_STATE", k))
        ) & I2C_INTR_STATE_SMBALERT
        await self.csr_write(f"I2C{k}_WRAP_RESTORE", _wrap_ctrl(k), I2C_WRAP_CTRL_HOST_SMBUS)
        self._drive_alert_low(False)
        clear_polls = await self._poll_all(f"gate{k}_released_all_zero", 0)
        self.gate[k] = {
            "see": see_polls,
            "others": others,
            "own_status": own_status,
            "own_intr": 1 if own_intr else 0,
            "clear": clear_polls,
        }

    async def _gate_rounds(self) -> None:
        for k in INSTANCES:
            await self._gate_round(k)
        self._stamp("GATE_ROUNDS")
        self._chk(
            "CHK-GATE-ALL-SEE-ALERT",
            "set: three alert pads driven low; observed: "
            + "; ".join(
                f"round k={k}: SMBUS_STATUS.SMBALERT=1 on instances 0,1,2 after "
                f"{self.gate[k]['see']} polls with SMBUS_EN set on all three"
                for k in INSTANCES
            )
            + "; cleared: pads released at the end of each round; checked_cleared: all three "
            "SMBUS_STATUS.SMBALERT read 0 after "
            + ",".join(str(self.gate[k]["clear"]) for k in INSTANCES)
            + " polls (rounds k=0,1,2)",
        )
        self._chk(
            "CHK-GATE-OTHERS-UNMASKED",
            "set: SMBUS_EN cleared on instance k only; observed: "
            + "; ".join(
                f"k={k}: instances {self.gate[k]['others']} read SMBUS_STATUS.SMBALERT=1 in "
                f"{OBSERVE_POLLS} of {OBSERVE_POLLS} polls, own instance SMBUS_STATUS.SMBALERT="
                f"{self.gate[k]['own_status']} (masked, compared) "
                f"INTR_STATE.SMBALERT={self.gate[k]['own_intr']} "
                f"logged only (not specified, measured)"
                for k in INSTANCES
            )
            + "; cleared: pads released and SMBUS_EN restored; checked_cleared: all three read 0 "
            "after the release in every round",
        )

    async def _teardown(self, cg: int) -> None:
        for i in INSTANCES:
            await self.csr_write(f"I2C{i}_SMBUS_CTRL_OFF", _reg("SMBUS_CTRL", i), 0)
            await self.csr_write(f"I2C{i}_WRAP_OFF", _wrap_ctrl(i), 0)
            await self.csr_write(f"I2C{i}_CTRL_OFF", _reg("CTRL", i), 0)
        self._drive_alert_low(False)
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
        await self._gate_rounds()
        await self._teardown(cg)
        self._emit_timeout_paths()
        self._emit_nonvac()
