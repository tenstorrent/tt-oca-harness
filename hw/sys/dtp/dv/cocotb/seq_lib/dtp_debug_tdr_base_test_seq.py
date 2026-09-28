# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Debug TDR helper base sequence for DTP tests.

Every TDR readback, pin observable, and capability comparison records named
family evidence: ``CHK-DBG-TDR`` is a decoded TDR field or a whole TDR,
``CHK-DBG-PIN`` a pin observable sampled through the driver, ``CHK-CAPS`` and
``CHK-CAPS-RO`` a capability value and its readback after a write attempt,
``CHK-TMP-PERSIST`` and ``CHK-TMP-ESCAPE`` the two TMP_STATUS bits. The
TDR accesses are driver-level read and write operations the sequence cannot
count, so scenarios attach the family checker with ``use_monitor=False``.
The SV-UVM twin is ``uvm/seq_lib/dtp_debug_tdr_base_test_seq.svh``.
"""

from __future__ import annotations

from env.dtp_dv_cfg import DTP_NUM_CLK_STOP_REQ
from env.dtp_tap_device import (
    DTP_DEBUG_CONTROL_LEN,
    DTP_EXPECTED_JTAG2AXI_CAPS,
    DTP_EXPECTED_JTAG_CAPS,
    DTP_IC_RESET_LEN,
    DTP_JTAG2AXI_CAPS_LEN,
    DTP_JTAG_CAPS_LEN,
    DTP_TMP_STATUS_LEN,
    unpack_jtag2axi_caps,
)
from env.dtp_types import DtpJtag2AxiTargetCfg, DtpJtagInstr

from .dtp_jtag_base_test_seq import dtp_jtag_base_test_seq

# Evidence IDs of the debug-TDR family, shared with the SV-UVM twin.
DBG_TDR_CHECK_ID = "CHK-DBG-TDR"
DBG_PIN_CHECK_ID = "CHK-DBG-PIN"
CAPS_CHECK_ID = "CHK-CAPS"
CAPS_RO_CHECK_ID = "CHK-CAPS-RO"
TMP_PERSIST_CHECK_ID = "CHK-TMP-PERSIST"
TMP_ESCAPE_CHECK_ID = "CHK-TMP-ESCAPE"

DBG_BOOT_STALL_BIT = 0
DBG_BOOT_STALL_OVRD_BIT = 1
DBG_CLA_CLOCK_STOP_EN_BIT = 2
DBG_JTAG_CLOCK_STOP_BIT = 3
DBG_CLA_CLOCK_STOP_BIT = 4

IC_RESET_PORT_INDEX = {
    "ext": 0,
    "sep": 1,
    "smc": 2,
}

EXPECTED_CAPS_BY_REG = {"JTAG_CAPS": DTP_EXPECTED_JTAG_CAPS, **DTP_EXPECTED_JTAG2AXI_CAPS}

# The debug-TDR pin observables and their values with DEBUG_CONTROL at 0x00
# and IC_RESET at its all-ones default (every slice enable inactive drives
# ovrd=0, ctrl_n=1).
DEBUG_OUTPUT_DEFAULTS: dict[str, int] = {
    "stop_clks": 0,
    "cla_clock_stop_en": 0,
    "jtag_boot_stall": 0,
    "jtag_boot_stall_ovrd": 0,
    "jtag_ic_reset_smc_ovrd": 0,
    "jtag_ic_reset_smc_ctrl_n": 1,
    "jtag_ic_reset_sep_ovrd": 0,
    "jtag_ic_reset_sep_ctrl_n": 1,
    "jtag_ic_reset_ext_ovrd": 0,
    "jtag_ic_reset_ext_ctrl_n": 1,
}


class dtp_debug_tdr_base_test_seq(dtp_jtag_base_test_seq):
    """Helpers for TMP_STATUS, IC_RESET, DEBUG_CONTROL, and CAPS TDRs."""

    async def snapshot_debug_outputs(self) -> dict[str, int]:
        """Sample every debug-TDR pin observable by name."""
        item = await self.sample_observables()
        return {name: item.signals[name] for name in DEBUG_OUTPUT_DEFAULTS}

    async def sample_dbg_signal(self, name: str) -> int:
        """Sample one debug-TDR pin observable by name through the driver."""
        item = await self.sample_observables()
        if name not in item.signals:
            raise KeyError(f"{name} is not exposed by the DTP JTAG driver")
        return item.signals[name]

    async def expect_dbg_signal(
        self,
        name: str,
        expected: int,
        *,
        check_id: str = DBG_PIN_CHECK_ID,
        context: str = "",
    ) -> None:
        """Sample one debug-TDR pin observable and record it."""
        observed = await self.sample_dbg_signal(name)
        self.family_check(check_id, name, observed, expected, context=context)

    def check_debug_outputs(
        self,
        check_id: str,
        observed: dict[str, int],
        expected: dict[str, int],
        *,
        context: str,
    ) -> None:
        """Record one comparison per debug-TDR pin observable."""
        for name, value in expected.items():
            self.family_check(check_id, name, observed[name], value, context=context)

    def decode_tmp_status(self, value: int) -> dict[str, int]:
        """Decode TMP_STATUS. Bit 1 reflects TMP persistence; bit 0 arms escape."""
        return {
            "raw": value & self.bit_mask(DTP_TMP_STATUS_LEN),
            "persistence": self.bit(value, 1),
            "bypass_escape": self.bit(value, 0),
        }

    def log_tmp_status(self, label: str, value: int) -> dict[str, int]:
        decoded = self.decode_tmp_status(value)
        self.log.info(
            "%s TMP_STATUS raw=0b%s persistence=%d bypass_escape=%d",
            label,
            format(decoded["raw"], "02b"),
            decoded["persistence"],
            decoded["bypass_escape"],
        )
        return decoded

    async def read_tmp_status(self, shift_value: int = 0) -> int:
        """Read TMP_STATUS[1:0]. Bit 1 is persistence, bit 0 is BYPASS_ESCAPE."""
        return (await self.read_tdr("TMP_STATUS", shift_value)) & self.bit_mask(DTP_TMP_STATUS_LEN)

    async def write_tmp_status(self, value: int) -> None:
        """Write TMP_STATUS[1:0], used to arm BYPASS_ESCAPE."""
        await self.write_tdr("TMP_STATUS", value & self.bit_mask(DTP_TMP_STATUS_LEN))

    async def check_tmp_persistence(
        self,
        label: str,
        expected: int,
        *,
        shift_value: int = 0,
        context: str = "",
    ) -> int:
        """Read TMP_STATUS, record its persistence bit, and return the raw value."""
        status = await self.read_tmp_status(shift_value=shift_value)
        decoded = self.log_tmp_status(label, status)
        self.family_check(
            TMP_PERSIST_CHECK_ID,
            "TMP_STATUS.persistence",
            decoded["persistence"],
            expected,
            context=f"{label} {context}".strip(),
        )
        return status

    async def check_tmp_escape(
        self,
        label: str,
        expected: int,
        *,
        shift_value: int = 0,
        context: str = "",
    ) -> int:
        """Read TMP_STATUS, record its BYPASS_ESCAPE bit, and return the raw value."""
        status = await self.read_tmp_status(shift_value=shift_value)
        decoded = self.log_tmp_status(label, status)
        self.family_check(
            TMP_ESCAPE_CHECK_ID,
            "TMP_STATUS.bypass_escape",
            decoded["bypass_escape"],
            expected,
            context=f"{label} {context}".strip(),
        )
        return status

    async def check_idcode_marker(self, *, context: str = "") -> int:
        """Read IDCODE and record its LSB marker bit; a routed TDR path returns 1."""
        idcode = (await self.read_idcode()).result
        self.family_check(
            DBG_TDR_CHECK_ID,
            "IDCODE.lsb",
            idcode & 0x1,
            1,
            context=f"idcode=0x{idcode:08x} {context}".strip(),
        )
        return idcode

    def decode_debug_control(self, value: int) -> dict[str, int]:
        """Decode DEBUG_CONTROL with writable bits [3:0] and CLA status bit [4]."""
        return {
            "raw": value & self.bit_mask(DTP_DEBUG_CONTROL_LEN),
            "boot_stall": self.bit(value, DBG_BOOT_STALL_BIT),
            "boot_stall_ovrd": self.bit(value, DBG_BOOT_STALL_OVRD_BIT),
            "cla_clock_stop_en": self.bit(value, DBG_CLA_CLOCK_STOP_EN_BIT),
            "jtag_clock_stop": self.bit(value, DBG_JTAG_CLOCK_STOP_BIT),
            "cla_clock_stop": self.bit(value, DBG_CLA_CLOCK_STOP_BIT),
        }

    def log_debug_control(self, label: str, value: int) -> dict[str, int]:
        decoded = self.decode_debug_control(value)
        self.log.info(
            "%s DEBUG_CONTROL raw=0x%02x cla_stop=%d jtag_stop=%d "
            "cla_stop_en=%d boot_ovrd=%d boot_stall=%d",
            label,
            decoded["raw"],
            decoded["cla_clock_stop"],
            decoded["jtag_clock_stop"],
            decoded["cla_clock_stop_en"],
            decoded["boot_stall_ovrd"],
            decoded["boot_stall"],
        )
        return decoded

    @staticmethod
    def pack_debug_control(
        *,
        boot_stall: int = 0,
        boot_stall_ovrd: int = 0,
        cla_clock_stop_en: int = 0,
        jtag_clock_stop: int = 0,
    ) -> int:
        """Pack writable DEBUG_CONTROL fields."""
        return (
            ((boot_stall & 0x1) << DBG_BOOT_STALL_BIT)
            | ((boot_stall_ovrd & 0x1) << DBG_BOOT_STALL_OVRD_BIT)
            | ((cla_clock_stop_en & 0x1) << DBG_CLA_CLOCK_STOP_EN_BIT)
            | ((jtag_clock_stop & 0x1) << DBG_JTAG_CLOCK_STOP_BIT)
        )

    async def read_debug_control(self, shift_value: int = 0) -> int:
        """Read DEBUG_CONTROL[4:0]."""
        return (await self.read_tdr("DEBUG_CONTROL", shift_value)) & self.bit_mask(
            DTP_DEBUG_CONTROL_LEN
        )

    async def write_debug_control(self, value: int) -> None:
        """Write DEBUG_CONTROL[3:0]; bit 4 is read-only CLA status."""
        await self.write_tdr("DEBUG_CONTROL", value & self.bit_mask(DTP_DEBUG_CONTROL_LEN))

    def check_debug_control_fields(
        self,
        decoded: dict[str, int],
        expected: dict[str, int],
        *,
        context: str = "",
    ) -> None:
        """Record one CHK-DBG-TDR comparison per named decoded DEBUG_CONTROL field."""
        for name, value in expected.items():
            self.family_check(
                DBG_TDR_CHECK_ID, f"DEBUG_CONTROL.{name}", decoded[name], value, context=context
            )

    def decode_ic_reset(self, value: int) -> dict[str, object]:
        """Decode IC_RESET TDR using OSS default EXT, SEP, SMC one-port order."""
        decoded_ports = {}
        for name, index in IC_RESET_PORT_INDEX.items():
            decoded_ports[name] = {
                "reset_enable": self.bit(value, 1 + (2 * index)),
                "reset_control": self.bit(value, 2 + (2 * index)),
            }
        return {
            "raw": value & self.bit_mask(DTP_IC_RESET_LEN),
            "reset_hold": self.bit(value, 0),
            "ports": decoded_ports,
        }

    def log_ic_reset(self, label: str, value: int) -> dict[str, object]:
        decoded = self.decode_ic_reset(value)
        self.log.info(
            "%s IC_RESET raw=0b%s reset_hold=%d",
            label,
            format(decoded["raw"], "07b"),
            decoded["reset_hold"],
        )
        ports = decoded["ports"]
        for name in ("ext", "sep", "smc"):
            port = ports[name]
            self.log.info(
                "  %s: reset_enable=%d reset_control=%d expected_ovrd=%d",
                name.upper(),
                port["reset_enable"],
                port["reset_control"],
                0 if port["reset_enable"] else 1,
            )
        return decoded

    @staticmethod
    def pack_ic_reset(
        *,
        reset_hold: int,
        reset_enable: dict[str, int],
        reset_control: dict[str, int],
    ) -> int:
        """Pack the IC_RESET TDR for one-port SMC/SEP/EXT default slices."""
        value = reset_hold & 0x1
        for name, index in IC_RESET_PORT_INDEX.items():
            value |= (reset_enable.get(name, 1) & 0x1) << (1 + (2 * index))
            value |= (reset_control.get(name, 1) & 0x1) << (2 + (2 * index))
        return value & ((1 << DTP_IC_RESET_LEN) - 1)

    async def read_ic_reset(self, shift_value: int = 0) -> int:
        """Read the IC_RESET TDR."""
        return (await self.read_tdr("IC_RESET", shift_value)) & self.bit_mask(DTP_IC_RESET_LEN)

    async def write_ic_reset(
        self,
        *,
        reset_hold: int,
        reset_enable: dict[str, int],
        reset_control: dict[str, int],
    ) -> int:
        """Write IC_RESET and return the packed value."""
        value = self.pack_ic_reset(
            reset_hold=reset_hold,
            reset_enable=reset_enable,
            reset_control=reset_control,
        )
        await self.write_tdr("IC_RESET", value)
        return value

    async def read_caps_tdr(self, reg: str) -> int:
        """Read a JTAG_CAPS or JTAG2AXI_CAPS TDR."""
        value = await self.read_tdr(reg)
        width = DTP_JTAG_CAPS_LEN if reg == "JTAG_CAPS" else DTP_JTAG2AXI_CAPS_LEN
        return value & self.bit_mask(width)

    def expect_caps_value(
        self,
        reg: str,
        value: int,
        *,
        check_id: str = CAPS_CHECK_ID,
        context: str = "packed value",
    ) -> None:
        """Record a CAPS TDR against the centralized expected value."""
        self.family_check(check_id, reg, value, EXPECTED_CAPS_BY_REG[reg], context=context)

    def decode_jtag_caps(self, value: int) -> dict[str, int]:
        """Decode JTAG_CAPS by the "JTAG Capabilities" table of the PTAP document."""
        return {
            "num_xtrig_int_ct": self.field(value, 54, 6),
            "num_xtrig_ctp": self.field(value, 48, 6),
            "num_extra_staps": self.field(value, 44, 4),
            "stap_io_en": self.bit(value, 43),
            "sep_dbg_en": self.bit(value, 42),
            "smc_dbg_en": self.bit(value, 41),
            "num_smc_ic_reset": self.field(value, 33, 8),
            "num_sep_ic_reset": self.field(value, 25, 8),
            "num_ext_ic_reset": self.field(value, 17, 8),
            "ic_reset_en": self.bit(value, 16),
            "tmp_en": self.bit(value, 15),
            "runbist_en": self.bit(value, 14),
            "highz_en": self.bit(value, 13),
            "clamp_en": self.bit(value, 12),
            "intest_en": self.bit(value, 11),
            "extest_pulse_en": self.bit(value, 10),
            "extest_train_en": self.bit(value, 9),
            "bsr_en": self.bit(value, 8),
            "och_ver": self.field(value, 0, 8),
        }

    def log_jtag_caps(self, value: int) -> dict[str, int]:
        decoded = self.decode_jtag_caps(value)
        self.log.info("JTAG_CAPS raw=0x%015x", value)
        for name, field_value in decoded.items():
            self.log.info("  %-18s = %d", name, field_value)
        return decoded

    def decode_jtag2axi_caps(self, value: int) -> dict[str, int]:
        """Decode a *_JTAG2AXI_CAPS value; ``data_width_bits`` expands ``data_size``."""
        fields = unpack_jtag2axi_caps(value)
        return {
            "raw": value & self.bit_mask(DTP_JTAG2AXI_CAPS_LEN),
            **fields,
            "data_width_bits": 8 << fields["data_size"],
        }

    def log_jtag2axi_caps(self, reg: str, value: int) -> dict[str, int]:
        decoded = self.decode_jtag2axi_caps(value)
        self.log.info("%s raw=0x%04x", reg, decoded["raw"])
        self.log.info("  rd_pl_depth    = %d", decoded["rd_pl_depth"])
        self.log.info("  wr_pl_depth    = %d", decoded["wr_pl_depth"])
        self.log.info("  data_size      = %d", decoded["data_size"])
        self.log.info("  data_width_bits= %d", decoded["data_width_bits"])
        self.log.info("  addr_size      = %d", decoded["addr_size"])
        self.log.info(
            "  bus_type       = %d (%s)",
            decoded["bus_type"],
            "AXI4-Lite" if decoded["bus_type"] else "AXI4",
        )
        return decoded

    async def check_caps_multi_read(
        self,
        reg: str,
        *,
        count: int = 5,
        check_id: str = CAPS_CHECK_ID,
    ) -> int:
        """Read a CAPS TDR repeatedly, record each read against the first, return the first."""
        self.log.info("Checking %s multi-read consistency (%d reads)", reg, count)
        values = []
        for idx in range(1, count + 1):
            value = await self.read_caps_tdr(reg)
            values.append(value)
            self.log.info("  %s read %d/%d = 0x%x", reg, idx, count, value)
        expected = values[0]
        for idx, value in enumerate(values, start=1):
            self.family_check(
                check_id, f"{reg} multi-read", value, expected, context=f"read={idx}/{count}"
            )
        return expected

    def caps_write_patterns(self, width: int, label: str) -> list[int]:
        """Return directed and seeded random write-attempt patterns for RO CAPS TDRs."""
        mask = self.bit_mask(width)
        rng = self.rng(f"{label}_ro_patterns")
        patterns = [
            0,
            mask,
            0x5555_5555_5555_5555 & mask,
            0xAAAA_AAAA_AAAA_AAAA & mask,
            0x1234_5678_9ABC_DEF0 & mask,
        ]
        for _ in range(self.random_count):
            patterns.append(rng.getrandbits(width) & mask)
        return list(dict.fromkeys(patterns))

    async def check_caps_read_only_patterns(
        self,
        reg: str,
        width: int,
        *,
        check_id: str = CAPS_RO_CHECK_ID,
    ) -> int:
        """Attempt multiple writes into a read-only CAPS TDR and record each readback."""
        initial = await self.read_caps_tdr(reg)
        self.log.info("Checking %s read-only behavior from initial=0x%x", reg, initial)
        patterns = self.caps_write_patterns(width, reg)
        for idx, pattern in enumerate(patterns, start=1):
            self.log_iteration(idx, len(patterns), "%s write-attempt pattern=0x%x", reg, pattern)
            await self.write_tdr(reg, pattern)
            readback = await self.read_caps_tdr(reg)
            self.family_check(
                check_id,
                f"{reg} read-only",
                readback,
                initial,
                context=f"pattern=0x{pattern:x}",
            )
        return initial

    async def check_caps_after_instruction_switch(self, reg: str, value: int) -> None:
        """Re-read a CAPS TDR after IDCODE and after BYPASS and record it against ``value``."""
        for idx, instr in enumerate([DtpJtagInstr.IDCODE, DtpJtagInstr.BYPASS_3F], start=1):
            self.log_iteration(idx, 2, "load %s before re-reading %s", instr.name, reg)
            await self.load_ir(instr)
            reread = await self.read_caps_tdr(reg)
            self.family_check(
                CAPS_CHECK_ID, f"{reg} after instruction switch", reread, value, context=instr.name
            )

    async def check_jtag2axi_caps(self, target: DtpJtag2AxiTargetCfg) -> int:
        """Run the common JTAG2AXI_CAPS field, stability, and RO checks for one bridge."""
        reg = target.caps_reg
        value = await self.read_caps_tdr(reg)
        decoded = self.log_jtag2axi_caps(reg, value)
        self.expect_caps_value(reg, value)

        expected_fields = {
            "bus_type": target.bus_type,
            "addr_size": target.addr_width,
            "data_width_bits": target.data_width,
            "rd_pl_depth": target.rd_pl_depth,
            "wr_pl_depth": target.wr_pl_depth,
        }
        for name, expected in expected_fields.items():
            self.family_check(CAPS_CHECK_ID, f"{reg}.{name}", decoded[name], expected)

        self.family_check(
            CAPS_CHECK_ID, f"{reg} multi-read value", await self.check_caps_multi_read(reg), value
        )
        self.family_check(
            CAPS_CHECK_ID,
            f"{reg} read-only sweep",
            await self.check_caps_read_only_patterns(reg, DTP_JTAG2AXI_CAPS_LEN),
            value,
        )
        await self.check_caps_after_instruction_switch(reg, value)
        return value

    async def wait_for_signal_value(
        self,
        name: str,
        expected: int,
        *,
        cycles: int = 6,
        context: str = "",
        check_id: str = DBG_PIN_CHECK_ID,
    ) -> None:
        """Poll a sampled observable across clk_i cycles and record the last sample.

        `stop_clks` passes through a 2-flop synchronizer and an output flop, so
        clock-stop tests must poll instead of assuming a fixed immediate value.
        The sample that ends the poll is the evidence either way; a mismatch
        after the budget records a FAIL.
        """
        last = await self.sample_dbg_signal(name)
        polled = 0
        while last != expected and polled < cycles:
            await self.wait_sys_cycles(1)
            last = await self.sample_dbg_signal(name)
            polled += 1
        self.family_check(
            check_id, name, last, expected, context=f"{context} polled_cycles={polled}".strip()
        )

    async def set_clk_stop_requests(self, value: int, cycles: int = 4) -> None:
        """Drive the CLA clock-stop request vector on dtp_tb_if."""
        assert value < (1 << DTP_NUM_CLK_STOP_REQ), (
            f"xtrig_clk_stop_req value 0x{value:x} exceeds {DTP_NUM_CLK_STOP_REQ} bits"
        )
        self.cfg.tb_if.ctrl.xtrig_clk_stop_req.value = value
        await self.wait_sys_cycles(cycles)
