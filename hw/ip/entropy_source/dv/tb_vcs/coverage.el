// Coverage Exclusion List for Entropy Source VCS Testbench
// This file specifies modules/instances to exclude from coverage collection

// Exclude testbench top-level (we only want DUT coverage)
instance { tb_entropy_top }

// Exclude reference models (behavioral models, not part of DUT)
module { RO_Jitter_Array }
module { ro_model_jitter }
module { Serial_Decorrelator_RefModel }
module { Entropy_Compressor_RefModel }

// Exclude checkers (verification components, not DUT)
module { Decorrelator_Checker }
module { Compressor_Checker }
