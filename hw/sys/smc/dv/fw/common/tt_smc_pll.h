#ifndef TT_SMC_PLL_H
#define TT_SMC_PLL_H

#include <stdint.h>
#include <stdbool.h>
#include "smc_defines.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    TT_SMC_PLL_SUCCESS,
    TT_SMC_PLL_ERROR_INVALID_PARAM,
    TT_SMC_PLL_ERROR_LOCK_TIMEOUT,
} tt_smc_status_t;

typedef struct {
    bool enable;
    bool freq_acq_enable;
    uint32_t fcw_int;
    uint32_t fcw_frac;
    uint32_t prediv;
    struct {
        uint8_t postdiv0;
        uint8_t postdiv1;
        uint8_t postdiv2;
        uint8_t postdiv3;
    } postdivs;
    struct {
        uint8_t postdiv0_config;
        uint8_t postdiv1_config;
        uint8_t postdiv2_config;
        uint8_t postdiv3_config;
    } postdiv_configs;
    uint32_t lock_threshold;
    uintptr_t status_reg_offset;
    uint32_t lock_detect_mask;
} CgmPllConfig;

typedef struct {
    uint32_t fcw_int0;
    uint32_t fcw_int1;
    uint32_t fcw_frac0;
    uint32_t fcw_frac1;
    uint32_t fcw_frac2;
    uint32_t fcw_frac3;
    struct {
        uint8_t prediv;
        uint8_t postdiv;
        uint8_t postdiv_config;
        uint8_t freq_lock_threshold;
    } div_config;
    bool cgm2_enable;
    struct {
        bool freq_sel_one_hot_clk0;
        bool freq_sel_one_hot_clk1;
        bool freq_sel_one_hot_clk2;
    } ctrl_config;
    uintptr_t lock_monitor_reg_offset;
    uint32_t lock_mask;
    uint32_t lock_expected_value;
} AwmPllConfig;

tt_smc_status_t tt_smc_cgm_pll_init(uint32_t pll_instance, const CgmPllConfig *config);
tt_smc_status_t tt_smc_awm_pll_init(uint32_t pll_instance, const AwmPllConfig *config);

#ifdef __cplusplus
}
#endif

#endif // TT_SMC_PLL_H