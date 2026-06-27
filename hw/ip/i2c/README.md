# OCA I2C Interface Component

## Overview

The OCA I2C Interface Component is a comprehensive I2C/SMBus/PMBus communication controller that provides full-featured support for both controller (master) and target (slave) operation modes. Based on industry standards and featuring robust error handling, configurable FIFOs, and extensive interrupt support, this component enables reliable inter-chip communication in complex system-on-chip designs. The design supports multiple operating speeds and advanced features like clock stretching, multi-controller arbitration, and bus monitoring capabilities.

## Features

* **Multi-Protocol Support**: Full compliance with I2C Rev. 7.0, SMBus Rev. 3.2, and PMBus Rev. 1.4 specifications
* **Dual Operating Modes**: Configurable as controller-only, target-only, controller-target, or bus monitor
* **High-Speed Operation**: Support for Standard-mode (100 kbaud), Fast-mode (400 kbaud), and Fast-mode Plus (1 Mbaud) with bandwidth up to 1 Mbaud
* **Advanced Controller Features**: Clock stretching support, automatic ACK control, multi-controller clock synchronization and bus arbitration
* **Flexible Target Capabilities**: Automatic clock stretching, programmable ACK control, broadcast transfer support, and bus idle detection
* **Configurable FIFO Architecture**: Independent TX/RX FIFO depths for both controller and target modes (Controller: 64/64, Target: 64/268 default)
* **Comprehensive Interrupt System**: Multiple interrupt sources covering FIFO thresholds, overflows, protocol errors, and transaction events
* **DMA Integration**: Ready signals for external DMA controller integration with configurable FIFO thresholds
* **SMBus Extensions**: Native SMBSUS# and SMBALERT# signal support with wired-AND capability
* **Debug and Override**: Direct SCL/SDA control in override mode for debugging and low-level testing
* **AXI4-Lite Interface**: 32-bit register interface with 8-bit address space for configuration and data access
* **Input Delay Compensation**: Configurable input delay cycles parameter for timing optimization
* **Loopback Support**: External controller loopback capability when operating in target mode
* **Memory Integration**: RAM configuration interface for efficient FIFO memory management

## Description

The OCA I2C Interface Component implements a state-of-the-art I2C communication system designed for high-reliability embedded applications. The component architecture separates controller and target functionality while providing seamless integration between modes when configured for dual operation.

### Protocol Compliance and Standards

The implementation strictly adheres to the I2C specification revision 6 with enhanced support for SMBus and PMBus protocols. The component handles all mandatory I2C features including START/STOP conditions, acknowledge signaling, and 7-bit target addressing. Advanced optional features like clock stretching and multi-controller arbitration are fully supported, making it suitable for complex multi-controller bus topologies.

### Controller Mode Operation

In controller mode, the component initiates and manages all bus transactions. The controller FSM handles address transmission, data transfer, and proper bus arbitration with other controllers. Advanced features include automatic retry on arbitration loss, configurable timeout detection, and comprehensive error reporting. The controller supports both 7-bit addressing and handles read/write transactions with automatic ACK/NACK generation.

### Target Mode Operation

Target mode provides full slave functionality with automatic address recognition and response generation. The component supports configurable target addresses and can respond to broadcast transactions. Clock stretching capability allows the target to control bus timing when additional processing time is required. The target mode includes overflow protection and automatic FIFO management.

### FIFO Architecture and Data Flow

The component features independent FIFO structures for controller and target modes, with separate TX and RX paths. This architecture enables efficient data streaming and reduces CPU intervention during bulk transfers. Configurable FIFO depths allow optimization for different application requirements, while threshold-based interrupts and DMA ready signals provide flexible flow control options.

### Error Handling and Diagnostics

Comprehensive error detection covers protocol violations, bus conflicts, timing violations, and FIFO overflow conditions. The interrupt system provides detailed status information enabling robust error recovery strategies. Bus monitoring capabilities allow detection of stuck bus conditions and implementation of recovery procedures.

### System Integration

The component integrates seamlessly with AXI4-Lite based systems through its register interface and provides standard I/O signals for external connection. RAM configuration interface enables efficient memory resource utilization, while the parameterizable design allows customization for specific system requirements. The modular architecture facilitates integration into both ASIC and FPGA implementations.

### Performance and Optimization

Optimized state machines minimize bus overhead while maintaining protocol compliance. Configurable input delay compensation ensures proper timing margins across different system configurations. The component's architecture balances performance with resource efficiency, making it suitable for both high-performance and resource-constrained applications.