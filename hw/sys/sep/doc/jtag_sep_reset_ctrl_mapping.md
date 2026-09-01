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
| `trng_jtag_rst_n_val/ovrd` | `sep_reset_ctrl` | `sep_sw_rst_no.trng` | `sep.sv` → `sep_reset_ctrl` |
| `kmac_jtag_rst_n_val/ovrd` | `sep_reset_ctrl` | `sep_sw_rst_no.kmac` | same |
| `hmac_jtag_rst_n_val/ovrd` | `sep_reset_ctrl` | `sep_sw_rst_no.hmac` | same |
| `aes_jtag_rst_n_val/ovrd` | `sep_reset_ctrl` | `sep_sw_rst_no.aes` | same |
| `otbn_jtag_rst_n_val/ovrd` | `sep_reset_ctrl` | `sep_sw_rst_no.otbn` | same |
| `km_jtag_rst_n_val/ovrd` | `sep_reset_ctrl` | `sep_sw_rst_no.km` | same |

## Routing Summary

```
SMU u_dtp IC_RESET TDR, SEP slice
  └─ jtag_ic_reset_sep_o -> jtag_sep_reset_ctrl  (SMU-internal net, no SMU port)
       └─ sep u_sep_reset_ctrl
            ├─ .sep_reset_n_{val,ovrd}
            │    muxes sep_intermediate_reset_ni onto sep_reset_no
            └─ per-IP .ovrd/.val (trng, kmac, hmac, aes, otbn, km)
                 muxes (SW_RESET_N bit AND sep_reset_n) onto sep_sw_rst_no.*
```

The SEP slice is seven override/value pairs wide. `jtag_ptap` derives the
slice width and the aggregate TDR geometry from the struct itself
(`NUM_SEP_IC_RESET`); see the IC_RESET TDR geometry comment there rather than
tracking the total here.
