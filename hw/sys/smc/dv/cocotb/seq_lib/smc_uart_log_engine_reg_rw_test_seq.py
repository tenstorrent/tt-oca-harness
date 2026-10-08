# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART/log-engine register RW depth test over real SEP_IN AXI."""

from __future__ import annotations

from pathlib import Path

import cocotb

from .smc_addr_map import _field_mask, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

_UART0 = 0  # UART_LOG_ENGINE_WRAP idx

# --- Field masks from the generated register headers ---------------------
# The masked readback compares below check exactly the sw-writable field of each
# register; the masks come from the generated `*_bm` symbols
# ([EXACT-EXPECTATION] / [ADDRESS-FROM-AUTHORITATIVE-MAP]).
_REPO = Path(__file__).resolve().parents[6]
_UART_H = _REPO / "hw" / "ip" / "uart" / "uart_16550" / "regs" / "gen" / "c" / "uart_16550_main.h"
_UART_LOG_ENGINE_CTRL_H = (
    _REPO
    / "hw"
    / "ip"
    / "uart"
    / "uart_log_engine_wrap"
    / "regs"
    / "gen"
    / "c"
    / "uart_log_engine_ctrl.h"
)
_LOG_ENGINE_H = _REPO / "hw" / "ip" / "uart" / "log_engine" / "regs" / "gen" / "c" / "log_engine.h"
_LOG_ENGINE_ADDR_H = _LOG_ENGINE_H.with_name("log_engine_addr.h")

UART_LOG_ENGINE_CTRL_MASK = _field_mask(
    _UART_LOG_ENGINE_CTRL_H, "UART_LOG_ENGINE_CTRL__CTRL__UART_EN_bm"
)
UART_SCR_MASK = _field_mask(_UART_H, "UART_16550_MAIN__SCR__SCR_bm")
LOG_REGION_SIZE_MASK = _field_mask(_LOG_ENGINE_H, "LOG_ENGINE__LOG_REGION_SIZE__LOG_REGION_SIZE_bm")
LOG_REGION_ADDR_LO_MASK = _field_mask(
    _LOG_ENGINE_H, "LOG_ENGINE__LOG_REGION_ADDR__LOG_REGION_ADDR_LO_bm"
)
LOG_REGION_ADDR_HI_MASK = (
    _field_mask(_LOG_ENGINE_H, "LOG_ENGINE__LOG_REGION_ADDR__LOG_REGION_ADDR_HI_bm") >> 32
)
LOG_REGION_ADDR_RESERVED_MASK = (~LOG_REGION_ADDR_HI_MASK) & 0xFFFF_FFFF
# INTR_ENABLE's two fields in log_engine.h.
LOG_INTR_ENABLE_MASK = _field_mask(
    _LOG_ENGINE_H, "LOG_ENGINE__INTR_ENABLE__LOG_FETCH_ERR_bm"
) | _field_mask(_LOG_ENGINE_H, "LOG_ENGINE__INTR_ENABLE__LOG_WRITE_ERR_bm")
# Two further `sw = rw; hw = r` log-engine registers with reset 0 and no
# side-effect property in log_engine.rdl. `INTR_TEST` is NOT added: it is
# `sw = w` with `singlepulse`, so a written 1 does not stick and no
# write/read-back expectation is derivable for it.
LOG_WRITE_ADDR_MASK = _field_mask(_LOG_ENGINE_H, "LOG_ENGINE__LOG_WRITE_ADDR__LOG_WRITE_ADDR_bm")
# `LOG_CTRL` is outside the write sweep: its generated macro is doubly indexed
# (`..._LOG_CTRL_BASE_ADDR(wrap_idx, LOG_CTRL_idx)` in smc_addr.h) so
# `smc_indexed_addr` cannot resolve it, and a write trips an arbiter assumption
# on an unfinished log write.

# Every row below passes `expected=None`, and `csr_read` with `expected=None`
# books NO scoreboard value check (smc_csr_seq_utils.py) -- only `resp_ok` is
# asserted, so these reads check decode (an OKAY response) only.
UART_LOG_READS = [
    (
        "UART_LOG_ENGINE_CTRL",
        smc_indexed_addr(
            "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR", _UART0
        ),
        None,
    ),
    (
        "UART0_IIR",
        smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR", _UART0),
        None,
    ),
    (
        "UART0_LSR",
        smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR", _UART0),
        None,
    ),
    (
        "UART0_MSR",
        smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MSR_BASE_ADDR", _UART0),
        None,
    ),
    (
        "UART0_SCR",
        smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_SCR_BASE_ADDR", _UART0),
        None,
    ),
    (
        "LOG_ENGINE_CTRL",
        smc_indexed_addr(
            "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_CTRL_BASE_ADDR", _UART0
        ),
        None,
    ),
    (
        "LOG_ENGINE_REGION_SIZE",
        smc_indexed_addr(
            "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_REGION_SIZE_BASE_ADDR",
            _UART0,
        ),
        None,
    ),
    (
        "LOG_ENGINE_REGION_ADDR",
        smc_indexed_addr(
            "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_REGION_ADDR_BASE_ADDR",
            _UART0,
        ),
        None,
    ),
    (
        "LOG_ENGINE_INTR_ENABLE",
        smc_indexed_addr(
            "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_INTR_ENABLE_BASE_ADDR", _UART0
        ),
        None,
    ),
    (
        "LOG_ENGINE_LOG_CTRL_0",
        smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR", _UART0)
        + smc_indexed_addr("LOG_ENGINE_LOG_CTRL_BASE_ADDR", 0, _LOG_ENGINE_ADDR_H),
        None,
    ),
]

# LOG_ENGINE_LOG_CTRL_0 is READ-only-swept (see UART_LOG_READS)
# and NOT part of the write/restore sweep (arbiter assume on unfinished log write).
UART_LOG_WRITES = [
    (
        "UART_LOG_ENGINE_CTRL",
        smc_indexed_addr(
            "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR", _UART0
        ),
        UART_LOG_ENGINE_CTRL_MASK,
        UART_LOG_ENGINE_CTRL_MASK,
    ),
    (
        "UART0_SCR",
        smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_SCR_BASE_ADDR", _UART0),
        0x5A,
        UART_SCR_MASK,
    ),
    (
        "LOG_ENGINE_REGION_SIZE",
        smc_indexed_addr(
            "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_REGION_SIZE_BASE_ADDR",
            _UART0,
        ),
        0x0000_1000,
        LOG_REGION_SIZE_MASK,
    ),
    (
        "LOG_ENGINE_REGION_ADDR",
        smc_indexed_addr(
            "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_REGION_ADDR_BASE_ADDR",
            _UART0,
        ),
        0x0000_2000,
        LOG_REGION_ADDR_LO_MASK,
    ),
    (
        "LOG_ENGINE_REGION_ADDR_HI",
        smc_indexed_addr(
            "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_REGION_ADDR_BASE_ADDR",
            _UART0,
        )
        + 4,
        0xFF5A_A5A5,
        LOG_REGION_ADDR_HI_MASK,
    ),
    (
        "LOG_ENGINE_INTR_ENABLE",
        smc_indexed_addr(
            "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_INTR_ENABLE_BASE_ADDR", _UART0
        ),
        LOG_INTR_ENABLE_MASK,
        LOG_INTR_ENABLE_MASK,
    ),
    (
        "LOG_ENGINE_LOG_WRITE_ADDR",
        smc_indexed_addr(
            "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_WRITE_ADDR_BASE_ADDR", _UART0
        ),
        0x5A5A_A5A5 & LOG_WRITE_ADDR_MASK,
        LOG_WRITE_ADDR_MASK,
    ),
]

# Fail-capable floors for this scenario, written out here and referenced ONLY by
# the closing gate / the testcase-level protocol-VIP record. They are not
# recomputed from the two tables the body walks: a floor derived from the same
# tables moves with the stimulus and can never catch a sweep that stopped short.
UART_LOG_MIN_CSR_ACCESSES = 45  # 10 reads + 7 registers x (save, write, rb,
# restore, restore-rb)
# Masked read-back compares this scenario must have PERFORMED AND PASSED: one
# after each write, one after each restore.
UART_LOG_EXPECTED_COMPARES = 14


class smc_uart_log_engine_reg_rw_test_seq(SmcCsrSeq):
    """UART/log-engine register RW sweep: decode reads, then save/write/readback/restore."""

    def __init__(self, name: str = "smc_uart_log_engine_reg_rw_test_seq") -> None:
        super().__init__(name)
        # Incremented only on the success side of a masked compare, so it counts
        # checks that PASSED rather than loop iterations.
        self.compares_passed = 0

    async def body(self) -> None:
        await self.csr_read_many(UART_LOG_READS)

        original = []
        for name, addr, pattern, mask in UART_LOG_WRITES:
            old_value = await self.csr_read(f"{name}_SAVE", addr)
            original.append((name, addr, old_value, mask))
            await self.csr_write(name, addr, pattern)
            got = await self.csr_read(f"{name}_READBACK", addr)
            assert (got & mask) == (pattern & mask), (
                f"{name} readback 0x{got:x} does not match 0x{pattern:x} mask 0x{mask:x}"
            )
            if name == "LOG_ENGINE_REGION_ADDR_HI":
                assert (got & LOG_REGION_ADDR_RESERVED_MASK) == 0, (
                    f"{name} reserved bits read nonzero after write: 0x{got:x}"
                )
            self.compares_passed += 1
            cocotb.log.info(
                "CHK-UART-LOG-ENGINE-REG-RW: %s @0x%08x wrote 0x%08x, read back "
                "0x%08x; masked with the generated field mask 0x%08x both sides "
                "are 0x%08x",
                name,
                addr,
                pattern,
                got,
                mask,
                pattern & mask,
            )

        for name, addr, value, mask in reversed(original):
            await self.csr_write(f"{name}_RESTORE", addr, value)
            got = await self.csr_read(f"{name}_RESTORE_READBACK", addr)
            assert (got & mask) == (value & mask), (
                f"{name} restore got 0x{got:x}, expected 0x{value:x} mask 0x{mask:x}"
            )
            if name == "LOG_ENGINE_REGION_ADDR_HI":
                assert (got & LOG_REGION_ADDR_RESERVED_MASK) == 0, (
                    f"{name} reserved bits read nonzero after restore: 0x{got:x}"
                )
            self.compares_passed += 1
            cocotb.log.info(
                "CHK-UART-LOG-ENGINE-REG-RESTORE: %s @0x%08x restored to the "
                "value saved before the write 0x%08x, read back 0x%08x; masked "
                "with 0x%08x both sides are 0x%08x",
                name,
                addr,
                value,
                got,
                mask,
                value & mask,
            )

        self.assert_all_reachable(UART_LOG_MIN_CSR_ACCESSES, "uart_log_engine_rw")
        assert self.compares_passed == UART_LOG_EXPECTED_COMPARES, (
            f"uart_log_engine_rw: {self.compares_passed} masked read-back "
            f"compare(s) passed, expected {UART_LOG_EXPECTED_COMPARES} "
            f"(one write readback and one restore readback for each of "
            f"{[entry[0] for entry in UART_LOG_WRITES]})"
        )
