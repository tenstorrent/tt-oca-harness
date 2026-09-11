verdiSetActWin -dock widgetDock_<Decl._Tree>
wvCreateWindow
wvSetPosition -win $_nWave2 {("G1" 0)}
wvOpenFile -win $_nWave2 \
           {/proj_soc/user_dev/gchang/tt-oca-harness3/hw/sys/sep/dv/build/runs/20260909_205540__vcs__sep_efuse_token_match_fault_pic_test/sep_efuse_token_match_fault_pic_test/waves/sep_efuse_token_match_fault_pic_test.fsdb}
verdiSetActWin -win $_nWave2
verdiWindowResize -win $_Verdi_1 "414" "69" "900" "700"
verdiSetActWin -dock widgetDock_MTB_SOURCE_TAB_1
verdiSetActWin -win $_nWave2
wvGetSignalOpen -win $_nWave2
wvGetSignalSetScope -win $_nWave2 "/sep_uvm_top"
wvGetSignalSetScope -win $_nWave2 \
           "/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_lc_state_jtag_dec"
wvGetSignalSetScope -win $_nWave2 \
           "/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token/u_fault_comparator_collapse_d0nt_touch"
wvSetPosition -win $_nWave2 {("G1" 5)}
wvSetPosition -win $_nWave2 {("G1" 5)}
wvAddSignal -win $_nWave2 -clear
wvAddSignal -win $_nWave2 -group {"G1" \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token/u_fault_comparator_collapse_d0nt_touch/in0_i} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token/u_fault_comparator_collapse_d0nt_touch/in1_i} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token/u_fault_comparator_collapse_d0nt_touch/in2_i} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token/u_fault_comparator_collapse_d0nt_touch/in3_i} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token/u_fault_comparator_collapse_d0nt_touch/out_o} -height 16 \
}
wvAddSignal -win $_nWave2 -group {"G2" \
}
wvSelectSignal -win $_nWave2 {( "G1" 1 2 3 4 5 )} 
wvSetPosition -win $_nWave2 {("G1" 5)}
wvSetPosition -win $_nWave2 {("G1" 5)}
wvSetPosition -win $_nWave2 {("G1" 5)}
wvAddSignal -win $_nWave2 -clear
wvAddSignal -win $_nWave2 -group {"G1" \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token/u_fault_comparator_collapse_d0nt_touch/in0_i} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token/u_fault_comparator_collapse_d0nt_touch/in1_i} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token/u_fault_comparator_collapse_d0nt_touch/in2_i} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token/u_fault_comparator_collapse_d0nt_touch/in3_i} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token/u_fault_comparator_collapse_d0nt_touch/out_o} -height 16 \
}
wvAddSignal -win $_nWave2 -group {"G2" \
}
wvSelectSignal -win $_nWave2 {( "G1" 1 2 3 4 5 )} 
wvSetPosition -win $_nWave2 {("G1" 5)}
wvGetSignalClose -win $_nWave2
wvSelectSignal -win $_nWave2 {( "G1" 1 )} 
wvZoom -win $_nWave2 0.000000 544991250.347598
wvSetCursor -win $_nWave2 12060663.908107
wvSetCursor -win $_nWave2 8291706.436824
wvSearchPrev -win $_nWave2
verdiWindowResize -win $_Verdi_1 "414" "69" "1061" "700"
wvSearchNext -win $_nWave2
wvSearchNext -win $_nWave2
wvSearchNext -win $_nWave2
wvSearchNext -win $_nWave2
wvSearchNext -win $_nWave2
wvSearchPrev -win $_nWave2
wvSearchPrev -win $_nWave2
wvSelectSignal -win $_nWave2 {( "G1" 2 )} 
wvSearchNext -win $_nWave2
wvSearchNext -win $_nWave2
wvSearchNext -win $_nWave2
wvSearchNext -win $_nWave2
wvSelectSignal -win $_nWave2 {( "G1" 3 )} 
wvSearchNext -win $_nWave2
wvSearchNext -win $_nWave2
wvSearchNext -win $_nWave2
wvSearchPrev -win $_nWave2
wvSearchPrev -win $_nWave2
wvSearchPrev -win $_nWave2
wvSelectSignal -win $_nWave2 {( "G1" 2 )} 
wvSearchNext -win $_nWave2
wvSearchNext -win $_nWave2
wvSearchNext -win $_nWave2
wvSearchNext -win $_nWave2
wvSearchNext -win $_nWave2
wvSearchPrev -win $_nWave2
wvSearchPrev -win $_nWave2
wvSearchPrev -win $_nWave2
wvSelectSignal -win $_nWave2 {( "G1" 4 )} 
wvSearchNext -win $_nWave2
wvSearchNext -win $_nWave2
wvSearchPrev -win $_nWave2
wvSearchPrev -win $_nWave2
wvSelectSignal -win $_nWave2 {( "G1" 5 )} 
wvSearchNext -win $_nWave2
wvSearchNext -win $_nWave2
wvSearchPrev -win $_nWave2
wvSearchPrev -win $_nWave2
wvSearchPrev -win $_nWave2
wvGetSignalOpen -win $_nWave2
wvGetSignalSetScope -win $_nWave2 "/sep_uvm_top"
wvGetSignalSetScope -win $_nWave2 "/sep_uvm_top/u_dut"
wvGetSignalSetScope -win $_nWave2 "/sep_uvm_top/u_dut/u_sep"
wvGetSignalSetScope -win $_nWave2 "/sep_uvm_top/u_dut/u_sep/sep_crypto"
wvGetSignalSetScope -win $_nWave2 \
           "/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper"
wvGetSignalSetScope -win $_nWave2 \
           "/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller"
wvGetSignalSetScope -win $_nWave2 \
           "/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg"
wvGetSignalSetScope -win $_nWave2 \
           "/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing"
wvGetSignalSetScope -win $_nWave2 \
           "/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token"
wvGetSignalSetScope -win $_nWave2 \
           "/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token/u_fault_comparator_collapse_d0nt_touch"
wvGetSignalSetScope -win $_nWave2 \
           "/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing"
wvGetSignalSetScope -win $_nWave2 \
           "/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token"
wvSetPosition -win $_nWave2 {("G1" 9)}
wvSetPosition -win $_nWave2 {("G1" 9)}
wvAddSignal -win $_nWave2 -clear
wvAddSignal -win $_nWave2 -group {"G1" \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token/u_fault_comparator_collapse_d0nt_touch/in0_i} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token/u_fault_comparator_collapse_d0nt_touch/in1_i} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token/u_fault_comparator_collapse_d0nt_touch/in2_i} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token/u_fault_comparator_collapse_d0nt_touch/in3_i} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token/u_fault_comparator_collapse_d0nt_touch/out_o} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token/fault_comparator_collapse} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token/match_n\[2:0\]} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token/match_p\[2:0\]} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token/pair_bad\[2:0\]} -height 16 \
}
wvAddSignal -win $_nWave2 -group {"G2" \
}
wvSelectSignal -win $_nWave2 {( "G1" 6 7 8 9 )} 
wvSetPosition -win $_nWave2 {("G1" 9)}
wvSetPosition -win $_nWave2 {("G1" 9)}
wvSetPosition -win $_nWave2 {("G1" 9)}
wvAddSignal -win $_nWave2 -clear
wvAddSignal -win $_nWave2 -group {"G1" \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token/u_fault_comparator_collapse_d0nt_touch/in0_i} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token/u_fault_comparator_collapse_d0nt_touch/in1_i} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token/u_fault_comparator_collapse_d0nt_touch/in2_i} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token/u_fault_comparator_collapse_d0nt_touch/in3_i} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token/u_fault_comparator_collapse_d0nt_touch/out_o} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token/fault_comparator_collapse} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token/match_n\[2:0\]} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token/match_p\[2:0\]} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token/pair_bad\[2:0\]} -height 16 \
}
wvAddSignal -win $_nWave2 -group {"G2" \
}
wvSelectSignal -win $_nWave2 {( "G1" 6 7 8 9 )} 
wvSetPosition -win $_nWave2 {("G1" 9)}
wvGetSignalClose -win $_nWave2
wvSelectGroup -win $_nWave2 {G2}
wvSelectSignal -win $_nWave2 {( "G1" 8 )} 
wvSelectSignal -win $_nWave2 {( "G1" 9 )} 
wvSelectSignal -win $_nWave2 {( "G1" 9 )} 
wvExpandBus -win $_nWave2
wvSelectSignal -win $_nWave2 {( "G1" 1 )} 
wvSelectSignal -win $_nWave2 {( "G1" 1 2 3 4 5 6 7 8 9 10 11 12 )} 
wvCut -win $_nWave2
wvSetPosition -win $_nWave2 {("G1" 0)}
wvGetSignalOpen -win $_nWave2
wvGetSignalSetScope -win $_nWave2 "/sep_uvm_top"
wvGetSignalSetScope -win $_nWave2 "/sep_uvm_top/u_dut"
wvGetSignalSetScope -win $_nWave2 "/sep_uvm_top/u_dut/u_sep"
wvGetSignalSetScope -win $_nWave2 "/sep_uvm_top/u_dut/u_sep/sep_crypto"
wvGetSignalSetScope -win $_nWave2 \
           "/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper"
wvGetSignalSetScope -win $_nWave2 \
           "/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller"
wvGetSignalSetScope -win $_nWave2 \
           "/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg"
wvGetSignalSetScope -win $_nWave2 \
           "/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing"
wvGetSignalSetScope -win $_nWave2 \
           "/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token"
wvGetSignalSetScope -win $_nWave2 \
           "/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token/u_fault_comparator_collapse_d0nt_touch"
wvGetSignalSetScope -win $_nWave2 \
           "/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_rma_sip_token"
wvGetSignalSetScope -win $_nWave2 \
           "/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_sec_disable_token/u_fault_comparator_collapse_d0nt_touch"
wvSetPosition -win $_nWave2 {("G1" 5)}
wvSetPosition -win $_nWave2 {("G1" 5)}
wvAddSignal -win $_nWave2 -clear
wvAddSignal -win $_nWave2 -group {"G1" \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_sec_disable_token/u_fault_comparator_collapse_d0nt_touch/in0_i} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_sec_disable_token/u_fault_comparator_collapse_d0nt_touch/in1_i} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_sec_disable_token/u_fault_comparator_collapse_d0nt_touch/in2_i} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_sec_disable_token/u_fault_comparator_collapse_d0nt_touch/in3_i} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_sec_disable_token/u_fault_comparator_collapse_d0nt_touch/out_o} -height 16 \
}
wvAddSignal -win $_nWave2 -group {"G2" \
}
wvSelectSignal -win $_nWave2 {( "G1" 1 2 3 4 5 )} 
wvSetPosition -win $_nWave2 {("G1" 5)}
wvGetSignalSetScope -win $_nWave2 \
           "/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_sec_disable_token"
wvSetPosition -win $_nWave2 {("G1" 9)}
wvSetPosition -win $_nWave2 {("G1" 9)}
wvAddSignal -win $_nWave2 -clear
wvAddSignal -win $_nWave2 -group {"G1" \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_sec_disable_token/u_fault_comparator_collapse_d0nt_touch/in0_i} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_sec_disable_token/u_fault_comparator_collapse_d0nt_touch/in1_i} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_sec_disable_token/u_fault_comparator_collapse_d0nt_touch/in2_i} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_sec_disable_token/u_fault_comparator_collapse_d0nt_touch/in3_i} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_sec_disable_token/u_fault_comparator_collapse_d0nt_touch/out_o} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_sec_disable_token/fault_comparator_collapse} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_sec_disable_token/match_n\[2:0\]} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_sec_disable_token/match_p\[2:0\]} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_sec_disable_token/pair_bad\[2:0\]} -height 16 \
}
wvAddSignal -win $_nWave2 -group {"G2" \
}
wvSelectSignal -win $_nWave2 {( "G1" 6 7 8 9 )} 
wvSetPosition -win $_nWave2 {("G1" 9)}
wvSetPosition -win $_nWave2 {("G1" 9)}
wvSetPosition -win $_nWave2 {("G1" 9)}
wvAddSignal -win $_nWave2 -clear
wvAddSignal -win $_nWave2 -group {"G1" \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_sec_disable_token/u_fault_comparator_collapse_d0nt_touch/in0_i} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_sec_disable_token/u_fault_comparator_collapse_d0nt_touch/in1_i} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_sec_disable_token/u_fault_comparator_collapse_d0nt_touch/in2_i} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_sec_disable_token/u_fault_comparator_collapse_d0nt_touch/in3_i} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_sec_disable_token/u_fault_comparator_collapse_d0nt_touch/out_o} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_sec_disable_token/fault_comparator_collapse} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_sec_disable_token/match_n\[2:0\]} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_sec_disable_token/match_p\[2:0\]} -height 16 \
{/sep_uvm_top/u_dut/u_sep/sep_crypto/u_sep_efuse_wrapper/u_efuse_interface_controller/gen_mmr_reg/u_efuse_token_processing/u_triple_redundant_comparator_sec_disable_token/pair_bad\[2:0\]} -height 16 \
}
wvAddSignal -win $_nWave2 -group {"G2" \
}
wvSelectSignal -win $_nWave2 {( "G1" 6 7 8 9 )} 
wvSetPosition -win $_nWave2 {("G1" 9)}
wvGetSignalClose -win $_nWave2
wvSelectSignal -win $_nWave2 {( "G1" 6 )} 
wvSearchPrev -win $_nWave2
wvSearchNext -win $_nWave2
wvSearchNext -win $_nWave2
wvSearchNext -win $_nWave2
wvSearchNext -win $_nWave2
wvSetCursor -win $_nWave2 6021979.884149
wvSearchNext -win $_nWave2
wvSearchNext -win $_nWave2
wvSearchNext -win $_nWave2
wvSearchNext -win $_nWave2
wvSearchNext -win $_nWave2
wvSearchNext -win $_nWave2
wvSearchNext -win $_nWave2
wvSearchNext -win $_nWave2
wvSearchNext -win $_nWave2
wvSearchPrev -win $_nWave2
wvSearchPrev -win $_nWave2
wvSearchPrev -win $_nWave2
wvSearchNext -win $_nWave2
wvSearchNext -win $_nWave2
wvSearchNext -win $_nWave2
wvSearchNext -win $_nWave2
wvSearchPrev -win $_nWave2
wvSearchPrev -win $_nWave2
wvSearchNext -win $_nWave2
wvSearchNext -win $_nWave2
wvSearchNext -win $_nWave2
wvSetWindowTimeUnit -win $_nWave2 1.000000 ns
wvSelectSignal -win $_nWave2 {( "G1" 9 )} 
wvExpandBus -win $_nWave2
wvSelectSignal -win $_nWave2 {( "G1" 8 )} 
wvSetPosition -win $_nWave2 {("G1" 8)}
wvExpandBus -win $_nWave2
wvSetPosition -win $_nWave2 {("G1" 15)}
wvSelectSignal -win $_nWave2 {( "G1" 7 )} 
wvSetPosition -win $_nWave2 {("G1" 7)}
wvExpandBus -win $_nWave2
wvSetPosition -win $_nWave2 {("G1" 18)}
wvSetCursor -win $_nWave2 32357.512990 -snap {("G2" 0)}
verdiWindowResize -win $_Verdi_1 "313" "120" "1061" "700"
wvScrollDown -win $_nWave2 1
wvScrollDown -win $_nWave2 1
wvScrollDown -win $_nWave2 1
wvScrollDown -win $_nWave2 0
wvScrollDown -win $_nWave2 0
wvScrollDown -win $_nWave2 0
wvScrollDown -win $_nWave2 0
wvScrollDown -win $_nWave2 0
wvScrollDown -win $_nWave2 0
wvScrollDown -win $_nWave2 0
wvScrollDown -win $_nWave2 0
wvScrollDown -win $_nWave2 0
wvScrollDown -win $_nWave2 0
wvScrollDown -win $_nWave2 0
wvScrollDown -win $_nWave2 0
wvScrollDown -win $_nWave2 0
wvScrollUp -win $_nWave2 1
wvScrollUp -win $_nWave2 1
wvScrollUp -win $_nWave2 1
wvScrollDown -win $_nWave2 0
wvScrollDown -win $_nWave2 0
verdiWindowResize -win $_Verdi_1 "595" "175" "1061" "700"
verdiSetActWin -dock widgetDock_MTB_SOURCE_TAB_1
wvScrollDown -win $_nWave2 1
wvScrollDown -win $_nWave2 1
wvScrollDown -win $_nWave2 1
wvScrollUp -win $_nWave2 1
wvScrollDown -win $_nWave2 1
wvScrollUp -win $_nWave2 1
wvScrollDown -win $_nWave2 1
wvScrollDown -win $_nWave2 0
wvScrollUp -win $_nWave2 1
wvScrollUp -win $_nWave2 1
wvScrollDown -win $_nWave2 1
wvScrollUp -win $_nWave2 1
wvScrollDown -win $_nWave2 1
wvScrollDown -win $_nWave2 1
wvScrollUp -win $_nWave2 1
wvScrollUp -win $_nWave2 1
verdiWindowResize -win $_Verdi_1 "388" "289" "1061" "700"
