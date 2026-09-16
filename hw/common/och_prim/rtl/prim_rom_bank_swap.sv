// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// ROM Bank Swap Module
//
//--------------------------------------------------
module prim_rom_bank_swap (
  // 5-bit control signal for bank swapping
  input logic [4:0] rom_bank_swap_i,

  // Outputs representing the potentially swapped ROM index for each position
  // Each output indicates which original ROM (0, 1, 2, or 3) should map
  // to this logical position, using a zero-hot style encoding.
  output logic [3:0] rom0_index,
  output logic [3:0] rom1_index,
  output logic [3:0] rom2_index,
  output logic [3:0] rom3_index
);

  // Define fixed identifiers for the original ROM banks
  // Using zero-hot makes downstream decoding potentially easier
  localparam logic [3:0] ROM0_ID = 4'b1110;
  localparam logic [3:0] ROM1_ID = 4'b1101;
  localparam logic [3:0] ROM2_ID = 4'b1011;
  localparam logic [3:0] ROM3_ID = 4'b0111;

  // Combinational logic to select ROM bank order based on i_rom_bank_swap
  always_comb begin
    // Default assignment (covers the default case and undefined swap codes)
    rom0_index = ROM0_ID;
    rom1_index = ROM1_ID;
    rom2_index = ROM2_ID;
    rom3_index = ROM3_ID;

    // Use a case statement to map swap code to permutation
    // 4! = 24 permutations
    case (rom_bank_swap_i)
      // --- Group 0: ROM 0 is first ---
      5'b00000: begin  // Order: 0, 1, 2, 3 (No Swap - Default)
        rom0_index = ROM0_ID;
        rom1_index = ROM1_ID;
        rom2_index = ROM2_ID;
        rom3_index = ROM3_ID;
      end
      5'b00001: begin  // Order: 0, 1, 3, 2 (Swap 2, 3)
        rom0_index = ROM0_ID;
        rom1_index = ROM1_ID;
        rom2_index = ROM3_ID;  // Real pos 2 gets data from original ROM 3
        rom3_index = ROM2_ID;  // Real pos 3 gets data from original ROM 2
      end
      5'b00010: begin  // Order: 0, 2, 1, 3 (Swap 1, 2)
        rom0_index = ROM0_ID;
        rom1_index = ROM2_ID;
        rom2_index = ROM1_ID;
        rom3_index = ROM3_ID;
      end
      5'b00011: begin  // Order: 0, 2, 3, 1 (Rotate 1, 2, 3 left)
        rom0_index = ROM0_ID;
        rom1_index = ROM2_ID;
        rom2_index = ROM3_ID;
        rom3_index = ROM1_ID;
      end
      5'b00100: begin  // Order: 0, 3, 1, 2 (Rotate 1, 2, 3 right)
        rom0_index = ROM0_ID;
        rom1_index = ROM3_ID;
        rom2_index = ROM1_ID;
        rom3_index = ROM2_ID;
      end
      5'b00101: begin  // Order: 0, 3, 2, 1 (Swap 1, 3)
        rom0_index = ROM0_ID;
        rom1_index = ROM3_ID;
        rom2_index = ROM2_ID;
        rom3_index = ROM1_ID;
      end

      // --- Group 1: ROM 1 is first ---
      5'b00110: begin  // Order: 1, 0, 2, 3 (Swap 0, 1)
        rom0_index = ROM1_ID;  // Real pos 0 gets data from original ROM 1
        rom1_index = ROM0_ID;  // Real pos 1 gets data from original ROM 0
        rom2_index = ROM2_ID;
        rom3_index = ROM3_ID;
      end
      5'b00111: begin  // Order: 1, 0, 3, 2 (Swap 0,1; Swap 2,3)
        rom0_index = ROM1_ID;
        rom1_index = ROM0_ID;
        rom2_index = ROM3_ID;
        rom3_index = ROM2_ID;
      end
      5'b01000: begin  // Order: 1, 2, 0, 3 (Swap 0,1; Swap 0,2 -> Rotate 0,1,2 left)
        rom0_index = ROM1_ID;
        rom1_index = ROM2_ID;
        rom2_index = ROM0_ID;
        rom3_index = ROM3_ID;
      end
      5'b01001: begin  // Order: 1, 2, 3, 0 (Rotate all left)
        rom0_index = ROM1_ID;
        rom1_index = ROM2_ID;
        rom2_index = ROM3_ID;
        rom3_index = ROM0_ID;
      end
      5'b01010: begin  // Order: 1, 3, 0, 2
        rom0_index = ROM1_ID;
        rom1_index = ROM3_ID;
        rom2_index = ROM0_ID;
        rom3_index = ROM2_ID;
      end
      5'b01011: begin  // Order: 1, 3, 2, 0 (Swap 0,1; Swap 0,3 -> Rotate 0,1,3 left)
        rom0_index = ROM1_ID;
        rom1_index = ROM3_ID;
        rom2_index = ROM2_ID;
        rom3_index = ROM0_ID;
      end

      // --- Group 2: ROM 2 is first ---
      5'b01100: begin  // Order: 2, 0, 1, 3
        rom0_index = ROM2_ID;
        rom1_index = ROM0_ID;
        rom2_index = ROM1_ID;
        rom3_index = ROM3_ID;
      end
      5'b01101: begin  // Order: 2, 0, 3, 1
        rom0_index = ROM2_ID;
        rom1_index = ROM0_ID;
        rom2_index = ROM3_ID;
        rom3_index = ROM1_ID;
      end
      5'b01110: begin  // Order: 2, 1, 0, 3 (Swap 0, 2)
        rom0_index = ROM2_ID;
        rom1_index = ROM1_ID;
        rom2_index = ROM0_ID;
        rom3_index = ROM3_ID;
      end
      5'b01111: begin  // Order: 2, 1, 3, 0
        rom0_index = ROM2_ID;
        rom1_index = ROM1_ID;
        rom2_index = ROM3_ID;
        rom3_index = ROM0_ID;
      end
      5'b10000: begin  // Order: 2, 3, 0, 1 (Rotate 0,1; Rotate 0,2,3)
        rom0_index = ROM2_ID;
        rom1_index = ROM3_ID;
        rom2_index = ROM0_ID;
        rom3_index = ROM1_ID;
      end
      5'b10001: begin  // Order: 2, 3, 1, 0 (Swap 0,2; Swap 1,3)
        rom0_index = ROM2_ID;
        rom1_index = ROM3_ID;
        rom2_index = ROM1_ID;
        rom3_index = ROM0_ID;
      end

      // --- Group 3: ROM 3 is first ---
      5'b10010: begin  // Order: 3, 0, 1, 2
        rom0_index = ROM3_ID;
        rom1_index = ROM0_ID;
        rom2_index = ROM1_ID;
        rom3_index = ROM2_ID;
      end
      5'b10011: begin  // Order: 3, 0, 2, 1 (Swap 0,3; Swap 1,2)
        rom0_index = ROM3_ID;
        rom1_index = ROM0_ID;
        rom2_index = ROM2_ID;
        rom3_index = ROM1_ID;
      end
      5'b10100: begin  // Order: 3, 1, 0, 2
        rom0_index = ROM3_ID;
        rom1_index = ROM1_ID;
        rom2_index = ROM0_ID;
        rom3_index = ROM2_ID;
      end
      5'b10101: begin  // Order: 3, 1, 2, 0 (Swap 0, 3)
        rom0_index = ROM3_ID;
        rom1_index = ROM1_ID;
        rom2_index = ROM2_ID;
        rom3_index = ROM0_ID;
      end
      5'b10110: begin  // Order: 3, 2, 0, 1 (Swap 0,3; Swap 0,2 -> Rotate 0,3,2 left)
        rom0_index = ROM3_ID;
        rom1_index = ROM2_ID;
        rom2_index = ROM0_ID;
        rom3_index = ROM1_ID;
      end
      5'b10111: begin  // Order: 3, 2, 1, 0 (Rotate all right)
        rom0_index = ROM3_ID;
        rom1_index = ROM2_ID;
        rom2_index = ROM1_ID;
        rom3_index = ROM0_ID;
      end

      // Default case for any swap codes >= 24 (5'b11000 to 5'b11111)
      // or if rom_bank_swap_i contains X or Z
      default: begin
        rom0_index = ROM0_ID;
        rom1_index = ROM1_ID;
        rom2_index = ROM2_ID;
        rom3_index = ROM3_ID;
      end
    endcase
  end

endmodule
