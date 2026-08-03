# SPDX-License-Identifier: Apache-2.0
"""smu_ic_reset_ss_domain_matrix_test - P4 IC_RESET SS cold/warm domains.

Exercises SS_COLD0 (port 5) and SS_WARM0 (port 37) one at a time with mutual
exclusion against fuse/warm/cool/cold and each other.

Does NOT close ss_reset_complete handshake (input tied dead under SEP=0).
"""

from __future__ import annotations

import cocotb
import pyuvm
from ocah_jtag_vip import OcahJtagDevice, OcahJtagTap
from cocotb.triggers import ClockCycles

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


# (port, ovrd leaf, val leaf, ss_idx or None for scalar)
_SS_DOMAINS = (
    (
        _IC_SMC_SS_COLD0,
        "ss_cold_reset_n_ovrd",
        "ss_cold_reset_n_val",
        0,
        "IC_RESET_SS_COLD_OVRD",
    ),
    (
        _IC_SMC_SS_WARM0,
        "ss_warm_reset_n_ovrd",
        "ss_warm_reset_n_val",
        0,
        "IC_RESET_SS_WARM_OVRD",
    ),
)

_SCALAR_OVRDS = (
    (_IC_SMC_FUSE, "fuse_reset_n_ovrd", None),
    (_IC_SMC_WARM, "warm_reset_n_ovrd", None),
    (_IC_SMC_COOL, "cool_reset_n_ovrd", None),
    (_IC_SMC_COLD, "cold_reset_n_ovrd", None),
)


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
class smu_ic_reset_ss_domain_matrix_test(smu_base_test):
    """IC_RESET SS cold0/warm0 with mutual exclusion."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = _make_ptap(dut, self.cfg.jtag_period_ns, regs=("IC_RESET",))
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 8)

        for _, ovrd_name, _, idx, _ in _SS_DOMAINS:
            sb.expect_eq(
                f"idle {ovrd_name}[{idx}]",
                _read_smc_reset_ctrl_bit(dut, ovrd_name, idx),
                0,
            )

        for port, ovrd_name, val_name, idx, token in _SS_DOMAINS:
            pattern = _pack_ic_reset(
                reset_hold=1,
                port_enable={port: 0},
                port_control={port: 0},
            )
            await jtag.write("IC_RESET", pattern)
            await ClockCycles(dut.clk_smu_i, 16)

            sb.expect_eq(
                f"{token} asserted",
                _read_smc_reset_ctrl_bit(dut, ovrd_name, idx),
                1,
                evidence=token,
            )
            sb.expect_eq(
                f"{val_name}[{idx}] asserted low",
                _read_smc_reset_ctrl_bit(dut, val_name, idx),
                0,
                evidence=token,
            )

            # Mutual exclusion vs scalar SMC domains.
            for _, other_ovrd, _ in _SCALAR_OVRDS:
                sb.expect_eq(
                    f"IC_RESET_SS_EXCL: {other_ovrd} idle while {token}",
                    _read_smc_reset_ctrl_bit(dut, other_ovrd),
                    0,
                    evidence="IC_RESET_SS_EXCL",
                )

            # Mutual exclusion vs the other SS domain.
            for other_port, other_ovrd, _, other_idx, other_tok in _SS_DOMAINS:
                if other_port == port:
                    continue
                sb.expect_eq(
                    f"IC_RESET_SS_EXCL: {other_tok} idle while {token}",
                    _read_smc_reset_ctrl_bit(dut, other_ovrd, other_idx),
                    0,
                    evidence="IC_RESET_SS_EXCL",
                )

            await jtag.write("IC_RESET", _IC_DEFAULT)
            await ClockCycles(dut.clk_smu_i, 16)
            sb.expect_eq(
                f"{token} released",
                _read_smc_reset_ctrl_bit(dut, ovrd_name, idx),
                0,
            )

        self.logger.info("smu_ic_reset_ss_domain_matrix_test: SS cold/warm OK")
