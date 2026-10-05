# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Mailbox CSR and IRQ-control smoke over real SYS AXI.

Every address and bit on the proof path is imported by symbol from the
generated PeakRDL headers (``smc_addr.h`` for the register bases,
``smc_base_config.h`` for the clock-gate enable, ``axil_mailbox_smc_wrap.h``
for the mailbox field masks). A regenerated map therefore moves this sequence
with it instead of silently retargeting a still-passing decode smoke
([ADDRESS-FROM-AUTHORITATIVE-MAP]).
"""

from __future__ import annotations

import cocotb
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import _REPO, _field_mask, smc_addr
from .smc_base_test_seq import smc_base_test_seq

# smc_addr_map.py exposes no generic accessor for these two generated headers,
# so the module-level parser is reused here rather than a second offset table.
_SMC_BASE_CFG_H = (
    _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "smc_base_config.h"
)
_AXIL_MAILBOX_H = (
    _REPO / "hw" / "ip" / "axi_lite_mailbox_unit" / "regs" / "gen" / "c" / "axil_mailbox_smc_wrap.h"
)

_CPU_CTRL_H = _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "cpu_ctrl.h"

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
MAILBOX_CG_EN = _field_mask(
    _SMC_BASE_CFG_H, "SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__MAILBOX_CG_EN_bm"
)

#: MailboxDepth of the SMC integration, from the peripheral parameter table in
#: `hw/sys/smc/doc/periphs.adoc` (SMC Peripheral Parameter Overrides: Mailbox
#: `MailboxDepth`, IP default 8, SMC value 2). The threshold clamp below is
#: computed from this value; the depth CPU_CTRL.SMC_ATTRIBUTES publishes to
#: software is compared against it, not used in its place.
MAILBOX_DEPTH = 2
SMC_ATTRIBUTES = smc_addr("SMC_TOP_SMC_CPU_CTRL_SMC_ATTRIBUTES_BASE_ADDR")
MAILBOX_DEPTH_BM = _field_mask(_CPU_CTRL_H, "CPU_CTRL__SMC_ATTRIBUTES__MAILBOX_DEPTH_bm")
MAILBOX_DEPTH_BP = _field_mask(_CPU_CTRL_H, "CPU_CTRL__SMC_ATTRIBUTES__MAILBOX_DEPTH_bp")

MAILBOX_STATUS = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_STATUS_BASE_ADDR")
MAILBOX_ERROR_FLAGS = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_ERROR_FLAGS_BASE_ADDR")
MAILBOX_WIRQT = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_WIRQT_BASE_ADDR")
MAILBOX_RIRQT = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_RIRQT_BASE_ADDR")
MAILBOX_IRQEN = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_IRQEN_BASE_ADDR")

# Idle STATUS of an untouched mailbox, stated per field from the generated
# header instead of a magic literal ([EXACT-EXPECTATION]): the read FIFO is
# empty (``EMPTY`` is defined as "1: Data is not available to read" in
# axil_mailbox.rdl) and FULL / WRITE_LEVEL_ABOVE_THRESH / READ_LEVEL_ABOVE_THRESH
# are all 0, as is the rest of the 64-bit read-only register.
MAILBOX_STATUS_IDLE = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__STATUS__EMPTY_bm")
# ERROR_FLAGS: no read-from-empty / write-to-full has been attempted yet, so
# both sticky flags (READ_ERROR, WRITE_ERROR) must still be clear.
MAILBOX_ERROR_FLAGS_IDLE = 0

# IRQEN is a plain rw enable register (eirq/rtirq/wtirq), so its readback is an
# exact mirror of what was written.
#
# WIRQT / RIRQT are threshold registers with a SPEC-defined clamp: "When a value
# larger than or equal to the MailboxDepth parameter is written to this register,
# it gets reduced to MailboxDepth - 1" (axil_mailbox register spec, WIRQT/RIRQT
# field descriptions -- regs/axil_mailbox.rdl:85,95 and the generated
# regs/gen/adoc/axil_mailbox_smc_wrap.adoc:59,67; the depth parameter itself is
# documented in hw/ip/axi_lite_mailbox_unit/doc/architecture.adoc). So the exact
# readback is `min(written, MAILBOX_DEPTH - 1)` -- a stated exact expectation
# that an all-zero dead register fails ([EXACT-EXPECTATION]). Their
# restore-to-0 leg is exact either way (0 is always in range).
CLAMPED_THRESHOLD = "clamped-to-depth"


def clamped_threshold(written: int, depth: int) -> int:
    """SPEC clamp of a WIRQT/RIRQT write for a mailbox of ``depth`` entries."""
    return written if written < depth else depth - 1


IRQEN_PATTERN = (
    _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__IRQEN__EIRQ_bm")
    | _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__IRQEN__RTIRQ_bm")
    | _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__IRQEN__WTIRQ_bm")
)

WRITE_READBACK = [
    ("WIRQT", MAILBOX_WIRQT, 0x5, CLAMPED_THRESHOLD),
    ("RIRQT", MAILBOX_RIRQT, 0x6, CLAMPED_THRESHOLD),
    ("IRQEN", MAILBOX_IRQEN, IRQEN_PATTERN, IRQEN_PATTERN),
]


# Directed, non-polling access count of `body()`; the callers' protocol-VIP
# stimulus floors are minima below this.
EXPECTED_ACCESSES = 24


class smc_mailbox_irq_test_seq(smc_base_test_seq):
    """Exercise mailbox status and IRQ-control registers."""

    def __init__(self, name: str = "smc_mailbox_irq_test_seq") -> None:
        super().__init__(name)
        self.clock_gate_value: int = 0
        self.accesses = 0

    async def _read(self, name: str, addr: int, expected: int | None = None) -> int:
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 8
        item.expected = expected
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        return item.rdata

    async def _write(self, name: str, addr: int, data: int) -> None:
        item = SmcSysAxiItem(f"wr_{name}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = 8
        item.wdata = data
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1

    async def body(self) -> None:
        self.clock_gate_value = await self._read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        enabled = self.clock_gate_value | MAILBOX_CG_EN
        await self._write("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL, enabled)
        await self._read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL, expected=enabled)

        # Exact idle expectations: a non-idle STATUS or any sticky error flag on
        # an untouched mailbox fails in the scoreboard value compare instead
        # of only proving the access returned OKAY.
        await self._read("MAILBOX_STATUS", MAILBOX_STATUS, expected=MAILBOX_STATUS_IDLE)
        await self._read(
            "MAILBOX_ERROR_FLAGS", MAILBOX_ERROR_FLAGS, expected=MAILBOX_ERROR_FLAGS_IDLE
        )

        # The depth the DUT publishes must be the documented integration value;
        # the clamp expectation is computed from the documented value.
        attrs = await self._read("SMC_ATTRIBUTES", SMC_ATTRIBUTES)
        published_depth = (attrs & MAILBOX_DEPTH_BM) >> MAILBOX_DEPTH_BP
        assert published_depth == MAILBOX_DEPTH, (
            f"CPU_CTRL.SMC_ATTRIBUTES.MAILBOX_DEPTH reads {published_depth} "
            f"(SMC_ATTRIBUTES=0x{attrs:x}); the SMC peripheral parameter table gives "
            f"MailboxDepth={MAILBOX_DEPTH}"
        )
        depth = MAILBOX_DEPTH

        clamped: list[tuple[str, int, int]] = []
        for name, addr, pattern, readback in WRITE_READBACK:
            if readback == CLAMPED_THRESHOLD:
                expected = clamped_threshold(pattern, depth)
                clamped.append((name, pattern, expected))
            else:
                expected = readback
            await self._write(name, addr, pattern)
            await self._read(name, addr, expected=expected)
        cocotb.log.info(
            "CHK-MAILBOX-IRQT-CLAMP: MailboxDepth=%d from the SMC peripheral parameter "
            "table, and CPU_CTRL.SMC_ATTRIBUTES publishes %d; %s each read back the SPEC "
            "clamp min(written, depth-1) exactly",
            depth,
            published_depth,
            ", ".join(f"{n} (wrote 0x{w:x}, expected 0x{e:x})" for n, w, e in clamped),
        )

        # In-range leg. Every threshold write above is >= depth, so all of them
        # clamp, and a register that returned depth-1 for any write -- or
        # ignored writes entirely -- satisfied them all. Writing depth-1, the
        # largest value the SPEC does NOT clamp, must read back unchanged.
        in_range = depth - 1
        for name, addr, _pattern, readback in WRITE_READBACK:
            if readback != CLAMPED_THRESHOLD:
                continue
            await self._write(f"{name}_IN_RANGE", addr, in_range)
            await self._read(f"{name}_IN_RANGE", addr, expected=in_range)
        cocotb.log.info(
            "CHK-MAILBOX-IRQT-IN-RANGE: WIRQT/RIRQT took 0x%x (depth-1, the "
            "largest unclamped value) back exactly, so the clamp above is a "
            "clamp and not a register stuck at depth-1",
            in_range,
        )

        for name, addr, _pattern, _readback in reversed(WRITE_READBACK):
            await self._write(f"{name}_RESTORE", addr, 0)
            await self._read(f"{name}_RESTORE", addr, expected=0)

        await self._write("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, self.clock_gate_value)
        await self._read(
            "CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, expected=self.clock_gate_value
        )
        # 19 mailbox/clock-gate accesses, the SMC_ATTRIBUTES read compared with
        # the documented depth, and the two in-range write/readback pairs.
        assert self.accesses == EXPECTED_ACCESSES, (
            f"mailbox CSR access sequence issued {self.accesses} accesses, "
            f"expected {EXPECTED_ACCESSES}"
        )
