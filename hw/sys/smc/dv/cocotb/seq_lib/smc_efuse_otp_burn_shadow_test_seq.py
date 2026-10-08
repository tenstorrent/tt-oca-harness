# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OTP program command path + shadow verify. *Model-backed (NOT silicon-path).*

MODEL-BACKED, DECLARED. `tb_efuse_otp_word0` / `tb_efuse_programmed_word0` tap
the adopter-supplied simulation stand-in for the foundry OTP macro,
`hw/ip/efuse/dv/models/efuse_bank_model.sv`, instantiated at
`hw/top/smc_ip_integration.sv`. Its set-once behaviour is `onwrite = woset` in
`hw/ip/efuse/dv/models/regs/efuse_bank.rdl`, a register file no other module
in `hw/` instantiates, and its program-failure injection (in
`efuse_bank_model.sv`) is a `+smc_efuse_prog_fail_count` plusarg with no
silicon counterpart. Nothing observed on those two probes is evidence that a
fuse burns in silicon.

DEFENDS (real DUT RTL):
  * Real fuse sense completes without `+skip_fuse_sense`, and the SMC_EFUSE_MAP
    window serves the sensed word over SEP_IN AXI (`efuse_shadow_regs.sv`, loaded
    by its sense FSM).
  * The eFuse interface controller issues a PROGRAM command, latches the
    readback comparison result and reports it in `PROGRAM_STATUS`
    (`efuse_interface_shim.sv` -> `efuse_program_interface.sv`), with
    both polarities observed: set on the injected failure, clear on the clean
    program.
  * `EFUSE_STATUS.efuse_sense_done` mirrors the sense handshake.

DEFENDS (model-scored, not silicon):
  * The bank model's storage is unchanged by a fail-injected program and
    sticky-ORs one bit on a successful one. This shows the controller's command
    reached the bank; it says nothing about fuse physics.

DOES NOT DEFEND:
  * Foundry OTP macro analog timing / voltage.
  * Full OCCP ROM secure-boot stack (see smc_occp_sanity_secure_error_test).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import efuse_ifc_u32, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_efuse_vip_utils import efuse_preload_word_at

EFUSE_STATUS = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_INTERFACE_CTRL_STATUS_BASE_ADDR")
EFUSE_PROGRAM_CTRL = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_CTRL_BASE_ADDR")
# Addressed and NAMED by the same generated symbol. At this offset the shadow
# block serves raw shadow word 0 (`efuse_shadow_regs.sv` returns
# `shadow_efuse.values[paddr>>2]` for the whole map window) rather than the
# lock fields the register name implies, so the value read back is fuse content
# and not the register's 0x0 reset.
SMC_EFUSE_MAP_LOCKS = smc_addr("SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR")

# Word 0 of the preload asset the bank model $readmemh's at time 0, derived from
# the asset at run time so it follows a regenerated asset.
OTP_WORD0_MARKER = efuse_preload_word_at(SMC_EFUSE_MAP_LOCKS)

# PROGRAM_CTRL field masks by generated symbol, so an eFuse RDL regeneration
# moves them with it.
_PROG_DATA = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_PROGRAM_CTRL__EFUSE_DATA_bm")
_PROG_GO = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_PROGRAM_CTRL__EFUSE_PROGRAM_GO_bm")
_PROG_READBACK = efuse_ifc_u32(
    "EFUSE_INTERFACE_CTRL__EFUSE_PROGRAM_CTRL__EFUSE_PROGRAM_READ_BACK_bm"
)
_PROG_ENABLE = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_PROGRAM_CTRL__PROGRAM_ENABLE_bm")
_PROG_DONE = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_PROGRAM_CTRL__PROGRAM_DONE_bm")
_PROG_STATUS = efuse_ifc_u32("EFUSE_INTERFACE_CTRL__EFUSE_PROGRAM_CTRL__PROGRAM_STATUS_bm")

#: Directed, timing-independent SEP_IN AXI accesses this sequence issues: two
#: PROGRAM_CTRL writes, the shadow-map read and the EFUSE_STATUS read. The
#: `_wait_program_done` polls are excluded because their count depends on DUT
#: timing.
DIRECTED_ACCESSES = 4


class smc_efuse_otp_burn_shadow_test_seq(SmcCsrSeq):
    """Sense + shadow golden + burn-fail then burn-success."""

    async def _wait_program_done(self, clk, label: str) -> int:
        for _ in range(10_000):
            await RisingEdge(clk)
            st = await self.csr_read(label, EFUSE_PROGRAM_CTRL)
            if st & _PROG_DONE:
                return st
        raise AssertionError(f"{label}: program_done never set")

    async def body(self) -> None:
        dut = cocotb.top
        clk = dut.clk_smc_i

        # The shared helper waits for the fuse-sense handshake AND the delayed
        # fuse_reset / warm-reset release the eFuse CSR block sits behind.
        await self.wait_fuse_sense_done()

        # PRELOAD PLUMBING, not sense proof. Both sides of this compare are
        # supplied by the testbench: the left is the bank model's own storage and
        # the right is the asset the model $readmemh'd into it, with no DUT RTL
        # in between (fuse sense only READS this array). It localises a dropped
        # `+smc_efuse_hex` plusarg to one line instead of a later shadow-read
        # mismatch.
        otp0 = int(dut.tb_efuse_otp_word0.value)
        assert otp0 == OTP_WORD0_MARKER, (
            f"eFuse bank-model preload plumbing: model storage word 0 is "
            f"0x{otp0:08x} but the asset word is 0x{OTP_WORD0_MARKER:08x}; the "
            f"+smc_efuse_hex image did not reach the model"
        )
        cocotb.log.info(
            "CHK-EFUSE-OTP-PRELOAD: bank-model storage word 0 = 0x%08x matches "
            "the +smc_efuse_hex asset (testbench plumbing check -- no DUT RTL "
            "on this path)",
            otp0,
        )

        # `tb_efuse_programmed_word0` is `assign`ed from `tb_efuse_otp_word0` in
        # `hw/sys/smc/dv/tb/tb_top.sv`, so the two probes are one net and are
        # never compared to each other.

        # SENSE + SHADOW TRANSPORT, real DUT RTL. SEP_IN AXI -> SMC fabric ->
        # efuse_shadow_reg_access_control -> efuse_shadow_regs, whose word 0 was
        # loaded by the sense FSM from the interface shim. The expectation is the
        # input asset, derived from neither the DUT nor the model's logic.
        map0 = await self.csr_read(
            "SMC_EFUSE_MAP_LOCKS", SMC_EFUSE_MAP_LOCKS, expected=OTP_WORD0_MARKER
        )
        cocotb.log.info(
            "CHK-EFUSE-OTP-SHADOW: SMC_EFUSE_MAP_LOCKS @0x%08x = 0x%08x, the "
            "sensed shadow word, matching asset word 0",
            SMC_EFUSE_MAP_LOCKS,
            map0,
        )

        # First PROGRAM (bit2 is clear in the preload word): the injected failure
        # must not sticky-OR. Prefer a clear bit so PROGRAM_READBACK observes a
        # real miss when the bank model zeroes the write data under
        # +smc_efuse_prog_fail_count.
        _FAIL_BIT = 2
        await self.csr_write(
            "EFUSE_PROGRAM_CTRL_FAIL",
            EFUSE_PROGRAM_CTRL,
            _FAIL_BIT | _PROG_DATA | _PROG_GO | _PROG_READBACK | _PROG_ENABLE,
        )
        st_fail = await self._wait_program_done(clk, "PROGRAM_FAIL")
        prog_fail = int(dut.tb_efuse_programmed_word0.value)
        assert prog_fail == OTP_WORD0_MARKER, (
            f"program-fail inject must not sticky-OR OTP bits: model storage is "
            f"0x{prog_fail:08x}, expected the unchanged 0x{OTP_WORD0_MARKER:08x}"
        )
        assert st_fail & _PROG_STATUS, (
            f"program_status expected 1 on injected fail (PROGRAM_CTRL=0x{st_fail:08x})"
        )
        cocotb.log.info(
            "CHK-EFUSE-OTP-PROGRAM-FAIL: PROGRAM_CTRL=0x%08x status=%d "
            "(real RTL: efuse_interface_shim readback comparison) and the "
            "bank-model word 0 is unchanged at 0x%08x (model-scored)",
            st_fail,
            1 if st_fail & _PROG_STATUS else 0,
            prog_fail,
        )

        # Second PROGRAM (bit0 is clear in the preload word): success sticky-OR.
        await self.csr_write(
            "EFUSE_PROGRAM_CTRL_OK",
            EFUSE_PROGRAM_CTRL,
            0 | _PROG_DATA | _PROG_GO | _PROG_READBACK | _PROG_ENABLE,
        )
        st_ok = await self._wait_program_done(clk, "PROGRAM_OK")
        prog_ok = int(dut.tb_efuse_programmed_word0.value)
        assert (prog_ok & 1) == 1, "sticky-OR burn did not set bit0"
        assert prog_ok == (OTP_WORD0_MARKER | 1), f"sticky-OR burn unexpected: got 0x{prog_ok:08x}"
        # POSITIVE CONTROL for the `program_status == 1` assert on the injected
        # failure above. Without it, a PROGRAM_CTRL whose status bit were stuck
        # high would satisfy the fail leg just as well.
        assert (st_ok & _PROG_STATUS) == 0, (
            f"program_status is set after a program that was NOT fail-injected "
            f"(PROGRAM_CTRL=0x{st_ok:08x}); the status bit does not "
            f"discriminate, so the injected-failure assert above proves nothing"
        )
        cocotb.log.info(
            "CHK-EFUSE-OTP-PROGRAM-OK: PROGRAM_CTRL=0x%08x status=%d -- the "
            "same status bit reads 1 on the injected failure and 0 here, so it "
            "discriminates; bank-model word 0 sticky-ORed to 0x%08x "
            "(model-scored)",
            st_ok,
            1 if st_ok & _PROG_STATUS else 0,
            prog_ok,
        )

        status = await self.csr_read("EFUSE_STATUS", EFUSE_STATUS)
        assert status & 1, "EFUSE_STATUS.efuse_sense_done not set"
        cocotb.log.info(
            "CHK-EFUSE-OTP-STATUS: EFUSE_STATUS=0x%08x, efuse_sense_done "
            "mirrored through the CSR path",
            status,
        )
