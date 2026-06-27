# OCA Log Engine

## Overview

The OCA Log Engine is a DMA-based logging system that efficiently transfers log messages from a configured memory region to a UART interface. It provides a scalable solution for system-level logging with hardware acceleration, reducing CPU overhead for log transmission. The engine supports up to 16 independent log entries with fair round-robin arbitration, making it suitable for multi-threaded or multi-core logging scenarios.

## Features

* **Multi-Interface Architecture**: 32-bit AXI4-Lite register interface, 64-bit AXI4-Lite log fetch interface, and 32-bit AXI4-Lite log write interface
* **Scalable Log Management**: Support for up to 16 independent log entries with configurable memory allocation
* **Fair Scheduling**: Round-robin arbitration ensures equitable access across all log entries
* **Flexible Memory Configuration**: Configurable memory log region size (must be multiple of 16 bytes) and start address (64-bit addressing)
* **UART Integration**: Direct hardware interface to UART transmitter with flow control support
* **Error Monitoring**: Comprehensive interrupt system for log fetch and write error detection
* **Flow Control**: Hardware-managed backpressure with UART ready signal integration
* **Parameterizable Design**: Configurable FIFO depth for performance tuning
* **Hardware Automation**: Automatic transfer completion detection and register clearing
* **SystemRDL Integration**: Register definitions generated from SystemRDL specification
* **Memory Efficiency**: Equal partitioning of memory region among 16 log entries
* **Real-time Operation**: Low-latency logging with minimal CPU intervention required

## Description

The OCA Log Engine operates as a hardware accelerator for system logging, bridging the gap between software log generation and UART-based log output. The engine is designed to handle high-frequency logging scenarios where software-only solutions would introduce significant CPU overhead.

### Operational Model

The Log Engine employs a memory-mapped approach where software components write log data to predefined memory regions and trigger transfers through register writes. Each of the 16 supported log entries has its own dedicated memory space within the configured log region, calculated as `region_size / 16` bytes per entry.

### Transfer Process

Log transfers are initiated by writing the desired byte count to one of the 16 LOG_CTRL registers. The engine's round-robin arbiter selects pending transfers fairly, ensuring no entry monopolizes the logging bandwidth. The selected log entry's data is fetched from memory in 64-bit words and buffered in an internal FIFO before being written byte-by-byte to the configured UART address.

### Memory Organization

The memory log region is equally partitioned among the 16 log entries:
- **Entry Address**: `log_region_addr + (entry_index × region_size/16) + byte_offset`
- **Maximum Entry Size**: `region_size/16` bytes
- **Addressing**: Full 64-bit memory addressing support

### Hardware Integration

The Log Engine integrates seamlessly with AXI4-Lite based systems and requires minimal external logic:
- **Clock Domain**: Single clock domain operation with standard reset methodology
- **Flow Control**: UART ready signal prevents transmitter overflow
- **Interrupt Support**: Error conditions generate maskable interrupts
- **Register Interface**: Standard AXI4-Lite register access for configuration and control

### Performance Characteristics

The engine is optimized for moderate throughput logging applications:
- **Fetch Bandwidth**: Limited by single AXI4-Lite transfer capability
- **Write Throughput**: Gated by UART transmitter capacity
- **Latency**: Minimal buffering provides low latency for time-sensitive logs
- **Fairness**: Round-robin scheduling prevents log entry starvation

### Software Interface

Software interaction with the Log Engine follows a simple pattern:
1. **Configuration**: Set memory region parameters and UART address
2. **Enablement**: Activate the engine through the control register
3. **Log Initiation**: Write log length to trigger transfers
4. **Completion Monitoring**: Poll or use interrupts to detect transfer completion
5. **Error Handling**: Process fetch/write error conditions as needed

This design provides an efficient, scalable solution for hardware-accelerated logging in embedded and system-on-chip applications, particularly beneficial in scenarios requiring high logging throughput or real-time performance constraints.