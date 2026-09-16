# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Generic Firmware Test Runner.

This module provides a generic cocotb test that can run any firmware image
and check for standardized pass/fail criteria. Firmware tests use the
protocol defined in test_common.h to report results.

Protocol (KMCSR Registers at base 0x14000):
    TB_RESULT    @ 0x110 : 0=fail, 1=pass (KMCSR_TB_RESULT_REG_ADDR)
    TB_SIGNATURE @ 0x114 : 0x600D600D (pass) or 0xBADBADBA (fail) (KMCSR_TB_SIGNATURE_REG_ADDR)
    TB_ERRCODE   @ 0x118 : Optional error code (KMCSR_TB_ERRCODE_REG_ADDR)
    TB_SUBTEST   @ 0x11C : Current subtest number (KMCSR_TB_SUBTEST_REG_ADDR)
    TB_CMD       @ 0x120 : Command from FW to TB (KMCSR_TB_CMD_REG_ADDR)
    TB_CMD_ARG   @ 0x124 : Command argument (KMCSR_TB_CMD_ARG_REG_ADDR)
    TB_CMD_STATUS@ 0x128 : Status from TB to FW (KMCSR_TB_CMD_STATUS_REG_ADDR)
    TB_CMD_RESULT@ 0x12C : Result from TB to FW (KMCSR_TB_CMD_RESULT_REG_ADDR)

Usage:
    # Run a specific firmware test:
    TEST=test_firmware make run SIM_ARGS="+ROM_HEX_FILE=path/to/test.rom.hex"

    # Or use the FW_TEST variable for convenience:
    FW_TEST=my_test make run_fw
"""

import os
import random
import sys
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

# Import generated register constants from PeakRDL
# Add the registers directory to the path
_registers_dir = Path(__file__).parent.parent.parent / "regs" / "gen" / "py"
if str(_registers_dir) not in sys.path:
    sys.path.insert(0, str(_registers_dir))

# Import KMCSR and mailbox register constants (from RDL-generated key_manager_reg)
from key_manager_reg import (
    MAILBOX_KM_KM_READ_DATA_REG_ADDR,
    KM_CSR_OTP_READ_LOCK_REG_reg_t,
)

# Import SEP mailbox register offsets (relative to SEP mailbox base, from RDL-generated C header)
from km_mailbox_sep_reg import (
    SEP_CTRL_REG_OFFSET,
    SEP_IRQ_ENABLE_REG_OFFSET,
    SEP_IRQ_STATUS_REG_OFFSET,
    SEP_READ_DATA_REG_OFFSET,
    SEP_STATUS_REG_OFFSET,
    SEP_WRITE_DATA_REG_OFFSET,
    SEP_WRITE_SEPARATOR_REG_OFFSET,
)

# Signatures (must match test_common.h - these are test protocol constants, not registers)
TEST_PASS_SIGNATURE = 0x600D600D
TEST_FAIL_SIGNATURE = 0xBADBADBA
TEST_RUNNING_SIG = 0x52554E4E  # "RUNN"

# Testbench commands (must match test_common.h)
TB_CMD_NOP = 0x00000000
TB_CMD_ROM_PARITY_EN = 0x00000001
TB_CMD_ROM_PARITY_DIS = 0x00000002
TB_CMD_SRAM_PARITY_EN = 0x00000003
TB_CMD_SRAM_PARITY_DIS = 0x00000004
TB_CMD_SRAM_READ_RAW = 0x00000005
TB_CMD_SEP_MBOX_WRITE = 0x00000006
TB_CMD_MONITOR_EN = 0x00000007
TB_CMD_MONITOR_DIS = 0x00000008
TB_CMD_SEP_MBOX_IRQ_ENABLE = 0x00000009
TB_CMD_SEP_MBOX_READ = 0x0000000A
TB_CMD_SEP_MBOX_IRQ_CHECK = 0x0000000B
TB_CMD_SEP_MBOX_WRITE_WITH_RESP = 0x0000000C
TB_CMD_KM_MBOX_READ_WITH_RESP = 0x0000000D
TB_CMD_TIMEOUT_SET = 0x0000000E
TB_CMD_SEP_MBOX_READ_WITH_RESP = 0x0000000F
TB_CMD_SEP_MBOX_STATUS_READ = 0x00000010  # Read SEP mailbox STATUS register
TB_CMD_SEP_MBOX_STATUS_WRITE = 0x00000011  # Write SEP mailbox STATUS register (W1C)
TB_CMD_SEP_MBOX_CTRL_WRITE = 0x00000012  # Write SEP mailbox CTRL register
TB_CMD_VUART_VERIFY = 0x00000013  # Verify VUART received expected string (arg = SRAM byte address of null-terminated string)
TB_CMD_SEP_MBOX_IRQ_STATUS_READ = 0x00000014  # Read SEP mailbox IRQ_STATUS register
TB_CMD_SEP_MBOX_IRQ_STATUS_WRITE = 0x00000015  # Write SEP mailbox IRQ_STATUS register (W1C)
TB_CMD_DRBG_SET_NEXT_VALUE = (
    0x0000001A  # Set next 32-bit value for DRBG AXI-Stream (arg = value); result = 1
)
TB_CMD_DRBG_GET_NEXT_VALUE = (
    0x0000001B  # Get value last set for DRBG (for verification); result = 32-bit value
)
TB_CMD_DRBG_SET_SEED = 0x0000001C  # Set seed for deterministic DRBG (arg = 32-bit seed); result = 1
TB_CMD_DRBG_STOP = (
    0x0000001D  # Stop sending DRBG data after current beat (TVALID held until TREADY); result = 1
)
TB_CMD_DRBG_START = 0x0000001E  # Resume sending DRBG data; result = 1
TB_CMD_CHECK_RECOVERABLE_ERR = (
    0x0000001F  # Testbench samples recoverable_err; result = 1 if set, 0 if clear
)
TB_CMD_CHECK_UNRECOVERABLE_RESTART = (
    0x00000020  # Ask TB: was CPU restarted due to unrecoverable fault? result = 1 if yes, 0 if no
)
TB_CMD_OTP_WRITE = (
    0x00000021  # TB drives otp_data_i port with known pattern (read-through, no strobe); result = 1
)
TB_CMD_WIPE_TRIGGER = 0x00000022  # TB asserts wipe_state_i for one cycle; result = 1
TB_CMD_SEP_MBOX_WRITE_SEPARATOR_WRITE = 0x00000023  # Write SEP mailbox WRITE_SEPARATOR register
TB_CMD_KEY_SHARE_READ = 0x00000024  # Read key share word from hwif_out; arg=[11:8]=engine,[4]=share,[3:0]=word; result=32-bit value
TB_CMD_GET_UNRECOVERABLE_FAULT_CODE = 0x00000025  # Get fault code captured from SEP mailbox before unrecoverable reset; result = 32-bit fault code
TB_CMD_INJECT_SPURIOUS_IRQ = (
    0x00000026  # Force spurious IRQ bits into PicoRV32; arg = bitmask; result = 1
)
TB_CMD_UNRECOVERABLE_WATCH_CTRL = (
    0x00000027  # Arm/disarm unrecoverable watcher; arg=1 arm, 0 disarm; result = 1
)
TB_CMD_GET_CYCLE_COUNT = 0x00000028  # Snapshot current testbench cycle counter; result = cycles
TB_CMD_KM_ASYNC_RESET = 0x00000029  # Pulse top-level async reset (cold_rst_n); result = 1
TB_CMD_DRBG_TVALID_GLITCH = 0x0000002A  # One-shot: assert TVALID for 1 cycle then drop without TREADY (STREAM_ERR injection); result = 1
TB_CMD_DRBG_QUEUE_BEAT = (
    0x0000002B  # Queue one DRBG beat: arg[3:0]=TSTRB; tdata from last SET_NEXT_VALUE; result = 1
)
TB_CMD_KM_WARM_RESET = 0x0000002C  # Pulse warm_rst_n for MIN_RESET_CYCLES+2 cycles; result = 1
TB_CMD_OTP_WRITE_CHANGED = (
    0x0000002D  # Drive changed 256-bit OTP patterns (triggers OTP_CHANGE IRQ); result = 1
)
TB_CMD_OTP_WRITE_SIGINT = 0x0000002E  # Drive corrupted dual-rail on one 256-bit field (triggers OTP_SIGINT IRQ); arg = field's OTP_READ_LOCK bit position; result = 1
TB_CMD_SEP_MBOX_DRAIN_CTRL = 0x0000002F  # Arm/disarm autonomous SEP outbound-FIFO drainer (models SEP draining KM->SEP); arg=1 arm, 0 disarm; result = 1
TB_CMD_ABR_SK_LOAD = 0x00000030  # Inject shared-key into ABR reg block: arg=word_index (0-7); pre-fill tb_abr_sk_load_data via DRBG_SET_NEXT_VALUE then call with arg=0xFF to assert hwset; result = 1
TB_CMD_ABR_SK_IRQ_STATUS_READ = 0x00000031  # Read ABR ML-KEM shared-key IRQ status (abr_mlkem_sharedkey_irq signal); result = 0 or 1
TB_CMD_KM_MBOX_READ_DURING_SEP_FLUSH = 0x00000032  # SEP CTRL.FLUSH then KM READ_DATA AR on the flush-active cycle; result = 1 if R arrives
# Testbench command status
TB_STATUS_IDLE = 0x00000000
TB_STATUS_ACK = 0x00000001
TB_STATUS_ERR = 0xFFFFFFFF

# OTP field names by OTP_READ_LOCK bit position, from the generated register
# layout.  TB_CMD_OTP_WRITE_SIGINT carries that bit position as its argument, so
# firmware selects a field with KM_CSR__OTP_READ_LOCK_REG__<FIELD>_bp and both
# sides name the field through the same generated collateral.
OTP_LOCK_FIELDS = tuple(
    name for name, *_ in KM_CSR_OTP_READ_LOCK_REG_reg_t._fields_ if name != "rsvd"
)

# Those of them that are 256-bit dual-rail members of km_otp_data_t; life_cycle
# and demotion are narrow encoded fields driven separately.
OTP_DR_FIELDS = tuple(n for n in OTP_LOCK_FIELDS if n not in ("life_cycle", "demotion"))

# First byte of each field's 32-byte ramp pattern.  Each field gets a distinct
# base in both sets so a swapped or mis-decoded readback cannot look correct,
# and every changed value differs from its own baseline.
OTP_PATTERN_BASE = {
    "chiplet_uid": 0x00,
    "sip_uid": 0x20,
    "sys_uid": 0x40,
    "class_key": 0x60,
    "sep_chiplet_id": 0x10,
    "sep_sip_id": 0x30,
    "sep_sys_id": 0x50,
}

OTP_PATTERN_BASE_CHANGED = {
    "chiplet_uid": 0x80,
    "sip_uid": 0xA0,
    "sys_uid": 0xC0,
    "class_key": 0xE0,
    "sep_chiplet_id": 0x90,
    "sep_sip_id": 0xB0,
    "sep_sys_id": 0xD0,
}


async def reset_dut(dut, cycles=20):
    """Assert and deassert cold reset (AASD) for the DUT."""
    dut.cold_rst_n.value = 0
    await ClockCycles(dut.clk, cycles)
    dut.cold_rst_n.value = 1
    await ClockCycles(dut.clk, 2)


def drive_otp_idle(dut):
    """Drive otp_data to a valid all-zeros dual-rail idle state.

    In production, sep_crypto.sv drives otp_data_i via prim_diff_encode_multi,
    which produces valid dual-rail output ({~value, value}) even when the eFuse
    payload is all-zeros.  The block-level testbench must replicate this so that
    the differential decoders in km_csr.sv see a valid encoding from the first
    clock edge after reset — otherwise the all-zero reset default fails the
    complement check and fires a spurious OTP_SIGINT IRQ before any firmware
    test sends TB_CMD_OTP_WRITE.

    Idle encoding (all fields carry a payload of 0):
      life_cycle[7:0]         : {~4'd0, 4'd0} = 8'hF0
      demotion_state_1[1:0]   : {~1'b0, 1'b0} = 2'b10
      demotion_state_2[1:0]   : {~1'b0, 1'b0} = 2'b10
      256-bit fields          : {256{1'b1}, 256{1'b0}}  (512-bit)
    """
    try:
        otp = dut.otp_data
        otp.life_cycle.value = 0xF0  # {~4'd0, 4'd0}
        if hasattr(otp, "demotion_state_1"):
            otp.demotion_state_1.value = 0b10  # {~1'b0, 1'b0}
            otp.demotion_state_2.value = 0b10
        # {256{1'b1}, 256{1'b0}} = all-ones complement over all-zeros value
        dr_zero = ((1 << 256) - 1) << 256
        for name in OTP_DR_FIELDS:
            getattr(otp, name).value = dr_zero
    except AttributeError:
        pass  # otp_data port not present in this elaboration


async def warm_reset_dut(dut, cycles=22):
    """Pulse warm reset (synchronous) on the DUT.

    Holds warm_rst_n low for at least MIN_RESET_CYCLES (default 16 in
    km_reset_conditioner) plus a few extra cycles so the conditioner's
    internal counter has time to propagate.  The conditioner itself stretches
    the reset to MIN_RESET_CYCLES, so this just needs to be long enough for
    the conditioner to detect and latch the request.
    """
    dut.warm_rst_n.value = 0
    await ClockCycles(dut.clk, cycles)
    dut.warm_rst_n.value = 1
    await ClockCycles(dut.clk, 2)


class KmcsrRegisterInterface:
    """Interface to KMCSR test protocol registers via hierarchical probing.

    This class provides access to the test protocol registers in KMCSR.
    Testbench reads firmware-written values and writes status/results.
    """

    def __init__(self, dut):
        """Initialize with hierarchical paths into the KMCSR register block.

        Args:
            dut: cocotb DUT handle for the Key Manager testbench top-level.
        """
        self.dut = dut
        # Hierarchical path to the register storage in km_csr_reg
        # Path: tb_key_manager -> u_key_manager -> u_kmcsr -> u_km_csr_reg -> field_storage
        self._reg_storage = dut.u_key_manager.u_kmcsr.u_km_csr_reg.field_storage
        # Hierarchical path to hwif_in for testbench-written registers
        self._hwif_in = dut.u_key_manager.u_kmcsr.hwif_in

    def read_tb_result(self):
        """Read TB_RESULT register (firmware writes, testbench reads)."""
        try:
            return int(self._reg_storage.TB_RESULT.result.value.value)
        except Exception:
            return 0

    def read_tb_signature(self):
        """Read TB_SIGNATURE register."""
        try:
            return int(self._reg_storage.TB_SIGNATURE.signature.value.value)
        except Exception:
            return 0

    def read_tb_errcode(self):
        """Read TB_ERRCODE register."""
        try:
            return int(self._reg_storage.TB_ERRCODE.errcode.value.value)
        except Exception:
            return 0

    def read_tb_subtest(self):
        """Read TB_SUBTEST register."""
        try:
            return int(self._reg_storage.TB_SUBTEST.subtest.value.value)
        except Exception:
            return 0

    def read_tb_cmd(self):
        """Read TB_CMD register (command from firmware)."""
        try:
            return int(self._reg_storage.TB_CMD.cmd.value.value)
        except Exception:
            return 0

    def read_tb_cmd_arg(self):
        """Read TB_CMD_ARG register (argument from firmware)."""
        try:
            return int(self._reg_storage.TB_CMD_ARG.arg.value.value)
        except Exception:
            return 0

    def write_tb_cmd_status(self, value):
        """Write TB_CMD_STATUS register (status to firmware)."""
        self._hwif_in.TB_CMD_STATUS.status.next.value = value

    def write_tb_cmd_result(self, value):
        """Write TB_CMD_RESULT register (result to firmware)."""
        self._hwif_in.TB_CMD_RESULT.result.next.value = value

    def write_tb_cmd(self, value):
        """Write TB_CMD register (to clear command)."""
        self._hwif_in.TB_CMD.cmd.next.value = value

    def write_vuart_print_enable(self, enable):
        """Write VUART_STATUS.PRINT_ENABLE bit (testbench controls printing)."""
        self._hwif_in.VUART_STATUS.print_enable.next.value = 1 if enable else 0


class TestbenchCommandHandler:
    """Handles commands from firmware via the KMCSR test protocol registers.

    This allows firmware to request testbench operations like error injection.
    Firmware writes commands to TB_CMD, and this handler executes them and
    writes acknowledgments to TB_CMD_STATUS.
    """

    def __init__(
        self,
        dut,
        kmcsr_regs,
        monitor=None,
        timeout_ref=None,
        current_cycles_ref=None,
        vuart_monitor=None,
        enable_unrecoverable_watch=False,
    ):
        """Initialize command handler and register all supported commands.

        Args:
            dut: cocotb DUT handle.
            kmcsr_regs: KmcsrRegisterInterface for reading/writing test protocol registers.
            monitor: Optional CpuMemoryMonitor for enable/disable commands.
            timeout_ref: Mutable list ``[int]`` holding the current timeout in cycles.
            current_cycles_ref: Mutable list ``[int]`` holding the current cycle count.
            vuart_monitor: Optional VuartMonitor for VUART verification commands.
            enable_unrecoverable_watch: If True, arm the unrecoverable watcher
                at startup.
        """
        self.dut = dut
        self.regs = kmcsr_regs
        self.monitor = monitor
        self.timeout_ref = timeout_ref  # Reference to mutable timeout (list with single element)
        self.current_cycles_ref = (
            current_cycles_ref  # Reference to mutable cycle count (list with single element)
        )
        self.vuart_monitor = vuart_monitor  # Reference to VUART monitor for verification
        self._running = False
        self.commands_processed = 0
        self._enable_unrecoverable_watch = enable_unrecoverable_watch
        self._unrecoverable_watch_armed = enable_unrecoverable_watch

        # Command handler registry
        self._handlers = {
            TB_CMD_ROM_PARITY_EN: self._handle_rom_parity_en,
            TB_CMD_ROM_PARITY_DIS: self._handle_rom_parity_dis,
            TB_CMD_SRAM_PARITY_EN: self._handle_sram_parity_en,
            TB_CMD_SRAM_PARITY_DIS: self._handle_sram_parity_dis,
            TB_CMD_SRAM_READ_RAW: self._handle_sram_read_raw,
            TB_CMD_SEP_MBOX_WRITE: self._handle_sep_mbox_write,
            TB_CMD_MONITOR_EN: self._handle_monitor_en,
            TB_CMD_MONITOR_DIS: self._handle_monitor_dis,
            TB_CMD_SEP_MBOX_IRQ_ENABLE: self._handle_sep_mbox_irq_enable,
            TB_CMD_SEP_MBOX_READ: self._handle_sep_mbox_read,
            TB_CMD_SEP_MBOX_IRQ_CHECK: self._handle_sep_mbox_irq_check,
            TB_CMD_SEP_MBOX_WRITE_WITH_RESP: self._handle_sep_mbox_write_with_resp,
            TB_CMD_KM_MBOX_READ_WITH_RESP: self._handle_km_mbox_read_with_resp,
            TB_CMD_TIMEOUT_SET: self._handle_timeout_set,
            TB_CMD_SEP_MBOX_READ_WITH_RESP: self._handle_sep_mbox_read_with_resp,
            TB_CMD_SEP_MBOX_STATUS_READ: self._handle_sep_mbox_status_read,
            TB_CMD_SEP_MBOX_STATUS_WRITE: self._handle_sep_mbox_status_write,
            TB_CMD_SEP_MBOX_CTRL_WRITE: self._handle_sep_mbox_ctrl_write,
            TB_CMD_VUART_VERIFY: self._handle_vuart_verify,
            TB_CMD_SEP_MBOX_IRQ_STATUS_READ: self._handle_sep_mbox_irq_status_read,
            TB_CMD_SEP_MBOX_IRQ_STATUS_WRITE: self._handle_sep_mbox_irq_status_write,
            TB_CMD_DRBG_SET_NEXT_VALUE: self._handle_drbg_set_next_value,
            TB_CMD_DRBG_GET_NEXT_VALUE: self._handle_drbg_get_next_value,
            TB_CMD_DRBG_SET_SEED: self._handle_drbg_set_seed,
            TB_CMD_DRBG_STOP: self._handle_drbg_stop,
            TB_CMD_DRBG_START: self._handle_drbg_start,
            TB_CMD_DRBG_TVALID_GLITCH: self._handle_drbg_tvalid_glitch,
            TB_CMD_CHECK_RECOVERABLE_ERR: self._handle_check_recoverable_err,
            TB_CMD_CHECK_UNRECOVERABLE_RESTART: self._handle_check_unrecoverable_restart,
            TB_CMD_OTP_WRITE: self._handle_otp_write,
            TB_CMD_WIPE_TRIGGER: self._handle_wipe_trigger,
            TB_CMD_SEP_MBOX_WRITE_SEPARATOR_WRITE: self._handle_sep_mbox_write_separator_write,
            TB_CMD_KEY_SHARE_READ: self._handle_key_share_read,
            TB_CMD_GET_UNRECOVERABLE_FAULT_CODE: self._handle_get_unrecoverable_fault_code,
            TB_CMD_INJECT_SPURIOUS_IRQ: self._handle_inject_spurious_irq,
            TB_CMD_UNRECOVERABLE_WATCH_CTRL: self._handle_unrecoverable_watch_ctrl,
            TB_CMD_GET_CYCLE_COUNT: self._handle_get_cycle_count,
            TB_CMD_KM_ASYNC_RESET: self._handle_km_async_reset,
            TB_CMD_DRBG_QUEUE_BEAT: self._handle_drbg_queue_beat,
            TB_CMD_KM_WARM_RESET: self._handle_km_warm_reset,
            TB_CMD_OTP_WRITE_CHANGED: self._handle_otp_write_changed,
            TB_CMD_OTP_WRITE_SIGINT: self._handle_otp_write_sigint,
            TB_CMD_SEP_MBOX_DRAIN_CTRL: self._handle_sep_mbox_drain_ctrl,
            TB_CMD_ABR_SK_LOAD: self._handle_abr_sk_load,
            TB_CMD_ABR_SK_IRQ_STATUS_READ: self._handle_abr_sk_irq_status_read,
            TB_CMD_KM_MBOX_READ_DURING_SEP_FLUSH: self._handle_km_mbox_read_during_sep_flush,
        }
        self._outbound_drain_armed = (
            False  # When armed, autonomously drain the SEP outbound FIFO (models the SEP)
        )
        self._unrecoverable_reset_done = (
            False  # True after we saw unrecoverable_err and reset DUT (for unrecoverable tests)
        )
        self._captured_unrecov_fault_code = (
            0  # Fault code read from SEP mailbox before unrecoverable reset
        )
        # DRBG: deterministic "random" from fixed seed for reproducible tests
        self._drbg_rng = random.Random(0x9E37_79B9)  # Fixed seed for deterministic DRBG data
        self._drbg_next_value = self._drbg_rng.getrandbits(32)
        self._drbg_stop_pending = False  # Stop requested; wait for TREADY before cutting off
        self._drbg_stopped = False  # Not sending (TVALID=0)
        self._drbg_glitch_pending = (
            False  # One-shot STREAM_ERR injection: assert TVALID 1 cycle then drop before TREADY
        )
        self._drbg_beat_queue = []  # List of (value, tstrb) tuples queued by TB_CMD_DRBG_QUEUE_BEAT

    async def start(self):
        """Start monitoring for commands and DRBG driver."""
        self._running = True
        cocotb.start_soon(self._command_loop())
        cocotb.start_soon(self._drbg_driver_loop())
        cocotb.start_soon(self._unrecoverable_watch_loop())
        cocotb.start_soon(self._outbound_drain_loop())

    def stop(self):
        """Stop monitoring."""
        self._running = False

    async def _command_loop(self):
        """Background task to monitor and handle commands."""
        while self._running:
            await RisingEdge(self.dut.clk)

            # Check for pending command
            cmd = self.regs.read_tb_cmd()
            if cmd != TB_CMD_NOP:
                arg = self.regs.read_tb_cmd_arg()
                self.dut._log.info(f"[TB CMD] Received command 0x{cmd:08X} arg=0x{arg:08X}")

                # Execute command
                handler = self._handlers.get(cmd)
                if handler:
                    try:
                        result = await handler(arg)
                        self.regs.write_tb_cmd_result(result)
                        self.regs.write_tb_cmd_status(TB_STATUS_ACK)
                        self.dut._log.info(f"[TB CMD] Command acknowledged, result=0x{result:08X}")
                    except Exception as e:
                        self.dut._log.error(f"[TB CMD] Command failed: {e}")
                        self.regs.write_tb_cmd_status(TB_STATUS_ERR)
                else:
                    self.dut._log.warning(f"[TB CMD] Unknown command: 0x{cmd:08X}")
                    self.regs.write_tb_cmd_status(TB_STATUS_ERR)

                # Clear command (testbench clears it)
                self.regs.write_tb_cmd(TB_CMD_NOP)
                self.commands_processed += 1

    async def _handle_rom_parity_en(self, arg):
        """Enable ROM parity error injection."""
        if hasattr(self.dut, "rom_parity_err_inject"):
            self.dut.rom_parity_err_inject.value = 1
            self.dut._log.info("[TB CMD] ROM parity error injection ENABLED")
            return 1
        else:
            self.dut._log.warning("[TB CMD] rom_parity_err_inject signal not found")
            return 0

    async def _handle_rom_parity_dis(self, arg):
        """Disable ROM parity error injection."""
        if hasattr(self.dut, "rom_parity_err_inject"):
            self.dut.rom_parity_err_inject.value = 0
            self.dut._log.info("[TB CMD] ROM parity error injection DISABLED")
            return 1
        else:
            return 0

    async def _handle_sram_parity_en(self, arg):
        """Enable SRAM parity error injection."""
        if hasattr(self.dut, "sram_parity_err_inject"):
            self.dut.sram_parity_err_inject.value = 1
            self.dut._log.info("[TB CMD] SRAM parity error injection ENABLED")
            return 1
        else:
            self.dut._log.warning("[TB CMD] sram_parity_err_inject signal not found")
            return 0

    async def _handle_sram_parity_dis(self, arg):
        """Disable SRAM parity error injection."""
        if hasattr(self.dut, "sram_parity_err_inject"):
            self.dut.sram_parity_err_inject.value = 0
            self.dut._log.info("[TB CMD] SRAM parity error injection DISABLED")
            return 1
        else:
            return 0

    async def _handle_sram_read_raw(self, arg):
        """Read raw SRAM data (before descrambling).

        Args:
            arg: Physical SRAM word address (13 bits, 0-8191)
                 Firmware calculates the scrambled address if scrambler is enabled.
                 Testbench simply reads from SRAM at the provided address.

        Returns:
            Raw 32-bit data value from SRAM model
        """
        try:
            # Access SRAM memory array from testbench
            # Path: tb_key_manager -> sram_mem array
            SRAM_WORDS = 8192

            if arg >= SRAM_WORDS:
                self.dut._log.error(
                    f"[TB CMD] Invalid SRAM word address: {arg} (must be 0-{SRAM_WORDS - 1})"
                )
                return 0

            physical_addr = arg

            # Read from SRAM memory array at physical address
            # Firmware has already calculated the scrambled address if needed
            sram_value = int(self.dut.sram_mem[physical_addr].value)

            self.dut._log.info(
                f"[TB CMD] SRAM raw read: physical_addr=0x{physical_addr:03X}, "
                f"data=0x{sram_value:08X}"
            )
            return sram_value
        except Exception as e:
            self.dut._log.error(f"[TB CMD] SRAM read failed: {e}")
            import traceback

            self.dut._log.error(traceback.format_exc())
            return 0

    async def _handle_sep_mbox_write(self, arg):
        """Write data to SEP mailbox inbound FIFO (SEP->KM direction).

        This simulates a SEP-side write to the mailbox WRITE_DATA register.
        Uses generated register offset from PeakRDL.

        Args:
            arg: 32-bit data word to write to SEP mailbox inbound FIFO

        Returns:
            1 if successful, 0 on error
        """
        from cocotb.triggers import RisingEdge

        try:
            AXI_OKAY = 0b00

            data = arg & 0xFFFFFFFF

            self.dut._log.info(
                f"[TB CMD] Writing 0x{data:08X} to SEP mailbox (offset 0x{SEP_WRITE_DATA_REG_OFFSET:03X})"
            )

            # Initialize SEP AXI signals if not already initialized
            if not hasattr(self.dut, "sep_awvalid"):
                self.dut._log.error("[TB CMD] SEP AXI signals not found in testbench")
                return 0

            # Drive AW and W channels simultaneously (AXI-Lite allows independent handshakes)
            self.dut.sep_awvalid.value = 1
            self.dut.sep_awaddr.value = SEP_WRITE_DATA_REG_OFFSET
            self.dut.sep_awprot.value = 0

            self.dut.sep_wvalid.value = 1
            self.dut.sep_wdata.value = data
            self.dut.sep_wstrb.value = 0xF  # All bytes

            self.dut.sep_bready.value = 1

            # Wait for AW and W handshakes (can happen in any order)
            max_cycles = 50
            cycles = 0
            aw_done = False
            w_done = False

            while cycles < max_cycles and (not aw_done or not w_done):
                await RisingEdge(self.dut.clk)
                cycles += 1

                if not aw_done and int(self.dut.sep_awready.value) == 1:
                    aw_done = True
                    self.dut.sep_awvalid.value = 0  # Deassert after handshake

                if not w_done and int(self.dut.sep_wready.value) == 1:
                    w_done = True
                    self.dut.sep_wvalid.value = 0  # Deassert after handshake

            if not aw_done or not w_done:
                self.dut._log.error(f"[TB CMD] SEP write handshake timeout after {cycles} cycles")
                self.dut.sep_awvalid.value = 0
                self.dut.sep_wvalid.value = 0
                self.dut.sep_bready.value = 0
                return 0

            # Wait for B response
            while cycles < max_cycles:
                await RisingEdge(self.dut.clk)
                cycles += 1
                if int(self.dut.sep_bvalid.value) == 1:
                    resp = int(self.dut.sep_bresp.value)
                    self.dut.sep_bready.value = 0
                    if resp == AXI_OKAY:
                        self.dut._log.info("[TB CMD] SEP mailbox write successful")
                        return 1
                    else:
                        self.dut._log.error(f"[TB CMD] SEP mailbox write error response: {resp}")
                        return 0

            # Timeout
            self.dut._log.error("[TB CMD] SEP mailbox write timeout waiting for B response")
            self.dut.sep_bready.value = 0
            return 0

        except Exception as e:
            self.dut._log.error(f"[TB CMD] SEP mailbox write failed: {e}")
            import traceback

            self.dut._log.error(traceback.format_exc())
            # Clean up signals
            try:
                self.dut.sep_awvalid.value = 0
                self.dut.sep_wvalid.value = 0
                self.dut.sep_bready.value = 0
            except:
                pass
            return 0

    async def _handle_monitor_en(self, arg):
        """Enable CPU/memory monitoring."""
        if self.monitor:
            self.monitor.enable()
            return 1
        else:
            self.dut._log.warning("[TB CMD] Monitor not available")
            return 0

    async def _handle_monitor_dis(self, arg):
        """Disable CPU/memory monitoring."""
        if self.monitor:
            self.monitor.disable()
            return 1
        else:
            return 0

    async def _handle_sep_mbox_irq_enable(self, arg):
        """Enable or disable SEP mailbox IRQ.

        This writes to the SEP mailbox IRQ_ENABLE register via SEP AXI interface.

        Args:
            arg: IRQ enable value (bit 0 = outbound_read_data_avail_en)

        Returns:
            1 if successful, 0 on error
        """
        from cocotb.triggers import RisingEdge

        try:
            AXI_OKAY = 0b00

            enable_value = arg & 0xFFFFFFFF

            self.dut._log.info(f"[TB CMD] Setting SEP mailbox IRQ_ENABLE to 0x{enable_value:08X}")

            # Initialize SEP AXI signals if not already initialized
            if not hasattr(self.dut, "sep_awvalid"):
                self.dut._log.error("[TB CMD] SEP AXI signals not found in testbench")
                return 0

            # Drive AW and W channels simultaneously
            self.dut.sep_awvalid.value = 1
            self.dut.sep_awaddr.value = SEP_IRQ_ENABLE_REG_OFFSET
            self.dut.sep_awprot.value = 0

            self.dut.sep_wvalid.value = 1
            self.dut.sep_wdata.value = enable_value
            self.dut.sep_wstrb.value = 0xF  # All bytes

            self.dut.sep_bready.value = 1

            # Wait for AW and W handshakes
            max_cycles = 50
            cycles = 0
            aw_done = False
            w_done = False

            while cycles < max_cycles and (not aw_done or not w_done):
                await RisingEdge(self.dut.clk)
                cycles += 1

                if not aw_done and int(self.dut.sep_awready.value) == 1:
                    aw_done = True
                    self.dut.sep_awvalid.value = 0

                if not w_done and int(self.dut.sep_wready.value) == 1:
                    w_done = True
                    self.dut.sep_wvalid.value = 0

            if not aw_done or not w_done:
                self.dut._log.error(
                    f"[TB CMD] SEP IRQ enable handshake timeout after {cycles} cycles"
                )
                self.dut.sep_awvalid.value = 0
                self.dut.sep_wvalid.value = 0
                self.dut.sep_bready.value = 0
                return 0

            # Wait for B response
            while cycles < max_cycles:
                await RisingEdge(self.dut.clk)
                cycles += 1
                if int(self.dut.sep_bvalid.value) == 1:
                    resp = int(self.dut.sep_bresp.value)
                    self.dut.sep_bready.value = 0
                    if resp == AXI_OKAY:
                        self.dut._log.info("[TB CMD] SEP mailbox IRQ_ENABLE set successfully")
                        return 1
                    else:
                        self.dut._log.error(
                            f"[TB CMD] SEP mailbox IRQ_ENABLE error response: {resp}"
                        )
                        return 0

            # Timeout
            self.dut._log.error("[TB CMD] SEP mailbox IRQ_ENABLE timeout waiting for B response")
            self.dut.sep_bready.value = 0
            return 0

        except Exception as e:
            self.dut._log.error(f"[TB CMD] SEP mailbox IRQ_ENABLE failed: {e}")
            import traceback

            self.dut._log.error(traceback.format_exc())
            try:
                self.dut.sep_awvalid.value = 0
                self.dut.sep_wvalid.value = 0
                self.dut.sep_bready.value = 0
            except:
                pass
            return 0

    async def _handle_sep_mbox_read(self, arg):
        """Read data from SEP mailbox outbound FIFO (KM->SEP direction).

        This reads from the SEP mailbox READ_DATA register via SEP AXI interface.

        Args:
            arg: Not used (0)

        Returns:
            Read data value (32-bit) or 0 on error
        """
        from cocotb.triggers import RisingEdge

        try:
            AXI_OKAY = 0b00

            self.dut._log.info("[TB CMD] Reading from SEP mailbox READ_DATA")

            # Initialize SEP AXI signals if not already initialized
            if not hasattr(self.dut, "sep_arvalid"):
                self.dut._log.error("[TB CMD] SEP AXI signals not found in testbench")
                return 0

            # Phase 1: AR channel - address phase
            self.dut.sep_arvalid.value = 1
            self.dut.sep_araddr.value = SEP_READ_DATA_REG_OFFSET
            self.dut.sep_arprot.value = 0
            self.dut.sep_rready.value = 0  # Not ready for data yet

            # Wait for AR handshake
            max_cycles = 50
            cycles = 0
            ar_done = False

            while cycles < max_cycles and not ar_done:
                await RisingEdge(self.dut.clk)
                cycles += 1
                if int(self.dut.sep_arready.value) == 1:
                    ar_done = True

            # Deassert ar_valid after handshake
            self.dut.sep_arvalid.value = 0

            if not ar_done:
                self.dut._log.error(
                    f"[TB CMD] SEP mailbox read AR handshake timeout after {cycles} cycles"
                )
                return 0

            # Phase 2: R channel - data phase
            self.dut.sep_rready.value = 1  # Ready to accept data

            # Wait for R handshake
            while cycles < max_cycles:
                await RisingEdge(self.dut.clk)
                cycles += 1

                if int(self.dut.sep_rvalid.value) == 1:
                    data = int(self.dut.sep_rdata.value)
                    resp = int(self.dut.sep_rresp.value)
                    self.dut.sep_rready.value = 0
                    if resp == AXI_OKAY:
                        self.dut._log.info(f"[TB CMD] SEP mailbox read successful: 0x{data:08X}")
                        return data
                    else:
                        self.dut._log.error(f"[TB CMD] SEP mailbox read error response: {resp}")
                        return 0

            # Timeout
            self.dut._log.error("[TB CMD] SEP mailbox read timeout waiting for R response")
            self.dut.sep_rready.value = 0
            return 0

        except Exception as e:
            self.dut._log.error(f"[TB CMD] SEP mailbox read failed: {e}")
            import traceback

            self.dut._log.error(traceback.format_exc())
            try:
                self.dut.sep_arvalid.value = 0
                self.dut.sep_rready.value = 0
            except:
                pass
            return 0

    async def _handle_sep_mbox_read_with_resp(self, arg):
        """Read data from SEP mailbox outbound FIFO and return AXI response code.

        This reads from the SEP mailbox READ_DATA register via SEP AXI interface
        and returns both the data and the AXI response code for underflow testing.

        Args:
            arg: Not used (0)

        Returns:
            Packed result: [31:8] = data, [7:0] = AXI response code (0=OKAY, 2=SLVERR, 3=DECERR)
        """
        from cocotb.triggers import RisingEdge

        try:
            AXI_OKAY = 0b00
            AXI_SLVERR = 0b10
            AXI_DECERR = 0b11

            self.dut._log.info("[TB CMD] Reading from SEP mailbox READ_DATA with response")

            # Initialize SEP AXI signals if not already initialized
            if not hasattr(self.dut, "sep_arvalid"):
                self.dut._log.error("[TB CMD] SEP AXI signals not found in testbench")
                return AXI_DECERR << 0  # Return DECERR in response field

            # Phase 1: AR channel - address phase
            self.dut.sep_arvalid.value = 1
            self.dut.sep_araddr.value = SEP_READ_DATA_REG_OFFSET
            self.dut.sep_arprot.value = 0
            self.dut.sep_rready.value = 0  # Not ready for data yet

            # Wait for AR handshake
            max_cycles = 50
            cycles = 0
            ar_done = False

            while cycles < max_cycles and not ar_done:
                await RisingEdge(self.dut.clk)
                cycles += 1
                if int(self.dut.sep_arready.value) == 1:
                    ar_done = True

            # Deassert ar_valid after handshake
            self.dut.sep_arvalid.value = 0

            if not ar_done:
                self.dut._log.error(
                    f"[TB CMD] SEP mailbox read AR handshake timeout after {cycles} cycles"
                )
                return AXI_DECERR << 0  # Return DECERR

            # Phase 2: R channel - data phase
            self.dut.sep_rready.value = 1  # Ready to accept data

            # Wait for R handshake
            while cycles < max_cycles:
                await RisingEdge(self.dut.clk)
                cycles += 1

                if int(self.dut.sep_rvalid.value) == 1:
                    data = int(self.dut.sep_rdata.value)
                    resp = int(self.dut.sep_rresp.value)
                    self.dut.sep_rready.value = 0

                    # Pack result: [31:8] = data, [7:0] = response code
                    result = (data << 8) | resp

                    if resp == AXI_OKAY:
                        self.dut._log.info(
                            f"[TB CMD] SEP mailbox read successful: data=0x{data:08X}, resp={resp}"
                        )
                    elif resp == AXI_SLVERR:
                        self.dut._log.info(
                            f"[TB CMD] SEP mailbox read SLVERR: data=0x{data:08X}, resp={resp}"
                        )
                    else:
                        self.dut._log.info(
                            f"[TB CMD] SEP mailbox read error: data=0x{data:08X}, resp={resp}"
                        )

                    return result

            # Timeout
            self.dut._log.error("[TB CMD] SEP mailbox read timeout waiting for R response")
            await RisingEdge(self.dut.clk)
            self.dut.sep_rready.value = 0
            return AXI_DECERR << 0  # Return DECERR on timeout

        except Exception as e:
            self.dut._log.error(f"[TB CMD] SEP mailbox read with response failed: {e}")
            import traceback

            self.dut._log.error(traceback.format_exc())
            try:
                if hasattr(self.dut, "sep_arvalid"):
                    self.dut.sep_arvalid.value = 0
                if hasattr(self.dut, "sep_rready"):
                    self.dut.sep_rready.value = 0
            except:
                pass
            return AXI_DECERR << 0  # Return DECERR on error

    async def _handle_sep_mbox_status_read(self, arg, quiet=False):
        """Read SEP mailbox STATUS register.

        This reads from the SEP mailbox STATUS register via SEP AXI interface.

        Args:
            arg: Not used (0)

        Returns:
            STATUS register value (32-bit) or 0 on error
        """
        from cocotb.triggers import RisingEdge

        try:
            AXI_OKAY = 0b00

            if not quiet:
                self.dut._log.info("[TB CMD] Reading SEP mailbox STATUS register")

            # Initialize SEP AXI signals if not already initialized
            if not hasattr(self.dut, "sep_arvalid"):
                self.dut._log.error("[TB CMD] SEP AXI signals not found in testbench")
                return 0

            # Phase 1: AR channel - address phase
            self.dut.sep_arvalid.value = 1
            self.dut.sep_araddr.value = SEP_STATUS_REG_OFFSET
            self.dut.sep_arprot.value = 0
            self.dut.sep_rready.value = 0  # Not ready for data yet

            # Wait for AR handshake
            max_cycles = 50
            cycles = 0
            ar_done = False

            while cycles < max_cycles and not ar_done:
                await RisingEdge(self.dut.clk)
                cycles += 1
                if int(self.dut.sep_arready.value) == 1:
                    ar_done = True

            # Deassert ar_valid after handshake
            self.dut.sep_arvalid.value = 0

            if not ar_done:
                self.dut._log.error(
                    f"[TB CMD] SEP mailbox STATUS read AR handshake timeout after {cycles} cycles"
                )
                return 0

            # Phase 2: R channel - data phase
            self.dut.sep_rready.value = 1  # Ready to accept data

            # Wait for R handshake
            cycles = 0
            r_done = False
            status_value = 0

            while cycles < max_cycles and not r_done:
                await RisingEdge(self.dut.clk)
                cycles += 1
                if int(self.dut.sep_rvalid.value) == 1:
                    resp = int(self.dut.sep_rresp.value)
                    if resp == AXI_OKAY:
                        status_value = int(self.dut.sep_rdata.value)
                        r_done = True
                    else:
                        self.dut._log.error(
                            f"[TB CMD] SEP mailbox STATUS read error response: {resp}"
                        )
                        self.dut.sep_rready.value = 0
                        return 0

            # Deassert r_ready after handshake
            self.dut.sep_rready.value = 0

            if not r_done:
                self.dut._log.error(
                    f"[TB CMD] SEP mailbox STATUS read R handshake timeout after {cycles} cycles"
                )
                return 0

            if not quiet:
                self.dut._log.info(f"[TB CMD] SEP mailbox STATUS: 0x{status_value:08X}")
            return status_value

        except Exception as e:
            self.dut._log.error(f"[TB CMD] SEP mailbox STATUS read failed: {e}")
            import traceback

            self.dut._log.error(traceback.format_exc())
            try:
                self.dut.sep_arvalid.value = 0
                self.dut.sep_rready.value = 0
            except:
                pass
            return 0

    async def _handle_sep_mbox_irq_status_read(self, arg):
        """Read SEP mailbox IRQ_STATUS register.

        This reads from the SEP mailbox IRQ_STATUS register via SEP AXI interface.
        Used by firmware to verify FLUSHED_BY_KM after KM performs a flush.

        Args:
            arg: Not used (0)

        Returns:
            IRQ_STATUS register value (32-bit) or 0 on error
        """
        from cocotb.triggers import RisingEdge

        try:
            AXI_OKAY = 0b00

            self.dut._log.info("[TB CMD] Reading SEP mailbox IRQ_STATUS register")

            if not hasattr(self.dut, "sep_arvalid"):
                self.dut._log.error("[TB CMD] SEP AXI signals not found in testbench")
                return 0

            self.dut.sep_arvalid.value = 1
            self.dut.sep_araddr.value = SEP_IRQ_STATUS_REG_OFFSET
            self.dut.sep_arprot.value = 0
            self.dut.sep_rready.value = 0

            max_cycles = 50
            cycles = 0
            ar_done = False
            while cycles < max_cycles and not ar_done:
                await RisingEdge(self.dut.clk)
                cycles += 1
                if int(self.dut.sep_arready.value) == 1:
                    ar_done = True

            self.dut.sep_arvalid.value = 0

            if not ar_done:
                self.dut._log.error(
                    "[TB CMD] SEP mailbox IRQ_STATUS read AR handshake timeout after %d cycles",
                    cycles,
                )
                return 0

            self.dut.sep_rready.value = 1
            cycles = 0
            r_done = False
            irq_status_value = 0
            while cycles < max_cycles and not r_done:
                await RisingEdge(self.dut.clk)
                cycles += 1
                if int(self.dut.sep_rvalid.value) == 1:
                    resp = int(self.dut.sep_rresp.value)
                    if resp == AXI_OKAY:
                        irq_status_value = int(self.dut.sep_rdata.value)
                        r_done = True
                    else:
                        self.dut._log.error(
                            "[TB CMD] SEP mailbox IRQ_STATUS read error response: %d", resp
                        )
                        self.dut.sep_rready.value = 0
                        return 0

            self.dut.sep_rready.value = 0

            if not r_done:
                self.dut._log.error(
                    "[TB CMD] SEP mailbox IRQ_STATUS read R handshake timeout after %d cycles",
                    cycles,
                )
                return 0

            self.dut._log.info("[TB CMD] SEP mailbox IRQ_STATUS: 0x%08X", irq_status_value)
            return irq_status_value

        except Exception as e:
            self.dut._log.error("[TB CMD] SEP mailbox IRQ_STATUS read failed: %s", e)
            import traceback

            self.dut._log.error(traceback.format_exc())
            try:
                self.dut.sep_arvalid.value = 0
                self.dut.sep_rready.value = 0
            except Exception:
                pass
            return 0

    async def _handle_sep_mbox_irq_status_write(self, arg):
        """Write SEP mailbox IRQ_STATUS register (W1C).

        This writes to the SEP mailbox IRQ_STATUS register via SEP AXI interface.
        Used for clearing IRQ status bits (write-1-to-clear).

        Args:
            arg: Value to write to IRQ_STATUS register (bits to clear)

        Returns:
            1 if successful, 0 on error
        """
        from cocotb.triggers import RisingEdge

        try:
            AXI_OKAY = 0b00

            write_value = arg & 0xFFFFFFFF

            self.dut._log.info(
                "[TB CMD] Writing 0x%08X to SEP mailbox IRQ_STATUS register (W1C)", write_value
            )

            if not hasattr(self.dut, "sep_awvalid"):
                self.dut._log.error("[TB CMD] SEP AXI signals not found in testbench")
                return 0

            self.dut.sep_awvalid.value = 1
            self.dut.sep_awaddr.value = SEP_IRQ_STATUS_REG_OFFSET
            self.dut.sep_awprot.value = 0

            self.dut.sep_wvalid.value = 1
            self.dut.sep_wdata.value = write_value
            self.dut.sep_wstrb.value = 0xF

            self.dut.sep_bready.value = 1

            max_cycles = 50
            cycles = 0
            aw_done = False
            w_done = False

            while cycles < max_cycles and (not aw_done or not w_done):
                await RisingEdge(self.dut.clk)
                cycles += 1

                if not aw_done and int(self.dut.sep_awready.value) == 1:
                    aw_done = True
                    self.dut.sep_awvalid.value = 0

                if not w_done and int(self.dut.sep_wready.value) == 1:
                    w_done = True
                    self.dut.sep_wvalid.value = 0

            if not aw_done or not w_done:
                self.dut._log.error(
                    "[TB CMD] SEP mailbox IRQ_STATUS write handshake timeout after %d cycles",
                    cycles,
                )
                self.dut.sep_awvalid.value = 0
                self.dut.sep_wvalid.value = 0
                self.dut.sep_bready.value = 0
                return 0

            while cycles < max_cycles:
                await RisingEdge(self.dut.clk)
                cycles += 1
                if int(self.dut.sep_bvalid.value) == 1:
                    resp = int(self.dut.sep_bresp.value)
                    self.dut.sep_bready.value = 0
                    if resp == AXI_OKAY:
                        self.dut._log.info("[TB CMD] SEP mailbox IRQ_STATUS write successful")
                        return 1
                    self.dut._log.error(
                        "[TB CMD] SEP mailbox IRQ_STATUS write error response: %d", resp
                    )
                    return 0

            self.dut._log.error(
                "[TB CMD] SEP mailbox IRQ_STATUS write timeout waiting for B response"
            )
            self.dut.sep_bready.value = 0
            return 0

        except Exception as e:
            self.dut._log.error("[TB CMD] SEP mailbox IRQ_STATUS write failed: %s", e)
            import traceback

            self.dut._log.error(traceback.format_exc())
            try:
                self.dut.sep_awvalid.value = 0
                self.dut.sep_wvalid.value = 0
                self.dut.sep_bready.value = 0
            except Exception:
                pass
            return 0

    async def _handle_sep_mbox_status_write(self, arg):
        """Write SEP mailbox STATUS register.

        This writes to the SEP mailbox STATUS register via SEP AXI interface.
        Used primarily for clearing status bits (write-1-to-clear).

        Args:
            arg: Value to write to STATUS register

        Returns:
            1 if successful, 0 on error
        """
        from cocotb.triggers import RisingEdge

        try:
            AXI_OKAY = 0b00

            write_value = arg & 0xFFFFFFFF

            self.dut._log.info(
                f"[TB CMD] Writing 0x{write_value:08X} to SEP mailbox STATUS register"
            )

            # Initialize SEP AXI signals if not already initialized
            if not hasattr(self.dut, "sep_awvalid"):
                self.dut._log.error("[TB CMD] SEP AXI signals not found in testbench")
                return 0

            # Drive AW and W channels simultaneously
            self.dut.sep_awvalid.value = 1
            self.dut.sep_awaddr.value = SEP_STATUS_REG_OFFSET
            self.dut.sep_awprot.value = 0

            self.dut.sep_wvalid.value = 1
            self.dut.sep_wdata.value = write_value
            self.dut.sep_wstrb.value = 0xF  # All bytes

            self.dut.sep_bready.value = 1

            # Wait for AW and W handshakes
            max_cycles = 50
            cycles = 0
            aw_done = False
            w_done = False

            while cycles < max_cycles and (not aw_done or not w_done):
                await RisingEdge(self.dut.clk)
                cycles += 1

                if not aw_done and int(self.dut.sep_awready.value) == 1:
                    aw_done = True
                    self.dut.sep_awvalid.value = 0

                if not w_done and int(self.dut.sep_wready.value) == 1:
                    w_done = True
                    self.dut.sep_wvalid.value = 0

            if not aw_done or not w_done:
                self.dut._log.error(
                    f"[TB CMD] SEP mailbox STATUS write handshake timeout after {cycles} cycles"
                )
                self.dut.sep_awvalid.value = 0
                self.dut.sep_wvalid.value = 0
                self.dut.sep_bready.value = 0
                return 0

            # Wait for B response
            while cycles < max_cycles:
                await RisingEdge(self.dut.clk)
                cycles += 1
                if int(self.dut.sep_bvalid.value) == 1:
                    resp = int(self.dut.sep_bresp.value)
                    self.dut.sep_bready.value = 0
                    if resp == AXI_OKAY:
                        self.dut._log.info("[TB CMD] SEP mailbox STATUS write successful")
                        return 1
                    else:
                        self.dut._log.error(
                            f"[TB CMD] SEP mailbox STATUS write error response: {resp}"
                        )
                        return 0

            # Timeout
            self.dut._log.error("[TB CMD] SEP mailbox STATUS write timeout waiting for B response")
            self.dut.sep_bready.value = 0
            return 0

        except Exception as e:
            self.dut._log.error(f"[TB CMD] SEP mailbox STATUS write failed: {e}")
            import traceback

            self.dut._log.error(traceback.format_exc())
            try:
                self.dut.sep_awvalid.value = 0
                self.dut.sep_wvalid.value = 0
                self.dut.sep_bready.value = 0
            except:
                pass
            return 0

    async def _handle_sep_mbox_irq_check(self, arg):
        """Check SEP mailbox IRQ status.

        This reads the mbox_irq_to_sep output signal from the DUT.

        Args:
            arg: Not used (0)

        Returns:
            IRQ status (1=asserted, 0=deasserted) or 0 on error
        """
        try:
            # Check if mbox_irq_to_sep signal exists
            if not hasattr(self.dut, "mbox_irq_to_sep"):
                self.dut._log.error("[TB CMD] mbox_irq_to_sep signal not found in testbench")
                return 0

            # Read IRQ signal value
            irq_status = int(self.dut.mbox_irq_to_sep.value)
            self.dut._log.info(f"[TB CMD] SEP mailbox IRQ status: {irq_status}")
            return irq_status

        except Exception as e:
            self.dut._log.error(f"[TB CMD] SEP mailbox IRQ check failed: {e}")
            import traceback

            self.dut._log.error(traceback.format_exc())
            return 0

    async def _handle_sep_mbox_ctrl_write(self, arg):
        """Write SEP mailbox CTRL register.

        This writes to the SEP mailbox CTRL register via SEP AXI interface.
        Used for configuring underflow/overflow response behavior.

        Args:
            arg: Value to write to CTRL register

        Returns:
            1 if successful, 0 on error
        """
        from cocotb.triggers import RisingEdge

        try:
            AXI_OKAY = 0b00

            write_value = arg & 0xFFFFFFFF

            self.dut._log.info(f"[TB CMD] Writing 0x{write_value:08X} to SEP mailbox CTRL register")

            # Initialize SEP AXI signals if not already initialized
            if not hasattr(self.dut, "sep_awvalid"):
                self.dut._log.error("[TB CMD] SEP AXI signals not found in testbench")
                return 0

            # Drive AW and W channels simultaneously
            self.dut.sep_awvalid.value = 1
            self.dut.sep_awaddr.value = SEP_CTRL_REG_OFFSET
            self.dut.sep_awprot.value = 0

            self.dut.sep_wvalid.value = 1
            self.dut.sep_wdata.value = write_value
            self.dut.sep_wstrb.value = 0xF  # All bytes

            self.dut.sep_bready.value = 1

            # Wait for AW and W handshakes
            max_cycles = 50
            cycles = 0
            aw_done = False
            w_done = False

            while cycles < max_cycles and (not aw_done or not w_done):
                await RisingEdge(self.dut.clk)
                cycles += 1

                if not aw_done and int(self.dut.sep_awready.value) == 1:
                    aw_done = True
                    self.dut.sep_awvalid.value = 0

                if not w_done and int(self.dut.sep_wready.value) == 1:
                    w_done = True
                    self.dut.sep_wvalid.value = 0

            if not aw_done or not w_done:
                self.dut._log.error(
                    f"[TB CMD] SEP mailbox CTRL write handshake timeout after {cycles} cycles"
                )
                self.dut.sep_awvalid.value = 0
                self.dut.sep_wvalid.value = 0
                self.dut.sep_bready.value = 0
                return 0

            # Wait for B response
            while cycles < max_cycles:
                await RisingEdge(self.dut.clk)
                cycles += 1
                if int(self.dut.sep_bvalid.value) == 1:
                    resp = int(self.dut.sep_bresp.value)
                    self.dut.sep_bready.value = 0
                    if resp == AXI_OKAY:
                        self.dut._log.info("[TB CMD] SEP mailbox CTRL write successful")
                        return 1
                    else:
                        self.dut._log.error(
                            f"[TB CMD] SEP mailbox CTRL write error response: {resp}"
                        )
                        return 0

            # Timeout
            self.dut._log.error("[TB CMD] SEP mailbox CTRL write timeout waiting for B response")
            self.dut.sep_bready.value = 0
            return 0

        except Exception as e:
            self.dut._log.error(f"[TB CMD] SEP mailbox CTRL write failed: {e}")
            import traceback

            self.dut._log.error(traceback.format_exc())
            try:
                self.dut.sep_awvalid.value = 0
                self.dut.sep_wvalid.value = 0
                self.dut.sep_bready.value = 0
            except:
                pass
            return 0

    async def _handle_km_mbox_read_during_sep_flush(self, arg):
        """Pulse SEP CTRL.FLUSH and issue a KM READ_DATA AR on the flush-active cycle.

        The flush register bit is high for the cycle after the SEP write commits.
        Driving KM AR so it handshakes on that cycle is the mailbox read/flush
        overlap. Returns 1 if an R beat arrives within 32 cycles.
        """
        from cocotb.triggers import RisingEdge

        SEP_CTRL_FLUSH = 0x4
        R_TIMEOUT_CYCLES = 32

        if not hasattr(self.dut, "tb_km_mbox_inject"):
            self.dut._log.error("[TB CMD] KM mailbox inject signals not found")
            raise RuntimeError("tb_km_mbox_inject missing")
        if not hasattr(self.dut, "sep_awvalid"):
            self.dut._log.error("[TB CMD] SEP AXI signals not found")
            raise RuntimeError("sep_awvalid missing")

        try:
            self.dut.tb_km_mbox_inject.value = 1
            self.dut.tb_km_arvalid.value = 0
            self.dut.tb_km_rready.value = 0
            self.dut.tb_km_araddr.value = MAILBOX_KM_KM_READ_DATA_REG_ADDR
            self.dut.tb_km_arprot.value = 0

            self.dut.sep_awvalid.value = 1
            self.dut.sep_awaddr.value = SEP_CTRL_REG_OFFSET
            self.dut.sep_awprot.value = 0
            self.dut.sep_wvalid.value = 1
            self.dut.sep_wdata.value = SEP_CTRL_FLUSH
            self.dut.sep_wstrb.value = 0xF
            self.dut.sep_bready.value = 1

            max_cycles = 50
            cycles = 0
            aw_done = False
            w_done = False
            while cycles < max_cycles and (not aw_done or not w_done):
                await RisingEdge(self.dut.clk)
                cycles += 1
                if not aw_done and int(self.dut.sep_awready.value) == 1:
                    aw_done = True
                    self.dut.sep_awvalid.value = 0
                if not w_done and int(self.dut.sep_wready.value) == 1:
                    w_done = True
                    self.dut.sep_wvalid.value = 0

            if not aw_done or not w_done:
                self.dut._log.error("[TB CMD] SEP CTRL.FLUSH handshake timeout")
                raise TimeoutError("SEP CTRL.FLUSH AW/W handshake")

            # After AW/W: cycle 0 clr=0 (B typically valid), cycle 1 clr=1 empty=0.
            # Take B on cycle 0; do not wait extra cycles or AR misses the flush window.
            await RisingEdge(self.dut.clk)
            if int(self.dut.sep_bvalid.value) == 1:
                self.dut.sep_bready.value = 0
            self.dut.tb_km_arvalid.value = 1
            await RisingEdge(self.dut.clk)
            ar_done = int(self.dut.tb_km_arready.value) == 1
            fifo_clr = int(self.dut.tb_km_fifo_clr.value)
            inbound_empty = int(self.dut.u_key_manager.u_mailbox.inbound_empty.value)
            self.dut._log.info(
                f"[TB CMD] KM READ_DATA AR handshake={ar_done} clr={fifo_clr} empty={inbound_empty}"
            )
            if not ar_done:
                self.dut._log.error("[TB CMD] KM READ_DATA AR did not handshake on flush cycle")
                raise TimeoutError("KM READ_DATA AR handshake")
            if fifo_clr != 1:
                self.dut._log.error("[TB CMD] KM READ_DATA AR handshake was not on fifo_clr")
                raise TimeoutError("KM READ_DATA AR missed flush cycle")

            self.dut.tb_km_arvalid.value = 0
            self.dut.tb_km_rready.value = 1

            for _ in range(R_TIMEOUT_CYCLES):
                await RisingEdge(self.dut.clk)
                if int(self.dut.tb_km_rvalid.value) == 1:
                    resp = int(self.dut.tb_km_rresp.value)
                    self.dut.tb_km_rready.value = 0
                    self.dut._log.info(
                        f"[TB CMD] KM READ_DATA R arrived during SEP flush, resp={resp}"
                    )
                    return 1

            self.dut._log.error(
                f"[TB CMD] KM READ_DATA R timeout ({R_TIMEOUT_CYCLES} cycles) after flush-overlap AR"
            )
            return 0
        finally:
            self.dut.tb_km_arvalid.value = 0
            self.dut.tb_km_rready.value = 0
            self.dut.tb_km_mbox_inject.value = 0
            self.dut.sep_awvalid.value = 0
            self.dut.sep_wvalid.value = 0
            self.dut.sep_bready.value = 0

    async def _handle_sep_mbox_write_separator_write(self, arg):
        """Write SEP mailbox WRITE_SEPARATOR register.

        Args:
            arg: Value to write to WRITE_SEPARATOR register

        Returns:
            1 if successful, 0 on error
        """
        from cocotb.triggers import RisingEdge

        try:
            AXI_OKAY = 0b00

            write_value = arg & 0xFFFFFFFF

            self.dut._log.info(
                f"[TB CMD] Writing 0x{write_value:08X} to SEP mailbox WRITE_SEPARATOR register"
            )

            if not hasattr(self.dut, "sep_awvalid"):
                self.dut._log.error("[TB CMD] SEP AXI signals not found in testbench")
                return 0

            self.dut.sep_awvalid.value = 1
            self.dut.sep_awaddr.value = SEP_WRITE_SEPARATOR_REG_OFFSET
            self.dut.sep_awprot.value = 0

            self.dut.sep_wvalid.value = 1
            self.dut.sep_wdata.value = write_value
            self.dut.sep_wstrb.value = 0xF

            self.dut.sep_bready.value = 1

            max_cycles = 50
            cycles = 0
            aw_done = False
            w_done = False

            while cycles < max_cycles and (not aw_done or not w_done):
                await RisingEdge(self.dut.clk)
                cycles += 1

                if not aw_done and int(self.dut.sep_awready.value) == 1:
                    aw_done = True
                    self.dut.sep_awvalid.value = 0

                if not w_done and int(self.dut.sep_wready.value) == 1:
                    w_done = True
                    self.dut.sep_wvalid.value = 0

            if not aw_done or not w_done:
                self.dut._log.error(
                    f"[TB CMD] SEP mailbox WRITE_SEPARATOR write handshake timeout after {cycles} cycles"
                )
                self.dut.sep_awvalid.value = 0
                self.dut.sep_wvalid.value = 0
                self.dut.sep_bready.value = 0
                return 0

            while cycles < max_cycles:
                await RisingEdge(self.dut.clk)
                cycles += 1
                if int(self.dut.sep_bvalid.value) == 1:
                    resp = int(self.dut.sep_bresp.value)
                    self.dut.sep_bready.value = 0
                    if resp == AXI_OKAY:
                        self.dut._log.info("[TB CMD] SEP mailbox WRITE_SEPARATOR write successful")
                        return 1
                    else:
                        self.dut._log.error(
                            f"[TB CMD] SEP mailbox WRITE_SEPARATOR write error response: {resp}"
                        )
                        return 0

            self.dut._log.error(
                "[TB CMD] SEP mailbox WRITE_SEPARATOR write timeout waiting for B response"
            )
            self.dut.sep_bready.value = 0
            return 0

        except Exception as e:
            self.dut._log.error(f"[TB CMD] SEP mailbox WRITE_SEPARATOR write failed: {e}")
            import traceback

            self.dut._log.error(traceback.format_exc())
            try:
                self.dut.sep_awvalid.value = 0
                self.dut.sep_wvalid.value = 0
                self.dut.sep_bready.value = 0
            except:
                pass
            return 0

    async def _handle_vuart_verify(self, arg):
        """Verify VUART received expected string.

        Args:
            arg: SRAM address (byte address) where expected null-terminated string is stored.
                 The testbench reads the string from SRAM and compares it with VUART output.
                 For known test patterns, we can also verify directly.

        Returns:
            1 if VUART output contains the expected string, 0 otherwise.
            Result is written to TB_CMD_RESULT.
        """
        try:
            if not self.vuart_monitor:
                self.dut._log.error("[TB CMD] VUART monitor not available")
                return 0

            # Convert byte address to SRAM word address
            # The SRAM interface extracts word address as mem_addr_i[SRAM_ADDR_WIDTH+1:2]
            # which is mem_addr_i[14:2] (divides by 4, doesn't subtract base)
            # SRAM_ADDR_WIDTH = 13, so we extract bits [14:2] from the byte address
            byte_addr = arg & 0xFFFFFFFF

            SRAM_BASE = 0x8000
            SRAM_WORDS = 8192
            SRAM_END = SRAM_BASE + SRAM_WORDS * 4 - 1
            if byte_addr < SRAM_BASE or byte_addr > SRAM_END:
                self.dut._log.error(
                    f"[TB CMD] Invalid SRAM address: 0x{byte_addr:08X} (must be 0x{SRAM_BASE:04X}-0x{SRAM_END:04X})"
                )
                return 0

            # Extract word address using same method as SRAM interface: bits [14:2]
            # This is equivalent to dividing by 4, but matches the hardware behavior
            word_addr = (byte_addr >> 2) & (SRAM_WORDS - 1)
            if word_addr >= SRAM_WORDS:
                self.dut._log.error(f"[TB CMD] SRAM address out of range: word_addr={word_addr}")
                return 0

            # Try to read string from SRAM
            expected_str = ""
            max_chars = 256
            self.dut._log.info(
                f"[TB CMD] Reading string from SRAM byte_addr=0x{byte_addr:08X}, word_addr={word_addr}"
            )

            # Read up to 8 words (32 bytes) to get the string
            for word_idx in range(word_addr, min(word_addr + 8, SRAM_WORDS)):
                try:
                    # Read from SRAM memory array (this should reflect CPU writes)
                    sram_word = int(self.dut.sram_mem[word_idx].value)

                    # Extract bytes from word (little-endian: byte0, byte1, byte2, byte3)
                    found_null = False
                    for byte_offset in range(4):
                        char_byte = (sram_word >> (byte_offset * 8)) & 0xFF
                        if char_byte == 0:
                            # Found null terminator - stop reading
                            found_null = True
                            break
                        expected_str += chr(char_byte)

                    if found_null:
                        break
                except Exception as e:
                    self.dut._log.error(f"[TB CMD] Failed to read SRAM at word {word_idx}: {e}")
                    return 0

            if not expected_str:
                self.dut._log.error("[TB CMD] Could not read expected string from SRAM")
                return 0

            self.dut._log.info(
                f"[TB CMD] Read expected string from SRAM: '{expected_str}' (length={len(expected_str)})"
            )

            # Get VUART output
            vuart_output = self.vuart_monitor.get_output()
            expected_len = len(expected_str)

            # Only compare the latest bytes sent on VUART (last N characters where N is expected string length)
            # This ensures we verify only what was just sent, not the entire test output
            if len(vuart_output) < expected_len:
                self.dut._log.error(
                    f"[TB CMD] VUART verification FAILED: VUART output length ({len(vuart_output)}) "
                    f"is less than expected string length ({expected_len})"
                )
                self.dut._log.error(f"[TB CMD] VUART output: '{vuart_output}'")
                return 0

            # VUART monitor only captures printable characters (0x20-0x7E), not newlines or control chars
            # So we need to compare the expected string without newlines/control chars
            # Get the printable characters from expected string (strip newlines and control chars)
            expected_printable = "".join(c for c in expected_str if 0x20 <= ord(c) < 0x7F)
            expected_printable_len = len(expected_printable)

            if len(vuart_output) < expected_printable_len:
                self.dut._log.error(
                    f"[TB CMD] VUART verification FAILED: VUART output length ({len(vuart_output)}) "
                    f"is less than expected printable string length ({expected_printable_len})"
                )
                self.dut._log.error(f"[TB CMD] VUART output: '{vuart_output}'")
                return 0

            # Get the last N printable characters from VUART output (where N is expected printable length)
            latest_vuart_output = vuart_output[-expected_printable_len:]
            self.dut._log.info(
                f"[TB CMD] Comparing last {expected_printable_len} printable chars of VUART output: "
                f"'{latest_vuart_output}' against expected printable: '{expected_printable}'"
            )

            # Check if the latest VUART output matches the expected printable string exactly
            if latest_vuart_output == expected_printable:
                self.dut._log.info(
                    "[TB CMD] VUART verification PASSED: latest output matches expected string"
                )
                return 1
            else:
                self.dut._log.error(
                    f"[TB CMD] VUART verification FAILED: expected printable '{expected_printable}' "
                    f"(length={expected_printable_len}), got latest output: '{latest_vuart_output}' "
                    f"(length={len(latest_vuart_output)})"
                )
                self.dut._log.error(f"[TB CMD] Full VUART output length: {len(vuart_output)} chars")
                return 0

        except Exception as e:
            self.dut._log.error(f"[TB CMD] VUART verify failed: {e}")
            import traceback

            self.dut._log.error(traceback.format_exc())
            return 0

    async def _handle_sep_mbox_write_with_resp(self, arg):
        """Write data to SEP mailbox inbound FIFO and return AXI response code.

        This writes to the SEP mailbox WRITE_DATA register via SEP AXI interface
        and returns the AXI response code for overflow testing.

        Args:
            arg: 32-bit data word to write to SEP mailbox

        Returns:
            AXI response code (0=OKAY, 2=SLVERR, 3=DECERR) packed in lower 8 bits
        """
        from cocotb.triggers import RisingEdge

        try:
            AXI_OKAY = 0b00
            AXI_SLVERR = 0b10
            AXI_DECERR = 0b11

            data = arg & 0xFFFFFFFF

            self.dut._log.info(
                f"[TB CMD] Writing 0x{data:08X} to SEP mailbox (with response check)"
            )

            # Initialize SEP AXI signals if not already initialized
            if not hasattr(self.dut, "sep_awvalid"):
                self.dut._log.error("[TB CMD] SEP AXI signals not found in testbench")
                return AXI_DECERR

            # Drive AW and W channels simultaneously
            self.dut.sep_awvalid.value = 1
            self.dut.sep_awaddr.value = SEP_WRITE_DATA_REG_OFFSET
            self.dut.sep_awprot.value = 0

            self.dut.sep_wvalid.value = 1
            self.dut.sep_wdata.value = data
            self.dut.sep_wstrb.value = 0xF  # All bytes

            self.dut.sep_bready.value = 1

            # Wait for AW and W handshakes
            max_cycles = 50
            cycles = 0
            aw_done = False
            w_done = False

            while cycles < max_cycles and (not aw_done or not w_done):
                await RisingEdge(self.dut.clk)
                cycles += 1

                if not aw_done and int(self.dut.sep_awready.value) == 1:
                    aw_done = True
                    self.dut.sep_awvalid.value = 0

                if not w_done and int(self.dut.sep_wready.value) == 1:
                    w_done = True
                    self.dut.sep_wvalid.value = 0

            if not aw_done or not w_done:
                self.dut._log.error(f"[TB CMD] SEP write handshake timeout after {cycles} cycles")
                self.dut.sep_awvalid.value = 0
                self.dut.sep_wvalid.value = 0
                self.dut.sep_bready.value = 0
                return AXI_DECERR

            # Wait for B response
            while cycles < max_cycles:
                await RisingEdge(self.dut.clk)
                cycles += 1
                if int(self.dut.sep_bvalid.value) == 1:
                    resp = int(self.dut.sep_bresp.value)
                    self.dut.sep_bready.value = 0
                    self.dut._log.info(
                        f"[TB CMD] SEP mailbox write response: {resp} (0=OKAY, 2=SLVERR, 3=DECERR)"
                    )
                    return resp

            # Timeout
            self.dut._log.error("[TB CMD] SEP mailbox write timeout waiting for B response")
            self.dut.sep_bready.value = 0
            return AXI_DECERR

        except Exception as e:
            self.dut._log.error(f"[TB CMD] SEP mailbox write with response failed: {e}")
            import traceback

            self.dut._log.error(traceback.format_exc())
            try:
                self.dut.sep_awvalid.value = 0
                self.dut.sep_wvalid.value = 0
                self.dut.sep_bready.value = 0
            except:
                pass
            return AXI_DECERR

    async def _handle_km_mbox_read_with_resp(self, arg):
        """Read data from KM mailbox inbound FIFO and return AXI response code.

        This reads from the KM mailbox READ_DATA register via crossbar injection
        and returns the AXI response code for underflow testing.

        Args:
            arg: Not used (0)

        Returns:
            AXI response code (0=OKAY, 2=SLVERR, 3=DECERR) packed in lower 8 bits
        """
        from cocotb.triggers import FallingEdge, RisingEdge

        try:
            AXI_OKAY = 0b00
            AXI_SLVERR = 0b10
            AXI_DECERR = 0b11

            self.dut._log.info("[TB CMD] Reading from KM mailbox READ_DATA (with response check)")

            # Check if crossbar injection signals exist
            if not hasattr(self.dut, "tb_xbar_arvalid"):
                self.dut._log.error("[TB CMD] Crossbar injection signals not found in testbench")
                return AXI_DECERR

            # Enable crossbar injection if not already enabled
            if hasattr(self.dut, "tb_xbar_inject"):
                self.dut.tb_xbar_inject.value = 1

            # Phase 1: AR channel - address phase
            await FallingEdge(self.dut.clk)
            self.dut.tb_xbar_arvalid.value = 1
            self.dut.tb_xbar_araddr.value = MAILBOX_KM_KM_READ_DATA_REG_ADDR
            self.dut.tb_xbar_arprot.value = 0
            self.dut.tb_xbar_rready.value = 0  # Not ready for data yet

            # Wait for AR handshake
            max_cycles = 200
            cycles = 0
            ar_done = False

            while cycles < max_cycles and not ar_done:
                await RisingEdge(self.dut.clk)
                cycles += 1
                ar_done = int(self.dut.tb_xbar_arready.value) == 1

            if not ar_done:
                self.dut._log.error(
                    f"[TB CMD] KM mailbox read AR handshake timeout after {cycles} cycles"
                )
                await FallingEdge(self.dut.clk)
                self.dut.tb_xbar_arvalid.value = 0
                return AXI_DECERR

            # Deassert ar_valid after handshake
            await FallingEdge(self.dut.clk)
            self.dut.tb_xbar_arvalid.value = 0

            # Phase 2: R channel - data phase
            self.dut.tb_xbar_rready.value = 1  # Ready to accept data

            # Wait for R handshake
            while cycles < max_cycles:
                await RisingEdge(self.dut.clk)
                cycles += 1

                if int(self.dut.tb_xbar_rvalid.value) == 1:
                    data = int(self.dut.tb_xbar_rdata.value)
                    resp = int(self.dut.tb_xbar_rresp.value)
                    await FallingEdge(self.dut.clk)
                    self.dut.tb_xbar_rready.value = 0
                    self.dut._log.info(
                        f"[TB CMD] KM mailbox read response: {resp} (0=OKAY, 2=SLVERR, 3=DECERR), data=0x{data:08X}"
                    )
                    return resp

            # Timeout
            self.dut._log.error("[TB CMD] KM mailbox read timeout waiting for R response")
            await FallingEdge(self.dut.clk)
            self.dut.tb_xbar_rready.value = 0
            return AXI_DECERR

        except Exception as e:
            self.dut._log.error(f"[TB CMD] KM mailbox read with response failed: {e}")
            import traceback

            self.dut._log.error(traceback.format_exc())
            try:
                if hasattr(self.dut, "tb_xbar_arvalid"):
                    self.dut.tb_xbar_arvalid.value = 0
                if hasattr(self.dut, "tb_xbar_rready"):
                    self.dut.tb_xbar_rready.value = 0
            except:
                pass
            return AXI_DECERR

    async def _handle_timeout_set(self, arg):
        """Set the testbench timeout value.

        This allows firmware to dynamically adjust the timeout based on test needs.
        The timeout is updated immediately and affects the main test loop.

        Args:
            arg: New timeout value in cycles (must be > 0)

        Returns:
            1 if successful, 0 on error
        """
        if arg == 0:
            self.dut._log.error(f"[TB CMD] Invalid timeout value: {arg} (must be > 0)")
            return 0

        if self.timeout_ref is not None:
            self.timeout_ref[0] = arg
            self.dut._log.info(f"[TB CMD] Timeout set to {arg} cycles")
            return 1
        else:
            self.dut._log.warning("[TB CMD] Timeout reference not available")
            return 0

    async def _handle_drbg_set_next_value(self, arg):
        """Override the next value scheduled from the DRBG (otherwise random). Result = 1."""
        self._drbg_next_value = arg & 0xFFFFFFFF
        self.dut._log.info(f"[TB CMD] DRBG next value overridden to 0x{self._drbg_next_value:08X}")
        return 1

    async def _handle_drbg_set_seed(self, arg):
        """Set seed for deterministic DRBG (arg = 32-bit seed). Result = 1."""
        self._drbg_rng.seed(arg & 0xFFFFFFFF)
        self._drbg_next_value = self._drbg_rng.getrandbits(32)
        self.dut._log.info(
            f"[TB CMD] DRBG seed set to 0x{arg & 0xFFFFFFFF:08X}, next value 0x{self._drbg_next_value:08X}"
        )
        return 1

    async def _handle_drbg_get_next_value(self, arg):
        """Return the value scheduled to come next from the DRBG (random or overridden by SET)."""
        return self._drbg_next_value

    async def _handle_drbg_stop(self, arg):
        """Request stop: if TVALID is asserted, wait for TREADY then deassert; else stop immediately. Result = 1."""
        if self._drbg_stopped:
            self.dut._log.info("[TB CMD] DRBG stop (already stopped, no wait)")
            return 1
        self._drbg_stop_pending = True
        self.dut._log.info("[TB CMD] DRBG stop requested (will deassert TVALID after next TREADY)")
        return 1

    async def _handle_drbg_start(self, arg):
        """Resume sending DRBG data (clear stopped state). Result = 1."""
        self._drbg_stopped = False
        self._drbg_stop_pending = False
        self.dut._log.info("[TB CMD] DRBG start (resuming)")
        return 1

    async def _handle_drbg_queue_beat(self, arg):
        """Queue one DRBG beat with explicit TSTRB for TSTRB assembly testing.

        The data value is taken from self._drbg_next_value (last set by
        TB_CMD_DRBG_SET_NEXT_VALUE).  The (value, tstrb) pair is appended to
        self._drbg_beat_queue and will be driven by _drbg_driver_loop before
        the next default-random beat.

        arg[3:0] = TSTRB value for this beat.
        Result = 1.
        """
        tstrb = int(arg) & 0xF
        value = self._drbg_next_value
        self._drbg_beat_queue.append((value, tstrb))
        self.dut._log.info(
            f"[TB CMD] DRBG queue beat: tdata=0x{value:08X} tstrb=0x{tstrb:01X} "
            f"(queue depth={len(self._drbg_beat_queue)})"
        )
        return 1

    async def _handle_drbg_tvalid_glitch(self, arg):
        """One-shot AXI-Stream protocol violation for STREAM_ERR testing.
        Arms the driver to assert TVALID for exactly one rising-edge cycle
        then deassert it without waiting for TREADY.  The driver is left in
        the stopped state after the glitch; call DRBG_START to resume.
        Result = 1."""
        self._drbg_glitch_pending = True
        self._drbg_stopped = (
            True  # Quiesce normal traffic; driver will re-take control for the glitch
        )
        self.dut._log.info("[TB CMD] DRBG TVALID glitch armed (1-cycle TVALID, then drop)")
        return 1

    async def _handle_check_recoverable_err(self, arg):
        """Sample recoverable_err output from key_manager. Result = 1 if high, 0 if low."""
        await ClockCycles(self.dut.clk, 2)  # Allow combinational path to settle
        try:
            val = (
                int(self.dut.recoverable_err.value)
                if self.dut.recoverable_err.value.is_resolvable
                else 0
            )
            self.dut._log.info(f"[TB CMD] CHECK_RECOVERABLE_ERR: recoverable_err = {val}")
            return 1 if val else 0
        except Exception as e:
            self.dut._log.error(f"[TB CMD] CHECK_RECOVERABLE_ERR failed: {e}")
            return 0

    async def _handle_check_unrecoverable_restart(self, arg):
        """Firmware asks: was the CPU restarted due to an unrecoverable fault?
        Returns 1 if we had seen unrecoverable_err and reset the DUT, 0 otherwise."""
        result = 1 if self._unrecoverable_reset_done else 0
        self.dut._log.info(
            f"[TB CMD] CHECK_UNRECOVERABLE_RESTART: restarted_after_unrecoverable = {result}"
        )
        return result

    async def _handle_unrecoverable_watch_ctrl(self, arg):
        """Arm/disarm the unrecoverable watcher for mixed-purpose firmware tests."""
        self._unrecoverable_watch_armed = (arg & 0x1) != 0
        self._unrecoverable_reset_done = False
        self._captured_unrecov_fault_code = 0
        state = "ARMED" if self._unrecoverable_watch_armed else "DISARMED"
        self.dut._log.info(f"[TB CMD] UNRECOVERABLE_WATCH_CTRL: {state}")
        return 1

    async def _handle_sep_mbox_drain_ctrl(self, arg):
        """Arm/disarm the autonomous SEP outbound-FIFO drainer.

        When armed, a background task continuously reads any word the KM places
        in the outbound (KM->SEP) FIFO, modelling a SEP that promptly consumes
        responses.  Handover tests arm this just before dispatching the
        firmware-load command so the ROM's wait-for-outbound-drain step (in
        rom_handover_finish) can complete even though the single test CPU is
        busy spinning inside the handover.  Default off so other tests, which
        explicitly read and validate response frames, are unaffected."""
        self._outbound_drain_armed = (arg & 0x1) != 0
        state = "ARMED" if self._outbound_drain_armed else "DISARMED"
        self.dut._log.info(f"[TB CMD] SEP_MBOX_DRAIN_CTRL: {state}")
        return 1

    async def _handle_get_cycle_count(self, arg):
        """Return the current testbench cycle counter."""
        del arg
        if self.current_cycles_ref is None:
            return 0
        return int(self.current_cycles_ref[0]) & 0xFFFFFFFF

    async def _handle_km_async_reset(self, arg):
        """Pulse tb_key_manager.cold_rst_n (external cold/async reset to Key Manager)."""
        del arg
        self.dut._log.info("[TB CMD] KM_ASYNC_RESET: pulsing cold_rst_n")
        await reset_dut(self.dut, cycles=20)
        return 1

    async def _handle_km_warm_reset(self, arg):
        """Pulse tb_key_manager.warm_rst_n (external warm synchronous reset to Key Manager).

        Asserts warm_rst_n for 22 cycles so the km_reset_conditioner's internal
        counter (MIN_RESET_CYCLES = 16) has enough time to latch and propagate
        the warm reset internally.  Returns 1 on success.
        """
        del arg
        self.dut._log.info("[TB CMD] KM_WARM_RESET: pulsing warm_rst_n")
        await warm_reset_dut(self.dut, cycles=22)
        return 1

    async def _handle_get_unrecoverable_fault_code(self, arg):
        """Return the fault code captured from the SEP outbound mailbox before
        the unrecoverable reset.  Returns 0 if no fault was captured."""
        code = self._captured_unrecov_fault_code
        self.dut._log.info(f"[TB CMD] GET_UNRECOVERABLE_FAULT_CODE: 0x{code:08X}")
        return code

    async def _handle_inject_spurious_irq(self, arg):
        """Inject spurious IRQ bits into the PicoRV32 IRQ vector.

        Deposits directly on the irq_vector signal inside picorv32_wrapper.
        The always_comb driving irq_vector only re-evaluates when irq_i or
        mbox_irq_i changes, so the deposit persists.  A background task
        re-deposits every clock edge to keep the bits asserted until the
        unrecoverable watch loop clears them."""
        self._spurious_irq_bits = arg
        if not hasattr(self, "_spurious_irq_task_running"):
            self._spurious_irq_task_running = False
        if arg and not self._spurious_irq_task_running:
            self._spurious_irq_task_running = True
            cocotb.start_soon(self._spurious_irq_driver())
        self.dut._log.info(f"[TB CMD] INJECT_SPURIOUS_IRQ: bits = 0x{arg:08X}")
        return 1

    async def _spurious_irq_driver(self):
        """Background: re-deposit spurious bits on irq_vector every cycle."""
        irq_vec = self.dut.u_key_manager.u_cpu.irq_vector
        while self._running and self._spurious_irq_bits:
            await RisingEdge(self.dut.clk)
            try:
                current = int(irq_vec.value) if irq_vec.value.is_resolvable else 0
                irq_vec.value = current | self._spurious_irq_bits
            except Exception:
                pass
        self._spurious_irq_task_running = False

    @staticmethod
    def _make_dr(value_256b):
        """Build a 512-bit dual-rail word: {~value[255:0], value[255:0]}."""
        mask256 = (1 << 256) - 1
        cpl = (~value_256b) & mask256
        return (cpl << 256) | (value_256b & mask256)

    @staticmethod
    def _ramp_256(base):
        """Build a 256-bit value from 32 ascending bytes starting at base."""
        return sum(((i + base) & 0xFF) << (i * 8) for i in range(32))

    def _drive_otp_dr_fields(self, otp_data, bases, corrupt_field=None):
        """Drive every 256-bit dual-rail field from its ramp pattern.

        When corrupt_field is given, that one field's complement half has bit 0
        left un-inverted so the KMCSR decoder reports a dual-rail violation
        while every other field stays valid, making OTP_SIGINT attributable.
        """
        mask256 = (1 << 256) - 1
        for name in OTP_DR_FIELDS:
            value = self._ramp_256(bases[name])
            if name == corrupt_field:
                cpl = ((~value) & mask256) ^ 1
                getattr(otp_data, name).value = (cpl << 256) | (value & mask256)
            else:
                getattr(otp_data, name).value = self._make_dr(value)

    async def _handle_otp_write(self, arg):
        """Drive OTP data port with known pattern (read-through, no strobe).

        Pattern (valid dual-rail throughout):
          life_cycle=0xA5 (lc=0x5), demotion_state_1=0b01 (d1=1), demotion_state_2=0b10 (d2=0)
          256-bit fields: 32-byte ramps from the OTP_PATTERN_BASE bases
        """
        if not hasattr(self.dut, "otp_data"):
            self.dut._log.warning("[TB CMD] OTP signals not found on DUT")
            return 0
        try:
            otp_data = self.dut.otp_data
            # life_cycle is dual-rail {~lc[3:0], lc[3:0]}: lc=0x5 -> 0xA5
            otp_data.life_cycle.value = 0xA5

            if hasattr(otp_data, "demotion_state_1") and hasattr(otp_data, "demotion_state_2"):
                # Each demotion bit is dual-rail {~d, d}: d1=1 -> 0b01, d2=0 -> 0b10
                otp_data.demotion_state_1.value = 0b01
                otp_data.demotion_state_2.value = 0b10
            else:
                self.dut._log.error(
                    "[TB CMD] OTP_WRITE: expected otp_data.demotion_state_1 and demotion_state_2"
                )
                return 0

            self._drive_otp_dr_fields(otp_data, OTP_PATTERN_BASE)
        except Exception as e:
            self.dut._log.error(f"[TB CMD] OTP_WRITE failed: {e}")
            return 0
        await RisingEdge(self.dut.clk)
        self.dut._log.info("[TB CMD] OTP_WRITE: drove known dual-rail pattern on otp_data port")
        return 1

    async def _handle_otp_write_changed(self, arg):
        """Drive OTP data port with a DIFFERENT pattern to trigger OTP_CHANGE IRQ.

        Changed pattern (valid dual-rail, differs from baseline in every field):
          life_cycle=0xC3 (lc=0x3), demotion_state_1=0b10 (d1=0), demotion_state_2=0b01 (d2=1)
          256-bit fields: 32-byte ramps from the OTP_PATTERN_BASE_CHANGED bases
        """
        if not hasattr(self.dut, "otp_data"):
            self.dut._log.warning("[TB CMD] OTP signals not found on DUT")
            return 0
        try:
            otp_data = self.dut.otp_data
            # Changed (valid) dual-rail values, all differing from the baseline:
            # life_cycle lc=0x3 -> 0xC3; demotion d1=0 -> 0b10, d2=1 -> 0b01
            otp_data.life_cycle.value = 0xC3

            if hasattr(otp_data, "demotion_state_1") and hasattr(otp_data, "demotion_state_2"):
                otp_data.demotion_state_1.value = 0b10
                otp_data.demotion_state_2.value = 0b01
            else:
                self.dut._log.error(
                    "[TB CMD] OTP_WRITE_CHANGED: expected demotion_state_1/2 fields"
                )
                return 0

            self._drive_otp_dr_fields(otp_data, OTP_PATTERN_BASE_CHANGED)
        except Exception as e:
            self.dut._log.error(f"[TB CMD] OTP_WRITE_CHANGED failed: {e}")
            return 0
        await RisingEdge(self.dut.clk)
        self.dut._log.info("[TB CMD] OTP_WRITE_CHANGED: drove changed dual-rail pattern")
        return 1

    async def _handle_otp_write_sigint(self, arg):
        """Drive the OTP port with a CORRUPTED dual-rail encoding on one field.

        arg selects the field by its OTP_READ_LOCK bit position, defaulting to
        chiplet_uid.  That field's value half is valid but its complement half
        has bit 0 NOT inverted, which should trigger OTP_SIGINT in
        hardware and an unrecoverable fault.  All other fields stay valid.
        """
        if not hasattr(self.dut, "otp_data"):
            self.dut._log.warning("[TB CMD] OTP signals not found on DUT")
            return 0
        field_bp = int(arg) if arg is not None else OTP_LOCK_FIELDS.index("chiplet_uid")
        field = OTP_LOCK_FIELDS[field_bp] if field_bp < len(OTP_LOCK_FIELDS) else None
        if field not in OTP_DR_FIELDS:
            self.dut._log.error(
                f"[TB CMD] OTP_WRITE_SIGINT: lock bit {field_bp} is not a dual-rail field"
            )
            return 0
        try:
            otp_data = self.dut.otp_data
            # life_cycle / demotion are VALID dual-rail here, so otp_sigint is
            # attributable solely to the selected field.
            otp_data.life_cycle.value = 0xA5

            if hasattr(otp_data, "demotion_state_1") and hasattr(otp_data, "demotion_state_2"):
                otp_data.demotion_state_1.value = 0b01
                otp_data.demotion_state_2.value = 0b10
            else:
                self.dut._log.error("[TB CMD] OTP_WRITE_SIGINT: expected demotion_state_1/2 fields")
                return 0

            self._drive_otp_dr_fields(otp_data, OTP_PATTERN_BASE, corrupt_field=field)
        except Exception as e:
            self.dut._log.error(f"[TB CMD] OTP_WRITE_SIGINT failed: {e}")
            return 0
        await RisingEdge(self.dut.clk)
        self.dut._log.info(f"[TB CMD] OTP_WRITE_SIGINT: drove corrupted dual-rail on {field}")
        return 1

    async def _handle_wipe_trigger(self, arg):
        """Assert wipe_state_i for one cycle (rising edge triggers WIPE_STATE IRQ and KPV zero)."""
        if not hasattr(self.dut, "wipe_state"):
            self.dut._log.warning("[TB CMD] wipe_state signal not found on DUT")
            return 0
        await RisingEdge(self.dut.clk)
        self.dut.wipe_state.value = 1
        await RisingEdge(self.dut.clk)
        self.dut.wipe_state.value = 0
        self.dut._log.info("[TB CMD] WIPE_TRIGGER: asserted wipe_state for one cycle")
        return 1

    async def _handle_key_share_read(self, arg):
        """Read a key share word from the crypto engine key register hwif_out.

        Arg encoding:
            [11:8] = engine (0=HMAC, 1=KMAC, 2=AES, 3=OTBN,
                             4=MLDSA_SEED, 5=MLKEM_SEED_D, 6=MLKEM_SEED_Z, 7=MLKEM_MSG)
            [4]    = share  (0=SHARE0, 1=SHARE1)
            [3:0]  = word index

        Returns the 32-bit value from the hwif_out flat arrays in the testbench.
        """
        engine = (arg >> 8) & 0xF
        share = (arg >> 4) & 0x1
        word = arg & 0xF

        engine_names = {
            0: "hmac",
            1: "kmac",
            2: "aes",
            3: "otbn",
            4: "mldsa_seed",
            5: "mlkem_seed_d",
            6: "mlkem_seed_z",
            7: "mlkem_msg",
        }
        name = engine_names.get(engine)
        if name is None:
            self.dut._log.warning(f"[TB CMD] KEY_SHARE_READ: invalid engine {engine}")
            return 0

        sig_name = f"{name}_share{share}"
        try:
            arr = getattr(self.dut, sig_name)
            val = int(arr[word].value)
        except Exception as e:
            self.dut._log.warning(
                f"[TB CMD] KEY_SHARE_READ: failed to read {sig_name}[{word}]: {e}"
            )
            return 0

        self.dut._log.info(f"[TB CMD] KEY_SHARE_READ: {name} share{share}[{word}] = 0x{val:08X}")
        return val

    async def _handle_abr_sk_load(self, arg):
        """Inject a model Adams Bridge shared-key write into the abr_wrapper_key reg block.

        Protocol (firmware drives these TB commands in sequence):
          1. For each word i (0..7): issue TB_CMD_DRBG_SET_NEXT_VALUE with the key word,
             then TB_CMD_ABR_SK_LOAD with arg=i. This loads tb_abr_sk_load_data[i].
          2. Issue TB_CMD_ABR_SK_LOAD with arg=0xFF to pulse tb_abr_sk_load_valid,
             which drives hwset=1 and we=1 into the reg block for one cycle.

        Arg encoding:
            0x00..0x07  = set tb_abr_sk_load_data[arg] = last DRBG next value
            0xFF        = assert tb_abr_sk_load_valid for one cycle (set KEY_VALID)
        """
        if not hasattr(self.dut, "tb_abr_sk_load_data"):
            self.dut._log.warning("[TB CMD] ABR_SK_LOAD: tb_abr_sk_load_data not found")
            return 0

        if arg == 0xFF:
            await RisingEdge(self.dut.clk)
            self.dut.tb_abr_sk_load_valid.value = 1
            await RisingEdge(self.dut.clk)
            self.dut.tb_abr_sk_load_valid.value = 0
            self.dut._log.info(
                "[TB CMD] ABR_SK_LOAD: pulsed tb_abr_sk_load_valid (hwset KEY_VALID)"
            )
        elif 0 <= arg <= 7:
            word_val = self._drbg_next_value
            self.dut.tb_abr_sk_load_data[arg].value = word_val
            self.dut._log.info(
                f"[TB CMD] ABR_SK_LOAD: set tb_abr_sk_load_data[{arg}] = 0x{word_val:08X}"
            )
        else:
            self.dut._log.warning(f"[TB CMD] ABR_SK_LOAD: invalid arg 0x{arg:X}")
            return 0
        return 1

    async def _handle_abr_sk_irq_status_read(self, arg):
        """Read the ABR ML-KEM shared-key IRQ status signal.

        Returns 1 if abr_mlkem_sharedkey_irq is asserted, 0 otherwise.
        """
        if not hasattr(self.dut, "abr_mlkem_sharedkey_irq"):
            self.dut._log.warning("[TB CMD] ABR_SK_IRQ_STATUS_READ: signal not found")
            return 0
        val = int(self.dut.abr_mlkem_sharedkey_irq.value)
        self.dut._log.info(f"[TB CMD] ABR_SK_IRQ_STATUS_READ: abr_mlkem_sharedkey_irq = {val}")
        return val

    async def _outbound_drain_loop(self):
        """Background task: when armed, model the SEP by continuously draining
        the KM->SEP (outbound) mailbox FIFO.

        Used by the firmware-handover tests: rom_handover_finish() spins until
        the outbound FIFO is empty before flushing it, but the single test CPU
        is stuck inside the handover and cannot issue the usual TB_CMD-driven
        reads.  This loop reads any available outbound word over the SEP AXI
        port so that wait can complete.

        The drainer shares the SEP AXI port with the TB command handlers, so it
        only acts when no TB command is being processed (the handover tests
        issue no further SEP-mailbox commands after arming)."""
        from cocotb.triggers import ClockCycles

        while self._running:
            await ClockCycles(self.dut.clk, 5)
            if not self._outbound_drain_armed:
                continue
            # Avoid contending for the SEP AXI port with an in-flight TB cmd.
            if self.regs.read_tb_cmd() != TB_CMD_NOP:
                continue
            try:
                status = await self._handle_sep_mbox_status_read(0, quiet=True)
                outbound_depth = (status >> 12) & 0xFF
                if outbound_depth < 1:
                    continue
                await self._handle_sep_mbox_read_with_resp(0)
            except Exception as e:
                self.dut._log.error(f"[TB CMD] Outbound drain failed: {e}")

    async def _unrecoverable_watch_loop(self):
        """Background task: when unrecoverable_err goes high, drain the SEP
        outbound mailbox to find the RESP_UNRECOVERABLE_FAULT message and
        capture the fault code, then reset the DUT."""
        RESP_UNRECOVERABLE_FAULT = 0xFF
        while self._running:
            await RisingEdge(self.dut.clk)
            if not self._unrecoverable_watch_armed:
                continue
            if self._unrecoverable_reset_done:
                continue
            try:
                unrec_trigger = False
                if self.dut.unrecoverable_err.value.is_resolvable:
                    unrec_trigger = int(self.dut.unrecoverable_err.value) != 0
                if not unrec_trigger:
                    continue
            except Exception:
                continue
            # Poll the SEP mailbox and look specifically for
            # RESP_UNRECOVERABLE_FAULT, instead of assuming the next frame
            # belongs to the unrecoverable path.
            #
            # Use READ_WITH_RESP so empty-FIFO reads (SLVERR) can be ignored
            # without corrupting header parsing.
            from cocotb.triggers import ClockCycles

            fault_found = False
            last_status = 0
            AXI_OKAY = 0
            try:
                for _ in range(5000):  # up to 50k cycles @ 10-cycle polling
                    await ClockCycles(self.dut.clk, 10)
                    # Poll outbound FIFO depth before attempting a frame read.
                    last_status = await self._handle_sep_mbox_status_read(0, quiet=True)
                    outbound_depth = (last_status >> 12) & 0xFF
                    # Need at least one word available to read a header.
                    if outbound_depth < 1:
                        continue

                    packed = await self._handle_sep_mbox_read_with_resp(0)
                    resp = packed & 0xFF
                    if resp != AXI_OKAY:
                        continue
                    hdr = (packed >> 8) & 0xFFFFFFFF

                    resp_id = (hdr >> 8) & 0xFF
                    payload_len = (hdr >> 16) & 0xFF

                    if resp_id == RESP_UNRECOVERABLE_FAULT and payload_len >= 1:
                        packed_fc = await self._handle_sep_mbox_read_with_resp(0)
                        if (packed_fc & 0xFF) != AXI_OKAY:
                            continue
                        fault_code = (packed_fc >> 8) & 0xFFFFFFFF
                        self._captured_unrecov_fault_code = fault_code
                        self.dut._log.info(
                            f"[TB CMD] Unrecoverable error detected; captured fault code 0x{fault_code:08X}"
                        )
                        # Consume remaining payload words (if any) and CRC.
                        for _ in range((payload_len - 1) + 1):
                            await self._handle_sep_mbox_read_with_resp(0)
                        fault_found = True
                        break

                    # Not unrecoverable frame: drain payload and optional CRC.
                    for _ in range(payload_len + (1 if payload_len > 0 else 0)):
                        await self._handle_sep_mbox_read_with_resp(0)

                if not fault_found:
                    self.dut._log.warning(
                        f"[TB CMD] RESP_UNRECOVERABLE_FAULT not observed after trigger "
                        f"(last status=0x{last_status:08X})"
                    )
            except Exception as e:
                self.dut._log.error(
                    f"[TB CMD] Failed while reading unrecoverable mailbox frame: {e}"
                )
                self._captured_unrecov_fault_code = 0

            self._unrecoverable_reset_done = True
            self._unrecoverable_watch_armed = False
            self.dut._log.info("[TB CMD] Unrecoverable error detected; resetting Key Manager")
            if hasattr(self, "_spurious_irq_bits"):
                self._spurious_irq_bits = 0
            await reset_dut(self.dut, cycles=20)

    async def _drbg_driver_loop(self):
        """Background task: drive DRBG AXI-Stream. Once TVALID is asserted it cannot deassert until TREADY."""
        while self._running:
            await RisingEdge(self.dut.clk)
            try:
                if not hasattr(self.dut, "drbg_tvalid"):
                    continue
                tready = (
                    int(self.dut.drbg_tready.value)
                    if self.dut.drbg_tready.value.is_resolvable
                    else 0
                )

                # One-shot STREAM_ERR injection: assert TVALID for one cycle then drop without TREADY.
                # _drbg_glitch_pending is set by _handle_drbg_tvalid_glitch; _drbg_stopped is also
                # set at that point so normal traffic is quiesced.
                if self._drbg_glitch_pending:
                    # Cycle 1: assert TVALID
                    self.dut.drbg_tvalid.value = 1
                    self.dut.drbg_tdata.value = self._drbg_next_value
                    self.dut.drbg_tstrb.value = 0xF
                    self._drbg_glitch_pending = False
                    # Wait for the next rising edge, then drop TVALID unconditionally (protocol violation)
                    await RisingEdge(self.dut.clk)
                    self.dut.drbg_tvalid.value = 0
                    self.dut._log.info(
                        "[DRBG glitch] TVALID asserted 1 cycle then dropped without TREADY (STREAM_ERR injected)"
                    )
                    # Remain in _drbg_stopped=True state; firmware calls tb_drbg_start() to resume
                    continue

                if self._drbg_stopped:
                    self.dut.drbg_tvalid.value = 0
                    continue
                # Queued beats take priority over default-random flow and over
                # stop-pending so the queue is always fully drained before stopping.
                # Each queued entry is (value, tstrb); drive until TREADY then
                # consume and move to next queued beat (or default-random).
                if self._drbg_beat_queue:
                    queued_value, queued_tstrb = self._drbg_beat_queue[0]
                    self.dut.drbg_tvalid.value = 1
                    self.dut.drbg_tdata.value = queued_value
                    self.dut.drbg_tstrb.value = queued_tstrb
                    if tready:
                        self._drbg_beat_queue.pop(0)
                        self.dut._log.info(
                            f"[DRBG queued beat] consumed: tdata=0x{queued_value:08X} "
                            f"tstrb=0x{queued_tstrb:01X} "
                            f"(remaining={len(self._drbg_beat_queue)})"
                        )
                        # Pre-stage the next beat's data now: TVALID stays high, so the
                        # RTL samples TDATA/TSTRB again at the very next rising edge and
                        # must see the next beat there, not the consumed one.
                        if self._drbg_beat_queue:
                            nv, nt = self._drbg_beat_queue[0]
                            self.dut.drbg_tdata.value = nv
                            self.dut.drbg_tstrb.value = nt
                        elif self._drbg_stop_pending:
                            # Queue drained with TREADY=1; the AXI handshake is
                            # complete so we can legally lower TVALID now.
                            self.dut.drbg_tvalid.value = 0
                            self._drbg_stopped = True
                            self._drbg_stop_pending = False
                        else:
                            self.dut.drbg_tdata.value = self._drbg_next_value
                            self.dut.drbg_tstrb.value = 0xF
                    continue
                if self._drbg_stop_pending:
                    # Queue was already empty when stop was requested; complete
                    # the current in-flight beat (AXI-Stream: TVALID must not
                    # deassert until TREADY) then stop.
                    self.dut.drbg_tvalid.value = 1
                    self.dut.drbg_tdata.value = self._drbg_next_value
                    self.dut.drbg_tstrb.value = 0xF
                    if tready:
                        self.dut.drbg_tvalid.value = 0
                        self._drbg_stopped = True
                        self._drbg_stop_pending = False
                    continue
                self.dut.drbg_tvalid.value = 1
                self.dut.drbg_tdata.value = self._drbg_next_value
                self.dut.drbg_tstrb.value = 0xF
                if tready:
                    # Refill with deterministic random for next beat (firmware can override via SET)
                    self._drbg_next_value = self._drbg_rng.getrandbits(32)
            except Exception:
                pass


class VuartMonitor:
    """Monitors VUART TX output from the testbench."""

    def __init__(self, dut):
        self.dut = dut
        self.output = ""
        self.lines = []
        self.current_line = ""
        self._running = False

    async def start(self):
        """Start monitoring VUART output."""
        self._running = True
        cocotb.start_soon(self._monitor_loop())

    def stop(self):
        """Stop monitoring."""
        self._running = False
        # Flush any remaining line
        if self.current_line:
            self.lines.append(self.current_line)

    async def _monitor_loop(self):
        """Background task to capture VUART TX characters."""
        while self._running:
            await RisingEdge(self.dut.clk)
            try:
                tx_valid = int(self.dut.vuart_tx_valid.value)
                if tx_valid:
                    tx_data = int(self.dut.vuart_tx_data.value)
                    if tx_data == 0x0A:  # Newline
                        self.lines.append(self.current_line)
                        self.current_line = ""
                    elif 0x20 <= tx_data < 0x7F:  # Printable
                        char = chr(tx_data)
                        self.output += char
                        self.current_line += char
                    # Ignore other control characters
            except Exception:
                pass  # Signal may not be valid during reset

    def get_output(self):
        """Return all captured output."""
        return self.output

    def get_lines(self):
        """Return captured output as list of lines."""
        return self.lines


class CpuMemoryMonitor:
    """Generic monitor for CPU memory interface and AXI transactions.

    Detects stuck transactions and can be enabled/disabled via firmware
    commands (TB_CMD_MONITOR_EN/DIS).
    """

    def __init__(self, dut):
        self.dut = dut
        self.enabled = False
        self._running = False
        self._task = None

        # State tracking
        self.mem_stuck_cycles = 0
        self.axi_stuck_cycles = 0
        self.last_mem_state = None
        self.last_axi_state = None
        self.cycle_count = 0

    def start(self):
        """Start the monitor task (monitoring disabled by default, enable via TB_CMD_MONITOR_EN)."""
        if not self._running:
            self._running = True
            self._task = cocotb.start_soon(self._monitor_loop())

    def enable(self):
        """Enable monitoring."""
        if not self.enabled:
            self.enabled = True
            self.dut._log.info("[MONITOR] CPU/memory monitoring ENABLED")
            if not self._running:
                self.start()

    def disable(self):
        """Disable monitoring."""
        if self.enabled:
            self.enabled = False
            self.dut._log.info("[MONITOR] CPU/memory monitoring DISABLED")

    def stop(self):
        """Stop monitoring completely."""
        self._running = False
        self.enabled = False

    async def _monitor_loop(self):
        """Main monitoring loop."""
        while self._running:
            await RisingEdge(self.dut.clk)

            if not self.enabled:
                continue

            self.cycle_count += 1

            # Periodic status every 10000 cycles
            if self.cycle_count % 10000 == 0:
                self.dut._log.info(f"[MONITOR] Status: cycle={self.cycle_count}")

            try:
                # Monitor CPU memory interface
                self._monitor_memory_interface()

                # Monitor AXI transactions
                self._monitor_axi_transactions()

            except Exception:
                # Ignore monitoring errors
                pass

    def _monitor_memory_interface(self):
        """Monitor CPU memory interface for stuck transactions."""
        try:
            mem_valid = int(self.dut.u_key_manager.u_cpu.mem_valid.value)
            mem_ready = int(self.dut.u_key_manager.u_cpu.mem_ready.value)
            mem_addr = int(self.dut.u_key_manager.u_cpu.mem_addr.value)
            mem_instr = int(self.dut.u_key_manager.u_cpu.mem_instr.value)

            # Track memory state for stuck detection
            mem_state = (mem_valid, mem_ready)
            if mem_state == self.last_mem_state:
                if mem_valid and not mem_ready:
                    self.mem_stuck_cycles += 1
                    if self.mem_stuck_cycles == 100:
                        self.dut._log.error(
                            f"[MONITOR] CPU memory transaction STUCK: valid=1 ready=0 addr=0x{mem_addr:08X} instr={mem_instr} for {self.mem_stuck_cycles} cycles"
                        )
            else:
                self.last_mem_state = mem_state
                if mem_valid and not mem_ready:
                    self.mem_stuck_cycles = 1
                else:
                    if self.mem_stuck_cycles > 0:
                        self.dut._log.info(
                            f"[MONITOR] CPU memory transaction completed after {self.mem_stuck_cycles} cycles"
                        )
                    self.mem_stuck_cycles = 0
        except (AttributeError, ValueError):
            pass

    def _monitor_axi_transactions(self):
        """Monitor CPU AXI interface for stuck transactions."""
        try:
            axi_awvalid = int(self.dut.u_key_manager.u_cpu.mem_axi_awvalid.value)
            axi_awready = int(self.dut.u_key_manager.u_cpu.mem_axi_awready.value)
            axi_awaddr = int(self.dut.u_key_manager.u_cpu.mem_axi_awaddr.value)
            axi_wvalid = int(self.dut.u_key_manager.u_cpu.mem_axi_wvalid.value)
            axi_wready = int(self.dut.u_key_manager.u_cpu.mem_axi_wready.value)
            axi_wdata = int(self.dut.u_key_manager.u_cpu.mem_axi_wdata.value)
            axi_bvalid = int(self.dut.u_key_manager.u_cpu.mem_axi_bvalid.value)
            axi_bready = int(self.dut.u_key_manager.u_cpu.mem_axi_bready.value)

            # Track AXI state for stuck detection
            axi_state = (axi_awvalid, axi_awready, axi_wvalid, axi_wready, axi_bvalid, axi_bready)
            if axi_state == self.last_axi_state:
                if (
                    (axi_awvalid and not axi_awready)
                    or (axi_wvalid and not axi_wready)
                    or (axi_bvalid and not axi_bready)
                ):
                    self.axi_stuck_cycles += 1
                    if self.axi_stuck_cycles == 100:
                        self.dut._log.error(
                            f"[MONITOR] AXI transaction STUCK: awvalid={axi_awvalid} awready={axi_awready} "
                            f"wvalid={axi_wvalid} wready={axi_wready} bvalid={axi_bvalid} bready={axi_bready} "
                            f"addr=0x{axi_awaddr:08X} data=0x{axi_wdata:08X}"
                        )
            else:
                self.last_axi_state = axi_state
                self.axi_stuck_cycles = 0
        except (AttributeError, ValueError):
            pass


@cocotb.test()
async def test_firmware_generic(dut):
    """Generic firmware test runner.

    Loads firmware from ROM_HEX_FILE plusarg, runs until completion,
    and checks pass/fail status from KMCSR test protocol registers.
    """
    dut._log.info("=" * 70)
    dut._log.info("Generic Firmware Test Runner")
    dut._log.info("=" * 70)

    # Get ROM hex file from plusargs
    rom_hex_file = cocotb.plusargs.get("ROM_HEX_FILE")

    if not rom_hex_file:
        # Try to find a default
        firmware_dir = Path(__file__).parent / "firmware"
        dut._log.error("No ROM_HEX_FILE specified!")
        dut._log.error(
            'Usage: TEST=test_firmware make run SIM_ARGS="+ROM_HEX_FILE=path/to/test.rom.hex"'
        )
        raise cocotb.result.TestFailure("ROM_HEX_FILE plusarg required")

    if not os.path.exists(rom_hex_file):
        raise cocotb.result.TestFailure(f"ROM hex file does not exist: {rom_hex_file}")

    # Extract test name from filename for logging
    test_name = Path(rom_hex_file).stem.replace(".rom", "")
    dut._log.info(f"Running firmware test: {test_name}")
    dut._log.info(f"ROM file: {rom_hex_file}")

    # Get optional timeout from plusargs (default 100000 cycles)
    timeout_str = cocotb.plusargs.get("TIMEOUT_CYCLES", "100000")
    try:
        initial_timeout = int(timeout_str)
    except ValueError:
        initial_timeout = 100000
    # Use lists to make timeout/cycle count mutable for testbench commands.
    max_cycles = [initial_timeout]
    current_cycles = [0]
    dut._log.info(
        f"Initial timeout: {max_cycles[0]} cycles (firmware can adjust via TB_CMD_TIMEOUT_SET)"
    )

    # Get VUART print enable from plusargs (default disabled to save simulation time)
    # Exception: test_vuart always enables printing since it tests VUART functionality
    vuart_print_enabled = cocotb.plusargs.get("VUART_PRINT", "0") == "1"
    if test_name == "test_vuart":
        vuart_print_enabled = True
        dut._log.info("VUART printing: FORCED ENABLED (test_vuart must test VUART functionality)")
    else:
        dut._log.info(
            f"VUART printing: {'ENABLED' if vuart_print_enabled else 'DISABLED'} (use +VUART_PRINT=1 to enable)"
        )

    # Start VUART monitor
    vuart = VuartMonitor(dut)

    # The HDL testbench owns clock generation; cocotb only drives reset/control.
    dut.cold_rst_n.value = 0
    dut.warm_rst_n.value = 1  # Warm reset deasserted at startup

    # Drive valid idle OTP encoding before releasing reset so the differential
    # decoders in km_csr see a valid complement relationship from the first
    # post-reset clock edge.  Without this, the all-zero Verilog default is an
    # invalid dual-rail value and fires a spurious OTP_SIGINT IRQ.
    drive_otp_idle(dut)

    await ClockCycles(dut.clk, 10)

    # Start VUART capture before releasing reset
    await vuart.start()

    dut._log.info("Starting firmware execution...")
    await reset_dut(dut, cycles=20)

    # Access KMCSR registers via hierarchical probing
    try:
        kmcsr_regs = KmcsrRegisterInterface(dut)
    except AttributeError as e:
        raise cocotb.result.TestFailure(f"Could not access KMCSR registers: {e}")

    # Set VUART print enable based on plusarg (must be done after reset)
    await ClockCycles(dut.clk, 2)  # Wait a couple cycles after reset
    kmcsr_regs.write_vuart_print_enable(vuart_print_enabled)

    cycle_counter_running = [True]

    async def cycle_counter_loop():
        while cycle_counter_running[0]:
            await RisingEdge(dut.clk)
            current_cycles[0] += 1

    cocotb.start_soon(cycle_counter_loop())

    # Create CPU/memory monitor (disabled by default, can be enabled via TB_CMD_MONITOR_EN)
    monitor = CpuMemoryMonitor(dut)
    monitor.start()  # Start the monitor task (but monitoring is disabled until firmware enables it)

    # Start testbench command handler (with monitor reference, timeout reference, and VUART monitor)
    tb_cmd_handler = TestbenchCommandHandler(
        dut,
        kmcsr_regs,
        monitor=monitor,
        timeout_ref=max_cycles,
        current_cycles_ref=current_cycles,
        vuart_monitor=vuart,
        enable_unrecoverable_watch=False,
    )
    await tb_cmd_handler.start()

    # Initialize parity injection signals if they exist
    if hasattr(dut, "rom_parity_err_inject"):
        dut.rom_parity_err_inject.value = 0
    if hasattr(dut, "sram_parity_err_inject"):
        dut.sram_parity_err_inject.value = 0

    # Initialize SEP AXI signals if they exist (for mailbox tests)
    if hasattr(dut, "sep_awvalid"):
        dut.sep_awvalid.value = 0
        dut.sep_awaddr.value = 0
        dut.sep_awprot.value = 0
        dut.sep_wvalid.value = 0
        dut.sep_wdata.value = 0
        dut.sep_wstrb.value = 0
        dut.sep_bready.value = 0
        dut.sep_arvalid.value = 0
        dut.sep_araddr.value = 0
        dut.sep_arprot.value = 0
        dut.sep_rready.value = 0

    # Wait for firmware to complete
    cycles_waited = 0

    while cycles_waited < max_cycles[0]:
        await ClockCycles(dut.clk, 100)
        cycles_waited += 100

        try:
            signature = kmcsr_regs.read_tb_signature()
            if signature == TEST_PASS_SIGNATURE or signature == TEST_FAIL_SIGNATURE:
                dut._log.info(f"Firmware completed after {cycles_waited} cycles")
                break
        except Exception:
            pass

        # Progress indicator every 10000 cycles
        if cycles_waited % 10000 == 0:
            dut._log.info(f"  Running... ({cycles_waited}/{max_cycles[0]} cycles)")

    # Stop monitoring
    cycle_counter_running[0] = False
    vuart.stop()
    tb_cmd_handler.stop()
    monitor.stop()
    await ClockCycles(dut.clk, 10)  # Let final output flush

    # Check for timeout
    if cycles_waited >= max_cycles[0]:
        dut._log.error(f"Timeout after {max_cycles[0]} cycles")
        dut._log.info("VUART output captured:")
        for line in vuart.get_lines():
            dut._log.info(f"  {line}")
        raise cocotb.result.TestFailure(f"Firmware execution timeout after {max_cycles[0]} cycles")

    # Read results from KMCSR registers
    signature = kmcsr_regs.read_tb_signature()
    result = kmcsr_regs.read_tb_result()
    errcode = kmcsr_regs.read_tb_errcode()
    subtest = kmcsr_regs.read_tb_subtest()

    # Report results
    dut._log.info("=" * 70)
    dut._log.info(f"Test: {test_name}")
    dut._log.info("-" * 70)

    # Display VUART output
    vuart_lines = vuart.get_lines()
    if vuart_lines:
        dut._log.info("Firmware Output:")
        for line in vuart_lines:
            dut._log.info(f"  {line}")
        dut._log.info("-" * 70)

    dut._log.info(f"Result:    {'PASS' if result == 1 else 'FAIL'}")
    dut._log.info(f"Signature: 0x{signature:08X}")
    dut._log.info(f"Subtests:  {subtest}")
    if errcode != 0:
        dut._log.info(f"Error Code: 0x{errcode:08X}")
    dut._log.info(f"Cycles:    {cycles_waited}")
    dut._log.info("=" * 70)

    # Verify results
    if signature == TEST_PASS_SIGNATURE and result == 1:
        dut._log.info(f"*** {test_name}: PASSED ***")
    else:
        if signature == TEST_FAIL_SIGNATURE:
            dut._log.error("Firmware reported failure")
        elif signature != TEST_PASS_SIGNATURE:
            dut._log.error(f"Unexpected signature: 0x{signature:08X}")
        if result != 1:
            dut._log.error(f"Result indicates failure: {result}")
        raise cocotb.result.TestFailure(f"{test_name}: FAILED")
