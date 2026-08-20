# JTAG SEP Reset Control - Open SEP Mapping

The 13 JTAG SEP reset overrides are split across two packed structs, by which side
of the SMU boundary consumes them. They live in different packages for the same
reason: only the SEP-internal half is open functional RTL.

| Struct | Package | Fields | DTP IC_RESET slice | Consumer |
|---|---|---|---|---|
| `jtag_sep_reset_ctrl_t` | `sep_pkg` (open) | 6 | SEP slice (`ic_reset_sep_t`) | `sep_reset_ctrl`, inside the SMU |
| `jtag_sep_spi_reset_ctrl_t` | `sep_spi_reset_pkg` (nonfree) | 7 | external slice (`ic_reset_ext_t`) | `sep_cdns_spi_wrap`, in the adopter SPI overlay outside the SMU |

The SMU has no output port for either: the SEP slice stays an internal net, and the
xSPI slice reaches the overlay through the SMU's existing `jtag_ic_reset_ext_o`.
Field declaration order within each struct is the TDI->TDO scan order, and
`jtag_ptap` sizes each slice from `$bits(type)/2`, so reordering or resizing either
struct moves TDR bit positions.

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

## Currently Implemented in `jtag_sep_spi_reset_ctrl_t`

### Cadence xSPI Reset Overrides (via `sep_cdns_spi_wrap`)

Consumed outside the SMU, so these ride the DTP's external IC_RESET slice. The
integrator sets `ic_reset_ext_t` to `sep_spi_reset_pkg::jtag_sep_spi_reset_ctrl_t` and routes
`jtag_ic_reset_ext_o` to the SPI integration.

| Struct Field | Override Applied In | Target Signal |
|---|---|---|
| `spi_xspi_jtag_rst_n_val/ovrd` | `sep_cdns_spi_wrap` | `spi_xspi_reset_n` |
| `spi_ctrl_reg_jtag_rst_n_val/ovrd` | same | `spi_ctrl_reg_reset_n` |
| `spi_phy_reg_jtag_rst_n_val/ovrd` | same | `spi_phy_reg_reset_n` |
| `spi_axi_jtag_rst_n_val/ovrd` | same | `spi_axi_reset_n` |
| `spi_phy_jtag_rst_n_val/ovrd` | same | `spi_phy_reset_n` |
| `spi_reg_jtag_rst_n_val/ovrd` | same | `spi_reg_reset_n` |
| `spi_xspi_reg_jtag_rst_n_val/ovrd` | same | `spi_xspi_reg_reset_n` |

### Not Yet Wired — Consider Adding

| Field | Relevant Module | Notes |
|---|---|---|
| `mailbox_jtag_rst_n_val/ovrd` | `axil_mailbox` in `sep_system_peripherals` | Allows independent mailbox reset without full SEP reset. Old project had this as a dedicated TDR. |
| SPI scan overrides | adopter SPI overlay | Adopter-owned SPI integrations may also want scan controls; only the reset overrides are wired today. |

## Old TDR → New Equivalent (Name Changed)

| Old TDR | Old Block | New Block in SEP | New Struct Field |
|---------|-----------|------------------|------------------|
| `jtag_sep_reset_n` | SEP main reset | SEP main reset | `sep_reset_n_val/ovrd` |
| `jtag_sep_ot_hmac_reset_n` | OT HMAC | HMAC | `hmac_jtag_rst_n_val/ovrd` |
| `jtag_sep_spacc_reset_n` | SPAcc (monolithic crypto) | **KMAC + AES** (split into OT IPs) | `kmac_jtag_rst_n` + `aes_jtag_rst_n` |
| `jtag_sep_pka_reset_n` | PKA (public key accelerator) | **OTBN** | `otbn_jtag_rst_n` |
| `jtag_sep_data_accel_reset_n` | Data accelerator | **KM (Key Manager)** | `km_jtag_rst_n` |
| SPI overlay reset controls | adopter SPI overlay | adopter integration | `jtag_sep_spi_reset_ctrl_t` (external slice) |

## Not Applicable to New SEP

| Old TDR | Why N/A |
|---------|---------|
| `o_jtag_sep_rsvd[16:0]` | Reserved bits, skip. |

## Routing Summary

```
SMU u_dtp IC_RESET TDR (TDI -> TDO: SMC | SEP | EXT)
  ├─ jtag_ic_reset_sep_o -> jtag_sep_reset_ctrl  (SMU-internal net, no port)
  │    └─ sep_wrapper (pass-through)
  │         └─ sep -> sep_reset_ctrl (fans out to two paths)
  │              ├─ Path A: .sep_reset_n_{val,ovrd}
  │              │    └─ Muxes sep_reset_no from sep_intermediate_reset_ni
  │              │       (efuse-sensing-done)
  │              └─ Path B: 5 crypto/KM overrides
  │                   └─ Muxes each of 5 sw_reset_bits (kmac, hmac, aes, otbn, km)
  └─ jtag_ic_reset_ext_o -> jtag_ic_reset_ext_o (SMU port, ic_reset_ext_t)
       └─ adopter SPI overlay (sep_ip_integration)
            └─ Path C: 7 xSPI overrides -> sep_cdns_spi_wrap
                 └─ Muxes spi_{xspi,xspi_reg,ctrl_reg,phy_reg,axi,phy,reg}_reset_n
```

Original internal migration notes are intentionally not reproduced in the open
tree.
