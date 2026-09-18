// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// GPIO shim -> prim_pad_wrapper pad shim
//
// Translates gpio_shim_pkg::gpio_model_ctrl_t into the vendored OpenTitan
// prim_pad_wrapper_pkg::pad_attr_t and instantiates the (InputStd/BidirStd)
// generic pad primitive. One instance per pin.
//-----------------------------------------------------------------------------

module prim_pad_shim #(
  parameter bit InputOnly = 1'b0
) (
  input  logic                            core2pad_i,
  input  logic                            core2pad_en_i,
  output logic                            pad2core_o,
  input  logic                            pad2core_en_i,
  input  gpio_shim_pkg::gpio_model_ctrl_t gpio_ctrl_i,
  input  logic                            gpio_nandtree_in_i,
  output logic                            gpio_nandtree_out_o,
  inout  wire                             pad_io
);

  import prim_pad_wrapper_pkg::*;

  pad_attr_t pad_attr;
  logic      pad_in;
  logic      pad_in_raw;

  assign pad_attr.invert         = 1'b0;
  assign pad_attr.virt_od_en     = 1'b0;
  assign pad_attr.od_en          = 1'b0;
  assign pad_attr.input_disable  = 1'b0;
  assign pad_attr.slew_rate      = 2'b00;
  assign pad_attr.keep_en        = 1'b0;
  assign pad_attr.pull_en        = gpio_ctrl_i.gpio_pull_en;
  assign pad_attr.pull_select    = gpio_ctrl_i.gpio_pull_sel;
  assign pad_attr.drive_strength = {1'b0, gpio_ctrl_i.gpio_drive_strength};
  assign pad_attr.schmitt_en     = gpio_ctrl_i.gpio_glitch_filter_enable;

  assign gpio_nandtree_out_o = gpio_nandtree_in_i;

  if (InputOnly) begin : gen_input
    prim_pad_wrapper #(
      .PadType(InputStd)
    ) u_pad (
      .clk_scan_i (1'b0),
      .scanmode_i (1'b0),
      .pok_i      ('0),
      .inout_io   (pad_io),
      .in_o       (pad_in),
      .in_raw_o   (pad_in_raw),
      .ie_i       (pad2core_en_i),
      .out_i      (1'b0),
      .oe_i       (1'b0),
      .attr_i     (pad_attr)
    );
    // Disabled input reads as 0.
    assign pad2core_o = pad_in & pad2core_en_i;
  end else begin : gen_bidir
    prim_pad_wrapper #(
      .PadType(BidirStd)
    ) u_pad (
      .clk_scan_i (1'b0),
      .scanmode_i (1'b0),
      .pok_i      ('0),
      .inout_io   (pad_io),
      .in_o       (pad_in),
      .in_raw_o   (pad_in_raw),
      .ie_i       (pad2core_en_i),
      .out_i      (core2pad_i),
      .oe_i       (core2pad_en_i),
      .attr_i     (pad_attr)
    );
    // Disabled input reads as 0
    // instead of propagating prim_pad_wrapper's disabled-input Z/X value.
    assign pad2core_o = pad_in & pad2core_en_i;
  end

endmodule
