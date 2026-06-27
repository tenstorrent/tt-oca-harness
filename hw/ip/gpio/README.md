# GPIO Peripheral

## Overview

The GPIO (General Purpose Input/Output) peripheral provides programmable digital I/O capabilities for the OCH system. It serves as a flexible interface for configuration straps, general-purpose signaling, and bit-banging protocols. The peripheral features dual-mode operation supporting both register-driven control and LSIO (Low Speed Input/Output) interface control with comprehensive access filtering and interrupt generation capabilities.

## Features

* **Dual Control Modes**: Register-driven control or LSIO interface selection with programmable direction control
* **Flexible I/O Configuration**: Bidirectional data path with independent RX/TX enable controls
* **Security & Access Control**: Advanced register access filtering with AXI protection level requirements for secure system integration
* **Configuration Strap Support**: Hardware strap capture during system reset for boot-time configuration
* **Comprehensive Interrupt System**: Configurable interrupt generation with multiple trigger modes (active-high/low level, rising/falling edge)
* **Programmable Electrical Characteristics**: Software-configurable drive strength, pull-up/pull-down resistors, and Schmitt trigger selection
* **Standard Bus Interfaces**: Support for both APB4 and AXI4-Lite register interfaces with generated interface code
* **Glitch Filtering**: Hardware-based glitch filtering for improved signal integrity
* **Dual Register Banks**: Separate interface control (gpio_intf_reg) and physical configuration (gpio_ctrl_reg) register sets
* **LSIO Integration**: Direct interface to Low Speed I/O subsystem for high-speed protocol handling
* **Test and Debug Support**: Comprehensive testbench framework with cocotb Python-based verification environment

## Description

The GPIO peripheral implements a sophisticated digital I/O control system designed for both general-purpose signaling and system-level configuration management. The architecture centers around a dual-interface design that allows software to choose between direct register control and hardware-assisted LSIO protocol handling, making it suitable for both simple bit manipulation and complex low-speed protocol implementations.

The peripheral's core functionality revolves around a bidirectional data path with independent transmit and receive enable controls. When configured for register-driven operation, software has complete control over the pad state through the DATA_CTRL register, including output data values and direction control. Alternatively, the LSIO interface mode allows external hardware to drive the GPIO signals directly, enabling high-speed protocol processing without software intervention.

Security features include comprehensive access control mechanisms that can restrict register access based on AXI protection levels, making individual GPIO pins accessible only to specific system components or privilege levels. This is particularly valuable for system-critical configuration pins and security-sensitive signaling paths.

The interrupt subsystem provides flexible event detection with support for both level-sensitive and edge-triggered interrupts. This enables efficient software notification for input signal changes, supporting both polling and interrupt-driven I/O models depending on application requirements.

Configuration strap functionality automatically captures pad values during system reset, providing a hardware mechanism for boot-time system configuration. The captured strap values are made available through read-only status registers, enabling software to determine system configuration without external storage requirements.

Physical layer characteristics are fully programmable through the gpio_ctrl_reg register bank, allowing software control of drive strength, pull resistor configuration, and Schmitt trigger selection. This flexibility enables the GPIO to interface with a wide variety of external devices and voltage levels while maintaining signal integrity.

The modular architecture includes separate interface and control register banks, allowing for independent management of logical functionality (data direction, protocol selection) and physical characteristics (drive strength, termination). This separation simplifies software development and enables fine-grained control over both digital and analog aspects of the I/O interface.