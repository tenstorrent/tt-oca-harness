/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include "occp_test_common.h"
#include "smc_defines.h"
#include "smc_gpio.h"

/* Register offsets within each per-GPIO sub-block.
 * DATA_CTRL is the first register in gpio_intf_t (offset 0x0).*/
static const uint32_t GPIO_INTF_DATA_CTRL_OFFSET = 0x0u;

/* In DV simulation the clock is driven by the testbench; this stub satisfies
 * the call-site in initialize_i3c/i2c_controller without touching real PLL
 * registers. */
static void program_cgm0_functional(void) {
}

/* Secure lifecycle states are PROD (0x1) and PROD_END (0x8), the ROM's
 * SMC_LC_STATE_IS_SECURE set; TEST_DEV and the RMA encodings are non-secure. */
bool is_secure_mode(void) {
    uint32_t lc_state = read_reg(SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_LC_STATE_BASE_ADDR) & 0xF;
    return (lc_state == 1) || (lc_state == 8);
}

#ifndef I3C_USE_HCI_CORE
/* Only reachable from the non-HCI branch of enable_i3c_gpio_overrides() below; the guard keeps an
 * HCI-core build free of -Wunused warnings.
 * CONTROL is the first register in gpio_ctrl_t (offset 0x0). */
static const uint32_t GPIO_CTRL_CONTROL_OFFSET = 0x0u;

static bool enable_gpio_hw_override(uint8_t gpio_num) {
    gpio_ctrl__CONTROL_t ctrl;
    ctrl.w = read_gpio_shim(gpio_num, GPIO_CTRL_CONTROL_OFFSET);
    ctrl.f.hw2_ovrd = 1;
    write_gpio_shim(gpio_num, GPIO_CTRL_CONTROL_OFFSET, ctrl.w);

    ctrl.w = read_gpio_shim(gpio_num, GPIO_CTRL_CONTROL_OFFSET);
    if (ctrl.f.hw2_ovrd != 1) {
        simputshex32("Failed to enable GPIO hw2_ovrd for gpio: ", gpio_num);
        return false;
    }
    return true;
}
#endif /* !I3C_USE_HCI_CORE */

static bool enable_i3c_gpio_overrides(uint32_t controller_id) {
    (void)controller_id;

#ifdef I3C_USE_HCI_CORE
    /* I3C_CORE=swap (OCA/HCI i3c-core as the OCCP controller): the OCA core reaches the i3c pads
     * through the gpio LSIO path (lsio_interface_select, driven by smc_padring), not the
     * smc_ip_integration hw2_ovrd override path. The override path's drive/input-enable signals
     * are gated off for the OCA instance, so hw2_ovrd must stay 0 (reset default) for the
     * controller to drive and sense the bus. Mirrors the target-side gating in
     * hw/sys/smc/bootrom/prod/lib/src/occp.c. The #else branch serves a build without
     * I3C_USE_HCI_CORE, whose controller reaches the pads through hw2_ovrd. */
    return true;
#else
    /* Enable hw2_ovrd on every I3C-related GPIO so the I3C HW function reaches the pads. */
    bool ok = true;
    enable_gpio_hw_override(27); /* I3C0 SCL */
    enable_gpio_hw_override(28); /* I3C0 SDA */
    enable_gpio_hw_override(63); /* I3C1 SCL (unbonded) */
    enable_gpio_hw_override(64); /* I3C1 SDA (unbonded) */
    enable_gpio_hw_override(29); /* I3C2 SCL */
    enable_gpio_hw_override(30); /* I3C2 SDA */
    enable_gpio_hw_override(31); /* I3C3 SCL */
    enable_gpio_hw_override(32); /* I3C3 SDA */
    enable_gpio_hw_override(33); /* I3C4 SCL */
    enable_gpio_hw_override(34); /* I3C4 SDA */
    enable_gpio_hw_override(35); /* I3C5 SCL */
    enable_gpio_hw_override(36); /* I3C5 SDA */
    return ok;
#endif /* I3C_USE_HCI_CORE */
}

static void wait_for_target_up_gpio(void) {
    gpio_intf__DATA_CTRL_t data_ctrl;
    uint32_t poll_count = 0;

    simputs("[OCCP_IF] wait_for_target_up_gpio enter\n");
    data_ctrl.w = read_gpio(58, GPIO_INTF_DATA_CTRL_OFFSET);
    simputshex32("[OCCP_IF] GPIO58 initial DATA_CTRL: ", data_ctrl.w);
    data_ctrl.f.interface_enable = 1;
    data_ctrl.f.enable_rx_tx = 2;
    simputshex32("[OCCP_IF] GPIO58 configured DATA_CTRL: ", data_ctrl.w);
    write_gpio(58, GPIO_INTF_DATA_CTRL_OFFSET, data_ctrl.w);

    data_ctrl.w = read_gpio(58, GPIO_INTF_DATA_CTRL_OFFSET);
    simputshex32("[OCCP_IF] GPIO58 readback DATA_CTRL: ", data_ctrl.w);
    simputshex16("[OCCP_IF] GPIO58 readback pad2core: ", data_ctrl.f.pad2core);

    simputs("Waiting for target to be ready...\n");
    while (data_ctrl.f.pad2core == 0) {
        data_ctrl.w = read_gpio(58, GPIO_INTF_DATA_CTRL_OFFSET);
        poll_count++;
        if ((poll_count & 0x3ffu) == 0u) {
            simputshex32("[OCCP_IF] GPIO58 poll DATA_CTRL: ", data_ctrl.w);
            simputshex16("[OCCP_IF] GPIO58 poll pad2core: ", data_ctrl.f.pad2core);
        }
    }
    simputshex32("[OCCP_IF] GPIO58 ready DATA_CTRL: ", data_ctrl.w);
    simputs("Target is ready!\n");
}

bool initialize_i2c_controller(I2C_Driver **drv) {
    simputs("Starting OCCP Master Test\n");

    // Pre-boot clock configuration; the BL0_PLLCLK strap skips PLL programming.
    if (!smc_strap_is_set(SMC_STRAP_BL0_PLLCLK)) {
        program_cgm0_functional();
    }

    // Pick the I2C controller at random.
    uint32_t controller_id;

    bool boot_recovery = smc_strap_is_set(SMC_STRAP_BOOT_RECOVERY);
    bool primary_chiplet = smc_strap_is_set(SMC_STRAP_PRIMARY_CHIPLET);

    // Controller selection logic:
    // Randomly choose between controllers 0 or 1
    uint32_t random_val = get_random_int() % 2;
    if (random_val == 0) {
        controller_id = I3C_RECOVERY_CONTROLLER_ID;
        simputs("Using I2C controller 0 (random selection)\n");
    } else {
        controller_id = I3C_CONTROLLER_ID;
        simputs("Using I2C controller 1 (random selection)\n");
    }

    // Get an instance of the I2C driver.
    *drv = I2C_GetDriverInstance(controller_id);
    if (!*drv) {
        simputs("Failed to get I2C driver instance\n");
        return false;
    }

    // Initialize the controller as MASTER; scratch reg 4 carries both I2C target addresses,
    // 8 bits each.
    uint8_t i2c_addr =
        (random_val == 0) ? (read_scratch(4) & 0x7F) : ((read_scratch(4) >> 8) & 0x7F);
    if ((*drv)->init_i2c_ctrlr(*drv, i2c_addr) != I2C_OK) {
        simputs("I2C init failed\n");
        return false;
    }
    return true;
}

bool initialize_i3c_controller(I3C_Driver **drv) {
    simputs("Starting OCCP Master Test\n");

    // Pre-boot clock configuration; the BL0_PLLCLK strap skips PLL programming.
    if (!smc_strap_is_set(SMC_STRAP_BL0_PLLCLK)) {
        program_cgm0_functional();
    }

    // Pick the I3C controller at random.
    uint32_t controller_id;

    // Check strap values for BOOT_RECOVERY and PRIMARY_CHIPLET
    bool boot_recovery = smc_strap_is_set(SMC_STRAP_BOOT_RECOVERY);
    bool primary_chiplet = smc_strap_is_set(SMC_STRAP_PRIMARY_CHIPLET);

    // Controller selection logic:
    // Randomly choose between controllers 0, 1 or 3
    uint32_t random_val = get_random_int() % 3;
    if (random_val == 0) {
        controller_id = I3C_RECOVERY_CONTROLLER_ID;
        simputs("Using I3C controller 0 (random selection)\n");
    } else if (random_val == 1) {
        controller_id = I3C_CONTROLLER_ID;
        simputs("Using I3C controller 1 (random selection)\n");
    } else {
        controller_id = I3C_BACKUP_CONTROLLER_ID;
        simputs("Using I3C controller 3 (random selection)\n");
    }

    if (!enable_i3c_gpio_overrides(controller_id)) {
        simputs("Failed to enable I3C GPIO hardware overrides\n");
        return false;
    }

    // Get an instance of the I3C driver.
    *drv = I3C_GetDriverInstance(controller_id);
    if (!*drv) {
        simputs("Failed to get I3C driver instance\n");
        return false;
    }

    // Initialize the controller as MANAGER.
    if ((*drv)->init(*drv, controller_id, 0, MANAGER) != I3C_OK) {
        simputs("I3C init failed\n");
        return false;
    }

    // Start the I3C core (configure interrupts, prescalers, etc.)
    if ((*drv)->start(*drv, 200) != I3C_OK) {
        simputs("I3C start failed\n");
        return false;
    }

    return true;
}

bool discover_devices(I3C_Driver *drv, I3C_DeviceInfo *discovered_devices) {
    int done = 0;

    // Kick off dynamic address assignment.
    // Loop in case the BFM comes up faster than the DUT.
    while (done == 0) {
        simputs("Issuing ENTDAA command\n");
        if (drv->issue_entdaa(drv) != I3C_OK) {
            simputs("ENTDAA issue failed\n");
            continue;
        }

        simputs("ENTDAA command issued\n");
        // Wait for the ENTDAA command to complete.
        if (drv->wait_command(drv, CMD_ID_ENTDAA, I3C_CMD_TIMEOUT_MS) != I3C_OK) {
            simputs("ENTDAA command timed out\n");
            continue;
        }
        done = 1;
    }

    // Process discovered devices.
    if (drv->process_devices(drv, discovered_devices, I3C_MAX_DEVICES) != I3C_OK) {
        simputs("Processing devices failed\n");
        return false;
    }

    return true;
}

bool initialize_interface(test_context_t *ctx) {
    ctx->status_reporting_disabled = smc_strap_is_set(SMC_STRAP_STATUS_RPT_DISABLE);
    if (ctx->status_reporting_disabled) {
        simputs("STATUS_RPT_DISABLE strap detected; use +force_status_reporting to force status "
                "reporting for OCCP tests\n");
    }
    if (smc_strap_is_set(SMC_STRAP_BOOT_I2C)) {
        I2C_Driver *drv = NULL;
        if (!initialize_i2c_controller(&drv)) {
            simputs("I2C init failed\n");
            return false;
        }
        wait_for_target_up_gpio();
        simputs("I2C target is ready!\n");
        ctx->drv.i2c_drv = drv;
        ctx->type = DRIVER_TYPE_I2C;
        return true;
    } else {
        I3C_Driver *drv = NULL;
        if (!initialize_i3c_controller(&drv)) {
            simputs("I3C init failed\n");
            return false;
        }
        wait_for_target_up_gpio();
        simputs("I3C target is ready!\n");
        ctx->drv.i3c_drv = drv;
        ctx->type = DRIVER_TYPE_I3C;
        if (!discover_devices(ctx->drv.i3c_drv, ctx->discovered_devices)) {
            simputs("I3C discover failed\n");
            return false;
        }
        ctx->slave_addr = ctx->discovered_devices[1].dynamic_addr;
        return true;
    }
}
