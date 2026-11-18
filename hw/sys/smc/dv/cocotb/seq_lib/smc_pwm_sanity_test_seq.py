# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smc_pwm_sanity_test: the SMC PWM from its registers to the waveform on GPIO pads 59-62.

Sources: vendor/lowRISC/opentitan/overlay/regs/pwm/regs/pwm.rdl and its generated
``pwm.h``, hw/ip/pwm/regs/pwm_ctrl.rdl, doc/integrator/meta/ocah_gpio_table.csv,
hw/ip/gpio/rtl/gpio.sv (LSIO select is vetoed by DATA_CTRL.lsio_disable),
hw/sys/smc/regs/gen/c/smc_addr.h, hw/sys/smc/regs/gen/py/smc_reg.py.

PWM channel i drives pad 59+i while PWM_CTRL.CTRL.PAD_EN[i] is set: the waveform while
PWM_EN[i] is set, and the INVERT[i] idle level while it is clear. An unclaimed pad is
software GPIO. The PWM counts on clk_smc_i, so every expected edge falls on a whole
number of clk_smc_i cycles.

Expected timing follows pwm.rdl: a beat is CLK_DIV+1 clocks, a period is 2^(DC_RESN+1)
beats, and DUTY_CYCLE.A and PHASE_DELAY count 2^-16 periods of which only the top
DC_RESN+1 bits are used. INVERT[i] swaps the active level.
"""

from __future__ import annotations

import random
import sys
from dataclasses import dataclass
from pathlib import Path

import cocotb
from cocotb.triggers import RisingEdge
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import (
    _PWM_H,
    _REPO,
    _component_row,
    generated_past_extent_resp,
    gpio_intf_u32,
    pwm_reset_word,
    reg_field_encode,
    smc_addr,
    smc_indexed_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

import smc_reg  # noqa: E402

_PWM_CTRL_H = _REPO / "hw/ip/pwm/regs/gen/c/pwm_ctrl.h"

AXI_RESP_SLVERR = 2
FUSE_SENSE_MAX_CYCLES = 200_000
PWM_BASE = smc_addr("SMC_TOP_SMC_PWM_PWM_BASE_ADDR")
PWM_SIZE = smc_addr("SMC_TOP_SMC_PWM_PWM_SIZE")
NUM_CH = smc_addr("SMC_TOP_SMC_PWM_PWM_PWM_PARAM_NUM")
assert (
    smc_addr("SMC_TOP_SMC_PWM_PWM_DUTY_CYCLE_NUM")
    == smc_addr("SMC_TOP_SMC_PWM_PWM_BLINK_PARAM_NUM")
    == NUM_CH
), "PWM channel arrays differ in length"
ALL_CH = (1 << NUM_CH) - 1
PAST_END_RDATA = _component_row("smc_pwm")["past_response"]["rdata"]
assert generated_past_extent_resp("smc_pwm")[0] == "DECERR"

PWM_PAD_BASE = 59
PWM_PADS = tuple(PWM_PAD_BASE + i for i in range(NUM_CH))
COOL_RESET_IN_PAD = 63
COOL_RESET_OUT_PAD = 64

PWM_CTRL = smc_addr("SMC_TOP_SMC_PWM_PWM_CTRL_CTRL_BASE_ADDR")
PWM_CFG = smc_addr("SMC_TOP_SMC_PWM_PWM_CFG_BASE_ADDR")
PWM_EN = smc_addr("SMC_TOP_SMC_PWM_PWM_PWM_EN_BASE_ADDR")
PWM_INVERT = smc_addr("SMC_TOP_SMC_PWM_PWM_INVERT_BASE_ADDR")
PWM_REGWEN = smc_addr("SMC_TOP_SMC_PWM_PWM_REGWEN_BASE_ADDR")

DATA_CTRL_CORE2PAD = gpio_intf_u32("GPIO_INTF__DATA_CTRL__CORE2PAD_bm")
DATA_CTRL_TX = 1 << gpio_intf_u32("GPIO_INTF__DATA_CTRL__ENABLE_RX_TX_bp")
DATA_CTRL_IF_EN = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERFACE_ENABLE_bm")
DATA_CTRL_LSIO_DISABLE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__LSIO_DISABLE_bm")
DATA_CTRL_LSIO_ENABLE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__LSIO_ENABLE_bm")

STROBE_ONE_LANE = 0b0001
PATTERN_SEED = 0x5A5A_A5A5
PATTERN_STEP = 0x1111_1111

#: Random configurations per seed.
NUM_CONFIGS = 8
#: DC_RESN and CLK_DIV draw ranges; the longest period is 2^6 beats of 8 clocks.
DC_RESN_RANGE = (0, 5)
CLK_DIV_RANGE = (0, 7)
MAX_PERIOD = (CLK_DIV_RANGE[1] + 1) << (DC_RESN_RANGE[1] + 1)
#: Periods recorded per waveform check, after one period is let pass.
WAVE_PERIODS = 4
#: Clocks the cool-reset pads are sampled for.
COOL_RESET_SAMPLES = 32
WAIT_BOUND = 4 * MAX_PERIOD

CHK_ORDER = (
    "CHK-PWM-RESET",
    "CHK-PWM-PAD-RESET",
    "CHK-PWM-RW",
    "CHK-PWM-STROBE",
    "CHK-PWM-PAST-END",
    "CHK-PWM-PAD-SW",
    "CHK-PWM-PAD-CLAIM",
    "CHK-PWM-PAD-WAVE",
    "CHK-PWM-PAD-IDLE",
    "CHK-PWM-PAD-VETO",
    "CHK-PWM-REGWEN",
    "CHK-PWM-PAD-RELEASE",
    "CHK-PAD-MOVED",
)


def _rw_mask(reg: str) -> int:
    """Software-writable bits of PWM register ``reg`` from its generated field layout."""
    mask = 0
    for _name, lsb, msb, sw, *_rest in getattr(smc_reg, f"PWM_{reg}_REG_FIELDS"):
        if sw == "rw":
            mask |= ((1 << (msb - lsb + 1)) - 1) << lsb
    return mask


def _reg(label: str, reg: str, addr: int) -> tuple[str, str, int, int]:
    return label, reg, addr, pwm_reset_word(reg)


def _chan_addr(reg: str, idx: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_PWM_PWM_{reg}_BASE_ADDR", idx)


def _channel_regs() -> list[tuple[str, str, int, int]]:
    return [
        _reg(f"{reg}_{idx}", reg, _chan_addr(reg, idx))
        for reg in ("PWM_PARAM", "DUTY_CYCLE", "BLINK_PARAM")
        for idx in range(NUM_CH)
    ]


ALERT_TEST = _reg("ALERT_TEST", "ALERT_TEST", smc_addr("SMC_TOP_SMC_PWM_PWM_ALERT_TEST_BASE_ADDR"))
REGWEN = _reg("REGWEN", "REGWEN", PWM_REGWEN)
LOCKED_REGS = [
    _reg("CFG", "CFG", PWM_CFG),
    _reg("PWM_EN", "PWM_EN", PWM_EN),
    _reg("INVERT", "INVERT", PWM_INVERT),
    *_channel_regs(),
]
ALL_REGS = [ALERT_TEST, REGWEN, *LOCKED_REGS]
assert len(ALL_REGS) * 4 == PWM_SIZE, "register list does not tile the decoded extent"

RW_ENTRIES = [
    (label, addr, (PATTERN_SEED ^ (k * PATTERN_STEP)) & 0xFFFF_FFFF & _rw_mask(reg), reset)
    for k, (label, reg, addr, reset) in enumerate(LOCKED_REGS)
]
assert all(pattern != reset for _, _, pattern, reset in RW_ENTRIES), "a pattern equals its reset"
# The same patterns with every writable bit flipped, so each bit is written both 1 and 0.
RW_ENTRIES_FLIPPED = [
    (label, addr, pattern ^ _rw_mask(reg), reset)
    for (label, addr, pattern, reset), (_, reg, _, _) in zip(RW_ENTRIES, LOCKED_REGS)
]

_BY_LABEL = {label: (addr, pattern, reset) for label, addr, pattern, reset in RW_ENTRIES}
PARAM0_LABEL = "PWM_PARAM_0"
PARAM0_ADDR, PARAM0_PATTERN, PARAM0_RESET = _BY_LABEL[PARAM0_LABEL]


def _pad_en(mask: int) -> int:
    return reg_field_encode(_PWM_CTRL_H, "PWM_CTRL", "CTRL", pad_en=mask)


def _data_ctrl(pad: int) -> int:
    return smc_indexed_addr("SMC_TOP_GPIO_INTF_WRAP_GPIO_INTF_DATA_CTRL_BASE_ADDR", pad)


def _cfg_word(clk_div: int, dc_resn: int, cntr_en: int) -> int:
    return reg_field_encode(_PWM_H, "PWM", "CFG", clk_div=clk_div, dc_resn=dc_resn, cntr_en=cntr_en)


def _duty_word(duty: int) -> int:
    return reg_field_encode(_PWM_H, "PWM", "DUTY_CYCLE", a=duty, b=duty)


@dataclass(frozen=True)
class PwmConfig:
    """One PWM setting and the pad timing pwm.rdl gives for it."""

    clk_div: int
    dc_resn: int
    duty: tuple[int, ...]
    phase: tuple[int, ...]
    invert: int

    @property
    def beats(self) -> int:
        return 1 << (self.dc_resn + 1)

    @property
    def beat_clks(self) -> int:
        return self.clk_div + 1

    @property
    def period(self) -> int:
        return self.beats * self.beat_clks

    def _slices(self, value: int) -> int:
        return value >> (15 - self.dc_resn)

    def active_clks(self, ch: int) -> int:
        return self._slices(self.duty[ch]) * self.beat_clks

    def lead_offset(self, ch: int) -> int:
        """Clocks from channel 0's leading edge to channel ``ch``'s, modulo the period."""
        beats = (self._slices(self.phase[ch]) - self._slices(self.phase[0])) % self.beats
        return beats * self.beat_clks

    def active_level(self, ch: int) -> int:
        return 1 ^ ((self.invert >> ch) & 1)

    def describe(self) -> str:
        return (
            f"CLK_DIV={self.clk_div} DC_RESN={self.dc_resn} period={self.period} "
            f"INVERT=0x{self.invert:x} "
            + " ".join(
                f"ch{ch}(A=0x{self.duty[ch]:04x} PHASE=0x{self.phase[ch]:04x} "
                f"active={self.active_clks(ch)} lead=+{self.lead_offset(ch)})"
                for ch in range(NUM_CH)
            )
        )


def draw_config(rng: random.Random) -> PwmConfig:
    """Draw a setting whose every channel has a duty strictly between 0 and a full period.

    The bits below the DC_RESN+1 used ones are drawn too, so the rounding down is graded.
    """
    dc_resn = rng.randint(*DC_RESN_RANGE)
    beats = 1 << (dc_resn + 1)
    unused = 15 - dc_resn

    def value(lo: int, hi: int) -> int:
        return (rng.randint(lo, hi) << unused) | rng.getrandbits(unused)

    return PwmConfig(
        clk_div=rng.randint(*CLK_DIV_RANGE),
        dc_resn=dc_resn,
        duty=tuple(value(1, beats - 1) for _ in range(NUM_CH)),
        phase=tuple(value(0, beats - 1) for _ in range(NUM_CH)),
        invert=rng.getrandbits(NUM_CH),
    )


def leading_edges(trace: list[int], pad: int, active: int) -> list[int]:
    """Indices in ``trace`` at which ``pad`` enters its ``active`` level."""
    return [
        t
        for t in range(1, len(trace))
        if (trace[t] >> pad) & 1 == active and (trace[t - 1] >> pad) & 1 != active
    ]


def check_wave(cfg: PwmConfig, trace: list[int], label: str) -> str:
    """Grade period, active time and leading-edge offset of every PWM pad in ``trace``."""
    leads = {}
    for ch, pad in enumerate(PWM_PADS):
        active = cfg.active_level(ch)
        edges = leading_edges(trace, pad, active)
        assert len(edges) >= 3, (
            f"{label}: pad {pad} entered level {active} {len(edges)} times in {len(trace)} "
            f"clocks, want at least 3; {cfg.describe()}"
        )
        gaps = [b - a for a, b in zip(edges, edges[1:])]
        assert all(gap == cfg.period for gap in gaps), (
            f"{label}: pad {pad} leading edges {gaps} clocks apart, want {cfg.period}; "
            f"{cfg.describe()}"
        )
        for start in edges[:-1]:
            run = 0
            while (trace[start + run] >> pad) & 1 == active:
                run += 1
            assert run == cfg.active_clks(ch), (
                f"{label}: pad {pad} active for {run} clocks from clock {start}, want "
                f"{cfg.active_clks(ch)}; {cfg.describe()}"
            )
        leads[ch] = edges[0]
    for ch in range(1, NUM_CH):
        offset = (leads[ch] - leads[0]) % cfg.period
        assert offset == cfg.lead_offset(ch), (
            f"{label}: pad {PWM_PADS[ch]} leads {offset} clocks after pad {PWM_PADS[0]}, want "
            f"{cfg.lead_offset(ch)}; {cfg.describe()}"
        )
    return cfg.describe()


class smc_pwm_sanity_test_seq(SmcCsrSeq):
    """Program the PWM, claim pads 59-62 and grade the waveforms against the settings."""

    def __init__(self, name: str = "smc_pwm_sanity_test_seq", *, seed: int = 1) -> None:
        super().__init__(name)
        self.seed = seed
        self.chk_seen: list[str] = []

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self.chk_seen.append(chk_id)

    @staticmethod
    def _word(sig_name: str) -> int:
        raw = getattr(cocotb.top, sig_name).value
        assert raw.is_resolvable, f"{sig_name} is X/Z: {raw}"
        return int(raw)

    def _bit(self, sig_name: str, pad: int) -> int:
        return (self._word(sig_name) >> pad) & 1

    def _pad(self, pad: int) -> tuple[int, int, int]:
        """(lsio select, core2pad_en, core2pad) of ``pad``."""
        return (
            self._bit("tb_lsio_interface_select", pad),
            self._bit("tb_core2pad_en_o", pad),
            self._bit("tb_core2pad_o", pad),
        )

    async def _await(self, label: str, cond) -> int:
        for edge in range(WAIT_BOUND):
            if cond():
                return edge
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(
            f"{label}: not reached within {WAIT_BOUND} clk_smc_i edges; pads "
            + " ".join(f"{p}(sel,oe,d)={self._pad(p)}" for p in (*PWM_PADS, COOL_RESET_OUT_PAD))
        )

    async def _hold(self, label: str, pad: int, want: tuple[int, int, int], cycles: int) -> None:
        """Require ``want`` on ``pad`` at each of ``cycles`` clk_smc_i edges."""
        for edge in range(cycles):
            got = self._pad(pad)
            assert got == want, f"{label}: pad {pad} (sel,oe,d)={got} want {want} at edge {edge}"
            await RisingEdge(cocotb.top.clk_smc_i)

    async def _record(self, cfg: PwmConfig) -> list[int]:
        """core2pad over WAVE_PERIODS periods, after one period is let pass."""
        for _ in range(cfg.period):
            await RisingEdge(cocotb.top.clk_smc_i)
        trace = []
        for _ in range(WAVE_PERIODS * cfg.period):
            trace.append(self._word("tb_core2pad_o"))
            await RisingEdge(cocotb.top.clk_smc_i)
        return trace

    async def _program(self, cfg: PwmConfig) -> None:
        """Stop the channels and the counter, load ``cfg`` and start them again."""
        await self.csr_write("PWM_EN_STOP", PWM_EN, 0)
        await self.csr_write("CFG_STOP", PWM_CFG, _cfg_word(cfg.clk_div, cfg.dc_resn, 0))
        for ch in range(NUM_CH):
            await self.csr_write_readback(
                f"PWM_PARAM_{ch}",
                _chan_addr("PWM_PARAM", ch),
                reg_field_encode(_PWM_H, "PWM", "PWM_PARAM", phase_delay=cfg.phase[ch]),
            )
            await self.csr_write_readback(
                f"DUTY_CYCLE_{ch}", _chan_addr("DUTY_CYCLE", ch), _duty_word(cfg.duty[ch])
            )
        await self.csr_write_readback("INVERT", PWM_INVERT, cfg.invert)
        await self.csr_write_readback("CFG", PWM_CFG, _cfg_word(cfg.clk_div, cfg.dc_resn, 1))
        await self.csr_write_readback("PWM_EN", PWM_EN, ALL_CH)

    async def _write_one_lane(self, name: str, addr: int, data: int) -> int:
        item = SmcSysAxiItem(f"wr_{name}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = 4
        item.wdata = data
        item.wstrb = STROBE_ONE_LANE
        item.allow_error = True
        item.expect_error = True
        item.expected_resp = AXI_RESP_SLVERR
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code == AXI_RESP_SLVERR, (
            f"{name} @ 0x{addr:08x} wstrb=0b{STROBE_ONE_LANE:04b}: resp={item.resp_code}, "
            f"want SLVERR"
        )
        return item.resp_code

    async def body(self) -> None:
        dut = cocotb.top
        for sig in ("tb_lsio_interface_select", "tb_core2pad_o", "tb_core2pad_en_o"):
            assert hasattr(dut, sig), f"{sig} is not visible on the bench top"
        await self.wait_fuse_sense_done(FUSE_SENSE_MAX_CYCLES)

        await self._check_reset()
        await self._check_registers()
        await self._check_software_gpio()
        cfg = await self._check_waveforms()
        await self._check_idle(cfg)
        await self._check_veto(cfg)
        await self._check_lock(cfg)
        await self._check_release()
        await self._check_cool_reset_pads()

        assert tuple(self.chk_seen) == CHK_ORDER, f"checker lines {self.chk_seen} out of order"

    async def _check_reset(self) -> None:
        for label, _, addr, reset in ALL_REGS:
            await self.csr_read(f"{label}_RESET", addr, expected=reset)
        self._chk(
            "CHK-PWM-RESET",
            f"{len(ALL_REGS)} registers at 0x{PWM_BASE:08x}..0x{PWM_BASE + PWM_SIZE - 4:08x} "
            f"read their generated reset words ({NUM_CH} channels)",
        )

        await self.csr_read("PAD_EN_RESET", PWM_CTRL, expected=_pad_en(0))
        reset = {pad: self._pad(pad) for pad in PWM_PADS}
        for pad, (sel, oe, _d) in reset.items():
            assert sel == 0 and oe == 0, f"reset: pad {pad} (sel,oe)=({sel},{oe}) want (0,0)"
        self._chk("CHK-PWM-PAD-RESET", f"PAD_EN reads 0; pads {PWM_PADS} (sel,oe,d) {reset}")

    async def _check_registers(self) -> None:
        await self.rw_coresident(RW_ENTRIES)
        await self.rw_coresident(RW_ENTRIES_FLIPPED)
        self._chk(
            "CHK-PWM-RW",
            f"{len(RW_ENTRIES)} registers (CFG, PWM_EN, INVERT and {NUM_CH} each of "
            "PWM_PARAM, DUTY_CYCLE, BLINK_PARAM) held distinct writable-bit patterns and then "
            "the same patterns with every writable bit flipped, each set written before any "
            "was read back, then restored to reset",
        )

        await self.csr_write_readback(PARAM0_LABEL, PARAM0_ADDR, PARAM0_PATTERN)
        lane_data = ~PARAM0_PATTERN & 0xFFFF_FFFF
        resp = await self._write_one_lane(f"{PARAM0_LABEL}_ONE_LANE", PARAM0_ADDR, lane_data)
        await self.csr_read(f"{PARAM0_LABEL}_AFTER_ONE_LANE", PARAM0_ADDR, expected=PARAM0_PATTERN)
        await self.csr_restore(PARAM0_LABEL, PARAM0_ADDR, PARAM0_RESET)
        self._chk(
            "CHK-PWM-STROBE",
            f"{PARAM0_LABEL} write of 0x{lane_data:08x} with wstrb=0b{STROBE_ONE_LANE:04b} "
            f"answered resp={resp} (SLVERR) and the register still read 0x{PARAM0_PATTERN:08x}",
        )

        past_end = PWM_BASE + PWM_SIZE
        # The word lies inside the PWM wrapper's window, so the SEP_IN monitor
        # does not treat its DECERR as dead space.
        self.env.axi_monitor.expected_decerr_addrs.add(past_end)
        rdata = await self.csr_read_expect_error("PAST_END", past_end) & 0xFFFF_FFFF
        assert rdata == PAST_END_RDATA, (
            f"PAST_END @ 0x{past_end:08x}: rdata 0x{rdata:08x}, want 0x{PAST_END_RDATA:08x}"
        )
        self._chk(
            "CHK-PWM-PAST-END",
            f"read at 0x{past_end:08x}, the first word past the decoded extent, answered an "
            f"error with 0x{rdata:08x}",
        )

    async def _check_software_gpio(self) -> None:
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

    async def _check_waveforms(self) -> PwmConfig:
        rng = random.Random(self.seed)
        configs = [draw_config(rng) for _ in range(NUM_CONFIGS)]
        cocotb.log.info("PWM seed %d draws %d configurations", self.seed, NUM_CONFIGS)

        await self._program(configs[0])
        await self.csr_write_readback("PAD_EN_ALL", PWM_CTRL, _pad_en(ALL_CH))
        await self._await("CLAIM", lambda: all(self._pad(p)[:2] == (1, 1) for p in PWM_PADS))
        lsio_enable = {}
        for pad in PWM_PADS:
            word = await self.csr_read(f"CLAIM_DATA_CTRL_{pad}", _data_ctrl(pad))
            lsio_enable[pad] = int(bool(word & DATA_CTRL_LSIO_ENABLE))
            assert lsio_enable[pad] == 1, f"GPIO_INTF[{pad}] DATA_CTRL=0x{word:08x}: lsio_enable 0"
        self._chk(
            "CHK-PWM-PAD-CLAIM",
            f"PAD_EN=PWM_EN=0x{ALL_CH:x}: pads {PWM_PADS} select 1, core2pad_en 1, "
            f"DATA_CTRL.lsio_enable {lsio_enable}",
        )

        graded = []
        for k, cfg in enumerate(configs):
            if k:
                await self._program(cfg)
            trace = await self._record(cfg)
            for pad in PWM_PADS:
                assert self._pad(pad)[:2] == (1, 1), f"config {k}: pad {pad} lost its claim"
            graded.append(f"[{k}] " + check_wave(cfg, trace, f"config {k}"))
        self._chk(
            "CHK-PWM-PAD-WAVE",
            f"seed {self.seed}: pads {PWM_PADS} matched period, active time and leading-edge "
            f"offset over {WAVE_PERIODS} periods for each of {NUM_CONFIGS} configurations: "
            + "; ".join(graded),
        )
        return configs[-1]

    async def _check_idle(self, cfg: PwmConfig) -> None:
        pad = PWM_PAD_BASE
        await self.csr_write("INVERT_0_CLEAR", PWM_INVERT, cfg.invert & ~1)
        await self.csr_write("PWM_EN_IDLE", PWM_EN, ALL_CH & ~1)
        await self._await("IDLE_LOW", lambda: self._pad(pad) == (1, 1, 0))
        await self._hold("IDLE_LOW", pad, (1, 1, 0), cfg.period)
        await self.csr_write("INVERT_0_SET", PWM_INVERT, cfg.invert | 1)
        await self._await("IDLE_HIGH", lambda: self._pad(pad) == (1, 1, 1))
        await self._hold("IDLE_HIGH", pad, (1, 1, 1), cfg.period)
        await self.csr_write_readback("INVERT_RESTORE", PWM_INVERT, cfg.invert)
        await self.csr_write_readback("PWM_EN_RESTORE", PWM_EN, ALL_CH)
        check_wave(cfg, await self._record(cfg), "idle restored")
        self._chk(
            "CHK-PWM-PAD-IDLE",
            f"PAD_EN[0]=1 PWM_EN[0]=0: pad {pad} held (sel,oe,d)=(1,1,0) for "
            f"a {cfg.period}-cycle period with INVERT[0]=0 and (1,1,1) with INVERT[0]=1; "
            "with PWM_EN[0] set again every pad matched the configuration",
        )

    async def _check_veto(self, cfg: PwmConfig) -> None:
        veto_pad = PWM_PAD_BASE + 2
        veto_word = DATA_CTRL_LSIO_DISABLE | DATA_CTRL_IF_EN | DATA_CTRL_TX
        await self.csr_write("VETO_1", _data_ctrl(veto_pad), veto_word | DATA_CTRL_CORE2PAD)
        await self._await("VETO_1", lambda: self._pad(veto_pad) == (1, 1, 1))
        await self._hold("VETO_1", veto_pad, (1, 1, 1), cfg.period)
        word = await self.csr_read("VETO_DATA_CTRL", _data_ctrl(veto_pad))
        assert not word & DATA_CTRL_LSIO_ENABLE, (
            f"veto: GPIO_INTF[{veto_pad}] DATA_CTRL=0x{word:08x} reports lsio_enable"
        )
        await self.csr_write("VETO_0", _data_ctrl(veto_pad), veto_word)
        await self._await("VETO_0", lambda: self._pad(veto_pad) == (1, 1, 0))
        await self._hold("VETO_0", veto_pad, (1, 1, 0), cfg.period)
        await self.csr_write("VETO_CLEAR", _data_ctrl(veto_pad), 0)
        word = await self.csr_read("VETO_CLEAR_RB", _data_ctrl(veto_pad))
        assert word & DATA_CTRL_LSIO_ENABLE, (
            f"veto cleared: GPIO_INTF[{veto_pad}] DATA_CTRL=0x{word:08x} lacks lsio_enable"
        )
        check_wave(cfg, await self._record(cfg), "veto cleared")
        self._chk(
            "CHK-PWM-PAD-VETO",
            f"PAD_EN[2]=1 with GPIO_INTF[{veto_pad}].lsio_disable=1: pad held core2pad 1 then 0 "
            f"from its registers for a {cfg.period}-cycle period each, lsio_enable read 0; "
            "after the veto cleared lsio_enable read 1 and every pad matched the configuration",
        )

    async def _check_lock(self, cfg: PwmConfig) -> None:
        running = [
            ("CFG", PWM_CFG, _cfg_word(cfg.clk_div, cfg.dc_resn, 1), _rw_mask("CFG")),
            ("PWM_EN", PWM_EN, ALL_CH, _rw_mask("PWM_EN")),
            ("INVERT", PWM_INVERT, cfg.invert, _rw_mask("INVERT")),
            (
                f"DUTY_CYCLE_{NUM_CH - 1}",
                _chan_addr("DUTY_CYCLE", NUM_CH - 1),
                _duty_word(cfg.duty[NUM_CH - 1]),
                _rw_mask("DUTY_CYCLE"),
            ),
        ]
        await self.csr_write("REGWEN_CLEAR", PWM_REGWEN, 0)
        await self.csr_read("REGWEN_CLEARED", PWM_REGWEN, expected=0)
        for label, addr, value, mask in running:
            await self.csr_write(f"{label}_LOCKED", addr, ~value & mask)
        for label, addr, value, _mask in running:
            await self.csr_read(f"{label}_LOCKED_RB", addr, expected=value)
        await self.csr_read("REGWEN_STILL_CLEARED", PWM_REGWEN, expected=0)
        check_wave(cfg, await self._record(cfg), "locked")
        self._chk(
            "CHK-PWM-REGWEN",
            "REGWEN cleared to 0; locked writes of the inverted running values to "
            + ", ".join(label for label, *_ in running)
            + " each left the running value, REGWEN still read 0, and every pad still matched "
            "the configuration",
        )

    async def _check_release(self) -> None:
        await self.csr_write_readback("PAD_EN_RELEASE", PWM_CTRL, _pad_en(0))
        await self._await("RELEASE", lambda: all(self._pad(p)[:2] == (0, 0) for p in PWM_PADS))
        self._chk(
            "CHK-PWM-PAD-RELEASE",
            f"PAD_EN=0: pads {PWM_PADS} select 0 and core2pad_en 0 with PWM_EN still 0x{ALL_CH:x}",
        )

    async def _check_cool_reset_pads(self) -> None:
        samples = 0
        cool_n = 0
        for edge in range(COOL_RESET_SAMPLES):
            cool_n = self._bit("tb_rst_cool_from_flr", 0)
            sel_out, oe_out, d_out = self._pad(COOL_RESET_OUT_PAD)
            sel_in = self._pad(COOL_RESET_IN_PAD)[0]
            assert (sel_out, oe_out, d_out) == (1, 1 - cool_n, 0), (
                f"pad {COOL_RESET_OUT_PAD} (sel,oe,d)=({sel_out},{oe_out},{d_out}) with "
                f"rst_cool_n={cool_n} at edge {edge}"
            )
            assert sel_in == 0, f"pad {COOL_RESET_IN_PAD} select {sel_in} at edge {edge}"
            samples += 1
            await RisingEdge(cocotb.top.clk_smc_i)
        self._chk(
            "CHK-PAD-MOVED",
            f"pad {COOL_RESET_OUT_PAD} select 1, core2pad 0, core2pad_en = ~rst_cool_n "
            f"(rst_cool_n={cool_n}) and pad {COOL_RESET_IN_PAD} select 0 over {samples} cycles",
        )
