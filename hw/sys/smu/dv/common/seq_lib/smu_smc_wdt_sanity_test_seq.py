# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CORE0 WDT unlock then CMP program via JTAG2AXI. SEP=1, no Force."""

from __future__ import annotations

import cocotb
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import smc_addr, wdt_bm, wdt_u32
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    WDT_KEY_UNLOCKED_RD,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
    wdt_key_read,
    wdt_unlock,
)

WDT_CTRL = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_CTRL_BASE_ADDR")
WDT_CMP = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_CMP_BASE_ADDR")
CMP_DEFAULT = wdt_u32("WDT__CMP__WDOGCMP0_reset")
CMP_PROGRAM = 0x2345
CMP_MASK = wdt_u32("WDT__CMP__WDOGCMP0_bm")
SCALE_MASK = wdt_bm("WDT__CTRL__WDOGSCALE_bm")
SCALE_PROGRAM = 0x1


class smu_smc_wdt_sanity_test_seq:
    """CORE0 WDT magic unlock and CMP program evidence."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.s1_ok = False
        self.s2_ok = False
        self.s3_ok = False
        self.s4_ok = False

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _sample_int(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on OSS tb_top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val)

    async def _rd32(self, jtag, addr: int) -> tuple[int, int]:
        st, rdata = await jtag2axi_single_read(
            jtag,
            addr,
            size=SMC_DBG_AXSIZE_4B,
            require_complete=True,
        )
        require_jtag_tdo_resolved(f"WDT RD @0x{addr:08x}")
        return st, int(rdata) & 0xFFFF_FFFF

    async def _wr32(self, jtag, addr: int, data: int) -> int:
        st, _ = await jtag2axi_single_write(
            jtag,
            addr,
            data,
            wstrb=0x0F,
            size=SMC_DBG_AXSIZE_4B,
            require_complete=True,
        )
        require_jtag_tdo_resolved(f"WDT WR @0x{addr:08x}")
        return st

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        dut = self.dut
        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)

        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        gate = self._sample_int("tb_smc_jtag2axi_security_disable") & 1
        if gate != 0:
            raise AssertionError(f"SMC J2A still gated after TCK sync: security_disable={gate}")
        self.s1_ok = True
        sb.expect_eq("CHK-WDT-SANITY-GATE-OPEN", gate, 0)

        st_c, cmp0 = await self._rd32(jtag, WDT_CMP)
        if st_c != J2A_STATUS_SUCCESS:
            raise AssertionError(f"WDT_CMP default status={st_c}")
        if (cmp0 & CMP_MASK) != CMP_DEFAULT:
            raise AssertionError(f"WDT_CMP default=0x{cmp0 & CMP_MASK:x} want 0x{CMP_DEFAULT:x}")
        self.s2_ok = True
        sb.expect_eq("CHK-WDT-CMP-DEFAULT", cmp0 & CMP_MASK, CMP_DEFAULT)

        st_w = await self._wr32(jtag, WDT_CTRL, SCALE_PROGRAM)
        if st_w != J2A_STATUS_SUCCESS:
            raise AssertionError(f"locked CTRL write status={st_w}")
        st_l, ctrl_l = await self._rd32(jtag, WDT_CTRL)
        if st_l != J2A_STATUS_SUCCESS:
            raise AssertionError(f"locked CTRL read status={st_l}")
        if (ctrl_l & SCALE_MASK) != 0:
            raise AssertionError(f"WDT_CTRL stuck unlocked: 0x{ctrl_l:08x}")
        self.s3_ok = True
        sb.expect_eq("CHK-WDT-CTRL-LOCKED", ctrl_l & SCALE_MASK, 0)

        st_k = await wdt_unlock(jtag)
        if st_k != J2A_STATUS_SUCCESS:
            raise AssertionError(f"WDT unlock status={st_k}")
        st_key, key_rd = await wdt_key_read(jtag)
        if st_key != J2A_STATUS_SUCCESS or key_rd != WDT_KEY_UNLOCKED_RD:
            raise AssertionError(
                f"WDT_KEY unlocked indicator st={st_key} val=0x{key_rd:x} "
                f"want {WDT_KEY_UNLOCKED_RD}"
            )
        sb.expect_eq("CHK-WDT-KEY-UNLOCKED", key_rd, WDT_KEY_UNLOCKED_RD)

        st_cu = await self._wr32(jtag, WDT_CTRL, SCALE_PROGRAM)
        if st_cu != J2A_STATUS_SUCCESS:
            raise AssertionError(f"unlocked CTRL write status={st_cu}")
        st_ur, ctrl_u = await self._rd32(jtag, WDT_CTRL)
        if st_ur != J2A_STATUS_SUCCESS:
            raise AssertionError(f"unlocked CTRL read status={st_ur}")
        if (ctrl_u & SCALE_MASK) != SCALE_PROGRAM:
            raise AssertionError(
                f"post-unlock CTRL scale=0x{ctrl_u & SCALE_MASK:x} "
                f"want 0x{SCALE_PROGRAM:x} (CTRL=0x{ctrl_u:08x})"
            )
        sb.expect_eq("CHK-WDT-CTRL-UNLOCKED", ctrl_u & SCALE_MASK, SCALE_PROGRAM)

        st_k2 = await wdt_unlock(jtag)
        if st_k2 != J2A_STATUS_SUCCESS:
            raise AssertionError(f"WDT unlock before CMP status={st_k2}")
        st_p = await self._wr32(jtag, WDT_CMP, CMP_PROGRAM)
        if st_p != J2A_STATUS_SUCCESS:
            raise AssertionError(f"WDT_CMP program status={st_p}")
        st_rb, cmp_rb = await self._rd32(jtag, WDT_CMP)
        if st_rb != J2A_STATUS_SUCCESS:
            raise AssertionError(f"WDT_CMP readback status={st_rb}")
        if (cmp_rb & CMP_MASK) != CMP_PROGRAM:
            raise AssertionError(
                f"WDT_CMP programmed=0x{cmp_rb & CMP_MASK:x} want 0x{CMP_PROGRAM:x}"
            )
        self.s4_ok = True
        self._log(f"WDT_UNLOCK_OK cmp=0x{cmp_rb & CMP_MASK:x} scale=0x{ctrl_u & SCALE_MASK:x}")
        sb.expect_eq(
            "CHK-WDT-UNLOCK CMP programmed",
            cmp_rb & CMP_MASK,
            CMP_PROGRAM,
            evidence="WDT_UNLOCK_OK",
        )
