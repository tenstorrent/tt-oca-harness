// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Hold types for the GPIO pad shim and model control/status structs.
//
// Bundles the fields the shim drives into gpio_model and reads back as status.

package gpio_shim_pkg;

  `include "axi/typedef.svh"

  ////////////////////////////
  // GPIO Definitions //
  ////////////////////////////

  typedef struct {
    logic [2:0] gpio_drive_strength;
    logic       gpio_pull_en;  // Active high weak PU/PD resistor enable.
    logic       gpio_pull_sel; // 0: pull down, 1: pull up.
    logic       gpio_sps;      // Active low weak PD resistor enable.
    logic       gpio_glitch_filter_enable; // Active high glitch filter enable.
  } gpio_model_ctrl_t;

  typedef struct {logic state;} gpio_model_status_t;

endpackage
