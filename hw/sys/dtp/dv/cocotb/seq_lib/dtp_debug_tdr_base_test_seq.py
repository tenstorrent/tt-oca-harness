# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Debug TDR helper base sequence for DTP tests."""

from __future__ import annotations

from env.dtp_tap_device import (
    DTP_DEBUG_CONTROL_LEN,
    DTP_EXPECTED_JTAG2AXI_CAPS,
    DTP_EXPECTED_JTAG_CAPS,
    DTP_IC_RESET_LEN,
    DTP_JTAG2AXI_CAPS_LEN,
    DTP_JTAG2AXI_RD_PL_DEPTH,
    DTP_JTAG2AXI_WR_PL_DEPTH,
    DTP_JTAG_CAPS_LEN,
    DTP_NUM_CLK_STOP_REQ,
    DTP_TMP_STATUS_LEN,
    unpack_jtag2axi_caps,
)
from env.dtp_types import DtpJtag2AxiTargetCfg, DtpJtagInstr

from .dtp_jtag_base_test_seq import dtp_jtag_base_test_seq

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


class dtp_debug_tdr_base_test_seq(dtp_jtag_base_test_seq):
    """Helpers for TMP_STATUS, IC_RESET, DEBUG_CONTROL, and CAPS TDRs."""

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

    def expect_caps_value(self, reg: str, value: int) -> None:
        """Compare a CAPS TDR against the centralized expected value."""
        expected = EXPECTED_CAPS_BY_REG[reg]
        self.assert_equal(reg, value, expected)

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

    async def check_caps_multi_read(self, reg: str, *, count: int = 5) -> int:
        """Read a CAPS TDR repeatedly and verify the value is stable."""
        self.log.info("Checking %s multi-read consistency (%d reads)", reg, count)
        values = []
        for idx in range(1, count + 1):
            value = await self.read_caps_tdr(reg)
            values.append(value)
            self.log.info("  %s read %d/%d = 0x%x", reg, idx, count, value)
        expected = values[0]
        for idx, value in enumerate(values, start=1):
            self.assert_equal(f"{reg} multi-read", value, expected, context=f"read={idx}")
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

    async def check_caps_read_only_patterns(self, reg: str, width: int) -> int:
        """Attempt multiple writes into a read-only CAPS TDR and verify no change."""
        initial = await self.read_caps_tdr(reg)
        self.log.info("Checking %s read-only behavior from initial=0x%x", reg, initial)
        patterns = self.caps_write_patterns(width, reg)
        for idx, pattern in enumerate(patterns, start=1):
            self.log_iteration(idx, len(patterns), "%s write-attempt pattern=0x%x", reg, pattern)
            await self.write_tdr(reg, pattern)
            readback = await self.read_caps_tdr(reg)
            self.assert_equal(
                f"{reg} read-only",
                readback,
                initial,
                context=f"pattern=0x{pattern:x}",
            )
        return initial

    async def check_jtag2axi_caps(self, target: DtpJtag2AxiTargetCfg) -> int:
        """Run the common JTAG2AXI_CAPS field, stability, and RO checks for one bridge."""
        reg = target.caps_reg
        value = await self.read_caps_tdr(reg)
        decoded = self.log_jtag2axi_caps(reg, value)
        self.expect_caps_value(reg, value)

        self.assert_equal(f"{reg}.bus_type", decoded["bus_type"], target.bus_type)
        self.assert_equal(f"{reg}.addr_size", decoded["addr_size"], target.addr_width)
        self.assert_equal(f"{reg}.data_width_bits", decoded["data_width_bits"], target.data_width)
        self.assert_equal(f"{reg}.rd_pl_depth", decoded["rd_pl_depth"], DTP_JTAG2AXI_RD_PL_DEPTH)
        self.assert_equal(f"{reg}.wr_pl_depth", decoded["wr_pl_depth"], DTP_JTAG2AXI_WR_PL_DEPTH)

        self.assert_equal(f"{reg} multi-read value", await self.check_caps_multi_read(reg), value)
        self.assert_equal(
            f"{reg} read-only sweep",
            await self.check_caps_read_only_patterns(reg, DTP_JTAG2AXI_CAPS_LEN),
            value,
        )

        for idx, instr in enumerate([DtpJtagInstr.IDCODE, DtpJtagInstr.BYPASS_3F], start=1):
            self.log_iteration(idx, 2, "load %s before re-reading CAPS", instr.name)
            await self.load_ir(instr)
            reread = await self.read_caps_tdr(reg)
            self.assert_equal(f"{reg} after instruction switch", reread, value, instr.name)
        return value

    async def wait_for_signal_value(
        self,
        name: str,
        expected: int,
        *,
        cycles: int = 6,
        context: str = "",
    ) -> None:
        """Poll a sampled observable across clk_i cycles.

        `stop_clks` passes through a 2-flop synchronizer and an output flop, so
        clock-stop tests must poll instead of assuming a fixed immediate value.
        """
        last = None
        for cycle in range(cycles + 1):
            item = await self.sample_observables()
            assert name in item.signals, f"{name} is not exposed by the DTP JTAG driver"
            last = item.signals[name]
            if last == expected:
                self.log.info(
                    "CHECK %-36s expected=%d observed=%d after %d cycles %s",
                    name,
                    expected,
                    last,
                    cycle,
                    f"({context})" if context else "",
                )
                return
            if cycle < cycles:
                await self.wait_sys_cycles(1)
        assert last == expected, (
            f"{name}: expected {expected}, got {last} after {cycles} cycles"
            f"{f' ({context})' if context else ''}"
        )

    async def set_clk_stop_requests(self, value: int, cycles: int = 4) -> None:
        """Drive the CLA clock-stop request vector on dtp_tb_if."""
        assert value < (1 << DTP_NUM_CLK_STOP_REQ), (
            f"xtrig_clk_stop_req value 0x{value:x} exceeds {DTP_NUM_CLK_STOP_REQ} bits"
        )
        self.cfg.tb_if.ctrl.xtrig_clk_stop_req.value = value
        await self.wait_sys_cycles(cycles)
