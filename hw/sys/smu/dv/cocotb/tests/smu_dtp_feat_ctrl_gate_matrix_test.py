# SPDX-License-Identifier: Apache-2.0
"""smu_dtp_feat_ctrl_gate_matrix_test - P2-I9a feat_ctrl gate polarities.

Golden (jtag_ptap.sv, enable-polarity feat_ctrl):
  smc_jtag2axi_security_disable = !soc_debug || !ap_debug
  smc_otp_jtag2axi_security_disable = !fuse_test || !soc_debug || !ap_debug

Forces feat_ctrl leafs (not security_disable net) and checks:
  1. Observed disable nets match golden
  2. Fabric VERSION_LO allow/deny (SUCCESS+data vs not SUCCESS+silicon)
  3. OTP MAP allow/deny transaction (SUCCESS complete vs payload denied)

Real LCC #3538 OUT. Must FAIL if gate polarities disagree with golden.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles

from seq_lib.smu_jtag_helpers import (
    J2A_STATUS_SUCCESS,
    SMC_EFUSE_MAP_BIRA_WORD,
    force_feat_ctrl_bits,
    jtag2axi_single_read,
    make_smu_jtag_tap,
    otp_jtag2axi_single_read,
    otp_jtag2axi_single_write,
    release_forced,
    shadow_map_word32,
)
from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()

SMC_VERSION_LO_ADDR = 0xC000_2900
VERSION_LO_EXPECT = 0x0001_00A0
GATED_POLL = 24
MAP_BYTE_OFF = SMC_EFUSE_MAP_BIRA_WORD & 0xFFF
OTP_DENY_PATTERN = 0xDEAD_BEEF
OTP_ALLOW_PATTERN = 0xA5A5_5A5A

_SEC_PATHS = (
    "u_dut.u_dtp.u_jtag_intf_unit.u_jtag_ptap.smc_jtag2axi_security_disable",
    "u_dut.u_dtp.u_jtag_ptap.smc_jtag2axi_security_disable",
)
_OTP_SEC_PATHS = (
    "u_dut.u_dtp.u_jtag_intf_unit.u_jtag_ptap.smc_otp_jtag2axi_security_disable",
    "u_dut.u_dtp.u_jtag_ptap.smc_otp_jtag2axi_security_disable",
)


def _resolve(dut, path: str):
    node = dut
    for part in path.split("."):
        if not hasattr(node, part):
            return None
        node = getattr(node, part)
    return node


def _read_net(dut, candidates) -> int | None:
    for path in candidates:
        h = _resolve(dut, path)
        if h is None:
            continue
        try:
            return int(h.value) & 1
        except Exception:
            continue
    return None


# (soc, ap, fuse_test) -> expect fabric allow, otp allow
_MATRIX = (
    # soc ap fuse | fabric_allow otp_allow
    (0, 0, 0, False, False),
    (0, 1, 1, False, False),
    (1, 0, 1, False, False),
    (1, 1, 0, True, False),
    (1, 1, 1, True, True),
)


@pyuvm.test()
class smu_dtp_feat_ctrl_gate_matrix_test(smu_base_test):
    """feat_ctrl polarity matrix vs jtag_ptap golden equations."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 8)

        for soc, ap, fuse, fab_allow, otp_allow in _MATRIX:
            forced = force_feat_ctrl_bits(
                dut,
                {"soc_debug": soc, "ap_debug": ap, "fuse_test": fuse},
                self.logger,
            )
            try:
                await ClockCycles(dut.clk_smu_i, 8)
                for _ in range(4):
                    await jtag.step_tms(0)

                golden_fab_dis = int(not (soc and ap))
                golden_otp_dis = int(not (fuse and soc and ap))
                fab_dis = _read_net(dut, _SEC_PATHS)
                otp_dis = _read_net(dut, _OTP_SEC_PATHS)
                assert fab_dis is not None, "smc_jtag2axi_security_disable not found"
                assert otp_dis is not None, "smc_otp_jtag2axi_security_disable not found"
                sb.expect_eq(
                    f"fabric disable soc={soc} ap={ap}",
                    fab_dis,
                    golden_fab_dis,
                evidence="FEAT_NET_GOLDEN")
                sb.expect_eq(
                    f"otp disable soc={soc} ap={ap} fuse={fuse}",
                    otp_dis,
                    golden_otp_dis,
                evidence="FEAT_FAB_ALLOW")
                sb.expect_eq(
                    f"fab_allow flag vs golden soc={soc} ap={ap}",
                    int(fab_allow),
                    int(not golden_fab_dis),
                evidence="FEAT_FAB_DENY")
                sb.expect_eq(
                    f"otp_allow flag vs golden fuse={fuse}",
                    int(otp_allow),
                    int(not golden_otp_dis),
                evidence="FEAT_OTP_ALLOW")

                # --- Fabric VERSION_LO ---
                if fab_allow:
                    st, rdata = await jtag2axi_single_read(
                        jtag, SMC_VERSION_LO_ADDR, require_complete=True
                    )
                    sb.expect_eq(
                        f"VERSION_LO allow status soc={soc} ap={ap}",
                        st,
                        J2A_STATUS_SUCCESS,
                    evidence="FEAT_OTP_DENY")
                    sb.expect_eq(
                        f"VERSION_LO allow data soc={soc} ap={ap}",
                        int(rdata) & 0xFFFF_FFFF,
                        VERSION_LO_EXPECT,
                    )
                else:
                    st, rdata = await jtag2axi_single_read(
                        jtag, SMC_VERSION_LO_ADDR, poll_limit=GATED_POLL
                    )
                    sb.expect_j2a_payload_denied(
                        f"VERSION_LO deny soc={soc} ap={ap}",
                        st,
                        rdata,
                        VERSION_LO_EXPECT,
                        data_bits=32,
                        success_status=J2A_STATUS_SUCCESS,
                    )

                # --- OTP MAP transaction ---
                # Gated OTP often returns idle SUCCESS (P1); real deny evidence is
                # that a gated write must not update the eFuse map shadow.
                if otp_allow:
                    wst, _ = await otp_jtag2axi_single_write(
                        jtag,
                        SMC_EFUSE_MAP_BIRA_WORD,
                        OTP_ALLOW_PATTERN,
                        require_complete=True,
                    )
                    sb.expect_eq(
                        f"OTP MAP allow write status fuse={fuse}",
                        wst,
                        J2A_STATUS_SUCCESS,
                    )
                    ost, odata = await otp_jtag2axi_single_read(
                        jtag, SMC_EFUSE_MAP_BIRA_WORD, require_complete=True
                    )
                    sb.expect_eq(
                        f"OTP MAP allow read status fuse={fuse}",
                        ost,
                        J2A_STATUS_SUCCESS,
                    )
                    sb.expect_eq(
                        f"OTP MAP allow RDATA fuse={fuse}",
                        int(odata) & 0xFFFF_FFFF,
                        OTP_ALLOW_PATTERN,
                    )
                    shadow = shadow_map_word32(dut, MAP_BYTE_OFF)
                    if shadow is not None:
                        sb.expect_eq(
                            f"OTP MAP shadow after allow fuse={fuse}",
                            shadow,
                            OTP_ALLOW_PATTERN,
                        )
                else:
                    before = shadow_map_word32(dut, MAP_BYTE_OFF)
                    await otp_jtag2axi_single_write(
                        jtag,
                        SMC_EFUSE_MAP_BIRA_WORD,
                        OTP_DENY_PATTERN,
                        poll_limit=GATED_POLL,
                    )
                    after = shadow_map_word32(dut, MAP_BYTE_OFF)
                    if before is not None and after is not None:
                        sb.expect_eq(
                            f"OTP MAP shadow unchanged when gated fuse={fuse}",
                            after,
                            before,
                        )
                        sb.expect_true(
                            f"OTP MAP shadow not DEAD_BEEF when gated fuse={fuse}",
                            after != OTP_DENY_PATTERN,
                        )
                    else:
                        # Fallback if shadow not VPI-readable: must not be
                        # SUCCESS delivering the deny pattern via readback.
                        ost, odata = await otp_jtag2axi_single_read(
                            jtag, SMC_EFUSE_MAP_BIRA_WORD, poll_limit=GATED_POLL
                        )
                        sb.expect_j2a_payload_denied(
                            f"OTP MAP deny read fuse={fuse}",
                            ost,
                            odata,
                            OTP_DENY_PATTERN,
                            data_bits=32,
                            success_status=J2A_STATUS_SUCCESS,
                        )
            finally:
                release_forced(forced)
            await ClockCycles(dut.clk_smu_i, 4)

        self.logger.info("smu_dtp_feat_ctrl_gate_matrix_test: matrix OK")
