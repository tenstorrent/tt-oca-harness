# JTAG SEP Reset Control Mapping

`sep_pkg::jtag_sep_reset_ctrl_t` carries the seven JTAG reset overrides consumed
by `sep_reset_ctrl`. The SMU drives it from the DTP's SEP IC_RESET slice
(`ic_reset_sep_t`, enabled by `JTAG_IC_RESET_SEP_ENABLE`) over an internal net;
there is no SMU port for it.

The struct is a pair of `.ovrd`/`.val` sub-structs that must stay the same width;
field declaration order within them is the TDI->TDO scan order, and `jtag_ptap`
sizes the slice from `$bits(type)/2`. Reordering or resizing either sub-struct
moves TDR bit positions. A new override is therefore declared at each
sub-struct's MSB, so the positions already in use do not shift.

## SEP Main Reset Override

| Struct Field | Override Applied In | Target Signal | RTL Path |
|---|---|---|---|
| `sep_reset_n_val/ovrd` | `sep_reset_ctrl` | `sep_reset_no` | `sep.sv` → `sep_reset_ctrl` |

## Crypto SW Reset Overrides (via `sep_reset_ctrl`)

| Struct Field | Override Applied In | Target Signal | RTL Path |
|---|---|---|---|
| `trng_jtag_rst_n_val/ovrd` | `sep_reset_ctrl` | `sep_sw_rst_no.trng` | `sep.sv` → `sep_reset_ctrl` → coordinated TRNG AXI isolate |
| `kmac_jtag_rst_n_val/ovrd` | `sep_reset_ctrl` | `sw_reset_bits[4]` | `sep.sv` → `sep_reset_ctrl` |
| `hmac_jtag_rst_n_val/ovrd` | `sep_reset_ctrl` | `sw_reset_bits[3]` | same |
| `aes_jtag_rst_n_val/ovrd` | `sep_reset_ctrl` | `sw_reset_bits[2]` | same |
| `otbn_jtag_rst_n_val/ovrd` | `sep_reset_ctrl` | `sw_reset_bits[1]` | same |
| `km_jtag_rst_n_val/ovrd` | `sep_reset_ctrl` | `sw_reset_bits[0]` | same |

## Not Yet Wired — Consider Adding

| Field | Relevant Module | Notes |
|---|---|---|
| `mailbox_jtag_rst_n_val/ovrd` | `axil_mailbox` in `sep_system_peripherals` | Allows independent mailbox reset without full SEP reset. Old project had this as a dedicated TDR. |

## Old TDR → New Equivalent (Name Changed)

| Old TDR | Old Block | New Block in SEP | New Struct Field |
|---------|-----------|------------------|------------------|
| `jtag_sep_reset_n` | SEP main reset | SEP main reset | `sep_reset_n_val/ovrd` |
| `jtag_sep_ot_hmac_reset_n` | OT HMAC | HMAC | `hmac_jtag_rst_n_val/ovrd` |
| `jtag_sep_spacc_reset_n` | SPAcc (monolithic crypto) | **KMAC + AES** (split into OT IPs) | `kmac_jtag_rst_n` + `aes_jtag_rst_n` |
| `jtag_sep_pka_reset_n` | PKA (public key accelerator) | **OTBN** | `otbn_jtag_rst_n` |
| `jtag_sep_data_accel_reset_n` | Data accelerator | **KM (Key Manager)** | `km_jtag_rst_n` |

## Not Applicable to New SEP

| Old TDR | Why N/A |
|---------|---------|
| `o_jtag_sep_rsvd[16:0]` | Reserved bits, skip. |

## Routing Summary

```
SMU u_dtp IC_RESET TDR, SEP slice
  └─ jtag_ic_reset_sep_o -> jtag_sep_reset_ctrl  (SMU-internal net, no port)
       └─ sep_wrapper (pass-through)
            └─ sep -> sep_reset_ctrl (fans out to two paths)
                 ├─ Path A: .sep_reset_n_{val,ovrd}
                 │    └─ Muxes sep_reset_no from sep_intermediate_reset_ni
                 │       (efuse-sensing-done)
                 └─ Path B: 6 crypto/KM/TRNG overrides
                      └─ Muxes each of 6 sw_reset_bits (trng, kmac, hmac, aes,
                         otbn, km)
```

The SEP slice is therefore seven override/value pairs wide. The TRNG pair sits
at the top, so the six already in use keep their TDR positions. `jtag_ptap`
derives the slice width and the aggregate TDR geometry from the struct itself
(`NUM_SEP_IC_RESET`); see the IC_RESET TDR geometry comment there rather than
tracking the total here.

Original internal migration notes are intentionally not reproduced in the open
tree.
