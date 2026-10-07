# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART/SPI/log-engine representative CSR precheck."""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import reg_field_pack

# Every expected value below is derived from the register definition and, for
# the modem-status pair, from the pad level this test drives.
#
#   UART_IIR=0x01, UART_LSR=0x60, UART_LOG_ENGINE_CTRL / LOG_ENGINE CTRL &
#   INTR_STATUS = 0: RDL reset constants (uart_16550_main.rdl / log_engine.rdl).
#
# UART_MSR expected values (spec-derived, see the MSR block below).
UART_MSR = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MSR_BASE_ADDR", 0)
UART_LOG_ENGINE_CTRL_CTRL = smc_indexed_addr(
    "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR", 0
)

# UART0 pad function enable: ``UART_LOG_ENGINE_CTRL.CTRL.UART_EN``.
UART_LOG_ENGINE_CTRL_UART_EN = reg_field_pack("UART_LOG_ENGINE_CTRL_CTRL_reg_t", uart_en=1)

# --- UART_MSR: field contract + the CTS pad level this test drives -----------
#
# EXPECTATION SOURCE (right-hand side of every compare below) -- the MSR field
# descriptions in ``hw/ip/uart/uart_16550/regs/uart_16550_main.rdl`` (reg MSR)
# and nothing else:
#   CTS  [4] "reflects the cts_ni input in the opposite polarity"
#   DSR  [5] "reflects the dsr_ni input in the opposite polarity"
#   RI   [6] "reflects the ri_ni  input in the opposite polarity"
#   DCD  [7] "reflects the dcd_ni input in the opposite polarity"
#   DCTS [0] "set when the CTS bit has changed since the last time this
#             register was read" (rclr)
#   DDSR [1] / DDCD [3]: same delta-since-last-read contract for DSR / DCD
#   TERI [2] "set when RI has changed from a 1 to a 0"
#
# DSR / RI / DCD (and their delta bits DDSR / TERI / DDCD) are outside every
# compare below. The integrator pin table
# (``doc/integrator/meta/ocah_gpio_table.csv``) pins only RX / TX / RTS / CTS
# for each UART, so no pad reaches ``dsr_ni`` / ``ri_ni`` / ``dcd_ni`` and this
# bench has no authority for their level other than the design itself. The
# compares are therefore masked to the CTS / DCTS bits this test drives
# (``MSR_LIVE_MASK``); the other six bits are logged, not asserted.
#
# CTS INPUT LEVEL -- driven by this test, because an undriven pad has no
# simulator-independent level: ``tb_top.sv`` puts a weak ``pullup`` on every pad
# so an undriven pad reads 1 where the simulator honours ``pullup``, and
# Verilator ignores ``pullup``. Pad 14 is therefore driven from the top-level
# ``tb_gpio_ext_drive_en`` / ``tb_gpio_ext_drive_value`` pins, the
# highest-precedence entry in tb_top's pad-injection mux, the same external
# pad-drive path the GPIO/I2C sequences use.
#
# PAD IDENTITY: pad 14 is UART[0].CTS per the integrator pin table
# ``doc/integrator/meta/ocah_gpio_table.csv`` (rendered by
# ``doc/integrator/meta/ocah_gpio_table.adoc`` in the integrator guide).
#
# STIMULUS PATH: the pad's UART function must be enabled before the pad can
# drive the UART's CTS input; ``UART_LOG_ENGINE_CTRL.CTRL.UART_EN`` is that
# enable (``uart_log_engine_ctrl.rdl``: "When set, the pad-mux downstream will
# be forced to accept UART traffic"). The register is read at its RDL reset 0x0
# before UART_EN = 1 is written.
MSR_DCTS = reg_field_pack("UART_16550_MAIN_MSR_reg_t", dcts=1)
MSR_CTS = reg_field_pack("UART_16550_MAIN_MSR_reg_t", cts=1)
# The bits every MSR compare is masked to: the two this test drives and reads.
MSR_LIVE_MASK = MSR_DCTS | MSR_CTS

# cts_ni driven 0  =>  CTS = ~0 = 1. First MSR read of the simulation:
# "changed since the last time this register was read" with no prior read and
# CTS asserted => the delta is reported => DCTS = 1.
MSR_FIRST_READ = MSR_DCTS | MSR_CTS  # 0x11
# Back-to-back second read: the first read is now "the last time this register
# was read" and CTS has not moved, so DCTS must have cleared.
MSR_SECOND_READ = MSR_CTS  # 0x10
# Settled words for each driven pad level (DCTS already consumed by the
# preceding read): pad 1 => cts_ni = 1 => CTS = 0; pad 0 => CTS = 1.
MSR_SETTLED = {0: MSR_CTS, 1: 0}
# The read on which a pad change first becomes visible: same CTS as above plus
# DCTS = 1, because CTS changed since the previous read.
MSR_TRANSITION = {0: MSR_DCTS | MSR_CTS, 1: MSR_DCTS}

# UART0 CTS pad index (see PAD IDENTITY above).
UART0_CTS_PAD = 14
# Bounded poll for a driven pad level to appear in MSR. There is no handshake to
# wait on (the pad is an asynchronous input crossing into the UART's clock
# domain), so completion is a bounded retry whose expiry is a hard failure
# ([TIMEOUT-MUST-FAIL]); each CSR read is hundreds of ns of sim time, so the
# bound sits far above the pad-to-MSR latency.
MSR_POLL_READS = 40

UART_LOG_READS = [
    ("UART_LOG_ENGINE_CTRL", UART_LOG_ENGINE_CTRL_CTRL, 0x0),
    (
        "UART_IIR",
        smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR", 0),
        0x1,
    ),
    (
        "UART_LSR",
        smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR", 0),
        0x0000_0060,
    ),
    (
        "LOG_ENGINE_CTRL",
        smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_CTRL_BASE_ADDR", 0),
        0x0,
    ),
    (
        "LOG_ENGINE_INTR_STATUS",
        smc_indexed_addr(
            "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_INTR_STATUS_BASE_ADDR", 0
        ),
        0x0,
    ),
]

# Non-poll accesses this body always issues: 5 RDL-reset reads + 1 UART_EN
# write + 2 back-to-back MSR reads + 2 x (>=1 transition read + 1 clear read)
# for the two pad toggles.
MIN_UART_LOG_ACCESSES = len(UART_LOG_READS) + 1 + 2 + 2 + 2


class smc_uart_spi_log_engine_test_seq(SmcCsrSeq):
    """Use UART/log-engine CSRs as the low-speed peripheral representative."""

    def __init__(self, name: str = "smc_uart_spi_log_engine_test_seq") -> None:
        super().__init__(name)
        self.msr_reads = 0

    def _drive_cts_pad(self, level: int) -> None:
        """Drive UART0 CTS pad 14 to ``level`` via the top-level TB pad pins."""
        dut = cocotb.top
        assert hasattr(dut, "tb_gpio_ext_drive_en"), (
            "tb_gpio_ext_drive_en is missing: this TB cannot drive the CTS pad, "
            "so the MSR CTS expectation would fall back to a pad default"
        )
        mask = 1 << UART0_CTS_PAD
        en = int(dut.tb_gpio_ext_drive_en.value) | mask
        val = int(dut.tb_gpio_ext_drive_value.value)
        val = (val | mask) if level else (val & ~mask)
        dut.tb_gpio_ext_drive_en.value = en
        dut.tb_gpio_ext_drive_value.value = val

    def _release_cts_pad(self) -> None:
        """Return pad 14 to the entry state ([NO-ORDER-DEPENDENCE])."""
        dut = cocotb.top
        mask = 1 << UART0_CTS_PAD
        dut.tb_gpio_ext_drive_en.value = int(dut.tb_gpio_ext_drive_en.value) & ~mask
        dut.tb_gpio_ext_drive_value.value = int(dut.tb_gpio_ext_drive_value.value) & ~mask

    async def _read_msr(self, name: str, expected: int | None = None) -> int:
        """Read UART_MSR and return its CTS / DCTS bits.

        ``expected`` is compared against the masked word, so the pass asserts
        nothing about DSR / RI / DCD or their delta bits. The unmasked word is
        logged on every read, so those bits stay visible without being asserted.
        """
        rdata = await self.csr_read(name, UART_MSR)
        self.msr_reads += 1
        live = rdata & MSR_LIVE_MASK
        cocotb.log.info(
            "%s: UART_MSR full word 0x%08x, CTS/DCTS bits 0x%02x, bits outside the "
            "compare 0x%08x (DSR/RI/DCD and their delta bits, logged only)",
            name,
            rdata,
            live,
            rdata & ~MSR_LIVE_MASK,
        )
        if expected is not None:
            assert live == expected, (
                f"{name}: UART_MSR CTS/DCTS bits 0x{live:02x} != expected "
                f"0x{expected:02x} (full word 0x{rdata:08x})"
            )
        return live

    async def _msr_follow_pad(self, level: int) -> int:
        """Drive pad 14 to ``level``, then prove MSR follows it exactly.

        Every read in the bounded poll carries an exact expectation:
          * before the change is visible: the settled word for the OLD level
            (DCTS already cleared by the previous read);
          * on the read where it becomes visible: that level's CTS plus
            DCTS = 1, i.e. the RDL "changed since the last read" contract;
          * the immediately following read: DCTS cleared, CTS unchanged.
        Returns the number of MSR reads issued. Raises if the driven level never
        appears within the bound.
        """
        old_settled = MSR_SETTLED[1 - level]
        transition = MSR_TRANSITION[level]
        settled = MSR_SETTLED[level]
        self._drive_cts_pad(level)
        reads = 0
        for i in range(MSR_POLL_READS):
            rdata = await self._read_msr(f"UART_MSR_PAD{level}_RD{i}")
            reads += 1
            if rdata == old_settled:
                # Change not visible yet; keep the old level's exact word.
                await ClockCycles(cocotb.top.clk_smc_i, 4)
                continue
            assert rdata == transition, (
                f"UART_MSR after driving CTS pad {UART0_CTS_PAD} to {level}: "
                f"read 0x{rdata:02x}, expected either the pre-change word "
                f"0x{old_settled:02x} or the transition word "
                f"0x{transition:02x} (CTS = ~cts_ni per the MSR field "
                f"description, DCTS = 1 for the change since the last read)"
            )
            cocotb.log.info(
                "CHK-UART-MSR-CTS-PAD%d: after this test drove CTS pad %d to "
                "%d, UART_MSR read 0x%02x == 0x%02x (CTS=%d = ~cts_ni, DCTS=1 "
                "for the change since the last read) on poll read %d",
                level,
                UART0_CTS_PAD,
                level,
                rdata,
                transition,
                1 - level,
                i,
            )
            follow = await self._read_msr(f"UART_MSR_PAD{level}_CLEARED", expected=settled)
            reads += 1
            cocotb.log.info(
                "CHK-UART-MSR-DELTA-CLEAR-PAD%d: next UART_MSR read = 0x%02x "
                "== 0x%02x -- DCTS cleared by the preceding read while CTS "
                "stayed at %d, as the rclr delta-since-last-read contract "
                "requires",
                level,
                follow,
                settled,
                1 - level,
            )
            return reads
        raise AssertionError(
            f"UART_MSR never reported CTS = {1 - level} after this test drove "
            f"CTS pad {UART0_CTS_PAD} to {level}: {MSR_POLL_READS} bounded "
            f"reads all returned the pre-change word 0x{old_settled:02x}. "
            f"Either the pad is not reaching uart_cts_ni (UART0 LSIO pad "
            f"function not enabled?) or the pin->MSR mapping is broken"
        )

    async def body(self) -> None:
        # RDL-reset reads first, so UART_LOG_ENGINE_CTRL is sampled at its reset
        # value (UART_EN = 0) BEFORE this sequence writes it. Nothing here
        # touches UART_MSR, so the first MSR read below is still the first read
        # of that register in the simulation -- which the DCTS contract needs.
        for name, addr, expected in UART_LOG_READS:
            rdata = await self.csr_read(name, addr, expected)
            cocotb.log.info(
                "CHK-UART-LOG-%s: SEP_IN AXI read @ 0x%08x returned OKAY "
                "rdata=0x%08x == RDL reset 0x%08x",
                name,
                addr,
                rdata,
                expected,
            )

        # Establish the CTS level as this test's own stimulus and route the pad
        # to the pin. Pad 14 is driven LOW before UART_EN: cts_ni then reads 0
        # both before and after the write, so enabling the pad function cannot
        # itself move CTS and the first MSR read needs no settling.
        self._drive_cts_pad(0)
        await self.csr_write(
            "UART_LOG_ENGINE_CTRL_UART_EN", UART_LOG_ENGINE_CTRL_CTRL, UART_LOG_ENGINE_CTRL_UART_EN
        )

        msr_first = await self._read_msr("UART_MSR", expected=MSR_FIRST_READ)
        cocotb.log.info(
            "CHK-UART-MSR-FIRST: UART_MSR @ 0x%08x CTS/DCTS bits = 0x%02x == "
            "DCTS|CTS 0x%02x (this test drives CTS pad %d low -> cts_ni=0 -> "
            "CTS=1; first read of this register -> DCTS=1; DSR/RI/DCD and "
            "their delta bits are masked out of the compare)",
            UART_MSR,
            msr_first,
            MSR_FIRST_READ,
            UART0_CTS_PAD,
        )

        msr_second = await self._read_msr("UART_MSR_RD2", expected=MSR_SECOND_READ)
        cocotb.log.info(
            "CHK-UART-MSR-DELTA-CLEAR: second UART_MSR read CTS/DCTS = 0x%02x == 0x%02x "
            "-- DCTS cleared by the preceding read while CTS stayed asserted, "
            "as the MSR delta-since-last-read contract requires",
            msr_second,
            MSR_SECOND_READ,
        )

        # Both polarities of the pin->MSR mapping, and DCTS set->clear in both
        # directions.
        try:
            await self._msr_follow_pad(1)
            await self._msr_follow_pad(0)
        finally:
            self._release_cts_pad()

        assert self.accesses >= MIN_UART_LOG_ACCESSES, (
            f"UART/log CSR precheck issued {self.accesses} accesses, fewer than "
            f"the {MIN_UART_LOG_ACCESSES} this body always performs"
        )
        assert self.msr_reads >= 6, (
            f"only {self.msr_reads} UART_MSR reads issued; the CTS/DCTS contract "
            f"needs at least 6 (2 back-to-back + 2 per pad toggle)"
        )
        cocotb.log.info(
            "CHK-UART-LOG-COUNT: %d SEP_IN AXI accesses value-checked "
            "(%d RDL-reset registers + 1 UART_EN write + %d UART_MSR reads "
            "across two test-driven CTS pad levels)",
            self.accesses,
            len(UART_LOG_READS),
            self.msr_reads,
        )
