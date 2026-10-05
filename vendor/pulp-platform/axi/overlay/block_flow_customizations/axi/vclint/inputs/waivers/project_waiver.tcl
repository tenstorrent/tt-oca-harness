# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

waive_violation -add {STARC05-2_10_6_1_4}  -comment {Created by nxu on 15-Sep-2025; Third party IP.}  -filter {(FileName =~ "*axi_pkg.sv") AND (LHS_Size == "128") AND (LHSExpr == "ret_addr") AND (RHS_Size == "128") AND (RHSExpr == "(aligned_addr(addr,size) + (i_beat * num_bytes(size)))")}  -app { lint } -tag { STARC05-2.10.6.1 } -user { nxu } -timestamp { 15-09-2025 12:39:25 }