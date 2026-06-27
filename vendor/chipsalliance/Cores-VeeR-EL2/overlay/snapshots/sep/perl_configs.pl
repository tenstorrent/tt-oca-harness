#  NOTE NOTE NOTE NOTE NOTE NOTE NOTE NOTE NOTE NOTE NOTE NOTE NOTE NOTE NOTE NOTE
#  This is an automatically generated file by aottaviano on Tue Jun 23 16:39:00 EDT 2026
# 
#  cmd:    veer -snapshot=sep -set=user_mode=1 -set=btb_enabled=0 -set=bht_size=32 -set=dccm_enable=1 -set=dccm_num_banks=2 -set=dccm_region=0xC -set=dccm_offset=0x0004_0000 -set=dccm_size=128 -set=dma_buf_depth=4 -set=dma_bus_tag=6 -set=fast_interrupt_redirect=1 -set=icache_enable=0 -set=iccm_enable=1 -set=iccm_region=0xC -set=iccm_offset=0x0000_0000 -set=iccm_size=256 -set=iccm_num_banks=4 -set=lsu_stbuf_depth=4 -set=lsu_num_nbload=4 -set=load_to_use_plus1=0 -set=pic_2cycle=1 -set=pic_region=0xC -set=pic_offset=0x0008_0000 -set=pic_size=32 -set=pic_total_int=255 -set=dma_buf_depth=4 -set=timer_legal_en=1 -set=bitmanip_zba=1 -set=bitmanip_zbb=1 -set=bitmanip_zbc=1 -set=bitmanip_zbe=1 -set=bitmanip_zbf=0 -set=bitmanip_zbp=0 -set=bitmanip_zbr=0 -set=bitmanip_zbs=0 -set=fpga_optimize=0 -set=text_in_iccm=1 -set=pmp_entries=16 -set=smepmp=1 -set=lockstep_enable=0 -set=lockstep_regfile_enable=0 -set=inst_access_enable0=1 -set=inst_access_addr0=0x10000000 -set=inst_access_mask0=0x0003ffff -set=inst_access_enable1=1 -set=inst_access_addr1=0x10400000 -set=inst_access_mask1=0x0000ffff 
# 
# To use this in a perf script, use 'require $RV_ROOT/configs/config.pl'
# Reference the hash via $config{name}..


%config = (
            'dccm' => {
                        'dccm_bits' => 17,
                        'lsu_sb_bits' => 17,
                        'dccm_data_width' => 32,
                        'dccm_eadr' => '0xc005ffff',
                        'dccm_enable' => '1',
                        'dccm_data_cell' => 'ram_16384x39',
                        'dccm_num_banks_2' => '',
                        'dccm_size_128' => '',
                        'dccm_byte_width' => '4',
                        'dccm_size' => 128,
                        'dccm_offset' => '0x0004_0000',
                        'dccm_reserved' => '0x1400',
                        'dccm_sadr' => '0xc0040000',
                        'dccm_width_bits' => 2,
                        'dccm_index_bits' => 14,
                        'dccm_num_banks' => '2',
                        'dccm_bank_bits' => 1,
                        'dccm_rows' => '16384',
                        'dccm_ecc_width' => 7,
                        'dccm_fdata_width' => 39,
                        'dccm_region' => '0xC'
                      },
            'retstack' => {
                            'ret_stack_size' => '8'
                          },
            'num_mmode_perf_regs' => '4',
            'triggers' => [
                            {
                              'poke_mask' => [
                                               '0x081818c7',
                                               '0xffffffff',
                                               '0x00000000'
                                             ],
                              'mask' => [
                                          '0x081818c7',
                                          '0xffffffff',
                                          '0x00000000'
                                        ],
                              'reset' => [
                                           '0x23e00000',
                                           '0x00000000',
                                           '0x00000000'
                                         ]
                            },
                            {
                              'poke_mask' => [
                                               '0x081810c7',
                                               '0xffffffff',
                                               '0x00000000'
                                             ],
                              'mask' => [
                                          '0x081810c7',
                                          '0xffffffff',
                                          '0x00000000'
                                        ],
                              'reset' => [
                                           '0x23e00000',
                                           '0x00000000',
                                           '0x00000000'
                                         ]
                            },
                            {
                              'reset' => [
                                           '0x23e00000',
                                           '0x00000000',
                                           '0x00000000'
                                         ],
                              'mask' => [
                                          '0x081818c7',
                                          '0xffffffff',
                                          '0x00000000'
                                        ],
                              'poke_mask' => [
                                               '0x081818c7',
                                               '0xffffffff',
                                               '0x00000000'
                                             ]
                            },
                            {
                              'reset' => [
                                           '0x23e00000',
                                           '0x00000000',
                                           '0x00000000'
                                         ],
                              'mask' => [
                                          '0x081810c7',
                                          '0xffffffff',
                                          '0x00000000'
                                        ],
                              'poke_mask' => [
                                               '0x081810c7',
                                               '0xffffffff',
                                               '0x00000000'
                                             ]
                            }
                          ],
            'protection' => {
                              'data_access_addr7' => '0x00000000',
                              'data_access_enable0' => '0x0',
                              'data_access_addr1' => '0x00000000',
                              'data_access_enable5' => '0x0',
                              'inst_access_addr5' => '0x00000000',
                              'inst_access_mask6' => '0xffffffff',
                              'inst_access_mask4' => '0xffffffff',
                              'inst_access_mask0' => '0x0003ffff',
                              'data_access_enable4' => '0x0',
                              'smepmp' => '1',
                              'data_access_addr3' => '0x00000000',
                              'data_access_enable6' => '0x0',
                              'inst_access_addr2' => '0x00000000',
                              'data_access_mask0' => '0xffffffff',
                              'inst_access_enable4' => '0x0',
                              'inst_access_addr3' => '0x00000000',
                              'inst_access_enable6' => '0x0',
                              'data_access_addr2' => '0x00000000',
                              'inst_access_enable0' => '1',
                              'inst_access_addr7' => '0x00000000',
                              'inst_access_addr1' => '0x10400000',
                              'inst_access_enable5' => '0x0',
                              'data_access_mask6' => '0xffffffff',
                              'data_access_addr5' => '0x00000000',
                              'pmp_entries' => '16',
                              'data_access_mask4' => '0xffffffff',
                              'data_access_enable1' => '0x0',
                              'inst_access_mask3' => '0xffffffff',
                              'inst_access_enable2' => '0x0',
                              'data_access_addr0' => '0x00000000',
                              'inst_access_enable3' => '0x0',
                              'inst_access_enable7' => '0x0',
                              'data_access_mask2' => '0xffffffff',
                              'inst_access_mask7' => '0xffffffff',
                              'inst_access_mask1' => '0x0000ffff',
                              'data_access_addr6' => '0x00000000',
                              'data_access_mask5' => '0xffffffff',
                              'data_access_addr4' => '0x00000000',
                              'data_access_mask7' => '0xffffffff',
                              'data_access_mask1' => '0xffffffff',
                              'inst_access_mask5' => '0xffffffff',
                              'inst_access_addr6' => '0x00000000',
                              'inst_access_addr4' => '0x00000000',
                              'inst_access_enable1' => '1',
                              'data_access_mask3' => '0xffffffff',
                              'data_access_enable2' => '0x0',
                              'data_access_enable3' => '0x0',
                              'data_access_enable7' => '0x0',
                              'inst_access_addr0' => '0x10000000',
                              'inst_access_mask2' => '0xffffffff'
                            },
            'regwidth' => '32',
            'testbench' => {
                             'build_axi4' => 1,
                             'SDVT_AHB' => '0',
                             'clock_period' => '100',
                             'sterr_rollback' => '0',
                             'TOP' => 'tb_top',
                             'ext_addrwidth' => '32',
                             'CPU_TOP' => '`RV_TOP.veer',
                             'RV_TOP' => '`TOP.rvtop_wrapper.rvtop',
                             'build_axi_native' => 1,
                             'ext_datawidth' => '64',
                             'lderr_rollback' => '1'
                           },
            'xlen' => 32,
            'tec_rv_icg' => 'clockhdr',
            'numiregs' => '32',
            'btb' => {
                       'btb_size' => 512,
                       'btb_toffset_size' => '12',
                       'btb_btag_size' => 5,
                       'btb_addr_lo' => '2',
                       'btb_fold2_index_hash' => 0,
                       'btb_array_depth' => 256,
                       'btb_index3_hi' => 25,
                       'btb_index2_hi' => 17,
                       'btb_enable' => '1',
                       'btb_index1_lo' => '2',
                       'btb_index1_hi' => 9,
                       'btb_btag_fold' => 0,
                       'btb_index3_lo' => 18,
                       'btb_index2_lo' => 10,
                       'btb_addr_hi' => 9
                     },
            'config_key' => '32\'hdeadbeef',
            'user_ec_rv_icg' => 'user_clock_gate',
            'iccm' => {
                        'iccm_num_banks' => '4',
                        'iccm_ecc_width' => '7',
                        'iccm_bank_bits' => 2,
                        'iccm_rows' => '16384',
                        'iccm_region' => '0xC',
                        'iccm_bank_hi' => 3,
                        'iccm_offset' => '0x0000_0000',
                        'iccm_bank_index_lo' => 4,
                        'iccm_size' => 256,
                        'iccm_reserved' => '0x1000',
                        'iccm_index_bits' => 14,
                        'iccm_sadr' => '0xc0000000',
                        'iccm_data_cell' => 'ram_16384x39',
                        'iccm_num_banks_4' => '',
                        'iccm_size_256' => '',
                        'iccm_bits' => 18,
                        'iccm_eadr' => '0xc003ffff',
                        'iccm_enable' => 1
                      },
            'pic' => {
                       'pic_total_int_plus1' => 256,
                       'pic_meipt_mask' => '0x0',
                       'pic_meigwclr_offset' => '0x5000',
                       'pic_meigwctrl_mask' => '0x3',
                       'pic_meigwctrl_offset' => '0x4000',
                       'pic_region' => '0xC',
                       'pic_meie_offset' => '0x2000',
                       'pic_meipt_count' => 255,
                       'pic_bits' => 15,
                       'pic_mpiccfg_offset' => '0x3000',
                       'pic_meip_offset' => '0x1000',
                       'pic_meipt_offset' => '0x3004',
                       'pic_size' => 32,
                       'pic_mpiccfg_count' => 1,
                       'pic_total_int' => 255,
                       'pic_meipl_mask' => '0xf',
                       'pic_meigwclr_count' => 255,
                       'pic_meie_count' => 255,
                       'pic_meie_mask' => '0x1',
                       'pic_2cycle' => '1',
                       'pic_base_addr' => '0xc0080000',
                       'pic_int_words' => 8,
                       'pic_mpiccfg_mask' => '0x1',
                       'pic_offset' => '0x0008_0000',
                       'pic_meigwclr_mask' => '0x0',
                       'pic_meip_count' => 8,
                       'pic_meip_mask' => '0x0',
                       'pic_meipl_offset' => '0x0000',
                       'pic_meigwctrl_count' => 255,
                       'pic_meipl_count' => 255
                     },
            'bht' => {
                       'bht_addr_lo' => '2',
                       'bht_hash_string' => '{hashin[4+1:2]^ghr[4-1:0]}// cf2',
                       'bht_addr_hi' => 5,
                       'bht_size' => 32,
                       'bht_ghr_range' => '3:0',
                       'bht_array_depth' => 16,
                       'bht_ghr_size' => 4,
                       'bht_ghr_hash_1' => ''
                     },
            'csr' => {
                       'mscause' => {
                                      'number' => '0x7ff',
                                      'exists' => 'true',
                                      'mask' => '0x0000000f',
                                      'reset' => '0x0'
                                    },
                       'mhpmcounter4' => {
                                           'exists' => 'true',
                                           'mask' => '0xffffffff',
                                           'reset' => '0x0'
                                         },
                       'mhpmevent6' => {
                                         'reset' => '0x0',
                                         'mask' => '0xffffffff',
                                         'exists' => 'true'
                                       },
                       'mhpmevent3' => {
                                         'exists' => 'true',
                                         'mask' => '0xffffffff',
                                         'reset' => '0x0'
                                       },
                       'mcgc' => {
                                   'exists' => 'true',
                                   'mask' => '0x000003ff',
                                   'reset' => '0x200',
                                   'number' => '0x7f8',
                                   'poke_mask' => '0x000003ff'
                                 },
                       'mrac' => {
                                   'number' => '0x7c0',
                                   'comment' => 'Memory region io and cache control.',
                                   'reset' => '0x0',
                                   'mask' => '0xffffffff',
                                   'exists' => 'true',
                                   'shared' => 'true'
                                 },
                       'instret' => {
                                      'exists' => 'false'
                                    },
                       'mie' => {
                                  'exists' => 'true',
                                  'mask' => '0x70000888',
                                  'reset' => '0x0'
                                },
                       'mhpmevent5' => {
                                         'exists' => 'true',
                                         'reset' => '0x0',
                                         'mask' => '0xffffffff'
                                       },
                       'mimpid' => {
                                     'mask' => '0x0',
                                     'reset' => '0x4',
                                     'exists' => 'true'
                                   },
                       'mfdht' => {
                                    'number' => '0x7ce',
                                    'comment' => 'Force Debug Halt Threshold',
                                    'exists' => 'true',
                                    'shared' => 'true',
                                    'mask' => '0x0000003f',
                                    'reset' => '0x0'
                                  },
                       'mitcnt0' => {
                                      'reset' => '0x0',
                                      'mask' => '0xffffffff',
                                      'exists' => 'true',
                                      'number' => '0x7d2'
                                    },
                       'dicawics' => {
                                       'reset' => '0x0',
                                       'mask' => '0x0130fffc',
                                       'comment' => 'Cache diagnostics.',
                                       'exists' => 'true',
                                       'number' => '0x7c8',
                                       'debug' => 'true'
                                     },
                       'mcpc' => {
                                   'reset' => '0x0',
                                   'mask' => '0x0',
                                   'comment' => 'Core pause',
                                   'exists' => 'true',
                                   'number' => '0x7c2'
                                 },
                       'dicago' => {
                                     'mask' => '0x0',
                                     'comment' => 'Cache diagnostics.',
                                     'reset' => '0x0',
                                     'exists' => 'true',
                                     'number' => '0x7cb',
                                     'debug' => 'true'
                                   },
                       'mhpmcounter6' => {
                                           'exists' => 'true',
                                           'reset' => '0x0',
                                           'mask' => '0xffffffff'
                                         },
                       'meicurpl' => {
                                       'mask' => '0xf',
                                       'comment' => 'External interrupt current priority level.',
                                       'reset' => '0x0',
                                       'exists' => 'true',
                                       'number' => '0xbcc'
                                     },
                       'mstatus' => {
                                      'exists' => 'true',
                                      'reset' => '0x1800',
                                      'mask' => '0x88'
                                    },
                       'mitcnt1' => {
                                      'exists' => 'true',
                                      'mask' => '0xffffffff',
                                      'reset' => '0x0',
                                      'number' => '0x7d5'
                                    },
                       'mhpmcounter5' => {
                                           'exists' => 'true',
                                           'reset' => '0x0',
                                           'mask' => '0xffffffff'
                                         },
                       'mhpmcounter3' => {
                                           'mask' => '0xffffffff',
                                           'reset' => '0x0',
                                           'exists' => 'true'
                                         },
                       'mhartid' => {
                                      'exists' => 'true',
                                      'reset' => '0x0',
                                      'mask' => '0x0',
                                      'poke_mask' => '0xfffffff0'
                                    },
                       'miccmect' => {
                                       'number' => '0x7f1',
                                       'mask' => '0xffffffff',
                                       'reset' => '0x0',
                                       'exists' => 'true'
                                     },
                       'dicad0' => {
                                     'number' => '0x7c9',
                                     'debug' => 'true',
                                     'mask' => '0xffffffff',
                                     'comment' => 'Cache diagnostics.',
                                     'reset' => '0x0',
                                     'exists' => 'true'
                                   },
                       'mhpmcounter4h' => {
                                            'reset' => '0x0',
                                            'mask' => '0xffffffff',
                                            'exists' => 'true'
                                          },
                       'mvendorid' => {
                                        'exists' => 'true',
                                        'reset' => '0x45',
                                        'mask' => '0x0'
                                      },
                       'time' => {
                                   'exists' => 'false'
                                 },
                       'mitbnd1' => {
                                      'exists' => 'true',
                                      'mask' => '0xffffffff',
                                      'reset' => '0xffffffff',
                                      'number' => '0x7d6'
                                    },
                       'mcounteren' => {
                                         'exists' => 'false'
                                       },
                       'mfdc' => {
                                   'number' => '0x7f9',
                                   'exists' => 'true',
                                   'mask' => '0x00071fff',
                                   'reset' => '0x00070040'
                                 },
                       'mcountinhibit' => {
                                            'exists' => 'true',
                                            'mask' => '0x7d',
                                            'reset' => '0x0',
                                            'commnet' => 'Performance counter inhibit. One bit per counter.',
                                            'poke_mask' => '0x7d'
                                          },
                       'micect' => {
                                     'exists' => 'true',
                                     'reset' => '0x0',
                                     'mask' => '0xffffffff',
                                     'number' => '0x7f0'
                                   },
                       'tselect' => {
                                      'mask' => '0x3',
                                      'reset' => '0x0',
                                      'exists' => 'true'
                                    },
                       'meipt' => {
                                    'number' => '0xbc9',
                                    'mask' => '0xf',
                                    'comment' => 'External interrupt priority threshold.',
                                    'reset' => '0x0',
                                    'exists' => 'true'
                                  },
                       'mpmc' => {
                                   'number' => '0x7c6',
                                   'exists' => 'true',
                                   'mask' => '0x2',
                                   'reset' => '0x2'
                                 },
                       'dicad1' => {
                                     'comment' => 'Cache diagnostics.',
                                     'mask' => '0x3',
                                     'reset' => '0x0',
                                     'exists' => 'true',
                                     'number' => '0x7ca',
                                     'debug' => 'true'
                                   },
                       'mhpmevent4' => {
                                         'reset' => '0x0',
                                         'mask' => '0xffffffff',
                                         'exists' => 'true'
                                       },
                       'dcsr' => {
                                   'exists' => 'true',
                                   'reset' => '0x40000003',
                                   'mask' => '0x00008c04',
                                   'poke_mask' => '0x00008dcc',
                                   'debug' => 'true'
                                 },
                       'mitbnd0' => {
                                      'reset' => '0xffffffff',
                                      'mask' => '0xffffffff',
                                      'exists' => 'true',
                                      'number' => '0x7d3'
                                    },
                       'misa' => {
                                   'exists' => 'true',
                                   'reset' => '0x40001104',
                                   'mask' => '0x0'
                                 },
                       'mdccmect' => {
                                       'number' => '0x7f2',
                                       'reset' => '0x0',
                                       'mask' => '0xffffffff',
                                       'exists' => 'true'
                                     },
                       'cycle' => {
                                    'exists' => 'false'
                                  },
                       'mitctl1' => {
                                      'number' => '0x7d7',
                                      'exists' => 'true',
                                      'reset' => '0x1',
                                      'mask' => '0x0000000f'
                                    },
                       'mhpmcounter6h' => {
                                            'exists' => 'true',
                                            'mask' => '0xffffffff',
                                            'reset' => '0x0'
                                          },
                       'meicidpl' => {
                                       'mask' => '0xf',
                                       'comment' => 'External interrupt claim id priority level.',
                                       'reset' => '0x0',
                                       'exists' => 'true',
                                       'number' => '0xbcb'
                                     },
                       'mhpmcounter3h' => {
                                            'exists' => 'true',
                                            'reset' => '0x0',
                                            'mask' => '0xffffffff'
                                          },
                       'mhpmcounter5h' => {
                                            'exists' => 'true',
                                            'reset' => '0x0',
                                            'mask' => '0xffffffff'
                                          },
                       'mitctl0' => {
                                      'number' => '0x7d4',
                                      'reset' => '0x1',
                                      'mask' => '0x00000007',
                                      'exists' => 'true'
                                    },
                       'mip' => {
                                  'poke_mask' => '0x70000888',
                                  'exists' => 'true',
                                  'reset' => '0x0',
                                  'mask' => '0x0'
                                },
                       'dmst' => {
                                   'number' => '0x7c4',
                                   'debug' => 'true',
                                   'exists' => 'true',
                                   'reset' => '0x0',
                                   'mask' => '0x0',
                                   'comment' => 'Memory synch trigger: Flush caches in debug mode.'
                                 },
                       'marchid' => {
                                      'mask' => '0x0',
                                      'reset' => '0x00000010',
                                      'exists' => 'true'
                                    },
                       'mfdhs' => {
                                    'comment' => 'Force Debug Halt Status',
                                    'mask' => '0x00000003',
                                    'reset' => '0x0',
                                    'exists' => 'true',
                                    'number' => '0x7cf'
                                  }
                     },
            'max_mmode_perf_event' => '516',
            'reset_vec' => '0x80000000',
            'core' => {
                        'bitmanip_zbb' => 1,
                        'bitmanip_zbc' => 1,
                        'div_new' => 1,
                        'lsu_num_nbload' => '4',
                        'bitmanip_zba' => 1,
                        'icache_only' => 'derived',
                        'bitmanip_zbr' => 0,
                        'iccm_only' => 1,
                        'bitmanip_zbs' => '0',
                        'lsu_stbuf_depth' => '4',
                        'bitmanip_zbe' => '1',
                        'timer_legal_en' => '1',
                        'bitmanip_zbf' => 0,
                        'div_bit' => '4',
                        'bitmanip_zbp' => 0,
                        'lsu2dma' => 0,
                        'no_iccm_no_icache' => 'derived',
                        'fast_interrupt_redirect' => '1',
                        'lsu_num_nbload_width' => '2',
                        'iccm_icache' => 'derived',
                        'dma_buf_depth' => '4',
                        'user_mode' => '1'
                      },
            'nmi_vec' => '0x11110000',
            'physical' => '1',
            'target' => 'default',
            'bus' => {
                       'sb_bus_tag' => '1',
                       'ifu_bus_prty' => '2',
                       'sb_bus_id' => '1',
                       'lsu_bus_tag' => 3,
                       'lsu_bus_id' => '1',
                       'dma_bus_id' => '1',
                       'dma_bus_tag' => '6',
                       'bus_prty_default' => '3',
                       'sb_bus_prty' => '2',
                       'ifu_bus_tag' => '3',
                       'ifu_bus_id' => '1',
                       'lsu_bus_prty' => '2',
                       'dma_bus_prty' => '2'
                     },
            'memmap' => {
                          'unused_region2' => '0x70000000',
                          'unused_region7' => '0x20000000',
                          'debug_sb_mem' => '0xb0580000',
                          'unused_region8' => '0x10000000',
                          'unused_region1' => '0x90000000',
                          'unused_region6' => '0x30000000',
                          'unused_region5' => '0x40000000',
                          'unused_region3' => '0x60000000',
                          'external_data_1' => '0xd0000000',
                          'unused_region9' => '0x00000000',
                          'unused_region4' => '0x50000000',
                          'external_data' => '0xe0580000',
                          'unused_region0' => '0xa0000000',
                          'serialio' => '0xf0580000',
                          'consoleio' => '0xf0580000'
                        },
            'even_odd_trigger_chains' => 'true',
            'perf_events' => [
                               1,
                               2,
                               3,
                               4,
                               5,
                               6,
                               7,
                               8,
                               9,
                               10,
                               11,
                               12,
                               13,
                               14,
                               15,
                               16,
                               17,
                               18,
                               19,
                               20,
                               21,
                               22,
                               23,
                               24,
                               25,
                               26,
                               27,
                               28,
                               30,
                               31,
                               32,
                               34,
                               35,
                               36,
                               37,
                               38,
                               39,
                               40,
                               41,
                               42,
                               43,
                               44,
                               45,
                               46,
                               47,
                               48,
                               49,
                               50,
                               54,
                               55,
                               56,
                               512,
                               513,
                               514,
                               515,
                               516
                             ],
            'icache' => {
                          'icache_status_bits' => 1,
                          'icache_beat_bits' => 3,
                          'icache_tag_lo' => 13,
                          'icache_num_beats' => 8,
                          'icache_banks_way' => 2,
                          'icache_ln_sz' => 64,
                          'icache_bank_width' => 8,
                          'icache_fdata_width' => 71,
                          'icache_tag_bypass_enable' => '1',
                          'icache_tag_num_bypass' => '2',
                          'icache_num_bypass_width' => 2,
                          'icache_num_lines_bank' => '64',
                          'icache_tag_depth' => 128,
                          'icache_data_width' => 64,
                          'icache_bank_bits' => 1,
                          'icache_scnd_last' => 6,
                          'icache_bank_lo' => 3,
                          'icache_bank_hi' => 3,
                          'icache_data_index_lo' => 4,
                          'icache_index_hi' => 12,
                          'icache_num_ways' => 2,
                          'icache_ecc' => '1',
                          'icache_tag_num_bypass_width' => 2,
                          'icache_tag_cell' => 'ram_128x25',
                          'icache_2banks' => '1',
                          'icache_waypack' => '1',
                          'icache_num_bypass' => '2',
                          'icache_num_lines' => 256,
                          'icache_num_lines_way' => '128',
                          'icache_size' => 16,
                          'icache_data_depth' => '512',
                          'icache_data_cell' => 'ram_512x71',
                          'icache_beat_addr_hi' => 5,
                          'icache_bypass_enable' => '1',
                          'icache_tag_index_lo' => '6'
                        },
            'harts' => 1
          );
1;
