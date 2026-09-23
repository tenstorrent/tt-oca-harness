# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The register blocks of the SMC peripherals no leaf writes.

`smc_rdl_field_sweep_test` owns the software-owned blocks of the SMC core and
`smc_gpio_intf_regblock_sweep_test`, `smc_filter_config_field_sweep_test`,
`smc_i2c_intr_reg_sweep_test` and `smc_uart_log_engine_field_sweep_test` own
four peripheral blocks. The rest of the peripherals have never had a write:
the AVSBus controller, the three telemetry receivers, the OCTS system timer,
the eFuse interface controller, the DMA controller's configuration and the
four log engines' region and enable registers.

Each register takes the cycle the other sweeps use -- read at reset, the
all-ones and the all-zeros pattern of the fields the generated contract pins,
each half written on its own so the byte lanes over the other half are
deasserted, then the RDL reset restored -- and only fields the contract makes
plain read-write are driven, so a `singlepulse` trigger, a `oneToClear` event
or a hardware-driven status is never written by the generic cycle.

Three registers need more than that, and say so at the call site:

* `EFUSE_PROGRAM_CTRL` holds the address, the data and the arming bit of a fuse
  burn. `efuse_program_go` is `singlepulse`, so the generic cycle already
  cannot pull the trigger, and this leaf additionally holds `efuse_data` and
  `program_enable` at their reset, so no combination it writes can arm one.
  The address and the read-back select are driven normally.
* `AVS_CFG_1` carries the AVS clock mux and divider.
  `hw/ip/avsbus_controller/regs/avsbus_controller.rdl` says to gate the clocks
  entering the mux before changing either and to turn them back on afterwards,
  which is what the ones leg and the restore of this cycle do. The gate is on
  the AVS protocol clock, not the register interface, so the block keeps
  answering throughout.
* The OCTS system timer's `CTRL` does not take the all-ones and all-zeros
  patterns at all. `system_timer_octs.rdl` says `CREDIT_VAL` "must be greater
  than PULSE_WIDTH" and `PULSE_WIDTH` "must be less than CREDIT_VAL", and the
  RTL holds a run-time assertion to it. All ones makes the two equal and all
  zeros makes `CREDIT_VAL` zero, so both would break the constraint. The
  register therefore takes two constrained cycles instead, whose four patterns
  between them drive every bit of all three fields to 0 and to 1 while keeping
  `CREDIT_VAL` above `PULSE_WIDTH` in every word written, including the
  rounding the RDL gives a `PULSE_WIDTH` of 0 ("a value of 0 will be rounded up
  to 1"). Both constrained fields sit in the same half of the word, so the
  half-register writes never leave an illegal pair resident either.
* The telemetry `INTR_TEST.BUFFER_THRESHOLD` field is plain storage, so the
  generic cycle drives it and leaves the event it raises in INTR_STATUS. Each
  receiver's INTR_STATUS is therefore cleared afterwards and re-read, which is
  also the `oneToClear` contract for that register.

`log_engine/CTRL` is swept last of the log-engine registers, so the enable is
only ever set while the region and write addresses are back at their reset and
no LOG_CTRL element holds a length -- the engine has nothing to fetch and no
transfer starts. `AVS_CMD`, `AVS_INTERRUPT_CLEAR`, the telemetry counters, the
DMA transfer descriptors and the eFuse read/program data registers are not
driven here: each is a command, an event clear or a hardware-owned value with
a leaf of its own or no written-value expectation at all.
"""

from __future__ import annotations

import cocotb

from .smc_log_engine_utils import WRAP, WRAP_PY
from .smc_regblock_field_sweep_utils import (
    RegInstance,
    SmcRegblockFieldSweepSeq,
    reg_instances,
    single_reg_instance,
)

# Single-instance registers, by IP-XACT path. Each is cross-checked against its
# own `*_REG_ADDR` symbol in the generated smc_reg.py before it is driven.
_SINGLE: tuple[tuple[str, frozenset[str]], ...] = (
    ("smc_avsbus_controller/AVS_INTERRUPT_MASK", frozenset()),
    ("smc_avsbus_controller/AVS_CFG_0", frozenset()),
    ("smc_avsbus_controller/AVS_CFG_1", frozenset()),
    ("smc_avsbus_controller/AVS_CONFIG", frozenset()),
    ("smc_system_timer_octs/TIMER_PRESET_LO", frozenset()),
    ("smc_system_timer_octs/TIMER_PRESET_HI", frozenset()),
    ("smc_system_timer_octs/TIMER_GPIO_ENABLE", frozenset()),
    ("efuse_interface_ctrl/EFUSE_READ_CTRL", frozenset()),
    ("efuse_interface_ctrl/EFUSE_READ_REQ_TIMEOUT", frozenset()),
    ("efuse_interface_ctrl/EFUSE_PROGRAM_REQ_TIMEOUT", frozenset()),
    # The data and the arming bit of a fuse burn stay at their reset.
    ("efuse_interface_ctrl/EFUSE_PROGRAM_CTRL", frozenset({"efuse_data", "program_enable"})),
)

# The DMA controller's register block answers a sub-word write with an error
# response, so its configuration takes the full-width cycle instead of the
# half-register one. Its fields are still driven both ways.
_WORD_ONLY: tuple[str, ...] = ("dma_ctrl/CONFIG",)

# The OCTS system timer CTRL cycles. Each pair is (ones-substitute,
# low-substitute) in field terms; between them every bit of every field takes
# both values, and every word keeps CREDIT_VAL above the effective PULSE_WIDTH
# the RDL defines (0 rounds up to 1).
_TIMER_CTRL = "smc_system_timer_octs/CTRL"
_TIMER_CTRL_LEGS: tuple[tuple[dict[str, int], dict[str, int]], ...] = (
    (
        {"CREDIT_VAL": 0xFF, "PULSE_WIDTH": 0xFE, "STEP": 0xFF},
        {"CREDIT_VAL": 0x02, "PULSE_WIDTH": 0x00, "STEP": 0x00},
    ),
    (
        {"CREDIT_VAL": 0xFD, "PULSE_WIDTH": 0x01, "STEP": 0x00},
        {"CREDIT_VAL": 0x02, "PULSE_WIDTH": 0x00, "STEP": 0x00},
    ),
)

_TELEMETRY = "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_"
_TELEMETRY_PATH = "smc_telemetry_receiver_wrap/telemetry_receiver"
_TELEMETRY_PY = "SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_{index}__"
# INTR_ENABLE is swept before INTR_TEST, so the event the test field raises
# cannot reach the interrupt output.
_TELEMETRY_REGS = ("INTR_ENABLE", "INTR_TEST", "CTRL")

_LOG_ENGINE_PATH = "smc_uart_wrap/uart_log_engine_wrap/log_engine"
# CTRL last: the enable is only set once the addresses are back at their reset.
_LOG_ENGINE_REGS = ("LOG_REGION_SIZE", "LOG_REGION_ADDR", "LOG_WRITE_ADDR", "CTRL")

_ACCESSES_PER_CYCLE = 12
_ACCESSES_PER_WORD_CYCLE = 7
_ACCESSES_PER_INTR_CLEAR = 3


def _timer_ctrl_words(inst: RegInstance) -> tuple[tuple[int, int], ...]:
    """The constrained CTRL words, checked against the RDL relation host-side.

    `system_timer_octs.rdl` makes CREDIT_VAL greater than PULSE_WIDTH a
    software constraint, and gives a PULSE_WIDTH of 0 the effective value 1.
    Every word this sweep writes -- both legs of both cycles and the RDL reset
    it restores -- is held to that here, before any access is issued, so a
    regenerated map with different resets cannot let an illegal word through.
    """
    by_name = {field.name: field for field in inst.reg.fields}
    reset = {
        name: (inst.reg.reset_word >> field.offset) & ((1 << field.width) - 1)
        for name, field in by_name.items()
    }

    def legal(values: dict[str, int], tag: str) -> None:
        credit = values["CREDIT_VAL"]
        effective = values["PULSE_WIDTH"] or 1
        assert credit > effective, (
            f"{inst.label} [{tag}]: CREDIT_VAL {credit} is not greater than the effective "
            f"PULSE_WIDTH {effective}, which the RDL requires"
        )

    legal(reset, "rdl reset")
    out: list[tuple[int, int]] = []
    for index, (ones, low) in enumerate(_TIMER_CTRL_LEGS):
        legal(ones, f"leg {index} ones")
        legal(low, f"leg {index} low")
        out.append(
            (
                SmcRegblockFieldSweepSeq.pack_fields(inst, **ones),
                SmcRegblockFieldSweepSeq.pack_fields(inst, **low),
            )
        )
    covered_ones = 0
    covered_zero = 0
    for ones, low in out:
        covered_ones |= ones | low
        covered_zero |= (~ones | ~low) & inst.reg.rw_mask
    assert covered_ones & inst.reg.rw_mask == inst.reg.rw_mask, (
        f"{inst.label}: the constrained patterns never drive "
        f"0x{inst.reg.rw_mask & ~covered_ones:x} of the writable bits to 1"
    )
    assert covered_zero == inst.reg.rw_mask, (
        f"{inst.label}: the constrained patterns never drive "
        f"0x{inst.reg.rw_mask & ~covered_zero:x} of the writable bits to 0"
    )
    return tuple(out)


def _telemetry_spec(register: str) -> tuple[str, str, str, str]:
    return (
        f"{_TELEMETRY_PATH}/{register}",
        f"{_TELEMETRY}{register}_BASE_ADDR",
        f"{_TELEMETRY}{register}_NUM",
        f"{_TELEMETRY_PY}{register}_REG_ADDR",
    )


def _log_engine_spec(register: str) -> tuple[str, str, str, str]:
    return (
        f"{_LOG_ENGINE_PATH}/{register}",
        f"{WRAP}LOG_ENGINE_{register}_BASE_ADDR",
        f"{WRAP}LOG_ENGINE_{register}_NUM",
        f"{WRAP_PY}LOG_ENGINE_{register}_REG_ADDR",
    )


class smc_periph_regblock_sweep_test_seq(SmcRegblockFieldSweepSeq):
    """Cycle every unswept peripheral register against its RDL contract."""

    def __init__(self, name: str = "smc_periph_regblock_sweep_test_seq") -> None:
        super().__init__(name)
        self.intr_status_cleared = 0

    async def _clear_telemetry_status(self, inst: RegInstance) -> None:
        """W1C the events the INTR_TEST cycle raised, and prove they went."""
        declared = inst.reg.declared_mask
        raised = await self.csr_read(f"{inst.label}:raised", inst.addr)
        await self.csr_write(f"{inst.label}:clear", inst.addr, declared)
        cleared = await self.csr_read(f"{inst.label}:cleared", inst.addr, expected=0)
        assert cleared & declared == 0, (
            f"{inst.label} @ 0x{inst.addr:08x}: a write of 0x{declared:x} into the "
            f"`oneToClear` events left 0x{cleared & declared:x} of them set (0x{raised:x} "
            f"was pending before the write)"
        )
        self.intr_status_cleared += 1

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        singles = [(single_reg_instance(path), hold) for path, hold in _SINGLE]
        word_only = [single_reg_instance(path) for path in _WORD_ONLY]
        timer_ctrl = single_reg_instance(_TIMER_CTRL)
        timer_words = _timer_ctrl_words(timer_ctrl)
        telemetry = {name: reg_instances(*_telemetry_spec(name)) for name in _TELEMETRY_REGS}
        telemetry_status = reg_instances(*_telemetry_spec("INTR_STATUS"))
        log_engine = {name: reg_instances(*_log_engine_spec(name)) for name in _LOG_ENGINE_REGS}

        receivers = len(telemetry["CTRL"])
        wraps = len(log_engine["CTRL"])
        assert receivers and wraps, "the generated map declares no telemetry receiver or wrapper"
        assert all(len(group) == receivers for group in telemetry.values()), (
            "the generated map declares a different instance count for the telemetry registers"
        )
        assert all(len(group) == wraps for group in log_engine.values()), (
            "the generated map declares a different instance count for the log-engine registers"
        )
        assert len(telemetry_status) == receivers
        assert len({inst.addr for inst, _hold in singles}) == len(singles), (
            "two of the single-instance registers resolve to the same address"
        )

        sb_before = self.env.scoreboard.sys_axi_value_checks_seen

        for inst, hold in singles:
            await self.granule_cycle(inst, hold_fields=hold)
        for ones, low in timer_words:
            await self.granule_cycle(timer_ctrl, low_value=low, ones_value=ones)
        for inst in word_only:
            await self.word_cycle(inst)
        cocotb.log.info(
            "CHK-PERIPH-REGBLOCK-SINGLE-SWEEP: %d single-instance peripheral registers of the "
            "AVSBus controller, the OCTS system timer, the eFuse interface controller and the "
            "DMA controller each read their RDL reset, took the all-ones and all-zeros pattern "
            "of the fields the contract pins through half-register writes whose byte lanes over "
            "the other half were deasserted, drove no bit outside the declared fields, and were "
            "restored; the eFuse data and program-enable bits were held at their reset "
            "throughout, so nothing this leg wrote could arm a fuse burn; the OCTS system "
            "timer CTRL took %d constrained cycles instead, every word of which keeps "
            "CREDIT_VAL above the effective PULSE_WIDTH its RDL requires while the four "
            "patterns between them still drive every writable bit both ways; and %d "
            "register(s) whose block refuses a sub-word write took the cycle at full width",
            len(singles),
            len(_TIMER_CTRL_LEGS),
            len(word_only),
        )

        for index in range(receivers):
            for name in _TELEMETRY_REGS:
                await self.granule_cycle(telemetry[name][index])
            await self._clear_telemetry_status(telemetry_status[index])
        cocotb.log.info(
            "CHK-PERIPH-TELEMETRY-SWEEP: %d telemetry receivers each cycled %s against their "
            "RDL contract and were restored, and the events the INTR_TEST field raised were "
            "then cleared out of INTR_STATUS by a write of its declared mask, which is the "
            "`oneToClear` contract that register carries",
            receivers,
            ", ".join(_TELEMETRY_REGS),
        )

        for index in range(wraps):
            for name in _LOG_ENGINE_REGS:
                await self.granule_cycle(log_engine[name][index])
        cocotb.log.info(
            "CHK-PERIPH-LOG-ENGINE-SWEEP: %d log engines each cycled %s against their RDL "
            "contract and were restored, with CTRL last so the enable was only ever set while "
            "the region and write addresses were back at their reset and no element held a "
            "length, and nothing was fetched",
            wraps,
            ", ".join(_LOG_ENGINE_REGS),
        )

        cycles = (
            len(singles)
            + len(_TIMER_CTRL_LEGS)
            + receivers * len(_TELEMETRY_REGS)
            + wraps * len(_LOG_ENGINE_REGS)
        )
        expected = (
            cycles * _ACCESSES_PER_CYCLE
            + len(word_only) * _ACCESSES_PER_WORD_CYCLE
            + receivers * _ACCESSES_PER_INTR_CLEAR
        )
        cycles += len(word_only)
        self.assert_all_reachable(expected, "PERIPH_REGBLOCK_SWEEP")
        assert self.registers_swept == cycles, (
            f"the sweep completed {self.registers_swept} field cycles for {cycles} registers"
        )
        assert self.intr_status_cleared == receivers, (
            f"{self.intr_status_cleared} of {receivers} telemetry INTR_STATUS registers cleared"
        )
        # Predicted words: every read of a register no field of which hardware
        # drives, plus the cleared INTR_STATUS read of each receiver.
        predicted = sum(6 for inst, _hold in singles if self.volatile_mask(inst) == 0)
        if self.volatile_mask(timer_ctrl) == 0:
            predicted += 6 * len(_TIMER_CTRL_LEGS)
        predicted += sum(
            6 * receivers for name in _TELEMETRY_REGS if self.volatile_mask(telemetry[name][0]) == 0
        )
        predicted += sum(
            6 * wraps for name in _LOG_ENGINE_REGS if self.volatile_mask(log_engine[name][0]) == 0
        )
        predicted += receivers
        self.assert_value_checks(sb_before, predicted, "PERIPH_REGBLOCK_SWEEP")
        cocotb.log.info(
            "CHK-PERIPH-REGBLOCK-COMPARES: the scoreboard booked at least %d exact-value "
            "compares of its own for the reads whose whole word the RDL contract predicts, "
            "independently of this sequence's own counters",
            predicted,
        )
