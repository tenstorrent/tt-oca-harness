# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG2AXI DECERR then immediate VERSION_LO SUCCESS. SEP=1, no Force."""

from __future__ import annotations

import cocotb
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import (
    SMC_CHIP_CONFIG_VERSION_LO,
    SMC_CHIP_CONFIG_VERSION_LO_RESET,
    SMC_LOCAL_XBAR_UNMAPPED_GAP,
)
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    DTP_EXPECTED_SMC_JTAG2AXI_CAPS,
    J2A_STATUS_BUSY,
    J2A_STATUS_DECERR,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)

VERSION_LO = SMC_CHIP_CONFIG_VERSION_LO
VERSION_LO_RESET = SMC_CHIP_CONFIG_VERSION_LO_RESET
UNMAPPED = SMC_LOCAL_XBAR_UNMAPPED_GAP
OTP_POLL = 128


class smu_dtp_jtag2axi_back_to_back_error_ok_test_seq:
    """DECERR then immediate VERSION_LO SUCCESS; gate open on the SEP=1 wrapper."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.s1_ok = False
        self.s2_ok = False
        self.s3_ok = False
        self.s4_ok = False
        self.s5_ok = False

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
            poll_limit=OTP_POLL,
            require_complete=True,
        )
        return st, int(rdata) & 0xFFFF_FFFF

    async def _wr32(self, jtag, addr: int, data: int) -> int:
        st, _ = await jtag2axi_single_write(
            jtag,
            addr,
            data,
            wstrb=0x0F,
            size=SMC_DBG_AXSIZE_4B,
            poll_limit=OTP_POLL,
            require_complete=True,
        )
        return st

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        jtag = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)

        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        sb.expect_eq("CHK-B2B-JTAG-READY", idcode, DTP_DEFAULT_IDCODE)

        gate = self._sample_int("tb_smc_jtag2axi_security_disable") & 1
        if gate != 0:
            raise AssertionError(f"SMC J2A still gated after TCK sync: security_disable={gate}")
        caps = int(await jtag.read("SMC_JTAG2AXI_CAPS")) & ((1 << 14) - 1)
        require_jtag_tdo_resolved("SMC J2A CAPS")
        if caps != DTP_EXPECTED_SMC_JTAG2AXI_CAPS:
            raise AssertionError(
                f"SMC J2A CAPS=0x{caps:04x} want 0x{DTP_EXPECTED_SMC_JTAG2AXI_CAPS:04x}"
            )
        self.s1_ok = True
        self._log(f"CHK-B2B-GATE-OPEN disable={gate} caps=0x{caps:04x}")
        sb.expect_eq(
            "CHK-B2B-GATE-OPEN",
            (gate, caps),
            (0, DTP_EXPECTED_SMC_JTAG2AXI_CAPS),
        )

        st0, d0 = await self._rd32(jtag, VERSION_LO)
        if st0 != J2A_STATUS_SUCCESS or d0 != VERSION_LO_RESET:
            raise AssertionError(
                f"VERSION_LO baseline @0x{VERSION_LO:08x} status={st0} "
                f"data=0x{d0:08x} want SUCCESS+0x{VERSION_LO_RESET:08x}"
            )
        self.s2_ok = True
        self._log(f"CHK-B2B-ALLOW @0x{VERSION_LO:08x} data=0x{d0:08x} status=SUCCESS")
        sb.expect_eq("CHK-B2B-ALLOW", d0, VERSION_LO_RESET)

        st_e, hole_data = await self._rd32(jtag, UNMAPPED)
        if st_e != J2A_STATUS_DECERR:
            raise AssertionError(
                f"unmapped RD @0x{UNMAPPED:08x} status={st_e} data=0x{hole_data:08x} "
                f"want DECERR={J2A_STATUS_DECERR}"
            )
        st1, d1 = await self._rd32(jtag, VERSION_LO)
        if st1 == J2A_STATUS_BUSY:
            raise AssertionError("VERSION_LO after RD-DECERR stuck BUSY")
        if st1 != J2A_STATUS_SUCCESS or d1 != VERSION_LO_RESET:
            raise AssertionError(
                f"immediate VERSION_LO after RD-DECERR status={st1} "
                f"data=0x{d1:08x} want SUCCESS+0x{VERSION_LO_RESET:08x}"
            )
        self.s3_ok = True
        self._log(
            f"CHK-J2A-B2B RD-DECERR@0x{UNMAPPED:08x} data=0x{hole_data:08x} "
            f"then VERSION_LO=0x{d1:08x} status=SUCCESS"
        )
        sb.expect_eq(
            "CHK-J2A-B2B",
            (st_e, st1, d1),
            (J2A_STATUS_DECERR, J2A_STATUS_SUCCESS, VERSION_LO_RESET),
            evidence="J2A_B2B_OK",
        )

        st_w = await self._wr32(jtag, UNMAPPED, 0xDEAD_BEEF)
        if st_w != J2A_STATUS_DECERR:
            raise AssertionError(
                f"unmapped WR @0x{UNMAPPED:08x} status={st_w} want DECERR={J2A_STATUS_DECERR}"
            )
        st2, d2 = await self._rd32(jtag, VERSION_LO)
        if st2 != J2A_STATUS_SUCCESS or d2 != VERSION_LO_RESET:
            raise AssertionError(
                f"immediate VERSION_LO after WR-DECERR status={st2} "
                f"data=0x{d2:08x} want SUCCESS+0x{VERSION_LO_RESET:08x}"
            )
        self.s4_ok = True
        self._log(f"CHK-B2B-WR-DECERR WR status=DECERR then VERSION_LO=0x{d2:08x}")
        sb.expect_eq("CHK-B2B-WR-DECERR", (st_w, d2), (J2A_STATUS_DECERR, VERSION_LO_RESET))

        capt = await jtag.read("SMC_AXI_SINGLE_OP", shift_value=0)
        require_jtag_tdo_resolved("SMC SINGLE_OP sticky")
        sticky = int(capt) & 0x3
        if sticky == J2A_STATUS_BUSY:
            raise AssertionError("SINGLE_OP sticky BUSY after b2b")
        if sticky != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"SINGLE_OP sticky status={sticky} want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        self.s5_ok = True
        self._log("CHK-B2B-STICKY status=SUCCESS")
        sb.expect_eq("CHK-B2B-STICKY", sticky, J2A_STATUS_SUCCESS)

        self._log(
            f"PASS JTAG2AXI-B2B s1={self.s1_ok} s2={self.s2_ok} s3={self.s3_ok} "
            f"s4={self.s4_ok} s5={self.s5_ok} unmapped=0x{UNMAPPED:08x}"
        )
