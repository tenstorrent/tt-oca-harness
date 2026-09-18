// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Knob accessor: the one place plusargs are read. A knob is a named integer
// control; the cocotb twin reads the same name from the environment, so
// bench code names knobs and never spells the transport. The simulator seed
// is not a knob: only ocah_test reads it (base_seed()).

class ocah_knobs;

  // Integer knob with a default; absent knob returns the default.
  static function int unsigned get_int(string name, int unsigned default_value);
    int unsigned value;
    if ($value$plusargs({name, "=%d"}, value)) return value;
    return default_value;
  endfunction

  // Integer knob with a lower bound: a present value below the bound is a
  // configuration defect, never silently clamped.
  static function int unsigned get_int_min(string name, int unsigned default_value,
                                           int unsigned minimum);
    int unsigned value = get_int(name, default_value);
    if (value < minimum)
      `uvm_fatal("ocah_knobs", $sformatf("+%s must be >= %0d, got %0d", name, minimum, value))
    return value;
  endfunction

  // Presence knob (`+NAME` with no value).
  static function bit is_set(string name);
    return $test$plusargs(name);
  endfunction

endclass : ocah_knobs
