# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Do the OTP bridges still work when the lifecycle posture has closed the fabric one?

The ``dbg_disable`` derivation in ``sep_lifecycle_ctrl.sv`` takes
``smc_jtag2axi`` from the Case-2 gating term and hardwires ``smc_otp_jtag2axi``
and ``sep_otp_jtag2axi`` to 1'b0: the OTP bridges are outside the lifecycle
debug ladder. The other OTP leaves run with an eFuse image that leaves debug
open, so this sequence is the one that observes an OTP bridge completing while
the fabric bridge is shut.

This anchor runs with the PROD_END SEP shadow image, where
seq_lib.smu_lifecycle_table gives ``smc_jtag2axi`` disabled, and then:

* shows the fabric bridge really is shut -- a SINGLE_OP on the primary TAP
  launches nothing on the DTP -> SMC debug AXI port, the same observation
  smu_sep_dbg_gating_test makes;
* drives both OTP bridges to completion over the same TAP in that state, and
  compares what comes back against a value the image or the RDL fixes:
  the SEP eFuse MAP LC_STATE word must read the PROD_END encoding the image
  programmed, and the eFuse bank-control shim CSR must read its RDL reset.

The SEP eFuse bank-control leg is the last step. The SEP eFuse interface
controller (``efuse_interface_controller.sv``) routes every
address outside the eFuse MAP/MMR window to ``SHIM_SEL``, which leaves the SEP
on ``efuse_bank_ctrl_req_o`` and therefore crosses the SMU boundary. So a SEP
OTP JTAG2AXI access to the shim window is the one stimulus on this bench that
makes the boundary port move without a fuse sense, and its answer comes back
through the same bridge.

Both OTP legs check a value, not just a status: a bridge that returned SUCCESS
with the error slave's 0xbadcab1e, or with a stale capture, fails here.
"""

from __future__ import annotations

from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import c_header_u32, smc_indexed_addr
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_OP_READ,
    J2A_OP_WRITE,
    J2A_STATUS_BUSY,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    SMC_OTP_AXSIZE_4B,
    make_smu_jtag_tap,
    otp_jtag2axi_single_read,
    otp_jtag2axi_single_write,
    pack_otp_single_op,
    pack_single_op,
    require_jtag_tdo_resolved,
    sep_otp_jtag2axi_single_read,
    unpack_otp_single_op,
)
from seq_lib.smu_lifecycle_table import (
    LC_STATE_PRESENSE,
    lc_raw_from_shadow_preload,
    lc_state_name,
    lc_state_word,
    posture,
)

_REPO_ROOT = Path(__file__).resolve().parents[6]
_SEP_ADDR_H = _REPO_ROOT / "hw" / "sys" / "sep" / "regs" / "gen" / "c" / "sep_addr.h"
_SHIM_CTRL_H = (
    _REPO_ROOT
    / "hw"
    / "ip"
    / "efuse"
    / "dv"
    / "models"
    / "regs"
    / "gen"
    / "c"
    / "efuse_shim_ctrl.h"
)

#: SEP eFuse MAP LC_STATE, the word the shadow image programs.
SEP_EFUSE_LC_STATE = c_header_u32(_SEP_ADDR_H, "SEP_TOP_SEP_EFUSE_MAP_LC_STATE_BASE_ADDR")
#: SEP eFuse MAP SPARE0, a writable word no other consumer reads.
SEP_EFUSE_SPARE0 = c_header_u32(_SEP_ADDR_H, "SEP_TOP_SEP_EFUSE_MAP_SPARE0_BASE_ADDR")
#: eFuse bank-control shim CSR, outside the MAP/MMR window and therefore on
#: the SMU boundary port.
SEP_EFUSE_SHIM_INIT_TIME = c_header_u32(
    _SEP_ADDR_H, "SEP_TOP_SEP_EXTERNAL_EFUSE_SHIM_CTRL_EFUSE_BANK_INIT_TIME_BASE_ADDR"
)
SEP_EFUSE_SHIM_INIT_TIME_RESET = c_header_u32(
    _SHIM_CTRL_H, "EFUSE_SHIM_CTRL__EFUSE_BANK_INIT_TIME__INIT_TIME_reset"
)

#: SMC eFuse MAP SPARE[0], the word smu_dtp_otp_smc_map_rw_test also uses.
SMC_EFUSE_SPARE0 = smc_indexed_addr("SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR", 0)

#: SMC CPU_CTRL scratch0, SMC-local. A benign always-mapped fabric target; the
#: point is whether the bridge launches, not what it returns.
FABRIC_PROBE_ADDR = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", 0)

SEP_SPARE_PATTERN = 0x5A5A_A5A5
SMC_SPARE_PATTERN = 0x1234_ABCD
SHIM_INIT_TIME_PATTERN = 0x0000_0040

OTP_POLL = 128
FABRIC_SETTLE_CYCLES = 4000
POSTURE_TIMEOUT_CYCLES = 60000


class SmuOtpBridgesUnderDbgDisableSeq:
    """Both OTP bridges complete while the lifecycle posture blocks the fabric bridge."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.log = test.logger

    def _rd(self, name: str, *, allow_xz: bool = False) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on the wrapper tb top")
        return self.test.read_int(pin, name, allow_xz=allow_xz)

    def _dbg_counts(self) -> tuple[int, int]:
        return (
            self._rd("dtp_smc_dbg_aw_count_o", allow_xz=True),
            self._rd("dtp_smc_dbg_ar_count_o", allow_xz=True),
        )

    async def _await_posture_settled(self) -> None:
        """Block until the LCC reflects the shadow image rather than its pre-sense word."""
        for _ in range(POSTURE_TIMEOUT_CYCLES):
            if self._rd("smc_lc_state_in_o", allow_xz=True) != LC_STATE_PRESENSE:
                # Let dbg_disable follow feat_ctrl before anything reads it.
                await ClockCycles(self.dut.clk_smu_i, 200)
                return
            await ClockCycles(self.dut.clk_smu_i, 10)
        raise AssertionError(
            f"lifecycle posture never left its pre-sense value within "
            f"{POSTURE_TIMEOUT_CYCLES} cycles; the SEP shadow image was not applied"
        )

    async def _sep_otp_rd(self, jtag, addr: int, name: str) -> int:
        status, rdata = await sep_otp_jtag2axi_single_read(jtag, addr, poll_limit=OTP_POLL)
        require_jtag_tdo_resolved(f"SEP OTP J2A RD {name}")
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"SEP OTP J2A RD {name} @0x{addr:08x} status={status} "
                f"want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        value = int(rdata) & 0xFFFF_FFFF
        self.log.info("SEP OTP J2A RD %s @0x%08x -> 0x%08x SUCCESS", name, addr, value)
        return value

    async def _sep_otp_wr(self, jtag, addr: int, data: int, name: str) -> None:
        """SEP OTP SINGLE_OP write; polls the capture until the status leaves BUSY."""
        raw = pack_otp_single_op(J2A_OP_WRITE, addr, data, wstrb=0xF, size=SMC_OTP_AXSIZE_4B)
        await jtag.write("SEP_OTP_AXI_SINGLE_OP", raw)
        require_jtag_tdo_resolved(f"SEP OTP J2A WR issue {name}")
        await ClockCycles(self.dut.clk_smu_i, 32)
        status = None
        for _ in range(OTP_POLL):
            capt = await jtag.read("SEP_OTP_AXI_SINGLE_OP", shift_value=0)
            require_jtag_tdo_resolved(f"SEP OTP J2A WR poll {name}")
            status, _ = unpack_otp_single_op(capt)
            if status != J2A_STATUS_BUSY:
                break
            await ClockCycles(self.dut.clk_smu_i, 16)
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"SEP OTP J2A WR {name} @0x{addr:08x} status={status} "
                f"want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        self.log.info("SEP OTP J2A WR %s @0x%08x data=0x%08x SUCCESS", name, addr, data)

    async def _smc_otp_rd(self, jtag, addr: int, name: str) -> int:
        status, rdata = await otp_jtag2axi_single_read(
            jtag, addr, poll_limit=OTP_POLL, require_complete=True
        )
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"SMC OTP J2A RD {name} @0x{addr:08x} status={status} "
                f"want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        value = int(rdata) & 0xFFFF_FFFF
        self.log.info("SMC OTP J2A RD %s @0x%08x -> 0x%08x SUCCESS", name, addr, value)
        return value

    async def _smc_otp_wr(self, jtag, addr: int, data: int, name: str) -> None:
        status, _ = await otp_jtag2axi_single_write(
            jtag, addr, data, poll_limit=OTP_POLL, require_complete=True
        )
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"SMC OTP J2A WR {name} @0x{addr:08x} status={status} "
                f"want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        self.log.info("SMC OTP J2A WR %s @0x%08x data=0x%08x SUCCESS", name, addr, data)

    async def run(self) -> None:
        sb = self.test.env.scoreboard

        preload = cocotb.plusargs.get("sep_shadow_reg_preload")
        assert preload is not None, (
            "+sep_shadow_reg_preload is required: it names the lifecycle state under test"
        )
        state = lc_state_name(lc_raw_from_shadow_preload(str(preload)))
        want = posture(state)
        assert want.smc_jtag2axi_disabled, (
            f"{state} leaves the SMC fabric JTAG2AXI path open; this anchor needs a state "
            "whose posture closes it, otherwise 'OTP works while the fabric is blocked' "
            "is not the scenario being run"
        )

        await self._await_posture_settled()

        lc_state = self._rd("smc_lc_state_in_o")
        fabric_gated = self._rd("lcc_dbg_disable_smc_jtag2axi_o")
        self.log.info(
            "posture: %s lc_state=0x%02x smc_jtag2axi_disabled=%d (spec: lc_state=0x%02x "
            "smc_jtag2axi_disabled=%d)",
            state,
            lc_state,
            fabric_gated,
            want.lc_state,
            int(want.smc_jtag2axi_disabled),
        )
        if lc_state != want.lc_state:
            raise AssertionError(
                f"lc_state reads 0x{lc_state:02x}, {state} encodes as 0x{want.lc_state:02x}"
            )
        sb.expect_eq(
            "SMC fabric JTAG2AXI disabled by the lifecycle posture",
            fabric_gated,
            1,
            evidence="CHK-OTP-DBG-POSTURE",
        )

        jtag = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)

        idcode = await jtag.read_idcode()
        require_jtag_tdo_resolved("IDCODE")
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"TAP not answering: IDCODE 0x{idcode:08x}")

        # The fabric bridge is shut. Without this the OTP results below would be
        # equally consistent with a posture that never closed anything.
        before_aw, before_ar = self._dbg_counts()
        await jtag.write(
            "SMC_AXI_SINGLE_OP",
            pack_single_op(J2A_OP_READ, FABRIC_PROBE_ADDR, size=SMC_DBG_AXSIZE_4B),
        )
        await ClockCycles(self.dut.clk_smu_i, FABRIC_SETTLE_CYCLES)
        after_aw, after_ar = self._dbg_counts()
        self.log.info(
            "DTP->SMC debug AXI after a SINGLE_OP read of 0x%08x: AW %d->%d AR %d->%d",
            FABRIC_PROBE_ADDR,
            before_aw,
            after_aw,
            before_ar,
            after_ar,
        )
        sb.expect_eq(
            "DTP->SMC debug AXI launches while the posture blocks the bridge",
            (after_aw - before_aw, after_ar - before_ar),
            (0, 0),
            evidence="CHK-OTP-FABRIC-BLOCKED",
        )

        # SMC OTP bridge, same TAP, same gated state.
        await self._smc_otp_wr(jtag, SMC_EFUSE_SPARE0, SMC_SPARE_PATTERN, "SMC_SPARE0")
        smc_rb = await self._smc_otp_rd(jtag, SMC_EFUSE_SPARE0, "SMC_SPARE0")
        sb.expect_eq(
            "SMC OTP bridge write/readback while the fabric bridge is blocked",
            smc_rb,
            SMC_SPARE_PATTERN,
            evidence="CHK-OTP-SMC-RW-WHILE-BLOCKED",
        )

        # SEP OTP bridge: the LC_STATE word the image programmed, read back
        # through the bridge. The expected value is the encoding
        # smu_lifecycle_table derives for the state, so a bridge that returned
        # the error slave's pattern or a stale capture fails here.
        want_lc_word = lc_state_word(lc_raw_from_shadow_preload(str(preload)))
        sep_lc = await self._sep_otp_rd(jtag, SEP_EFUSE_LC_STATE, "SEP_EFUSE_LC_STATE")
        sb.expect_eq(
            "SEP OTP bridge returns the LC_STATE word the shadow image programmed",
            sep_lc & 0xFF,
            want_lc_word,
            evidence="CHK-OTP-SEP-LC-READ-WHILE-BLOCKED",
        )

        await self._sep_otp_wr(jtag, SEP_EFUSE_SPARE0, SEP_SPARE_PATTERN, "SEP_SPARE0")
        sep_rb = await self._sep_otp_rd(jtag, SEP_EFUSE_SPARE0, "SEP_SPARE0")
        sb.expect_eq(
            "SEP OTP bridge write/readback while the fabric bridge is blocked",
            sep_rb,
            SEP_SPARE_PATTERN,
            evidence="CHK-OTP-SEP-RW-WHILE-BLOCKED",
        )

        # The shim window: outside the eFuse MAP/MMR range, so the SEP eFuse
        # interface controller sends it out of the SEP on the bank-control
        # AXI-Lite port that crosses the SMU boundary.
        shim_reset = await self._sep_otp_rd(jtag, SEP_EFUSE_SHIM_INIT_TIME, "SEP_SHIM_INIT_TIME")
        sb.expect_eq(
            "eFuse bank-control shim CSR reads its RDL reset over the SEP OTP bridge",
            shim_reset,
            SEP_EFUSE_SHIM_INIT_TIME_RESET,
            evidence="CHK-OTP-SEP-BANK-CTRL-READ",
        )
        await self._sep_otp_wr(
            jtag, SEP_EFUSE_SHIM_INIT_TIME, SHIM_INIT_TIME_PATTERN, "SEP_SHIM_INIT_TIME"
        )
        shim_rb = await self._sep_otp_rd(jtag, SEP_EFUSE_SHIM_INIT_TIME, "SEP_SHIM_INIT_TIME")
        sb.expect_eq(
            "eFuse bank-control shim CSR takes a write over the SEP OTP bridge",
            shim_rb,
            SHIM_INIT_TIME_PATTERN,
            evidence="CHK-OTP-SEP-BANK-CTRL-WRITE",
        )
        await self._sep_otp_wr(
            jtag,
            SEP_EFUSE_SHIM_INIT_TIME,
            SEP_EFUSE_SHIM_INIT_TIME_RESET,
            "SEP_SHIM_INIT_TIME restore",
        )

        # The gate has to still be shut at the end, or the OTP completions above
        # cannot be attributed to the blocked-fabric state they were taken in.
        sb.expect_eq(
            "lifecycle posture still blocks the fabric bridge after the OTP traffic",
            self._rd("lcc_dbg_disable_smc_jtag2axi_o"),
            1,
            evidence="CHK-OTP-DBG-POSTURE-HELD",
        )
