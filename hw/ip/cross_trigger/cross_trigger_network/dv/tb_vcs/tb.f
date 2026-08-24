# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Cross Trigger Network Testbench file list

// Include paths
+incdir+${OCH_ROOT}/vendor/pulp-platform/axi/upstream/include

// RTL files
-f ${OCH_ROOT}/hw/comp/cross_trigger_network/tb_vcs/rtl.f

// Testbench
${OCH_ROOT}/hw/comp/cross_trigger_network/tb_vcs/tb_cross_trigger_network.sv
