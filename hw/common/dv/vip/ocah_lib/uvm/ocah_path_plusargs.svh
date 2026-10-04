// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// File-path plusarg guard. A bench top includes this file at module scope and
// calls ocah_require_file_plusargs() from an `initial` block with no delay, so
// a `+<name>=<path>` whose file cannot be opened ends the run at time 0 with
// one line naming the plusarg. An absent plusarg is not an error; a bench
// lists every name it or its models consume as a path, and only the ones
// present on the command line are opened.
//
// The cocotb twin is ocah_lib.require_file_plusargs(); both report the same
// `[ocah_path_plusargs] +<name>=<path> is not a readable file` line.

function automatic void ocah_require_file_plusargs(input string names[]);
  string path;
  int    fd;
  foreach (names[i]) begin
    if (!$value$plusargs({names[i], "=%s"}, path)) continue;
    fd = $fopen(path, "r");
    if (fd == 0) begin
      $fatal(1, "[ocah_path_plusargs] +%s=%s is not a readable file", names[i], path);
    end
    $fclose(fd);
  end
endfunction
