// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Pin rules on one STAP host leg, the forwarded TAP pins a downstream TAP
// samples at the rising TCK edge (IEEE 1149.1). tb_top instantiates one per
// STAP host port.
//
//   X-hygiene (four-state simulators only, `OCAH_ASSERT): the forwarded TMS
//   is resolved at every rising edge out of reset, and the host TDO at every
//   rising edge while its enable marks a shift. Outside a shift the host TDO
//   carries whatever the TDO lockup flop last sampled, which the rules leave
//   unchecked.
//   TDO timing (every simulator, `OCAH_SVA_ASSERT_I under SIMULATION): while
//   the enable marks a shift, the host TDO changes only in the TCK-low phase,
//   so the rising edge samples the bit the falling edge launched.
//
// trst_n is the forwarded host TRST, which carries power-on reset as well;
// en_i is the runtime suppress knob.

`include "ocah_assert.svh"
`include "ocah_sva_macros.svh"

module dtp_stap_host_sva (
  input wire logic tck,
  input wire logic trst_n,
  input wire logic tms,
  input wire logic tdo,
  input wire logic tdo_oen,
  input wire logic en_i
);

  wire tdo_shifting = en_i && (tdo_oen === 1'b1);

  `OCAH_ASSERT(DTP_STAP_HOST_TMS_KNOWN, en_i |-> !$isunknown(tms), tck, !trst_n)
  `OCAH_ASSERT(DTP_STAP_HOST_TDO_KNOWN_WHEN_SHIFTING, tdo_shifting |-> !$isunknown(tdo), tck,
               !trst_n)

`ifdef SIMULATION
  always @(tdo) begin
    if (tdo_shifting === 1'b1 && trst_n === 1'b1 && !$isunknown(tdo))
      `OCAH_SVA_ASSERT_I(DTP_STAP_HOST_TDO_NEGEDGE_WHEN_SHIFTING, (tck !== 1'b1))
  end
`endif  // SIMULATION

endmodule : dtp_stap_host_sva
