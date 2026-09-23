# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART and log-engine register cycles on every uart_log_engine_wrap instance.

Four blocks share one wrapper instance, and this sequence drives the
software-owned registers of three of them on all four wrappers while the UART
stays at its reset configuration.

* The six writable UART 16550 registers take the generic half-register cycle.
  LCR runs last of them, so the DLAB it sets in its ones leg is back at 0
  before anything reads the two addresses DLAB re-maps.
* The divisor-latch window has its own leg. DLL and DLM are reachable only
  while `LCR.DLAB` is 1, and their contract comes from the generated
  `uart_16550_dl` header rather than the SMC map, which does not instantiate
  the window. The leg writes both latches, drops DLAB and reads IER at the
  address DLM occupied -- IER's own reset word there is what shows the window
  switched back -- then raises DLAB again to find both latches still holding
  what was written, and restores them.
* The log engine takes the generic cycle on INTR_ENABLE and a pulse leg on
  INTR_TEST, whose two fields are `write-only`: a write of them raises the
  matching INTR_STATUS events and a write of the same mask back into
  INTR_STATUS clears them.
* LOG_CTRL is a 16-element array, and its pass is phased: every element of a
  wrapper is given a signature derived from its own index, then all 16 are read
  back while the signatures are co-resident. An array folded onto one physical
  register returns the last signature written and fails the first readback.
  The signatures stay resident: a nonzero LOG_LEN is a pending request to the
  log engine's arbiter, which requires a request to hold until it is granted,
  so only the hardware may clear the field.

`log_engine/CTRL.EN` stays at its reset 0 throughout, so the nonzero LOG_LEN
each element carries starts no log transfer, and LOG_REGION_ADDR,
LOG_REGION_SIZE and LOG_WRITE_ADDR are left alone: they address the region a
transfer would read and write.

`uart/RBR`, `uart/LSR` and `uart/MSR` are not read here. Each has fields with a
read side effect, so a read of them is not repeatable, and `uart/IIR` is
hardware-driven throughout.
"""

from __future__ import annotations

import cocotb

from .smc_addr_map import smc_indexed_addr, uart_16550_dl_offset, uart_16550_dl_u32
from .smc_regblock_field_sweep_utils import (
    RegInstance,
    SmcRegblockFieldSweepSeq,
    array_reg_instances,
    reg_instances,
)

_WRAP = "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_"
_WRAP_PY = "SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_{index}__"
_WRAP_PATH = "smc_uart_wrap/uart_log_engine_wrap"


def _uart_spec(register: str) -> tuple[str, str, str, str]:
    return (
        f"{_WRAP_PATH}/uart/{register}",
        f"{_WRAP}UART_{register}_BASE_ADDR",
        f"{_WRAP}UART_{register}_NUM",
        f"{_WRAP_PY}UART_{register}_REG_ADDR",
    )


def _log_engine_spec(register: str) -> tuple[str, str, str, str]:
    return (
        f"{_WRAP_PATH}/log_engine/{register}",
        f"{_WRAP}LOG_ENGINE_{register}_BASE_ADDR",
        f"{_WRAP}LOG_ENGINE_{register}_NUM",
        f"{_WRAP_PY}LOG_ENGINE_{register}_REG_ADDR",
    )


# LCR is swept last: its ones pattern sets DLAB, which re-maps the two
# addresses the divisor-latch leg uses.
_UART_REGISTERS = ("IER", "ITR", "SCR", "ECR", "MCR", "LCR")

_UART_BASE = f"{_WRAP}UART_BASE_ADDR"
_UART_IER_OFFSET_SYMBOL = "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR"
_WRAP_STRIDE_SYMBOL = f"{_WRAP}STRIDE"

_DLL_OFFSET = uart_16550_dl_offset("UART_16550_DL_DLL_BASE_ADDR")
_DLM_OFFSET = uart_16550_dl_offset("UART_16550_DL_DLM_BASE_ADDR")
_DLL_MASK = uart_16550_dl_u32("UART_16550_DL__DLL__DLL_bm")
_DLM_MASK = uart_16550_dl_u32("UART_16550_DL__DLM__DLM_bm")
_DLL_RESET = uart_16550_dl_u32("UART_16550_DL__DLL__DLL_reset")
_DLM_RESET = uart_16550_dl_u32("UART_16550_DL__DLM__DLM_reset")

_LOG_CTRL_PATH = f"{_WRAP_PATH}/log_engine/LOG_CTRL"
_LOG_CTRL_PY = _WRAP_PY + "LOG_ENGINE_LOG_CTRL_{element}__REG_ADDR"

# Signature for LOG_CTRL element i: a fixed marker in the upper byte and the
# index inverted in the lower one, so element i cannot be satisfied by element
# j's value and a zeroed element cannot be satisfied at all.
_LOG_CTRL_MARKER = 0x5A00


def _log_ctrl_signature(element: int) -> int:
    return _LOG_CTRL_MARKER | ((element ^ 0xA5) & 0xFF)


_ACCESSES_PER_GRANULE_CYCLE = 12
_ACCESSES_PER_DL_LEG = 18
_ACCESSES_PER_PULSE_LEG = 5
_ACCESSES_PER_LOG_CTRL_ELEMENT = 2


def _field_mask(inst: RegInstance, name: str) -> int:
    for field in inst.reg.fields:
        if field.name == name:
            return field.mask
    raise KeyError(f"{inst.label}: the generated map declares no {name} field")


def _write_only_mask(inst: RegInstance) -> int:
    mask = 0
    for field in inst.reg.fields:
        if field.access == "write-only":
            mask |= field.mask
    return mask


class smc_uart_log_engine_field_sweep_test_seq(SmcRegblockFieldSweepSeq):
    """Cycle the UART, divisor-latch and log-engine registers on every wrapper."""

    def __init__(self, name: str = "smc_uart_log_engine_field_sweep_test_seq") -> None:
        super().__init__(name)
        self.dl_legs = 0
        self.pulses = 0
        self.log_ctrl_elements = 0

    async def _dl_window(self, index: int, lcr: RegInstance, ier: RegInstance) -> None:
        base = smc_indexed_addr(_UART_BASE, index)
        dll = base + _DLL_OFFSET
        dlm = base + _DLM_OFFSET
        assert dlm == smc_indexed_addr(_UART_IER_OFFSET_SYMBOL, index), (
            f"uart[{index}]: the divisor-latch window places DLM at 0x{dlm:08x} and the SMC "
            f"map places IER at 0x{ier.addr:08x}; the leg below proves the window switch at "
            f"one address, so the two have to be the same address"
        )
        dlab = _field_mask(lcr, "DLAB")
        pattern = (_DLL_MASK, _DLM_MASK)
        reset = (_DLL_RESET, _DLM_RESET)

        await self.csr_write(f"uart[{index}]:dlab_set", lcr.addr, dlab)
        await self.read_check(lcr, "dlab_set", dlab)
        for label, addr, mask, value in (
            ("DLL", dll, _DLL_MASK, pattern[0]),
            ("DLM", dlm, _DLM_MASK, pattern[1]),
        ):
            await self.csr_write(f"uart[{index}]:{label}_ones", addr, value)
            got = await self.csr_read(f"uart[{index}]:{label}_ones_rb", addr, expected=value)
            assert got == value & mask, (
                f"uart[{index}] {label} @ 0x{addr:08x}: wrote 0x{value:02x} into the latch "
                f"and read 0x{got:08x}"
            )

        await self.csr_write(f"uart[{index}]:dlab_clear", lcr.addr, 0)
        await self.read_check(lcr, "dlab_clear", 0)
        await self.read_check(ier, "main_window", 0)

        await self.csr_write(f"uart[{index}]:dlab_reset", lcr.addr, dlab)
        for label, addr, value in (("DLL", dll, pattern[0]), ("DLM", dlm, pattern[1])):
            got = await self.csr_read(f"uart[{index}]:{label}_held", addr, expected=value)
            assert got == value, (
                f"uart[{index}] {label} @ 0x{addr:08x}: reads 0x{got:08x} after DLAB was "
                f"cleared and set again, not the 0x{value:02x} written before the switch"
            )
        for label, addr, value in (("DLL", dll, reset[0]), ("DLM", dlm, reset[1])):
            await self.csr_write(f"uart[{index}]:{label}_restore", addr, value)
        for label, addr, value in (("DLL", dll, reset[0]), ("DLM", dlm, reset[1])):
            await self.csr_read(f"uart[{index}]:{label}_restore_rb", addr, expected=value)
        await self.csr_write(f"uart[{index}]:dlab_restore", lcr.addr, 0)
        await self.read_check(lcr, "dlab_restore", 0)
        self.dl_legs += 1

    async def _intr_test_pulse(self, test: RegInstance, status: RegInstance) -> None:
        pulse = _write_only_mask(test)
        assert pulse, (
            f"{test.label}: the generated map declares no write-only field, so there is "
            f"no interrupt this leg could raise"
        )
        await self.csr_read(f"{status.label}:idle", status.addr, expected=0)
        await self.csr_write(f"{test.label}:pulse", test.addr, pulse)
        raised = await self.csr_read(f"{status.label}:raised", status.addr, expected=pulse)
        assert raised & pulse == pulse, (
            f"{status.label} @ 0x{status.addr:08x}: a write of 0x{pulse:x} into the "
            f"write-only test fields left the matching events at 0x{raised & pulse:x}"
        )
        await self.csr_write(f"{status.label}:clear", status.addr, pulse)
        cleared = await self.csr_read(f"{status.label}:cleared", status.addr, expected=0)
        assert cleared & pulse == 0, (
            f"{status.label} @ 0x{status.addr:08x}: a write of 0x{pulse:x} into the "
            f"`oneToClear` events left 0x{cleared & pulse:x} of them set"
        )
        self.pulses += 1

    async def _log_ctrl_pass(self, elements: tuple[RegInstance, ...]) -> None:
        # LOG_CTRL.LOG_LEN is `hwclr`, so the generated contract does not pin its
        # readback and the generic cycle leaves it alone; the engine is disabled
        # throughout this pass, so nothing clears it and the signature is what
        # the element must return. A nonzero LOG_LEN is a pending arbiter request
        # that must hold until granted, so the signatures are not written back to 0.
        signatures = [_log_ctrl_signature(inst.index) & inst.reg.declared_mask for inst in elements]
        assert len(set(signatures)) == len(signatures), (
            "the LOG_CTRL signatures are not pairwise distinct, so a co-resident readback "
            "would not discriminate elements"
        )
        for inst, signature in zip(elements, signatures):
            await self.csr_write(f"{inst.label}:signature", inst.addr, signature)
        for inst, signature in zip(elements, signatures):
            got = await self.csr_read(f"{inst.label}:signature_rb", inst.addr, expected=signature)
            assert got == signature, (
                f"{inst.label} @ 0x{inst.addr:08x}: reads 0x{got:08x} while all "
                f"{len(elements)} elements hold their own signature, its own is "
                f"0x{signature:08x}"
            )
            self.log_ctrl_elements += 1

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        uart = {name: reg_instances(*_uart_spec(name)) for name in _UART_REGISTERS}
        intr_enable = reg_instances(*_log_engine_spec("INTR_ENABLE"))
        intr_status = reg_instances(*_log_engine_spec("INTR_STATUS"))
        intr_test = reg_instances(*_log_engine_spec("INTR_TEST"))
        count = len(intr_enable)
        assert count and all(len(group) == count for group in uart.values()), (
            "the generated map declares a different instance count for the wrapper registers"
        )

        for index in range(count):
            for name in _UART_REGISTERS:
                await self.granule_cycle(uart[name][index])
        cocotb.log.info(
            "CHK-UART-16550-FIELD-SWEEP: %d UART instances each drove %s to all-ones and "
            "all-zeros through half-register writes whose byte lanes over the other half "
            "were deasserted, read each one back against its generated RDL contract and "
            "restored its reset; %d contract compares",
            count,
            ", ".join(_UART_REGISTERS),
            self.value_checks,
        )

        for index in range(count):
            await self._dl_window(index, uart["LCR"][index], uart["IER"][index])
        cocotb.log.info(
            "CHK-UART-16550-DL-WINDOW: on %d UART instances both divisor latches took "
            "0x%02x and their reset behind LCR.DLAB, held it across a clear and a re-raise "
            "of DLAB, and the address DLM occupies returned IER's own reset word while "
            "DLAB was clear",
            self.dl_legs,
            _DLL_MASK,
        )

        for index in range(count):
            await self.granule_cycle(intr_enable[index])
            await self._intr_test_pulse(intr_test[index], intr_status[index])
        cocotb.log.info(
            "CHK-LOG-ENGINE-INTR-SWEEP: %d log engines drove INTR_ENABLE to all-ones and "
            "all-zeros through half-register writes, and a write of the write-only "
            "INTR_TEST fields raised exactly those INTR_STATUS events from a measured "
            "clear state and a write of the same mask cleared them again",
            self.pulses,
        )

        for index in range(count):
            await self._log_ctrl_pass(
                array_reg_instances(_LOG_CTRL_PATH, _LOG_CTRL_PY, _WRAP_STRIDE_SYMBOL, index)
            )
        cocotb.log.info(
            "CHK-LOG-ENGINE-LOG-CTRL-SWEEP: %d LOG_CTRL elements each took an "
            "index-unique log length and were read back while all 16 elements of their "
            "wrapper held their own signature",
            self.log_ctrl_elements,
        )

        elements_per_wrap = len(
            array_reg_instances(_LOG_CTRL_PATH, _LOG_CTRL_PY, _WRAP_STRIDE_SYMBOL, 0)
        )
        expected = count * (
            len(_UART_REGISTERS) * _ACCESSES_PER_GRANULE_CYCLE
            + _ACCESSES_PER_DL_LEG
            + _ACCESSES_PER_GRANULE_CYCLE
            + _ACCESSES_PER_PULSE_LEG
            + elements_per_wrap * _ACCESSES_PER_LOG_CTRL_ELEMENT
        )
        self.assert_all_reachable(expected, "UART_LOG_ENGINE_FIELD_SWEEP")
        assert self.registers_swept == count * (len(_UART_REGISTERS) + 1), (
            f"the sweep completed {self.registers_swept} field cycles for "
            f"{count * (len(_UART_REGISTERS) + 1)} registers"
        )
        assert self.dl_legs == count and self.pulses == count, (
            f"{self.dl_legs} divisor-latch legs and {self.pulses} pulse legs for {count} wrappers"
        )
        assert self.log_ctrl_elements == count * elements_per_wrap, (
            f"the sweep read back {self.log_ctrl_elements} LOG_CTRL elements, the generated "
            f"map declares {count * elements_per_wrap}"
        )
