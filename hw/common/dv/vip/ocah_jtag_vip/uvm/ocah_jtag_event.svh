// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Passive monitor observation event, distinct from the stimulus sequence
// item (items carry intent, events carry observed behavior). One flexible
// event object with a kind enum:
//
//   OCAH_JTAG_EV_STEP — one completed TCK cycle. tms/tdi are the values the
//     DUT captured on the rising edge; tdo is the value stable just before
//     it. Published on the following TCK falling edge, when subscribers can
//     safely sample any DUT-side observables that update on the rising edge.
//   OCAH_JTAG_EV_TRST — asynchronous TRST assertion/release edge.

typedef enum {
  OCAH_JTAG_EV_STEP,
  OCAH_JTAG_EV_TRST
} ocah_jtag_event_kind_e;

class ocah_jtag_event extends uvm_object;
  `uvm_object_utils(ocah_jtag_event)

  ocah_jtag_event_kind_e kind = OCAH_JTAG_EV_STEP;

  // STEP fields.
  bit tms;
  bit tdi;
  bit tdo;
  bit trst_n;          // level during the step (0 = TAP held in reset)
  int unsigned index;  // monotonically increasing TCK-cycle counter

  // TRST fields.
  bit trst_asserted;   // 1 = falling edge (reset asserted), 0 = released

  // Debug context.
  time timestamp;

  function new(string name = "ocah_jtag_event");
    super.new(name);
  endfunction

  function string convert2string();
    if (kind == OCAH_JTAG_EV_TRST)
      return $sformatf("TRST %s @%0t", trst_asserted ? "asserted" : "released", timestamp);
    return $sformatf(
        "STEP %0d: tms=%0b tdi=%0b tdo=%0b trst_n=%0b @%0t", index, tms, tdi, tdo, trst_n, timestamp
    );
  endfunction

endclass : ocah_jtag_event
