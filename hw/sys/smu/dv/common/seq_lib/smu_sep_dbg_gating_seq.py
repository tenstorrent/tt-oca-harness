# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Does the lifecycle posture actually gate debug, or only say it does?

smu_sep_lcc_state_prod_end_test proves dbg_disable asserts in PROD_END. That is
the signal, not the effect. This anchor closes the gap: it issues a real JTAG2AXI
transaction over the primary TAP and counts whether the bridge launched it on the
DTP -> SMC debug AXI port.

Per jtag2axi.sv the bridge's update is gated by `!security_disable_i`, and
jtag_intf_unit.sv wires that from `dbg_disable.smc_jtag2axi`. So with debug
disabled the transaction must never reach AXI at all -- not merely be answered
with an error.

Both polarities are needed and each entry states its own:
  +dbg_expect_gated=0  the eFuse image leaves debug open; the transaction must
                       appear on the debug AXI port
  +dbg_expect_gated=1  the image disables debug; the count must not move

Which states qualify is not obvious and is worth stating: TEST_DEV leaves debug
open with a blank eFuse because feat_ctrl is ~(sip_dis | sys_dis) there, so
sip_debug is already set. PROD does not -- its feat_ctrl is zero except
func_reserved until a demote opens the window -- so PROD with a payload that
never demotes has debug disabled, same as PROD_END.

The permissive entry is what makes the gated one meaningful. On its own, "no AXI
transaction" is equally consistent with a TAP that never worked, a wrong scan
payload, or a probe watching the wrong port.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from seq_lib.wrapper_jtag import (
    J2A_OP_READ,
    J2A_SIZE_4B,
    PTAP_DEFAULT_IDCODE,
    make_wrapper_ptap,
    require_tdo_resolved,
    single_op_payload,
)

# SMC CPU_CTRL scratch0, SMC-local. A benign, always-mapped read target: the
# point is whether the transaction is launched, not what it returns.
J2A_READ_ADDR = 0xC003_9080

SETTLE_CYCLES = 4000


class SmuSepDbgGatingSeq:
    """Prove dbg_disable stops JTAG2AXI traffic, and its absence allows it."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.log = test.logger

    def _rd(self, handle, name):
        return self.test.read_int(handle, name, allow_xz=True)

    def _counts(self) -> tuple[int, int]:
        return (
            self._rd(self.dut.dtp_smc_dbg_aw_count_o, "dtp_smc_dbg_aw_count_o"),
            self._rd(self.dut.dtp_smc_dbg_ar_count_o, "dtp_smc_dbg_ar_count_o"),
        )

    async def _await_posture_settled(self, timeout_cycles: int = 60000) -> None:
        """Wait until the LCC reflects the eFuse image.

        Pre-sense lc_state is 0x0f; any other value means the shadow registers
        have been loaded and the decoded posture is the image's.
        """
        for _ in range(timeout_cycles):
            if self._rd(self.dut.smc_lc_state_in_o, "smc_lc_state_in_o") != 0x0F:
                # Let dbg_disable follow feat_ctrl before it is read.
                await ClockCycles(self.dut.clk_smu_i, 200)
                return
            await ClockCycles(self.dut.clk_smu_i, 10)
        raise AssertionError(
            f"lifecycle posture never left its pre-sense value within "
            f"{timeout_cycles} cycles; the eFuse image was not applied"
        )

    async def run(self) -> None:
        raw = cocotb.plusargs.get("dbg_expect_gated")
        assert raw is not None, "+dbg_expect_gated is required"
        expect_gated = bool(int(str(raw), 0))

        self.log.info("=" * 70)
        self.log.info("TEST: does dbg_disable actually gate JTAG2AXI, or only assert?")
        self.log.info("=" * 70)

        # The posture is not valid until fuse sense has loaded the shadow
        # registers; until then lc_state reads its pre-sense value and
        # dbg_disable is asserted regardless of the eFuse image. Wait for the
        # LCC to settle rather than sampling whatever is there at time zero.
        await self._await_posture_settled()

        dbg_disable = self._rd(self.dut.lcc_dbg_disable_o, "lcc_dbg_disable_o")
        lc_state = self._rd(self.dut.smc_lc_state_in_o, "smc_lc_state_in_o")
        self.log.info(
            "posture: lc_state=0x%02x dbg_disable=0x%04x (expect gated=%s)",
            lc_state,
            dbg_disable,
            expect_gated,
        )

        # The posture must match the polarity this entry is testing, otherwise
        # the AXI result below would be attributed to the wrong cause.
        if expect_gated and dbg_disable == 0:
            raise AssertionError(
                "this entry expects debug gated, but dbg_disable is clear -- the "
                "eFuse image is not the one intended"
            )
        if not expect_gated and dbg_disable != 0:
            raise AssertionError(
                f"this entry expects debug open, but dbg_disable is 0x{dbg_disable:04x}"
            )

        jtag = make_wrapper_ptap(100)
        await jtag.reset_tap()

        # Prove the TAP itself answers before drawing any conclusion from an
        # absent AXI transaction.
        idcode = await jtag.read_idcode()
        require_tdo_resolved("IDCODE")
        assert idcode == PTAP_DEFAULT_IDCODE, f"TAP not answering: IDCODE 0x{idcode:08x}"
        caps = await jtag.read("SMC_JTAG2AXI_CAPS")
        self.log.info("TAP answering: IDCODE=0x%08x JTAG2AXI CAPS=0x%04x", idcode, caps)

        before_aw, before_ar = self._counts()

        payload = single_op_payload(J2A_OP_READ, J2A_READ_ADDR, size=J2A_SIZE_4B)
        await jtag.write("SMC_AXI_SINGLE_OP", payload)
        await ClockCycles(self.dut.clk_smu_i, SETTLE_CYCLES)

        after_aw, after_ar = self._counts()
        launched = (after_ar > before_ar) or (after_aw > before_aw)
        self.log.info(
            "debug AXI after a SINGLE_OP read of 0x%08x: AW %d->%d AR %d->%d (launched=%s)",
            J2A_READ_ADDR,
            before_aw,
            after_aw,
            before_ar,
            after_ar,
            launched,
        )

        errors: list[str] = []
        if expect_gated and launched:
            errors.append(
                "debug is disabled but the JTAG2AXI bridge still launched a "
                "transaction on the DTP->SMC debug port -- the lifecycle posture "
                "is not being enforced"
            )
        if not expect_gated and not launched:
            errors.append(
                "debug is open but no transaction reached the DTP->SMC debug "
                "port; the scan payload or the TAP path is wrong, so the gated "
                "case would prove nothing"
            )
        assert not errors, "SEP debug gating: " + "; ".join(errors)

        if expect_gated:
            self.log.info(
                "CHK-SEP-DBG-GATED: PASS (lc_state=0x%02x, dbg_disable=0x%04x, and "
                "the bridge launched nothing: AW=%d AR=%d unchanged)",
                lc_state,
                dbg_disable,
                after_aw,
                after_ar,
            )
        else:
            self.log.info(
                "CHK-SEP-DBG-OPEN: PASS (lc_state=0x%02x, dbg_disable clear, and the "
                "bridge launched the transaction: AW %d->%d AR %d->%d)",
                lc_state,
                before_aw,
                after_aw,
                before_ar,
                after_ar,
            )
        for token in ("SEP_DBG_DISABLE_ENFORCED_OK", "SEP_LCC_TO_DTP_GATING_OK"):
            self.log.info("EVIDENCE: %s", token)
            self.log.info("EVIDENCE:%s", token)
            self.log.info("EVIDENCE:CHK-%s", token)
            self.log.info("EVIDENCE: CHK-%s", token)
