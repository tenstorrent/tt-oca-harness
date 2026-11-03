# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PWM channel i claims GPIO pad 59+i while PWM_CTRL.CTRL.PAD_EN[i] is set.

Sources: docs/superpowers/specs/2026-11-02-pwm-pad-wiring-design.md ("Pad map",
"Decisions"), hw/ip/pwm/regs/pwm_ctrl.rdl, hw/ip/gpio/rtl/gpio.sv (LSIO select is
vetoed by DATA_CTRL.lsio_disable), vendor/lowRISC/opentitan/overlay/regs/pwm/regs/gen/c/pwm.h.

A claimed pad is an output driven by the channel: the waveform while PWM_EN[i] is
set, and the INVERT[i] idle level while it is clear. An unclaimed pad is software
GPIO. Cool Reset Out sits on pad 64 and claims it from reset; Cool Reset In on pad
63 is software GPIO.
"""

from __future__ import annotations

from pathlib import Path

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import gpio_intf_u32, reg_field_encode, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

_REPO = Path(__file__).resolve().parents[6]
_PWM_H = _REPO / "vendor/lowRISC/opentitan/overlay/regs/pwm/regs/gen/c/pwm.h"
_PWM_CTRL_H = _REPO / "hw/ip/pwm/regs/gen/c/pwm_ctrl.h"

PWM_PAD_BASE = 59
COOL_RESET_IN_PAD = 63
COOL_RESET_OUT_PAD = 64
NUM_CH = smc_addr("SMC_TOP_SMC_PWM_PWM_PWM_PARAM_NUM")
PWM_PADS = tuple(PWM_PAD_BASE + i for i in range(NUM_CH))
ALL_CH = (1 << NUM_CH) - 1

PWM_CTRL = smc_addr("SMC_TOP_SMC_PWM_PWM_CTRL_CTRL_BASE_ADDR")
PWM_CFG = smc_addr("SMC_TOP_SMC_PWM_PWM_CFG_BASE_ADDR")
PWM_EN = smc_addr("SMC_TOP_SMC_PWM_PWM_PWM_EN_BASE_ADDR")
PWM_INVERT = smc_addr("SMC_TOP_SMC_PWM_PWM_INVERT_BASE_ADDR")

CLK_DIV = 1
DC_RESN = 3
# One beat is CLK_DIV + 1 core clocks; the phase counter wraps after 2^(DC_RESN + 1) beats.
PERIOD_CYCLES = (CLK_DIV + 1) << (DC_RESN + 1)
HALF_DUTY = 0x8000

FUSE_SENSE_MAX_CYCLES = 200_000
SETTLE_BOUND = 4 * PERIOD_CYCLES

DATA_CTRL_CORE2PAD = gpio_intf_u32("GPIO_INTF__DATA_CTRL__CORE2PAD_bm")
DATA_CTRL_TX = 1 << gpio_intf_u32("GPIO_INTF__DATA_CTRL__ENABLE_RX_TX_bp")
DATA_CTRL_IF_EN = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERFACE_ENABLE_bm")
DATA_CTRL_LSIO_DISABLE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__LSIO_DISABLE_bm")
DATA_CTRL_LSIO_ENABLE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__LSIO_ENABLE_bm")

CHK_ORDER = (
    "CHK-PWM-PAD-RESET",
    "CHK-PWM-PAD-SW",
    "CHK-PWM-PAD-CLAIM",
    "CHK-PWM-PAD-IDLE",
    "CHK-PWM-PAD-VETO",
    "CHK-PWM-PAD-RELEASE",
    "CHK-PAD-MOVED",
)


def _pad_en(mask: int) -> int:
    return reg_field_encode(_PWM_CTRL_H, "PWM_CTRL", "CTRL", pad_en=mask)


def _data_ctrl(pad: int) -> int:
    return smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR", pad)


class smc_pwm_pad_test_seq(SmcCsrSeq):
    """Claim, idle, veto and release of the PWM pads, and the moved cool-reset pads."""

    def __init__(self, name: str = "smc_pwm_pad_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: list[str] = []

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self.chk_seen.append(chk_id)

    @staticmethod
    def _bit(sig_name: str, pad: int) -> int:
        raw = getattr(cocotb.top, sig_name).value
        assert raw.is_resolvable, f"{sig_name} is X/Z: {raw}"
        return (int(raw) >> pad) & 1

    def _pad(self, pad: int) -> tuple[int, int, int]:
        """(lsio select, core2pad_en, core2pad) of ``pad``."""
        return (
            self._bit("tb_lsio_interface_select", pad),
            self._bit("tb_core2pad_en_o", pad),
            self._bit("tb_core2pad_o", pad),
        )

    async def _await(self, label: str, cond) -> int:
        for edge in range(SETTLE_BOUND):
            if cond():
                return edge
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(
            f"{label}: not reached within {SETTLE_BOUND} clk_smc_i edges; pads "
            + " ".join(f"{p}(sel,oe,d)={self._pad(p)}" for p in (*PWM_PADS, COOL_RESET_OUT_PAD))
        )

    async def _hold(self, label: str, pads: tuple[int, ...], want: tuple[int, int, int]) -> None:
        """Require ``want`` on every pad at each of PERIOD_CYCLES clk_smc_i edges."""
        for edge in range(PERIOD_CYCLES):
            for pad in pads:
                got = self._pad(pad)
                assert got == want, (
                    f"{label}: pad {pad} (sel,oe,d)={got} want {want} at edge {edge}"
                )
            await RisingEdge(cocotb.top.clk_smc_i)

    async def _levels_over_period(self, pads: tuple[int, ...]) -> dict[int, set[int]]:
        seen: dict[int, set[int]] = {pad: set() for pad in pads}
        for _ in range(PERIOD_CYCLES):
            for pad in pads:
                seen[pad].add(self._bit("tb_core2pad_o", pad))
            await RisingEdge(cocotb.top.clk_smc_i)
        return seen

    async def _set_pad_en(self, label: str, mask: int) -> None:
        await self.csr_write_readback(label, PWM_CTRL, _pad_en(mask))

    async def body(self) -> None:
        dut = cocotb.top
        for sig in ("tb_lsio_interface_select", "tb_core2pad_o", "tb_core2pad_en_o"):
            assert hasattr(dut, sig), f"{sig} is not visible on the bench top"
        await self.wait_fuse_sense_done(FUSE_SENSE_MAX_CYCLES)

        await self.csr_read("PAD_EN_RESET", PWM_CTRL, expected=_pad_en(0))
        reset = {pad: self._pad(pad) for pad in PWM_PADS}
        for pad, (sel, oe, _d) in reset.items():
            assert sel == 0 and oe == 0, f"reset: pad {pad} (sel,oe)=({sel},{oe}) want (0,0)"
        self._chk(
            "CHK-PWM-PAD-RESET",
            f"PAD_EN reads 0; pads {PWM_PADS} (sel,oe,d) {reset}",
        )

        sw_pad = PWM_PAD_BASE + 1
        sw_word = DATA_CTRL_IF_EN | DATA_CTRL_TX
        await self.csr_write("SW_DRIVE_1", _data_ctrl(sw_pad), sw_word | DATA_CTRL_CORE2PAD)
        await self._await("SW_DRIVE_1", lambda: self._pad(sw_pad) == (0, 1, 1))
        await self.csr_write("SW_DRIVE_0", _data_ctrl(sw_pad), sw_word)
        await self._await("SW_DRIVE_0", lambda: self._pad(sw_pad) == (0, 1, 0))
        await self.csr_restore("SW_DRIVE", _data_ctrl(sw_pad))
        await self._await("SW_RELEASE", lambda: self._pad(sw_pad)[:2] == (0, 0))
        self._chk(
            "CHK-PWM-PAD-SW",
            f"PAD_EN=0: GPIO_INTF[{sw_pad}] interface_enable|tx drove core2pad 1 then 0 with "
            f"core2pad_en 1 and select 0, then released",
        )

        for i in range(NUM_CH):
            await self.csr_write(
                f"DUTY_{i}",
                smc_indexed_addr("SMC_TOP_SMC_PWM_PWM_DUTY_CYCLE_BASE_ADDR", i),
                reg_field_encode(_PWM_H, "PWM", "DUTY_CYCLE", a=HALF_DUTY, b=HALF_DUTY),
            )
        await self.csr_write(
            "CFG",
            PWM_CFG,
            reg_field_encode(_PWM_H, "PWM", "CFG", clk_div=CLK_DIV, dc_resn=DC_RESN, cntr_en=1),
        )
        await self._set_pad_en("PAD_EN_ALL", ALL_CH)
        await self.csr_write("PWM_EN_ALL", PWM_EN, ALL_CH)
        await self._await("CLAIM_SELECT", lambda: all(self._pad(p)[:2] == (1, 1) for p in PWM_PADS))
        await self._await("CLAIM_RUNNING", lambda: self._bit("tb_core2pad_o", PWM_PAD_BASE) == 1)
        lsio_enable = {}
        for pad in PWM_PADS:
            word = await self.csr_read(f"CLAIM_DATA_CTRL_{pad}", _data_ctrl(pad))
            lsio_enable[pad] = int(bool(word & DATA_CTRL_LSIO_ENABLE))
            assert lsio_enable[pad] == 1, f"GPIO_INTF[{pad}] DATA_CTRL=0x{word:08x}: lsio_enable 0"
        seen = await self._levels_over_period(PWM_PADS)
        for pad in PWM_PADS:
            assert self._pad(pad)[:2] == (1, 1), f"claim: pad {pad} lost select or output enable"
            assert seen[pad] == {0, 1}, (
                f"claim: pad {pad} core2pad took {sorted(seen[pad])} over {PERIOD_CYCLES} "
                f"clk_smc_i edges, want both 0 and 1"
            )
        self._chk(
            "CHK-PWM-PAD-CLAIM",
            f"PAD_EN=PWM_EN=0x{ALL_CH:x}, CLK_DIV={CLK_DIV} DC_RESN={DC_RESN} DUTY.A=0x{HALF_DUTY:x}: "
            f"pads {PWM_PADS} select 1, core2pad_en 1, DATA_CTRL.lsio_enable {lsio_enable}, "
            f"core2pad levels over one {PERIOD_CYCLES}-cycle period "
            + " ".join(f"{p}:{sorted(s)}" for p, s in seen.items()),
        )

        await self.csr_write("PWM_EN_IDLE", PWM_EN, ALL_CH & ~1)
        await self._await("IDLE_LOW", lambda: self._pad(PWM_PAD_BASE) == (1, 1, 0))
        await self._hold("IDLE_LOW", (PWM_PAD_BASE,), (1, 1, 0))
        await self.csr_write("INVERT_0", PWM_INVERT, 1)
        await self._await("IDLE_HIGH", lambda: self._pad(PWM_PAD_BASE) == (1, 1, 1))
        await self._hold("IDLE_HIGH", (PWM_PAD_BASE,), (1, 1, 1))
        await self.csr_write_readback("INVERT_RESTORE", PWM_INVERT, 0)
        await self.csr_write_readback("PWM_EN_RESTORE", PWM_EN, ALL_CH)
        self._chk(
            "CHK-PWM-PAD-IDLE",
            f"PAD_EN[0]=1 PWM_EN[0]=0: pad {PWM_PAD_BASE} held (sel,oe,d)=(1,1,0) for "
            f"{PERIOD_CYCLES} cycles, and (1,1,1) for {PERIOD_CYCLES} cycles with INVERT[0]=1",
        )

        veto_pad = PWM_PAD_BASE + 2
        veto_word = DATA_CTRL_LSIO_DISABLE | DATA_CTRL_IF_EN | DATA_CTRL_TX
        await self.csr_write("VETO_1", _data_ctrl(veto_pad), veto_word | DATA_CTRL_CORE2PAD)
        await self._await("VETO_1", lambda: self._pad(veto_pad) == (1, 1, 1))
        await self._hold("VETO_1", (veto_pad,), (1, 1, 1))
        word = await self.csr_read("VETO_DATA_CTRL", _data_ctrl(veto_pad))
        assert not word & DATA_CTRL_LSIO_ENABLE, (
            f"veto: GPIO_INTF[{veto_pad}] DATA_CTRL=0x{word:08x} reports lsio_enable"
        )
        await self.csr_write("VETO_0", _data_ctrl(veto_pad), veto_word)
        await self._await("VETO_0", lambda: self._pad(veto_pad) == (1, 1, 0))
        await self._hold("VETO_0", (veto_pad,), (1, 1, 0))
        await self.csr_write("VETO_CLEAR", _data_ctrl(veto_pad), 0)
        word = await self.csr_read("VETO_CLEAR_RB", _data_ctrl(veto_pad))
        assert word & DATA_CTRL_LSIO_ENABLE, (
            f"veto cleared: GPIO_INTF[{veto_pad}] DATA_CTRL=0x{word:08x} lacks lsio_enable"
        )
        seen = await self._levels_over_period((veto_pad,))
        assert seen[veto_pad] == {0, 1}, (
            f"veto released: pad {veto_pad} core2pad took {sorted(seen[veto_pad])}, want the waveform"
        )
        self._chk(
            "CHK-PWM-PAD-VETO",
            f"PAD_EN[2]=1 with GPIO_INTF[{veto_pad}].lsio_disable=1: pad held core2pad 1 then 0 "
            f"from its registers for {PERIOD_CYCLES} cycles each, lsio_enable read 0; after the "
            f"veto cleared lsio_enable read 1 and the pad carried the waveform again",
        )

        await self._set_pad_en("PAD_EN_RELEASE", 0)
        await self._await("RELEASE", lambda: all(self._pad(p)[:2] == (0, 0) for p in PWM_PADS))
        self._chk(
            "CHK-PWM-PAD-RELEASE",
            f"PAD_EN=0: pads {PWM_PADS} select 0 and core2pad_en 0 with PWM_EN still 0x{ALL_CH:x}",
        )
        await self.csr_write("PWM_EN_OFF", PWM_EN, 0)
        await self.csr_write("CFG_OFF", PWM_CFG, 0)

        samples = 0
        for edge in range(PERIOD_CYCLES):
            cool_n = self._bit("tb_rst_cool_from_flr", 0)
            sel_out, oe_out, d_out = self._pad(COOL_RESET_OUT_PAD)
            sel_in = self._pad(COOL_RESET_IN_PAD)[0]
            assert (sel_out, oe_out, d_out) == (1, 1 - cool_n, 0), (
                f"pad {COOL_RESET_OUT_PAD} (sel,oe,d)=({sel_out},{oe_out},{d_out}) with "
                f"rst_cool_n={cool_n} at edge {edge}"
            )
            assert sel_in == 0, f"pad {COOL_RESET_IN_PAD} select {sel_in} at edge {edge}"
            samples += 1
            await RisingEdge(dut.clk_smc_i)
        self._chk(
            "CHK-PAD-MOVED",
            f"pad {COOL_RESET_OUT_PAD} select 1, core2pad 0, core2pad_en = ~rst_cool_n "
            f"(rst_cool_n={cool_n}) and pad {COOL_RESET_IN_PAD} select 0 over {samples} cycles",
        )

        assert tuple(self.chk_seen) == CHK_ORDER, f"checker lines {self.chk_seen} out of order"
