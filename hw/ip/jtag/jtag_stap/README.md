# JTAG Secondary Test Access Port (STAP) Interface

This module provides a scan chain interface for connecting to remote
Primary Test Access Ports (PTAPs) on other chiplets or dies, as well
as to local on-chip TAP controllers. It implements a flexible interface
with optional timing optimization features.

The STAP includes a Segment Insertion Bit (SIB) for selective access
to a 3-bit control register (3DCR) that controls TMS parking, STAP
selection, and configuration hold behavior.

Key features include optional scan input pipeline stage, lockup latches 
on TDI/TDO/scan output paths for timing closure, and parameterized 
control structures that allow new signals to be added without RTL 
modifications.

Reset handling supports both TRST and scan control resets from TLR 
transitions, with the config_hold bit allowing the 3DCR to maintain 
state across TAP state machine operations.

The `security_disable_i` input is part of the generic IP behavior. When asserted, it blocks host
access while preserving the internal 3DCR control/readback path.

There is no CSR block associated with this component as it is a
primitive intended for instantiation in larger JTAG hierarchies
and multi-die test access systems.

## Running Tests

```bash
cd dv/tb
make help
```

## Documentation

The pages under `doc/` are AsciiDoc sources published with the rest of the OCAH
documentation, under the DTP subsystem in the TRM:

```bash
make -f ocah.mk ocah-doc-trm-html
```

