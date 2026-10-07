# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""RDL-contract sweep of the software-owned SMC CSR blocks over SEP_IN AXI.

Every address, reset value, field position and software-access type below comes
from the generated register map through :mod:`seq_lib.smc_rdl_regmap`, which
reads the PeakRDL IP-XACT export and cross-checks each address against the
matching ``smc_reg.py`` symbol. Nothing here is a hand-transcribed address, mask
or reset word.

Each swept register is driven through one cycle and put back:

* read at reset -- bits no field of the register occupies must read 0, and every
  field whose RDL reset survives until software writes it must carry that reset;
* write each half of the register with its software-writable bits set, and read
  the whole register back after each half. The halves go out as separate
  narrower accesses, so the byte lanes over the other half are deasserted and
  each readback also proves the untouched half kept its value;
* write each half with the low pattern (0, or the RDL reset where a 0 is a
  hardware event) and read back again;
* restore the RDL reset and read it back.

A register with no field the contract makes software-writable with a pinned
readback gets the reset read alone. A register array gets that cycle on element
0 and then a phased pass over every element: all elements are given a signature
derived from their own index, all are read back while the signatures are
co-resident, and only then are they restored -- so an array folded onto one
physical register fails rather than returning the value just written through
the same address.

Fields the contract does not pin are never written by the generic cycle
(``RdlField.plain_rw``): hardware-driven, self-clearing, ``oneToSet`` and
read-side-effect fields have no written-value expectation. The CPU_CTRL ones
that carry a contract of their own are driven by ``_special_registers``.

``_EXCLUDED`` names every remaining software-writable register of the swept
blocks and what driving it would do here; ``_assert_partition`` fails if a
register of those blocks is in neither list, so a regenerated map cannot add one
silently.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_rdl_regmap import RdlReg, rdl_array, rdl_register, rdl_registers_under

# Blocks this sequence owns. Every register instance under these prefixes has to
# be accounted for by _SWEPT, _SPECIAL or _EXCLUDED.
_BLOCKS: tuple[str, ...] = (
    "smc_misc_wrap/scratch_cold",
    "smc_misc_wrap/scratch_cold_warm",
    "smc_misc_wrap/ndm_reset",
    "dfx_ctrl",
    "smc_base_config",
    "smc_reset_unit",
    "smc_cpu_ctrl",
)

# Registers driven through the generic cycle, by IP-XACT path. A path with no
# index is a register array and is expanded over every element.
#
# CLOCK_GATE_CONTROL is last: its ones leg enables the activity clock gates of
# the DMA, mailbox, filter, remap, output-fabric, zeroer, I3C, AVS, I2C, UART
# and telemetry blocks at once, so it runs after every other register has been
# read back.
_SWEPT: tuple[str, ...] = (
    "smc_misc_wrap/scratch_cold/SCRATCH",
    "smc_misc_wrap/scratch_cold_warm/SCRATCH",
    "dfx_ctrl/STATUS_SMU",
    "dfx_ctrl/DEBUG_CTRL",
    "dfx_ctrl/DEBUG_BUS_MUX",
    "smc_reset_unit/ISOLATE_REQ_PINEN_REG",
    "smc_reset_unit/SYNC_REG",
    "smc_cpu_ctrl/RESET_VECTOR",
    "smc_cpu_ctrl/CORE_RESET_PULSE_COUNT",
    "smc_cpu_ctrl/RESET_TIMEOUT",
    "smc_cpu_ctrl/WDT_TIMEOUT",
    "smc_cpu_ctrl/TEST_CTRL",
    "smc_cpu_ctrl/SCRATCH",
    "smc_cpu_ctrl/WB_PC_CORE0",
    "smc_cpu_ctrl/WB_PC_CORE1",
    "smc_cpu_ctrl/WB_PC_CORE2",
    "smc_cpu_ctrl/WB_PC_CORE3",
    "smc_cpu_ctrl/SMC_ATTRIBUTES",
    "smc_cpu_ctrl/DUMMY_ROM_0",
    "smc_cpu_ctrl/DUMMY_ROM_1",
    "smc_cpu_ctrl/DUMMY_ROM_2",
    "smc_cpu_ctrl/DUMMY_ROM_3",
    "smc_cpu_ctrl/DUMMY_ROM_NULL",
    "smc_base_config/HANG_DET_SYS_AXI_CTRL",
    "smc_base_config/HANG_DET_SYS_AXI_TIMEOUT_THRESHOLD",
    "smc_base_config/HANG_DET_SEP_AXI_CTRL",
    "smc_base_config/HANG_DET_SEP_AXI_TIMEOUT_THRESHOLD",
    "smc_base_config/HANG_DET_DATA_ACCEL_CTRL",
    "smc_base_config/HANG_DET_DATA_ACCEL_TIMEOUT_THRESHOLD",
    "smc_base_config/CLOCK_GATE_CONTROL",
)

# Registers whose RDL contract is not "the write lands and the read returns it",
# driven by _special_registers with the contract each one declares.
_SPECIAL: tuple[str, ...] = (
    "smc_cpu_ctrl/WDT_TIMEOUT_RESET",
    "smc_cpu_ctrl/MUTEX",
    "smc_cpu_ctrl/SEMA",
    "smc_cpu_ctrl/REFERENCE_COUNTER",
)

# Registers of the swept blocks this sequence leaves alone, and what driving
# each one here would do.
_EXCLUDED: dict[str, str] = {
    "smc_base_config/GLOBAL_BASE": (
        "base of the outbound aperture every SEP_IN request above the local "
        "window is routed through"
    ),
    "smc_base_config/LOCAL_BASE": "sw = r; read back by smc_dual_base_addressing_test",
    "smc_base_config/REGION_SIZE": (
        "the local-alias fold mask is REGION_SIZE-1, so a value that is not a "
        "power of two misroutes every later access of this sequence"
    ),
    "smc_cpu_ctrl/RESET_CTRL": (
        "per-core and uncore reset levels plus the four core reset-pulse starts"
    ),
    "smc_misc_wrap/ndm_reset/NDMRESET_REQUEST": "driven by smc_ndm_reset_test",
    "smc_misc_wrap/ndm_reset/NDMRESET_PROCESS": "driven by smc_ndm_reset_test",
    "smc_misc_wrap/ndm_reset/NDMRESET_CLUSTER_COUNT": "driven by smc_ndm_reset_test",
    "smc_reset_unit/SS_CONFIG": "driven by smc_reset_unit_sanity_test",
    "smc_reset_unit/SS_CONFIG_LOCK": (
        "onwrite = woset and only a cold reset clears it, so the restore leg cannot put it back"
    ),
    "smc_reset_unit/SS_COLD_RESET_N": "driven by smc_reset_unit_sanity_test",
    "smc_reset_unit/SS_WARM_RESET_N": "subsystem warm resets, asserted by writing 0",
    "smc_reset_unit/SS_CONFIG_HOLD": "driven by smc_reset_unit_sanity_test",
    "smc_reset_unit/SS_SRAM_HOLD": "driven by smc_reset_unit_sanity_test",
    "smc_reset_unit/SS_CRITICAL_HOLD": "driven by smc_reset_unit_sanity_test",
    "smc_reset_unit/SS_DEBUG_HOLD": "driven by smc_reset_unit_sanity_test",
    "smc_reset_unit/SS_RESET_COMPLETE": "sw = r; driven by smc_ss_reset_complete_test",
    "smc_reset_unit/SS_COLD_RESET_LOCK": (
        "onwrite = woset and only a cold reset clears it, so the restore leg cannot put it back"
    ),
    "smc_reset_unit/SS_FORCE_TO_REF_CLK": "driven by smc_reset_unit_sanity_test",
    "smc_reset_unit/ISOLATE_REQ_REG": "driven by smc_reset_unit_sanity_test",
    "smc_reset_unit/ISOLATE_REQ_SMC_REG": (
        "hardware-set on cfg_flr_pf_active and cleared by any software write"
    ),
    "smc_reset_unit/ISOLATE_REQ_SMCEN_REG": "driven by smc_reset_unit_sanity_test",
    "smc_reset_unit/ISOLATE_REQ_VIS": "sw = r pin visibility; driven by smc_flr_sanity_test",
    "smc_reset_unit/ISOLATE_REQ_FLR_COUNTER_VALUE": "driven by smc_flr_sanity_test",
    "smc_reset_unit/ISOLATE_REQ_FLR_RESET_COUNTER_VALUE": "driven by smc_flr_sanity_test",
}

# Low pattern per register. Default 0. CPU_CTRL.WDT_TIMEOUT is the max_count of
# the second watchdog stage (smc_cpu_ctrl_wrap.sv max_count): while the cluster
# watchdog is idle the counter reloads max_count every clock, so a 0 makes
# cycle_count 0 and asserts wdt_second_timeout_o. Its low leg writes the RDL
# reset instead, which is also what the restore leg puts back.
_LOW_IS_RESET: frozenset[str] = frozenset({"smc_cpu_ctrl/WDT_TIMEOUT"})

# Signature for element i of a register array: a fixed marker, the index, and
# the index again inverted, so element i cannot be satisfied by element j's
# value and a zeroed or tied-off element cannot be satisfied at all.
_ARRAY_SIGNATURE_MARKER = 0x5EED_0000


def _array_signature(index: int) -> int:
    return _ARRAY_SIGNATURE_MARKER | (0x100 * index) | (index ^ 0xA5)


# cpu_ctrl.rdl SEMA.sema: "Writing to this register will inc/dec the semaphore
# value. The written value is treated as a signed number using 2s compliment."
_SEMA_STEP = 1

# cpu_ctrl.rdl MUTEX.mutex, reset 1: "Reads will attempt to acquire mutex, 1 on
# success. If the mutex is already acquired, the read will return 0. To release
# the mutex, write any value to the register."
_MUTEX_FREE = 1
_MUTEX_HELD = 0

# doc/trm/src/clock_domains.adoc (Reference Counter),
# CPU_CTRL.REFERENCE_COUNTER: a free-running counter on the always-on reference
# clock, "advancing continuously from reset". cpu_ctrl.rdl makes the field `sw =
# rw; hw = rw`, so software both reads it and loads it, and the counter resumes
# from the loaded value.
_REF_COUNTER_SETTLE = 64

# The straps block belongs to the open integration, not to smc.sv; the SMC map
# places it in the mandatory region of the adopter external window, and
# straps.rdl makes both `sw = r; hw = w`: STRAPS_LO @0x0 straps[31:0],
# STRAPS_HI @0x4 straps[28:0]. What they hold is whatever the integration
# latched from the bonded pads at cold reset, so the value is read once and
# held against the write, not predicted.
_STRAPS_REGS = (
    ("STRAPS_LO", 0x0, 0xFFFF_FFFF),
    ("STRAPS_HI", 0x4, 0x1FFF_FFFF),
)
_STRAPS_WRITE_PATTERN = 0xFFFF_FFFF

# A software load of REFERENCE_COUNTER crosses into the reference-clock domain
# and the count returns through the synchroniser, so the readback that first
# shows the loaded value is some accesses after the write. The contract is
# write-then-poll; a counter that never shows the load within this many
# readbacks fails.
_REF_COUNTER_LOAD_POLLS = 16


def _straps_base() -> int:
    return smc_addr("SMC_TOP_SMC_EXTERNAL_MANDATORY_STRAPS_BASE_ADDR")


def _assert_partition() -> None:
    """Every register of the swept blocks is swept, special, or excluded."""
    accounted = set(_SWEPT) | set(_SPECIAL) | set(_EXCLUDED)
    unaccounted = sorted(
        {reg.base_path for block in _BLOCKS for reg in rdl_registers_under(block)} - accounted
    )
    assert not unaccounted, (
        "the generated register map carries registers of the swept blocks that this "
        "sequence neither drives nor names a reason to leave alone: " + ", ".join(unaccounted)
    )
    stale = sorted(accounted - {reg.base_path for b in _BLOCKS for reg in rdl_registers_under(b)})
    assert not stale, "named registers that the generated map no longer has: " + ", ".join(stale)


class smc_rdl_field_sweep_test_seq(SmcCsrSeq):
    """Drive every software-owned field of the swept CSR blocks and restore it."""

    def __init__(self, name: str = "smc_rdl_field_sweep_test_seq") -> None:
        super().__init__(name)
        self.registers_swept = 0
        self.write_groups = 0
        self.value_checks = 0

    # -- checking --------------------------------------------------------

    @staticmethod
    def _word_mask(reg: RdlReg) -> int:
        return (1 << (reg.width_bytes * 8)) - 1

    async def _read_check(self, reg: RdlReg, label: str, model: int) -> int:
        value = await self.csr_read(f"{reg.path}:{label}", reg.addr, length=reg.width_bytes)
        value &= self._word_mask(reg)

        unimplemented = value & ~reg.declared_mask & self._word_mask(reg)
        assert unimplemented == 0, (
            f"{reg.path} @ 0x{reg.addr:08x} [{label}]: read "
            f"0x{value:0{reg.width_bytes * 2}x}, which drives 0x{unimplemented:x} in bits "
            f"no field of the register occupies (declared 0x{reg.declared_mask:x})"
        )

        got_rw = value & reg.rw_mask
        want_rw = model & reg.rw_mask
        assert got_rw == want_rw, (
            f"{reg.path} @ 0x{reg.addr:08x} [{label}]: software-writable bits read "
            f"0x{got_rw:x}, the register contract says 0x{want_rw:x}"
        )

        pinned_ro = reg.static_mask & ~reg.rw_mask
        assert value & pinned_ro == reg.reset_word & pinned_ro, (
            f"{reg.path} @ 0x{reg.addr:08x} [{label}]: bits software cannot write read "
            f"0x{value & pinned_ro:x}, their RDL reset is 0x{reg.reset_word & pinned_ro:x}"
        )
        self.value_checks += 1
        return value

    # -- generic cycle ---------------------------------------------------

    async def _granule_cycle(self, reg: RdlReg, low_value: int) -> None:
        """Half-register writes with the other half's byte lanes deasserted."""
        half = reg.width_bytes // 2
        granules = ((0, half), (half, half))
        model = reg.reset_word
        await self._read_check(reg, "reset", model)

        for pattern, tag in ((reg.rw_mask, "ones"), (low_value, "low")):
            for offset, width in granules:
                gmask = ((1 << (width * 8)) - 1) << (offset * 8)
                touched = reg.rw_mask & gmask
                await self.csr_write(
                    f"{reg.path}:{tag}@{offset}",
                    reg.addr + offset,
                    (pattern & gmask) >> (offset * 8),
                    length=width,
                )
                model = (model & ~touched) | (pattern & touched)
                self.write_groups += 1
                await self._read_check(reg, f"{tag}@{offset}", model)

        for offset, width in granules:
            gmask = ((1 << (width * 8)) - 1) << (offset * 8)
            await self.csr_write(
                f"{reg.path}:restore@{offset}",
                reg.addr + offset,
                (reg.reset_word & gmask) >> (offset * 8),
                length=width,
            )
        await self._read_check(reg, "restore", reg.reset_word)

    async def _array_pass(self, regs: tuple[RdlReg, ...]) -> None:
        """Co-resident signature pass over every element of a register array."""
        for index, reg in enumerate(regs):
            await self.csr_write(
                f"{reg.path}:signature",
                reg.addr,
                _array_signature(index) & reg.rw_mask,
                length=reg.width_bytes,
            )
            self.write_groups += 1
        for index, reg in enumerate(regs):
            signature = _array_signature(index) & reg.rw_mask
            await self._read_check(reg, "signature", (reg.reset_word & ~reg.rw_mask) | signature)
        for reg in regs:
            await self.csr_write(
                f"{reg.path}:restore", reg.addr, reg.reset_word, length=reg.width_bytes
            )
        for reg in regs:
            await self._read_check(reg, "restore", reg.reset_word)

    async def _sweep(self) -> None:
        for path in _SWEPT:
            try:
                regs: tuple[RdlReg, ...] = (rdl_register(path),)
            except KeyError:
                regs = rdl_array(path)
            head = regs[0]
            if head.rw_mask == 0:
                # Read-only register: the reset read is the whole cycle, so it
                # has to be able to fail on its own.
                assert head.declared_mask != self._word_mask(head) or head.static_mask, (
                    f"{path} has no software-writable field and no bit whose value the "
                    f"RDL pins, so a reset read of it could not fail"
                )
                for reg in regs:
                    await self._read_check(reg, "reset", reg.reset_word)
                    self.registers_swept += 1
                continue
            await self._granule_cycle(head, head.reset_word if path in _LOW_IS_RESET else 0)
            self.registers_swept += 1
            if len(regs) > 1:
                await self._array_pass(regs)
                self.registers_swept += len(regs) - 1

    # -- registers with a contract of their own --------------------------

    async def _wdt_timeout_reset(self) -> None:
        reg = rdl_register("smc_cpu_ctrl/WDT_TIMEOUT_RESET")
        pulse_bits = 0
        for field in reg.fields:
            pulse_bits |= field.mask
        await self.csr_write(
            "WDT_TIMEOUT_RESET:pulse", reg.addr, pulse_bits, length=reg.width_bytes
        )
        self.write_groups += 1
        after = await self.csr_read("WDT_TIMEOUT_RESET:after", reg.addr, length=reg.width_bytes)
        assert after & pulse_bits == 0, (
            f"WDT_TIMEOUT_RESET @ 0x{reg.addr:08x}: wrote 0x{pulse_bits:x} into fields the RDL "
            f"marks singlepulse, which are visible to hardware for one clock and clear "
            f"themselves, but the readback still carries 0x{after & pulse_bits:x}"
        )
        self.value_checks += 1
        half = reg.width_bytes // 2
        await self.csr_write("WDT_TIMEOUT_RESET:upper", reg.addr + half, 0, length=half)
        self.write_groups += 1
        after = await self.csr_read("WDT_TIMEOUT_RESET:upper_rb", reg.addr, length=reg.width_bytes)
        assert after & pulse_bits == 0, (
            f"WDT_TIMEOUT_RESET @ 0x{reg.addr:08x}: reads 0x{after & pulse_bits:x} after a "
            f"write whose byte lanes over those fields were deasserted"
        )
        self.value_checks += 1

    async def _mutex(self) -> None:
        for reg in rdl_array("smc_cpu_ctrl/MUTEX"):
            first = await self.csr_read(f"{reg.path}:acquire", reg.addr, length=reg.width_bytes)
            assert first & 1 == _MUTEX_FREE, (
                f"{reg.path} @ 0x{reg.addr:08x}: the acquiring read returned {first & 1}; the "
                f"RDL reset is the free mutex, so it must return {_MUTEX_FREE}"
            )
            held = await self.csr_read(f"{reg.path}:held", reg.addr, length=reg.width_bytes)
            assert held & 1 == _MUTEX_HELD, (
                f"{reg.path} @ 0x{reg.addr:08x}: a second read while the mutex was held "
                f"returned {held & 1}, not {_MUTEX_HELD}, so it was handed out twice"
            )
            await self.csr_write(f"{reg.path}:release", reg.addr, 0, length=reg.width_bytes)
            self.write_groups += 1
            freed = await self.csr_read(f"{reg.path}:reacquire", reg.addr, length=reg.width_bytes)
            assert freed & 1 == _MUTEX_FREE, (
                f"{reg.path} @ 0x{reg.addr:08x}: a write released the mutex but the next read "
                f"returned {freed & 1}, not {_MUTEX_FREE}"
            )
            self.value_checks += 3

    async def _semaphore(self) -> None:
        for reg in rdl_array("smc_cpu_ctrl/SEMA"):
            width = max(field.offset + field.width for field in reg.fields)
            modulus = 1 << width
            start = await self.csr_read(f"{reg.path}:start", reg.addr, length=reg.width_bytes)
            start &= modulus - 1
            assert start == reg.reset_word, (
                f"{reg.path} @ 0x{reg.addr:08x}: reads 0x{start:x} before any increment, its "
                f"RDL reset is 0x{reg.reset_word:x}"
            )
            await self.csr_write(f"{reg.path}:inc", reg.addr, _SEMA_STEP, length=reg.width_bytes)
            self.write_groups += 1
            up = await self.csr_read(f"{reg.path}:inc_rb", reg.addr, length=reg.width_bytes)
            assert up & (modulus - 1) == (start + _SEMA_STEP) % modulus, (
                f"{reg.path} @ 0x{reg.addr:08x}: a write of +{_SEMA_STEP} moved the semaphore "
                f"from 0x{start:x} to 0x{up & (modulus - 1):x}"
            )
            await self.csr_write(
                f"{reg.path}:dec", reg.addr, (-_SEMA_STEP) % modulus, length=reg.width_bytes
            )
            self.write_groups += 1
            down = await self.csr_read(f"{reg.path}:dec_rb", reg.addr, length=reg.width_bytes)
            assert down & (modulus - 1) == start, (
                f"{reg.path} @ 0x{reg.addr:08x}: a write of -{_SEMA_STEP} left the semaphore at "
                f"0x{down & (modulus - 1):x}, not back at 0x{start:x}"
            )
            self.value_checks += 3

    async def _reference_counter(self) -> None:
        reg = rdl_register("smc_cpu_ctrl/REFERENCE_COUNTER")
        running = await self.csr_read("REFERENCE_COUNTER:running", reg.addr, length=reg.width_bytes)
        assert running > reg.reset_word, (
            f"REFERENCE_COUNTER @ 0x{reg.addr:08x}: reads 0x{running:x}, still at or below its "
            f"reset 0x{reg.reset_word:x} well past reset release, so it is not advancing"
        )
        await self.csr_write("REFERENCE_COUNTER:load", reg.addr, 0, length=reg.width_bytes)
        self.write_groups += 1
        loaded = running
        for _ in range(_REF_COUNTER_LOAD_POLLS):
            loaded = await self.csr_read(
                "REFERENCE_COUNTER:loaded", reg.addr, length=reg.width_bytes
            )
            if loaded < running:
                break
        assert loaded < running, (
            f"REFERENCE_COUNTER @ 0x{reg.addr:08x}: `sw = rw`, but {_REF_COUNTER_LOAD_POLLS} "
            f"readbacks after a software write of 0 it still reads 0x{loaded:x} against "
            f"0x{running:x} before the write, so the write did not load the counter"
        )
        await ClockCycles(cocotb.top.clk_smc_i, _REF_COUNTER_SETTLE)
        resumed = await self.csr_read("REFERENCE_COUNTER:resumed", reg.addr, length=reg.width_bytes)
        assert resumed > loaded, (
            f"REFERENCE_COUNTER @ 0x{reg.addr:08x}: 0x{loaded:x} right after the write and "
            f"0x{resumed:x} {_REF_COUNTER_SETTLE} clk_smc_i cycles later; the counter stopped "
            f"instead of resuming from the loaded value"
        )
        self.value_checks += 3

    # -- adopter straps window -------------------------------------------

    async def _straps_window(self) -> None:
        base = _straps_base()
        captured: dict[str, int] = {}
        for label, offset, declared in _STRAPS_REGS:
            addr = base + offset
            value = await self.csr_read(f"{label}:capture", addr)
            captured[label] = value
            outside = value & ~declared & 0xFFFF_FFFF
            assert outside == 0, (
                f"{label} @ 0x{addr:08x}: reads 0x{value:08x}, which drives 0x{outside:x} "
                f"outside the 0x{declared:08x} its RDL field occupies"
            )
            await self.csr_write(f"{label}:write", addr, _STRAPS_WRITE_PATTERN)
            self.write_groups += 1
            after = await self.csr_read(f"{label}:after_write", addr)
            assert after == value, (
                f"{label} @ 0x{addr:08x}: straps.rdl makes it `sw = r`, but a software write of "
                f"0x{_STRAPS_WRITE_PATTERN:08x} changed the readback from 0x{value:08x} to "
                f"0x{after:08x}"
            )
            self.value_checks += 2
        cocotb.log.info(
            "CHK-RDL-STRAPS-RO: both adopter strap capture registers at 0x%08x read with "
            "every undeclared bit 0 (STRAPS_LO=0x%08x STRAPS_HI=0x%08x), and a software "
            "write of 0x%08x left both unchanged, which is the `sw = r` contract of "
            "straps.rdl",
            base,
            captured["STRAPS_LO"],
            captured["STRAPS_HI"],
            _STRAPS_WRITE_PATTERN,
        )

    # -- body ------------------------------------------------------------

    async def body(self) -> None:
        _assert_partition()
        await self.wait_fuse_sense_done()

        await self._sweep()
        cocotb.log.info(
            "CHK-RDL-SWEEP-CYCLE: %d register instances read their RDL reset, took the pattern "
            "their software-access type allows through half-register writes and a co-resident "
            "array pass, and were restored to that reset; %d value compares so far",
            self.registers_swept,
            self.value_checks,
        )

        await self._wdt_timeout_reset()
        await self._mutex()
        await self._semaphore()
        await self._reference_counter()
        cocotb.log.info(
            "CHK-RDL-SWEEP-SPECIAL: the singlepulse, mutex, semaphore and free-running counter "
            "registers of CPU_CTRL each met the contract their RDL declares instead of a plain "
            "write/readback; %d value compares in total",
            self.value_checks,
        )

        await self._straps_window()

        assert self.registers_swept == len(_swept_instances()), (
            f"the sweep drove {self.registers_swept} register instances, the swept list "
            f"declares {len(_swept_instances())}"
        )


def _swept_instances() -> tuple[str, ...]:
    """Every register instance the swept list expands to."""
    out: list[str] = []
    for path in _SWEPT:
        try:
            out.append(rdl_register(path).path)
        except KeyError:
            out.extend(reg.path for reg in rdl_array(path))
    return tuple(out)
