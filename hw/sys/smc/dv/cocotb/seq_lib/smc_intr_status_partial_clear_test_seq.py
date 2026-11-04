# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_R5_001 ANCHOR: smc_intr_status_partial_clear_test
# DV-TESTCASE-CONTRACT-REVISION: 1 RECORD-SHA256: 2c5cab6ee3105067d2e928d1ca44ed1353f478deba6b19e22d927ece1209f4bb
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_COV_R5_VPLAN_DETAIL.md @ artifact_revision 1 ENV: cocotb
"""Write-one-to-clear status registers cleared a few bits at a time.

Three blocks carry an interrupt status register whose bits software raises
through the matching `INTR_TEST` register and clears by writing a one back:
the I2C `INTR_STATE`, the log engine `INTR_STATUS` and the telemetry receiver
`INTR_STATUS`.

This leaf drives the half of that contract in which a set bit that a write
carries a zero over *stays* set. On each instance of each of the three registers it

* reads the register and requires it clear, so every bit it goes on to see set
  is one this sequence raised;
* writes the event bits of `INTR_TEST` and requires the status register to
  report exactly those raised. Only the `read-write` fields take part: a status
  register also carries `read-only` level bits that hardware drives from a
  condition -- the I2C FIFO thresholds, the stretch and halt indications -- and
  a write cannot clear one of those while its condition holds;
* writes back **half** of the raised bits, and requires precisely those to have
  gone and the other half to still be set -- the write carried a zero over
  them, and a `oneToClear` field holds its value against a zero. Where a
  register has only one clearable bit that write carries no bits at all, which
  puts the same contract to the same test;
* writes the remaining half and requires the register to read clear again.

The two halves are alternating bits of the mask, so neither is a contiguous run
that a byte-granular decode could clear by accident, and the sequence fails if
the half that has to survive the write is empty.

Two further legs then run on I2C instances 1 and 2 only, with every expected
word taken from the I2C register reference (`i2c.adoc`, the 13 `RW1C` fields
of `INTR_STATE` and the 13 `W1P` fields of `INTR_TEST`):

* a swapped pass that writes the second half first, so the half the first pass
  cleared at once is the half held set against a zero here. Across both passes
  each of the 13 clearable bits is held once and cleared once per instance;
* a single-source walk that raises each `W1P` source alone, requires exactly
  that bit on the written instance and nothing on the other, and clears it.

Before any of it the I2C peripheral clock is ungated and instances 1 and 2 are
read at their reset word, and the leaf prints an ordered fence over all five
terms.

Raising a status bit through `INTR_TEST` is the same mechanism
`smc_i2c_intr_reg_sweep_test` already uses, and nothing here leaves a bit set:
each register ends the leg reading clear, which is its reset.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time

from .smc_addr_map import CLOCK_GATE_CONTROL, I2C_CG_EN
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_regblock_field_sweep_utils import RegInstance, reg_instances

_I2C = "SMC_TOP_SMC_I2C_WRAP_I2C_"
_WRAP = "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_"
_TELEMETRY = "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_"


def _i2c_spec(register: str) -> tuple[str, str, str, str]:
    return (
        f"smc_i2c_wrap/i2c/{register}",
        f"{_I2C}{register}_BASE_ADDR",
        f"{_I2C}{register}_NUM",
        f"SMC_I2C_WRAP_I2C_{{index}}__{register}_REG_ADDR",
    )


def _log_engine_spec(register: str) -> tuple[str, str, str, str]:
    return (
        f"smc_uart_wrap/uart_log_engine_wrap/log_engine/{register}",
        f"{_WRAP}LOG_ENGINE_{register}_BASE_ADDR",
        f"{_WRAP}LOG_ENGINE_{register}_NUM",
        f"SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_{{index}}__LOG_ENGINE_{register}_REG_ADDR",
    )


def _telemetry_spec(register: str) -> tuple[str, str, str, str]:
    return (
        f"smc_telemetry_receiver_wrap/telemetry_receiver/{register}",
        f"{_TELEMETRY}{register}_BASE_ADDR",
        f"{_TELEMETRY}{register}_NUM",
        f"SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_{{index}}__{register}_REG_ADDR",
    )


# Each entry is a block name, the status register spec and the INTR_TEST spec
# that raises its bits.
_BLOCKS: tuple[tuple[str, tuple[str, str, str, str], tuple[str, str, str, str]], ...] = (
    ("i2c", _i2c_spec("INTR_STATE"), _i2c_spec("INTR_TEST")),
    ("log_engine", _log_engine_spec("INTR_STATUS"), _log_engine_spec("INTR_TEST")),
    ("telemetry", _telemetry_spec("INTR_STATUS"), _telemetry_spec("INTR_TEST")),
)

# Accesses one register instance costs: the idle read, the INTR_TEST write and
# the raised read, the partial clear and its read, the rest and its read.
_ACCESSES_PER_INSTANCE = 7


# I2C INTR_STATE / INTR_TEST from the I2C register reference: the 13 RW1C event
# fields (i2c.adoc:56-94) are the 13 W1P sources of INTR_TEST (i2c.adoc:139-153).
I2C_INTR_SOURCES: tuple[tuple[int, str], ...] = (
    (3, "RX_OVERFLOW"),
    (5, "SCL_INTERFERENCE"),
    (6, "SDA_INTERFERENCE"),
    (7, "STRETCH_TIMEOUT"),
    (8, "SDA_UNSTABLE"),
    (9, "CMD_COMPLETE"),
    (13, "UNEXP_STOP"),
    (14, "HOST_TIMEOUT"),
    (15, "SMBALERT"),
    (16, "CONTROLLER_TX_FIFO_ERROR"),
    (17, "CONTROLLER_RX_FIFO_ERROR"),
    (18, "TARGET_TX_FIFO_ERROR"),
    (19, "TARGET_RX_FIFO_ERROR"),
)
I2C_RW1C_MASK = 0x000FE3E8
I2C_FIRST_HALF = 0x000AA148
I2C_SECOND_HALF = 0x000542A0
SWAP_INSTANCES = (1, 2)

FENCE_ORDER = ["SETUP", "EXISTING_PASS", "SWAP_PASS", "SINGLE_I2C1", "SINGLE_I2C2"]
# Each checker line prints once, before the fence term that closes its leg.
CHECKER_BEFORE = {
    "CHK-INTR-STATUS-PARTIAL-CLEAR": "EXISTING_PASS",
    "CHK-I2C12-W1C-SWAP-HOLD": "SWAP_PASS",
    "CHK-I2C1-INTR-TEST-SINGLE": "SINGLE_I2C1",
    "CHK-I2C2-INTR-TEST-SINGLE": "SINGLE_I2C2",
}


def _alternating(mask: int) -> tuple[int, int]:
    """Split a mask into two interleaved halves, lowest set bit first."""
    first = 0
    second = 0
    for index, bit in enumerate(b for b in range(mask.bit_length()) if mask >> b & 1):
        if index % 2:
            second |= 1 << bit
        else:
            first |= 1 << bit
    return first, second


class smc_intr_status_partial_clear_test_seq(SmcCsrSeq):
    """Clear write-one-to-clear status bits a few at a time, not all at once."""

    def __init__(self, name: str = "smc_intr_status_partial_clear_test_seq") -> None:
        super().__init__(name)
        self.registers = 0
        self.bits_held = 0
        # Per I2C instance, the bits a pass held set against a written zero.
        self.i2c_held: dict[int, int] = {}
        self.stamps: list[tuple[str, int, int, int]] = []
        self.chk_lines: list[tuple[str, int]] = []
        self._term_start = 0
        self._reads = 0

    async def csr_read(
        self, name: str, addr: int, expected: int | None = None, length: int = 4, prot: int = 0
    ) -> int:
        self._reads += 1
        return await super().csr_read(name, addr, expected, length, prot)

    def _stamp(self, term: str, reads: int) -> None:
        accesses = self.accesses - self._term_start
        self._term_start = self.accesses
        now = int(get_sim_time("ps"))
        assert accesses > 0 and reads > 0, f"fence term {term} issued no accesses"
        self.stamps.append((term, now, accesses, reads))
        cocotb.log.info("FENCE %s @ %dps accesses=%d reads=%d", term, now, accesses, reads)

    def _chk(self, name: str, fmt: str, *args) -> None:
        cocotb.log.info(f"{name}: {fmt}", *args)
        self.chk_lines.append((name, len(self.stamps)))

    @staticmethod
    def _clearable(status: RegInstance) -> int:
        """The `oneToClear` event bits, which the generated map marks read-write.

        A status register mixes two kinds of field. The event bits are
        `read-write`: hardware sets them, software clears them by writing a
        one, and they hold their value otherwise -- those are the ones this
        leaf is about. The rest are `read-only` level bits the hardware drives
        from a condition, such as the I2C FIFO thresholds and the stretch and
        halt indications; a write cannot clear those while their condition
        holds, so they are excluded here rather than expected to go.
        """
        mask = 0
        for field in status.reg.fields:
            if field.access == "read-write":
                mask |= field.mask
        return mask

    async def _leg(self, block: str, status: RegInstance, test: RegInstance) -> None:
        common = self._clearable(status) & test.reg.declared_mask
        assert common, (
            f"{block} [{status.label}]: the status register and INTR_TEST declare no field "
            f"in common, so nothing here could raise a bit to clear"
        )
        first, second = _alternating(common)
        if not second:
            # A single clearable bit cannot be split. The contract is the same
            # one either way -- a `oneToClear` field holds its value against a
            # zero -- so the write that has to leave it set carries no bits at
            # all instead of the other half.
            first, second = 0, common
        assert second, (
            f"{block} [{status.label}]: the clearable mask 0x{common:x} is empty, so there "
            f"is nothing for a partial clear to hold"
        )

        idle = await self.csr_read(f"{block}{status.index}_STATUS_IDLE", status.addr)
        assert idle & common == 0, (
            f"{block} [{status.label}]: reads 0x{idle:x} before this sequence raised "
            f"anything; every bit it goes on to clear has to be one it raised itself"
        )

        await self.csr_write(f"{block}{status.index}_INTR_TEST", test.addr, common)
        raised = await self.csr_read(f"{block}{status.index}_STATUS_RAISED", status.addr)
        assert raised & common == common, (
            f"{block} [{status.label}]: reads 0x{raised:x} after INTR_TEST was written with "
            f"0x{common:x}; every one of those bits has to be set"
        )

        await self.csr_write(f"{block}{status.index}_CLEAR_FIRST", status.addr, first)
        held = await self.csr_read(f"{block}{status.index}_STATUS_HELD", status.addr)
        assert held & first == 0, (
            f"{block} [{status.label}]: reads 0x{held:x} after a write of 0x{first:x}; a "
            f"`oneToClear` field written with a one has to go"
        )
        assert held & second == second, (
            f"{block} [{status.label}]: reads 0x{held:x} after a write of 0x{first:x}, "
            f"which carried a zero over 0x{second:x}; a `oneToClear` field holds its value "
            f"against a zero, so those bits have to still be set"
        )
        self.bits_held += bin(second).count("1")
        if block == "i2c":
            self.i2c_held[status.index] = self.i2c_held.get(status.index, 0) | (held & second)

        await self.csr_write(f"{block}{status.index}_CLEAR_REST", status.addr, second)
        cleared = await self.csr_read(f"{block}{status.index}_STATUS_CLEARED", status.addr)
        assert cleared & common == 0, (
            f"{block} [{status.label}]: reads 0x{cleared:x} after both halves were written "
            f"back; the register has to end the leg at its reset"
        )
        self.registers += 1

    def _reads_since(self, mark: int) -> int:
        return self._reads - mark

    async def _setup(self, status: dict[int, RegInstance], test: dict[int, RegInstance]) -> None:
        """Ungate the I2C clock and read instances 1 and 2 at their reset word."""
        self._term_start = self.accesses
        mark = self._reads
        for idx in SWAP_INSTANCES:
            assert idx in status and idx in test, (
                f"the generated map declares no I2C{idx} INTR_STATE / INTR_TEST"
            )
            common = self._clearable(status[idx]) & test[idx].reg.declared_mask
            assert common == I2C_RW1C_MASK, (
                f"I2C{idx}: the generated map's clearable INTR_STATE / INTR_TEST mask is "
                f"0x{common:08x}; the I2C register reference names the 13 RW1C / W1P fields "
                f"0x{I2C_RW1C_MASK:08x}"
            )
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        for idx in SWAP_INSTANCES:
            got = await self.csr_read(f"I2C{idx}_INTR_STATE_RESET", status[idx].addr)
            assert got == 0, (
                f"I2C{idx} INTR_STATE reads 0x{got:08x} at setup; every field resets 0x0 and "
                f"no status condition is true with the block idle"
            )
        self._stamp("SETUP", self._reads_since(mark))

    async def _swap_pass(
        self, status: dict[int, RegInstance], test: dict[int, RegInstance]
    ) -> None:
        """Second half first: the bits the existing pass cleared at once are held here."""
        mark = self._reads
        words: dict[int, tuple[int, int, int]] = {}
        for idx in SWAP_INSTANCES:
            assert idx in self.i2c_held, f"the existing pass did not run on I2C{idx} first"
            addr = status[idx].addr
            await self.csr_write(f"I2C{idx}_SWAP_INTR_TEST", test[idx].addr, I2C_RW1C_MASK)
            raised = await self.csr_read(f"I2C{idx}_SWAP_RAISED", addr)
            assert raised == I2C_RW1C_MASK, (
                f"I2C{idx} INTR_STATE reads 0x{raised:08x} after INTR_TEST "
                f"0x{I2C_RW1C_MASK:08x}; expected exactly 0x{I2C_RW1C_MASK:08x}"
            )
            await self.csr_write(f"I2C{idx}_SWAP_CLEAR_SECOND", addr, I2C_SECOND_HALF)
            held = await self.csr_read(f"I2C{idx}_SWAP_HELD", addr)
            assert held == I2C_FIRST_HALF, (
                f"I2C{idx} INTR_STATE reads 0x{held:08x} after the written "
                f"0x{I2C_SECOND_HALF:08x}; the bits written 0 hold and the bits written 1 "
                f"clear, so expected exactly 0x{I2C_FIRST_HALF:08x}"
            )
            await self.csr_write(f"I2C{idx}_SWAP_CLEAR_FIRST", addr, I2C_FIRST_HALF)
            cleared = await self.csr_read(f"I2C{idx}_SWAP_CLEARED", addr)
            assert cleared == 0, (
                f"I2C{idx} INTR_STATE reads 0x{cleared:08x} after the written "
                f"0x{I2C_FIRST_HALF:08x}; expected 0x00000000"
            )
            self.i2c_held[idx] |= held & ~cleared
            covered = self.i2c_held[idx] & I2C_RW1C_MASK
            assert covered == I2C_RW1C_MASK, (
                f"I2C{idx}: the held readbacks of the two passes cover 0x{covered:08x}; all 13 "
                f"RW1C bits 0x{I2C_RW1C_MASK:08x} have to be read held once"
            )
            words[idx] = (raised, held, cleared)
        self._chk(
            "CHK-I2C12-W1C-SWAP-HOLD",
            "%s; %d/13 bits read held then cleared per instance across both passes (from the "
            "held readbacks)",
            "; ".join(
                f"i2c{idx} raised=0x{r:08X} held=0x{h:08X} cleared=0x{c:x}"
                for idx, (r, h, c) in words.items()
            ),
            min(bin(self.i2c_held[idx]).count("1") for idx in SWAP_INSTANCES),
        )
        self._stamp("SWAP_PASS", self._reads_since(mark))

    async def _single_walk(
        self,
        idx: int,
        other: int,
        status: dict[int, RegInstance],
        test: dict[int, RegInstance],
    ) -> None:
        """Raise each W1P source of one instance alone and clear it."""
        mark = self._reads
        addr = status[idx].addr
        walked = 0
        for bit, field in I2C_INTR_SOURCES:
            word = 1 << bit
            assert test[idx].reg.declared_mask & word, (
                f"I2C{idx} INTR_TEST declares no field at bit {bit} ({field})"
            )
            before = await self.csr_read(f"I2C{idx}_{field}_BEFORE", addr)
            assert before == 0, (
                f"I2C{idx} INTR_STATE reads 0x{before:08x} before {field} was raised"
            )
            await self.csr_write(f"I2C{idx}_{field}_INTR_TEST", test[idx].addr, word)
            raised = await self.csr_read(f"I2C{idx}_{field}_RAISED", addr)
            assert raised == word, (
                f"I2C{idx} INTR_STATE reads 0x{raised:08x} after INTR_TEST 0x{word:08x} "
                f"({field}); expected exactly that bit"
            )
            seen = await self.csr_read(f"I2C{other}_{field}_OTHER", status[other].addr)
            assert seen == 0, (
                f"I2C{other} INTR_STATE reads 0x{seen:08x} while only I2C{idx} {field} "
                f"was raised; expected 0x00000000"
            )
            await self.csr_write(f"I2C{idx}_{field}_CLEAR", addr, word)
            after = await self.csr_read(f"I2C{idx}_{field}_CLEARED", addr)
            assert after == 0, (
                f"I2C{idx} INTR_STATE reads 0x{after:08x} after the written 0x{word:08x} "
                f"({field}); expected 0x00000000"
            )
            walked += 1
        assert walked == len(I2C_INTR_SOURCES) == 13, f"I2C{idx}: {walked} of 13 W1P sources walked"
        self._chk(
            f"CHK-I2C{idx}-INTR-TEST-SINGLE",
            "%d/13 W1P fields raised alone (INTR_STATE == 1<<f, i2c%d 0x0) and cleared to "
            "0x0 by the written 1<<f",
            walked,
            other,
        )
        self._stamp(f"SINGLE_I2C{idx}", self._reads_since(mark))

    def _emit_timeout_paths(self) -> None:
        cfg = self.cfg
        assert cfg is not None, "sequence cfg is not initialized"
        waits = [
            (
                "fuse_sense_done",
                "200000 clk_smc_i cycles",
                "tb_fuse_sense_done and the delayed fuse reset released",
            ),
            (
                "sep_in_access",
                f"{cfg.axi_timeout_ns}ns per access",
                f"{self.accesses} accesses completed, last response OKAY",
            ),
        ]
        assert self.timeouts == 0, f"{self.timeouts} SEP_IN accesses expired"
        self._chk(
            "CHK-TIMEOUT-PATHS",
            "%d bounded waits, each raising AssertionError with its address and last state "
            "on expiry; %s; 0 expired",
            len(waits),
            "; ".join(f"{n} bound={b} last={st}" for n, b, st in waits),
        )

    def _emit_nonvac(self) -> None:
        order = [term for term, *_ in self.stamps]
        assert order == FENCE_ORDER, f"fence order {order}, expected {FENCE_ORDER}"
        times = [ps for _t, ps, _a, _r in self.stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        floors = {
            "SETUP": (4, 2),
            "EXISTING_PASS": (7 * self.registers, 3 * self.registers),
            "SWAP_PASS": (6 * len(SWAP_INSTANCES), 3 * len(SWAP_INSTANCES)),
            "SINGLE_I2C1": (6 * 13, 4 * 13),
            "SINGLE_I2C2": (6 * 13, 4 * 13),
        }
        for term, _ps, accesses, reads in self.stamps:
            acc_floor, read_floor = floors[term]
            assert accesses >= acc_floor and reads >= read_floor, (
                f"{term}: {accesses} accesses / {reads} reads, expected at least "
                f"{acc_floor} / {read_floor}"
            )
        printed: dict[str, list[int]] = {}
        for name, at in self.chk_lines:
            printed.setdefault(name, []).append(at)
        for name, term in CHECKER_BEFORE.items():
            assert printed.get(name, []) == [order.index(term)], (
                f"{name} printed at fence positions {printed.get(name)}, expected once "
                f"between the term before {term} and {term}"
            )
        cocotb.log.info(
            "CHK-NONVAC: %s (counts and times per term); checker lines %s",
            " < ".join(f"{t}@{ps}ps[accesses={a},reads={r}]" for t, ps, a, r in self.stamps),
            ",".join(name for name, _ in self.chk_lines),
        )

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        i2c_status = {r.index: r for r in reg_instances(*_i2c_spec("INTR_STATE"))}
        i2c_test = {r.index: r for r in reg_instances(*_i2c_spec("INTR_TEST"))}
        await self._setup(i2c_status, i2c_test)
        accesses_mark = self.accesses
        reads_mark = self._reads

        legs: list[tuple[str, RegInstance, RegInstance]] = []
        for block, status_spec, test_spec in _BLOCKS:
            statuses = reg_instances(*status_spec)
            tests = reg_instances(*test_spec)
            assert statuses and len(statuses) == len(tests), (
                f"{block}: the generated map declares {len(statuses)} status and "
                f"{len(tests)} INTR_TEST instances"
            )
            legs.extend(zip([block] * len(statuses), statuses, tests))
        assert len({status.addr for _b, status, _t in legs}) == len(legs), (
            "two status registers resolve to the same address"
        )

        for block, status, test in legs:
            await self._leg(block, status, test)

        assert self.registers == len(legs), (
            f"{self.registers} of {len(legs)} status registers driven"
        )
        assert self.bits_held >= len(legs), (
            f"{self.bits_held} bits were held set across {len(legs)} registers; each leg "
            f"holds at least one"
        )
        floor = len(legs) * _ACCESSES_PER_INSTANCE
        existing_accesses = self.accesses - accesses_mark
        assert existing_accesses >= floor, (
            f"the sequence issued {existing_accesses} SEP_IN accesses; {len(legs)} registers "
            f"cannot have taken fewer than {floor}"
        )
        sb = getattr(getattr(self, "env", None), "scoreboard", None)
        assert sb is not None, "no scoreboard on this sequence's env"

        reads_existing = self._reads - reads_mark
        self._chk(
            "CHK-INTR-STATUS-PARTIAL-CLEAR",
            "on %d write-one-to-clear status registers "
            "across the I2C blocks, the log engines and the telemetry receivers, the whole "
            "declared mask was raised through INTR_TEST, half of it was written back and "
            "went, and the %d bit(s) the write carried a zero over stayed set, which is "
            "the `oneToClear` contract; every register then took the other half and read "
            "clear again",
            self.registers,
            self.bits_held,
        )
        self._stamp("EXISTING_PASS", reads_existing)

        await self._swap_pass(i2c_status, i2c_test)
        await self._single_walk(1, 2, i2c_status, i2c_test)
        await self._single_walk(2, 1, i2c_status, i2c_test)
        self._emit_timeout_paths()
        self._emit_nonvac()
