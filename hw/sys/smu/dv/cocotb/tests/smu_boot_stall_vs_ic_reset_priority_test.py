# SPDX-License-Identifier: Apache-2.0
"""smu_boot_stall_vs_ic_reset_priority_test - P3-H5b stall vs IC_RESET priority.

Boot-stall (DEBUG_CONTROL) and IC_RESET are independent TDRs. After stall is
made sticky across cold (fuse gated), this corner checks:

  1. IC_RESET warm then cold while stall sticky: ovrd asserts; stall survives
  2. IC_RESET DEFAULT: domain ovrd clears; stall still sticky; fuse still gated
  3. TRST clears stall AND IC_RESET; fuse_reset releases

Must FAIL if IC_RESET clears stall, stall survives TRST, or wrong IC_RESET
domain asserts while stall is active.
"""

from __future__ import annotations

import cocotb
import pyuvm
from ocah_jtag_vip import OcahJtagDevice, OcahJtagTap
from cocotb.triggers import ClockCycles

from seq_lib.smu_axi_helpers import wait_signal_high
from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()

# SMU SEP=0 IC_RESET geometry from smu.sv / jtag_ptap (real RTL).
_IC_NUM_PORTS = 69
_IC_LEN = 2 * _IC_NUM_PORTS + 1
_IC_DEFAULT = (1 << _IC_LEN) - 1
_IC_EXT = 0
_IC_SMC_FUSE = 1
_IC_SMC_WARM = 2
_IC_SMC_COOL = 3
_IC_SMC_COLD = 4
_IC_SMC_SS_COLD0 = 5
_IC_SMC_SS_WARM0 = 37



def _make_ptap(dut, period_ns: float, *, regs: tuple[str, ...] = ("DEBUG_CONTROL",)) -> OcahJtagTap:
    """Build OcahJtagTap against real TB JTAG pins (no Force / no fake DUT)."""
    device = OcahJtagDevice(
        name="smu_ptap",
        idcode=0x0000_0001,
        ir_width=6,
        idle_delay=2,
        add_bypass=True,
    )
    device.add_reg("IDCODE", 32, 0x01)
    if "DEBUG_CONTROL" in regs:
        device.add_reg("DEBUG_CONTROL", 5, 0x18, write=True)
    if "IC_RESET" in regs:
        # SMU SEP=0: 69 ports * 2 + hold = 139
        device.add_reg("IC_RESET", 139, 0x0D, write=True)
    if "EXTEST" in regs:
        device.add_reg("EXTEST", 8, 0x04, write=True)
    jtag = OcahJtagTap(
        dut,
        name="smu_ptap",
        tck_period_ns=period_ns,
        ir_width=6,
        tap_type="ptap",
        signal_map={
            "tck": "jtag_tck",
            "tms": "jtag_tms",
            "tdi": "jtag_tdi",
            "tdo": "jtag_tdo",
            "trst": "jtag_trst",
            "tdo_oen": "jtag_tdo_oen",
        },
    )
    jtag.add_device(device)
    jtag.init_signals()
    return jtag

def _pack_debug_control(
    *,
    boot_stall: int = 0,
    boot_stall_ovrd: int = 0,
    cla_clock_stop_en: int = 0,
    jtag_clock_stop: int = 0,
) -> int:
    # DTP DEBUG_CONTROL TDR bit layout (real DTP TDR).
    return (
        ((boot_stall & 0x1) << 0)
        | ((boot_stall_ovrd & 0x1) << 1)
        | ((cla_clock_stop_en & 0x1) << 2)
        | ((jtag_clock_stop & 0x1) << 3)
    )


def _pack_ic_reset(
    *,
    reset_hold: int = 1,
    port_enable: dict[int, int] | None = None,
    port_control: dict[int, int] | None = None,
) -> int:
    value = _IC_DEFAULT & ~0x1
    value |= reset_hold & 0x1
    for idx, en in (port_enable or {}).items():
        bit = 1 + 2 * int(idx)
        value = (value & ~(1 << bit)) | ((en & 0x1) << bit)
    for idx, ctrl in (port_control or {}).items():
        bit = 2 + 2 * int(idx)
        value = (value & ~(1 << bit)) | ((ctrl & 0x1) << bit)
    return value & _IC_DEFAULT

def _smu(dut):
    """Real SMU instance: bare u_dut, or wrapper u_dut.u_smu."""
    u_dut = dut.u_dut
    return u_dut.u_smu if hasattr(u_dut, "u_smu") else u_dut


def _read_smc_reset_ctrl_bit(dut, leaf: str, idx: int | None = None) -> int:
    """Observe real jtag_smc_reset_ctrl fields (no Force)."""
    ctrl = _smu(dut).jtag_smc_reset_ctrl
    group_name = "ovrd" if leaf.endswith("_ovrd") else "val"
    # Prefer hierarchical struct fields exposed by Verilator public_flat.
    if hasattr(ctrl, "ovrd") and hasattr(ctrl, "val"):
        group = getattr(ctrl, group_name)
        if idx is None:
            return int(getattr(group, leaf).value) & 1
        vec = getattr(group, leaf)
        try:
            return int(vec[idx].value) & 1
        except Exception:  # noqa: BLE001
            return (int(vec.value) >> idx) & 1
    # Packed fallback: ovrd[135:68] | val[67:0]
    packed = int(ctrl.value)
    scalar = {
        "fuse_reset_n_ovrd": 68,
        "warm_reset_n_ovrd": 69,
        "cool_reset_n_ovrd": 70,
        "cold_reset_n_ovrd": 71,
        "fuse_reset_n_val": 0,
        "warm_reset_n_val": 1,
        "cool_reset_n_val": 2,
        "cold_reset_n_val": 3,
    }
    if idx is None:
        return (packed >> scalar[leaf]) & 1
    if leaf == "ss_cold_reset_n_ovrd":
        bit = 72 + idx
    elif leaf == "ss_warm_reset_n_ovrd":
        bit = 104 + idx
    elif leaf == "ss_cold_reset_n_val":
        bit = 4 + idx
    elif leaf == "ss_warm_reset_n_val":
        bit = 36 + idx
    else:
        raise AssertionError(f"Unknown ss leaf {leaf}")
    return (packed >> bit) & 1

@pyuvm.test()
class smu_boot_stall_vs_ic_reset_priority_test(smu_base_test):
    """Stall sticky isolation vs IC_RESET; TRST clears both."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = _make_ptap(dut, self.cfg.jtag_period_ns, regs=("DEBUG_CONTROL", "IC_RESET"))
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 8)

        sb.expect_eq(
            "fuse_reset after bring-up",
            int(dut.fuse_reset_n_delayed_o.value),
            1,
        evidence="STALL_VS_IC_RESET")

        # --- Make stall sticky across cold (same window as P2-I3a) ---
        await jtag.write(
            "DEBUG_CONTROL",
            _pack_debug_control(boot_stall_ovrd=1, boot_stall=1),
        )
        await ClockCycles(dut.clk_smu_i, 8)
        sb.expect_eq("stall ovrd before cold", int(dut.jtag_boot_stall_ovrd.value), 1)
        sb.expect_eq("stall val before cold", int(dut.jtag_boot_stall.value), 1)

        self.logger.info("Cold reset with TRST held high (stall sticky + fuse gate)")
        dut.rst_cold_ni.value = 0
        await ClockCycles(dut.clk_ref_i, 64)
        dut.rst_cold_ni.value = 1
        await ClockCycles(dut.clk_ref_i, self.cfg.post_reset_settle_cycles)
        await wait_signal_high(
            dut.rst_primary_smc_clk_no,
            dut.clk_smu_i,
            timeout_cycles=2000,
            name="rst_primary after cold+stall",
        )
        await ClockCycles(dut.clk_smu_i, 64)

        sb.expect_eq(
            "stall ovrd sticky after cold",
            int(dut.jtag_boot_stall_ovrd.value),
            1,
        )
        sb.expect_eq(
            "stall val sticky after cold",
            int(dut.jtag_boot_stall.value),
            1,
        )
        sb.expect_eq(
            "fuse_reset gated while stall sticky",
            int(dut.fuse_reset_n_delayed_o.value),
            0,
        )

        # --- IC_RESET warm while stall sticky ---
        warm_pat = _pack_ic_reset(
            reset_hold=1,
            port_enable={_IC_SMC_WARM: 0},
            port_control={_IC_SMC_WARM: 0},
        )
        await jtag.write("IC_RESET", warm_pat)
        await ClockCycles(dut.clk_smu_i, 16)
        sb.expect_eq(
            "warm ovrd while stall",
            _read_smc_reset_ctrl_bit(dut, "warm_reset_n_ovrd"),
            1,
        )
        sb.expect_eq(
            "cold idle while warm+stall",
            _read_smc_reset_ctrl_bit(dut, "cold_reset_n_ovrd"),
            0,
        )
        sb.expect_eq(
            "stall survives IC_RESET warm",
            int(dut.jtag_boot_stall_ovrd.value),
            1,
        )
        sb.expect_eq(
            "fuse still gated during warm ovrd",
            int(dut.fuse_reset_n_delayed_o.value),
            0,
        )

        # --- Switch to cold ovrd while stall sticky ---
        cold_pat = _pack_ic_reset(
            reset_hold=1,
            port_enable={_IC_SMC_COLD: 0},
            port_control={_IC_SMC_COLD: 0},
        )
        await jtag.write("IC_RESET", cold_pat)
        await ClockCycles(dut.clk_smu_i, 16)
        sb.expect_eq(
            "cold ovrd while stall",
            _read_smc_reset_ctrl_bit(dut, "cold_reset_n_ovrd"),
            1,
        )
        sb.expect_eq(
            "warm cleared when cold packed alone",
            _read_smc_reset_ctrl_bit(dut, "warm_reset_n_ovrd"),
            0,
        )
        sb.expect_eq(
            "stall survives IC_RESET cold",
            int(dut.jtag_boot_stall_ovrd.value),
            1,
        )
        sb.expect_eq(
            "fuse still gated during cold ovrd",
            int(dut.fuse_reset_n_delayed_o.value),
            0,
        )

        # --- Release IC_RESET; stall + fuse gate remain ---
        await jtag.write("IC_RESET", _IC_DEFAULT)
        await ClockCycles(dut.clk_smu_i, 16)
        sb.expect_eq(
            "cold cleared by DEFAULT",
            _read_smc_reset_ctrl_bit(dut, "cold_reset_n_ovrd"),
            0,
        )
        sb.expect_eq(
            "stall sticky after IC_RESET DEFAULT",
            int(dut.jtag_boot_stall_ovrd.value),
            1,
        )
        sb.expect_eq(
            "fuse still gated after IC_RESET DEFAULT",
            int(dut.fuse_reset_n_delayed_o.value),
            0,
        )

        # --- TRST clears stall and IC_RESET ---
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 16)
        sb.expect_eq(
            "stall ovrd cleared by TRST",
            int(dut.jtag_boot_stall_ovrd.value),
            0,
        )
        sb.expect_eq(
            "stall val cleared by TRST",
            int(dut.jtag_boot_stall.value),
            0,
        )
        sb.expect_eq(
            "warm idle after TRST",
            _read_smc_reset_ctrl_bit(dut, "warm_reset_n_ovrd"),
            0,
        )
        sb.expect_eq(
            "cold idle after TRST",
            _read_smc_reset_ctrl_bit(dut, "cold_reset_n_ovrd"),
            0,
        )
        await wait_signal_high(
            dut.fuse_reset_n_delayed_o,
            dut.clk_smu_i,
            timeout_cycles=2000,
            name="fuse_reset after TRST",
        )
        sb.expect_eq(
            "fuse_reset high after TRST",
            int(dut.fuse_reset_n_delayed_o.value),
            1,
        )

        self.logger.info(
            "smu_boot_stall_vs_ic_reset_priority_test: stall|IC_RESET isolation+TRST OK"
        )
