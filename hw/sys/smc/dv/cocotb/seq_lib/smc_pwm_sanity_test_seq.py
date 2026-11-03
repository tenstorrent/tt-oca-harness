# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smc_pwm_sanity_test: PWM register reset, read/write, strobe, REGWEN lock and decoded extent.

Sources: vendor/lowRISC/opentitan/overlay/regs/pwm/regs/pwm.rdl and its generated
``pwm.h``, hw/sys/smc/regs/gen/c/smc_addr.h, hw/sys/smc/regs/gen/py/smc_reg.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import (
    _component_row,
    generated_past_extent_resp,
    pwm_reset_word,
    smc_addr,
    smc_indexed_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

import smc_reg  # noqa: E402

AXI_RESP_SLVERR = 2
FUSE_SENSE_MAX_CYCLES = 200_000
PWM_BASE = smc_addr("SMC_TOP_SMC_PWM_PWM_BASE_ADDR")
PWM_SIZE = smc_addr("SMC_TOP_SMC_PWM_PWM_SIZE")
NUM_CHANNELS = smc_addr("SMC_TOP_SMC_PWM_PWM_PWM_PARAM_NUM")
assert (
    smc_addr("SMC_TOP_SMC_PWM_PWM_DUTY_CYCLE_NUM")
    == smc_addr("SMC_TOP_SMC_PWM_PWM_BLINK_PARAM_NUM")
    == NUM_CHANNELS
), "PWM channel arrays differ in length"
PAST_END_RDATA = _component_row("smc_pwm")["past_response"]["rdata"]
assert generated_past_extent_resp("smc_pwm")[0] == "DECERR"

STROBE_ONE_LANE = 0b0001
PATTERN_SEED = 0x5A5A_A5A5
PATTERN_STEP = 0x1111_1111


def _rw_mask(reg: str) -> int:
    """Software-writable bits of PWM register ``reg`` from its generated field layout."""
    mask = 0
    for _name, lsb, msb, sw, *_rest in getattr(smc_reg, f"PWM_{reg}_REG_FIELDS"):
        if sw == "rw":
            mask |= ((1 << (msb - lsb + 1)) - 1) << lsb
    return mask


def _reg(label: str, reg: str, addr: int) -> tuple[str, str, int, int]:
    return label, reg, addr, pwm_reset_word(reg)


def _channel_regs() -> list[tuple[str, str, int, int]]:
    regs = []
    for reg in ("PWM_PARAM", "DUTY_CYCLE", "BLINK_PARAM"):
        for idx in range(NUM_CHANNELS):
            addr = smc_indexed_addr(f"SMC_TOP_SMC_PWM_PWM_{reg}_BASE_ADDR", idx)
            regs.append(_reg(f"{reg}_{idx}", reg, addr))
    return regs


ALERT_TEST = _reg("ALERT_TEST", "ALERT_TEST", smc_addr("SMC_TOP_SMC_PWM_PWM_ALERT_TEST_BASE_ADDR"))
REGWEN = _reg("REGWEN", "REGWEN", smc_addr("SMC_TOP_SMC_PWM_PWM_REGWEN_BASE_ADDR"))
LOCKED_REGS = [
    _reg("CFG", "CFG", smc_addr("SMC_TOP_SMC_PWM_PWM_CFG_BASE_ADDR")),
    _reg("PWM_EN", "PWM_EN", smc_addr("SMC_TOP_SMC_PWM_PWM_PWM_EN_BASE_ADDR")),
    _reg("INVERT", "INVERT", smc_addr("SMC_TOP_SMC_PWM_PWM_INVERT_BASE_ADDR")),
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
LOCK_PROBES = [
    (label, addr, ~reset & _rw_mask(reg), reset)
    for label, reg, addr, reset in LOCKED_REGS
    if label in ("CFG", "PWM_EN", "INVERT", f"DUTY_CYCLE_{NUM_CHANNELS - 1}")
]
assert len(LOCK_PROBES) == 4 and all(data != reset for _, _, data, reset in LOCK_PROBES)

_BY_LABEL = {label: (addr, pattern, reset) for label, addr, pattern, reset in RW_ENTRIES}
PARAM0_LABEL = "PWM_PARAM_0"
PARAM0_ADDR, PARAM0_PATTERN, PARAM0_RESET = _BY_LABEL[PARAM0_LABEL]


class smc_pwm_sanity_test_seq(SmcCsrSeq):
    """Reset, read/write, partial-strobe, REGWEN-lock and past-end checks of the SMC PWM."""

    def __init__(self, name: str = "smc_pwm_sanity_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: set[str] = set()

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self.chk_seen.add(chk_id)

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
        await self.wait_fuse_sense_done(FUSE_SENSE_MAX_CYCLES)

        for label, _, addr, reset in ALL_REGS:
            await self.csr_read(f"{label}_RESET", addr, expected=reset)
        self._chk(
            "CHK-PWM-RESET",
            f"{len(ALL_REGS)} registers at 0x{PWM_BASE:08x}..0x{PWM_BASE + PWM_SIZE - 4:08x} "
            f"read their generated reset words ({NUM_CHANNELS} channels)",
        )

        await self.rw_coresident(RW_ENTRIES)
        await self.rw_coresident(RW_ENTRIES_FLIPPED)
        self._chk(
            "CHK-PWM-RW",
            f"{len(RW_ENTRIES)} registers (CFG, PWM_EN, INVERT and {NUM_CHANNELS} each of "
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

        regwen_label, _, regwen_addr, _ = REGWEN
        await self.csr_write(f"{regwen_label}_CLEAR", regwen_addr, 0)
        await self.csr_read(f"{regwen_label}_CLEARED", regwen_addr, expected=0)
        for label, addr, data, _reset in LOCK_PROBES:
            await self.csr_write(f"{label}_LOCKED", addr, data)
        for label, addr, _data, reset in LOCK_PROBES:
            await self.csr_read(f"{label}_LOCKED_RB", addr, expected=reset)
        await self.csr_read(f"{regwen_label}_STILL_CLEARED", regwen_addr, expected=0)
        self._chk(
            "CHK-PWM-REGWEN",
            "REGWEN cleared to 0; locked writes "
            + ", ".join(f"{label}<-0x{data:08x}" for label, _, data, _ in LOCK_PROBES)
            + " each left the reset word, and REGWEN still read 0",
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
