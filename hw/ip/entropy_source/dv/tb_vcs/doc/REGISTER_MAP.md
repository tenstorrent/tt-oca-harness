# Entropy Source Register Map

**Source**: `regs/entropy_source.rdl`
**Last Updated**: 2025-12-15
**Status**: Complete - All registers implemented and tested (addresses corrected to match RDL)

---

## Complete Register Map

| Address | Register                    | Bit Field             | Type     | Default    | Description                                                             |
|---------|-----------------------------|-----------------------|----------|------------|-------------------------------------------------------------------------|
|         | **CORE CONTROL AND STATUS** |                       |          |            |                                                                         |
| 0x000   | COMPONENT_ID                | [15:0] NAME           | RO       | 0x0001     | Component identifier                                                    |
| 0x000   | COMPONENT_ID                | [27:24] MINOR_VERSION | RO       | 0x0        | Minor version                                                           |
| 0x000   | COMPONENT_ID                | [31:28] MAJOR_VERSION | RO       | 0x1        | Major version                                                           |
| 0x004   | CTRL                        | [0] RESET             | RW       | 0          | Software reset (active high)                                            |
| 0x004   | CTRL                        | [4] AUTOTUNE_ENABLE   | RW       | 0          | Auto-detune failed ROs                                                  |
| 0x004   | CTRL                        | [8] BYPASS_COMP       | RW       | 0          | (NEW) Bypass compressor, push raw 12-byte RO data to FIFO (3x32-bit)   |
| 0x004   | CTRL                        | [25:16] DOWNSAMPLE    | RW       | 0          | (NEW) Downsample decorrelator output (default changed 63->0)           |
| 0x008   | STATUS                      | [0] RSVD              | RO       | 0          | Reserved                                                                |
| 0x00C   | DEBUG_CTRL                  | [7:0] SELECT_SIGNAL   | RW       | 0x00       | (NEW) Debug signal selection (expanded from [5:0])                      |
| 0x00C   | DEBUG_CTRL                  | [11:8] SELECT_FREQ    | RW       | 0x0        | Debug frequency divider                                                 |
|         | **INTERRUPT REGISTERS**     |                       |          |            |                                                                         |
| 0x010   | INTR_STATUS                 | [0] HEALTH_TEST_FAIL  | RW, W1C  | 0          | Health test failure (any test)                                          |
| 0x010   | INTR_STATUS                 | [4] FIFO_ERROR        | RW, W1C  | 0          | FIFO security error                                                     |
| 0x010   | INTR_STATUS                 | [8] FIFO_OVERFLOW     | RW, W1C  | 0          | FIFO overflow error                                                     |
| 0x010   | INTR_STATUS                 | [12] FIFO_UNDERFLOW   | RW, W1C  | 0          | FIFO underflow error                                                    |
| 0x014   | INTR_ENABLE                 | [0] HEALTH_TEST_FAIL  | RW       | 0          | Enable health test interrupt                                            |
| 0x014   | INTR_ENABLE                 | [4] FIFO_ERROR        | RW       | 0          | Enable FIFO error interrupt                                             |
| 0x014   | INTR_ENABLE                 | [8] FIFO_OVERFLOW     | RW       | 0          | Enable overflow interrupt                                               |
| 0x014   | INTR_ENABLE                 | [12] FIFO_UNDERFLOW   | RW       | 0          | Enable underflow interrupt                                              |
| 0x018   | INTR_TEST                   | [0] HEALTH_TEST_FAIL  | WO       | 0          | SW injection - health test                                              |
| 0x018   | INTR_TEST                   | [4] FIFO_ERROR        | WO       | 0          | SW injection - FIFO error                                               |
| 0x018   | INTR_TEST                   | [8] FIFO_OVERFLOW     | WO       | 0          | SW injection - overflow                                                 |
| 0x018   | INTR_TEST                   | [12] FIFO_UNDERFLOW   | WO       | 0          | SW injection - underflow                                                |
|         | **FIFO CONTROL AND STATUS** |                       |          |            |                                                                         |
| 0x020   | FIFO_CTRL                   | [0] ENABLE            | RW       | 1          | FIFO enable (1=enabled, 0=frozen)                                       |
| 0x024   | FIFO_STATUS                 | [6:0] LEVEL           | RO       | 0x00       | FIFO fill level (0-64)                                                  |
| 0x024   | FIFO_STATUS                 | [12:8] WPTR           | RO       | 0x00       | Write pointer (0-63)                                                    |
| 0x024   | FIFO_STATUS                 | [20:16] RPTR          | RO       | 0x00       | Read pointer (0-63)                                                     |
| 0x028   | FIFO_RDATA                  | [31:0] RDATA          | RO       | 0x00000000 | FIFO read data (auto-pop)                                               |
|         | **HEALTH TEST CONFIG**      |                       |          |            |                                                                         |
| 0x030   | HEALTH_TEST_CTRL            | [0] ENABLE_REP        | RW       | 1          | Enable repetition test                                                  |
| 0x030   | HEALTH_TEST_CTRL            | [1] ENABLE_APT        | RW       | 1          | Enable APT test                                                         |
| 0x030   | HEALTH_TEST_CTRL            | [2] ENABLE_MARKOV     | RW       | 1          | Enable Markov test                                                      |
| 0x030   | HEALTH_TEST_CTRL            | [15:8] REP_LIMIT      | RW       | 15         | Repetition threshold                                                    |
| 0x030   | HEALTH_TEST_CTRL            | [18:16] SAMPLE_SIZE   | RW       | 1          | APT sample size (1/2/3/4)                                               |
| 0x030   | HEALTH_TEST_CTRL            | [29:20] PROP_LIMIT    | RW       | 600        | APT proportion threshold (deprecated - use APT_PROPORTION_* regs)       |
| 0x038   | MARKOV_TEST_PROB_THRESHOLDS | [7:0] PROB_01         | RW       | 100        | Threshold for 0->1 transitions                                          |
| 0x038   | MARKOV_TEST_PROB_THRESHOLDS | [15:8] PROB_10        | RW       | 100        | Threshold for 1->0 transitions                                          |
| 0x038   | MARKOV_TEST_PROB_THRESHOLDS | [23:16] PROB_00       | RW       | 100        | Threshold for 0->0 transitions                                          |
| 0x038   | MARKOV_TEST_PROB_THRESHOLDS | [31:24] PROB_11       | RW       | 100        | Threshold for 1->1 transitions                                          |
|         | **HEALTH TEST STATUS**      |                       |          |            |                                                                         |
| 0x040   | HEALTH_TEST_STATUS          | [0] REPETITION_FAIL   | RO       | 0          | Repetition test status                                                  |
| 0x040   | HEALTH_TEST_STATUS          | [3] APT_FAIL          | RO       | 0          | APT test status                                                         |
| 0x040   | HEALTH_TEST_STATUS          | [4] MARKOV_01_FAIL    | RO       | 0          | Markov 0->1 test status                                                 |
| 0x040   | HEALTH_TEST_STATUS          | [5] MARKOV_10_FAIL    | RO       | 0          | Markov 1->0 test status                                                 |
| 0x040   | HEALTH_TEST_STATUS          | [6] MARKOV_00_FAIL    | RO       | 0          | Markov 0->0 test status                                                 |
| 0x040   | HEALTH_TEST_STATUS          | [7] MARKOV_11_FAIL    | RO       | 0          | Markov 1->1 test status                                                 |
| 0x044   | REPETITION_TEST_COUNT       | [7:0] COUNT           | RO       | 0x00       | Current repetition count                                                |
| 0x050   | APT_PATTERN_COUNT_1BIT      | [9:0] PATTERN_COUNT   | RO       | 0x000      | 1-bit pattern count                                                     |
| 0x050   | APT_PATTERN_COUNT_1BIT      | [13:10] TARGET        | RO       | 0x0        | 1-bit target pattern                                                    |
| 0x050   | APT_PATTERN_COUNT_1BIT      | [29:20] SAMPLES       | RO       | 0x000      | 1-bit samples processed                                                 |
| 0x054   | APT_PATTERN_COUNT_2BIT      | [9:0] PATTERN_COUNT   | RO       | 0x000      | 2-bit pattern count                                                     |
| 0x054   | APT_PATTERN_COUNT_2BIT      | [13:10] TARGET        | RO       | 0x0        | 2-bit target pattern                                                    |
| 0x054   | APT_PATTERN_COUNT_2BIT      | [29:20] SAMPLES       | RO       | 0x000      | 2-bit samples processed                                                 |
| 0x058   | APT_PATTERN_COUNT_3BIT      | [9:0] PATTERN_COUNT   | RO       | 0x000      | 3-bit pattern count                                                     |
| 0x058   | APT_PATTERN_COUNT_3BIT      | [13:10] TARGET        | RO       | 0x0        | 3-bit target pattern                                                    |
| 0x058   | APT_PATTERN_COUNT_3BIT      | [29:20] SAMPLES       | RO       | 0x000      | 3-bit samples processed                                                 |
| 0x05C   | APT_PATTERN_COUNT_4BIT      | [9:0] PATTERN_COUNT   | RO       | 0x000      | 4-bit pattern count                                                     |
| 0x05C   | APT_PATTERN_COUNT_4BIT      | [13:10] TARGET        | RO       | 0x0        | 4-bit target pattern                                                    |
| 0x05C   | APT_PATTERN_COUNT_4BIT      | [29:20] SAMPLES       | RO       | 0x000      | 4-bit samples processed                                                 |
| 0x060   | APT_PROPORTION_1BIT         | [9:0] LIMIT           | RW       | 600        | APT proportion threshold for 1-bit samples                              |
| 0x064   | APT_PROPORTION_2BIT         | [9:0] LIMIT           | RW       | 600        | APT proportion threshold for 2-bit samples                              |
| 0x068   | APT_PROPORTION_3BIT         | [9:0] LIMIT           | RW       | 600        | APT proportion threshold for 3-bit samples                              |
| 0x06C   | APT_PROPORTION_4BIT         | [9:0] LIMIT           | RW       | 600        | APT proportion threshold for 4-bit samples                              |
| 0x080   | MARKOV_TEST_COUNTS_0        | [15:0] COUNT_01       | RO       | 0x0000     | Highest per-lane alternation count                                      |
| 0x080   | MARKOV_TEST_COUNTS_0        | [31:16] COUNT_10      | RO       | 0x0000     | Lowest per-lane alternation count                                       |
| 0x088   | MARKOV_TEST_PROBABILITIES   | [7:0] PROB_01         | RO       | 0x00       | Calculated 0->1 probability                                             |
| 0x088   | MARKOV_TEST_PROBABILITIES   | [15:8] PROB_10        | RO       | 0x00       | Calculated 1->0 probability                                             |
| 0x088   | MARKOV_TEST_PROBABILITIES   | [23:16] PROB_00       | RO       | 0x00       | Calculated 0->0 probability                                             |
| 0x088   | MARKOV_TEST_PROBABILITIES   | [31:24] PROB_11       | RO       | 0x00       | Calculated 1->1 probability                                             |
|         | **RING OSCILLATOR CONTROL** |                       |          |            |                                                                         |
| 0x090   | RING_OSC_ENABLE             | [11:0] ENABLE         | RW       | 0x000      | Enable 12 noise ROs                                                     |
| 0x090   | RING_OSC_ENABLE             | [23:12] SAMPLE_CLK    | RW       | 0x000      | Enable 12 sample clock ROs                                              |
| 0x094   | RING_OSC_TUNE               | [11:0] DETUNE         | RW       | 0x000      | Detune noise ROs                                                        |
| 0x094   | RING_OSC_TUNE               | [23:12] SAMPLE_DETUNE | RW       | 0x000      | Detune sample clock ROs                                                 |
| 0x098   | RING_OSC_CTRL               | [11:0] CLK_SELECT     | RW       | 0x000      | Sample clock source select                                              |
|         | **DECORRELATOR CONTROL**    |                       |          |            |                                                                         |
| 0x0A0   | DECORRELATOR_CTRL           | [11:0] BYPASS         | RW       | 0x000      | Per-generator bypass (0x000=decorr, 0xFFF=bypass)                       |
| 0x0A0   | DECORRELATOR_CTRL           | [31:12] SAMPLE_DIV    | RW       | 63         | (NEW) Sample clock divider (was [23:16], now 20-bit)                   |
| 0x0A4   | DECORRELATOR_MASK           | [7:0] BYTE_MASK       | RW       | 0xFF       | Entropy byte enable mask                                                |
|         | **STARTUP CONTROL**         |                       |          |            |                                                                         |
| 0x0B0   | STARTUP_CTRL                | [15:0] DELAY_CYCLES   | RW       | 0x0000     | Startup delay after power-on reset                                      |
|         | **PER-GEN HEALTH STATUS**   |                       |          |            |                                                                         |
| 0x0C0   | GENERATOR_0_HEALTH_STATUS   | [7:0] STATUS          | RO       | 0x00       | Generator 0 byte-stream health status                                   |
| 0x0C4   | GENERATOR_1_HEALTH_STATUS   | [7:0] STATUS          | RO       | 0x00       | Generator 1 byte-stream health status                                   |
| 0x0C8   | GENERATOR_2_HEALTH_STATUS   | [7:0] STATUS          | RO       | 0x00       | Generator 2 byte-stream health status                                   |
| 0x0CC   | GENERATOR_3_HEALTH_STATUS   | [7:0] STATUS          | RO       | 0x00       | Generator 3 byte-stream health status                                   |
| 0x0D0   | GENERATOR_4_HEALTH_STATUS   | [7:0] STATUS          | RO       | 0x00       | Generator 4 byte-stream health status                                   |
| 0x0D4   | GENERATOR_5_HEALTH_STATUS   | [7:0] STATUS          | RO       | 0x00       | Generator 5 byte-stream health status                                   |
| 0x0D8   | GENERATOR_6_HEALTH_STATUS   | [7:0] STATUS          | RO       | 0x00       | Generator 6 byte-stream health status                                   |
| 0x0DC   | GENERATOR_7_HEALTH_STATUS   | [7:0] STATUS          | RO       | 0x00       | Generator 7 byte-stream health status                                   |
| 0x0E0   | GENERATOR_8_HEALTH_STATUS   | [7:0] STATUS          | RO       | 0x00       | Generator 8 byte-stream health status                                   |
| 0x0E4   | GENERATOR_9_HEALTH_STATUS   | [7:0] STATUS          | RO       | 0x00       | Generator 9 byte-stream health status                                   |
| 0x0E8   | GENERATOR_10_HEALTH_STATUS  | [7:0] STATUS          | RO       | 0x00       | Generator 10 byte-stream health status                                  |
| 0x0EC   | GENERATOR_11_HEALTH_STATUS  | [7:0] STATUS          | RO       | 0x00       | Generator 11 byte-stream health status                                  |

---

## Register Summary

### By Type
- **Read-Write (RW)**: 16 registers (includes 4 APT_PROPORTION_* registers)
- **Read-Only (RO)**: 25 registers
- **Write-Only (WO)**: 1 register (INTR_TEST)
- **Total**: 42 functional registers

### By Address Range
| Range | Purpose | Count |
|-------|---------|-------|
| 0x000-0x018 | Core & Interrupts | 7 |
| 0x020-0x028 | FIFO | 3 |
| 0x030-0x06C | Health Tests | 14 (note: 0x034-0x037 reserved) |
| 0x090-0x098 | Ring Oscillators | 3 |
| 0x0A0-0x0A4 | Decorrelator | 2 |
| 0x0B0 | Startup Control | 1 |
| 0x0C0-0x0EC | Generator Status | 12 |

### Address Map Notes
- **0x034-0x037**: Reserved address space (gap between HEALTH_TEST_CTRL and MARKOV_TEST_PROB_THRESHOLDS)
- **0x048-0x04F**: Reserved address space (gap between REPETITION_TEST_COUNT and APT_PATTERN_COUNT registers)
- **0x070-0x07F**: Reserved address space (gap between APT_PROPORTION_4BIT and MARKOV_TEST_COUNTS_0)

---

## Test Coverage Summary

| Suite | Tests | Status | Coverage |
|-------|-------|--------|----------|
| Suite 0: Sanity | 3 | [DONE] | Register walk, basic functionality |
| Suite 1: Decorrelator | 15 | [DONE] | All decorrelator modes (pure + mixed + bypass) |
| Suite 2: FIFO | 16 | [DONE] | All FIFO operations + security features |
| Suite 3: Health Tests | 16 | [DONE] | All health test modes + interrupts |

**Total Tests**: 50 tests across 4 suites
**Total Registers Tested**: 42/42 (100%)
**Total Bits Tested**: 477 bits (includes 4x10-bit APT_PROPORTION registers)

---

## Key Implementation Notes

### Decorrelator Configuration (NEW Changes)
**DECORRELATOR_CTRL Register (0x0A0)**:
- **SAMPLE_CLK_DIV field**: Moved from [23:16] to [31:12] (commit 7883562f)
- **Field width**: Changed from 8-bit to 20-bit
- **Default value**: Still 63 (division by 64)
- **Range**: 8-255 for div-8 to div-256

**Common configurations**:
- Full decorrelation: BYPASS=0x000, DIV=63 (div-64)
- Full bypass: BYPASS=0xFFF, DIV=7 (div-8)
- Fast sampling: BYPASS=0x000, DIV=7 (div-8)
- Slow sampling: BYPASS=0x000, DIV=255 (div-256)

### Downsampling Configuration (NEW Default)
**CTRL.DOWNSAMPLE_RATE field (0x004[25:16])**:
- **Default changed**: From 63 to 0 (commit 7883562f)
- **Behavior**: Rate=0 means NO downsampling (capture all samples)
- **Applied after**: DECORRELATOR_CTRL.SAMPLE_CLK_DIV

### Compressor Bypass Mode (NEW Feature)
**CTRL.BYPASS_ENTROPY_COMPRESSOR field (0x004[8])**:
- **Added**: Commit b7bed4f0
- **Default**: 0 (compressor enabled)
- **When BYPASS=1**: Pushes raw 12-byte RO data directly to FIFO without compression
- **FIFO Impact**: Each sample generates **3 consecutive 32-bit FIFO entries** (12 bytes total)
- **Timing**: Uses FSM to push 3 words over 3 consecutive cycles
- **Use Case**: Debug mode to observe raw RO outputs before compression

**Normal Mode (BYPASS=0)**:
- Compressor enabled: 12 bytes -> 4 bytes (32-bit compressed entropy)
- FIFO push: 1 word per sample

**Bypass Mode (BYPASS=1)**:
- Compressor bypassed: 12 bytes pushed as-is
- FIFO push: 3 words per sample (bytes [3:0], [7:4], [11:8])

### Debug Monitor Expansion (NEW)
**DEBUG_CTRL.SELECT_SIGNAL field (0x00C[7:0])**:
- **Expanded**: From [5:0] to [7:0] (commit b7bed4f0)
- **Signal count**: Increased from 64 to 256 signals
- **New signals**: Includes raw uncompressed entropy_stream_uncompressed[11:0][7:0]

### Interrupt System
All four interrupts use standard pattern:
1. **INTR_STATUS**: Write-1-Clear status latches
2. **INTR_ENABLE**: Enable/disable gating
3. **INTR_TEST**: Software injection for testing
4. **Output**: irq_o = |(INTR_STATUS & INTR_ENABLE)

### FIFO Security Features
Implemented in entropy_fifo.sv:
1. **Parity Protection**: 4-bit odd parity per 32-bit word (one per byte)
2. **Differential Pointers**: Normal + inverted storage for wptr/rptr
3. **Security Alert**: Combined parity_error | pointer_error -> FIFO_ERROR interrupt

[WARNING] Individual error signals not exposed to APB - requires backdoor access for testing

### Health Test Architecture
- **HEALTH_TEST_STATUS (0x038)**: Tests 32-bit compressed stream entering FIFO
- **GENERATOR_*_HEALTH_STATUS (0xC0-0xEC)**: Per-generator 8-bit byte-stream testing
- **Single interrupt**: HEALTH_TEST_FAILED triggers for any test failure
- **Status identification**: Read HEALTH_TEST_STATUS[7:0] to identify which test(s) failed

---

**Documentation References**:
- Complete test specifications: `TEST_PLAN.txt`
