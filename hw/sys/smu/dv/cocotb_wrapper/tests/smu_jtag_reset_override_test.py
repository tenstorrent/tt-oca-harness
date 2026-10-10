# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_jtag_reset_override_test - IC_RESET TDR override of EXT/SMC slices.

SMU IC_RESET TDR is 155 bits on the SEP=1 wrapper (68 SMC + 8 SEP + 1 EXT ports
+ hold), not the 7-bit standalone DTP smoke geometry. The EXT port sits
nearest TDO, so it is the one port whose position does not survive a wrong
SEP slice width in the helper geometry: a DR shifted short of the TDR lands
the EXT fields in the SEP slice and the ext ovrd leg below fails.

The EXT override is applied and released in the order the DTP JTAG chapter
(hw/sys/dtp/doc/jtag.adoc) gives a hazard-free consumer: reset_control is
written in one Update-DR and reset_enable moved in a second, so the select
and the data input of the consumer's multiplexer never change together. The
override leaves the DTP with `.ovrd` active high and `.val` carrying
reset_control, so each staging update shows on the EXT slice alone.

Real checkers:
  - Default IC_RESET readback is all-ones over the whole DR
  - EXT control=0 staged with enable=1 drives ctrl_n=0 while ovrd stays 0
  - EXT enable=0/control=0 asserts ext ovrd=1 and ctrl_n=0
  - EXT control=1 staged with enable=0 drives ctrl_n=1 while ovrd stays 1
  - SMC cold_reset port override updates hierarchical SMC slice
  - Clearing TDR restores ovrd=0
  - Every managed-subsystem cold and warm port and every SEP port, including
    the Key Manager, in the same two-update order: control staged, override
    applied, control released under the override, then cleared. The leaf loads
    the Key Manager smoke ROM first; an empty ROM returns X and the look-ahead
    read takes the ROM request to X once km_jtag_rst_n is released. After each
    update the SMC and SEP slices are read whole: each is a packed struct whose
    .ovrd half sits above its .val half, the first field of each half nearest TDI, and the
    halves carry the inverse of reset_enable and reset_control
    (doc/integrator/src/smu.adoc, "IC_RESET TDR Structure"), so every
    port's override and value are compared bit by bit.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from seq_lib.smu_compose_helpers import hier
from seq_lib.smu_jtag_helpers import (
    SMU_IC_RESET_DEFAULT,
    SMU_IC_RESET_EXT_PORT,
    SMU_IC_RESET_LEN,
    SMU_IC_RESET_NUM_SEP_PORTS,
    SMU_IC_RESET_NUM_SMC_PORTS,
    SMU_IC_RESET_SMC_COLD_PORT,
    SMU_IC_RESET_SMC_FUSE_PORT,
    SMU_IC_RESET_SMC_SS_COLD0_PORT,
    SMU_IC_RESET_SMC_SS_WARM0_PORT,
    make_smu_jtag_tap,
    pack_ic_reset_ports,
    require_jtag_tdo_resolved,
)
from seq_lib.smu_tb_pins import smu_scope
from smu_base_test import smu_base_test

SS_PORTS = 32


def _sample(signal, name: str) -> int:
    val = signal.value
    if not val.is_resolvable:
        raise AssertionError(f"X/Z sample on {name}: {val}")
    return int(val)


def _override_slices(dut) -> tuple[int, int, int, int]:
    """(smc ovrd half, smc val half, sep ovrd half, sep val half) of the IC_RESET slices."""
    smu = smu_scope(dut)
    smc_slice = hier(smu, "jtag_smc_reset_ctrl")
    sep_slice = hier(smu, "jtag_sep_reset_ctrl")
    n_smc, n_sep = SMU_IC_RESET_NUM_SMC_PORTS, SMU_IC_RESET_NUM_SEP_PORTS
    widths = (len(smc_slice), len(sep_slice))
    if widths != (2 * n_smc, 2 * n_sep):
        raise AssertionError(f"IC_RESET slice widths {widths} do not match the TDR geometry")
    smc = _sample(smc_slice, "jtag_smc_reset_ctrl")
    sep = _sample(sep_slice, "jtag_sep_reset_ctrl")
    return (smc >> n_smc, smc & ((1 << n_smc) - 1), sep >> n_sep, sep & ((1 << n_sep) - 1))


async def _read_ic_reset(jtag, dut, shift_value: int, where: str, log) -> int:
    """Read IC_RESET, failing on any X/Z TDO bit while the PTAP drives TDO.

    The JTAG VIP reads an X/Z TDO bit as 0, so the bench's `jtag_tdo` and
    `jtag_tdo_oen` (high during Shift-IR and Shift-DR) are sampled on every TCK
    rising edge of the scan, and at least one DR length of driven bits must be
    seen.
    """
    driven = [0]
    bad: list[str] = []

    async def watch() -> None:
        while True:
            await RisingEdge(dut.jtag_tck)
            oen = dut.jtag_tdo_oen.value
            tdo = dut.jtag_tdo.value
            if not oen.is_resolvable:
                bad.append(f"jtag_tdo_oen={oen}")
            elif int(oen):
                driven[0] += 1
                if not tdo.is_resolvable:
                    bad.append(f"jtag_tdo={tdo} at driven bit {driven[0] - 1}")

    watcher = cocotb.start_soon(watch())
    try:
        readback = await jtag.read("IC_RESET", shift_value=shift_value)
    finally:
        watcher.cancel()
    require_jtag_tdo_resolved(where)
    log.info("%s: %d driven TDO bits sampled, %d X/Z", where, driven[0], len(bad))
    if bad:
        raise AssertionError(f"X/Z on TDO during {where}: {bad[:8]}")
    if driven[0] < SMU_IC_RESET_LEN:
        raise AssertionError(
            f"{where}: {driven[0]} driven TDO bits sampled, fewer than the "
            f"{SMU_IC_RESET_LEN}-bit IC_RESET DR"
        )
    return int(readback)


@pyuvm.test()
class smu_jtag_reset_override_test(smu_base_test):
    """IC_RESET override/release on EXT and SMC cold-reset slices."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 8)

        default = await _read_ic_reset(
            jtag, dut, SMU_IC_RESET_DEFAULT, "IC_RESET default readback", self.logger
        )
        sb.expect_eq(
            "IC_RESET default",
            default,
            SMU_IC_RESET_DEFAULT,
            evidence="IC_RESET_DEFAULT",
        )
        sb.expect_eq(
            "ext ovrd idle",
            _sample(dut.jtag_ic_reset_ext_ovrd, "jtag_ic_reset_ext_ovrd"),
            0,
        )
        sb.expect_eq(
            "smc ovrd idle",
            _sample(dut.jtag_ic_reset_smc_ovrd, "jtag_ic_reset_smc_ovrd"),
            0,
        )

        ext_staged = pack_ic_reset_ports(
            reset_hold=1,
            port_enable={SMU_IC_RESET_EXT_PORT: 1},
            port_control={SMU_IC_RESET_EXT_PORT: 0},
        )
        await jtag.write("IC_RESET", ext_staged)
        await ClockCycles(dut.clk_smu_i, 16)
        sb.expect_eq(
            "ext control staged low with the override still off (ovrd, ctrl_n)",
            (
                _sample(dut.jtag_ic_reset_ext_ovrd, "jtag_ic_reset_ext_ovrd"),
                _sample(dut.jtag_ic_reset_ext_ctrl_n, "jtag_ic_reset_ext_ctrl_n"),
            ),
            (0, 0),
            evidence="IC_RESET_EXT_STAGED",
        )

        ext_assert = pack_ic_reset_ports(
            reset_hold=1,
            port_enable={SMU_IC_RESET_EXT_PORT: 0},
            port_control={SMU_IC_RESET_EXT_PORT: 0},
        )
        await jtag.write("IC_RESET", ext_assert)
        await ClockCycles(dut.clk_smu_i, 16)
        sb.expect_eq(
            "ext ovrd asserted",
            _sample(dut.jtag_ic_reset_ext_ovrd, "jtag_ic_reset_ext_ovrd"),
            1,
        )
        sb.expect_eq(
            "ext ctrl_n asserted low",
            _sample(dut.jtag_ic_reset_ext_ctrl_n, "jtag_ic_reset_ext_ctrl_n"),
            0,
        )
        smc_ovrd, _, sep_ovrd, _ = _override_slices(dut)
        sb.expect_eq(
            "only the ext override is set while ext is asserted (ext ovrd, whole smc ovrd half, "
            "whole sep ovrd half)",
            (_sample(dut.jtag_ic_reset_ext_ovrd, "jtag_ic_reset_ext_ovrd"), smc_ovrd, sep_ovrd),
            (1, 0, 0),
            evidence="IC_RESET_DOMAIN_EXCL",
        )
        rb = await _read_ic_reset(
            jtag, dut, ext_assert, "IC_RESET EXT pattern readback", self.logger
        )
        sb.expect_eq(
            "IC_RESET EXT pattern readback",
            rb,
            ext_assert,
        )

        ext_release_staged = pack_ic_reset_ports(
            reset_hold=1,
            port_enable={SMU_IC_RESET_EXT_PORT: 0},
            port_control={SMU_IC_RESET_EXT_PORT: 1},
        )
        await jtag.write("IC_RESET", ext_release_staged)
        await ClockCycles(dut.clk_smu_i, 16)
        sb.expect_eq(
            "ext control staged high with the override still on (ovrd, ctrl_n)",
            (
                _sample(dut.jtag_ic_reset_ext_ovrd, "jtag_ic_reset_ext_ovrd"),
                _sample(dut.jtag_ic_reset_ext_ctrl_n, "jtag_ic_reset_ext_ctrl_n"),
            ),
            (1, 1),
            evidence="IC_RESET_EXT_RELEASE_STAGED",
        )

        smc_assert = pack_ic_reset_ports(
            reset_hold=1,
            port_enable={SMU_IC_RESET_SMC_COLD_PORT: 0},
            port_control={SMU_IC_RESET_SMC_COLD_PORT: 0},
        )
        await jtag.write("IC_RESET", smc_assert)
        await ClockCycles(dut.clk_smu_i, 16)
        sb.expect_eq(
            "smc ovrd asserted",
            _sample(dut.jtag_ic_reset_smc_ovrd, "jtag_ic_reset_smc_ovrd"),
            1,
        )
        sb.expect_eq(
            "smc ctrl_n asserted low",
            _sample(dut.jtag_ic_reset_smc_ctrl_n, "jtag_ic_reset_smc_ctrl_n"),
            0,
        )
        smc_ovrd, _, sep_ovrd, _ = _override_slices(dut)
        sb.expect_eq(
            "only the smc cold override is set while smc cold is asserted (ext ovrd, whole smc "
            "ovrd half, whole sep ovrd half)",
            (_sample(dut.jtag_ic_reset_ext_ovrd, "jtag_ic_reset_ext_ovrd"), smc_ovrd, sep_ovrd),
            (0, 1 << (SMU_IC_RESET_SMC_COLD_PORT - SMU_IC_RESET_SMC_FUSE_PORT), 0),
            evidence="IC_RESET_DOMAIN_EXCL",
        )

        await jtag.write("IC_RESET", SMU_IC_RESET_DEFAULT)
        await ClockCycles(dut.clk_smu_i, 16)
        sb.expect_eq(
            "ext ovrd cleared",
            _sample(dut.jtag_ic_reset_ext_ovrd, "jtag_ic_reset_ext_ovrd"),
            0,
        )
        sb.expect_eq(
            "smc ovrd cleared",
            _sample(dut.jtag_ic_reset_smc_ovrd, "jtag_ic_reset_smc_ovrd"),
            0,
        )

        await self._walk_ss_and_sep_ports(dut, sb, jtag)

        self.logger.info("smu_jtag_reset_override_test: IC_RESET EXT/SMC override checked")

    async def _walk_ss_and_sep_ports(self, dut, sb, jtag) -> None:
        """Stage, apply, release and clear every SS and SEP port together.

        km_jtag_rst_n is included. The testlist loads the Key Manager smoke
        ROM, so the request stays 0 or 1 when that override releases the CPU.
        """
        ss_ports = [SMU_IC_RESET_SMC_SS_COLD0_PORT + i for i in range(SS_PORTS)] + [
            SMU_IC_RESET_SMC_SS_WARM0_PORT + i for i in range(SS_PORTS)
        ]
        sep_ports = [SMU_IC_RESET_EXT_PORT + 1 + i for i in range(SMU_IC_RESET_NUM_SEP_PORTS)]
        ports = ss_ports + sep_ports
        smc_all = (1 << SMU_IC_RESET_NUM_SMC_PORTS) - 1
        sep_all = (1 << SMU_IC_RESET_NUM_SEP_PORTS) - 1
        ss_mask = 0
        for port in ss_ports:
            ss_mask |= 1 << (port - SMU_IC_RESET_SMC_FUSE_PORT)
        # Port EXT_PORT + 1 + i is the SEP field i places from TDO, which is
        # bit i of each half.
        observed = []
        for enable, control in ((1, 0), (0, 0), (0, 1)):
            port_enable = dict.fromkeys(ports, enable)
            word = pack_ic_reset_ports(
                reset_hold=1,
                port_enable=port_enable,
                port_control=dict.fromkeys(ports, control),
            )
            await jtag.write("IC_RESET", word)
            await ClockCycles(dut.clk_smu_i, 16)
            readback = await _read_ic_reset(
                jtag, dut, word, "IC_RESET SS/SEP walk readback", self.logger
            )
            observed.append(
                (
                    readback == word,
                    _sample(dut.ic_reset_smc_ovrd_o, "ic_reset_smc_ovrd_o"),
                    *_override_slices(dut),
                )
            )
        await jtag.write("IC_RESET", SMU_IC_RESET_DEFAULT)
        await ClockCycles(dut.clk_smu_i, 16)
        readback = await _read_ic_reset(
            jtag, dut, SMU_IC_RESET_DEFAULT, "IC_RESET SS/SEP walk clear readback", self.logger
        )
        observed.append(
            (
                readback == SMU_IC_RESET_DEFAULT,
                _sample(dut.ic_reset_smc_ovrd_o, "ic_reset_smc_ovrd_o"),
                *_override_slices(dut),
            )
        )
        # (readback, smc ovrd pin, smc ovrd, smc val, sep ovrd, sep val)
        want = [
            (True, 0, 0, smc_all & ~ss_mask, 0, 0),
            (True, ss_mask, ss_mask, smc_all & ~ss_mask, sep_all, 0),
            (True, ss_mask, ss_mask, smc_all, sep_all, sep_all),
            (True, 0, 0, smc_all, 0, sep_all),
        ]
        self.logger.info(
            "IC_RESET SS/SEP walk (readback ok, smc ovrd pin, smc ovrd, smc val, sep ovrd, "
            "sep val): " + " ".join(str(tuple(hex(v) for v in row)) for row in observed)
        )
        sb.expect_eq(
            "SS and SEP ports staged, applied, released and cleared",
            observed,
            want,
            evidence="IC_RESET_SS_SEP_WALK",
        )
