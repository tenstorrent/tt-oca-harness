# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sideband representative CSR precheck.

Every OKAY status read carries an exact expected word built from the generated
PeakRDL header ``hw/ip/avsbus_controller/regs/gen/c/avsbus_controller.h``
(field masks / positions / RDL reset values) plus the RDL field descriptions of
the post-reset idle state -- never from the RTL.

AVS_DEBUG_READBACK non-destructiveness
---------------------------------------------------------
``avsbus_controller.rdl`` declares AVS_DEBUG_READBACK a mirror of AVS_READBACK
whose read "does NOT affect the AVS readback fifo pointer", and
``hw/ip/avsbus_controller/doc/memmap.adoc`` says it "returns the same data
without popping". Comparing two AVS_DEBUG_READBACK reads to each other proves
nothing on its own -- with the readback FIFO empty the two words are the same
constant whatever the pointer does. The observable that *does* discriminate is
``AVS_INTERRUPT.READBACK_UNDERFLOW_INT``, which ``avsbus_controller.rdl``
defines as "an APB read on the AVS_READBACK reg occurred when the readback fifo
was empty". So with the FIFO empty:

* a read that touches the readback pointer raises that flag, and
* a read that does not, leaves it clear.

This sequence therefore asserts the property against its contrast:
``AVS_INTERRUPT == 0`` before and after the AVS_DEBUG_READBACK pair (nothing
touched the pointer), then the AVS_READBACK read -- the register the RDL
documents as pointer-advancing -- must raise exactly
READBACK_UNDERFLOW_INT. That second leg is the positive control: it shows the
flag can reach 1 on this DUT over this path, so the two ``== 0`` compares are
live measurements rather than a stuck-at-0 pass. The AVS_DEBUG_READBACK data
word itself is still NOT compared against a constant: the RDL reset
(0xFFFFFFFF) is overridden by the hw=w driver and the empty-FIFO sentinel the
DUT returns exists only in the RTL, so adopting it would be an RTL-transcribed
expectation.
"""

from __future__ import annotations

import cocotb

# ``_REPO`` / ``_field_mask`` come from the authoritative-map module:
# it is the single place that knows the repo layout and how to read a generated
# PeakRDL C header, and AVSBus has no ``smc_addr_map`` accessor of its own.
from .smc_addr_map import _REPO, _field_mask, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

_AVSBUS_H = _REPO / "hw" / "ip" / "avsbus_controller" / "regs" / "gen" / "c" / "avsbus_controller.h"


def _avs(symbol: str) -> int:
    """Field mask / position / reset value from generated ``avsbus_controller.h``."""
    return _field_mask(_AVSBUS_H, symbol)


# --- Authoritative AVSBus window (PeakRDL smc_addr.h) ---
AVS_READBACK = smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_READBACK_BASE_ADDR")
AVS_DEBUG_READBACK = smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_DEBUG_READBACK_BASE_ADDR")
AVS_NORMAL_STATUS = smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_NORMAL_STATUS_BASE_ADDR")
AVS_SLAVE_STATUS = smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_SLAVE_STATUS_BASE_ADDR")
AVS_FIFOS_STATUS = smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_FIFOS_STATUS_BASE_ADDR")
AVS_INTERRUPT = smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_INTERRUPT_BASE_ADDR")
AVS_INTERRUPT_MASK = smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_INTERRUPT_MASK_BASE_ADDR")
# avsbus_controller.rdl AVS_INTERRUPT_MASK -- nine rw fields, all masked at reset.
AVS_INTERRUPT_MASK_RESET = 0x1FF
AVS_INTERRUPT_CLEAR = smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_INTERRUPT_CLEAR_BASE_ADDR")

# --- Readback-pointer witness (see module docstring) ---
# ``AVS_INTERRUPT`` reset word: every interrupt field's RDL reset is 0, so the
# whole register reads 0x00000000 with nothing pending.
AVS_INTERRUPT_NONE_PENDING = 0x00000000
# The single flag the readback pointer raises when it is advanced on an empty
# FIFO (avsbus_controller.rdl AVS_INTERRUPT.READBACK_UNDERFLOW_INT). Mask by
# symbol from the generated header.
AVS_READBACK_UNDERFLOW = _avs("AVSBUS_CONTROLLER__AVS_INTERRUPT__READBACK_UNDERFLOW_INT_bm")
# Write-1 clear for the same flag (AVS_INTERRUPT_CLEAR.CLEAR_READBACK_UNDERFLOW_INT
# in avsbus_controller.rdl); leaves the block back at "no pending interrupts".
AVS_CLEAR_READBACK_UNDERFLOW = _avs(
    "AVSBUS_CONTROLLER__AVS_INTERRUPT_CLEAR__CLEAR_READBACK_UNDERFLOW_INT_bm"
)

# --- Exact expected words for the untouched, no-command-ever-issued state ---
# AVS_NORMAL_STATUS: the RDL descriptions define the idle state directly --
# command FIFO empty and neither master nor slave driving the AVS bus. Every
# other bit in the register is an activity/error indicator whose RDL reset is 0
# and which cannot have been set because no AVS_CMD was ever written.
AVS_NORMAL_STATUS_IDLE = _avs("AVSBUS_CONTROLLER__AVS_NORMAL_STATUS__CMD_FIFO_EMPTY_bm") | _avs(
    "AVSBUS_CONTROLLER__AVS_NORMAL_STATUS__AVS_BUS_IS_IDLE_bm"
)

# AVS_SLAVE_STATUS: no slave subframe has been received, so both fields hold
# their RDL reset values.
AVS_SLAVE_STATUS_RESET = (
    _avs("AVSBUS_CONTROLLER__AVS_SLAVE_STATUS__AVS_SLAVE_ACK_reset")
    << _avs("AVSBUS_CONTROLLER__AVS_SLAVE_STATUS__AVS_SLAVE_ACK_bp")
) | (
    _avs("AVSBUS_CONTROLLER__AVS_SLAVE_STATUS__AVS_SLAVE_STATUS_RESPONSE_reset")
    << _avs("AVSBUS_CONTROLLER__AVS_SLAVE_STATUS__AVS_SLAVE_STATUS_RESPONSE_bp")
)

# AVS_FIFOS_STATUS: both FIFOs empty -> occupied = 0, vacant = full depth. The
# depths come from the RDL reset values of the vacant-slot fields.
AVS_FIFOS_STATUS_EMPTY = (
    (
        _avs("AVSBUS_CONTROLLER__AVS_FIFOS_STATUS__CMD_FIFO_OCCUPIED_SLOTS_reset")
        << _avs("AVSBUS_CONTROLLER__AVS_FIFOS_STATUS__CMD_FIFO_OCCUPIED_SLOTS_bp")
    )
    | (
        _avs("AVSBUS_CONTROLLER__AVS_FIFOS_STATUS__CMD_FIFO_VACANT_SLOTS_reset")
        << _avs("AVSBUS_CONTROLLER__AVS_FIFOS_STATUS__CMD_FIFO_VACANT_SLOTS_bp")
    )
    | (
        _avs("AVSBUS_CONTROLLER__AVS_FIFOS_STATUS__READBACK_FIFO_OCCUPIED_SLOTS_reset")
        << _avs("AVSBUS_CONTROLLER__AVS_FIFOS_STATUS__READBACK_FIFO_OCCUPIED_SLOTS_bp")
    )
    | (
        _avs("AVSBUS_CONTROLLER__AVS_FIFOS_STATUS__READBACK_FIFO_VACANT_SLOTS_reset")
        << _avs("AVSBUS_CONTROLLER__AVS_FIFOS_STATUS__READBACK_FIFO_VACANT_SLOTS_bp")
    )
)

# Value-checked OKAY status reads. Every row carries an exact expected word, so
# the loop below needs no slice and no `expected is not None` guard: a row added
# without an expectation is a TypeError/None compare, not a silently skipped
# read.
SIDEBAND_OKAY_READS = [
    ("AVS_NORMAL_STATUS", AVS_NORMAL_STATUS, AVS_NORMAL_STATUS_IDLE),
    ("AVS_SLAVE_STATUS", AVS_SLAVE_STATUS, AVS_SLAVE_STATUS_RESET),
    ("AVS_FIFOS_STATUS", AVS_FIFOS_STATUS, AVS_FIFOS_STATUS_EMPTY),
]
SIDEBAND_ERR_READS = [
    ("AVS_READBACK", AVS_READBACK),
]
# AVS_DEBUG_READBACK is read twice (the non-destructive-mirror pair) from its own
# constant above; the rest is one access per table row. Derived from what the body
# actually performs, so the end-gate count cannot drift from the loops.
SIDEBAND_DEBUG_READBACK_ACCESSES = 2
# AVS_INTERRUPT is read four times (before the pair, after the pair, after the
# pointer-advancing AVS_READBACK, and after the write-1-clear) plus the one
# AVS_INTERRUPT_CLEAR write.
SIDEBAND_INTERRUPT_ACCESSES = 5
SIDEBAND_TOTAL_ACCESSES = (
    SIDEBAND_DEBUG_READBACK_ACCESSES
    + SIDEBAND_INTERRUPT_ACCESSES
    + len(SIDEBAND_OKAY_READS)
    + len(SIDEBAND_ERR_READS)
)


class smc_sideband_protocol_smoke_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        # Entry state: no interrupt is pending, so READBACK_UNDERFLOW_INT is 0
        # and any later 1 must have been raised by something this body did.
        await self.csr_read(
            "AVS_INTERRUPT_ENTRY",
            AVS_INTERRUPT,
            expected=AVS_INTERRUPT_NONE_PENDING,
        )

        # The two AVS_DEBUG_READBACK reads. Their data word is not compared (see
        # module docstring); what is asserted is that they returned the same word
        # AND that they left the readback pointer untouched, which the
        # AVS_INTERRUPT read below measures.
        dbg = await self.csr_read("AVS_DEBUG_READBACK", AVS_DEBUG_READBACK)
        dbg_again = await self.csr_read("AVS_DEBUG_READBACK_REREAD", AVS_DEBUG_READBACK)
        assert dbg_again == dbg, (
            f"AVS_DEBUG_READBACK @ 0x{AVS_DEBUG_READBACK:08x} is documented as a "
            f"non-destructive mirror, but two back-to-back reads returned "
            f"0x{dbg:08x} then 0x{dbg_again:08x} (readback FIFO pointer moved)"
        )
        # Exact expectation: still nothing pending. A DUT whose debug read did
        # advance/pop the readback pointer would have raised
        # READBACK_UNDERFLOW_INT here, because the readback FIFO is
        # empty in this scenario (no AVS_CMD was ever written -- AVS_FIFOS_STATUS
        # below value-compares that). The contrast leg further down proves this
        # flag can reach 1 over this same path, so this is not a stuck-at-0 pass.
        await self.csr_read(
            "AVS_INTERRUPT_AFTER_DEBUG_READBACK",
            AVS_INTERRUPT,
            expected=AVS_INTERRUPT_NONE_PENDING,
        )
        cocotb.log.info(
            "CHK-AVS-DEBUG-READBACK-NONDESTRUCTIVE: 0x%08x read twice -> "
            "0x%08X == 0x%08X and AVS_INTERRUPT @ 0x%08x still == 0x%08X, i.e. "
            "READBACK_UNDERFLOW_INT (bm 0x%02X) stayed clear: neither read "
            "touched the readback FIFO pointer (rdl:149-151 non-destructive "
            "mirror; rdl:299-303 defines the witness). Contrast leg below shows "
            "the same flag going to 1 on a pointer-advancing read.",
            AVS_DEBUG_READBACK,
            dbg,
            dbg_again,
            AVS_INTERRUPT,
            AVS_INTERRUPT_NONE_PENDING,
            AVS_READBACK_UNDERFLOW,
        )

        for name, addr, expected in SIDEBAND_OKAY_READS:
            await self.csr_read(name, addr, expected=expected)
            # csr_read passes ``expected`` to the scoreboard, which fails the run
            # on any rdata mismatch -- so reaching this line means the exact
            # expectation held.
            cocotb.log.info(
                "CHK-AVS-%s: 0x%08x resp=OKAY rdata == expected 0x%08X "
                "(from generated avsbus_controller.h)",
                name.replace("AVS_", "").replace("_", "-"),
                addr,
                expected,
            )

        for name, addr in SIDEBAND_ERR_READS:
            # AVS_READBACK is the register the RDL documents as
            # pointer-advancing ("Reading this register causes the AVS response
            # readback fifo pointer to advance"). Read on an empty FIFO it
            # returns rdata == 0 -- that half IS document-cited (memmap.adoc,
            # Address Alignment and Access Requirements: "a read of
            # `AVS_READBACK` while the readback FIFO is empty returns 0 without
            # popping") -- together with an AXI error response. The error
            # response is an integration behaviour of the SEP_IN path on an
            # empty-readback read, not a documented register property; it is
            # pinned so the leg cannot degrade into an OKAY or a wedge.
            # csr_read_decerr_zero asserts both halves.
            await self.csr_read_decerr_zero(name, addr)
            cocotb.log.info(
                "CHK-AVS-READBACK-EMPTY-FIFO-READ: 0x%08x resp=SLVERR/DECERR and "
                "rdata == 0 (rdata == 0 per memmap.adoc:95 'Empty FIFO, no "
                "response data'; the error response is this SEP_IN integration's "
                "empty-readback termination, NOT a document-cited property)",
                addr,
            )

        # Contrast / positive-control leg for the non-destructive property
        # above: the pointer-advancing read just issued must have raised exactly
        # READBACK_UNDERFLOW_INT ("an APB read on the AVS_READBACK reg occurred
        # when the readback fifo was empty"). Exact word, so a DUT that raised
        # nothing, or raised something else too, fails.
        await self.csr_read(
            "AVS_INTERRUPT_AFTER_READBACK",
            AVS_INTERRUPT,
            expected=AVS_READBACK_UNDERFLOW,
        )
        cocotb.log.info(
            "CHK-AVS-READBACK-POINTER-ADVANCE: AVS_READBACK read on the empty "
            "readback FIFO raised AVS_INTERRUPT == 0x%08X "
            "(READBACK_UNDERFLOW_INT only, rdl:299-303). This is the positive "
            "control that makes the two AVS_INTERRUPT == 0x%08X compares above "
            "fail-capable: the witness flag is alive at 1 on this DUT and this "
            "path, so 'debug read left it clear' is a measurement.",
            AVS_READBACK_UNDERFLOW,
            AVS_INTERRUPT_NONE_PENDING,
        )

        # Documented write-1 clear (AVS_INTERRUPT_CLEAR), and the register must
        # return to "no pending interrupts" -- which also restores the entry
        # state for any later scenario sharing this block.
        await self.csr_write(
            "AVS_INTERRUPT_CLEAR_UNDERFLOW",
            AVS_INTERRUPT_CLEAR,
            AVS_CLEAR_READBACK_UNDERFLOW,
        )
        await self.csr_read(
            "AVS_INTERRUPT_AFTER_CLEAR",
            AVS_INTERRUPT,
            expected=AVS_INTERRUPT_NONE_PENDING,
        )
        cocotb.log.info(
            "CHK-AVS-INTERRUPT-W1C: AVS_INTERRUPT_CLEAR @ 0x%08x <= 0x%08X "
            "cleared READBACK_UNDERFLOW_INT; AVS_INTERRUPT back to 0x%08X "
            "(rdl:422-426 CLEAR_READBACK_UNDERFLOW_INT)",
            AVS_INTERRUPT_CLEAR,
            AVS_CLEAR_READBACK_UNDERFLOW,
            AVS_INTERRUPT_NONE_PENDING,
        )

        # AVS_INTERRUPT_MASK write/read-back/restore. Placed LAST:
        # every AVS_INTERRUPT check above depends on the interrupt state being
        # untouched, and clearing a mask bit un-masks a real source into the
        # PLIC. Nothing is driven between the write and the restore, and the AVS
        # FSM is quiescent here (the same bench state in which
        # `check_sideband_observability` measures avs_irq=0 and the FSM in
        # IDLE), so the un-masked window is dead time.
        #
        # `avsbus_controller.rdl` gives AVS_INTERRUPT_MASK nine rw fields
        # with reset 0x1FF (all masked). The probe clears alternate bits so a
        # stuck-at-1 register cannot read it back, then 0x1FF is restored and
        # re-read.
        mask_probe = AVS_INTERRUPT_MASK_RESET & 0x0AA
        await self.csr_read(
            "AVS_INTERRUPT_MASK_RESET",
            AVS_INTERRUPT_MASK,
            expected=AVS_INTERRUPT_MASK_RESET,
        )
        await self.csr_write("AVS_INTERRUPT_MASK_WR", AVS_INTERRUPT_MASK, mask_probe)
        await self.csr_read("AVS_INTERRUPT_MASK_RB", AVS_INTERRUPT_MASK, expected=mask_probe)
        await self.csr_write(
            "AVS_INTERRUPT_MASK_RESTORE",
            AVS_INTERRUPT_MASK,
            AVS_INTERRUPT_MASK_RESET,
        )
        await self.csr_read(
            "AVS_INTERRUPT_MASK_RESTORE_RB",
            AVS_INTERRUPT_MASK,
            expected=AVS_INTERRUPT_MASK_RESET,
        )
        cocotb.log.info(
            "CHK-AVS-INTERRUPT-MASK: reset 0x%03X read back, probe 0x%03X "
            "written and read back, restored to 0x%03X -- nine rw mask fields "
            "proven live, un-masked only across dead time",
            AVS_INTERRUPT_MASK_RESET,
            mask_probe,
            AVS_INTERRUPT_MASK_RESET,
        )

        assert self.accesses == SIDEBAND_TOTAL_ACCESSES + 5, (
            f"sideband CSR precheck issued {self.accesses} accesses, expected "
            f"{SIDEBAND_TOTAL_ACCESSES + 5}"
        )
        # Every access above goes through csr_read / csr_write /
        # csr_read_decerr_zero and leaves ``allow_timeout`` False, so
        # SmcSysAxiDriver._timed_event raises on expiry and ``self.timeouts``
        # stays 0 on this path; the driver enforces the no-hang property and the
        # test publishes ``timeouts=None``.
