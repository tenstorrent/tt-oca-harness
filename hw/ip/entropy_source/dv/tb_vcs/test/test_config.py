# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
Test configuration parameters for entropy testbench.
Centralizes all configuration settings and provides predefined clock configurations.

Usage Examples
==============

1. Using DEFAULT_CONFIG (standard configuration):

    from test.test_config import DEFAULT_CONFIG

    @cocotb.test()
    async def my_test(dut):
        cfg = DEFAULT_CONFIG
        apb, mon = await init(dut, config=cfg)
        # Test uses: APB 100MHz, RO 142.9MHz, RO model injection ENABLED

2. Using predefined clock configuration:

    from test.test_config import get_config_with_clocks, CLOCK_CONFIG_FAST_RO

    @cocotb.test()
    async def my_test(dut):
        cfg = get_config_with_clocks(CLOCK_CONFIG_FAST_RO)
        apb, mon = await init(dut, config=cfg)
        # Test uses: APB 100MHz, RO 500MHz (fast RO sampling)

3. Disabling RO model injection (use real ring oscillators):

    from test.test_config import get_custom_config, ROConfig

    @cocotb.test()
    async def my_test(dut):
        cfg = get_custom_config(ro=ROConfig(inject_model=0))
        apb, mon = await init(dut, config=cfg)
        # Test uses DUT's real ring oscillators instead of behavioral model

4. Custom configuration with multiple overrides:

    from test.test_config import get_config_with_clocks, CLOCK_CONFIG_CDC_STRESS_FAST_RO
    from test.test_config import ROConfig, DecorrelatorConfig

    @cocotb.test()
    async def my_test(dut):
        cfg = get_config_with_clocks(
            CLOCK_CONFIG_CDC_STRESS_FAST_RO,
            ro=ROConfig(inject_model=1, num_lanes=12),
            decorrelator=DecorrelatorConfig(mode=2, sample_period=8)  # BYPASS mode
        )
        apb, mon = await init(dut, config=cfg)

5. Printing configuration summary:

    from test.test_config import print_config_summary, DEFAULT_CONFIG

    @cocotb.test()
    async def my_test(dut):
        cfg = DEFAULT_CONFIG
        print_config_summary(cfg)  # Shows all configuration details
        apb, mon = await init(dut, config=cfg)

Available Clock Configurations
===============================
- CLOCK_CONFIG_DEFAULT:              APB 100MHz, RO 142.9MHz (balanced, default)
- CLOCK_CONFIG_FAST_RO:              APB 100MHz, RO 500MHz (max throughput)
- CLOCK_CONFIG_CDC_STRESS_FAST_RO:   APB 50MHz, RO 500MHz (CDC stress, 10x ratio)
- CLOCK_CONFIG_CDC_STRESS_SLOW_RO:   APB 200MHz, RO 143MHz (fast APB, slow entropy)
- CLOCK_CONFIG_SYNCHRONOUS:          APB 143MHz, RO 143MHz (1:1 for debug)
- CLOCK_CONFIG_INVERTED:             APB 200MHz, RO 400MHz (inverted ratio)
- CLOCK_CONFIG_SLOW:                 APB 50MHz, RO 143MHz (waveform debug)

RO Model Injection Control
===========================
inject_model parameter:
  0: Use DUT's real ring oscillators (no model injection)
  1: Inject behavioral RO model into DUT decorrelators (default)

The RO model allows controlled bias, correlation, and stuck-at fault injection
for comprehensive testing. Real ROs are useful for validating actual hardware behavior.

RO Model Auto-Randomization
============================
auto_randomize parameter:
  False: Manual control - call ro_model_randomize_all() explicitly (default)
  True: Automatic - init() automatically randomizes all RO lanes

Example - Manual randomization (default):
    cfg = DEFAULT_CONFIG  # auto_randomize=False
    apb, mon = await init(dut, config=cfg)
    await ro_model_randomize_all(dut, config=cfg)  # Explicit call

Example - Automatic randomization:
    cfg = get_custom_config(ro=ROConfig(auto_randomize=True))
    apb, mon = await init(dut, config=cfg)
    # RO lanes automatically randomized by init() - no explicit call needed
"""

from dataclasses import dataclass


@dataclass
class ClockConfig:
    """Clock period configurations in nanoseconds

    Two independent clock domains:
    - APB/System clock: Drives APB bus, CSRs, health monitors, FIFO
    - RO sampling clock: Drives RO models, samplers, decorrelators, entropy compressor

    Per spec: RO sampling clock should be 130-560 MHz (1.8-7.7 ns period)
    """

    apb_period_ns: int = 10  # 100 MHz APB clock
    rosc_period_ns: int = 7  # ~142.9 MHz RO sample clock

    @property
    def apb_freq_mhz(self) -> float:
        """APB clock frequency in MHz"""
        return 1000.0 / self.apb_period_ns

    @property
    def rosc_freq_mhz(self) -> float:
        """RO sampling clock frequency in MHz"""
        return 1000.0 / self.rosc_period_ns

    @property
    def freq_ratio(self) -> float:
        """Ratio of RO sampling clock to APB clock (rosc/apb)"""
        return self.apb_period_ns / self.rosc_period_ns

    def validate(self) -> tuple[bool, str]:
        """Validate clock configuration against spec requirements
        Returns: (is_valid, error_message)
        """
        # Check RO sampling clock is within spec range (130-560 MHz)
        if self.rosc_period_ns < 1.8:
            return False, f"RO sampling clock too fast: {self.rosc_freq_mhz:.1f} MHz (max 560 MHz)"
        if self.rosc_period_ns > 7.7:
            return False, f"RO sampling clock too slow: {self.rosc_freq_mhz:.1f} MHz (min 130 MHz)"

        # Check APB clock is reasonable (typically 50-200 MHz for this design)
        if self.apb_period_ns < 5:
            return False, f"APB clock too fast: {self.apb_freq_mhz:.1f} MHz (max ~200 MHz typical)"
        if self.apb_period_ns > 20:
            return False, f"APB clock too slow: {self.apb_freq_mhz:.1f} MHz (min ~50 MHz typical)"

        return True, ""


@dataclass
class ResetConfig:
    """Reset timing configurations"""

    reset_cycles: int = 4  # Number of cycles to hold reset


@dataclass
class APBConfig:
    """APB bus configuration"""

    addr_width: int = 9  # APB address width (entropy_source_reg uses 9-bit for 0x12C)
    data_width: int = 32  # APB data width
    addr_min: int = 0x00  # Min valid address
    # Per entropy_source.rdl the highest implemented offset is 0x12C
    # (GENERATOR_11_SAMPLE_CLK_CONFIG).
    addr_max: int = 0x12C  # Max valid address (inclusive)
    addr_step: int = 4  # Address alignment (word-aligned)
    # No page register in entropy_source_reg; use exclusive upper bound helper at addr_max+step
    page_reg_addr: int = 0x130


@dataclass
class ROConfig:
    """Ring Oscillator model configuration"""

    num_lanes: int = 12  # Number of RO lanes
    prob_scale: int = 1_000_000  # Probability scaling factor

    # Model injection control
    # 0: No injection - use DUT's real ring oscillators
    # 1: Inject model - force RO model outputs into DUT decorrelators (default)
    # 2: Inject 32-bit data directly to health tests (bypass decorr+compressor)
    inject_model: int = 1  # Enable RO model injection by default

    # Health test direct injection mode (when inject_model=2)
    # Generates 32-bit samples directly at health test input
    # Bypasses decorrelator + compressor for controlled testing
    # Supports bias/correlation on 32-bit word generation
    health_test_inject_enable: bool = False  # False = inject at decorrelator (default)
    # True = inject at health test input

    # Automatic randomization control
    # True: init() automatically calls ro_model_randomize_all()
    # False: Manual control - call ro_model_randomize_all() explicitly (default)
    auto_randomize: bool = False

    # Randomization ranges for bias/correlation
    bias_min: float = 0.4
    bias_max: float = 0.6
    corr_min: float = 0.4
    corr_max: float = 0.9

    # Stuck-at fault injection (for lanes 0 and 1)
    stuck_probability: float = 0.1  # 10% chance stuck-at-1
    stuck_zero_probability: float = 0.1  # next 10% stuck-at-0

    # Sampling
    sample_timeout: int = 8  # Max retries for valid sample

    @property
    def inject_enabled(self) -> bool:
        """Check if RO model injection is enabled"""
        return self.inject_model == 1


@dataclass
class DecorrelatorConfig:
    """Decorrelator configuration

    The decorrelator is a reference model in the testbench for generating
    golden entropy data. It supports 5 operating modes with different
    decorrelation algorithms.

    Recommended sample_period values (coprime with depth for proper decorrelation):
        Mode 0 (DECOR_29): 64 cycles - 29-deep XOR decorrelator (spec default)
        Mode 1 (DECOR_7):  16 cycles - 7-deep XOR decorrelator
        Mode 2 (BYPASS):    8 cycles - No decorrelation, raw bits
        Mode 3 (LFSR_29): 64 cycles - 29-bit Fibonacci LFSR
        Mode 4 (LFSR_7):  16 cycles - 7-bit Fibonacci LFSR

    sample_period is informational: the reference model in tb_entropy_top.sv samples on
    the DUT clock divider (DECORRELATOR_CTRL.SAMPLE_CLK_DIV), and no testbench module
    reads decor_cfg.sample_period.

    DUT Configuration (applies to RTL):
    - bypass_dut: Enable bypass mode in DUT
    - sample_clk_div: Clock divider value (actual division = sample_clk_div + 1)
                     Example: 63 → divide by 64
    - bypass_mask: Per-lane bypass control (0x000=none, 0xFFF=all)
    """

    depth: int = 29  # Default decorrelator depth
    sample_period: int = 64  # Output sample period in cycles
    mode: int = 0  # 0=DECOR_29, 1=DECOR_7, 2=BYPASS, 3=LFSR_29, 4=LFSR_7

    # DUT-specific configuration (RTL decorrelator)
    bypass_dut: bool = False  # True: bypass mode, False: decorrelation (default/desired)
    sample_clk_div: int = 63  # Clock divider value (63 → divide by 64)
    bypass_mask: int = 0x000  # Per-lane bypass (0x000 = no bypass, 0xFFF = all bypassed)

    # Shift direction (applies to reference model)
    shift_dir: int = 1  # 0: shift right (in[28]→out[7:0]), 1: shift left (in[0]→out[28:21])

    # Decorrelator output checker configuration
    checker_enable: bool = True  # Enable decorrelator output checker (DUT vs ref model)
    checker_verbose: bool = False  # False: only show mismatches, True: show all matches

    @property
    def mode_name(self) -> str:
        """Get human-readable mode name"""
        names = {0: "DECOR_29", 1: "DECOR_7", 2: "BYPASS", 3: "LFSR_29", 4: "LFSR_7"}
        return names.get(self.mode, f"UNKNOWN({self.mode})")

    @property
    def recommended_sample_period(self) -> int:
        """Get recommended sample period for current mode"""
        recommendations = {
            0: 64,  # DECOR_29
            1: 16,  # DECOR_7
            2: 8,  # BYPASS
            3: 64,  # LFSR_29
            4: 16,  # LFSR_7
        }
        return recommendations.get(self.mode, 64)

    @property
    def dut_mode_name(self) -> str:
        """Get DUT operating mode name"""
        return "BYPASS" if self.bypass_dut else "DECORRELATION"

    @property
    def actual_division(self) -> int:
        """Get actual clock division ratio"""
        return self.sample_clk_div + 1


@dataclass
class CompressorConfig:
    """Entropy Compressor (BIW Extractor) configuration

    The compressor is a reference model in the testbench for compressing
    12 decorrelator byte streams into a single 32-bit word using BIW
    (Barak-Impagliazzo-Wigderson) extraction.

    Operating Modes:
    - Normal (bypass=False): BIW extraction using GF(2^8) multiply-add
      Output = 4 groups × y[i] = (a[i] * b[i]) + c[i] in GF(2^8)
    - Bypass (bypass=True): Simple concatenation (debug mode)
      Output = {bytes[0], bytes[1], bytes[2], bytes[3]}

    Lane Masking:
    - lane_mask=0xFFF: All 12 lanes active (default)
    - lane_mask=0x001: Only lane 0 active (single lane test)
    - lane_mask=0xAAA: Even lanes only (lanes 0,2,4,6,8,10)

    Grouping (Strided, Fixed):
    - Group 0: lanes [0, 4, 8]  → output[31:24]
    - Group 1: lanes [1, 5, 9]  → output[23:16]
    - Group 2: lanes [2, 6, 10] → output[15:8]
    - Group 3: lanes [3, 7, 11] → output[7:0]
    """

    enable: bool = True  # Enable compressor
    bypass: bool = False  # False: BIW mode, True: bypass (debug)
    lane_mask: int = 0xFFF  # Per-lane enable mask (12 bits)
    checker_enable: bool = True  # Enable output checker (compares DUT vs ref model)
    checker_verbose: bool = False  # Show MATCH messages (False=errors only)

    def is_lane_enabled(self, lane_num: int) -> bool:
        """Check if specific lane is enabled

        Args:
            lane_num: Lane number (0-11)

        Returns:
            True if lane is enabled in mask
        """
        if lane_num < 0 or lane_num >= 12:
            return False
        return bool(self.lane_mask & (1 << lane_num))

    def count_active_lanes(self) -> int:
        """Count number of active lanes

        Returns:
            Number of lanes enabled in mask (0-12)
        """
        return bin(self.lane_mask).count("1")

    def get_group_lanes(self, group_num: int) -> tuple[int, int, int]:
        """Get lane indices for a BIW extraction group (strided grouping)

        Args:
            group_num: Group number (0-3)

        Returns:
            Tuple of (lane_a, lane_b, lane_c) for the group

        Examples:
            >>> cfg.get_group_lanes(0)
            (0, 4, 8)
            >>> cfg.get_group_lanes(2)
            (2, 6, 10)
        """
        if group_num == 0:
            return (0, 4, 8)
        elif group_num == 1:
            return (1, 5, 9)
        elif group_num == 2:
            return (2, 6, 10)
        elif group_num == 3:
            return (3, 7, 11)
        else:
            return (0, 0, 0)

    @property
    def mode_name(self) -> str:
        """Get human-readable mode name"""
        return "BYPASS" if self.bypass else "BIW_EXTRACTION"


@dataclass
class TestConfig:
    """Overall test configuration"""

    # Sub-configurations
    clock: ClockConfig = None
    reset: ResetConfig = None
    apb: APBConfig = None
    ro: ROConfig = None
    decorrelator: DecorrelatorConfig = None
    compressor: CompressorConfig = None

    # DUT Control Register Settings (CTRL register 0x004)
    bypass_compressor_dut: bool = False  # CTRL.BYPASS_ENTROPY_COMPRESSOR[8]
    # False: Compressor enabled (1 FIFO word/sample)
    # True: Compressor bypassed (3 FIFO words/sample, raw 12-byte data)
    downsample_rate: int = 0  # CTRL.DOWNSAMPLE_RATE[25:16]
    # 0: No downsampling (default)
    # N: Drop first N samples, then keep 1 out of (N+1)

    # Test-specific parameters
    apb_random_iterations: int = 10  # Number of random APB transactions
    decorrelator_samples: int = 3  # Number of decorrelator samples to collect
    fifo_verification_enable: bool = True  # Enable FIFO readout verification
    fifo_error_monitor_enable: bool = True  # Enable background FIFO overflow/underflow monitor
    clk_divider_check_enable: bool = True  # Enable clock divider synchronization checker
    # Disable for tests that change divider on-the-fly (health tests)
    # Cycles to wait if decorrelator not present
    fallback_wait_cycles: int = 256

    def __post_init__(self):
        """Initialize sub-configs if not provided"""
        if self.clock is None:
            self.clock = ClockConfig()
        if self.reset is None:
            self.reset = ResetConfig()
        if self.apb is None:
            self.apb = APBConfig()
        if self.ro is None:
            self.ro = ROConfig()
        if self.decorrelator is None:
            self.decorrelator = DecorrelatorConfig()
        if self.compressor is None:
            self.compressor = CompressorConfig()


# Default configuration instance
DEFAULT_CONFIG = TestConfig()


# ============================================================================
# Predefined Clock Configurations for Different Test Scenarios
# ============================================================================

# Default: Balanced configuration with good CDC margin (1.43x ratio)
# APB: 100 MHz, RO: 142.9 MHz
CLOCK_CONFIG_DEFAULT = ClockConfig(apb_period_ns=10, rosc_period_ns=7)

# Fast RO: Maximum speed RO sampling with standard APB
# APB: 100 MHz, RO: 500 MHz (2 ns period)
# Use for: Testing maximum entropy throughput and fast decorrelator operation
CLOCK_CONFIG_FAST_RO = ClockConfig(apb_period_ns=10, rosc_period_ns=2)

# CDC Stress Test 1: Very fast RO with slow APB (high freq ratio ~10x)
# APB: 50 MHz, RO: 500 MHz
# Use for: Stressing CDC FIFOs, testing back-pressure, validating synchronizers
CLOCK_CONFIG_CDC_STRESS_FAST_RO = ClockConfig(apb_period_ns=20, rosc_period_ns=2)

# CDC Stress Test 2: Fast APB with slow RO (low freq ratio ~0.7x)
# APB: 200 MHz, RO: 143 MHz
# Use for: Testing APB reads with slow entropy generation, empty FIFO handling
CLOCK_CONFIG_CDC_STRESS_SLOW_RO = ClockConfig(apb_period_ns=5, rosc_period_ns=7)

# Synchronous: Nearly 1:1 ratio for simplified debug
# APB: 143 MHz, RO: 143 MHz
# Use for: Initial debug, waveform analysis, understanding data flow
CLOCK_CONFIG_SYNCHRONOUS = ClockConfig(apb_period_ns=7, rosc_period_ns=7)

# Inverted: APB faster than RO (ratio ~0.5x)
# APB: 200 MHz, RO: 400 MHz
# Use for: Testing entropy consumption faster than production edge cases
CLOCK_CONFIG_INVERTED = ClockConfig(apb_period_ns=5, rosc_period_ns=2.5)

# Slow: Both clocks at lower frequencies for detailed waveform analysis
# APB: 50 MHz, RO: 143 MHz
# Use for: Debugging, manual waveform inspection
CLOCK_CONFIG_SLOW = ClockConfig(apb_period_ns=20, rosc_period_ns=7)


def get_config() -> TestConfig:
    """Get the default test configuration"""
    return DEFAULT_CONFIG


def get_custom_config(**kwargs) -> TestConfig:
    """Create a custom configuration with overrides"""
    return TestConfig(**kwargs)


def get_config_with_clocks(clock_config: ClockConfig, **kwargs) -> TestConfig:
    """Create a test configuration with specific clock settings

    Args:
        clock_config: ClockConfig instance (e.g., CLOCK_CONFIG_FAST_RO)
        **kwargs: Additional TestConfig overrides

    Returns:
        TestConfig with specified clock configuration

    Example:
        cfg = get_config_with_clocks(CLOCK_CONFIG_CDC_STRESS_FAST_RO)
    """
    return TestConfig(clock=clock_config, **kwargs)


def print_clock_info(config: ClockConfig) -> None:
    """Print clock configuration summary

    Args:
        config: ClockConfig to display

    Example:
        print_clock_info(CLOCK_CONFIG_DEFAULT)
    """
    print("=" * 60)
    print("Clock Configuration Summary")
    print("=" * 60)
    print(f"APB Clock:        {config.apb_period_ns} ns ({config.apb_freq_mhz:.1f} MHz)")
    print(f"RO Sample Clock:  {config.rosc_period_ns} ns ({config.rosc_freq_mhz:.1f} MHz)")
    print(f"Frequency Ratio:  {config.freq_ratio:.2f}x (rosc/apb)")
    print("-" * 60)

    is_valid, error_msg = config.validate()
    if is_valid:
        print("Status: VALID ✓")
    else:
        print("Status: INVALID ✗")
        print(f"Error: {error_msg}")
    print("=" * 60)


def print_config_summary(config: TestConfig) -> None:
    """Print comprehensive test configuration summary

    Args:
        config: TestConfig to display

    Example:
        print_config_summary(DEFAULT_CONFIG)
    """
    print("=" * 70)
    print("Test Configuration Summary")
    print("=" * 70)
    print()

    # Clock Configuration
    print("Clock Configuration:")
    print(
        f"  APB Clock:        {config.clock.apb_period_ns} ns ({config.clock.apb_freq_mhz:.1f} MHz)"
    )
    print(
        f"  RO Sample Clock:  {config.clock.rosc_period_ns} ns ({config.clock.rosc_freq_mhz:.1f} MHz)"
    )
    print(f"  Frequency Ratio:  {config.clock.freq_ratio:.2f}x (rosc/apb)")

    is_valid, error_msg = config.clock.validate()
    if not is_valid:
        print(f"  WARNING: {error_msg}")
    print()

    # RO Model Configuration
    print("RO Model Configuration:")
    print(f"  Number of Lanes:     {config.ro.num_lanes}")
    print(f"  Model Injection:     {'ENABLED' if config.ro.inject_enabled else 'DISABLED'}")
    print("                       (0=use real ROs, 1=use model)")
    print(f"  Auto-Randomize:      {'ENABLED' if config.ro.auto_randomize else 'DISABLED'}")
    print("                       (True=init() randomizes, False=manual)")
    print(f"  Bias Range:          [{config.ro.bias_min:.2f}, {config.ro.bias_max:.2f}]")
    print(f"  Correlation Range:   [{config.ro.corr_min:.2f}, {config.ro.corr_max:.2f}]")
    print(f"  Stuck-at-1 Prob:     {config.ro.stuck_probability:.1%}")
    print(f"  Stuck-at-0 Prob:     {config.ro.stuck_zero_probability:.1%}")
    print()

    # Decorrelator Configuration
    print("Decorrelator Configuration:")
    print(f"  Reference Model Mode: {config.decorrelator.mode} ({config.decorrelator.mode_name})")
    print(f"  Depth:                {config.decorrelator.depth}")
    print(f"  Sample Period:        {config.decorrelator.sample_period} cycles")
    print(f"  Recommended Period:   {config.decorrelator.recommended_sample_period} cycles")
    if config.decorrelator.sample_period != config.decorrelator.recommended_sample_period:
        print("  NOTE: Using non-recommended sample period!")
    print()
    print(f"  DUT Mode:             {config.decorrelator.dut_mode_name}")
    print(f"  DUT Bypass:           {config.decorrelator.bypass_dut}")
    print(f"  DUT Bypass Mask:      0x{config.decorrelator.bypass_mask:03X}")
    print(
        f"  DUT Clock Divider:    {config.decorrelator.sample_clk_div} (div-{config.decorrelator.actual_division})"
    )
    print()
    print(f"  Checker Enabled:      {config.decorrelator.checker_enable}")
    print(f"  Checker Verbose:      {config.decorrelator.checker_verbose}")
    print()

    # Compressor Configuration
    print("Compressor Configuration:")
    print(f"  Operating Mode:       {config.compressor.mode_name}")
    print(f"  Enabled:              {config.compressor.enable}")
    print(f"  Model Bypass:         {config.compressor.bypass} (BIW extraction vs concatenation)")
    print(f"  Lane Mask:            0x{config.compressor.lane_mask:03X}")
    print(f"  Active Lanes:         {config.compressor.count_active_lanes()}/12")
    print(f"  Checker Enabled:      {config.compressor.checker_enable}")
    print(f"  Checker Verbose:      {config.compressor.checker_verbose}")
    print()

    # DUT Control Settings
    print("DUT Control Settings (CTRL Register):")
    print(f"  Bypass Compressor:    {config.bypass_compressor_dut}")
    print("                        (0=compressor enabled, 1=bypass to FIFO)")
    print(f"  Downsample Rate:      {config.downsample_rate}")
    print(
        f"                        (0=no downsample, N=drop N then 1-in-{config.downsample_rate + 1})"
    )
    print()

    # Test Parameters
    print("Test Parameters:")
    print(f"  APB Random Iterations:    {config.apb_random_iterations}")
    print(f"  Decorrelator Samples:     {config.decorrelator_samples}")
    print(f"  Fallback Wait Cycles:     {config.fallback_wait_cycles}")
    print()

    print("=" * 70)
