# Telemetry Receiver Component

## Overview

The Telemetry Receiver is a high-performance hardware component designed to decode, buffer, and process telemetry data from telemetry transmitters in multi-chiplet systems. The component implements a specialized receiver for Tenstorrent-specific telemetry message formats while maintaining modularity for adaptation to other telemetry protocols and message structures.

The receiver processes telemetry messages containing chiplet NoC (Network-on-Chip) traffic statistics, including probe identification and multiple 32-bit counter values. Data is received through an 8-bit ATB (AMBA Trace Bus) interface and stored in a configurable circular buffer for efficient readout and analysis.

## Features

* **32-bit APB4 or AXI4-Lite Register Interface**: Standard bus interfaces for system integration and configuration access
* **8-bit ATB Telemetry Interface**: High-speed telemetry data reception with ATB protocol compliance
* **Configurable Circular Buffer**: Programmable buffer depth (default 8 entries) with threshold-based monitoring
* **Multi-Counter Message Support**: Decodes messages with probe ID and up to 4 counter values per message
* **Flexible Message Format**: Modular design allows easy adaptation to different telemetry message formats via local parameters
* **Comprehensive Interrupt System**: Buffer threshold and error condition interrupts for efficient event-driven operation
* **Real-time Status Monitoring**: Buffer occupancy, message validity, and error status reporting
* **LSB-First Data Processing**: Optimized for little-endian message formats with 8-bit beat processing
* **Packet Validation**: Automatic detection of incomplete messages and missing packet indicators
* **Counter Validity Tracking**: Per-byte validity bits for robust counter value interpretation

## Description

The Telemetry Receiver implements a sophisticated telemetry data processing pipeline specifically optimized for NoC traffic monitoring in multi-chiplet architectures. The component receives telemetry data as a stream of 8-bit beats transmitted in LSB-first format, assembles these beats into structured packets, and extracts meaningful telemetry information including probe identifiers and performance counters.

The receiver's architecture centers around a two-stage processing system: an assembly buffer that reconstructs complete telemetry messages from incoming data beats, and a message buffer that stores decoded telemetry information for software readout. This dual-buffer approach enables continuous data reception while allowing software to process previously received messages without blocking incoming telemetry streams.

Each telemetry message consists of 1-3 packets, where every packet contains 8 beats (64 bits total). The first packet includes the probe ID identifying the monitoring location, the first counter value, and partial data for the second counter. Subsequent packets contain additional counter values, with the final packet marked by a "last packet" bit. Each counter byte is encoded with a validity bit, enabling robust handling of partially valid or corrupted counter data.

The component supports up to four 32-bit counters per telemetry message, providing comprehensive monitoring capability for NoC traffic analysis, performance characterization, and system health monitoring. Counter values represent various traffic metrics such as packet counts, bandwidth utilization, latency measurements, and congestion indicators, enabling detailed system-level performance analysis and optimization.

Advanced features include configurable buffer thresholds for interrupt generation, automatic detection of missing packet terminators, and comprehensive status reporting for system-level diagnostics. The modular design facilitates easy customization for different telemetry formats while maintaining compatibility with standard AMBA interfaces and existing system software frameworks.