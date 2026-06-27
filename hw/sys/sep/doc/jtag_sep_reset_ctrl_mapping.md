# JTAG SEP Reset Control - Open SEP Mapping

## Currently Implemented in `jtag_sep_reset_ctrl_t`

### SEP Main Reset Override

| Struct Field | Override Applied In | Target Signal | RTL Path |
|---|---|---|---|
| `sep_reset_n_val/ovrd` | `sep_reset_ctrl` | `sep_reset_no` | `sep.sv` → `sep_reset_ctrl` |

### Crypto SW Reset Overrides (via `sep_reset_ctrl`)

| Struct Field | Override Applied In | Target Signal | RTL Path |
|---|---|---|---|
| `kmac_jtag_rst_n_val/ovrd` | `sep_reset_ctrl` | `sw_reset_bits[4]` | `sep.sv` → `sep_reset_ctrl` |
| `hmac_jtag_rst_n_val/ovrd` | `sep_reset_ctrl` | `sw_reset_bits[3]` | same |
| `aes_jtag_rst_n_val/ovrd` | `sep_reset_ctrl` | `sw_reset_bits[2]` | same |
| `otbn_jtag_rst_n_val/ovrd` | `sep_reset_ctrl` | `sw_reset_bits[1]` | same |
| `km_jtag_rst_n_val/ovrd` | `sep_reset_ctrl` | `sw_reset_bits[0]` | same |

### Not Yet Wired — Consider Adding

These are commented out in the struct definition with TODO notes:

| Commented-Out Field | Relevant Module | Notes |
|---|---|---|
| `mailbox_jtag_rst_n_val/ovrd` | `axil_mailbox` in `sep_system_peripherals` | Allows independent mailbox reset without full SEP reset. Old project had this as a dedicated TDR. |
| SPI scan/reset overrides | adopter SPI overlay | Optional adopter-owned SPI integrations may need their own reset and scan controls. |

## Old TDR → New Equivalent (Name Changed)

| Old TDR | Old Block | New Block in SEP | New Struct Field |
|---------|-----------|------------------|------------------|
| `jtag_sep_reset_n` | SEP main reset | SEP main reset | `sep_reset_n_val/ovrd` |
| `jtag_sep_ot_hmac_reset_n` | OT HMAC | HMAC | `hmac_jtag_rst_n_val/ovrd` |
| `jtag_sep_spacc_reset_n` | SPAcc (monolithic crypto) | **KMAC + AES** (split into OT IPs) | `kmac_jtag_rst_n` + `aes_jtag_rst_n` |
| `jtag_sep_pka_reset_n` | PKA (public key accelerator) | **OTBN** | `otbn_jtag_rst_n` |
| `jtag_sep_data_accel_reset_n` | Data accelerator | **KM (Key Manager)** | `km_jtag_rst_n` |
| SPI overlay reset controls | adopter SPI overlay | adopter integration | overlay-defined |

## Not Applicable to New SEP

| Old TDR | Why N/A |
|---------|---------|
| `o_jtag_sep_rsvd[16:0]` | Reserved bits, skip. |

## Routing Summary

```
SMU (jtag_sep_reset_ctrl = '0, TODO: DTP drives)
  └─ sep_wrapper (pass-through)
       └─ sep (fans out to three paths)
            ├─ Path A: .sep_reset_n_{val,ovrd} → sep_reset_ctrl
            │    └─ Muxes sep_reset_no from sep_intermediate_reset_ni (efuse-sensing-done)
            ├─ Path B: full struct → sep_reset_ctrl
            │    └─ Muxes each of 5 sw_reset_bits (kmac, hmac, aes, otbn, km)
            └─ Optional adopter overlay
                 └─ Adds overlay-specific reset controls if needed
```

Original internal migration notes are intentionally not reproduced in the open
tree.
