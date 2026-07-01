// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//Description : This module recieves Virtual ID in decimal Format, Fuse Map as Multi-Hot Vector and returns Physical ID in Decimal Format

module dfd_rv_vidtopid
	#(
		parameter int NrHarts = 8,

		localparam int NrHartsIdx = (NrHarts == 1) ? 1 : $clog2(NrHarts)
	)
	(
		input  logic [NrHarts-1:0]                   fuse_map_i,   // Indexed by Physical ID
		input  logic [NrHarts-1:0] [NrHartsIdx-1:0]  vid_map_i,    // Indexed by Physical PID
		input  logic [NrHartsIdx-1:0]                vid_i,
		input  logic [NrHarts-1:0]                   vid_vector_i, // Indexed by Virtual ID

		output logic [NrHartsIdx-1:0]                pid_o,
		output logic [NrHarts-1:0]                   pid_vector_o, // Indexed by PID
		output logic                                 map_avail_o   // 0: Not Mapped to Any PID , 1: Mapped to a valid PID
	);

	typedef struct packed {
		logic [NrHartsIdx-1:0]  pid;
		logic                   mapped;
	} vidtopid_t;

	vidtopid_t  [NrHarts-1:0]  VIdToPId; //Indexed by Logical ID
	logic [NrHartsIdx:0]       pid;

	always_comb begin
		pid      = '0;
		VIdToPId = '0;
		for (int i = 0 ; i < NrHarts; i++) begin
			if (fuse_map_i[i]) begin
				VIdToPId[vid_map_i[i]].pid    = (NrHartsIdx)'(i);
				VIdToPId[vid_map_i[i]].mapped = '1;
			end
		end
	end

	always_comb begin
		pid_vector_o = '0;
		for (int k = 0; k < NrHarts ; k++) begin
			if (VIdToPId[k].mapped) begin
				pid_vector_o[VIdToPId[k].pid] = VIdToPId[k].mapped ? vid_vector_i[k] : '0;
			end
		end
	end

	// NOTE: For 8 Harts , Max Lols : 28 which should be fine to meeting 2.6GHz Timing, optimize later if needed
	assign pid_o       = VIdToPId[vid_i].pid;
	assign map_avail_o = VIdToPId[vid_i].mapped;

endmodule
