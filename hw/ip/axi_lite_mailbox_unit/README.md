# Mailbox Unit

## Overview

This document specifies the Mailbox Unit hardware IP functionality. The Mailbox
Unit provides FIFO-based bidirectional communication channels for
inter-processor or inter-chiplet communication using AXI4-Lite interfaces. It
enables efficient data exchange between processing elements through dedicated
hardware channels with minimal software overhead.

## Features

* Multiple configurable mailbox instances
* FIFO-based communication with configurable depth
* Bidirectional inbound and outbound channels
* 64-bit data width support
* Programmable interrupt thresholds
* Error detection and reporting
* AXI4-Lite interface compatibility
* Software-controllable FIFO flush operations

## Description

The Mailbox IP is designed for secure communication between processing elements
in multi-core or multi-chiplet systems. Each mailbox instance provides paired
channels for simultaneous bidirectional data transfer. The IP supports multiple
independent mailbox pairs, each with dedicated control registers, status
monitoring, and interrupt generation capabilities. The implementation uses
standard AXI4-Lite interfaces for integration into existing system
architectures.

**Generating the IP**

```bash
python3 generate_ip.py -i <io-port-type>
```

Replace `<io-port-type>` with:
- `axi4-lite`
- `axi4-lite-flattened`

**Note**: This IP is AXI4-Lite exclusive and does not support APB4 interfaces.