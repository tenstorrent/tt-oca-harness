# eFuse Model

Simulation-only behavioral OTP bank, driven through
[`efuse_interface_shim.sv`](../../rtl/efuse_interface_shim.sv) (in
`hw/ip/efuse/rtl/`) which translates the generic `fuse_command_*` controller
interface into the APB sequence this model expects. It is a single,
technology-neutral bank model shared by both the SEP and SMC eFuse macro
instances.

## `efuse_bank_model.sv`

A 4 KB (1024 x 32-bit word), register-backed, write-one-to-set APB target
(`efuse_bank_reg.sv`, hand-maintained in this directory; `regs/efuse_bank.rdl`
describes the same register layout and is excluded from `make regen-regs`).
Beyond the bank storage itself, it adds three simulation-only conveniences:

- **OTP image preload**: deposits an Intel-hex image into the bank once reset is released
  (`+sep_efuse_hex=<path>` / `+smc_efuse_hex=<path>`, SEP defaults to
  `out/sep_efuse.hex` when no plusarg is given).
- **Program-fail injection**: silently drops program writes (no APB error,
  matching real OTP) to exercise firmware's `PROGRAM_READ_BACK` error path —
  either the first N writes after reset
  (`+{sep,smc}_efuse_prog_fail_count=<N>`) or ~N% of writes at random
  (`+{sep,smc}_efuse_prog_fail_percent=<N>`, seeded by
  `+{sep,smc}_efuse_prog_fail_seed`).
- **`IsSmcInstance` parameter**: selects the `sep_`/`smc_` plusarg prefix and
  log tag above so one model serves either macro instance; the bank itself is
  otherwise identical for both.

## Usage

Instantiate one `efuse_bank_model` per eFuse macro instance (SEP and SMC each
have their own, independent OTP bank — see
[`hw/sys/smc/rtl/smc_peripherals/efuse/smc_efuse_wrapper.sv`](../../../../sys/smc/rtl/smc_peripherals/efuse/smc_efuse_wrapper.sv)),
wired to the corresponding `efuse_interface_shim`'s `efuse_model_otp_req_o`/
`efuse_model_otp_resp_i` ports. See `hw/top/sep_ip_integration.sv` and
`hw/top/smc_ip_integration.sv` for reference integrations.
