// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Byte offset -> (bank, entry) for the 4-core CPU scratchpad.
//
// One definition, used by every backdoor that reaches the scratch macros: the
// +smc_scratch_ram_hex image loader in smc_cpu_mem_dv.sv and the peek decodes
// in tb_top.sv. A wrong copy of this map is silent: it loads firmware into
// banks the CPU never fetches from, and every testcase that does not execute
// that firmware still passes.
//
// Sources. The geometry comes from the register description and the
// architecture document, never from the cluster RTL:
//
//   hw/sys/smc/regs/include/spm_memory.rdl
//     mem spm_memory: NUM_ENTRIES = 131072 words of WIDTH = 64 bits, i.e.
//     8 bytes per entry and 1 MiB of scratch in total.
//   hw/sys/smc/doc/cpu.adoc, memory-system table
//     Local SRAM/Scratchpad: 1 MiB (32 banks), SECDED ECC.
//
// The interleave -- how an offset inside that 1 MiB picks one of the 32 banks
// and an entry within it -- is not fixed by either document. It is carried
// here as a DV-owned table with two assumptions: consecutive 64-byte stripes
// rotate across the FOUR banks of a group, and the eight 128 KiB groups are
// contiguous. Bank and entry are then
//
//     bank  = 4 * (offset / 128 KiB) + (offset / 64) % 4
//     entry = ((offset % 128 KiB) / 256) * 8 + (offset % 64) / 8
//
// smc_dual_axi_sram_probe_test cross-checks this table against front-door AXI
// traffic (CHK-SCRATCH-BACKDOOR-DECODE): a table that disagreed with the
// design fails that testcase instead of silently misplacing an image. A flat
// "round-robin across all 32 banks every 64 bytes" model agrees with this
// table only for the first 256 bytes and diverges from offset 0x100 onward.
package smc_scratch_map_pkg;

  // spm_memory.rdl: 131072 entries x 64 bits.
  localparam int unsigned SCRATCH_NUM_ENTRIES = 131072;
  localparam int unsigned SCRATCH_ENTRY_BITS = 64;
  localparam int unsigned SCRATCH_BYTES_PER_ENTRY = SCRATCH_ENTRY_BITS / 8;
  localparam int unsigned SCRATCH_TOTAL_BYTES = SCRATCH_NUM_ENTRIES * SCRATCH_BYTES_PER_ENTRY;
  // cpu.adoc: 32 banks.
  localparam int unsigned SCRATCH_NUM_BANKS = 32;

  // DV-owned interleave assumptions (see the header).
  localparam int unsigned SCRATCH_BANK_STRIPE_BYTES = 64;
  localparam int unsigned SCRATCH_BANKS_PER_GROUP = 4;

  // Derived: eight contiguous groups of four banks, 128 KiB each.
  localparam int unsigned SCRATCH_NUM_GROUPS = SCRATCH_NUM_BANKS / SCRATCH_BANKS_PER_GROUP;
  localparam int unsigned SCRATCH_GROUP_BYTES = SCRATCH_TOTAL_BYTES / SCRATCH_NUM_GROUPS;
  localparam int unsigned SCRATCH_ENTRIES_PER_STRIPE =
      SCRATCH_BANK_STRIPE_BYTES / SCRATCH_BYTES_PER_ENTRY;

  // Which of the 32 scratch_ram_intf_req[] ports serves this byte offset.
  // Offsets are relative to the base of the scratch window, so the group index
  // is just the high part of the offset.
  function automatic int unsigned smc_scratch_bank(input int unsigned offset);
    return SCRATCH_BANKS_PER_GROUP * (offset / SCRATCH_GROUP_BYTES)
         + ((offset / SCRATCH_BANK_STRIPE_BYTES) % SCRATCH_BANKS_PER_GROUP);
  endfunction

  // Which entry of that bank. address[16:8] concatenated with address[5:3],
  // written as arithmetic so it reads the same way as the bank function.
  function automatic int unsigned smc_scratch_entry(input int unsigned offset);
    return ((offset % SCRATCH_GROUP_BYTES)
              / (SCRATCH_BANK_STRIPE_BYTES * SCRATCH_BANKS_PER_GROUP))
             * SCRATCH_ENTRIES_PER_STRIPE
         + ((offset % SCRATCH_BANK_STRIPE_BYTES) / SCRATCH_BYTES_PER_ENTRY);
  endfunction

endpackage : smc_scratch_map_pkg
