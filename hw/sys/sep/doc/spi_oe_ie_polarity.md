# SPI Output Enable / Input Enable Polarity Guide

This document explains the OE (Output Enable) and IE (Input Enable) signal
polarity conventions used by the open OCAH SEP SPI subsystem.

## Signal Flow Overview

```
OpenTitan SPI Host
    |
    v
sep_ot_spi_wrap
    |
    v
adopter pad or board-level integration
```

## Polarity Conventions

### OpenTitan SPI Host

OpenTitan uses active-HIGH OE/IE signals:

| Signal | Value | Meaning |
|--------|-------|---------|
| `sd_oe` | 1 | Output driver ENABLED |
| `sd_oe` | 0 | Output driver DISABLED (tri-state) |
| `sd_ie` | 1 | Input receiver ENABLED |
| `sd_ie` | 0 | Input receiver DISABLED |

### Adopter Pad Integration

The open RTL exports technology-neutral SPI pad control signals. Adopters are
responsible for mapping those signals to their pad cells and applying any
required polarity conversion in their overlay or top-level integration.

## Signal Transformation in OCH

### `sep_ot_spi_wrap.sv`

The `sep_ot_spi_wrap` module carries the OpenTitan SPI host signals through a
native AXI4-Lite integration wrapper. OE/IE polarity is kept explicit at the
wrapper boundary so the adopter integration can choose the required pad mapping.

## Key Design Decisions

1. **Open path stays technology-neutral**: The open tree does not encode a
   foundry pad-cell polarity.

2. **Adopter-owned polarity conversion**: Any final inversion belongs in the
   adopter pad integration, where the target pad cell semantics are known.

3. **Explicit signal naming**: Wrapper interfaces should make active-high versus
   active-low behavior clear in signal names and documentation.

## Troubleshooting

### Symptom: Data lines always tri-stated

- Check that OE is asserted at the SPI host wrapper output.
- Check the adopter pad integration for the expected OE polarity.

### Symptom: Data lines always driven (bus contention)

- Check that OE is being deasserted during read operations
- Verify no extra inversion in the signal path

### Symptom: Input data always 0 or X

- Check that IE is being asserted during read operations
- Verify input receiver is enabled at the pad

## Related Files

| File | Description |
|------|-------------|
| `hw/sys/sep/rtl/sep_ot_spi_wrap.sv` | Open SPI host integration wrapper |
| `hw/sys/sep/rtl/sep_io_pkg.sv` | SPI I/O signal type definitions |
