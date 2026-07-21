# Efuse

The eFuse IP provides secure access to One-Time Programmable (OTP) memory
through a layered architecture that separates generic OCAH control logic from
adopter-specific macro integrations. The open tree contains the generic
controller, shadow registers, command interface, and APB-backed simulation model.
Foundry or macro-specific shims belong in adopter overlays.

## Open Model

The committed open model uses `efuse_interface_shim.sv` and
`efuse_bank_model.sv` for fast simulation with a register-backed behavioral OTP
bank. This path is technology-neutral and is intended for open RTL bring-up,
software development, and register validation. The bank model additionally
supports sim-only OTP image preload and program-fail injection (see
[`dv/models/README.md`](dv/models/README.md)), and a single model
serves either the SEP or SMC eFuse macro instance via its `IsSmcInstance`
parameter.

## Interfaces

The controller exposes functional and debug access paths and four destination
endpoints:

- **Shadow Registers**: boot-time cache of eFuse contents
- **Efuse CSR**: control and status registers for read/write operations
- **MMR**: security token storage used by SEP
- **Interface SHIM CSR**: adopter-specific timing/configuration registers routed
  through the generic controller

The macro-facing command interface is expressed as `fuse_command_*` packed
structs. Adopter shims translate that command/response contract into their own
macro-side read and program sequences.

## Behavioral Bank Model

The open `efuse_bank_model.sv` APB model provides a deterministic OTP-like
behavioral target for simulation. It models the 3 KB default bank size, read
commands, program commands, program/read-back commands, set-once semantics, and
lock behavior without embedding foundry macro collateral.

## Tests

Open tests should target the generic shim/model path. Overlay-specific tests and
macro timing models should live with the overlay that provides that integration.
