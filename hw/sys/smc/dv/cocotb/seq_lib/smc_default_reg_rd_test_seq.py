# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Default register read smoke over the real SEP_IN AXI ingress port.

This is the OSS-safe slice of the default-reg-read flow: it reads
side-effect-free internal SMC CSRs through ``sep_axi_in_req_i`` and checks
that every selected address returns an OKAY AXI response **and** — wherever the
generated register map defines one — the exact reset value for that register.

Access-port identity: the test starts this sequence on ``env.sys_axi_agent``,
whose driver declares ``bus_prefix = "s_axi"`` / ``bus_name = "SEP_IN AXI"``
(``env/smc_sys_axi_agent.py``), and ``tb_top.sv`` wires the top-level
``s_axi_*`` pins into ``smc.sep_axi_in_req_i``. The SYS_IN port (``sys_axi_*``
-> ``sys_axi_in_req_i``) is driven by the separate ``env.sys_in_axi_agent``,
which this test never starts.

What that does and does not prove: every register read below lives inside
``smc_misc_wrap`` and is reached over the same internal register fabric from
either ingress port, so the reset-default proof holds regardless of which port
carried it. It gives NO coverage of the SYS_IN ingress port itself.

Addresses come from the generated PeakRDL map only (indexed
``SCRATCH_BASE_ADDR(idx)`` macros and per-register ``*_BASE_ADDR`` symbols in
``hw/sys/smc/regs/gen/c/smc_addr.h``); expected values come from
``smc_csr_field_catalog`` so the address and the value share one source.
"""

from __future__ import annotations

import cocotb
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_base_test_seq import smc_base_test_seq
from .smc_csr_field_catalog import SmcCsrAccessKind, catalog_entry

# (catalog name, generated address). The expected value is taken from the
# catalog entry returned by ``catalog_entry`` — no second copy here.
READABLE_REGS = [
    ("SCRATCH_COLD_0", smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 0)),
    ("SCRATCH_COLD_1", smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 1)),
    (
        "SCRATCH_COLD_WARM_0",
        smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_SCRATCH_BASE_ADDR", 0),
    ),
    ("CHIP_CONFIG_VERSION_LO", smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_LO_BASE_ADDR")),
    ("CHIP_CONFIG_VERSION_HI", smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_HI_BASE_ADDR")),
    ("CHIP_CONFIG_CHIP_ID", smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_CHIP_ID_BASE_ADDR")),
]

# Stimulus-derived floor for the value compares -- the ONE DUT-sensitive check
# this testcase performs ([NO-ZERO-ACTIVITY-PASS]).
#
# A LITERAL, not read from the catalog: a floor summed from the same
# ``catalog_entry(...).expected is not None`` predicate the read loop applies
# moves with the catalog, so a regression that dropped all six entries to
# ``expected=None`` would compare zero values and still pass as ``0 == 0``.
# ``tests/smc_default_reg_rd_test.py`` floors the same number a second time
# against the scoreboard's own independent ``sys_axi_value_checks_seen`` tally.
#
# All six READABLE_REGS entries must therefore carry a cataloged expected value;
# ``_read`` raises rather than skipping if one does not.
EXPECTED_VALUE_COMPARES = 6
assert EXPECTED_VALUE_COMPARES == len(READABLE_REGS), (
    "every READABLE_REGS entry must be value-compared; update "
    "EXPECTED_VALUE_COMPARES (and the floor in tests/smc_default_reg_rd_test.py) "
    "deliberately when the table changes"
)


class smc_default_reg_rd_test_seq(smc_base_test_seq):
    """Read a compact set of side-effect-free SMC CSRs."""

    def __init__(self, name: str = "smc_default_reg_rd_test_seq") -> None:
        super().__init__(name)
        self.reads = 0
        self.value_checks = 0

    async def _read(self, name: str, addr: int, expected: int, kind: SmcCsrAccessKind) -> None:
        # ``expected`` is non-optional: a catalog entry that carries no
        # expectation is a hard error here, not a silently decode-only read, so
        # a catalog regression cannot shrink the value-compare count.
        assert expected is not None, (
            f"{name} @ 0x{addr:08x}: smc_csr_field_catalog states no expected "
            f"value, but every register in this sweep must be value-compared "
            f"(see EXPECTED_VALUE_COMPARES)"
        )
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.expected = expected
        await self.start_item(item)
        await self.finish_item(item)
        self.reads += 1

        # Gate the evidence token on the mapped expectation, not on the read
        # having been issued: OKAY first, then the exact value where the
        # generated map defines one.
        #
        # Defence-in-depth guard, NOT this sequence's timeout contract: these
        # items leave ``allow_timeout`` False, so the driver already raises
        # AssertionError on expiry (env/smc_sys_axi_agent.py:148-167) and control
        # never reaches this line with ``timed_out`` True. [TIMEOUT-MUST-FAIL] is
        # satisfied one layer up; this only catches a future call site that turns
        # ``allow_timeout`` on and would otherwise fall through to a value
        # compare against untransferred data.
        assert not item.timed_out, f"{name} @ 0x{addr:08x}: SEP_IN AXI read never responded"
        assert item.resp_ok, (
            f"{name} @ 0x{addr:08x}: SEP_IN AXI read returned non-OKAY resp={item.resp_code}"
        )
        mask = (1 << (item.length * 8)) - 1
        got = item.rdata & mask
        exp = expected & mask
        assert got == exp, (
            f"{name} @ 0x{addr:08x}: default read 0x{got:08x}, expected 0x{exp:08x} ({kind.value})"
        )
        self.value_checks += 1
        cocotb.log.info(
            "CHK-DEFAULT-REG-VALUE: %s @ 0x%08x read OKAY and returned its "
            "mapped default 0x%08x (%s)",
            name,
            addr,
            exp,
            kind.value,
        )

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        for name, addr in READABLE_REGS:
            entry = catalog_entry(name, addr, writable=name.startswith("SCRATCH_"))
            await self._read(name, addr, entry.expected, entry.kind)
        # Read-count refactor guard: `reads` is bumped unconditionally by the
        # single path through the loop, so this only catches a future early exit.
        assert self.reads == len(READABLE_REGS), "default-reg read sweep did not run"
        # Value-compare floor. Unlike the line above this is NOT satisfied by
        # construction: `value_checks` is bumped only after a `got == exp`
        # compare actually ran, and EXPECTED_VALUE_COMPARES is an independent
        # literal, so a catalog regression that stopped supplying expectations
        # fails here instead of shrinking the expectation with it.
        # Note what min_csr_accesses in tests/smc_default_reg_rd_test.py
        # does and does not cover: it floors the number of READS, not the number
        # of value compares -- the compare floor is this assert plus the
        # scoreboard-sourced floor in that same test.
        assert self.value_checks == EXPECTED_VALUE_COMPARES, (
            f"default-reg value compares ran {self.value_checks} times, "
            f"expected {EXPECTED_VALUE_COMPARES}: the exact-value compare is "
            f"this testcase's only DUT-sensitive check, so a shortfall is a "
            f"failure, never a quiet decode-only pass"
        )
        cocotb.log.info(
            "CHK-DEFAULT-REG-SWEEP: %d/%d SMC CSR reads compared exactly against "
            "a cataloged default (floor %d, an independent literal); all reads "
            "OKAY. Every register in this sweep is value-compared -- there is no "
            "decode-only path.",
            self.value_checks,
            self.reads,
            EXPECTED_VALUE_COMPARES,
        )
