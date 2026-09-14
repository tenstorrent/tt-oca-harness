# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import random
import sys
from pathlib import Path
from typing import Optional

import cocotb
from apb_vip import APBMaster, APBMonitor
from cocotb.clock import Clock
from cocotb.triggers import ReadOnly, RisingEdge

from test.test_config import DEFAULT_CONFIG, TestConfig

# Import auto-generated register defaults from PeakRDL
# This is the single source of truth from the RDL file
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "data" / "registers" / "py_headers"))
from entropy_source_reg import (
    ENTROPY_SOURCE_APT_PATTERN_COUNT_1BIT_REG_DEFAULT,
    ENTROPY_SOURCE_APT_PATTERN_COUNT_2BIT_REG_DEFAULT,
    ENTROPY_SOURCE_APT_PROPORTION_1BIT_REG_DEFAULT,
    ENTROPY_SOURCE_APT_PROPORTION_LO_REG_DEFAULT,
    ENTROPY_SOURCE_COMPONENT_ID_REG_DEFAULT,
    ENTROPY_SOURCE_CTRL_REG_DEFAULT,
    ENTROPY_SOURCE_DEBUG_CTRL_REG_DEFAULT,
    ENTROPY_SOURCE_DECORRELATOR_CTRL_REG_DEFAULT,
    ENTROPY_SOURCE_DECORRELATOR_MASK_REG_DEFAULT,
    ENTROPY_SOURCE_FIFO_CTRL_REG_DEFAULT,
    ENTROPY_SOURCE_FIFO_RDATA_REG_DEFAULT,
    ENTROPY_SOURCE_FIFO_STATUS_REG_DEFAULT,
    ENTROPY_SOURCE_GENERATOR_0_HEALTH_STATUS_REG_DEFAULT,
    ENTROPY_SOURCE_GENERATOR_1_HEALTH_STATUS_REG_DEFAULT,
    ENTROPY_SOURCE_GENERATOR_2_HEALTH_STATUS_REG_DEFAULT,
    ENTROPY_SOURCE_GENERATOR_3_HEALTH_STATUS_REG_DEFAULT,
    ENTROPY_SOURCE_GENERATOR_4_HEALTH_STATUS_REG_DEFAULT,
    ENTROPY_SOURCE_GENERATOR_5_HEALTH_STATUS_REG_DEFAULT,
    ENTROPY_SOURCE_GENERATOR_6_HEALTH_STATUS_REG_DEFAULT,
    ENTROPY_SOURCE_GENERATOR_7_HEALTH_STATUS_REG_DEFAULT,
    ENTROPY_SOURCE_GENERATOR_8_HEALTH_STATUS_REG_DEFAULT,
    ENTROPY_SOURCE_GENERATOR_9_HEALTH_STATUS_REG_DEFAULT,
    ENTROPY_SOURCE_GENERATOR_10_HEALTH_STATUS_REG_DEFAULT,
    ENTROPY_SOURCE_GENERATOR_11_HEALTH_STATUS_REG_DEFAULT,
    ENTROPY_SOURCE_HEALTH_TEST_CTRL_REG_DEFAULT,
    ENTROPY_SOURCE_HEALTH_TEST_STATUS_REG_DEFAULT,
    ENTROPY_SOURCE_HEALTH_TEST_WINDOW_SIZE_REG_DEFAULT,
    ENTROPY_SOURCE_INTR_ENABLE_REG_DEFAULT,
    ENTROPY_SOURCE_INTR_STATUS_REG_DEFAULT,
    ENTROPY_SOURCE_INTR_TEST_REG_DEFAULT,
    ENTROPY_SOURCE_MARKOV_TEST_COUNTS_0_REG_DEFAULT,
    ENTROPY_SOURCE_MARKOV_TEST_PROB_THRESHOLDS_REG_DEFAULT,
    ENTROPY_SOURCE_REPETITION_TEST_COUNT_REG_DEFAULT,
    ENTROPY_SOURCE_RING_OSC_CTRL_REG_DEFAULT,
    ENTROPY_SOURCE_RING_OSC_ENABLE_REG_DEFAULT,
    ENTROPY_SOURCE_RING_OSC_TUNE_REG_DEFAULT,
    ENTROPY_SOURCE_SHA256_STATUS_REG_DEFAULT,
)

# Fixed-point scale for the p_bias/p_corr values written to the RO model.
PROB_SCALE = DEFAULT_CONFIG.ro.prob_scale

# Register Address Map (from entropy_source.rdl)
# All addresses are byte-aligned (4-byte increments for 32-bit registers)
# Format: {name: (address, access_type, description, default_value, write_mask)}
# Default values are imported from PeakRDL-generated Python file (single source of truth)
# Write mask indicates which bits are writable (1=writable, 0=read-only or reserved)
REG_MAP = {
    # Register Name                   Address   RW/RO   Description                                          Default (from RDL)                           Write Mask
    "COMPONENT_ID": (
        0x00,
        "RO",
        "Component Identification",
        ENTROPY_SOURCE_COMPONENT_ID_REG_DEFAULT,
        0x00000000,
    ),
    "CTRL": (0x04, "RW", "Entropy Source Control", ENTROPY_SOURCE_CTRL_REG_DEFAULT, 0x13FF0112),
    "DEBUG_CTRL": (
        0x0C,
        "RW",
        "Debug control to monitor internal signals",
        ENTROPY_SOURCE_DEBUG_CTRL_REG_DEFAULT,
        0x000007FF,
    ),  # SELECT_SIGNAL[7:0] + SELECT_FREQ_DIV[10:8] = 11 bits
    "INTR_STATUS": (
        0x10,
        "RW",
        "Interrupt Status - Write 1 to clear",
        ENTROPY_SOURCE_INTR_STATUS_REG_DEFAULT,
        0x11111111,
    ),
    "INTR_ENABLE": (
        0x14,
        "RW",
        "Interrupt Enable",
        ENTROPY_SOURCE_INTR_ENABLE_REG_DEFAULT,
        0x11111111,
    ),
    "INTR_TEST": (
        0x18,
        "WO",
        "Interrupt Test - Single pulse",
        ENTROPY_SOURCE_INTR_TEST_REG_DEFAULT,
        0x11111111,
    ),
    "SHA256_STATUS": (
        0x1C,
        "RO",
        "SHA-256 conditioner progress",
        ENTROPY_SOURCE_SHA256_STATUS_REG_DEFAULT,
        0x00000000,
    ),
    "FIFO_CTRL": (0x20, "RW", "FIFO Control", ENTROPY_SOURCE_FIFO_CTRL_REG_DEFAULT, 0x00000011),
    "FIFO_STATUS": (
        0x24,
        "RO",
        "FIFO Status - Level, pointers",
        ENTROPY_SOURCE_FIFO_STATUS_REG_DEFAULT,
        0x00000000,
    ),
    "FIFO_RDATA": (
        0x28,
        "RO",
        "FIFO Read Data - Read pops 32 entropy bits",
        ENTROPY_SOURCE_FIFO_RDATA_REG_DEFAULT,
        0x00000000,
    ),
    # 0x2C RESERVED
    "HEALTH_TEST_CTRL": (
        0x30,
        "RW",
        "Health Test Control - Enable and configure",
        ENTROPY_SOURCE_HEALTH_TEST_CTRL_REG_DEFAULT,
        0x0000FF07,
    ),  # ENABLE[2:0] + REPETITION_LIMIT[15:8]
    "HEALTH_TEST_WINDOW_SIZE": (
        0x34,
        "RW",
        "APT and Markov Window Size",
        ENTROPY_SOURCE_HEALTH_TEST_WINDOW_SIZE_REG_DEFAULT,
        0x0000FFFF,
    ),
    "MARKOV_TEST_PROB_THRESHOLDS": (
        0x38,
        "RW",
        "Markov Test Probability Thresholds",
        ENTROPY_SOURCE_MARKOV_TEST_PROB_THRESHOLDS_REG_DEFAULT,
        0xFFFFFFFF,
    ),
    # 0x3C RESERVED
    "HEALTH_TEST_STATUS": (
        0x40,
        "RO",
        "Health Test Status - 0=pass, 1=fail",
        ENTROPY_SOURCE_HEALTH_TEST_STATUS_REG_DEFAULT,
        0x00000000,
    ),
    "REPETITION_TEST_COUNT": (
        0x44,
        "RO",
        "Repetition Test Count",
        ENTROPY_SOURCE_REPETITION_TEST_COUNT_REG_DEFAULT,
        0x00000000,
    ),
    # 0x48-0x4C RESERVED
    "APT_PATTERN_COUNT_1BIT": (
        0x50,
        "RO",
        "APT High One Count",
        ENTROPY_SOURCE_APT_PATTERN_COUNT_1BIT_REG_DEFAULT,
        0x00000000,
    ),
    "APT_PATTERN_COUNT_2BIT": (
        0x54,
        "RO",
        "APT Low One Count",
        ENTROPY_SOURCE_APT_PATTERN_COUNT_2BIT_REG_DEFAULT,
        0x00000000,
    ),
    # 0x58-0x5C RESERVED
    "APT_PROPORTION_1BIT": (
        0x60,
        "RW",
        "APT High One-Count Limit",
        ENTROPY_SOURCE_APT_PROPORTION_1BIT_REG_DEFAULT,
        0x0000FFFF,
    ),
    # 0x64-0x6C RESERVED
    "APT_PROPORTION_LO": (
        0x70,
        "RW",
        "APT Low One-Count Limit",
        ENTROPY_SOURCE_APT_PROPORTION_LO_REG_DEFAULT,
        0x0000FFFF,
    ),
    # 0x74-0x7C RESERVED
    "MARKOV_TEST_COUNTS_0": (
        0x80,
        "RO",
        "Markov Test Counts - per-lane max, min alternation",
        ENTROPY_SOURCE_MARKOV_TEST_COUNTS_0_REG_DEFAULT,
        0x00000000,
    ),
    "RING_OSC_ENABLE": (
        0x90,
        "RW",
        "Ring Oscillator Enables",
        ENTROPY_SOURCE_RING_OSC_ENABLE_REG_DEFAULT,
        0x00FFFFFF,
    ),
    "RING_OSC_TUNE": (
        0x94,
        "RW",
        "Ring Oscillator Tune Control",
        ENTROPY_SOURCE_RING_OSC_TUNE_REG_DEFAULT,
        0x00FFFFFF,
    ),
    "RING_OSC_CTRL": (
        0x98,
        "RW",
        "Ring Oscillator Sample Clock Select",
        ENTROPY_SOURCE_RING_OSC_CTRL_REG_DEFAULT,
        0x00000FFF,
    ),
    "DECORRELATOR_CTRL": (
        0xA0,
        "RW",
        "Decorrelator Control",
        ENTROPY_SOURCE_DECORRELATOR_CTRL_REG_DEFAULT,
        0xFFFFFFFF,
    ),
    "DECORRELATOR_MASK": (
        0xA4,
        "RW",
        "Decorrelator Mask",
        ENTROPY_SOURCE_DECORRELATOR_MASK_REG_DEFAULT,
        0x000000FF,
    ),
    # Individual generator health status registers (0xC0-0xEC)
    "GENERATOR_0_HEALTH_STATUS": (
        0xC0,
        "RO",
        "Generator 0 Health Test Status",
        ENTROPY_SOURCE_GENERATOR_0_HEALTH_STATUS_REG_DEFAULT,
        0x00000000,
    ),
    "GENERATOR_1_HEALTH_STATUS": (
        0xC4,
        "RO",
        "Generator 1 Health Test Status",
        ENTROPY_SOURCE_GENERATOR_1_HEALTH_STATUS_REG_DEFAULT,
        0x00000000,
    ),
    "GENERATOR_2_HEALTH_STATUS": (
        0xC8,
        "RO",
        "Generator 2 Health Test Status",
        ENTROPY_SOURCE_GENERATOR_2_HEALTH_STATUS_REG_DEFAULT,
        0x00000000,
    ),
    "GENERATOR_3_HEALTH_STATUS": (
        0xCC,
        "RO",
        "Generator 3 Health Test Status",
        ENTROPY_SOURCE_GENERATOR_3_HEALTH_STATUS_REG_DEFAULT,
        0x00000000,
    ),
    "GENERATOR_4_HEALTH_STATUS": (
        0xD0,
        "RO",
        "Generator 4 Health Test Status",
        ENTROPY_SOURCE_GENERATOR_4_HEALTH_STATUS_REG_DEFAULT,
        0x00000000,
    ),
    "GENERATOR_5_HEALTH_STATUS": (
        0xD4,
        "RO",
        "Generator 5 Health Test Status",
        ENTROPY_SOURCE_GENERATOR_5_HEALTH_STATUS_REG_DEFAULT,
        0x00000000,
    ),
    "GENERATOR_6_HEALTH_STATUS": (
        0xD8,
        "RO",
        "Generator 6 Health Test Status",
        ENTROPY_SOURCE_GENERATOR_6_HEALTH_STATUS_REG_DEFAULT,
        0x00000000,
    ),
    "GENERATOR_7_HEALTH_STATUS": (
        0xDC,
        "RO",
        "Generator 7 Health Test Status",
        ENTROPY_SOURCE_GENERATOR_7_HEALTH_STATUS_REG_DEFAULT,
        0x00000000,
    ),
    "GENERATOR_8_HEALTH_STATUS": (
        0xE0,
        "RO",
        "Generator 8 Health Test Status",
        ENTROPY_SOURCE_GENERATOR_8_HEALTH_STATUS_REG_DEFAULT,
        0x00000000,
    ),
    "GENERATOR_9_HEALTH_STATUS": (
        0xE4,
        "RO",
        "Generator 9 Health Test Status",
        ENTROPY_SOURCE_GENERATOR_9_HEALTH_STATUS_REG_DEFAULT,
        0x00000000,
    ),
    "GENERATOR_10_HEALTH_STATUS": (
        0xE8,
        "RO",
        "Generator 10 Health Test Status",
        ENTROPY_SOURCE_GENERATOR_10_HEALTH_STATUS_REG_DEFAULT,
        0x00000000,
    ),
    "GENERATOR_11_HEALTH_STATUS": (
        0xEC,
        "RO",
        "Generator 11 Health Test Status",
        ENTROPY_SOURCE_GENERATOR_11_HEALTH_STATUS_REG_DEFAULT,
        0x00000000,
    ),
}

__all__ = [
    "start_clocks",
    "init",
    "init_apb",
    "apb_reset",
    "apb_write",
    "apb_read",
    "apb_compare",
    "reg_wr",
    "reg_rd",
    "ro_model_set",
    "ro_model_enable",
    "ro_model_randomize_all",
    "ro_model_sample_once",
    "ro_model_word32_enable",
    "ro_model_word32_configure",
    "ro_model_word32_set",
    "ro_model_word32_read",
    "ro_model_word32_set_fixed",
    "get_random_val",
    "decor_set_mode",
    "decor_set_mode_by_name",
    "decor_get_mode_name",
    "decor_get_recommended_sample_period",
    "decor_print_mode_info",
    "decor_configure",
    "decor_checker_get_stats",
    "decor_checker_verify",
    "compressor_configure",
    "compressor_set_mode",
    "compressor_set_lane_mask",
    "compressor_get_stats",
    "compressor_checker_get_stats",
    "compressor_checker_verify",
    "DECOR_MODE_29",
    "DECOR_MODE_7",
    "DECOR_MODE_BYPASS",
    "DECOR_MODE_LFSR29",
    "DECOR_MODE_LFSR7",
    "REG_MAP",
    # High-level test helpers
    "log_phase_header",
    "configure_testbench",
    "program_dut_registers",
    "collect_entropy_samples",
    "verify_fifo_readout",
    "verify_checkers",
    "print_test_summary",
    # FIFO helper functions
    "read_fifo_status",
    "check_fifo_errors",
    "clear_fifo_errors",
    # Helper functions
    "enable_entropy_pipeline",
    "configure_health_tests",
    "configure_apt_thresholds",
    "enable_and_verify_interrupt",
    "poll_for_irq_assertion",
    "poll_for_irq_deassertion",
    "irq_checker_verify",
    "irq_checker_verify_async",
    "configure_all_ros_stuck",
    "configure_ro_stuck",
    "configure_degraded_entropy",
    "restore_normal_entropy_generation",
    "clear_and_verify_interrupt",
    "health_test_isr_recovery",
    "drain_fifo_to_level",
    "read_intr_status",
    "read_irq_output",
    "read_repetition_counter",
]


async def start_clocks(
    dut, apb_period_ns: int = None, rosc_period_ns: int = None, config: TestConfig = None
) -> None:
    """Start APB and rosc_sample clocks."""
    cfg = config or DEFAULT_CONFIG
    apb_period_ns = apb_period_ns or cfg.clock.apb_period_ns
    rosc_period_ns = rosc_period_ns or cfg.clock.rosc_period_ns

    # Prefer interface clock if present
    apb_clk = getattr(dut, "apb", None).pclk if hasattr(dut, "apb") else dut.pclk_i
    cocotb.start_soon(Clock(apb_clk, apb_period_ns, units="ns").start())
    cocotb.start_soon(Clock(dut.rosc_sample_clk, rosc_period_ns, units="ns").start())


async def init(
    dut,
    apb_period_ns: int = None,
    rosc_period_ns: int = None,
    reset_cycles: int = None,
    config: TestConfig = None,
) -> tuple[APBMaster, APBMonitor]:
    """Start clocks, create APB master/monitor, and apply reset.

    Initializes all model configurations from Python TestConfig (single source of truth):
      - RO model: Injection control, basic setup, optional auto-randomization
      - Decorrelator: Mode, sample period, shift direction, checker settings
      - Compressor: Enable, bypass mode, lane mask, debug group selection

    Args:
        dut: DUT instance
        apb_period_ns: APB clock period override (default: from config)
        rosc_period_ns: RO sample clock period override (default: from config)
        reset_cycles: Reset duration override (default: from config)
        config: TestConfig instance (default: DEFAULT_CONFIG)

    Returns:
        Tuple of (APBMaster, APBMonitor)
    """
    cfg = config or DEFAULT_CONFIG

    # Configure RO model injection control
    if hasattr(dut, "ro_inject_enable"):
        dut.ro_inject_enable.value = cfg.ro.inject_model
        inject_status = "ENABLED" if cfg.ro.inject_enabled else "DISABLED"
        dut._log.info(f"RO Model Injection: {inject_status}")

    # Configure clock divider checker control
    if hasattr(dut, "disable_clk_divider_check"):
        disable_value = 0 if cfg.clk_divider_check_enable else 1
        dut.disable_clk_divider_check.value = disable_value
        checker_status = "ENABLED" if cfg.clk_divider_check_enable else "DISABLED"
        dut._log.info(
            f"Clock Divider Checker: {checker_status} (disable_clk_divider_check={disable_value})"
        )
    else:
        dut._log.warning(
            "Clock Divider Checker: Signal 'disable_clk_divider_check' not found in DUT!"
        )
        dut._log.warning("  -> Testbench may need rebuilding with updated tb_entropy_top.sv")

    # Initialize all model configurations from Python (single source of truth)
    ro_init(dut, cfg.ro, log=True)
    decor_init(dut, cfg.decorrelator, log=True)
    compressor_init(dut, cfg.compressor, log=True)

    await start_clocks(dut, apb_period_ns=apb_period_ns, rosc_period_ns=rosc_period_ns, config=cfg)
    master, monitor = init_apb(dut)
    reset_cycles = reset_cycles or cfg.reset.reset_cycles
    await apb_reset(master, cycles=reset_cycles)

    # Auto-randomize RO model if enabled in config
    if cfg.ro.auto_randomize:
        dut._log.info("Auto-randomizing RO model (cfg.ro.auto_randomize=True)")
        await ro_model_randomize_all(dut, config=cfg)

    # Start background FIFO error monitor if enabled
    if cfg.fifo_error_monitor_enable:
        # cocotb.start_soon() creates a TRUE BACKGROUND COROUTINE:
        # - Returns immediately (non-blocking)
        # - Coroutine runs concurrently with main test
        # - Monitors every clock edge independently
        monitor_task = cocotb.start_soon(fifo_error_monitor(dut, master))
        dut._log.info("FIFO error monitor: ENABLED (background coroutine started)")
        dut._log.info("  - Monitors: dut.dut.fifo_overflow, dut.dut.fifo_underflow")
        dut._log.info("  - Method: Direct signal probing (NO APB traffic)")
    else:
        dut._log.info("FIFO error monitor: DISABLED (test expects overflow/underflow)")

    return master, monitor


async def fifo_error_monitor(dut, apb: APBMaster) -> None:
    """Background monitor that watches FIFO overflow/underflow signals.

    This monitor runs as a TRUE BACKGROUND COROUTINE (via cocotb.start_soon()) and:
    - Probes RTL signals directly (NO APB traffic!)
    - Runs concurrently with test execution
    - Raises exception immediately when errors detected

    Background execution via cocotb.start_soon():
    - Creates independent coroutine that runs concurrently
    - Does not block the calling function
    - Continues running until test ends or exception raised

    To disable for tests that expect overflow or underflow, set:
        config.fifo_error_monitor_enable = False

    Args:
        dut: DUT instance
        apb: Unused.

    Raises:
        AssertionError: If FIFO overflow or underflow is detected
    """
    from cocotb.triggers import RisingEdge

    try:
        # Try to access signals first to verify hierarchy
        # Signal hierarchy: tb_entropy_top (cocotb dut) -> entropy_source dut -> fifo_overflow
        try:
            test_overflow = int(dut.dut.fifo_overflow.value)
            test_underflow = int(dut.dut.fifo_underflow.value)
            dut._log.info(
                f"FIFO error monitor: Signal access OK (overflow={test_overflow}, underflow={test_underflow})"
            )
        except AttributeError as ae:
            dut._log.error(f"FIFO error monitor: Cannot access signals! {ae}")
            dut._log.error(
                "  Signal path: dut.dut.fifo_overflow (tb_entropy_top.entropy_source.fifo_overflow)"
            )
            raise

        # Monitor runs on every clock edge - truly passive monitoring
        while True:
            await RisingEdge(dut.apb.pclk)
            await ReadOnly()  # Wait for signals to settle

            # Probe RTL signals directly (NO APB traffic!)
            # Correct hierarchy: dut (tb_entropy_top) -> dut (entropy_source) -> fifo_overflow
            fifo_overflow = int(dut.dut.fifo_overflow.value)
            fifo_underflow = int(dut.dut.fifo_underflow.value)

            if fifo_overflow:
                dut._log.error("[FAIL] FIFO OVERFLOW detected by background monitor!")
                dut._log.error(f"   Signal: dut.dut.fifo_overflow = {fifo_overflow}")
                raise AssertionError(
                    "FIFO overflow detected! Check FIFO push rate vs FIFO size. "
                    "If overflow is expected, disable monitor with: "
                    "config.fifo_error_monitor_enable = False"
                )

            if fifo_underflow:
                dut._log.error("[FAIL] FIFO UNDERFLOW detected by background monitor!")
                dut._log.error(f"   Signal: dut.dut.fifo_underflow = {fifo_underflow}")
                raise AssertionError(
                    "FIFO underflow detected! Reading from empty FIFO. "
                    "If underflow is expected, disable monitor with: "
                    "config.fifo_error_monitor_enable = False"
                )

    except Exception as e:
        # If exception is from overflow/underflow detection, re-raise it
        if "FIFO overflow" in str(e) or "FIFO underflow" in str(e):
            raise
        if "AttributeError" in str(type(e)):
            raise  # Re-raise signal access errors
        # Otherwise, monitor is stopping (test ended) - exit gracefully
        dut._log.info(f"FIFO error monitor stopping: {e}")


def init_apb(dut) -> tuple[APBMaster, APBMonitor]:
    """Create APB master and monitor, start the monitor coroutine."""
    master = APBMaster(dut)
    monitor = APBMonitor(dut)
    cocotb.start_soon(monitor.start())
    return master, monitor


async def apb_reset(master: APBMaster, cycles: int = 4) -> None:
    """Drive APB to idle and apply reset via APBMaster."""
    await master.initialize_bus()
    await master.apply_reset(cycles=cycles)


async def apb_write(master: APBMaster, addr: int, data: int) -> None:
    await master.write(addr, data)


async def apb_read(master: APBMaster, addr: int) -> int:
    return await master.read(addr)


async def apb_compare(dut, master: APBMaster, addr: int, expected: int) -> None:
    """Read and compare against expected; raises on mismatch."""
    value = await apb_read(master, addr)
    if value != (expected & 0xFFFF_FFFF):
        raise AssertionError(
            f"APB compare failed @0x{addr:02X}: got 0x{value:08X}, exp 0x{expected:08X}"
        )
    dut._log.info(f"APB compare OK @0x{addr:02X} == 0x{value:08X}")


async def reg_wr(master: APBMaster, reg_name: str, data: int) -> None:
    """Write to register by name.

    Args:
        master: APB master instance
        reg_name: Register name from REG_MAP (e.g., 'COMPONENT_ID', 'CTRL')
        data: Data value to write (32-bit)

    Example:
        await reg_wr(apb, 'CTRL', ctrl_value)
    """
    if reg_name not in REG_MAP:
        raise ValueError(
            f"Unknown register: {reg_name}. Valid registers: {', '.join(REG_MAP.keys())}"
        )

    addr, access, desc, default, write_mask = REG_MAP[reg_name]

    if access == "RO":
        raise ValueError(f"Cannot write to read-only register: {reg_name}")

    await master.write(addr, data)


async def reg_rd(master: APBMaster, reg_name: str) -> int:
    """Read from register by name.

    Args:
        master: APB master instance
        reg_name: Register name from REG_MAP (e.g., 'COMPONENT_ID', 'CTRL')

    Returns:
        32-bit register value

    Example:
        value = await reg_rd(apb, 'COMPONENT_ID')
    """
    if reg_name not in REG_MAP:
        raise ValueError(
            f"Unknown register: {reg_name}. Valid registers: {', '.join(REG_MAP.keys())}"
        )

    addr, access, desc, default, write_mask = REG_MAP[reg_name]

    if access == "WO":
        raise ValueError(f"Cannot read from write-only register: {reg_name}")

    return await master.read(addr)


def _fp_to_scale(x: float) -> int:
    x = max(0.0, min(1.0, float(x)))
    return int(x * PROB_SCALE)


async def ro_model_set(
    dut,
    idx: int,
    p_bias: float = 0.5,
    p_corr: float = 0.5,
    stuck: Optional[int] = None,
    seed: Optional[int] = None,
) -> None:
    """Configure one RO model lane via ro_cfg interface.

    Validates the configuration and warns about problematic combinations.
    """
    # Guard if RO model interface is not present in this top
    try:
        cfg = dut.ro_cfg
    except AttributeError:
        dut._log.warning("ro_cfg interface not found on DUT; skipping ro_model_set")
        return

    # Validate configuration (only if not using stuck-at)
    if stuck is None:
        _validate_ro_config(dut, p_bias, p_corr)

    if seed is not None:
        cfg.seed[idx].value = int(seed)
        cfg.seed_en.value = 1
        await RisingEdge(dut.apb.pclk)
        cfg.seed_en.value = 0
    cfg.p_bias[idx].value = _fp_to_scale(p_bias)
    cfg.p_corr[idx].value = _fp_to_scale(p_corr)
    if stuck is None:
        cfg.stuck_en[idx].value = 0
        cfg.stuck_val[idx].value = 0
    else:
        cfg.stuck_en[idx].value = 1
        cfg.stuck_val[idx].value = 1 if stuck else 0


async def ro_model_enable(dut, enable: bool) -> None:
    """Globally enable/disable RO model updates."""
    try:
        dut.ro_cfg.enable.value = 1 if enable else 0
        await RisingEdge(dut.apb.pclk)
    except AttributeError:
        dut._log.warning("ro_cfg interface not found on DUT; skipping ro_model_enable")


async def ro_model_randomize_all(
    dut, num_lanes: int = None, seed_base: Optional[int] = None, config: TestConfig = None
) -> None:
    """Randomize all RO model lanes with varied bias/correlation and occasional stuck-at.
    Parameters from config:
    - p_bias in [bias_min, bias_max]
    - p_corr in [corr_min, corr_max]
    - For lanes 0 and 1, stuck_probability% chance stuck-at-1, stuck_zero_probability% stuck-at-0
    """
    cfg = config or DEFAULT_CONFIG
    num_lanes = num_lanes or cfg.ro.num_lanes

    # If interface missing, warn and return
    if not hasattr(dut, "ro_cfg"):
        dut._log.warning("ro_cfg interface not found on DUT; skipping ro_model_randomize_all")
        return

    for i in range(num_lanes):
        # Randomize bias and correlation within configured ranges
        bias_range = cfg.ro.bias_max - cfg.ro.bias_min
        p_bias = cfg.ro.bias_min + bias_range * random.random()

        corr_range = cfg.ro.corr_max - cfg.ro.corr_min
        p_corr = cfg.ro.corr_min + corr_range * random.random()

        # Apply stuck-at faults to lanes 0 and 1 with configured probability
        stuck = None
        if i in (0, 1):
            r = random.random()
            if r < cfg.ro.stuck_probability:
                stuck = 1
            elif r < (cfg.ro.stuck_probability + cfg.ro.stuck_zero_probability):
                stuck = 0

        seed_i = (seed_base + i) if seed_base is not None else int(random.getrandbits(32))
        await ro_model_set(dut, idx=i, p_bias=p_bias, p_corr=p_corr, seed=seed_i, stuck=stuck)


async def ro_model_sample_once(dut, max_tries: int = None, config: TestConfig = None) -> int:
    """Pulse-enable the RO model for one sample and return the 16-bit vector (as int).
    Skips if interface not present; retries a few cycles to avoid X/Z.
    """
    cfg = config or DEFAULT_CONFIG
    max_tries = max_tries or cfg.ro.sample_timeout
    if not hasattr(dut, "ro_cfg") or not hasattr(dut, "ro_bits"):
        dut._log.warning("ro_cfg/ro_bits not exposed; cannot sample RO model")
        return 0
    # Pulse enable for exactly one sample clock edge
    dut.ro_cfg.enable.value = 1
    await RisingEdge(dut.rosc_sample_clk)
    dut.ro_cfg.enable.value = 0
    # Read result; retry if unknowns; ensure valid asserted on this edge
    for _ in range(max_tries):
        # Ensure 'valid' is asserted if available
        if hasattr(dut, "ro_vlds"):
            v = dut.ro_vlds.value.binstr
            if v is None:
                await RisingEdge(dut.rosc_sample_clk)
                continue
            lv = v.lower()
            # skip if any x/z or if not all lanes reported valid
            if ("x" in lv) or ("z" in lv) or ("0" in lv):
                await RisingEdge(dut.rosc_sample_clk)
                continue
        # Now read bits
        s = dut.ro_bits.value.binstr
        if s is not None:
            ls = s.lower()
            if ("x" not in ls) and ("z" not in ls):
                try:
                    return int(ls, 2)
                except Exception:
                    pass
        await RisingEdge(dut.rosc_sample_clk)
    dut._log.debug("ro_model_sample_once: returning 0 after unresolved samples")
    return 0


async def get_random_val(dut, log: bool = True) -> int:
    """Return one 16-bit random sample from the RO model (pulsed enable).
    If log is True, print the sampled value.
    """
    val = await ro_model_sample_once(dut)
    if log:
        try:
            dut._log.info(f"RO sample: 0x{val:04X}")
        except Exception:
            pass
    return val


# =============================================================================
# RO Model Configuration Validation
# =============================================================================
# The RO_Jitter_Model probabilistic generator has non-intuitive behavior when
# both p_bias and p_corr are extreme. This validation system helps users avoid
# common pitfalls.
#
# Validation Levels:
#
# 1. ERROR (p_corr >= 0.99):
#    - Output gets STUCK at 0 (correlation locks to prev_bit which starts at 0)
#    - p_bias setting is COMPLETELY IGNORED
#    - Example: p_bias=1.0, p_corr=1.0 → ALL ZEROS (not all ones!)
#    - Solution: Use ro_model_word32_set_fixed() for predictable patterns
#
# 2. WARNING (p_corr >= 0.95 with extreme p_bias):
#    - Correlation dominates ~95% of the time
#    - p_bias only affects ~5% of bits
#    - Output may not match expectations
#    - Recommendation: Use fixed value injection for predictable results
#
# 3. INFO (extreme p_bias with low p_corr):
#    - Intentional extreme bias (e.g., p_bias=0.99, p_corr=0.1)
#    - This usually works as expected
#    - Just noting that fixed injection may be more precise
#
# 4. SILENT (balanced configurations):
#    - Normal ranges (p_bias ~0.3-0.7, p_corr ~0.3-0.7)
#    - No warnings needed
#
# Functions with validation:
#   - ro_model_set()              (per-lane configuration)
#   - ro_model_word32_configure() (32-bit word generation)
#   - ro_model_word32_set()       (convenience wrapper)
#
# =============================================================================

# Functions for configuring 32-bit word generation mode
# This bypasses decorrelator and compressor for controlled health test injection


def _validate_ro_config(dut, p_bias: float, p_corr: float) -> None:
    """Validate RO model configuration and warn about problematic combinations.

    Args:
        dut: DUT instance (for logging)
        p_bias: Probability of '1' bit (0.0 to 1.0)
        p_corr: Probability of bit correlation (0.0 to 1.0)

    The RO_Jitter_Model uses this algorithm:
        if (random() < p_corr):
            output = previous_bit
        else:
            output = (random() < p_bias) ? 1 : 0

    This means:
    - High p_corr causes output to lock to previous value
    - When p_corr ≈ 1.0, p_bias is essentially ignored
    - prev_bit initializes to 0, so p_corr=1.0 produces all zeros

    Example Error Message:
        When calling: await ro_model_word32_set(dut, enable=True, p_bias=1.0, p_corr=1.0)

        You will see:
        ================================================================================
        CONFIGURATION ERROR: p_corr >= 0.99 produces STUCK OUTPUT!
        ================================================================================
          Current config: p_bias=1.00, p_corr=1.00

          WHY THIS FAILS:
          - With p_corr >= 0.99, the correlation path ALWAYS wins
          - Output becomes: bit = prev_bit (locked to previous)
          - Since prev_bit initializes to 0, output STAYS AT 0
          - Your p_bias setting is IGNORED!

          EXPECTED vs ACTUAL:
          - You probably expect: ALL ONES (p_bias=1.00)
          - You will actually get: ALL ZEROS (prev_bit=0)

          SOLUTION:
          Use ro_model_word32_set_fixed() instead for predictable patterns:
            await ro_model_word32_set_fixed(dut, 0xFFFFFFFF)  # All ones
            await ro_model_word32_set_fixed(dut, 0x00000000)  # All zeros
            await ro_model_word32_set_fixed(dut, 0x55555555)  # Alternating
        ================================================================================
    """

    # _fp_to_scale clamps silently; report out-of-range values before the clamp hides them.
    if p_bias < 0.0 or p_bias > 1.0:
        dut._log.error("=" * 80)
        dut._log.error(f"INVALID CONFIGURATION: p_bias={p_bias} out of range [0.0, 1.0]!")
        dut._log.error("=" * 80)
        dut._log.error("  p_bias will be clamped to valid range.")
        dut._log.error("=" * 80)

    if p_corr < 0.0 or p_corr > 1.0:
        dut._log.error("=" * 80)
        dut._log.error(f"INVALID CONFIGURATION: p_corr={p_corr} out of range [0.0, 1.0]!")
        dut._log.error("=" * 80)
        dut._log.error("  p_corr will be clamped to valid range.")
        dut._log.error("=" * 80)

    # Check for extremely high correlation (>= 0.99)
    if p_corr >= 0.99:
        dut._log.error("=" * 80)
        dut._log.error("CONFIGURATION ERROR: p_corr >= 0.99 produces STUCK OUTPUT!")
        dut._log.error("=" * 80)
        dut._log.error(f"  Current config: p_bias={p_bias:.2f}, p_corr={p_corr:.2f}")
        dut._log.error("")
        dut._log.error("  WHY THIS FAILS:")
        dut._log.error("  - With p_corr >= 0.99, the correlation path ALWAYS wins")
        dut._log.error("  - Output becomes: bit = prev_bit (locked to previous)")
        dut._log.error("  - Since prev_bit initializes to 0, output STAYS AT 0")
        dut._log.error("  - Your p_bias setting is IGNORED!")
        dut._log.error("")

        if p_bias >= 0.99:
            dut._log.error("  EXPECTED vs ACTUAL:")
            dut._log.error(f"  - You probably expect: ALL ONES (p_bias={p_bias:.2f})")
            dut._log.error("  - You will actually get: ALL ZEROS (prev_bit=0)")
        elif p_bias <= 0.01:
            dut._log.error("  EXPECTED vs ACTUAL:")
            dut._log.error(f"  - You expect: ALL ZEROS (p_bias={p_bias:.2f})")
            dut._log.error("  - You will get: ALL ZEROS (but due to correlation, not bias!)")
        else:
            dut._log.error("  ACTUAL BEHAVIOR:")
            dut._log.error("  - Output locked at 0 (correlation dominates)")
            dut._log.error(f"  - Your p_bias={p_bias:.2f} setting has NO EFFECT")

        dut._log.error("")
        dut._log.error("  SOLUTION:")
        dut._log.error("  Use ro_model_word32_set_fixed() instead for predictable patterns:")
        dut._log.error("    await ro_model_word32_set_fixed(dut, 0xFFFFFFFF)  # All ones")
        dut._log.error("    await ro_model_word32_set_fixed(dut, 0x00000000)  # All zeros")
        dut._log.error("    await ro_model_word32_set_fixed(dut, 0x55555555)  # Alternating")
        dut._log.error("=" * 80)

    # Check for high correlation (>= 0.95) with extreme bias
    elif p_corr >= 0.95 and (p_bias >= 0.95 or p_bias <= 0.05):
        dut._log.warning("=" * 80)
        dut._log.warning("CONFIGURATION WARNING: High correlation + extreme bias")
        dut._log.warning("=" * 80)
        dut._log.warning(f"  Current config: p_bias={p_bias:.2f}, p_corr={p_corr:.2f}")
        dut._log.warning("")
        dut._log.warning("  ISSUE:")
        dut._log.warning(
            f"  - With p_corr={p_corr:.2f}, correlation dominates (~{p_corr * 100:.0f}% of the time)"
        )
        dut._log.warning(
            f"  - Your p_bias={p_bias:.2f} only affects ~{(1 - p_corr) * 100:.0f}% of bits"
        )
        dut._log.warning("  - Output may not match your expectations!")
        dut._log.warning("")

        if p_bias >= 0.95:
            expected_ones_pct = p_corr * 0.0 + (1 - p_corr) * p_bias  # prev_bit starts at 0
            dut._log.warning("  EXPECTED vs LIKELY ACTUAL:")
            dut._log.warning(f"  - You probably expect: ~{p_bias * 100:.0f}% ones")
            dut._log.warning(
                f"  - You will likely get: ~{expected_ones_pct * 100:.0f}% ones (correlation starts at 0)"
            )

        dut._log.warning("")
        dut._log.warning("  RECOMMENDATION:")
        dut._log.warning("  For predictable extreme patterns, use fixed value injection:")
        dut._log.warning("    await ro_model_word32_set_fixed(dut, <your_pattern>)")
        dut._log.warning("=" * 80)

    # Extreme bias with low correlation: log the expected ones ratio
    elif (p_bias >= 0.95 or p_bias <= 0.05) and p_corr <= 0.1:
        dut._log.info("=" * 80)
        dut._log.info("CONFIGURATION NOTE: Extreme bias with low correlation")
        dut._log.info("=" * 80)
        dut._log.info(f"  Current config: p_bias={p_bias:.2f}, p_corr={p_corr:.2f}")
        dut._log.info("")
        dut._log.info("  BEHAVIOR:")
        if p_bias >= 0.95:
            dut._log.info(f"  - Output will be ~{p_bias * 100:.0f}% ones (highly biased)")
        else:
            dut._log.info(
                f"  - Output will be ~{p_bias * 100:.0f}% ones (highly biased towards zeros)"
            )
        dut._log.info(f"  - Correlation is low ({p_corr:.2f}), so bias dominates")
        dut._log.info("")
        dut._log.info("  This may be intentional. If you need EXACT patterns, consider:")
        dut._log.info("    await ro_model_word32_set_fixed(dut, <specific_pattern>)")
        dut._log.info("=" * 80)


async def ro_model_word32_enable(dut, enable: bool) -> None:
    """Enable/disable 32-bit word generation mode.

    When enabled, RO model generates 32-bit words at ro_cfg.word32_data
    with valid signal ro_cfg.word32_valid. These are injected directly
    into health test module, bypassing decorrelator and compressor.

    Args:
        dut: DUT instance with ro_cfg interface
        enable: True to enable word32 mode, False to disable
    """
    try:
        dut.ro_cfg.word32_enable.value = 1 if enable else 0
        await RisingEdge(dut.apb.pclk)
    except AttributeError:
        dut._log.warning("ro_cfg.word32_enable not found; skipping ro_model_word32_enable")


async def ro_model_word32_configure(dut, p_bias: float = 0.5, p_corr: float = 0.5) -> None:
    """Configure bias and correlation for 32-bit word generation.

    Args:
        dut: DUT instance with ro_cfg interface
        p_bias: Probability of '1' bit (0.0 to 1.0, default 0.5)
        p_corr: Probability of bit correlation (0.0 to 1.0, default 0.5)

    Warnings:
        This function validates the configuration and warns about problematic
        combinations that don't produce expected results.
    """
    try:
        cfg = dut.ro_cfg

        # Validate configuration and warn about problematic combinations
        _validate_ro_config(dut, p_bias, p_corr)

        cfg.word32_p_bias.value = _fp_to_scale(p_bias)
        cfg.word32_p_corr.value = _fp_to_scale(p_corr)
        await RisingEdge(dut.apb.pclk)
    except AttributeError:
        dut._log.warning(
            "ro_cfg.word32_p_bias/p_corr not found; skipping ro_model_word32_configure"
        )


async def ro_model_word32_set(
    dut, enable: bool = True, p_bias: float = 0.5, p_corr: float = 0.5
) -> None:
    """Configure and enable/disable 32-bit word generation mode in one call.

    This is a convenience function that combines enable and configure operations.

    Args:
        dut: DUT instance with ro_cfg interface
        enable: True to enable word32 mode, False to disable
        p_bias: Probability of '1' bit (0.0 to 1.0, default 0.5)
        p_corr: Probability of bit correlation (0.0 to 1.0, default 0.5)

    Example:
        # Enable with extreme bias for Markov test
        await ro_model_word32_set(dut, enable=True, p_bias=0.95, p_corr=0.9)

        # Disable and return to normal decorrelator injection
        await ro_model_word32_set(dut, enable=False)
    """
    await ro_model_word32_configure(dut, p_bias=p_bias, p_corr=p_corr)
    await ro_model_word32_enable(dut, enable=enable)


async def ro_model_word32_read(dut) -> Optional[int]:
    """Read the current 32-bit word from RO model.

    Returns:
        32-bit word as integer, or None if interface not available
    """
    try:
        word = dut.ro_cfg.word32_data.value
        return int(word)
    except (AttributeError, ValueError):
        dut._log.warning("ro_cfg.word32_data not accessible; returning None")
        return None


async def ro_model_word32_set_fixed(dut, value: int, enable: bool = True) -> None:
    """Configure 32-bit injection to use a fixed value (not probabilistic).

    This bypasses the probabilistic RO_Jitter_Model generation and directly
    injects a specific 32-bit pattern. Useful for precise boundary testing
    where exact counter values are needed.

    Args:
        dut: DUT instance with ro_cfg interface
        value: Fixed 32-bit value to inject (0x00000000 to 0xFFFFFFFF)
        enable: True to enable fixed mode, False to disable 32-bit injection

    Example:
        # Inject pattern with 10 zeros then 22 ones for Repetition boundary test
        # Pattern: 0b0000000000_1111111111111111111111 = 0x003FFFFF
        await ro_model_word32_set_fixed(dut, 0x003FFFFF)

        # Inject all zeros (32 consecutive zeros, repetition_count=32)
        await ro_model_word32_set_fixed(dut, 0x00000000)

        # Inject all ones (32 consecutive ones, repetition_count=32)
        await ro_model_word32_set_fixed(dut, 0xFFFFFFFF)

        # Inject alternating pattern for Markov test (0101...)
        await ro_model_word32_set_fixed(dut, 0x55555555)

        # Disable fixed mode and return to probabilistic generation
        await ro_model_word32_set_fixed(dut, 0x00000000, enable=False)
    """
    try:
        # Set fixed value
        dut.ro_cfg.word32_fixed_value.value = value & 0xFFFFFFFF

        # Enable/disable fixed value mode
        dut.ro_cfg.word32_use_fixed.value = 1 if enable else 0

        # Enable/disable 32-bit word generation
        dut.ro_cfg.word32_enable.value = 1 if enable else 0

        await RisingEdge(dut.apb.pclk)  # Let it propagate

        dut._log.debug(
            f"ro_model_word32_set_fixed: value=0x{value:08X}, "
            f"use_fixed={enable}, word32_enable={enable}"
        )

    except AttributeError as e:
        dut._log.error(f"ro_cfg interface not available for fixed value configuration: {e}")
        raise


# Decorrelator mode constants
DECOR_MODE_29 = 0  # DECOR_29: 29-deep XOR decorrelator (default per spec)
DECOR_MODE_7 = 1  # DECOR_7: 7-deep XOR decorrelator (shallow)
DECOR_MODE_BYPASS = 2  # BYPASS: No decorrelation, raw bits (debug)
DECOR_MODE_LFSR29 = 3  # LFSR_29: 29-bit Fibonacci LFSR
DECOR_MODE_LFSR7 = 4  # LFSR_7: 7-bit Fibonacci LFSR

# Mode name mapping
_DECOR_MODE_NAMES = {
    0: "DECOR_29",
    1: "DECOR_7",
    2: "BYPASS",
    3: "LFSR_29",
    4: "LFSR_7",
}

_DECOR_NAME_TO_MODE = {
    "DECOR_29": 0,
    "DECOR_7": 1,
    "BYPASS": 2,
    "LFSR_29": 3,
    "LFSR_7": 4,
    # Aliases
    "decor_29": 0,
    "decor_7": 1,
    "bypass": 2,
    "lfsr_29": 3,
    "lfsr_7": 4,
}


def decor_set_mode(dut, mode: int) -> None:
    """Set decorrelator operating mode.

    Args:
        dut: DUT instance
        mode: Operating mode (0-4)
            0: DECOR_29 - 29-deep XOR decorrelator (default per spec)
            1: DECOR_7 - 7-deep XOR decorrelator (shallow)
            2: BYPASS - No decorrelation, raw bits (debug)
            3: LFSR_29 - 29-bit Fibonacci LFSR (x^29 + x^2 + 1)
            4: LFSR_7 - 7-bit Fibonacci LFSR (x^7 + x^6 + 1)

    Raises:
        AttributeError: If decor_cfg interface not found
        ValueError: If mode is out of range
    """
    if not hasattr(dut, "decor_cfg"):
        raise AttributeError("decor_cfg interface not found on DUT; cannot configure decorrelator")

    if mode < 0 or mode > 4:
        raise ValueError(f"Invalid decorrelator mode: {mode} (valid: 0-4)")

    dut.decor_cfg.mode.value = mode
    mode_name = _DECOR_MODE_NAMES.get(mode, f"UNKNOWN({mode})")
    dut._log.info(f"Decorrelator mode set to {mode} ({mode_name})")


def decor_set_mode_by_name(dut, mode_name: str) -> None:
    """Set decorrelator operating mode by name.

    Args:
        dut: DUT instance
        mode_name: Operating mode name (case-insensitive):
            "DECOR_29" or "decor_29"
            "DECOR_7" or "decor_7"
            "BYPASS" or "bypass"
            "LFSR_29" or "lfsr_29"
            "LFSR_7" or "lfsr_7"

    Raises:
        AttributeError: If decor_cfg interface not found
        ValueError: If mode_name is not recognized
    """
    if mode_name not in _DECOR_NAME_TO_MODE:
        valid_names = ", ".join(sorted(set(_DECOR_NAME_TO_MODE.keys())))
        raise ValueError(f"Invalid decorrelator mode name: '{mode_name}'. Valid: {valid_names}")

    mode = _DECOR_NAME_TO_MODE[mode_name]
    decor_set_mode(dut, mode)


def decor_get_mode_name(mode: int) -> str:
    """Get decorrelator mode name from mode number.

    Args:
        mode: Mode number (0-4)

    Returns:
        Mode name string (e.g., "DECOR_29")
    """
    return _DECOR_MODE_NAMES.get(mode, f"UNKNOWN({mode})")


def decor_get_recommended_sample_period(mode: int) -> int:
    """Get recommended sample period for decorrelator mode.

    Recommended periods are coprime with the decorrelator depth
    to ensure proper decorrelation and bit rotation.

    Args:
        mode: Decorrelator mode (0-4)

    Returns:
        Recommended sample period in cycles

    Examples:
        >>> decor_get_recommended_sample_period(0)  # DECOR_29
        64
        >>> decor_get_recommended_sample_period(1)  # DECOR_7
        16
    """
    recommendations = {
        0: 64,  # DECOR_29: coprime with 29
        1: 16,  # DECOR_7: coprime with 7
        2: 8,  # BYPASS: output every 8 cycles
        3: 64,  # LFSR_29: same as DECOR_29
        4: 16,  # LFSR_7: same as DECOR_7
    }
    return recommendations.get(mode, 64)


def decor_print_mode_info(mode: int) -> None:
    """Print detailed information about a decorrelator mode.

    Args:
        mode: Decorrelator mode (0-4)

    Example:
        >>> decor_print_mode_info(0)
        Decorrelator Mode 0: DECOR_29
        Description: 29-deep XOR decorrelator (spec default)
        Recommended sample period: 64 cycles
        Output bits per sample: 8
    """
    mode_info = {
        0: {
            "name": "DECOR_29",
            "desc": "29-deep XOR decorrelator (spec default)",
            "bits": 8,
            "notes": "XOR with bit from 29 cycles earlier, extracts oldest 8 bits",
        },
        1: {
            "name": "DECOR_7",
            "desc": "7-deep XOR decorrelator (shallow variant)",
            "bits": 4,
            "notes": "XOR with bit from 7 cycles earlier, extracts oldest 4 bits, zero-padded to 8",
        },
        2: {
            "name": "BYPASS",
            "desc": "No decorrelation, raw bits (debug mode)",
            "bits": 8,
            "notes": "Accumulates last 8 raw input bits without XOR feedback",
        },
        3: {
            "name": "LFSR_29",
            "desc": "29-bit Fibonacci LFSR",
            "bits": 8,
            "notes": "Polynomial x^29 + x^2 + 1, extracts MSBs [28:21]",
        },
        4: {
            "name": "LFSR_7",
            "desc": "7-bit Fibonacci LFSR",
            "bits": 4,
            "notes": "Polynomial x^7 + x^6 + 1, extracts MSBs [6:3], zero-padded to 8",
        },
    }

    info = mode_info.get(mode)
    if info:
        print("=" * 60)
        print(f"Decorrelator Mode {mode}: {info['name']}")
        print("=" * 60)
        print(f"Description: {info['desc']}")
        print(f"Recommended sample period: {decor_get_recommended_sample_period(mode)} cycles")
        print(f"Output bits per sample: {info['bits']} bits")
        print(f"Implementation: {info['notes']}")
        print("=" * 60)
    else:
        print(f"Unknown decorrelator mode: {mode}")


def decor_configure(dut, mode: int, shift_dir: int = 1, log: bool = True) -> None:
    """Configure decorrelator with recommended settings for a mode.

    This is a convenience function that:
    1. Sets the decorrelator mode
    2. Sets the shift direction
    3. Logs the configuration (if log=True)
    4. Shows the recommended sample period

    The reference model in tb_entropy_top.sv samples on the DUT clock divider
    (DECORRELATOR_CTRL.SAMPLE_CLK_DIV); this function only displays the recommendation.

    Args:
        dut: DUT instance
        mode: Decorrelator mode (0-4)
        shift_dir: Shift direction (0=right, 1=left, default: 1)
        log: Whether to log configuration details (default: True)

    Example:
        decor_configure(dut, DECOR_MODE_BYPASS, shift_dir=1)
    """
    decor_set_mode(dut, mode)

    # Set shift direction
    if hasattr(dut, "decor_cfg"):
        dut.decor_cfg.shift_dir.value = shift_dir

    if log:
        recommended_period = decor_get_recommended_sample_period(mode)
        mode_name = decor_get_mode_name(mode)

        dut._log.info("=" * 60)
        dut._log.info(f"Decorrelator configured: Mode {mode} ({mode_name})")
        dut._log.info(f"Recommended sample period: {recommended_period} cycles")
        dut._log.info("NOTE: Sample period is hardcoded in testbench to 64 cycles")
        dut._log.info("      Edit tb_entropy_source.sv .SAMPLE_PERIOD() to change")
        dut._log.info("=" * 60)


# ============================================================================
# Configuration Init Functions (Single Source of Truth)
# ============================================================================
# These functions apply Python configuration to SystemVerilog interfaces
# init() calls these before starting the clocks.


def ro_init(dut, config, log: bool = False) -> None:
    """Initialize RO model configuration from ROConfig instance.

    Args:
        dut: DUT instance
        config: ROConfig instance (from test_config.py)
        log: Whether to log configuration details (default: False)

    Note:
        This is automatically called by init() function.
        Per-lane randomization is done separately by ro_model_randomize_all().
    """
    if not hasattr(dut, "ro_cfg"):
        if log:
            dut._log.warning("ro_cfg interface not found; skipping configuration")
        return

    # Apply basic configuration (per-lane config done by ro_model_randomize_all)
    dut.ro_cfg.enable.value = 0  # Disabled until ROs are enabled
    dut.ro_cfg.seed_en.value = 0

    if log:
        dut._log.info("=" * 60)
        dut._log.info("RO Model initialized")
        dut._log.info(f"  Num Lanes:    {config.num_lanes}")
        dut._log.info(f"  Inject Model: {'ENABLED' if config.inject_enabled else 'DISABLED'}")
        dut._log.info("=" * 60)


def decor_init(dut, config, log: bool = False) -> None:
    """Initialize decorrelator configuration from DecorrelatorConfig instance.

    Args:
        dut: DUT instance
        config: DecorrelatorConfig instance (from test_config.py)
        log: Whether to log configuration details (default: False)

    Note:
        This is automatically called by init() function.
    """
    if not hasattr(dut, "decor_cfg"):
        if log:
            dut._log.warning("decor_cfg interface not found; skipping configuration")
        return

    # Apply configuration
    dut.decor_cfg.mode.value = config.mode
    dut.decor_cfg.sample_period.value = config.sample_period
    dut.decor_cfg.shift_dir.value = config.shift_dir
    dut.decor_cfg.bypass_mask.value = config.bypass_mask
    dut.decor_cfg.checker_enable.value = 1 if config.checker_enable else 0
    dut.decor_cfg.checker_verbose.value = 1 if config.checker_verbose else 0

    if log:
        dut._log.info("=" * 60)
        dut._log.info(f"Decorrelator configured: {config.mode_name}")
        dut._log.info(f"  Mode:            {config.mode} ({config.mode_name})")
        dut._log.info(f"  Sample Period:   {config.sample_period} cycles")
        dut._log.info(f"  Shift Direction: {config.shift_dir}")
        dut._log.info(f"  Bypass Mask:     0x{config.bypass_mask:03X}")
        dut._log.info(f"  Checker Enabled: {config.checker_enable}")
        dut._log.info(f"  Checker Verbose: {config.checker_verbose}")
        dut._log.info("=" * 60)


def compressor_init(dut, config, log: bool = False) -> None:
    """Initialize compressor configuration from CompressorConfig instance.

    Args:
        dut: DUT instance
        config: CompressorConfig instance (from test_config.py)
        log: Whether to log configuration details (default: False)

    Note:
        This is automatically called by init() function.
    """
    if not hasattr(dut, "compressor_cfg"):
        if log:
            dut._log.warning("compressor_cfg interface not found; skipping configuration")
        return

    # Apply configuration
    dut.compressor_cfg.enable.value = 1 if config.enable else 0
    dut.compressor_cfg.bypass.value = 1 if config.bypass else 0
    dut.compressor_cfg.lane_mask.value = config.lane_mask
    dut.compressor_cfg.checker_enable.value = 1 if config.checker_enable else 0
    dut.compressor_cfg.checker_verbose.value = 1 if config.checker_verbose else 0

    if log:
        dut._log.info("=" * 60)
        dut._log.info(f"Compressor configured: {config.mode_name}")
        dut._log.info(f"  Enabled:        {config.enable}")
        dut._log.info(f"  Bypass:         {config.bypass}")
        dut._log.info(
            f"  Lane Mask:      0x{config.lane_mask:03X} ({config.count_active_lanes()}/12 lanes)"
        )
        dut._log.info("  Grouping:       Strided [0,4,8], [1,5,9], [2,6,10], [3,7,11]")
        dut._log.info(f"  Checker Enable: {config.checker_enable}")
        dut._log.info(f"  Checker Verbose: {config.checker_verbose}")
        dut._log.info("=" * 60)


def compressor_configure(dut, config, log: bool = False) -> None:
    """Alias for compressor_init()."""
    compressor_init(dut, config, log)


def compressor_set_mode(dut, bypass: bool) -> None:
    """Set compressor operating mode.

    Args:
        dut: DUT instance
        bypass: True for bypass mode (concatenation), False for BIW extraction

    Raises:
        AttributeError: If compressor_cfg interface not found

    Example:
        compressor_set_mode(dut, bypass=False)  # Enable BIW extraction
    """
    if not hasattr(dut, "compressor_cfg"):
        raise AttributeError("compressor_cfg interface not found on DUT")

    dut.compressor_cfg.bypass.value = 1 if bypass else 0
    mode_name = "BYPASS" if bypass else "BIW_EXTRACTION"
    dut._log.info(f"Compressor mode set to {mode_name}")


def compressor_set_lane_mask(dut, lane_mask: int) -> None:
    """Set compressor lane mask (enable/disable specific lanes).

    Args:
        dut: DUT instance
        lane_mask: 12-bit mask (bit[i]=1 enables lane i)

    Raises:
        AttributeError: If compressor_cfg interface not found

    Examples:
        compressor_set_lane_mask(dut, 0xFFF)  # All lanes enabled
        compressor_set_lane_mask(dut, 0x001)  # Only lane 0 enabled
        compressor_set_lane_mask(dut, 0xAAA)  # Even lanes only
    """
    if not hasattr(dut, "compressor_cfg"):
        raise AttributeError("compressor_cfg interface not found on DUT")

    dut.compressor_cfg.lane_mask.value = lane_mask & 0xFFF
    active_count = bin(lane_mask).count("1")
    dut._log.info(f"Compressor lane mask set to 0x{lane_mask:03X} ({active_count}/12 lanes)")


def compressor_get_stats(dut) -> dict:
    """Read compressor statistics.

    The combinational compressor model tracks no statistics; every count reads zero.

    Returns:
        Dictionary with dummy statistics (all zeros):
        {
            'sample_count': 0,
            'zero_count': 0,
            'pattern_detect': 0
        }

    Example:
        stats = compressor_get_stats(dut)
        # Returns all zeros - statistics not tracked in combinational model
    """
    return {
        "sample_count": 0,
        "zero_count": 0,
        "pattern_detect": 0,
    }


def decor_checker_get_stats(dut) -> dict:
    """Read decorrelator checker statistics.

    Returns:
        Dictionary with statistics:
        {
            'check_count': Total number of checks performed,
            'mismatch_count': Number of cycles with mismatches,
            'match_rate': Percentage of checks that passed (0.0-100.0)
        }

    Raises:
        AttributeError: If checker signals not found

    Example:
        stats = decor_checker_get_stats(dut)
        print(f"Checks: {stats['check_count']}, Mismatches: {stats['mismatch_count']}")
        print(f"Match rate: {stats['match_rate']:.2f}%")
    """
    if not hasattr(dut, "checker_check_count") or not hasattr(dut, "checker_mismatch_count"):
        raise AttributeError("Checker signals not found in DUT")

    check_count = int(dut.checker_check_count.value)
    mismatch_count = int(dut.checker_mismatch_count.value)

    # Calculate match rate
    if check_count > 0:
        match_rate = 100.0 * (check_count - mismatch_count) / check_count
    else:
        match_rate = 0.0

    return {
        "check_count": check_count,
        "mismatch_count": mismatch_count,
        "match_rate": match_rate,
    }


def decor_checker_verify(dut, log=None) -> None:
    """Verify decorrelator checker results and fail test if mismatches detected.

    Reads checker statistics and raises AssertionError if any mismatches were detected.
    Call this at the end of tests to ensure decorrelator outputs matched reference model.

    Args:
        dut: DUT instance
        log: Logger instance (optional, uses dut._log if not provided)

    Raises:
        AttributeError: If checker signals not found
        AssertionError: If mismatches were detected

    Example:
        # At end of test
        decor_checker_verify(dut)  # Fails test if mismatches detected
    """
    logger = log or dut._log

    if not hasattr(dut, "checker_check_count") or not hasattr(dut, "checker_mismatch_count"):
        logger.warning("Checker signals not found - skipping verification")
        return

    stats = decor_checker_get_stats(dut)

    if stats["check_count"] == 0:
        logger.warning(
            "  [WARN] Decorrelator Checker: No checks performed (checker may be disabled)"
        )
        return

    # Log that checker is alive (ran checks) - independent of pass/fail
    logger.info("  [DECOR CHECK] Decorrelator checker is ALIVE")

    if stats["mismatch_count"] == 0:
        logger.info(f"  [PASS] Decorrelator Checker: {stats['check_count']} checks, 0 mismatches")
    else:
        logger.error(
            f"  [FAIL] Decorrelator Checker: {stats['check_count']} checks, {stats['mismatch_count']} mismatches ({stats['match_rate']:.2f}% match rate)"
        )
        raise AssertionError(
            f"Decorrelator checker failed: {stats['mismatch_count']} cycles with mismatches "
            f"out of {stats['check_count']} checks ({100.0 - stats['match_rate']:.2f}% failure rate)"
        )


def compressor_checker_get_stats(dut) -> dict:
    """Read compressor checker statistics.

    Returns:
        Dictionary with statistics:
        {
            'check_count': Total number of checks performed,
            'mismatch_count': Number of mismatches detected,
            'match_rate': Percentage of checks that passed (0.0-100.0)
        }

    Raises:
        AttributeError: If checker signals not found

    Example:
        stats = compressor_checker_get_stats(dut)
        print(f"Checks: {stats['check_count']}, Mismatches: {stats['mismatch_count']}")
        print(f"Match rate: {stats['match_rate']:.2f}%")
    """
    if not hasattr(dut, "compressor_check_count") or not hasattr(dut, "compressor_mismatch_count"):
        raise AttributeError("Compressor checker signals not found in DUT")

    check_count = int(dut.compressor_check_count.value)
    mismatch_count = int(dut.compressor_mismatch_count.value)

    # Calculate match rate
    if check_count > 0:
        match_rate = 100.0 * (check_count - mismatch_count) / check_count
    else:
        match_rate = 0.0

    return {
        "check_count": check_count,
        "mismatch_count": mismatch_count,
        "match_rate": match_rate,
    }


def compressor_checker_verify(dut, log=None) -> None:
    """Verify compressor checker results and fail test if mismatches detected.

    Reads checker statistics and raises AssertionError if any mismatches were detected.
    Call this at the end of tests to ensure compressor outputs matched reference model.

    Args:
        dut: DUT instance
        log: Logger instance (optional, uses dut._log if not provided)

    Raises:
        AttributeError: If checker signals not found
        AssertionError: If mismatches were detected

    Example:
        # At end of test
        compressor_checker_verify(dut)  # Fails test if mismatches detected
    """
    logger = log or dut._log

    if not hasattr(dut, "compressor_check_count") or not hasattr(dut, "compressor_mismatch_count"):
        logger.warning("Compressor checker signals not found - skipping verification")
        return

    stats = compressor_checker_get_stats(dut)

    if stats["check_count"] == 0:
        logger.warning("  [WARN] Compressor Checker: No checks performed (checker may be disabled)")
        return

    # Log that checker is alive (ran checks) - independent of pass/fail
    logger.info("  [COMP CHECK] Compressor checker is ALIVE")

    if stats["mismatch_count"] == 0:
        logger.info(f"  [PASS] Compressor Checker: {stats['check_count']} checks, 0 mismatches")
    else:
        logger.error(
            f"  [FAIL] Compressor Checker: {stats['check_count']} checks, {stats['mismatch_count']} mismatches ({stats['match_rate']:.2f}% match rate)"
        )
        raise AssertionError(
            f"Compressor checker failed: {stats['mismatch_count']} mismatches "
            f"out of {stats['check_count']} checks ({100.0 - stats['match_rate']:.2f}% failure rate)"
        )


def irq_checker_verify(dut, apb, expected_irq: bool = True, log=None) -> None:
    """Verify IRQ checker - that interrupt was properly tested/verified.

    This function logs that IRQ verification was performed, making the IRQ
    checker appear as "ALIVE" in regression reports.

    Args:
        dut: DUT instance
        apb: APB master instance (for reading INTR_STATUS if needed)
        expected_irq: Expected IRQ state (True=asserted, False=deasserted)
        log: Logger instance (optional, uses dut._log if not provided)

    Raises:
        AssertionError: If IRQ state doesn't match expected

    Example:
        # After testing interrupt assertion
        irq_checker_verify(dut, apb, expected_irq=True)

        # After clearing interrupt
        irq_checker_verify(dut, apb, expected_irq=False)

    Note:
        This function is synchronous and should be called after async IRQ operations.
        It primarily serves to mark IRQ verification as "active" in test logs.
    """
    logger = log or dut._log

    # Log that IRQ checker is alive (ran checks) - independent of pass/fail
    logger.info("  [IRQ CHECK] IRQ checker is ALIVE")

    # Read actual IRQ state
    try:
        actual_irq = int(dut.irq.value)
    except AttributeError:
        logger.warning("  [WARN] IRQ signal not found - skipping IRQ verification")
        return

    # Verify IRQ state matches expectation
    if expected_irq:
        if actual_irq == 1:
            logger.info(f"  [PASS] IRQ verified: irq_o={actual_irq} (asserted as expected)")
        else:
            logger.error(f"  [FAIL] IRQ verification failed: irq_o={actual_irq} (expected HIGH)")
            raise AssertionError(f"IRQ should be asserted (HIGH), but got {actual_irq}")
    else:
        if actual_irq == 0:
            logger.info(f"  [PASS] IRQ verified: irq_o={actual_irq} (deasserted as expected)")
        else:
            logger.error(f"  [FAIL] IRQ verification failed: irq_o={actual_irq} (expected LOW)")
            raise AssertionError(f"IRQ should be deasserted (LOW), but got {actual_irq}")


async def irq_checker_verify_async(dut, apb, expected_irq: bool = True, log=None) -> None:
    """Async version of irq_checker_verify for use in async test contexts.

    Args:
        dut: DUT instance
        apb: APB master instance
        expected_irq: Expected IRQ state (True=asserted, False=deasserted)
        log: Logger instance (optional)

    Example:
        await irq_checker_verify_async(dut, apb, expected_irq=True)
    """
    from cocotb.triggers import Timer

    await Timer(1, units="ns")  # Tiny delay to ensure signal settled
    irq_checker_verify(dut, apb, expected_irq, log)


# ============================================================================
# FIFO Helper Functions
# ============================================================================


async def read_fifo_status(apb):
    """Read FIFO status register and return level, wptr, rptr.

    Args:
        apb: APB master instance

    Returns:
        Tuple of (level, wptr, rptr)

    Example:
        level, wptr, rptr = await read_fifo_status(apb)
    """
    status = await reg_rd(apb, "FIFO_STATUS")
    level = status & 0x7F
    wptr = (status >> 8) & 0x3F
    rptr = (status >> 16) & 0x3F
    return level, wptr, rptr


async def check_fifo_errors(dut, apb):
    """Check for FIFO overflow/underflow errors via interrupt status.

    Args:
        dut: DUT instance
        apb: APB master instance

    Returns:
        Tuple of (overflow, underflow) flags (0 or 1)

    Example:
        overflow, underflow = await check_fifo_errors(dut, apb)
    """
    intr_status = await reg_rd(apb, "INTR_STATUS")
    overflow = (intr_status >> 8) & 0x1
    underflow = (intr_status >> 12) & 0x1
    return overflow, underflow


async def clear_fifo_errors(apb):
    """Clear FIFO error flags via write-1-to-clear.

    Args:
        apb: APB master instance

    Example:
        await clear_fifo_errors(apb)
    """
    # Clear overflow (bit 8) and underflow (bit 12)
    await reg_wr(apb, "INTR_STATUS", 0x1100)


# ============================================================================
# Test Helper Functions
# ============================================================================


async def enable_entropy_pipeline(apb, ro_enable: int = 0xFFF, decorr_div: int = 64):
    """Enable standard entropy pipeline configuration.

    Args:
        apb: APB master instance
        ro_enable: Ring oscillator enable mask (default: 0xFFF = all 12 ROs)
        decorr_div: Decorrelator division factor (default: 64 for div-64)

    Example:
        await enable_entropy_pipeline(apb)  # Standard config
        await enable_entropy_pipeline(apb, decorr_div=8)  # Fast sampling
    """
    await reg_wr(apb, "FIFO_CTRL", 0x00000001)
    # Configure sampling clocks to use external clock (not internal RO clocks)
    # Default RING_OSC_CTRL.SAMPLE_CLK_SELECT = 0xFFF selects disabled RO clocks
    # Set to 0x000 to use external clock from testbench
    await reg_wr(apb, "RING_OSC_CTRL", 0x000)
    await reg_wr(apb, "RING_OSC_ENABLE", ro_enable)
    decorr_ctrl = (decorr_div - 1) << 12
    await reg_wr(apb, "DECORRELATOR_CTRL", decorr_ctrl)
    await reg_wr(apb, "DECORRELATOR_MASK", 0x000000FF)


async def configure_health_tests(
    apb,
    enable_rep: bool = True,
    enable_apt: bool = True,
    enable_markov: bool = True,
    rep_threshold: int = 25,
    apt_hi_limit: int = 1200,
    apt_lo_limit: int = 848,
    markov_thresholds: int = 0x006404B0,
):
    """Configure health test enables and thresholds.

    Args:
        apb: APB master instance
        enable_rep: Enable repetition test
        enable_apt: Enable APT test
        enable_markov: Enable Markov test
        rep_threshold: Repetition test threshold (8-bit)
        apt_hi_limit: Maximum accepted one count in an APT window
        apt_lo_limit: Minimum accepted one count in an APT window
        markov_thresholds: Packed high and low 16-bit Markov count thresholds

    Example:
        await configure_health_tests(apb)  # Default config
        await configure_health_tests(apb, rep_threshold=10,
                                     apt_hi_limit=1100, apt_lo_limit=948)
    """
    enables = int(enable_rep) | (int(enable_apt) << 1) | (int(enable_markov) << 2)
    ctrl_val = enables | (rep_threshold << 8)
    await reg_wr(apb, "HEALTH_TEST_CTRL", ctrl_val)
    await reg_wr(apb, "MARKOV_TEST_PROB_THRESHOLDS", markov_thresholds)
    await configure_apt_thresholds(apb, apt_hi_limit, apt_lo_limit)


async def configure_apt_thresholds(apb, high_limit: int = 1200, low_limit: int = 848):
    """Configure the APT high and low one-count limits.

    Args:
        apb: APB master instance
        high_limit: Fail when the window one count exceeds this value
        low_limit: Fail when the window one count is below this value
    """
    await reg_wr(apb, "APT_PROPORTION_1BIT", high_limit)
    await reg_wr(apb, "APT_PROPORTION_LO", low_limit)


async def enable_and_verify_interrupt(apb, intr_name: str, intr_bit: int, dut_log):
    """Enable interrupt and verify it's set.

    Args:
        apb: APB master instance
        intr_name: Interrupt name for logging (e.g., "HEALTH_TEST_FAILED")
        intr_bit: Interrupt bit position (0-15)
        dut_log: DUT logger instance

    Example:
        await enable_and_verify_interrupt(apb, "HEALTH_TEST_FAILED", 0, dut._log)
    """
    mask = 1 << intr_bit
    await reg_wr(apb, "INTR_ENABLE", mask)
    readback = await reg_rd(apb, "INTR_ENABLE")
    assert (readback & mask) == mask, f"INTR_ENABLE.{intr_name} should be 1"
    dut_log.info(f"INTR_ENABLE: 0x{readback:08X} ({intr_name} enabled)")


async def poll_for_irq_assertion(
    dut, timeout_cycles: int = 10000, poll_interval: int = 100
) -> bool:
    """Poll for irq_o assertion with timeout.

    Args:
        dut: DUT instance
        timeout_cycles: Maximum cycles to wait
        poll_interval: Cycles between checks

    Returns:
        True if IRQ asserted, False if timeout

    Example:
        if await poll_for_irq_assertion(dut):
            dut._log.info("IRQ detected!")
    """
    from cocotb.triggers import ClockCycles

    for i in range(timeout_cycles // poll_interval):
        await ClockCycles(dut.apb.pclk, poll_interval)
        irq = await read_irq_output(dut)

        if i % 10 == 0:
            dut._log.info(f"  Polling cycle {i}: irq_o={irq}")

        if irq == 1:
            dut._log.info(f"  >>> irq_o ASSERTED at cycle {i} ({i * poll_interval} clocks)")
            return True

    return False


async def poll_for_irq_deassertion(
    dut, timeout_cycles: int = 10000, poll_interval: int = 100
) -> bool:
    """Poll for irq_o deassertion (going LOW) with timeout.

    Complement to poll_for_irq_assertion(). Useful for verifying IRQ clears after
    handling interrupt.

    Args:
        dut: DUT instance
        timeout_cycles: Maximum cycles to wait
        poll_interval: Cycles between checks

    Returns:
        True if IRQ deasserted (went LOW), False if timeout

    Example:
        # After clearing interrupt
        if await poll_for_irq_deassertion(dut):
            dut._log.info("IRQ successfully cleared!")
        else:
            dut._log.error("IRQ did not clear - still HIGH")
    """
    from cocotb.triggers import ClockCycles

    for i in range(timeout_cycles // poll_interval):
        await ClockCycles(dut.apb.pclk, poll_interval)
        irq = await read_irq_output(dut)

        if i % 10 == 0:
            dut._log.info(f"  Polling cycle {i}: irq_o={irq}")

        if irq == 0:
            dut._log.info(f"  >>> irq_o DEASSERTED at cycle {i} ({i * poll_interval} clocks)")
            return True

    dut._log.error(f"  >>> irq_o did not deassert after {timeout_cycles} cycles")
    return False


async def configure_all_ros_stuck(dut, stuck_value: int = 0, num_lanes: int = 12):
    """Configure all RO lanes to stuck-at pattern.

    Args:
        dut: DUT instance
        stuck_value: Stuck value (0 or 1)
        num_lanes: Number of RO lanes (default: 12)

    Example:
        await configure_all_ros_stuck(dut, stuck_value=0)  # All stuck-at-0
    """
    dut._log.info(f"Configuring all {num_lanes} ROs as stuck-at-{stuck_value}...")
    for lane in range(num_lanes):
        await ro_model_set(dut, idx=lane, stuck=stuck_value)
    dut._log.info(f"All ROs configured: stuck-at-{stuck_value}")


async def configure_ro_stuck(dut, lane_config: dict, log: bool = True):
    """Configure specific RO lanes with individual stuck-at patterns or normal operation.

    More flexible than configure_all_ros_stuck() - allows per-lane control with
    arbitrary stuck values or normal operation. Useful for autotune tests that
    need selective failures on specific lanes.

    Args:
        dut: DUT instance
        lane_config: Dict mapping lane numbers to stuck values
                    - Key: lane number (0-11)
                    - Value: None (normal), 0 (stuck-at-0), or 1 (stuck-at-1)
        log: Whether to log configuration details (default: True)

    Example:
        # Configure even lanes stuck-at-0, odd lanes normal
        await configure_ro_stuck(dut, {
            0: 0, 1: None, 2: 0, 3: None,
            4: 0, 5: None, 6: 0, 7: None,
            8: 0, 9: None, 10: 0, 11: None
        })

        # Configure lanes 0-3 stuck-at-1, rest normal
        await configure_ro_stuck(dut, {0: 1, 1: 1, 2: 1, 3: 1})

        # Compact form for even lanes
        even_lanes = {i: 0 for i in range(0, 12, 2)}
        await configure_ro_stuck(dut, even_lanes)
    """
    if log:
        stuck_0_lanes = [l for l, v in lane_config.items() if v == 0]
        stuck_1_lanes = [l for l, v in lane_config.items() if v == 1]
        normal_lanes = [l for l, v in lane_config.items() if v is None]

        dut._log.info("Configuring per-lane RO patterns:")
        if stuck_0_lanes:
            dut._log.info(f"  Stuck-at-0: Lanes {stuck_0_lanes}")
        if stuck_1_lanes:
            dut._log.info(f"  Stuck-at-1: Lanes {stuck_1_lanes}")
        if normal_lanes:
            dut._log.info(f"  Normal:     Lanes {normal_lanes}")

    # Configure specified lanes
    for lane, stuck_value in lane_config.items():
        if lane < 0 or lane >= 12:
            dut._log.warning(f"  Skipping invalid lane {lane} (valid: 0-11)")
            continue
        await ro_model_set(dut, idx=lane, stuck=stuck_value)

    if log:
        dut._log.info(f"  [DONE] Configured {len(lane_config)} lanes")


async def configure_degraded_entropy(
    dut,
    apb,
    stuck_value: int = 0,
    num_lanes: int = 12,
    enable_bypass: bool = True,
    decorr_div: int = 63,
    wait_cycles: int = 0,
):
    """Configure degraded entropy for health test failure injection.

    This function configures the DUT to produce degraded entropy by:
    1. Setting all RO lanes to stuck-at pattern (stuck-at-0 or stuck-at-1)
    2. Optionally enabling decorrelator bypass (recommended for immediate effect)
    3. Optionally waiting for stabilization

    Args:
        dut: DUT instance
        apb: APB master instance
        stuck_value: Stuck-at value (0 or 1, default: 0)
        num_lanes: Number of RO lanes (default: 12)
        enable_bypass: Enable decorrelator bypass (default: True)
        decorr_div: Decorrelator clock divider value (default: 63 for div-64)
        wait_cycles: Stabilization wait cycles (default: 0)

    Example:
        # For repetition/Markov failure (stuck-at-0 + bypass)
        await configure_degraded_entropy(dut, apb, stuck_value=0, enable_bypass=True)

        # For maximum degradation test
        await configure_degraded_entropy(dut, apb, stuck_value=0, enable_bypass=True, wait_cycles=100)
    """
    from cocotb.triggers import ClockCycles

    # Configure all RO lanes to stuck-at pattern
    dut._log.info(
        f"Configuring degraded entropy: stuck-at-{stuck_value}, bypass={'ON' if enable_bypass else 'OFF'}"
    )
    for lane in range(num_lanes):
        await ro_model_set(dut, idx=lane, stuck=stuck_value)
    dut._log.info(f"  All {num_lanes} ROs configured: stuck-at-{stuck_value}")

    # Configure decorrelator bypass
    if enable_bypass:
        # BYPASS all lanes: mask=0xFFF (bits [11:0])
        decorr_ctrl = ((decorr_div) << 12) | 0xFFF
        await reg_wr(apb, "DECORRELATOR_CTRL", decorr_ctrl)
        dut._log.info(f"  Decorrelator: BYPASS enabled (mask=0xFFF), div={decorr_div + 1}")
    else:
        # No bypass: mask=0x000
        decorr_ctrl = ((decorr_div) << 12) | 0x000
        await reg_wr(apb, "DECORRELATOR_CTRL", decorr_ctrl)
        dut._log.info(f"  Decorrelator: BYPASS disabled (mask=0x000), div={decorr_div + 1}")

    # Optional stabilization wait
    if wait_cycles > 0:
        dut._log.info(f"  Waiting {wait_cycles} cycles for stabilization...")
        await ClockCycles(dut.apb.pclk, wait_cycles)


async def restore_normal_entropy_generation(dut, apb, num_lanes: int = 12, wait_cycles: int = 128):
    """Restore ROs and decorrelator to normal operation.

    Args:
        dut: DUT instance
        apb: APB master instance
        num_lanes: Number of RO lanes (default: 12)
        wait_cycles: Stabilization wait cycles (default: 128)

    Example:
        await restore_normal_entropy_generation(dut, apb)
    """
    from cocotb.triggers import ClockCycles

    dut._log.info("Restoring all ROs to normal operation...")
    for lane in range(num_lanes):
        await ro_model_set(dut, idx=lane, stuck=None)

    dut._log.info("Disabling decorrelator bypass...")
    await reg_wr(apb, "DECORRELATOR_CTRL", 0x0003F000)  # div-64, no bypass

    dut._log.info(f"Waiting {wait_cycles} cycles for stabilization...")
    await ClockCycles(dut.apb.pclk, wait_cycles)


async def clear_and_verify_interrupt(dut, apb, intr_bit: int, intr_name: str):
    """Clear interrupt via W1C and verify cleared.

    Args:
        dut: DUT instance
        apb: APB master instance
        intr_bit: Interrupt bit position
        intr_name: Interrupt name (snake_case) for status dict

    Example:
        await clear_and_verify_interrupt(dut, apb, 0, "health_test_failed")
    """
    from cocotb.triggers import ClockCycles

    await reg_wr(apb, "INTR_STATUS", 1 << intr_bit)
    await ClockCycles(dut.apb.pclk, 2)

    intr_status = await read_intr_status(apb)
    irq = await read_irq_output(dut)
    dut._log.info(f"After W1C: INTR_STATUS.{intr_name}={intr_status[intr_name]}, irq_o={irq}")

    assert intr_status[intr_name] == 0, f"INTR_STATUS.{intr_name} should be cleared"
    assert irq == 0, "irq_o should be LOW after clearing"


async def health_test_isr_recovery(
    dut, apb, test_type: str, restore_entropy_fn, new_threshold: int, dut_log=None
):
    """Common ISR recovery flow for health test failures.

    Implements the critical 3-phase ISR recovery pattern:
    1. Phase 7: Restore good entropy (stop failure source)
    2. Phase 8: Toggle enable (clear counter + update threshold)
    3. Phase 9: W1C (clear interrupt)

    This helper enforces the correct ordering to prevent interrupt re-assertion.
    CRITICAL: Good entropy must be restored BEFORE clearing the interrupt!

    Args:
        dut: DUT instance
        apb: APB master instance
        test_type: Health test type - "repetition", "apt", or "markov"
        restore_entropy_fn: Async function to restore good entropy generation.
                           Should be a coroutine that stops the failure source.
                           Examples:
                           - lambda: restore_normal_entropy_generation(dut, apb)
                           - async def: await ro_model_word32_set(dut, enable=False)
        new_threshold: New threshold value for the health test.
                      Should be higher than trigger threshold to prevent false alarms.
        dut_log: Optional logger (defaults to dut._log if not provided)

    Example (Repetition test):
        await health_test_isr_recovery(
            dut, apb,
            test_type="repetition",
            restore_entropy_fn=lambda: restore_normal_entropy_generation(dut, apb),
            new_threshold=50,
            dut_log=dut._log
        )

    Example (APT test with inline restore):
        async def restore_apt():
            await ro_model_word32_set(dut, enable=False)

        await health_test_isr_recovery(
            dut, apb, "apt", restore_apt, 600, dut._log
        )

    Example (Markov test with multi-step restore):
        async def restore_markov():
            await ro_model_word32_set(dut, enable=False)
            await reg_wr(apb, 'DECORRELATOR_CTRL', 0x0003F000)

        await health_test_isr_recovery(
            dut, apb, "markov", restore_markov, 100, dut._log
        )
    """
    from cocotb.triggers import ClockCycles

    if dut_log is None:
        dut_log = dut._log

    # ========================================================================
    # Phase 7: Restore good entropy FIRST (stop failure source)
    # ========================================================================
    dut_log.info("\n--- Phase 7: ISR - Restore good entropy (stop failure source) ---")
    dut_log.info("CRITICAL: Must restore good entropy BEFORE clearing interrupt!")

    # Call user-provided restoration function
    await restore_entropy_fn()

    # Verify IRQ remains HIGH (sticky interrupt behavior)
    dut_log.info("\nVerifying IRQ remains asserted after restoring entropy...")
    irq_after_restore = await read_irq_output(dut)
    if irq_after_restore == 1:
        dut_log.info(
            "  [PASS] irq_o still HIGH after restoring entropy (correct - sticky interrupt)"
        )
    else:
        dut_log.error("  [ERROR] irq_o went LOW after restoring entropy (should stay HIGH!)")
        assert False, "IRQ should remain asserted until W1C clears it"

    # ========================================================================
    # Phase 8: Toggle enable (clear counter + update threshold)
    # ========================================================================
    dut_log.info("\n--- Phase 8: ISR - Clear counter (toggle enable 0->1) ---")

    # Get test-specific configuration
    if test_type == "repetition":
        enable_bit = 0
        test_name = "Repetition"
        threshold_start_bit = 8
        threshold_num_bits = 8  # bits [15:8]
        threshold_register = "HEALTH_TEST_CTRL"
    elif test_type == "apt":
        enable_bit = 1
        test_name = "APT"
        threshold_start_bit = None
        threshold_num_bits = None
        threshold_register = "APT_PROPORTION_1BIT"
    elif test_type == "markov":
        enable_bit = 2
        test_name = "Markov"
        threshold_start_bit = None  # Separate register
        threshold_num_bits = None
        threshold_register = "MARKOV_TEST_PROB_THRESHOLDS"
    else:
        raise ValueError(
            f"Unknown test_type: {test_type}. Must be 'repetition', 'apt', or 'markov'"
        )

    # Step 8a: Disable test temporarily
    dut_log.info(f"[8a] Disabling {test_name} test...")
    ctrl_val = await reg_rd(apb, "HEALTH_TEST_CTRL")
    ctrl_val &= ~(1 << enable_bit)
    await reg_wr(apb, "HEALTH_TEST_CTRL", ctrl_val)
    await ClockCycles(dut.apb.pclk, 10)
    dut_log.info(f"  {test_name} test disabled")

    # Step 8b: Re-enable test with new threshold (toggle clears counter)
    dut_log.info(f"[8b] Re-enabling {test_name} test (toggle clears counter)...")
    ctrl_val |= 1 << enable_bit

    if test_type == "markov":
        await reg_wr(apb, "HEALTH_TEST_CTRL", ctrl_val)
        markov_threshold_val = (100 << 16) | new_threshold
        await reg_wr(apb, threshold_register, markov_threshold_val)
        dut_log.info(f"  {test_name} test re-enabled with limits: low=100, high={new_threshold}")
    elif test_type == "apt":
        await reg_wr(apb, "HEALTH_TEST_CTRL", ctrl_val)
        window_size = await reg_rd(apb, "HEALTH_TEST_WINDOW_SIZE") & 0xFFFF
        await configure_apt_thresholds(
            apb, high_limit=new_threshold, low_limit=max(0, window_size - new_threshold)
        )
        dut_log.info(
            f"  {test_name} test re-enabled with limits: "
            f"low={max(0, window_size - new_threshold)}, high={new_threshold}"
        )
    else:
        # Repetition has threshold in HEALTH_TEST_CTRL
        threshold_mask = ((1 << threshold_num_bits) - 1) << threshold_start_bit
        ctrl_val = (ctrl_val & ~threshold_mask) | (new_threshold << threshold_start_bit)
        await reg_wr(apb, "HEALTH_TEST_CTRL", ctrl_val)
        dut_log.info(f"  {test_name} test re-enabled with threshold={new_threshold}")

    # Step 8c: Wait for stabilization
    dut_log.info("[8c] Waiting for stabilization (128 cycles)...")
    await ClockCycles(dut.apb.pclk, 128)
    dut_log.info("  [PASS] Counter cleared, system stabilized with good entropy")

    # ========================================================================
    # Phase 9: Clear interrupt (W1C) - NOW SAFE
    # ========================================================================
    dut_log.info("\n--- Phase 9: ISR - Clear interrupt (W1C) ---")
    dut_log.info("Now safe to clear interrupt - good entropy restored, counter cleared")
    await clear_and_verify_interrupt(dut, apb, 0, "health_test_failed")
    dut_log.info("[PASS] Interrupt cleared successfully")


async def drain_fifo_to_level(apb, target_level: int = 10, dut_log=None) -> tuple:
    """Drain FIFO down to target level.

    Args:
        apb: APB master instance
        target_level: Target FIFO level (default: 10)
        dut_log: Optional logger for status messages

    Returns:
        Tuple of (drain_count, final_level)

    Example:
        drained, level = await drain_fifo_to_level(apb, target_level=10, dut_log=dut._log)
    """
    level, _, _ = await read_fifo_status(apb)
    drain_count = 0

    while level > target_level:
        await reg_rd(apb, "FIFO_RDATA")
        drain_count += 1
        level, _, _ = await read_fifo_status(apb)

    if dut_log:
        dut_log.info(f"Drained {drain_count} entries, new level={level}")

    return drain_count, level


# ============================================================================
# Interrupt Verification Helper Functions
# ============================================================================


async def read_intr_status(apb):
    """Read INTR_STATUS register and return dict of all interrupts.

    Args:
        apb: APB master instance

    Returns:
        Dict with keys: 'health_test_failed', 'fifo_error', 'fifo_overflow', 'fifo_underflow'

    Example:
        status = await read_intr_status(apb)
        if status['fifo_overflow']:
            print("Overflow detected!")
    """
    status = await reg_rd(apb, "INTR_STATUS")
    return {
        "health_test_failed": (status >> 0) & 0x1,
        "fifo_error": (status >> 4) & 0x1,
        "fifo_overflow": (status >> 8) & 0x1,
        "fifo_underflow": (status >> 12) & 0x1,
    }


async def read_irq_output(dut):
    """Read the global irq_o output signal.

    Args:
        dut: DUT instance (tb_entropy_top)

    Returns:
        IRQ value (0 or 1)

    Example:
        irq = await read_irq_output(dut)
        assert irq == 1, "IRQ should be asserted"
    """
    return int(dut.irq.value)


# ============================================================================
# Health Test Helper Functions
# ============================================================================


async def read_repetition_counter(apb):
    """Read repetition test counter value.

    Args:
        apb: APB master instance

    Returns:
        Repetition counter value (0-255)

    Example:
        count = await read_repetition_counter(apb)
    """
    reg_val = await reg_rd(apb, "REPETITION_TEST_COUNT")
    return reg_val & 0xFF


# ============================================================================
# High-Level Test Helper Functions (Reusable across tests)
# ============================================================================


def log_phase_header(dut, phase_name: str) -> None:
    """Print a phase or test header banner.

    Args:
        dut: DUT instance
        phase_name: Phase name to display
    """
    dut._log.info("\n" + "=" * 70)
    dut._log.info(phase_name)
    dut._log.info("=" * 70)


async def configure_testbench(dut, config: TestConfig = None):
    """Phase 1: Configure testbench (clocks, reset, models).

    Args:
        dut: DUT instance
        config: TestConfig instance (default: DEFAULT_CONFIG)

    Returns:
        Tuple of (apb_master, monitor, config)
    """
    cfg = config or DEFAULT_CONFIG

    log_phase_header(dut, "PHASE 1: TESTBENCH CONFIGURATION")

    # Step 1.1: Log configuration
    dut._log.info("\n[Step 1.1] Test Configuration:")
    dut._log.info(f"  APB Clock:       {cfg.clock.apb_freq_mhz:.1f} MHz")
    dut._log.info(f"  RO Sample Clock: {cfg.clock.rosc_freq_mhz:.1f} MHz")
    dut._log.info(f"  RO Injection:    {'ENABLED' if cfg.ro.inject_enabled else 'DISABLED'}")
    dut._log.info(f"  RO Lanes:        {cfg.ro.num_lanes}")
    dut._log.info(f"  Ref Model Mode:  {cfg.decorrelator.mode_name}")
    dut._log.info(f"  DUT Mode:        {cfg.decorrelator.dut_mode_name}")

    # Step 1.2: Initialize testbench
    dut._log.info("\n[Step 1.2] Initializing testbench (clocks and reset)...")
    apb, mon = await init(dut, config=cfg)
    dut._log.info("  [DONE] Clocks started, reset applied")

    # Step 1.3: Verify RO injection
    dut._log.info("\n[Step 1.3] Verifying RO injection control...")
    if hasattr(dut, "ro_inject_enable"):
        inject_status = int(dut.ro_inject_enable.value)
        dut._log.info(f"  ro_inject_enable = {inject_status}")
        assert inject_status == cfg.ro.inject_model, (
            f"RO injection mismatch: expected {cfg.ro.inject_model}, got {inject_status}"
        )
        dut._log.info("  [PASS] RO injection control verified")
    else:
        dut._log.warning("  [WARN] ro_inject_enable signal not found in DUT")

    # Step 1.4: Log decorrelator config
    dut._log.info("\n[Step 1.4] Decorrelator reference model configuration:")
    dut._log.info(f"  Mode:          {cfg.decorrelator.mode_name}")
    dut._log.info(f"  Sample Period: {cfg.decorrelator.sample_period} APB clocks")
    dut._log.info(
        f"  Checker:       {'ENABLED' if cfg.decorrelator.checker_enable else 'DISABLED'}"
    )

    # Step 1.5: Randomize RO model
    dut._log.info("\n[Step 1.5] Configuring RO model parameters...")
    await ro_model_randomize_all(dut, config=cfg)
    dut._log.info(f"  [DONE] All {cfg.ro.num_lanes} RO lanes configured")

    # Step 1.6: Log compressor config
    dut._log.info("\n[Step 1.6] Compressor reference model configuration:")
    if hasattr(dut, "compressor_cfg"):
        enable = int(dut.compressor_cfg.enable.value)
        bypass = int(dut.compressor_cfg.bypass.value)
        lane_mask = int(dut.compressor_cfg.lane_mask.value)
        mode_name = "BYPASS" if bypass else "BIW_EXTRACTION"
        active_lanes = bin(lane_mask).count("1")
        dut._log.info(f"  Mode:      {mode_name}")
        dut._log.info(f"  Enabled:   {bool(enable)}")
        dut._log.info(f"  Lane Mask: 0x{lane_mask:03X} ({active_lanes}/12 lanes)")
    else:
        dut._log.warning("  [WARN] Compressor reference model not found")

    dut._log.info("\n" + "=" * 70)
    dut._log.info("[PHASE 1 COMPLETE] Testbench configured and ready")
    dut._log.info("=" * 70)

    return apb, mon, cfg


async def program_dut_registers(dut, apb: APBMaster, config: TestConfig) -> None:
    """Phase 2: Program DUT registers via APB.

    Args:
        dut: DUT instance
        apb: APB master instance
        config: TestConfig instance
    """
    cfg = config
    log_phase_header(dut, "PHASE 2: DUT PROGRAMMING (APB Register Access)")

    # Step 2.0: Program CTRL register
    dut._log.info("\n[Step 2.0] Programming CTRL register...")
    bypass_comp_bit = 1 if cfg.bypass_compressor_dut else 0
    downsample_val = cfg.downsample_rate & 0x3FF  # 10-bit field
    ctrl_val = (downsample_val << 16) | (bypass_comp_bit << 8)
    await reg_wr(apb, "CTRL", ctrl_val)
    dut._log.info(f"  CTRL = 0x{ctrl_val:08X}")
    dut._log.info(
        f"    BYPASS_ENTROPY_COMPRESSOR[8] = {bypass_comp_bit} ({'bypass' if bypass_comp_bit else 'enabled'})"
    )
    dut._log.info(
        f"    DOWNSAMPLE_RATE[25:16] = {downsample_val} ({'no downsample' if downsample_val == 0 else f'drop {downsample_val}, then 1-in-{downsample_val + 1}'})"
    )

    # Step 2.1: Program DECORRELATOR_CTRL
    dut._log.info("\n[Step 2.1] Programming DECORRELATOR_CTRL register...")
    bypass_val = cfg.decorrelator.bypass_mask if cfg.decorrelator.bypass_dut else 0x000
    decorr_ctrl_val = (cfg.decorrelator.sample_clk_div << 12) | (bypass_val & 0xFFF)
    await reg_wr(apb, "DECORRELATOR_CTRL", decorr_ctrl_val)
    dut._log.info(f"  DECORRELATOR_CTRL = 0x{decorr_ctrl_val:08X}")

    # Step 2.2: Enable FIFO
    dut._log.info("\n[Step 2.2] Enabling FIFO for data collection...")
    await reg_wr(apb, "FIFO_CTRL", 0x00000001)
    dut._log.info("  FIFO_CTRL = 0x00000001 (FIFO enabled)")

    # Step 2.3: Program DECORRELATOR_MASK
    dut._log.info("\n[Step 2.3] Programming DECORRELATOR_MASK register...")
    await reg_wr(apb, "DECORRELATOR_MASK", 0x000000FF)
    dut._log.info("  DECORRELATOR_MASK = 0xFF (8 lanes enabled)")

    # Step 2.4: Program RING_OSC_ENABLE
    dut._log.info("\n[Step 2.4] Programming RING_OSC_ENABLE register...")
    ro_enable_val = 0x00000FFF  # Enable all 12 noise ROs
    await reg_wr(apb, "RING_OSC_ENABLE", ro_enable_val)
    dut._log.info(f"  RING_OSC_ENABLE = 0x{ro_enable_val:08X}")

    dut._log.info("\n" + "=" * 70)
    dut._log.info("[PHASE 2 COMPLETE] DUT programmed via APB")
    dut._log.info("=" * 70)


async def collect_entropy_samples(dut, config: TestConfig, num_samples: int):
    """Phase 3: Collect entropy samples and golden compressed words.

    Args:
        dut: DUT instance
        config: TestConfig instance
        num_samples: Number of samples to collect

    Returns:
        Tuple of (ref_samples, golden_queue)
    """
    from cocotb.triggers import RisingEdge

    cfg = config
    log_phase_header(dut, "PHASE 3: SAMPLE COLLECTION")

    dut._log.info(f"\n[Observe] Collecting {num_samples} decorrelator samples...")
    dut._log.info("           (Also collecting golden compressed words)")
    dut._log.info("-" * 70)

    ref_samples = []
    golden_queue = []

    if not hasattr(dut, "entropy_bytes_vld"):
        dut._log.error("[ERROR] entropy_bytes_vld signal not found!")
        raise AssertionError("Required decorrelator signals not accessible")

    # Determine which decorrelator output to use
    use_masked = hasattr(dut, "entropy_bytes_masked_flat")
    if use_masked:
        dut._log.info("[Info] Using entropy_bytes_masked_flat (DECORRELATOR_MASK applied)")
    else:
        dut._log.info("[Info] Using entropy_bytes_flat (unmasked, DECORRELATOR_MASK=0xFF assumed)")

    for sample_num in range(num_samples):
        # Wait for next valid pulse
        await RisingEdge(dut.entropy_bytes_vld)
        await ReadOnly()

        # Collect decorrelator output (prefer masked bytes to match DUT behavior)
        if hasattr(dut, "entropy_bytes_masked_flat"):
            # Use masked bytes (matches DUT decorrelator output with DECORRELATOR_MASK applied)
            packed = int(dut.entropy_bytes_masked_flat.value)
            ref_bytes = [(packed >> (8 * i)) & 0xFF for i in range(cfg.ro.num_lanes)]
            ref_samples.append(ref_bytes)
        elif hasattr(dut, "entropy_bytes_flat"):
            # Without the masked view, compare against the raw lane bytes.
            packed = int(dut.entropy_bytes_flat.value)
            ref_bytes = [(packed >> (8 * i)) & 0xFF for i in range(cfg.ro.num_lanes)]
            ref_samples.append(ref_bytes)

        # Collect golden compressed word
        if hasattr(dut, "compressed_word") and hasattr(dut, "compressed_vld"):
            comp_vld = int(dut.compressed_vld.value)
            if comp_vld:
                golden_word = int(dut.compressed_word.value)
                golden_queue.append(golden_word)
                # Show first few
                if sample_num < 3:
                    dut._log.info(f"  Golden[{sample_num}] = 0x{golden_word:08X}")

        # Show sample details (first 3, last 2 only)
        if hasattr(dut, "entropy_bytes_flat"):
            show_sample = (sample_num < 3) or (sample_num >= num_samples - 2)
            if show_sample:
                hex_str = " ".join([f"0x{b:02X}" for b in ref_bytes])
                dut._log.info(f"  Sample[{sample_num}]: {hex_str}")
            elif sample_num == 3:
                dut._log.info("  ... (showing first 3 and last 2 only)")

    dut._log.info(f"\n[Summary] Collected {len(ref_samples)} decorrelator samples")
    dut._log.info(f"[Summary] Collected {len(golden_queue)} golden compressed words")

    dut._log.info("\n" + "=" * 70)
    dut._log.info("[PHASE 3 COMPLETE] Sample collection complete")
    dut._log.info("=" * 70)

    return ref_samples, golden_queue


async def verify_fifo_readout(
    dut, apb: APBMaster, golden_queue: list, num_samples: int, downsample_rate: int = 0
) -> None:
    """Phase 4: Verify FIFO readout against golden queue.

    Args:
        dut: DUT instance
        apb: APB master instance
        golden_queue: List of golden compressed words (all compressed_vld from model)
        num_samples: Target number of samples
        downsample_rate: RTL's CTRL.DOWNSAMPLE_RATE (default 0)

    RTL Behavior:
        - If downsample_rate=0: NO drops, push EVERY compressed_vld to FIFO (1-in-1)
        - If downsample_rate=N: Drop first N, then push 1 out of every (N+1) compressed_vld
    """
    from cocotb.triggers import RisingEdge

    log_phase_header(dut, "PHASE 4: FIFO READOUT VERIFICATION")

    # Determine drop count and downsampling behavior
    rtl_drop_count = downsample_rate  # Rate=0 means no drops, Rate=N means drop first N
    continuous_downsample = downsample_rate > 0

    dut._log.info(f"Target samples: {num_samples}")
    dut._log.info(f"Golden queue: {len(golden_queue)} samples (all compressed_vld)")
    dut._log.info(f"Downsample rate: {downsample_rate}")
    dut._log.info(f"  RTL drops first: {rtl_drop_count}")
    dut._log.info(
        f"  After drops: {'1-in-' + str(downsample_rate) + ' sampling' if continuous_downsample else 'capture all'}\n"
    )

    if len(golden_queue) == 0:
        dut._log.warning("[SKIP] Golden queue is empty")
        return

    # Disable ROs to stop entropy generation (proper way to freeze FIFO push)
    await RisingEdge(dut.apb.pclk)
    dut._log.info("[Freeze] Disabling RING_OSC_ENABLE to stop entropy generation...")
    await reg_wr(apb, "RING_OSC_ENABLE", 0x00000000)

    # Wait for pipeline to drain
    from cocotb.triggers import ClockCycles

    await ClockCycles(dut.apb.pclk, 10)
    dut._log.info("  ROs disabled, pipeline drained\n")

    # Check FIFO status (FIFO stays enabled for reading)
    dut._log.info("[Step 1] Reading FIFO status...")
    fifo_status = await reg_rd(apb, "FIFO_STATUS")
    fifo_level = fifo_status & 0x7F
    dut._log.info(f"  FIFO level: {fifo_level} entries\n")

    # Check for errors
    dut._log.info("[Step 2] Checking for FIFO errors...")
    intr_status = await reg_rd(apb, "INTR_STATUS")
    fifo_overflow = (intr_status >> 8) & 0x1
    fifo_underflow = (intr_status >> 12) & 0x1

    if fifo_overflow or fifo_underflow:
        dut._log.error("[FAIL] FIFO error detected!")
        raise AssertionError("FIFO overflow or underflow detected")
    dut._log.info("  [PASS] No overflow/underflow\n")

    # Pre-process golden_queue to match RTL behavior
    dut._log.info("[Step 3] Pre-processing golden queue to match RTL behavior...")

    if len(golden_queue) <= rtl_drop_count:
        dut._log.warning(f"  Golden queue ({len(golden_queue)}) <= drop count ({rtl_drop_count})")
        dut._log.warning("  Insufficient golden entries - cannot verify!")
        return

    # Step 3a: Drop first entries (if any)
    after_drops = golden_queue[rtl_drop_count:]
    if rtl_drop_count > 0:
        dut._log.info(f"  Step 3a: Dropped first {rtl_drop_count} entries")
        dut._log.info(f"           Remaining: {len(after_drops)} samples")
    else:
        dut._log.info(f"  Step 3a: No drops (rate=0), using all {len(after_drops)} golden samples")

    # Step 3b: Apply continuous downsampling if needed
    if continuous_downsample:
        # Keep every Nth entry (1-in-N sampling after initial drops)
        adjusted_golden = after_drops[::downsample_rate]
        dut._log.info(f"  Step 3b: Applied 1-in-{downsample_rate} downsampling")
        dut._log.info(f"           Final adjusted golden: {len(adjusted_golden)} samples")
    else:
        # DOWNSAMPLE_RATE=0: Capture all samples (1-in-1, no drops, no downsampling)
        adjusted_golden = after_drops
        dut._log.info(
            f"  Step 3b: No downsampling (rate=0), keeping all {len(adjusted_golden)} samples"
        )

    dut._log.info("")

    # Determine alignment
    dut._log.info("[Step 4] Determining alignment...")
    golden_skip = 0
    fifo_skip = 0

    if fifo_level < len(adjusted_golden):
        golden_skip = len(adjusted_golden) - fifo_level
        num_to_verify = fifo_level
        dut._log.info(f"  FIFO has fewer - skip first {golden_skip} from adjusted golden")
    elif fifo_level > len(adjusted_golden):
        fifo_skip = fifo_level - len(adjusted_golden)
        num_to_verify = len(adjusted_golden)
        dut._log.info(f"  FIFO has more - skip first {fifo_skip} from FIFO")
    else:
        num_to_verify = len(adjusted_golden)
        dut._log.info("  Perfect alignment!")

    dut._log.info(f"  Will verify {num_to_verify} samples\n")

    # Ensure we have something to verify
    if num_to_verify == 0:
        dut._log.error("[FAIL] No samples to verify!")
        dut._log.error(f"  FIFO level: {fifo_level}")
        dut._log.error(f"  Adjusted golden queue: {len(adjusted_golden)}")
        raise AssertionError("FIFO verification failed: No samples to compare")

    # Skip FIFO entries if needed (FIFO is already enabled, can read directly)
    if fifo_skip > 0:
        dut._log.info(f"[Step 5] Skipping first {fifo_skip} FIFO entries...")
        for i in range(fifo_skip):
            await reg_rd(apb, "FIFO_RDATA")
        dut._log.info("")

    # Compare aligned portions
    dut._log.info(f"[Step 6] Comparing {num_to_verify} samples...")
    dut._log.info("-" * 70)

    # Log that FIFO checker is alive (actively verifying) - independent of pass/fail
    dut._log.info("[FIFO CHECK] FIFO checker is ALIVE")

    fifo_mismatch_count = 0
    for i in range(num_to_verify):
        fifo_word = await reg_rd(apb, "FIFO_RDATA")
        golden_word = adjusted_golden[golden_skip + i]
        match = fifo_word == golden_word

        # Show first 5, last 2, and all mismatches
        if i < 5 or i >= num_to_verify - 2 or not match:
            status = "MATCH" if match else "MISMATCH"
            dut._log.info(
                f"  [{i:2d}] FIFO: 0x{fifo_word:08X}  Golden: 0x{golden_word:08X}  [{status}]"
            )
            if not match:
                dut._log.error(f"       XOR: 0x{fifo_word ^ golden_word:08X}")
                fifo_mismatch_count += 1
        elif i == 5:
            dut._log.info("  ... (showing first 5 and last 2 only)")

    # Report results
    if fifo_mismatch_count == 0:
        dut._log.info(f"\n[PASS] All {num_to_verify} samples matched!")
    else:
        dut._log.error(f"\n[FAIL] {fifo_mismatch_count}/{num_to_verify} mismatches!")
        raise AssertionError(f"FIFO verification failed: {fifo_mismatch_count} mismatches")

    dut._log.info("\n" + "=" * 70)
    dut._log.info("[PHASE 4 COMPLETE] FIFO readout verified")
    dut._log.info("=" * 70)


async def verify_checkers(dut) -> None:
    """Phase 5: Verify all checkers.

    Args:
        dut: DUT instance
    """
    log_phase_header(dut, "PHASE 5: CHECKER VERIFICATION")

    dut._log.info("\n[5.1] Decorrelator Checker Verification")
    decor_checker_verify(dut)

    dut._log.info("\n[5.2] Compressor Checker Verification")
    compressor_checker_verify(dut)

    dut._log.info("\n" + "=" * 70)
    dut._log.info("[PHASE 5 COMPLETE] All checker verifications passed")
    dut._log.info("=" * 70)


def print_test_summary(dut, config: TestConfig, ref_samples: list, golden_queue: list) -> None:
    """Print test summary.

    Args:
        dut: DUT instance
        config: TestConfig instance
        ref_samples: List of decorrelator samples collected
        golden_queue: List of golden compressed words
    """
    cfg = config

    dut._log.info("\n" + "=" * 70)
    dut._log.info("TEST SUMMARY")
    dut._log.info("=" * 70)

    dut._log.info("\nConfiguration:")
    dut._log.info(
        f"  Clock: APB {cfg.clock.apb_freq_mhz:.1f} MHz, RO {cfg.clock.rosc_freq_mhz:.1f} MHz"
    )
    dut._log.info(
        f"  RO Model: {cfg.ro.num_lanes} lanes, injection {('ENABLED' if cfg.ro.inject_enabled else 'DISABLED')}"
    )
    dut._log.info(
        f"  Decorrelator: {cfg.decorrelator.mode_name}, {cfg.decorrelator.sample_period} cycle period"
    )
    dut._log.info(
        f"  DUT Mode: {cfg.decorrelator.dut_mode_name}, div-{cfg.decorrelator.actual_division} clock"
    )

    dut._log.info("\nResults:")
    dut._log.info("  [PASS] Testbench configured")
    dut._log.info("  [PASS] DUT programmed via APB")
    dut._log.info("  [PASS] RO model auto-synchronized")
    dut._log.info(f"  [PASS] Decorrelator samples collected: {len(ref_samples)}")

    if cfg.fifo_verification_enable and len(golden_queue) > 0:
        dut._log.info(f"  [PASS] FIFO readout: {len(golden_queue)} samples verified")

    dut._log.info("\n" + "=" * 70)
    dut._log.info("[PASS] Test completed successfully!")
    dut._log.info("=" * 70)


# ============================================================================
# Golden Reference Model for Repetition Counter
# ============================================================================


class RepetitionCounterGolden:
    """Golden reference model for repetition counter

    Monitors entropy samples and calculates expected repetition counter value.
    The repetition test counts RUN LENGTH (total occurrences, not repetitions).

    Counter semantics (matching the RTL):
    - First bit: count = 1 (run length of 1)
    - Second identical bit: count = 2 (run length of 2)
    - Third identical bit: count = 3 (run length of 3)
    - Different bit: count = 1 (new run starts with length 1)

    Example: 0x55555550 = 0000_0101_0101_0101_0101_0101_0101_0101 (LSB first)
             -> Scanning left to right: 0,0,0,0,0,1,0,1,0,1,...
             -> First 0: count=1, Second 0: count=2, Third 0: count=3, Fourth 0: count=4
             -> Then 1: count=1 (new bit, run length 1)

    Counter saturates at the configured threshold.
    """

    def __init__(self, threshold: int):
        """Initialize golden model

        Args:
            threshold: Counter saturation value (typically 10-255)
        """
        self.threshold = threshold
        self.counter = 0  # Run length count (starts at 0, becomes 1 on first bit)
        self.previous_bit = None
        self.sample_count = 0

    def update(self, entropy_sample: int, valid: bool):
        """Update golden model with new entropy sample

        Processes each bit in the 32-bit sample sequentially (LSB first).
        Counts run length:
        - First bit: counter = 1 (run starts at length 1)
        - Same bit: counter += 1 (run length increases)
        - Different bit: counter = 1 (new run starts at length 1)
        - Counter saturates at threshold

        Args:
            entropy_sample: 32-bit entropy value
            valid: True if sample is valid
        """
        if not valid:
            return

        self.sample_count += 1

        # Process each bit in the sample (LSB first, bit 0 to bit 31)
        for bit_idx in range(32):
            current_bit = (entropy_sample >> bit_idx) & 0x1

            if self.previous_bit is None:
                # First bit ever - initialize with run length 1
                self.previous_bit = current_bit
                self.counter = 1
                continue

            # Compare current bit with previous bit
            if current_bit == self.previous_bit:
                # Same bit - run continues, increment length
                if self.counter < self.threshold:
                    self.counter += 1
                # Counter saturates at threshold
            else:
                # Different bit - new run starts with length 1
                self.counter = 1
                self.previous_bit = current_bit

    def get_expected_count(self) -> int:
        """Get expected counter value

        Returns:
            Expected repetition counter value (0 to threshold)
        """
        return self.counter

    def reset(self):
        """Reset golden model to initial state"""
        self.counter = 0
        self.previous_sample = None
        self.sample_count = 0


async def verify_health_test_counters(apb, expected_ranges=None, log_verbose=True, dut_log=None):
    """Read and verify all health test counter registers.

    Args:
        apb: APB master interface
        expected_ranges: Dict with expected min/max values for each counter
                        Example: {
                            'repetition': (0, 50),
                            'apt_hi': (400, 600),
                            'markov_01': (1000, None)
                        }
        log_verbose: If True, log all counter values; if False, log summary only
        dut_log: Logger instance for output (optional)

    Returns:
        Dict with:
            - 'counters': Dict of all counter values
            - 'errors': List of error strings
    """
    counters = {}
    errors = []

    # Read repetition counter
    counters["repetition"] = await reg_rd(apb, "REPETITION_TEST_COUNT")

    # Read the retained high and low APT count views.
    counters["apt_hi"] = await reg_rd(apb, "APT_PATTERN_COUNT_1BIT")
    counters["apt_lo"] = await reg_rd(apb, "APT_PATTERN_COUNT_2BIT")

    # Read Markov counters. The two fields are the per-lane maximum and minimum
    # alternation count, not per-direction transition counts, so they do not sum
    # to a transition total.
    markov_counts_0 = await reg_rd(apb, "MARKOV_TEST_COUNTS_0")
    counters["markov_01"] = markov_counts_0 & 0xFFFF  # Lower 16 bits
    counters["markov_10"] = (markov_counts_0 >> 16) & 0xFFFF  # Upper 16 bits

    # Logging
    if log_verbose and dut_log:
        dut_log.info("  Health Test Counters:")
        dut_log.info(f"    REP={counters['repetition']}")
        dut_log.info(f"    APT: high={counters['apt_hi']}, low={counters['apt_lo']}")
        dut_log.info(f"    MARKOV: max={counters['markov_01']}, min={counters['markov_10']}")

    # Verification against expected ranges
    if expected_ranges:
        for name, (min_val, max_val) in expected_ranges.items():
            value = counters.get(name)
            if value is None:
                continue
            if min_val is not None and value < min_val:
                errors.append(f"{name} counter ({value}) below minimum ({min_val})")
            if max_val is not None and value > max_val:
                errors.append(f"{name} counter ({value}) above maximum ({max_val})")

    return {"counters": counters, "errors": errors}


async def monitor_per_lane_health_status(
    apb, lanes=None, expected_failures=None, log_details=False, dut_log=None
):
    """Read and analyze per-lane health test status for all 12 generators.

    Args:
        apb: APB master interface
        lanes: List of lanes to check (default: all 12)
        expected_failures: Dict mapping lane numbers to expected failure bits
                          Example: {0: 0x01, 2: 0x01, 4: 0x01} (even lanes, repetition)
        log_details: If True, log detailed bit decode; if False, summary only
        dut_log: Logger instance for output (optional)

    Returns:
        Dict with:
            - 'lane_status': Dict of lane_number -> status_byte
            - 'failures': Dict of test_type -> list_of_failed_lanes
                         Keys: 'repetition', 'apt', 'markov'
            - 'errors': List of error strings
    """
    if lanes is None:
        lanes = range(12)

    lane_status = {}
    failures = {"repetition": [], "apt": [], "markov": []}
    errors = []

    # Read all lane status registers
    for lane in lanes:
        reg_name = f"GENERATOR_{lane}_HEALTH_STATUS"
        status = await reg_rd(apb, reg_name)
        lane_status[lane] = status

        # Decode status bits
        # Bit [0]: Repetition test failure
        # Bit [3]: APT test failure
        # Bits [4] and [5]: Markov high- and low-threshold failures
        if status & 0x01:
            failures["repetition"].append(lane)
        if status & 0x08:
            failures["apt"].append(lane)
        if status & 0x30:
            failures["markov"].append(lane)

        if log_details and dut_log:
            rep_char = "F" if (status & 0x01) else "P"
            apt_char = "F" if (status & 0x08) else "P"
            markov_bits = (status >> 4) & 0x3
            dut_log.info(
                f"  Lane {lane:2d}: 0x{status:02X} "
                f"[Rep={rep_char} APT={apt_char} Markov=0x{markov_bits:X}]"
            )

    # Summary logging
    if dut_log:
        if failures["repetition"]:
            dut_log.info(f"  Repetition failures: Lanes {failures['repetition']}")
        if failures["apt"]:
            dut_log.info(f"  APT failures: Lanes {failures['apt']}")
        if failures["markov"]:
            dut_log.info(f"  Markov failures: Lanes {failures['markov']}")

    # Verification against expectations
    if expected_failures:
        for lane, expected_bits in expected_failures.items():
            actual_bits = lane_status.get(lane, 0)
            if (actual_bits & expected_bits) != expected_bits:
                errors.append(
                    f"Lane {lane}: expected failure bits 0x{expected_bits:02X}, "
                    f"got 0x{actual_bits:02X}"
                )

    return {"lane_status": lane_status, "failures": failures, "errors": errors}


async def verify_autotune_detune_pattern(
    apb, dut, expected_lanes, min_count=None, exact_match=False, dut_log=None
):
    """Verify autotune FSM detune pattern by probing RTL signals.

    Probes per-lane RTL signals:
    - tb_entropy_top.dut.egen.gen_ecmplx[lane].gen_inst.nsrc.ro.detune_i
    - tb_entropy_top.dut.egen.gen_ecmplx[lane].gen_inst.test_fail

    Args:
        apb: APB master interface
        dut: DUT instance for RTL signal probing
        expected_lanes: List of lane numbers expected to be detuned (e.g., [0,2,4,6,8,10])
        min_count: Minimum number of lanes that must be detuned (None = no check)
        exact_match: If True, ONLY expected_lanes should be detuned; if False, allow extras
        dut_log: Logger instance for output (optional)

    Returns:
        Dict with:
            - 'detune_bits': The raw detune status value (composite 12-bit)
            - 'detuned_lanes': List of lane numbers that are detuned
            - 'per_lane_status': List of dicts with lane, detune_i, test_fail per lane
            - 'errors': List of error strings
    """
    # Probe RTL signals for all 12 lanes
    detune_bits = 0
    detuned_lanes = []
    per_lane_status = []

    if dut_log:
        dut_log.info("  Probing per-lane RTL signals:")
        dut_log.info("  Lane | detune_i | test_fail | Status")
        dut_log.info("  -----|----------|-----------|-------")

    # Probe per-lane detune signals from RTL using the exposed rtl_detune_flat vector
    # When autotune is enabled, this shows FSM state; when disabled, shows register value
    # Path: tb_entropy_top.rtl_detune_flat[11:0] (exposed from debug_signals.svh)

    # Read the 12-bit detune vector once
    try:
        detune_flat_sig = dut.rtl_detune_flat
        detune_bits = int(detune_flat_sig.value) & 0xFFF
    except AttributeError as e:
        if dut_log:
            dut_log.warning(f"Cannot access rtl_detune_flat, using register fallback - {e}")
        # Fallback: read from register input (only correct when autotune disabled)
        try:
            detune_bits = int(dut.dut.egen.jitter_ro_detune_i.value) & 0xFFF
        except AttributeError:
            detune_bits = 0

    # Extract per-lane detune values from the composite vector
    for lane in range(12):
        detune_value = (detune_bits >> lane) & 0x1

        # Read per-lane health status from APB to get test_fail info
        try:
            health_status = await reg_rd(apb, f"GENERATOR_{lane}_HEALTH_STATUS")
            test_fail_value = health_status & 0xFF  # All 8 bits of health status
        except Exception:
            test_fail_value = 0

        # Store per-lane status
        per_lane_status.append(
            {"lane": lane, "detune_i": detune_value, "test_fail": test_fail_value}
        )

        # Build composite detune bits and detuned lanes list
        if detune_value:
            detune_bits |= 1 << lane
            detuned_lanes.append(lane)

        # Log per-lane status
        if dut_log:
            status_str = "DETUNE" if detune_value else "OK    "
            dut_log.info(
                f"   {lane:2d}  |    {detune_value}     |    0x{test_fail_value:02X}    | {status_str}"
            )

    if dut_log:
        dut_log.info(f"\n  Composite DETUNE: 0x{detune_bits:03X} -> Lanes {detuned_lanes}")

    errors = []

    # Check minimum count
    if min_count is not None and len(detuned_lanes) < min_count:
        errors.append(
            f"Insufficient lanes detuned: {len(detuned_lanes)}/{min_count} (expected at least {min_count})"
        )

    # Check expected lanes are detuned
    for lane in expected_lanes:
        if lane not in detuned_lanes:
            errors.append(f"Lane {lane} not detuned (expected to be detuned)")

    # Check for unexpected detunes (if exact_match requested)
    if exact_match:
        for lane in detuned_lanes:
            if lane not in expected_lanes:
                errors.append(f"Lane {lane} unexpectedly detuned")

    return {
        "detune_bits": detune_bits,
        "detuned_lanes": detuned_lanes,
        "per_lane_status": per_lane_status,
        "errors": errors,
    }


async def monitor_repetition_counter_golden(
    dut, apb, threshold: int, duration_cycles: int
) -> tuple:
    """Monitor repetition counter and compare CSR against golden reference

    Probes the entropy input to the repetition test module and builds a golden
    reference model. Periodically reads the REPETITION_TEST_COUNT CSR and compares
    against the golden value.

    Args:
        dut: DUT instance
        apb: APB master interface for CSR reads
        threshold: Configured repetition threshold
        duration_cycles: Number of cycles to monitor

    Returns:
        Tuple of (final_csr_value, final_golden_value, mismatch_count)
    """
    from cocotb.triggers import RisingEdge

    # Initialize golden model
    golden = RepetitionCounterGolden(threshold)

    # Find the repetition test module signals
    # Path: tb_entropy_top.dut.htst.reptst
    try:
        reptst = dut.dut.htst.reptst
        # Probe entropy input and valid signal
        entropy_signal = reptst.entropy_i
        valid_signal = reptst.entropy_valid_i
    except AttributeError as e:
        dut._log.error(f"Failed to find repetition test signals: {e}")
        return (0, 0, 0)

    dut._log.info(f"\n[GOLDEN MODEL] Monitoring repetition counter for {duration_cycles} cycles")
    dut._log.info(f"  Threshold: {threshold}")
    dut._log.info("  Probing: entropy_i, entropy_valid_i")

    mismatch_count = 0
    check_interval = 100  # Check every 100 cycles
    last_logged_entropy = None
    last_logged_valid = None

    for cycle in range(duration_cycles):
        await RisingEdge(dut.apb.pclk)

        # Sample entropy and valid on each clock edge
        try:
            entropy_val = int(entropy_signal.value)
            valid_val = int(valid_signal.value)

            # Track last entropy/valid for logging
            if valid_val == 1:
                last_logged_entropy = entropy_val
                last_logged_valid = True

            # Update golden model
            golden.update(entropy_val, valid_val == 1)

        except ValueError:
            # Handle 'x' or 'z' values
            pass

        # Periodically check CSR against golden
        if (cycle + 1) % check_interval == 0:
            rep_count_csr = await reg_rd(apb, "REPETITION_TEST_COUNT")
            csr_value = rep_count_csr & 0xFF
            golden_value = golden.get_expected_count()

            # Log with entropy_i value
            if last_logged_entropy is not None:
                entropy_str = f"0x{last_logged_entropy:08X}"
            else:
                entropy_str = "N/A"

            if csr_value != golden_value:
                mismatch_count += 1
                dut._log.warning(
                    f"  Cycle {cycle + 1}: entropy_i={entropy_str}, CSR={csr_value}, Golden={golden_value} [MISMATCH]"
                )
            else:
                dut._log.info(
                    f"  Cycle {cycle + 1}: entropy_i={entropy_str}, CSR={csr_value}, Golden={golden_value} [OK]"
                )

    # Final check
    rep_count_csr = await reg_rd(apb, "REPETITION_TEST_COUNT")
    final_csr = rep_count_csr & 0xFF
    final_golden = golden.get_expected_count()

    # Get final entropy value
    try:
        final_entropy = int(entropy_signal.value)
        final_entropy_str = f"0x{final_entropy:08X}"
    except:
        final_entropy_str = "N/A"

    dut._log.info("\n[GOLDEN MODEL] Final values:")
    dut._log.info(f"  Last entropy_i: {final_entropy_str}")
    dut._log.info(f"  CSR REPETITION_TEST_COUNT: {final_csr}")
    dut._log.info(f"  Golden expected value: {final_golden}")
    dut._log.info(f"  Samples processed: {golden.sample_count}")
    dut._log.info(f"  Mismatches: {mismatch_count}")

    return (final_csr, final_golden, mismatch_count)
