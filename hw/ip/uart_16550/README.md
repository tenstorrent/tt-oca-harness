# UART 16550 Component

## Overview

This document specifies the UART 16550 hardware Component functionality. The UART 16550 implements the National Semiconductor UART 16550 standard with additional enhancements including independently-configurable Transmitter and Receiver FIFO depths and FIFO data and pointer parity protection. It provides a full-featured serial communication interface compatible with industry-standard UART protocols.

## Features

* Full UART 16550 compatibility and functionality
* 32-bit AXI4-Lite register interface
* Independently-configurable Transmitter and Receiver FIFO depths (4 to 4096 entries)
* FIFO parity protection for data and pointers with error reporting
* Comprehensive interrupt support with 6 priority levels
* Direct Memory Access (DMA) signaling with immediate and hysteresis modes
* Modem control interface (CTS, DSR, RI, DCD, RTS, DTR, OUT1, OUT2)
* System and line loopback modes for testing
* Programmable baud rate generation with 16x oversampling
* Configurable word length, stop bits, and parity
* Break signal generation and detection
* Timeout detection for incomplete transfers

## Description

The UART 16550 Component is a serial communication controller designed for embedded systems requiring reliable asynchronous serial communication. It extends the classic 16550 UART with enhanced FIFO capabilities and robust error detection mechanisms. The IP supports both APB4 and AXI4-Lite register interfaces for flexible system integration.

The design features independent transmit and receive data paths with configurable FIFO depths, enabling efficient handling of high-throughput serial communication with minimal CPU intervention. Advanced features include comprehensive interrupt management, DMA support for automated data transfers, and extensive loopback capabilities for system validation.

**Register Interface Compatibility**

The component supports both APB4 and AXI4-Lite interfaces:
* APB4: Traditional 32-bit peripheral bus interface
* AXI4-Lite: Advanced microcontroller bus architecture for higher performance applications

**Generating SystemRDL Documentation**

The register maps are defined using SystemRDL and can be regenerated using:

```bash
cd hw/comp/uart_16550/regs/
peakrdl regblock uart_16550_main.rdl -o ../rtl/ --cpuif axi4-lite --module-name uart_16550_main_reg
peakrdl regblock uart_16550_dl.rdl -o ../rtl/ --cpuif axi4-lite --module-name uart_16550_dl_reg
```