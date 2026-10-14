# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OCTS register map, reset values and access rules over SEP_IN.

Specs hw/ip/system_timer_octs/regs/system_timer_octs.rdl, hw/ip/system_timer_octs/doc/memmap.adoc.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

_BASE = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_BASE_ADDR")
_START = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_START_BASE_ADDR")
_CTRL = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_CTRL_BASE_ADDR")
_STATUS = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_STATUS_BASE_ADDR")
_PRESET_LO = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_LO_BASE_ADDR")
_PRESET_HI = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_HI_BASE_ADDR")
_COUNT_LO = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_COUNT_LO_BASE_ADDR")
_COUNT_HI = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_COUNT_HI_BASE_ADDR")
_CREDIT_EXPIRED = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_CREDIT_EXPIRED_BASE_ADDR")
_GPIO_EN = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_GPIO_ENABLE_BASE_ADDR")

_STATUS_MODE = 0x1
_STATUS_RUNNING = 0x10
_RESET_CTRL = 0x0001_020A
_COUNT_SAMPLES = 64
_RUN_WAIT_CYCLES = 100
_COUNT_SLACK = 0x1000
_RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}

_CHK_STEP = (
    ("CHK-OCTS-RESET-VALUES", "S1"),
    ("CHK-OCTS-CTRL-PRESET-READBACK", "S3"),
    ("CHK-OCTS-GPIO-ENABLE-RW", "S4"),
    ("CHK-OCTS-DECODE-OFFSETS", "S5"),
    ("CHK-OCTS-READONLY-START", "S5"),
    ("CHK-OCTS-APERTURE-PAST", "S6"),
)


class smc_octs_csr_access_test_seq(SmcCsrSeq):
    """Walk the nine OCTS registers: reset, read-back, decode, read-only and past-the-end."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int]] = []
        self._printed: list[tuple[str, int]] = []

    def _stamp(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, text: str, *args) -> None:
        self._printed.append((chk_id, len(self._stamps)))
        cocotb.log.info("%s: " + text, chk_id, *args)

    async def _access(self, op: SmcSysAxiOp, name: str, addr: int, data: int = 0):
        item = SmcSysAxiItem(f"{'rd' if op is SmcSysAxiOp.READ else 'wr'}_{name}")
        item.op = op
        item.addr = addr
        item.length = 4
        item.wdata = data
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None, f"{name} @ 0x{addr:08x}: no response code"
        return item

    async def _write_resp(self, name: str, addr: int, data: int) -> int:
        item = await self._access(SmcSysAxiOp.WRITE, name, addr, data)
        return item.resp_code

    async def _read_resp(self, name: str, addr: int) -> tuple[int, int]:
        item = await self._access(SmcSysAxiOp.READ, name, addr)
        return item.rdata, item.resp_code

    async def _rd(self, name: str, addr: int, expected: int) -> int:
        got = await self.csr_read(name, addr)
        assert got == expected, f"{name} @ 0x{addr:08x} read 0x{got:08x}, expected 0x{expected:08x}"
        return got

    async def _sample_count_net(self) -> int:
        dut = cocotb.top
        assert hasattr(dut, "timer_count"), "tb_top has no timer_count net"
        clk = dut.clk_smc_i
        zero = 0
        for i in range(_COUNT_SAMPLES):
            await RisingEdge(clk)
            value = dut.timer_count.value
            assert value.is_resolvable, f"timer_count has X/Z at rise {i}: {value}"
            if int(value) == 0:
                zero += 1
        assert zero == _COUNT_SAMPLES, f"timer_count zero at {zero} of {_COUNT_SAMPLES} rises"
        return zero

    async def body(self) -> None:
        # S1
        ctrl0 = await self._rd("CTRL_RESET", _CTRL, _RESET_CTRL)
        zero_regs = (
            ("TIMER_START", _START),
            ("STATUS", _STATUS),
            ("PRESET_LO", _PRESET_LO),
            ("PRESET_HI", _PRESET_HI),
            ("COUNT_LO", _COUNT_LO),
            ("COUNT_HI", _COUNT_HI),
            ("CREDIT_EXPIRED", _CREDIT_EXPIRED),
            ("TIMER_GPIO_ENABLE", _GPIO_EN),
        )
        for reg, addr in zero_regs:
            await self._rd(f"{reg}_RESET", addr, 0)
        zero_rises = await self._sample_count_net()
        self._stamp("S1")
        self._chk(
            "CHK-OCTS-RESET-VALUES",
            "CTRL 0x%08x; TIMER_START STATUS PRESET_LO PRESET_HI COUNT_LO COUNT_HI "
            "CREDIT_EXPIRED TIMER_GPIO_ENABLE all 0x0 (STATUS.MODE 0, RUNNING 0); "
            "timer_count_o 0 at %d of %d rises; zero reset values are bench-limited (2-state "
            "zero init)",
            ctrl0,
            zero_rises,
            _COUNT_SAMPLES,
        )

        # S2
        await self.csr_write("CTRL_PATTERN", _CTRL, 0xFFA5_5AC3)
        ctrl_pat = await self._rd("CTRL_PATTERN_RB", _CTRL, 0x00A5_5AC3)
        await self.csr_write("PRESET_LO_PATTERN", _PRESET_LO, 0xDEAD_BEEF)
        lo1 = await self._rd("PRESET_LO_RB1", _PRESET_LO, 0xDEAD_BEEF)
        hi1 = await self._rd("PRESET_HI_RB1", _PRESET_HI, 0)
        await self.csr_write("PRESET_HI_PATTERN", _PRESET_HI, 0x1234_5678)
        lo2 = await self._rd("PRESET_LO_RB2", _PRESET_LO, 0xDEAD_BEEF)
        hi2 = await self._rd("PRESET_HI_RB2", _PRESET_HI, 0x1234_5678)
        patterns = {ctrl_pat, lo2, hi2}
        own = {"CTRL": _CTRL, "PRESET_LO": _PRESET_LO, "PRESET_HI": _PRESET_HI}
        elsewhere = []
        for reg, addr in (
            ("TIMER_START", _START),
            ("STATUS", _STATUS),
            ("COUNT_LO", _COUNT_LO),
            ("COUNT_HI", _COUNT_HI),
            ("CREDIT_EXPIRED", _CREDIT_EXPIRED),
            ("TIMER_GPIO_ENABLE", _GPIO_EN),
        ):
            got = await self.csr_read(f"{reg}_ALIAS", addr)
            elsewhere.append(got)
            assert got not in patterns, (
                f"pattern 0x{got:08x} also readable at {reg} 0x{addr:08x} "
                f"(own offsets {sorted(hex(a - _BASE) for a in own.values())})"
            )
        self._stamp("S2")

        # S3
        await self.csr_write("CTRL_PW0", _CTRL, 0x0001_0010)
        ctrl_pw0 = await self._rd("CTRL_PW0_RB", _CTRL, 0x0001_0010)
        self._stamp("S3")
        self._chk(
            "CHK-OCTS-CTRL-PRESET-READBACK",
            "CTRL 0xFFA55AC3 read back 0x%08x; CTRL with PULSE_WIDTH 0 read back 0x%08x; PRESET_LO "
            "0x%08x with PRESET_HI 0x%08x, then PRESET_HI 0x%08x with PRESET_LO 0x%08x",
            ctrl_pat,
            ctrl_pw0,
            lo1,
            hi1,
            hi2,
            lo2,
        )

        # S4
        await self.csr_write("GPIO_EN_1", _GPIO_EN, 1)
        en1 = await self._rd("GPIO_EN_1_RB", _GPIO_EN, 1)
        await self.csr_write("GPIO_EN_0", _GPIO_EN, 0)
        en0 = await self._rd("GPIO_EN_0_RB", _GPIO_EN, 0)
        self._stamp("S4")
        self._chk(
            "CHK-OCTS-GPIO-ENABLE-RW",
            "TIMER_GPIO_ENABLE read %d after a write of 1 and %d after a write of 0",
            en1,
            en0,
        )

        # S5
        await self.csr_write("CTRL_RESTORE", _CTRL, _RESET_CTRL)
        await self.csr_write("PRESET_LO_RESTORE", _PRESET_LO, 0)
        await self.csr_write("PRESET_HI_RESTORE", _PRESET_HI, 0)
        await self.csr_write("START", _START, 1)
        start_rb = await self._rd("START_RB", _START, 0)
        await ClockCycles(cocotb.top.clk_smc_i, _RUN_WAIT_CYCLES)
        count_prev = await self.csr_read("COUNT_LO_PREV", _COUNT_LO)
        resp_status = await self._write_resp("STATUS_FFFF", _STATUS, 0xFFFF_FFFF)
        resp_lo = await self._write_resp("COUNT_LO_FFFF", _COUNT_LO, 0xFFFF_FFFF)
        resp_hi = await self._write_resp("COUNT_HI_FFFF", _COUNT_HI, 0xFFFF_FFFF)
        status = await self.csr_read("STATUS_RUN", _STATUS)
        count_hi = await self.csr_read("COUNT_HI_RUN", _COUNT_HI)
        count_lo = await self.csr_read("COUNT_LO_RUN", _COUNT_LO)
        self._stamp("S5")
        assert status == _STATUS_RUNNING, (
            f"STATUS 0x{status:08x} after TIMER_START, expected MODE 0 and RUNNING 1 only"
        )
        assert count_hi == 0, f"COUNT_HI 0x{count_hi:08x} after a write of 0xFFFFFFFF"
        assert count_prev <= count_lo <= count_prev + _COUNT_SLACK, (
            f"COUNT_LO 0x{count_lo:08x} not in [0x{count_prev:08x}, "
            f"0x{count_prev + _COUNT_SLACK:08x}]"
        )
        assert count_lo != 0xFFFF_FFFF, "COUNT_LO took the written 0xFFFFFFFF"
        assert count_lo > 0, "COUNT_LO did not advance after TIMER_START"
        self._chk(
            "CHK-OCTS-DECODE-OFFSETS",
            "offsets 0x00 0x04 0x08 0x0C 0x10 0x14 0x18 0x1C 0x20 each answered; patterns "
            "0x%08x 0x%08x 0x%08x readable only at 0x04 0x0C 0x10 (other offsets read %s); "
            "STATUS 0x%08x RUNNING 1 after TIMER_START; COUNT_LO 0x%08x advanced past 0x%08x; "
            "COUNT_HI 0x%x",
            ctrl_pat,
            lo2,
            hi2,
            ",".join(f"0x{v:x}" for v in elsewhere),
            status,
            count_lo,
            count_prev,
            count_hi,
        )
        self._chk(
            "CHK-OCTS-READONLY-START",
            "TIMER_START read %d after a write of 1; writes of 0xFFFFFFFF to STATUS COUNT_LO "
            "COUNT_HI returned resp %s %s %s (not specified, measured); STATUS 0x%08x MODE 0 "
            "RUNNING "
            "1; COUNT_HI "
            "0x%x; COUNT_LO 0x%08x no lower than previous 0x%08x and within 0x%x of it",
            start_rb,
            _RESP_NAME.get(resp_status, resp_status),
            _RESP_NAME.get(resp_lo, resp_lo),
            _RESP_NAME.get(resp_hi, resp_hi),
            status,
            count_hi,
            count_lo,
            count_prev,
            _COUNT_SLACK,
        )

        # S6
        past1, r1 = await self._read_resp("PAST_24", _BASE + 0x24)
        past2, r2 = await self._read_resp("PAST_28", _BASE + 0x28)
        w1 = await self._write_resp("PAST_24_WR", _BASE + 0x24, 0xA5A5_5A5A)
        self._stamp("S6")
        self._chk(
            "CHK-OCTS-APERTURE-PAST",
            "read 0x24 resp %s data 0x%08x; read 0x28 resp %s data 0x%08x; write 0x24 resp %s "
            "(not specified, measured)",
            _RESP_NAME.get(r1, r1),
            past1,
            _RESP_NAME.get(r2, r2),
            past2,
            _RESP_NAME.get(w1, w1),
        )

        self._fence()

    def _fence(self) -> None:
        order = [s for s, _ in self._stamps]
        assert order == ["S1", "S2", "S3", "S4", "S5", "S6"], f"step order {order}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:], strict=False)), f"stamps {times}"
        assert [c for c, _ in self._printed] == [c for c, _ in _CHK_STEP], (
            f"checker line order {[c for c, _ in self._printed]}"
        )
        for (chk, step), (_, stamped) in zip(_CHK_STEP, self._printed, strict=True):
            idx = order.index(step) + 1
            assert stamped >= idx, f"{chk} printed before the stamp of {step}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            ">".join(order),
            ",".join(c for c, _ in self._printed),
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
