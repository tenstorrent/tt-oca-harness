// Testbench File List for Entropy Source
// Use $OCH_ROOT environment variable for portability

// APB VIP Interface
$OCH_ROOT/hw/comp/entropy_source/tb_vcs/apb_vip/apb_intf.sv

// Reference Models
$OCH_ROOT/hw/comp/entropy_source/tb_vcs/models/ro/ro_cfg_if.sv
$OCH_ROOT/hw/comp/entropy_source/tb_vcs/models/ro/RO_Jitter_Model.sv
$OCH_ROOT/hw/comp/entropy_source/tb_vcs/models/ro/RO_Jitter_Array.sv
$OCH_ROOT/hw/comp/entropy_source/tb_vcs/models/decorrelator/decor_cfg_if.sv
$OCH_ROOT/hw/comp/entropy_source/tb_vcs/models/decorrelator/Serial_Decorrelator_RefModel.sv
$OCH_ROOT/hw/comp/entropy_source/tb_vcs/models/decorrelator/Decorrelator_Checker.sv
$OCH_ROOT/hw/comp/entropy_source/tb_vcs/models/compressor/compressor_cfg_if.sv
$OCH_ROOT/hw/comp/entropy_source/tb_vcs/models/compressor/Entropy_Compressor_RefModel.sv
$OCH_ROOT/hw/comp/entropy_source/tb_vcs/models/compressor/Compressor_Checker.sv

// Testbench files
$OCH_ROOT/hw/comp/entropy_source/tb_vcs/tb_entropy_top.sv
