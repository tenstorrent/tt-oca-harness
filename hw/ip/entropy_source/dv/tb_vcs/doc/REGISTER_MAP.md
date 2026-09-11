# Entropy Source Register Map

**Source**: `regs/entropy_source.rdl`
**Scope**: Hand-authored overview; `regs/entropy_source.rdl` is authoritative

---

## Complete Register Map

| Address | Register                    | Bit Field             | Type     | Default    | Description                                                             |
|---------|-----------------------------|-----------------------|----------|------------|-------------------------------------------------------------------------|
|         | **CORE CONTROL AND STATUS** |                       |          |            |                                                                         |
| 0x000   | COMPONENT_ID                | [15:0] NAME           | RO       | 0x0001     | Component identifier                                                    |
| 0x000   | COMPONENT_ID                | [27:24] MINOR_VERSION | RO       | 0x0        | Minor version                                                           |
| 0x000   | COMPONENT_ID                | [31:28] MAJOR_VERSION | RO       | 0x1        | Major version                                                           |
| 0x004   | CTRL                        | [0] RSVD0             | RAZ/WI   | 0          | Reserved                                                                |
| 0x004   | CTRL                        | [1] MODULE_ENABLE     | RW       | 1          | Enable startup health testing and entropy output                        |
| 0x004   | CTRL                        | [4] AUTOTUNE_ENABLE   | RW       | 0          | Auto-detune failed ROs                                                  |
| 0x004   | CTRL                        | [8] BYPASS_COMP       | RW       | 0          | Bypass BIW and write generator bytes as three FIFO words                |
| 0x004   | CTRL                        | [25:16] DOWNSAMPLE    | RW       | 0          | Select every (N+1)th bypassed decorrelator output                       |
| 0x004   | CTRL                        | [28] SHA256_ENABLE    | RW       | 1          | Enable SHA-256 conditioning                                             |
| 0x00C   | DEBUG_CTRL                  | [7:0] SELECT_SIGNAL   | RW       | 0x00       | Debug signal selection                                                  |
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
| 0x030   | HEALTH_TEST_CTRL            | [15:8] REPETITION_LIMIT | RW     | 25         | Repetition threshold                                                    |
| 0x034   | HEALTH_TEST_WINDOW_SIZE     | [15:0] SIZE           | RW       | 2048       | APT and Markov window size                                              |
| 0x038   | MARKOV_TEST_PROB_THRESHOLDS | [15:0] PROB_01_THRESHOLD | RW    | 1200       | Markov high-count threshold                                             |
| 0x038   | MARKOV_TEST_PROB_THRESHOLDS | [31:16] PROB_10_THRESHOLD | RW   | 100        | Markov low-count threshold                                              |
|         | **HEALTH TEST STATUS**      |                       |          |            |                                                                         |
| 0x040   | HEALTH_TEST_STATUS          | [0] REPETITION_FAIL   | RO       | 0          | Repetition test status                                                  |
| 0x040   | HEALTH_TEST_STATUS          | [3] APT_FAIL          | RO       | 0          | APT test status                                                         |
| 0x040   | HEALTH_TEST_STATUS          | [4] MARKOV_HI_FAIL    | RO       | 0          | Markov high-threshold status                                            |
| 0x040   | HEALTH_TEST_STATUS          | [5] MARKOV_LO_FAIL    | RO       | 0          | Markov low-threshold status                                             |
| 0x044   | REPETITION_TEST_COUNT       | [15:0] REPETITION_COUNT | RO     | 0x0000     | Highest current repetition count                                        |
| 0x050   | APT_PATTERN_COUNT_1BIT      | [15:0] PATTERN_COUNT  | RO       | 0x0000     | Maximum per-lane one count                                              |
| 0x054   | APT_PATTERN_COUNT_2BIT      | [15:0] PATTERN_COUNT  | RO       | 0x0000     | Minimum per-lane one count                                              |
| 0x060   | APT_PROPORTION_1BIT         | [15:0] LIMIT          | RW       | 1200       | APT high one-count limit                                                |
| 0x070   | APT_PROPORTION_LO           | [15:0] LIMIT          | RW       | 848        | APT low one-count limit                                                 |
| 0x080   | MARKOV_TEST_COUNTS_0        | [15:0] COUNT_01       | RO       | 0x0000     | Highest per-lane alternation count                                      |
| 0x080   | MARKOV_TEST_COUNTS_0        | [31:16] COUNT_10      | RO       | 0x0000     | Lowest per-lane alternation count                                       |
|         | **RING OSCILLATOR CONTROL** |                       |          |            |                                                                         |
| 0x090   | RING_OSC_ENABLE             | [11:0] ENABLE         | RW       | 0x000      | Enable 12 noise ROs                                                     |
| 0x090   | RING_OSC_ENABLE             | [23:12] SAMPLE_CLK    | RW       | 0x000      | Enable 12 sample clock ROs                                              |
| 0x094   | RING_OSC_TUNE               | [11:0] DETUNE         | RW       | 0x000      | Detune noise ROs                                                        |
| 0x094   | RING_OSC_TUNE               | [23:12] SAMPLE_DETUNE | RW       | 0x000      | Detune sample clock ROs                                                 |
| 0x098   | RING_OSC_CTRL               | [11:0] CLK_SELECT     | RW       | 0x000      | Sample clock source select                                              |
|         | **DECORRELATOR CONTROL**    |                       |          |            |                                                                         |
| 0x0A0   | DECORRELATOR_CTRL           | [11:0] BYPASS         | RW       | 0x000      | Per-generator bypass (0x000=decorr, 0xFFF=bypass)                       |
| 0x0A0   | DECORRELATOR_CTRL           | [31:12] SAMPLE_DIV    | RW       | 63         | Sample clock divider (20-bit field)                                     |
| 0x0A4   | DECORRELATOR_MASK           | [7:0] BYTE_MASK       | RW       | 0xFF       | Entropy byte enable mask                                                |
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

## Address Map Notes

Offsets 0x008, 0x058-0x05C, 0x064-0x06C, and 0x088 are reserved holes with no register.

---

## Key Implementation Notes

### Decorrelator Configuration

**DECORRELATOR_CTRL Register (0x0A0)**:

- **SAMPLE_CLK_DIV field**: [31:12]
- **Field width**: 20-bit
- **Default value**: 63 (division by 64)
- **Range**: 8-255 for div-8 to div-256

**Common configurations**:

- Full decorrelation: BYPASS=0x000, DIV=63 (div-64)
- Full bypass: BYPASS=0xFFF, DIV=7 (div-8)
- Fast sampling: BYPASS=0x000, DIV=7 (div-8)
- Slow sampling: BYPASS=0x000, DIV=255 (div-256)

### Downsampling Configuration

**CTRL.DOWNSAMPLE_RATE field (0x004[25:16])**:

- **Default**: 0
- **Behavior**: Rate=0 means NO downsampling (capture all samples)
- **Applied after**: DECORRELATOR_CTRL.SAMPLE_CLK_DIV

### Compressor Bypass Mode

**CTRL.BYPASS_ENTROPY_COMPRESSOR field (0x004[8])**:

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

### Debug Monitor

**DEBUG_CTRL.SELECT_SIGNAL field (0x00C[7:0])**:

- **Signal count**: Selects one of 256 observation inputs
- **Observed data**: Includes raw uncompressed `entropy_stream_uncompressed[11:0][7:0]`

### Interrupt System

All eight interrupts use the same pattern:

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

- **HEALTH_TEST_STATUS (0x040)**: Tests the 32-bit post-BIW stream
- **GENERATOR_*_HEALTH_STATUS (0xC0-0xEC)**: Per-generator 8-bit byte-stream testing
- **Single interrupt**: HEALTH_TEST_FAILED triggers for any test failure
- **Status identification**: Read HEALTH_TEST_STATUS[7:0] to identify which test(s) failed

---

**Documentation References**:

- Complete test specifications: `TEST_PLAN.txt`
