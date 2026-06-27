# System Timer OCTS IP

## Overview

The System Timer OCTS (Open Chiplet Time Synchronization) IP is a sophisticated 64-bit timer designed specifically for multi-chiplet systems requiring precise time synchronization across different clock domains. This hardware IP provides a robust solution for coordinated timing operations between multiple timer instances, enabling accurate timestamping and synchronized operations in distributed chiplet architectures. The timer supports configurable PRIMARY/SECONDARY modes with built-in clock domain crossing capabilities and comprehensive error detection mechanisms.

## Features

* **Dual Operation Modes**: Configurable as PRIMARY (timing master) or SECONDARY (timing follower) timer instance
* **64-bit High-Precision Counter**: Full 64-bit counter range providing nanosecond-level timing resolution
* **Multi-Protocol Bus Support**: Flexible bus interface supporting both APB4 and AXI4-Lite protocols with flattened variants
* **Clock Domain Crossing**: Built-in CDC synchronization using proven 2FF synchronizer for reliable cross-domain operation
* **Credit-Based Synchronization**: Programmable credit mechanism enabling periodic resynchronization with configurable credit values
* **Configurable Pulse Generation**: Adjustable pulse width for synchronization signals (sync_load and credit pulses)
* **Real-time Status Monitoring**: Running status indicator and current count value accessible via registers
* **Synchronization Error Detection**: Credit expired counter register for monitoring synchronization health between PRIMARY and SECONDARY instances
* **Flexible Preset Capability**: 64-bit preset value loading for synchronized timer initialization
* **Comprehensive Register Interface**: Complete register set for configuration, control, and status monitoring
* **Test Mode Support**: Built-in test enable and scan reset support for manufacturing test integration
* **Step Input Support**: External step input for SECONDARY mode allowing fine-grained timing adjustment
* **Hardware-Software Integration**: Seamless integration with software through memory-mapped register interface
* **Robust Error Handling**: Timeout detection and error reporting for system-level fault tolerance
* **Low-Power Design**: Optimized for minimal power consumption while maintaining timing accuracy

## Description

The System Timer OCTS IP addresses the critical challenge of maintaining synchronized timing across multiple chiplets in a disaggregated computing system. In multi-chiplet architectures, precise time synchronization is essential for coordinated operations, distributed computing tasks, performance monitoring, and system-level debugging.

### Operational Architecture

The timer operates in one of two distinct modes determined at instantiation time through the IS_PRIMARY parameter. The PRIMARY timer acts as the timing authority, generating synchronization signals and maintaining the master timeline. SECONDARY timers receive synchronization signals from the PRIMARY and adjust their local counters to maintain alignment with the master timeline.

### Synchronization Mechanism

The synchronization protocol uses a credit-based approach where the PRIMARY timer periodically sends credit pulses to SECONDARY timers. Each SECONDARY timer maintains an internal credit counter that decrements with each clock cycle. When the credit counter reaches zero, the SECONDARY timer relies on incoming credit pulses to continue accurate timekeeping. This mechanism provides both continuous operation and periodic resynchronization opportunities.

The sync_load signal provides a global reset mechanism, allowing all timers in the system to start from a synchronized baseline. This is particularly useful for system initialization and recovery scenarios.

### Clock Domain Crossing

The timer incorporates robust clock domain crossing logic using proven 2FF synchronizers. This enables reliable operation even when PRIMARY and SECONDARY timers operate in different clock domains, which is common in multi-chiplet systems where each chiplet may have its own local clock source.

### Error Detection and Recovery

The credit expired counter serves as a critical diagnostic tool for system health monitoring. In a properly functioning system, this counter should remain low, indicating regular receipt of credit pulses from the PRIMARY timer. If the counter grows large, it indicates potential communication failures, clock issues, or PRIMARY timer malfunctions, enabling proactive system maintenance and fault isolation.

### Register Interface and Software Integration

The comprehensive register interface provides software with complete control over timer operation. Configuration registers allow setting of credit values, pulse widths, and preset values. Status registers provide real-time information about timer state, current count values, and synchronization health. The interface supports both APB4 and AXI4-Lite protocols, making it compatible with a wide range of system-on-chip architectures.

### Test and Validation Support

The design includes comprehensive test infrastructure supporting both manufacturing test and system validation. Test modes allow bypassing normal operation for direct register access and functional verification. The cocotb-based testbench provides extensive coverage including cross-domain synchronization testing, credit mechanism validation, and error condition simulation.

### Multi-Chiplet System Integration

In a typical multi-chiplet deployment, one chiplet hosts the PRIMARY timer while other chiplets host SECONDARY timers. The synchronization signals are routed through the inter-chiplet communication fabric, enabling system-wide time coordination. The credit mechanism provides resilience against temporary communication disruptions while maintaining long-term synchronization accuracy.

This design enables applications such as distributed computing tasks with precise timing requirements, coordinated data collection across multiple chiplets, system-wide performance monitoring with synchronized timestamps, and debugging of complex multi-chiplet interactions with accurate timing correlation.