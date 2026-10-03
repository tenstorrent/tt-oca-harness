/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* SMC OCCP Interface Implementation
 * On-Chip Command Processor for I2C/I3C communication
 */

#include <stdint.h>
#include <string.h>
#include "i3c_target_driver.h"
#include "smc_rom_defs.h"
#include "smc_defines.h"
#include "smc_security.h"
#include "smc_efuse.h"
#include "smc_strap.h"
#include "smc_interface_map.h"
#include "smc_status.h"
#include "smc_scratchpad.h"
#include "smc_occp_status.h"
#include "smc_occp_error_codes.h"
#include "smc_post_code.h"
#include "virt_console.h"
#include "i2c_target_driver.h"
#include "occp.h"

/*********************************************************************
 * Type Definitions and Constants
 ********************************************************************/

typedef void *interface_driver_t;

typedef enum { DRIVER_TYPE_I3C, DRIVER_TYPE_I2C } driver_type_t;

typedef struct {
    interface_driver_t channel_drivers[5];
    driver_type_t type[5];
    size_t num_channels;

} smc_active_interfaces_t;

static uint32_t TRANSPORT_TIMEOUT = 10000; /* Global transport timeout default value*/
/* Initialize transport timeout from efuse during system initialization */
static void smc_occp_init_transport_timeout(void) {
    uint32_t efuse_timeout = smc_efuse_get_transport_timeout();

    if (efuse_timeout == 0) {
        TRANSPORT_TIMEOUT = 10000; // Default value when efuse is 0
    } else {
        TRANSPORT_TIMEOUT = efuse_timeout;
    }
    simputshex32("OCCP: Transport timeout set to: ", TRANSPORT_TIMEOUT);
}

/*********************************************************************
 * Function Prototypes
 ********************************************************************/

/**
 * Reads efuses and straps to determine a valid I3C or I2C address.
 * but actual fusing scheme is not yet finalized.
 */
static uint64_t smc_occp_determine_i3c_address(uint8_t efuse_slot_id);

/**
 * Initializes an I3C channel with the given controller ID and I3C ID.
 * Returns OCCP_ERROR_NONE on success or an appropriate error code.
 */
#ifndef SMC_OCCP_DISABLE_I3C_INIT
static int smc_occp_init_i3c_channel(bool use_channel, uint8_t controller_id, uint64_t i3c_id);
#endif

/**
 * Initializes an I2C channel with the given controller ID and I2C ID.
 * Returns OCCP_ERROR_NONE on success or an appropriate error code.
 */
static int smc_occp_init_i2c_channel(bool use_channel, uint8_t controller_id, uint8_t i2c_id);

/**
 * Busy polls active interface_driver_t channels in g_smc_active_interfaces.
 * Initially polls all enabled interfaces. After the first successful command,
 * latches to that interface and only polls the latched interface.
 * Returns the index of the channel that has data available.
 */
static int smc_occp_poll_channels(void);

/**
 * Latches the interface to the specified index after first successful command.
 * This implements the interface latching behavior per specification.
 */
static void smc_occp_latch_interface(int interface_index);

/**
 * Unlatches the current interface and returns to polling all interfaces.
 * Used for error recovery when the latched interface becomes unresponsive.
 */
static void smc_occp_unlatch_interface(void);

/**
 * Checks if the specified interface has data available.
 * Works for both I2C and I3C interfaces.
 */
static bool smc_occp_interface_has_data(int interface_index);

/**
 * Records an interface error and triggers unlatch if threshold exceeded.
 * Returns true if interface was unlatched due to errors.
 */
static bool smc_occp_handle_interface_error(void);

/**
 * Writes a complete reply to an OCCP command to the interface's bus through
 * whatever HW interface the peripheral uses.
 */
static int smc_occp_send_to_bus(interface_driver_t drv, driver_type_t drv_type, const uint8_t *data,
                                size_t length, uint32_t timeout);

/**
 * Reads [length] bytes from the interface bus.
 * Due to the HW interface of the I3C peripheral, you must read in increments of 4 bytes
 * if you are reading a partial transaction. If you read a partial transaction that is not
 * 4-byte aligned, you will discard data.
 * Reading in non 4-byte chunks is fine if the read will completely read the I3C rx FIFO
 * for that private write transaction.
 */
static int smc_occp_read_from_bus_4byte_aligned_or_complete_stream(
    interface_driver_t drv, driver_type_t drv_type, uint8_t *buffer, size_t length,
    uint32_t timeout, bool expect_excess_bytes, bool is_flush);

/*********************************************************************
 * OCCP Command Handlers
 ********************************************************************/

/**
 * Handles the OCCP_GET_STATUS, OCCP_GET_SEP_STATUS, and OCCP_GET_SMC_STATUS commands
 * since they all share the same logic but return a uint32_t status from different buffers.
 */
static int smc_occp_handle_get_status(interface_driver_t drv, driver_type_t drv_type,
                                      occp_header hdr, bool body_crc_present);
static int smc_occp_handle_get_version(interface_driver_t drv, driver_type_t drv_type,
                                       occp_header hdr, bool body_crc_present);
static int smc_occp_handle_get_boot_version(interface_driver_t drv, driver_type_t drv_type,
                                            occp_header hdr, bool body_crc_present);
static int smc_occp_handle_read(interface_driver_t drv, driver_type_t drv_type, occp_header hdr,
                                bool body_crc_present);
static int smc_occp_handle_write(interface_driver_t drv, driver_type_t drv_type, occp_header hdr,
                                 bool body_crc_present);

static int smc_occp_handle_jump(interface_driver_t drv, driver_type_t drv_type, occp_header hdr,
                                bool body_crc_present);
static int smc_occp_handle_validate_boot(interface_driver_t drv, driver_type_t drv_type,
                                         occp_header hdr, bool body_crc_present);

static occp_error_code_t smc_occp_handle_error_response(interface_driver_t drv,
                                                        driver_type_t drv_type, occp_header hdr,
                                                        Occp_ErrMsgID msgid);

/**
 * Checks whether a read/write access is allowed based on secured mode, recovery strap,
 * and SRAM stack protection limit.
 * Returns OCCP_ERROR_NONE if access is allowed or an appropriate occp_error_code_t error.
 * Note: Address alignment is checked based on command type - this function assumes
 * proper alignment has already been applied by the caller.
 */
static uint8_t smc_occp_check_addr_access_allowed(uint64_t addr, uint16_t access_size);
/**
 * Flushes the interface FIFO to clear any remaining body data after a header error.
 * This prevents body data from corrupting the next command read.
 * Uses a conservative approach with timeouts to handle cases where the length field
 * in the header might be corrupted.
 */
static int smc_occp_flush_interface_fifo(interface_driver_t drv, driver_type_t drv_type);

/** Calculate CRC8 for the occp header based on the polynomial 0xD3 defined in
 * https://users.ece.cmu.edu/%7Ekoopman/crc/crc8.html */
static uint8_t calculate_crc8(uint8_t *buffer, size_t length);
/** Calculate CRC32 for the occp header based on the polynomial 0x992C14AC defined in
 * https://users.ece.cmu.edu/%7Ekoopman/crc/crc32.html */
static void crc32_init_table(void); // Helper function to initialize the CRC32 table
static uint32_t calculate_crc32(uint8_t *buffer, size_t length);

static Occp_ErrMsgID smc_occp_validate_header(packet_header hdr);
static Occp_ErrMsgID smc_occp_validate_body(uint8_t *buffer, size_t length, bool crc_present);

static int error_response_sent = 0;

static bool enable_gpio_hw_override(uint8_t gpio_num) {
    GPIO_CTRL_CONTROL_reg_u gpio_ctrl;
    gpio_ctrl.val =
        read_gpio_shim(gpio_num, SMC_EXTERNAL_MANDATORY_GPIO_CTRL_0__CONTROL_REG_OFFSET);
    gpio_ctrl.f.hw2_ovrd = 1;
    write_gpio_shim(gpio_num, SMC_EXTERNAL_MANDATORY_GPIO_CTRL_0__CONTROL_REG_OFFSET,
                    gpio_ctrl.val);

    gpio_ctrl.val =
        read_gpio_shim(gpio_num, SMC_EXTERNAL_MANDATORY_GPIO_CTRL_0__CONTROL_REG_OFFSET);
    if (gpio_ctrl.f.hw2_ovrd != 1) {
        simputshex32("Failed to enable GPIO hw2_ovrd for gpio: ", gpio_num);
        return false;
    }
    return true;
}

#ifndef SMC_OCCP_DISABLE_I3C_INIT
static bool enable_i3c_gpio_overrides(uint32_t controller_id) {
    (void)controller_id;

#ifdef I3C_USE_HCI_CORE
    /* I3C_CORE=chipsalliance (OCA/HCI i3c-core as the OCCP target): the OCA core reaches the i3c
     * pads via the gpio LSIO path (lsio_interface_select, driven by smc_padring), NOT the
     * smc_ip_integration hw2_ovrd override path that the Cadence core uses. Setting hw2_ovrd here
     * would force the gpio_shim onto the override path, whose drive/input-enable signals are gated
     * OFF for the OCA instance (SwapI3cCore=1) -> the pad INPUT buffer stays disabled and the OCA
     * target never sees the bus (root cause of the ENTDAA M2 timeout). So leave hw2_ovrd=0 (reset
     * default) for the i3c GPIOs; the OCA core's LSIO routing then serves the shared bus (mirrors
     * the cocotb OCA target).
     */
    return true;
#else
    /* Mirror the proven bring-up sequence used by i3c_loop_back:
     * enable hw2_ovrd on all I3C-related GPIOs so the I3C HW function reaches the pads.
     */
    bool ok = true;
    enable_gpio_hw_override(SMC_I3C_0_SCL_GPIO); /* I3C0 SCL */
    enable_gpio_hw_override(SMC_I3C_0_SDA_GPIO); /* I3C0 SDA */
    enable_gpio_hw_override(SMC_I3C_1_SCL_GPIO); /* I3C1 SCL (unbonded) */
    enable_gpio_hw_override(SMC_I3C_1_SDA_GPIO); /* I3C1 SDA (unbonded) */
    enable_gpio_hw_override(SMC_I3C_2_SCL_GPIO); /* I3C2 SCL */
    enable_gpio_hw_override(SMC_I3C_2_SDA_GPIO); /* I3C2 SDA */
    enable_gpio_hw_override(SMC_I3C_3_SCL_GPIO); /* I3C3 SCL */
    enable_gpio_hw_override(SMC_I3C_3_SDA_GPIO); /* I3C3 SDA */
    enable_gpio_hw_override(SMC_I3C_4_SCL_GPIO); /* I3C4 SCL */
    enable_gpio_hw_override(SMC_I3C_4_SDA_GPIO); /* I3C4 SDA */
    enable_gpio_hw_override(SMC_I3C_5_SCL_GPIO); /* I3C5 SCL */
    enable_gpio_hw_override(SMC_I3C_5_SDA_GPIO); /* I3C5 SDA */
    return ok;
#endif /* I3C_USE_HCI_CORE */
}
#endif

/* Enable the GPIO 2nd HW function override for the always-on observation
 * functions. This is routed through the smc_ip_integration override path, so
 * hw2_ovrd must be set for it to reach its pad. CAT_THERM is a safety output
 * and must be active out of boot.
 *
 * PVT RO observation is deliberately absent: the pad shrink removed GPIO 57 and
 * moved that function to the dedicated PVT_CLK_OBS_PAD, so there is no GPIO
 * override left to program.
 */
static void enable_observation_gpio_overrides(void) {
    enable_gpio_hw_override(SMC_CAT_THERM_GPIO); /* thermal trip output */
}

/**
 * Set the GPIO status to the external host
 * @param status The occp status from smc_occp_init
 * if status is No Error, then set GPIO to indicate success,
 * otherwise clear GPIO to indicate error.
 */
static void set_gpio_status(occp_error_code_t status) {
    GPIO_INTF_DATA_CTRL_reg_u gpio_control;

    gpio_control.val = read_gpio(58, SMC_EXTERNAL_MANDATORY_GPIO_CTRL_58__CONTROL_REG_OFFSET);
    gpio_control.f.interface_enable = 1; // Enable the interface
    gpio_control.f.enable_rx_tx = 1;     // Enable Tx

    if (status == OCCP_ERROR_NONE) {
        // Set GPIO to indicate success
        gpio_control.f.core2pad = 1; // Register driven data send to pad
        write_gpio(58, SMC_EXTERNAL_MANDATORY_GPIO_CTRL_58__CONTROL_REG_OFFSET,
                   gpio_control.val); // Write control register to enable GPIO
        simputs("OCCP: GPIO set to indicate success\n");
    } else {

        // Clear GPIO to indicate error
        gpio_control.f.core2pad = 0; // Set chip to pad mode
        write_gpio(58, SMC_EXTERNAL_MANDATORY_GPIO_CTRL_58__CONTROL_REG_OFFSET,
                   gpio_control.val); // Write control register to enable GPIO
        simputs("OCCP: GPIO set to indicate error\n");
    }
}

/*********************************************************************
 * Static Global Variables
 ********************************************************************/

static smc_active_interfaces_t g_smc_active_interfaces = {0};

/* Interface latching state - initially -1 (no interface latched) */
static int g_latched_interface_index = -1;
static bool g_interface_latching_active = false;
static uint32_t g_interface_error_count = 0;
static int g_last_unlatched_interface = -1; /* Track last unlatched interface for round-robin */

/* Interface unlatch thresholds and configuration */
#define INTERFACE_ERROR_THRESHOLD 5         /* Unlatch after 5 consecutive errors */
#define INTERFACE_TIMEOUT_THRESHOLD 1000000 /* Timeout iterations before unlatch */

/* Max message body plus up to 4 bytes CRC overhead */
static uint8_t g_occp_data_buffer[OCCP_MAX_MSG_SIZE + 4];

/**
 * @brief Calculates CRC8 checksum for a given data buffer using polynomial 0xD3.
 *
 * This function computes the CRC8 value for the specified buffer, typically used
 * for OCCP header integrity checks.
 *
 * @param data Pointer to the input data buffer.
 * @param length Number of bytes in the buffer to process.
 * @return Calculated CRC8 value.
 */
static uint8_t calculate_crc8(uint8_t *data, size_t length) {
    // x^8 +x^7 +x^5 +x^2 +x +1
    uint8_t crc = 0xFF; // Initial value

    for (size_t i = 0; i < length; i++) {
        // simputshex16("OCCP: Calculating CRC8, processing byte: ", data[i]);
        crc ^= data[i];

        for (int j = 0; j < 8; j++) {
            if (crc & 0x80) {
                crc = (crc << 1) ^ CRC8_POLYNOMIAL;
            } else {
                crc <<= 1;
            }
        }
    }

    return crc;
}

// Precomputed CRC32 table for polynomial 0x992C14AC
static uint32_t crc32_table[256];
static bool crc32_table_initialized = false;

// Generate the CRC32 table at runtime (called once)
static void crc32_init_table(void) {
    for (uint32_t i = 0; i < 256; i++) {
        uint32_t crc = i << 24;
        for (int j = 0; j < 8; j++) {
            if (crc & 0x80000000)
                crc = (crc << 1) ^ CRC32_POLYNOMIAL;
            else
                crc <<= 1;
        }
        crc32_table[i] = crc;
    }
    crc32_table_initialized = true;
}

static uint32_t calculate_crc32(uint8_t *data, size_t length) {
    if (!crc32_table_initialized) crc32_init_table();

    uint32_t crc = 0xFFFFFFFF;
    for (size_t i = 0; i < length; i++) {
        uint8_t idx = (uint8_t)((crc >> 24) ^ data[i]);
        crc = (crc << 8) ^ crc32_table[idx];
    }
    return crc ^ 0xFFFFFFFF;
}

static Occp_ErrMsgID smc_occp_validate_header(packet_header hdr) {
    // Validate the header fields
    // only calculate crc on the 56 bits of header fields

    uint8_t *hdr_ptr = ((uint8_t *)&hdr) + 1;

    uint8_t calculated_crc = calculate_crc8(hdr_ptr, 7);
    if (hdr.hdr_crc != calculated_crc) {
        simputshex16("OCCP: Header CRC mismatch. Calculated: ", calculated_crc);
        simputshex16("OCCP: Header CRC mismatch. Received: ", hdr.hdr_crc);
        return Corrupt_header;
    }
    return NoErr;
}
static Occp_ErrMsgID smc_occp_validate_body(uint8_t *data_buffer, size_t data_len,
                                            bool crc_present) {
    simputshex16("OCCP: Validating body of length: ", data_len);
    if (data_len == 0) // This condition should not be hit, as the calling function should have
                       // checked this earlier
    {
        return Invalid_header;
    }
    if (crc_present) {
        if (data_len > (PACKET_SIZE_FOR_CRC8 +
                        sizeof(uint32_t))) // If body length > 14 bytes, then data_len = body_len +
                                           // 4 byte CRC will be >18; use CRC32
        {
            uint32_t crc32_val;
            memcpy(
                &crc32_val, data_buffer + data_len - 4,
                sizeof(uint32_t)); // data_len = message_length+4 byte crc32; last 4 bytes are crc32
            simputshex32("OCCP: Validating body CRC32, received CRC32: ", crc32_val);
            if (calculate_crc32(data_buffer, (data_len - 4)) == crc32_val) {
                return NoErr;
            } else {
                return Corrupt_Data;
            }
        } else {
            simputshex16("OCCP: Validating body CRC8, received CRC8: ", data_buffer[data_len - 1]);
            if (calculate_crc8(data_buffer, data_len - 1) ==
                data_buffer[data_len -
                            1]) // data_len = message_length+1 byte crc8; last byte is crc8
            {
                return NoErr;
            } else {
                simputs("OCCP: Body CRC8 mismatch, returning Corrupt_Data\n");
                return Corrupt_Data;
            }
        }
    } else {
        return NoErr;
    }
}

int smc_occp_init(void) {
    occp_error_code_t ret = OCCP_ERROR_NONE;
    /* Determine I3C ID from efuses and straps */
    uint64_t i3c_id = 0x0;
    uint8_t i2c_address = 0x55; // Default I2C address if efuse is invalid

    smc_occp_init_transport_timeout();   // Initialize global TRANSPORT_TIMEOUT from efuse
    enable_observation_gpio_overrides(); // Route thermal trip + PVT obs to their pads (hw2_ovrd)
    /* Determine I3C ID from efuses and straps */
    /*Efuse slot id[0:5] is for I3C pid [0:5], efuse slot id[6:8] id for I2C addr[0:2]*/
#ifndef SMC_OCCP_DISABLE_I3C_INIT
    i3c_id = smc_occp_determine_i3c_address(0x0);
    ret |= smc_occp_init_i3c_channel(true, 0, i3c_id);
    i3c_id = smc_occp_determine_i3c_address(0x1);
    ret |= smc_occp_init_i3c_channel(true, 1, i3c_id);
    i3c_id = smc_occp_determine_i3c_address(0x3);
    ret |= smc_occp_init_i3c_channel(true, 3, i3c_id);
#else
    simputs("OCCP: I3C init disabled by build define\n");
#endif
    /*For I2C, Lower 7 bits of the read id is used as the i2c_addr*/
    /*Efuse slot id[0:5] is for I3C pid [0:5], efuse slot id[6:8] id for I2C addr[0:2]*/
    i3c_id = smc_occp_determine_i3c_address(0x6);
    i2c_address = (uint8_t)(i3c_id & 0x7F); /* Use lower 7 bits for I2C */
    if ((i2c_address > 0x7) && (i2c_address < 0x78))
        ret |= smc_occp_init_i2c_channel(true, 0x0, i2c_address);
    else {
        ret |= smc_occp_init_i2c_channel(
            true, 0x0,
            0x55); // Default to HW default value 0x55 if the incoming i2c address is invalid
        simputs("No Valid I2C Address found, defaulting to 0x55\n");
    }
    i3c_id = smc_occp_determine_i3c_address(0x7);
    i2c_address = (uint8_t)(i3c_id & 0x7F); /* Use lower 7 bits for I2C */
    if ((i2c_address > 0x7) && (i2c_address < 0x78))
        ret |= smc_occp_init_i2c_channel(true, 0x1, i2c_address);
    else
        ret |= smc_occp_init_i2c_channel(
            true, 0x1,
            0x55); // Default to HW default value 0x55 if the incoming i2c address is invalid

    if (ret != OCCP_ERROR_NONE) {
        simputs("[ERROR] OCCP interface initialization failed\n");
        occp_status_set_interface_status(OCCP_INTERFACE_STATUS_ERROR);
        set_gpio_status(OCCP_ERROR_INTERFACE_ERROR);
        return ret;
    } else {
        simputs("[MAIN] OCCP interface initialized successfully\n");
        occp_status_set_interface_status(OCCP_INTERFACE_STATUS_READY);
        set_gpio_status(OCCP_ERROR_NONE);
        return ret;
    }
}

void smc_occp_force_unlatch(void) {
    simputs("OCCP: Force unlatch requested\n");
    smc_occp_unlatch_interface();
}

static int smc_occp_poll_channels(void) {
    static uint32_t timeout_counter = 0;

    while (1) {
        if (g_interface_latching_active && g_latched_interface_index >= 0) {
            /* Interface already latched - only check the latched interface */
            if (smc_occp_interface_has_data(g_latched_interface_index)) {
                timeout_counter = 0; /* Reset timeout on successful data */
                return g_latched_interface_index;
            }

            /* Check for timeout on latched interface */
            timeout_counter++;
            if (timeout_counter >= INTERFACE_TIMEOUT_THRESHOLD) {
                simputs("OCCP: Latched interface timeout, attempting unlatch\n");
                smc_occp_unlatch_interface();
                timeout_counter = 0; /* Reset counter */
            }
        } else {
            /* No interface latched yet - poll all enabled interfaces */
            /* Implement round-robin: start polling from interface after last unlatched */
            int start_index =
                (g_last_unlatched_interface >= 0)
                    ? (g_last_unlatched_interface + 1) % (int)g_smc_active_interfaces.num_channels
                    : 0;

            int i;
            for (i = 0; i < (int)g_smc_active_interfaces.num_channels; i++) {
                int current_index = (start_index + i) % (int)g_smc_active_interfaces.num_channels;
                if (smc_occp_interface_has_data(current_index)) {
                    timeout_counter = 0; /* Reset timeout when data found */
                    return current_index;
                }
            }
        }
    }
}

static void smc_occp_latch_interface(int interface_index) {
    if (!g_interface_latching_active) {
        g_latched_interface_index = interface_index;
        g_interface_latching_active = true;
        g_interface_error_count = 0; /* Reset error count on successful latch */

        // Report the active interface in POST code
        switch (interface_index) {
        case 0:
            smc_post_code_set_interface(POST_CODE_IFACE_I3C0);
            break;
        case 1:
            smc_post_code_set_interface(POST_CODE_IFACE_I3C1);
            break;
        case 2:
            smc_post_code_set_interface(POST_CODE_IFACE_I3C3);
            break;
        case 3:
            smc_post_code_set_interface(POST_CODE_IFACE_I2C0);
            break;
        case 4:
            smc_post_code_set_interface(POST_CODE_IFACE_I2C1);
            break;
        default:
            smc_post_code_set_interface(POST_CODE_IFACE_NONE);
            break;
        }

        simputshex16("OCCP: Interface latched to index: ", (uint16_t)interface_index);
        simputs("OCCP: Now ignoring commands from other interfaces\n");
    }
}

static void smc_occp_unlatch_interface(void) {
    if (g_interface_latching_active) {
        simputshex16("OCCP: Unlatching interface index: ", (uint16_t)g_latched_interface_index);
        simputs("OCCP: Returning to polling all enabled interfaces\n");

        /* Drain FIFO to prevent immediate re-latching on stale bytes. */
        interface_driver_t drv = g_smc_active_interfaces.channel_drivers[g_latched_interface_index];
        driver_type_t drv_type = g_smc_active_interfaces.type[g_latched_interface_index];
        smc_occp_flush_interface_fifo(drv, drv_type);

        /* Track the last unlatched interface for round-robin polling. */
        g_last_unlatched_interface = g_latched_interface_index;

        g_latched_interface_index = -1;
        g_interface_latching_active = false;
        g_interface_error_count = 0;

        /* Report interface unlatch event */
        smc_status_report(
            SMC_STATUS_TYPE_WARNING,
            SMC_OCCP_ERROR_WITH_DATA(SMC_OCCP_ERROR_CMD_FAILED, OCCP_ERROR_INTERFACE_ERROR));
    }
}

static bool smc_occp_handle_interface_error(void) {
    if (g_interface_latching_active) {
        g_interface_error_count++;
        simputshex32("OCCP: Interface error count: ", g_interface_error_count);

        if (g_interface_error_count >= INTERFACE_ERROR_THRESHOLD) {
            simputs("OCCP: Interface error threshold exceeded, unlatching\n");
            smc_occp_unlatch_interface();
            return true; /* Interface was unlatched */
        }
    }
    return false; /* Interface still latched */
}

static bool smc_occp_interface_has_data(int interface_index) {
    if (interface_index < 0 || (size_t)interface_index >= g_smc_active_interfaces.num_channels) {
        return false;
    }

    interface_driver_t drv = g_smc_active_interfaces.channel_drivers[interface_index];
    if (drv == NULL) {
        return false;
    }

    // if (interface_index == 0x3 || interface_index == 0x4)
    if (g_smc_active_interfaces.type[interface_index] == DRIVER_TYPE_I2C) {
        // simputshex16("OCCP: Checking I2C RX FIFO for interface index: ",
        // (uint16_t)interface_index);
        I2C_Driver *i2c_drv = (I2C_Driver *)drv;
        /* Check I2C RX FIFO level using proper driver API */
        return (i2c_drv->check_rx_fifo(i2c_drv) > 0);
    } else if (g_smc_active_interfaces.type[interface_index] == DRIVER_TYPE_I3C) {

        // simputshex16("OCCP: Checking I3C RX FIFO for interface index: ",
        // (uint16_t)interface_index);
        I3C_Driver *i3c_drv = (I3C_Driver *)drv;
        /* Check I3C RX FIFO level using proper driver API */
        return (i3c_drv->check_rx_fifo(i3c_drv) > 0);
    } else {
        simputshex16("OCCP: Unknown driver type for interface index: ", (uint16_t)interface_index);
        return false; // Unknown driver type
    }
}
static void smc_occp_handle_transport_error(interface_driver_t drv, driver_type_t drv_type,
                                            packet_header command_packet, bool hdr_valid,
                                            occp_error_code_t occp_status) {
    if (hdr_valid == 0) {
        command_packet.hdr.app_id = 0xFF;
        command_packet.hdr.msg_id = 0xFF;
        command_packet.hdr.flags = 0x0;
    }
    if (occp_status == OCCP_ERROR_TRANSPORT_INCOMPLETE) {
        smc_occp_handle_error_response(drv, drv_type, command_packet.hdr,
                                       Incomplete_msg); // Incomplete transaction
    } else if (occp_status == OCCP_ERROR_TRANSPORT_OVERFLOW) {
        smc_occp_handle_error_response(drv, drv_type, command_packet.hdr,
                                       Oversize_msg); // Overflow transaction
    } else {
        smc_occp_handle_error_response(
            drv, drv_type, command_packet.hdr,
            Transport_crc); // Generic transport CRC, SMC Boot ROM will not generate this error
    }
}

void smc_occp_process(void) {
    packet_header command_packet;
    occp_header command_word;
    // Set initial OCCP state to IDLE
    smc_post_code_set_occp_state(POST_CODE_OCCP_STATE_IDLE);

    while (1) {
        /* Reset error_response_sent flag at the start of each command iteration */
        error_response_sent = 0;

        int channel_with_data = smc_occp_poll_channels();
        interface_driver_t drv = g_smc_active_interfaces.channel_drivers[channel_with_data];
        driver_type_t drv_type = g_smc_active_interfaces.type[channel_with_data];
        occp_error_code_t occp_status = OCCP_ERROR_INVALID_COMMAND; // initialize to invalid command
        occp_error_code_t ret = OCCP_ERROR_TIMEOUT;                 // initialize to timeout error
        if (!drv) {
            simputs("[OCCP] Channel driver is NULL\n");
            continue; // Skip to next iteration if no valid driver
        }
        occp_status = smc_occp_read_from_bus_4byte_aligned_or_complete_stream(
            drv, drv_type, (uint8_t *)&command_packet, sizeof(command_packet), TRANSPORT_TIMEOUT, 1,
            0);
        // Set state to indicate command being received
        smc_post_code_set_occp_state(POST_CODE_OCCP_STATE_CMD_RECEIVED);

        if (occp_status == OCCP_ERROR_NONE) {
            // Set state to indicate command processing
            smc_post_code_set_occp_state(POST_CODE_OCCP_STATE_PROCESSING);

            /*
            Received packet header format
            <8-bit Header CRC | 24-bit rsvd |32-bit OCCP Header>
            Packet structure is
            <64bit header| Message Body(1024max)|Body CRC (8 /32 bit)>
            */
            // Check for Header CRC pass
            Occp_ErrMsgID header_validation = smc_occp_validate_header(command_packet);

            if (header_validation != NoErr) {
                simputs("OCCP: Invalid OCCP header received\n");
                // Set error state for header validation failure
                smc_post_code_set_occp_state(POST_CODE_OCCP_STATE_ERROR);
                smc_post_code_set_error(POST_CODE_ERROR_COMMAND);
                smc_status_report(SMC_STATUS_TYPE_ERROR,
                                  SMC_OCCP_ERROR_WITH_DATA(SMC_OCCP_ERROR_CMD_FAILED,
                                                           header_validation)); /* Command failed */
                ret = smc_occp_handle_error_response(drv, drv_type, command_packet.hdr,
                                                     header_validation); // Header error
            } else {
                command_word = command_packet.hdr;
                if (command_word.app_id == Base) {
                    if (command_word.msg_id < Base_max_command) {
                        // Found proper Base command, latch to this interface
                        smc_occp_latch_interface(channel_with_data);
                    }

                    switch (command_word.msg_id) {
                    case GetVersion_base:
                        ret = smc_occp_handle_get_version(drv, drv_type, command_word,
                                                          command_packet.body_crc_present);
                        break;
                    case GetStatus:
                        ret = smc_occp_handle_get_status(drv, drv_type, command_word,
                                                         command_packet.body_crc_present);
                        break;
                    case WriteData:
                        ret = smc_occp_handle_write(drv, drv_type, command_word,
                                                    command_packet.body_crc_present);
                        break;
                    case ReadData:
                        ret = smc_occp_handle_read(drv, drv_type, command_word,
                                                   command_packet.body_crc_present);
                        break;
                    default:
                        simputshex32("Unknown OCCP command received: ", command_word.msg_id);
                        smc_post_code_set_occp_state(POST_CODE_OCCP_STATE_ERROR);
                        smc_post_code_set_error(POST_CODE_ERROR_COMMAND);
                        smc_status_report(
                            SMC_STATUS_TYPE_ERROR,
                            SMC_OCCP_ERROR_WITH_DATA(SMC_OCCP_ERROR_CMD_UNKNOWN,
                                                     command_word.msg_id)); /* Unknown command */
                        ret = smc_occp_handle_error_response(drv, drv_type, command_word,
                                                             Invalid_Msgid); // MsgID error
                        break;
                    }
                } else if (command_word.app_id == Boot) {
                    if (command_word.msg_id <
                        Boot_max_command) { // Proper Boot command, latch to this interface
                        smc_occp_latch_interface(channel_with_data);
                    }
                    switch (command_word.msg_id) {
                    case GetVersion_boot:
                        ret = smc_occp_handle_get_boot_version(drv, drv_type, command_word,
                                                               command_packet.body_crc_present);
                        break;
                    case ExecuteImage:
                        ret = smc_occp_handle_jump(drv, drv_type, command_word,
                                                   command_packet.body_crc_present);
                        break;
                    case AuthenticateImage:
                        ret = smc_occp_handle_validate_boot(drv, drv_type, command_word,
                                                            command_packet.body_crc_present);
                        break;
                    case Train_d2d:
                        // ret = smc_occp_handle_train_d2d(drv, drv_type, command_word,
                        // command_packet.body_crc_present);
                        simputs("OCCP: Train_d2d command not implemented in Boot ROM\n");
                        smc_status_report(
                            SMC_STATUS_TYPE_ERROR,
                            SMC_OCCP_ERROR_WITH_DATA(SMC_OCCP_ERROR_CMD_UNKNOWN,
                                                     command_word.msg_id)); /* Unknown command */
                        ret = smc_occp_handle_error_response(drv, drv_type, command_word,
                                                             Unsupported_StatusID); // MsgID error
                        break;
                    default:
                        simputshex32("Unknown OCCP command received: ", command_word.msg_id);
                        smc_post_code_set_occp_state(POST_CODE_OCCP_STATE_ERROR);
                        smc_post_code_set_error(POST_CODE_ERROR_COMMAND);
                        smc_status_report(
                            SMC_STATUS_TYPE_ERROR,
                            SMC_OCCP_ERROR_WITH_DATA(SMC_OCCP_ERROR_CMD_UNKNOWN,
                                                     command_word.msg_id)); /* Unknown command */
                        ret = smc_occp_handle_error_response(drv, drv_type, command_word,
                                                             Invalid_Msgid); // MsgID error
                        break;
                    }
                } else {

                    simputshex16("OCCP: Invalid Application received: ", command_word.app_id);
                    smc_post_code_set_occp_state(POST_CODE_OCCP_STATE_ERROR);
                    smc_post_code_set_error(POST_CODE_ERROR_COMMAND);
                    smc_status_report(
                        SMC_STATUS_TYPE_ERROR,
                        SMC_OCCP_ERROR_WITH_DATA(SMC_OCCP_ERROR_CMD_UNKNOWN,
                                                 command_word.app_id)); /* Unknown command */
                    ret =
                        smc_occp_handle_error_response(drv, drv_type, command_word, Invalid_Appid);
                }
            }
        } else {
            // Set error state for command read failure
            smc_post_code_set_occp_state(POST_CODE_OCCP_STATE_ERROR);
            smc_post_code_set_error(POST_CODE_ERROR_COMMAND);

            if (occp_status == OCCP_ERROR_TRANSPORT_INCOMPLETE ||
                occp_status == OCCP_ERROR_TRANSPORT_OVERFLOW) {
                // If the first command read is incomplete, flush the fifo to clear any partial data
                // and wait for a new command
                bool hdr_valid = 0;
                // Handle transport error for incomplete/overflow reads
                smc_post_code_set_occp_state(POST_CODE_OCCP_STATE_ERROR);
                smc_post_code_set_error(POST_CODE_ERROR_INTERFACE);
                smc_occp_handle_transport_error(drv, drv_type, command_packet, hdr_valid,
                                                occp_status);
            }
            simputs("Error reading OCCP command from bus\n");
            occp_status_set_error_code(occp_status);
            smc_status_report(SMC_STATUS_TYPE_ERROR,
                              SMC_OCCP_ERROR_CMD_READ); /* Command read error */
            /* Handle interface error and potentially unlatch */
            if (smc_occp_handle_interface_error()) {
                simputs("OCCP: Interface unlatched due to errors, retrying with all interfaces\n");
            }
            continue; /* Retry reading the command. */
        }
        if (ret == OCCP_ERROR_NONE) {
            /* Reset error count on successful command */
            smc_post_code_set_occp_state(POST_CODE_OCCP_STATE_COMPLETE);
            smc_post_code_set_error(POST_CODE_ERROR_NONE);
            g_interface_error_count = 0;
        } else {
            /* Set error state for command execution failure */
            smc_post_code_set_occp_state(POST_CODE_OCCP_STATE_ERROR);
            smc_post_code_set_error(POST_CODE_ERROR_COMMAND);
            occp_status_set_error_code(ret);
            smc_status_report(
                SMC_STATUS_TYPE_ERROR,
                SMC_OCCP_ERROR_WITH_DATA(SMC_OCCP_ERROR_CMD_FAILED, ret)); /* Command failed */
            if (!error_response_sent) {
                // avoid flushing the fifo twice (already done if error response was sent)
                smc_occp_flush_interface_fifo(drv, drv_type);
            }

            /* Handle interface error for command execution failures */
            smc_occp_handle_interface_error();
        }
        occp_status_increment_command_count();
    }
}

static occp_error_code_t smc_occp_handle_error_response(interface_driver_t drv,
                                                        driver_type_t drv_type, occp_header hdr,
                                                        Occp_ErrMsgID err) {
    simputshex16("OCCP: Error code to report: ", (uint16_t)err);
    /* Fill the occp_error_resp struct fields correctly. */
    error_response err_response;
    // Access header fields through the hdr member
    if (err == Corrupt_header) {
        err_response.hdr.app_id = 0xFF;
        err_response.hdr.msg_id = 0xFF;
    } else {
        err_response.hdr.app_id = hdr.app_id;
        err_response.hdr.msg_id = hdr.msg_id;
    }
    err_response.hdr.flags = hdr.flags;
    err_response.hdr.error = 1;                 // Indicate error status
    err_response.hdr.length = sizeof(uint32_t); // Length of error_code field
    err_response.body_crc_present = true;       // Error response includes body CRC
    err_response.i3c_flags = 0;                 // Reserved
    // Use the correct field for error code (if the struct is defined as 'err_code' or similar)
    err_response.err_code = (uint32_t)err;
    // Calculate header CRC if your header struct has a 'crc' field
    uint8_t *hdr_ptr = ((uint8_t *)&err_response) + 1;
    err_response.hdr_crc = calculate_crc8(hdr_ptr, 7); // CRC over 7 bytes after hdr_crc
    // Calculate body CRC
    uint8_t *body_ptr =
        (uint8_t *)&err_response + 8;   // Point to the start of the body (after header)
    size_t body_len = sizeof(uint32_t); // Length of the body (error_code field)
    err_response.body_crc = calculate_crc8(body_ptr, body_len);

    /*IMPORTANT: When header validation fails (corrupted CRC, invalid app/msg IDs),we must flush the
    interface FIFO to prevent body data from the failed command from being interpreted as the next
    command header. This prevents the ROM from entering an unpredictable state due to header
    corruption.*/
    smc_occp_flush_interface_fifo(drv, drv_type);

    // Set response ready state before sending error response
    smc_post_code_set_occp_state(POST_CODE_OCCP_STATE_RESP_READY);

    /* Send error response to host after clearing the rx fifo */
    smc_occp_send_to_bus(drv, drv_type, (uint8_t *)&err_response, sizeof(err_response),
                         TRANSPORT_TIMEOUT);

    /* Mark that error response was sent and FIFO was already flushed */
    error_response_sent = 1;

    return OCCP_ERROR_INVALID_COMMAND;
}

static int smc_occp_handle_get_boot_version(interface_driver_t drv, driver_type_t drv_type,
                                            occp_header hdr, bool body_crc_present) {
    get_version_response response;
    simputs("Handling GET_BOOT_VERSION command\n");

    // Check for length of the command
    uint16_t count_len_bytes = hdr.length; // Length of the body as per header
    if (count_len_bytes != GET_VER_HEADER_LENGTH) {
        simputshex16("Error in Get Version Command length, Ignoring GET_VERSION Command: ",
                     count_len_bytes);
        smc_occp_handle_error_response(drv, drv_type, hdr, Invalid_header);
        smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_CMD_FAILED);
        return OCCP_ERROR_INVALID_COMMAND;
    }

    // check to ensure no extra bytes are present in the FIFO
    int flushed_bytes = smc_occp_flush_interface_fifo(drv, drv_type);
    if (flushed_bytes != 0) {
        simputs("Oversize message for GET_VERSION command\n");
        smc_occp_handle_error_response(drv, drv_type, hdr, Oversize_msg);
        return OCCP_ERROR_TRANSPORT_OVERFLOW;
    }

    // Creating get version response header
    response.body_crc_present = true; // Body CRC for version response
    response.i3c_flags = 0;           // Reserved
    response.hdr.error = 0;           // No error
    response.hdr.flags = hdr.flags;   // Echo back flags from request
    response.hdr.app_id = hdr.app_id; // Echo back app_id from request
    response.hdr.msg_id = hdr.msg_id; // Echo back msg_id from request
    response.hdr.length = 4;          // Length of status field (4 bytes)
    // Calculate header CRC
    uint8_t *hdr_ptr = ((uint8_t *)&response) + 1;
    response.hdr_crc = calculate_crc8(hdr_ptr, 7); // CRC over 7 bytes after hdr_crc
    // Creating get version response
    response.major_version = BOOT_VERSION_MAJOR;
    response.minor_version = BOOT_VERSION_MINOR;
    response.patch_version = BOOT_VERSION_PATCH;
    // Calculate body CRC over exactly 'length' bytes of body (exclude CRC byte)
    uint8_t *body_ptr = (uint8_t *)&response + 8; // Start of body (after 8-byte packet header)
    size_t body_len = response.hdr.length;        // 4-byte version body
    response.body_crc = calculate_crc8(body_ptr, body_len);

    // Set response ready state before sending
    smc_post_code_set_occp_state(POST_CODE_OCCP_STATE_RESP_READY);

    return smc_occp_send_to_bus(drv, drv_type, (uint8_t *)&response, sizeof(response),
                                TRANSPORT_TIMEOUT);
}
static int smc_occp_handle_get_version(interface_driver_t drv, driver_type_t drv_type,
                                       occp_header hdr, bool body_crc_present) {
    get_version_response response;
    simputs("Handling GET_VERSION command\n");
    // check for length of the command
    uint16_t count_len_bytes = hdr.length; // Length of the body as per header
    if (count_len_bytes != GET_VER_HEADER_LENGTH) {
        simputshex16("Error in Get Version Command length, Ignoring GET_VERSION Command: ",
                     count_len_bytes);
        smc_occp_handle_error_response(drv, drv_type, hdr, Invalid_header);
        smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_CMD_FAILED);
        return OCCP_ERROR_INVALID_COMMAND;
    }

    // check to ensure no extra bytes are present in the FIFO
    int flushed_bytes = smc_occp_flush_interface_fifo(drv, drv_type);
    if (flushed_bytes != 0) {
        simputs("Oversize message for GET_VERSION command\n");
        smc_occp_handle_error_response(drv, drv_type, hdr, Oversize_msg);
        return OCCP_ERROR_TRANSPORT_OVERFLOW;
    }

    // Creating get version response header
    response.body_crc_present = true; // Body CRC for version response
    response.i3c_flags = 0;           // Reserved
    response.hdr.error = 0;           // No error
    response.hdr.flags = hdr.flags;   // Echo back flags from request
    response.hdr.app_id = hdr.app_id; // Echo back app_id from request, will be 0x0
    response.hdr.msg_id = hdr.msg_id; // Echo back msg_id from request, will be 0x0
    response.hdr.length = 4;          // Length of version fields (4 bytes)
    // Calculate header CRC
    uint8_t *hdr_ptr = ((uint8_t *)&response) + 1;
    response.hdr_crc = calculate_crc8(hdr_ptr, 7); // CRC over 7 bytes after hdr_crc
    // Creating get version response
    response.major_version = OCCP_VERSION_MAJOR;
    response.minor_version = OCCP_VERSION_MINOR;
    response.patch_version = OCCP_VERSION_PATCH;
    // Calculate body CRC over exactly 'length' bytes of body (exclude CRC byte)
    uint8_t *body_ptr = (uint8_t *)&response + 8; // Start of body (after 8-byte packet header)
    size_t body_len = response.hdr.length;        // 4-byte version body
    response.body_crc = calculate_crc8(body_ptr, body_len);

    // Set response ready state before sending
    smc_post_code_set_occp_state(POST_CODE_OCCP_STATE_RESP_READY);

    return smc_occp_send_to_bus(drv, drv_type, (uint8_t *)&response, sizeof(response),
                                TRANSPORT_TIMEOUT);
}

static int smc_occp_handle_get_status(interface_driver_t drv, driver_type_t drv_type,
                                      occp_header hdr, bool body_crc_present) {
    if (!smc_strap_is_status_rpt_disable()) {
        uint32_t occp_status_reg = 0;
        uint32_t status = 0;
        uint8_t status_buf[GET_STAT_HEADER_LENGTH + 1] = {0};
        uint16_t status_id = 0;
        Occp_ErrMsgID body_validation = Corrupt_Data;
        occp_error_code_t command_status = OCCP_ERROR_GENERAL;
        get_status_response response;

        uint16_t count_len_bytes = hdr.length;

        // Check for correct command length
        if (count_len_bytes != GET_STAT_HEADER_LENGTH) {
            simputshex16("Error in Status ID length, Ignoring GET_STATUS Command: ",
                         count_len_bytes);
            smc_occp_handle_error_response(drv, drv_type, hdr, Invalid_header);
            smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_CMD_FAILED);
            return OCCP_ERROR_INVALID_COMMAND;
        }

        // Add CRC length if present
        if (body_crc_present) {
            if (count_len_bytes > PACKET_SIZE_FOR_CRC8)
                count_len_bytes += sizeof(uint32_t); // Add crc32 length
            else
                count_len_bytes += sizeof(uint8_t); // Add crc8 length
        }

        // Read the command
        command_status = smc_occp_read_from_bus_4byte_aligned_or_complete_stream(
            drv, drv_type, (uint8_t *)&status_buf, count_len_bytes, TRANSPORT_TIMEOUT, 0, 0);

        if (command_status == OCCP_ERROR_NONE) {
            body_validation =
                smc_occp_validate_body((uint8_t *)&status_buf, count_len_bytes, body_crc_present);
            if (body_validation == NoErr) {
                memcpy(&status_id, &status_buf, hdr.length);
                simputshex16("GET_STATUS command with Status ID: ", status_id);
                if (status_id <= 0xFF) {
                    occp_status_reg = occp_status_get();
                    switch (status_id) {
                    case 0:
                        status = ((uint32_t)(occp_status_reg & 0xF)) |
                                 ((uint32_t)SMC_STATUS_FW_ID_SMC_BL0 << 16) |
                                 ((uint32_t)SMC_STATUS_TYPE_STATUS << 24);
                        simputshex32("Boot status: ", status);
                        break;
                    case 1:
                        status = ((uint32_t)((occp_status_reg >> 4) & 0xF)) |
                                 ((uint32_t)SMC_STATUS_FW_ID_SMC_BL0 << 16) |
                                 ((uint32_t)SMC_STATUS_TYPE_STATUS << 24);
                        break;
                    case 2:
                        status = (uint32_t)((occp_status_reg >> 8) & 0xFFFF);
                        status |= ((uint32_t)SMC_STATUS_FW_ID_SMC_BL0 << 16);
                        status |= ((uint32_t)SMC_STATUS_TYPE_STATUS << 24);
                        break;
                    case 3:
                        status = (uint32_t)((occp_status_reg >> 16) & 0xFF);
                        status |= ((uint32_t)SMC_STATUS_FW_ID_SMC_BL0 << 16);
                        status |= ((uint32_t)SMC_STATUS_TYPE_ERROR << 24);
                        break;
                    default:
                        simputshex16("Error in Status ID, Ignoring GET_STATUS Command: ",
                                     status_id);
                        smc_occp_handle_error_response(drv, drv_type, hdr, Unsupported_StatusID);
                        smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_CMD_FAILED);
                        return OCCP_ERROR_INVALID_COMMAND;
                    }
                } else if (status_id == 0x8000) {
                    sep_status_read(&status);
                    simputshex32("SEP status read: ", status);
                } else if (status_id == 0x8001) {
                    smc_status_read(&status);
                    simputshex32("SMC status read: ", status);
                } else {
                    simputshex16("Error in Status ID, Ignoring GET_STATUS Command: ", status_id);
                    smc_occp_handle_error_response(drv, drv_type, hdr, Unsupported_StatusID);
                    smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_CMD_FAILED);
                    return OCCP_ERROR_INVALID_COMMAND;
                }
            } else {
                simputs("Error in Status ID, Ignoring GET_STATUS Command");
                smc_occp_handle_error_response(drv, drv_type, hdr, body_validation);
                smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_CMD_FAILED);
                return OCCP_ERROR_CRC;
            }

            response.body_crc_present = true;
            response.i3c_flags = 0;
            response.hdr.error = 0;
            response.hdr.flags = hdr.flags;
            response.hdr.app_id = hdr.app_id;
            response.hdr.msg_id = hdr.msg_id;
            response.hdr.length = 4;
            uint8_t *hdr_ptr = ((uint8_t *)&response) + 1;
            response.hdr_crc = calculate_crc8(hdr_ptr, 7);
            response.status = status;
            simputshex32("GET_STATUS response with Status: ", response.status);
            uint8_t *body_ptr = (uint8_t *)&response + 8;
            size_t body_len = response.hdr.length;
            response.body_crc = calculate_crc8(body_ptr, body_len);
            // Set response ready state before sending
            smc_post_code_set_occp_state(POST_CODE_OCCP_STATE_RESP_READY);

            return smc_occp_send_to_bus(drv, drv_type, (uint8_t *)&response, sizeof(response),
                                        TRANSPORT_TIMEOUT);
        } else if (command_status == OCCP_ERROR_TRANSPORT_INCOMPLETE) {
            simputs("Error reading GET_STATUS command from bus (incomplete)\n");
            smc_occp_handle_error_response(drv, drv_type, hdr, Incomplete_msg);
            return OCCP_ERROR_TRANSPORT_INCOMPLETE;
        } else if (command_status == OCCP_ERROR_TRANSPORT_OVERFLOW) {
            simputs("Error reading GET_STATUS command from bus (oversize)\n");
            smc_occp_handle_error_response(drv, drv_type, hdr, Oversize_msg);
            return OCCP_ERROR_TRANSPORT_OVERFLOW;
        }
    } else {
        simputs("Status reporting is disabled. Ignoring GET_STATUS command\n");
        smc_occp_handle_error_response(drv, drv_type, hdr, Unsupported_StatusID);
        return OCCP_ERROR_INVALID_COMMAND;
    }
    return OCCP_ERROR_INVALID_COMMAND;
}

static int smc_occp_handle_write(interface_driver_t drv, driver_type_t drv_type, occp_header hdr,
                                 bool body_crc_present) {
    simputs("Handling WRITE command\n");
    uint16_t count_len_bytes = hdr.length;
    uint64_t addr;
    packet_header write_response_header;
    Occp_ErrMsgID body_validation = Corrupt_Data;

    simputshex16("WRITE command length in bytes: ", count_len_bytes);
    /* Check for zero-length transfer */
    if (count_len_bytes == 0) {
        simputs("WRITE command with zero length not allowed\n");
        smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_WRITE_OVERFLOW);
        smc_occp_handle_error_response(drv, drv_type, hdr, Invalid_header);
        return OCCP_ERROR_BUFFER_OVERFLOW;
    }
    if (count_len_bytes < WRITE_HEADER_LENGTH) {
        simputshex16("WRITE command length shorter than header: ", count_len_bytes);
        smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_WRITE_OVERFLOW);
        smc_occp_handle_error_response(drv, drv_type, hdr, Invalid_header);
        return OCCP_ERROR_BUFFER_OVERFLOW;
    }
    /* Check for Max length overflow */
    if (count_len_bytes > OCCP_MAX_MSG_SIZE) {
        simputshex32("WRITE count would cause overflow: ", count_len_bytes);
        simputshex16("Maximum allowed count: ", OCCP_MAX_MSG_SIZE);
        smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_WRITE_OVERFLOW);
        smc_occp_handle_error_response(drv, drv_type, hdr, Invalid_header);
        return OCCP_ERROR_BUFFER_OVERFLOW;
    }

    if (body_crc_present) {
        if (count_len_bytes > PACKET_SIZE_FOR_CRC8) {
            count_len_bytes = count_len_bytes + sizeof(uint32_t); // Account for 4-byte CRC
        } else {
            count_len_bytes = count_len_bytes + sizeof(uint8_t); // Account for 1-byte CRC
        }
    }
    /* WRITE command format per spec: 16 bit reserved + 5 bit attr +11 bit len + 8-byte address +
     * data +crc*/
    occp_error_code_t ret = smc_occp_read_from_bus_4byte_aligned_or_complete_stream(
        drv, drv_type, g_occp_data_buffer, count_len_bytes, TRANSPORT_TIMEOUT, 0, 0);
    if (ret != OCCP_ERROR_NONE) {
        simputs("Error reading WRITE command header from bus\n");
        if (ret == OCCP_ERROR_TRANSPORT_INCOMPLETE) {
            smc_occp_handle_error_response(drv, drv_type, hdr,
                                           Incomplete_msg); // Incomplete transaction
            smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_CMD_FAILED);
            return OCCP_ERROR_TRANSPORT_INCOMPLETE;
        } else if (ret == OCCP_ERROR_TRANSPORT_OVERFLOW) {
            smc_occp_handle_error_response(drv, drv_type, hdr,
                                           Oversize_msg); // Oversize transaction
            smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_CMD_FAILED);
            return OCCP_ERROR_TRANSPORT_OVERFLOW;
        }
        return ret;
    }
    simputshex16("Body Crc present flag: ", body_crc_present);
    body_validation = smc_occp_validate_body(g_occp_data_buffer, count_len_bytes, body_crc_present);
    if (body_validation != NoErr) {
        simputs("Error in WRITE command body, Ignoring WRITE Command \n");
        smc_occp_handle_error_response(drv, drv_type, hdr, body_validation); // Body error
        smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_CMD_FAILED);
        return OCCP_ERROR_INVALID_COMMAND;
    }
    // Use memcpy for little-endian 16-bit extraction
    // OCCP WRITE command format:
    // - Addr (bits 95-32): 64-bit write address.
    // - WLen (bits 106-96): 11-bit write length in bytes.
    // - AddrAttr (bits 111-107): 5-bit address attributes.
    // - Reserved (bits 127-112): 16 bits reserved.
    // Extract address, write size, attr, and reserved bytes
    memcpy(&addr, g_occp_data_buffer, sizeof(addr));
    uint16_t write_size;
    memcpy(&write_size, &g_occp_data_buffer[8], sizeof(write_size));
    write_size &= 0x7FF; // 11-bit length field

    if (write_size == 0) {
        simputs("WRITE command with zero length not allowed\n");
        smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_WRITE_OVERFLOW);
        smc_occp_handle_error_response(drv, drv_type, hdr, Invalid_header); // was Invalid_req_len
        return OCCP_ERROR_BUFFER_OVERFLOW;
    }
    if (write_size > OCCP_MAX_WR_SIZE) {
        simputshex16("WRITE command size exceeds maximum after bounds check: ", write_size);
        smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_WRITE_OVERFLOW);
        smc_occp_handle_error_response(drv, drv_type, hdr, Invalid_header); // was Invalid_req_len
        return OCCP_ERROR_BUFFER_OVERFLOW;
    }

    /* Check if address is 32-bit or 64-bit aligned. If not, return Invalid_Address error code.
     * Any address that’s 64-bit aligned (multiple of 8) is also a multiple of 4, so it passes.
     * Only addresses that are not divisible by 4 will fail.
     */
    if (addr % 4 != 0) {
        simputs("Write address is not 32-bit aligned\n");
        smc_post_code_set_error(POST_CODE_ERROR_ACCESS);
        smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_WRITE_ACCESS_DENIED);
        smc_occp_handle_error_response(drv, drv_type, hdr, Invalid_Address);
        return OCCP_ERROR_ACCESS_VIOLATION;
    }

    simputshex32("Count in num of bytes: ", count_len_bytes);
    simputshex16("Number of bytes to write: ", write_size);
    simputshex64("Address to write to: ", addr);

    uint8_t *data_buffer_ptr = g_occp_data_buffer + 12; // The rest then is data
    ret = smc_occp_check_addr_access_allowed(addr, write_size);
    if (ret != OCCP_ERROR_NONE) {
        simputshex16("Write denied. Access check returned code: ", ret);
        smc_post_code_set_error(POST_CODE_ERROR_ACCESS);
        smc_status_report(SMC_STATUS_TYPE_ERROR,
                          SMC_OCCP_ERROR_WITH_NIBBLE(SMC_OCCP_ERROR_WRITE_ACCESS_DENIED,
                                                     ret)); /* WRITE access denied */
        smc_occp_handle_error_response(drv, drv_type, hdr, Invalid_Address); // Addr is invalid
        simputshex16("Write command processed Return code: ", ret);
        return ret;
    } else {
        /* If write sizes correspond to 32-bit or 64-bit values, we may be writing registers so do
         * so in full width. */
        if (write_size == sizeof(uint32_t)) {
            /* stream will come LE so use as-is. */
            uint32_t word;
            memcpy(&word, data_buffer_ptr, sizeof(word));
            simputshex32("Writing 32-bit value: ", word);
            write_reg(addr, word);
        } else if (write_size == sizeof(uint64_t) && (addr % 8 == 0)) {
            /* Only use write64_reg if address is 8-byte aligned. */
            uint64_t word;
            memcpy(&word, data_buffer_ptr, sizeof(word));
            simputshex64("Writing 64-bit value: ", word);
            write64_reg(addr, word);
        } else {
            for (int i = 0; i < write_size; i++) {
                /* Write each byte in LE order. */
                uint8_t byte = data_buffer_ptr[i];
                volatile uint8_t *p_addr = (volatile uint8_t *)(uintptr_t)addr;
                *p_addr = byte;
                addr++;
            }
        }
    }
    simputshex16("Write command processed Return code: ", ret);
    write_response_header.body_crc_present = false; // No body CRC for write response
    write_response_header.i3c_flags = 0;            // Reserved
    write_response_header.hdr.error = (ret == OCCP_ERROR_NONE) ? 0 : 1; // Indicate error status
    write_response_header.hdr.flags = hdr.flags;   // Echo back flags from request
    write_response_header.hdr.app_id = hdr.app_id; // Echo back app_id from request
    write_response_header.hdr.msg_id = hdr.msg_id; // Echo back msg_id from request
    write_response_header.hdr.length = 0;          // No body for write response
    // Calculate header CRC
    uint8_t *hdr_ptr = ((uint8_t *)&write_response_header) + 1;
    write_response_header.hdr_crc = calculate_crc8(hdr_ptr, 7);
    simputshex16("Write response header crc: ", write_response_header.hdr_crc);

    // Set response ready state before sending
    smc_post_code_set_occp_state(POST_CODE_OCCP_STATE_RESP_READY);
    return smc_occp_send_to_bus(drv, drv_type, (uint8_t *)&write_response_header,
                                sizeof(write_response_header), TRANSPORT_TIMEOUT);
}

static int smc_occp_handle_read(interface_driver_t drv, driver_type_t drv_type, occp_header hdr,
                                bool body_crc_present) {
    simputs("Handling READ command\n");
    uint16_t count_len_bytes = hdr.length;
    uint64_t addr;
    Occp_ErrMsgID body_validation = Corrupt_Data;
    packet_header read_response_header;

    /* Check for command length  */
    if (count_len_bytes != READ_HEADER_LENGTH) {
        simputshex16("Error in Read Command length, Ignoring READ Command: ", count_len_bytes);
        smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_READ_OVERFLOW);
        smc_occp_handle_error_response(drv, drv_type, hdr, Invalid_header);
        return OCCP_ERROR_BUFFER_OVERFLOW;
    }
    if (body_crc_present) {
        if (count_len_bytes > PACKET_SIZE_FOR_CRC8) {
            count_len_bytes = count_len_bytes + sizeof(uint32_t); // Account for 4-byte CRC
        } else {
            count_len_bytes = count_len_bytes + sizeof(uint8_t); // Account for 1-byte CRC
        }
    }

    /* READ data */
    occp_error_code_t ret = smc_occp_read_from_bus_4byte_aligned_or_complete_stream(
        drv, drv_type, g_occp_data_buffer, count_len_bytes, TRANSPORT_TIMEOUT, 0, 0);
    if (ret != OCCP_ERROR_NONE) {
        simputs("Error reading READ command from bus\n");
        if (ret == OCCP_ERROR_TRANSPORT_INCOMPLETE) {
            smc_occp_handle_error_response(drv, drv_type, hdr,
                                           Incomplete_msg); // Incomplete transaction
            smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_CMD_FAILED);
            return OCCP_ERROR_TRANSPORT_INCOMPLETE;
        } else if (ret == OCCP_ERROR_TRANSPORT_OVERFLOW) {
            smc_occp_handle_error_response(drv, drv_type, hdr,
                                           Oversize_msg); // Oversize transaction
            smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_CMD_FAILED);
            return OCCP_ERROR_TRANSPORT_OVERFLOW;
        }
        return ret;
    }

    body_validation = smc_occp_validate_body(g_occp_data_buffer, count_len_bytes, body_crc_present);
    if (body_validation == NoErr) {

        // Optimized: Use memcpy for little-endian extraction
        /**
         * Extracts fields from the OCCP data buffer:
         * - Addr (bits 95-32): 64-bit read address
         * - RLen (bits 106-96): 11-bit read length in bytes.
         * - AddrAttr (bits 111-107): 5-bit address attributes.
         */
        memcpy(&addr, g_occp_data_buffer, sizeof(addr));
        uint16_t num_bytes_to_send;
        memcpy(&num_bytes_to_send, &g_occp_data_buffer[8], sizeof(num_bytes_to_send));
        num_bytes_to_send &= 0x7FF; // 11-bit length field

        if (num_bytes_to_send == 0) {
            simputs("READ command with zero length not allowed\n");
            smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_READ_OVERFLOW);
            smc_occp_handle_error_response(drv, drv_type, hdr,
                                           Invalid_header); // was Invalid_req_len
            return OCCP_ERROR_BUFFER_OVERFLOW;
        }

        if (num_bytes_to_send > OCCP_MAX_RD_SIZE) {
            simputshex16("READ command size exceeds maximum after bounds check: ",
                         num_bytes_to_send);
            smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_READ_OVERFLOW);
            smc_occp_handle_error_response(drv, drv_type, hdr,
                                           Invalid_header); // was Invalid_req_len
            return OCCP_ERROR_BUFFER_OVERFLOW;
        }

        /* Check if address is 32-bit or 64-bit aligned. If not, return Invalid_Address error code.
         * Any address that’s 64-bit aligned (multiple of 8) is also a multiple of 4, so it passes.
         * Only addresses that are not divisible by 4 will fail.
         */
        if (addr % 4 != 0) {
            simputs("Read address is not 32-bit aligned\n");
            smc_post_code_set_error(POST_CODE_ERROR_ACCESS);
            smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_READ_ACCESS_DENIED);
            smc_occp_handle_error_response(drv, drv_type, hdr, Invalid_Address);
            return OCCP_ERROR_ACCESS_VIOLATION;
        }

        simputshex32("Count in bytes: ", count_len_bytes);
        simputshex16("Number of bytes to read: ", num_bytes_to_send);
        simputshex64("Address to read from: ", addr);

        ret = smc_occp_check_addr_access_allowed(addr, num_bytes_to_send);
        if (ret != OCCP_ERROR_NONE) {
            simputshex16("Read denied. Returning 0s. Access check returned code: ", ret);
            smc_post_code_set_error(POST_CODE_ERROR_ACCESS);
            smc_status_report(SMC_STATUS_TYPE_ERROR,
                              SMC_OCCP_ERROR_WITH_NIBBLE(SMC_OCCP_ERROR_READ_ACCESS_DENIED,
                                                         ret)); /* READ access denied */
            smc_occp_handle_error_response(drv, drv_type, hdr, Invalid_Address); // Addr is invalid
            simputshex16("Read command processed Return code: ", ret);
            return ret;
        } else {
            read_response_header.body_crc_present = true;
            read_response_header.i3c_flags = 0;           // Reserved
            read_response_header.hdr.error = 0;           // No error
            read_response_header.hdr.flags = hdr.flags;   // Echo back flags from request
            read_response_header.hdr.app_id = hdr.app_id; // Echo back app_id from request
            read_response_header.hdr.msg_id = hdr.msg_id; // Echo back msg_id from request
            // Header length should reflect only the body size (data bytes), not CRC
            read_response_header.hdr.length = num_bytes_to_send;
            // Calculate header CRC
            uint8_t *hdr_ptr = ((uint8_t *)&read_response_header) + 1;
            read_response_header.hdr_crc =
                calculate_crc8(hdr_ptr, 7); // CRC over 7 bytes after hdr_crc
            simputshex16("Read response header crc: ", read_response_header.hdr_crc);

            // Create read response body viz. read data.
            /* Explicit size check in case we are reading registers with strict access widths. */
            if (num_bytes_to_send == (sizeof(uint32_t))) {
                uint32_t word = read_reg(addr);
                memcpy(g_occp_data_buffer, &word, sizeof(uint32_t));
                simputshex32("Read 32-bit value ", word);
            } else if (num_bytes_to_send == sizeof(uint64_t) && (addr % 8 == 0)) {
                uint64_t word = read64_reg(addr);
                memcpy(g_occp_data_buffer, &word, sizeof(uint64_t));
                simputshex64("Read 64-bit value: ", word);
            } else {
                volatile uint8_t *p_addr = (volatile uint8_t *)(uintptr_t)addr;
                uint8_t *data_buffer_ptr = g_occp_data_buffer;
                for (int i = 0; i < num_bytes_to_send; i++) {
                    data_buffer_ptr[i] = p_addr[i];
                }
            }
            /* Calculate body CRC  */
            uint8_t *body_ptr = g_occp_data_buffer;
            size_t body_len = num_bytes_to_send;
            uint32_t body_crc32 = 0;
            uint8_t body_crc8 = 0;
            if (num_bytes_to_send > PACKET_SIZE_FOR_CRC8) {
                body_crc32 = calculate_crc32(body_ptr, body_len);
                simputshex32("Calculated 32-bit body CRC for read data: ", body_crc32);
                memcpy(g_occp_data_buffer + num_bytes_to_send, &body_crc32, sizeof(body_crc32));
                num_bytes_to_send += sizeof(body_crc32); // Include CRC in total bytes to send
            } else {
                body_crc8 = calculate_crc8(body_ptr, body_len);
                simputshex16("Calculated 8-bit body CRC for read data: ", body_crc8);
                memcpy(g_occp_data_buffer + num_bytes_to_send, &body_crc8, sizeof(body_crc8));
                num_bytes_to_send += sizeof(body_crc8); // Include CRC in total bytes to send
            }

            // Combine header and body into one packet and send
            uint8_t
                packet_buffer[sizeof(read_response_header) + OCCP_MAX_RD_SIZE + sizeof(uint32_t)];
            memcpy(packet_buffer, &read_response_header,
                   sizeof(read_response_header)); // First part of packet is header + header crc
            memcpy(packet_buffer + sizeof(read_response_header), g_occp_data_buffer,
                   num_bytes_to_send); // Second part is data + data crc
            /*for (size_t i=0; i < (sizeof(read_response_header) + num_bytes_to_send); i++)
            {
                simputshex16("OCCP: Handling READ Packet data byte: ", packet_buffer[i]);
            }*/
            // Set response ready state before sending
            smc_post_code_set_occp_state(POST_CODE_OCCP_STATE_RESP_READY);
            return smc_occp_send_to_bus(
                drv, drv_type, packet_buffer, sizeof(read_response_header) + num_bytes_to_send,
                TRANSPORT_TIMEOUT); // Combined header and body send to transport layer
        }
    } else {
        simputs("Error in READ command body, Ignoring READ Command \n");
        smc_occp_handle_error_response(drv, drv_type, hdr, body_validation); // Body error
        smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_CMD_FAILED);
        return OCCP_ERROR_INVALID_COMMAND;
    }
    return OCCP_ERROR_CRC;
}

static int smc_occp_handle_jump(interface_driver_t drv, driver_type_t drv_type, occp_header hdr,
                                bool body_crc_present) {
    simputs("Handling JUMP command\n");
    uint64_t address;
    packet_header jump_response_header;
    Occp_ErrMsgID body_validation;

    uint16_t count_len_bytes = hdr.length;
    /* Check for command length  */
    if (count_len_bytes != EXEC_IMG_HEADER_LENGTH) {
        simputshex16("Error in Execute image Command length, Ignoring Execute image Command: ",
                     count_len_bytes);
        smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_READ_OVERFLOW);
        smc_occp_handle_error_response(drv, drv_type, hdr, Invalid_header);
        return OCCP_ERROR_BUFFER_OVERFLOW;
    }
    if (body_crc_present) {
        if (count_len_bytes > PACKET_SIZE_FOR_CRC8) {
            count_len_bytes += sizeof(uint32_t); // Account for 4-byte CRC
        } else {
            count_len_bytes += sizeof(uint8_t); // Account for 1-byte CRC
        }
    }

    occp_error_code_t ret = smc_occp_read_from_bus_4byte_aligned_or_complete_stream(
        drv, drv_type, g_occp_data_buffer, count_len_bytes, TRANSPORT_TIMEOUT, 0, 0);
    if (ret != OCCP_ERROR_NONE) {
        simputs("Error reading Execute command header from bus\n");
        if (ret == OCCP_ERROR_TRANSPORT_INCOMPLETE) {
            smc_occp_handle_error_response(drv, drv_type, hdr,
                                           Incomplete_msg); // Incomplete transaction
            smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_JUMP_READ_FAILED);
            return OCCP_ERROR_TRANSPORT_INCOMPLETE;
        } else if (ret == OCCP_ERROR_TRANSPORT_OVERFLOW) {
            smc_occp_handle_error_response(drv, drv_type, hdr,
                                           Oversize_msg); // Oversize transaction
            smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_JUMP_READ_FAILED);
            return OCCP_ERROR_TRANSPORT_OVERFLOW;
        }
        return ret;
    }
    body_validation = smc_occp_validate_body(g_occp_data_buffer, count_len_bytes, body_crc_present);
    if (body_validation != NoErr) {
        simputs("Error in JUMP command body, Ignoring JUMP Command");
        smc_occp_handle_error_response(drv, drv_type, hdr, body_validation); // Body error
        smc_status_report(SMC_STATUS_TYPE_ERROR,
                          SMC_OCCP_ERROR_JUMP_READ_FAILED); /* JUMP failed - read error */
        return OCCP_ERROR_INVALID_COMMAND;
    }
    /* Extract address (8 bytes) in little-endian format as per spec */
    address = (uint64_t)g_occp_data_buffer[7] << 56 | (uint64_t)g_occp_data_buffer[6] << 48 |
              (uint64_t)g_occp_data_buffer[5] << 40 | (uint64_t)g_occp_data_buffer[4] << 32 |
              (uint64_t)g_occp_data_buffer[3] << 24 | (uint64_t)g_occp_data_buffer[2] << 16 |
              (uint64_t)g_occp_data_buffer[1] << 8 | (uint64_t)g_occp_data_buffer[0];

    if (!smc_security_is_secure_mode()) {
        /* Validate jump address before alignment */
        if (address == 0) {
            simputs("Jump to NULL address not allowed\n");
            smc_post_code_set_error(POST_CODE_ERROR_ACCESS);
            smc_occp_handle_error_response(drv, drv_type, hdr, Invalid_Address);
            smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_JUMP_READ_FAILED);
            return OCCP_ERROR_ACCESS_VIOLATION;
        }

        /* Check if address is 32-bit or 64-bit aligned. If not, return Invalid_Address error code.
         * Any address that’s 64-bit aligned (multiple of 8) is also a multiple of 4, so it passes.
         * Only addresses that are not divisible by 4 will fail.
         */
        if (address % 4 != 0) {
            simputs("Jump address is not 32-bit aligned\n");
            smc_post_code_set_error(POST_CODE_ERROR_ACCESS);
            smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_JUMP_READ_FAILED);
            smc_occp_handle_error_response(drv, drv_type, hdr, Invalid_Address);
            return OCCP_ERROR_ACCESS_VIOLATION;
        }

        simputshex64("Jump address (aligned): ", address);
        ret = smc_occp_check_addr_access_allowed(
            address, sizeof(uint64_t)); /* Minimum manifest header size */
        if (ret != OCCP_ERROR_NONE) {
            simputs("JUMP: Jump address access denied\n");
            smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_JUMP_READ_FAILED);
            smc_occp_handle_error_response(drv, drv_type, hdr, Invalid_Address);
            return OCCP_ERROR_ACCESS_VIOLATION;
        }

        /* Report jump execution */
        jump_response_header.body_crc_present = false; // No body CRC for jump response
        jump_response_header.i3c_flags = 0;            // Reserved
        jump_response_header.hdr.error = 0;            // No error
        jump_response_header.hdr.flags = hdr.flags;    // Echo back flags from request
        jump_response_header.hdr.app_id = hdr.app_id;  // Echo back app_id from request
        jump_response_header.hdr.msg_id = hdr.msg_id;  // Echo back msg_id from request
        jump_response_header.hdr.length = 0;           // No body for jump response
        // Calculate header CRC
        uint8_t *hdr_ptr = ((uint8_t *)&jump_response_header) + 1;
        jump_response_header.hdr_crc = calculate_crc8(hdr_ptr, 7);
        // Set response ready state before sending
        smc_post_code_set_occp_state(POST_CODE_OCCP_STATE_RESP_READY);

        smc_status_report(SMC_STATUS_TYPE_STATUS,
                          SMC_OCCP_ERROR_WITH_DATA(SMC_OCCP_STATUS_JUMP_EXECUTED,
                                                   (address >> 16))); /* JUMP executed */
        smc_occp_send_to_bus(drv, drv_type, (uint8_t *)&jump_response_header,
                             sizeof(jump_response_header), TRANSPORT_TIMEOUT);
        /* Mark boot sequence complete */
        smc_post_code_set_boot_phase(POST_CODE_BOOT_PHASE_BOOT_COMPLETE);
        simputs("[MAIN] Boot sequence completed successfully\n");
        smc_status_report(SMC_STATUS_TYPE_STATUS, SMC_STATUS_BOOT_COMPLETE); /* Boot complete */

        void *jmp_address = (void *)address;
        goto *jmp_address;
    } else {
        ret = OCCP_ERROR_SECURITY_VIOLATION;
        simputs("OCCP_JUMP command received in secure mode, ignoring.\n");
        smc_post_code_set_error(POST_CODE_ERROR_INVALID_SEC_MODE);
        smc_occp_handle_error_response(drv, drv_type, hdr, Invalid_Msgid);
        smc_status_report(SMC_STATUS_TYPE_ERROR,
                          SMC_OCCP_ERROR_JUMP_SECURITY); /* JUMP blocked - security */
    }
    return ret;
}

static int smc_occp_handle_validate_boot(interface_driver_t drv, driver_type_t drv_type,
                                         occp_header hdr, bool body_crc_present) {
    simputs("Handling OCCP_VALIDATE_AND_BOOT command\n");
    uint64_t address;
    Occp_ErrMsgID body_validation;
    packet_header validate_response_header;

    uint16_t count_len_bytes = hdr.length;
    /* Check for command length  */
    if (count_len_bytes != AUTH_IMG_HEADER_LENGTH) {
        simputshex16(
            "Error in Authenticate Image Command length, Ignoring Authenticate Image Command: ",
            count_len_bytes);
        smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_READ_OVERFLOW);
        smc_occp_handle_error_response(drv, drv_type, hdr, Invalid_header);
        return OCCP_ERROR_BUFFER_OVERFLOW;
    }
    if (body_crc_present) {
        if (count_len_bytes > PACKET_SIZE_FOR_CRC8) {
            count_len_bytes += sizeof(uint32_t); // Account for 4-byte CRC
        } else {
            count_len_bytes += sizeof(uint8_t); // Account for 1-byte CRC
        }
    }

    occp_error_code_t ret = smc_occp_read_from_bus_4byte_aligned_or_complete_stream(
        drv, drv_type, g_occp_data_buffer, count_len_bytes, TRANSPORT_TIMEOUT, 0, 0);
    if (ret != OCCP_ERROR_NONE) {
        simputs("Error reading Authenticate image command header from bus\n");
        if (ret == OCCP_ERROR_TRANSPORT_INCOMPLETE) {
            smc_occp_handle_error_response(drv, drv_type, hdr,
                                           Incomplete_msg); // Incomplete transaction
            smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_VALIDATE_ADDRESS_FAILED);
            return OCCP_ERROR_TRANSPORT_INCOMPLETE;
        } else if (ret == OCCP_ERROR_TRANSPORT_OVERFLOW) {
            smc_occp_handle_error_response(drv, drv_type, hdr,
                                           Oversize_msg); // Oversize transaction
            smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_VALIDATE_ADDRESS_FAILED);
            return OCCP_ERROR_TRANSPORT_OVERFLOW;
        }
        return ret;
    } else {
        body_validation =
            smc_occp_validate_body(g_occp_data_buffer, count_len_bytes, body_crc_present);
        if (body_validation != NoErr) {
            simputs("Error in JUMP command body, Ignoring JUMP Command");
            smc_occp_handle_error_response(drv, drv_type, hdr, body_validation); // Body error
            smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_CMD_FAILED);
            return OCCP_ERROR_INVALID_COMMAND;
        }
        /* Extract address (8 bytes) in little-endian format as per spec */
        address = (uint64_t)g_occp_data_buffer[7] << 56 | (uint64_t)g_occp_data_buffer[6] << 48 |
                  (uint64_t)g_occp_data_buffer[5] << 40 | (uint64_t)g_occp_data_buffer[4] << 32 |
                  (uint64_t)g_occp_data_buffer[3] << 24 | (uint64_t)g_occp_data_buffer[2] << 16 |
                  (uint64_t)g_occp_data_buffer[1] << 8 | (uint64_t)g_occp_data_buffer[0];

        /* Validate manifest address before alignment */
        if (address == 0) {
            simputs("Manifest address cannot be NULL\n");
            smc_post_code_set_error(POST_CODE_ERROR_ACCESS);
            smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_VALIDATE_ADDRESS_FAILED);
            smc_occp_handle_error_response(drv, drv_type, hdr, Invalid_Address);
            return OCCP_ERROR_ACCESS_VIOLATION;
        }

        /* Check if address is 32-bit or 64-bit aligned. If not, return Invalid_Address error code.
         * Any address that’s 64-bit aligned (multiple of 8) is also a multiple of 4, so it passes.
         * Only addresses that are not divisible by 4 will fail.
         */
        if (address % 4 != 0) {
            simputs("Jump address is not 32-bit aligned\n");
            smc_post_code_set_error(POST_CODE_ERROR_ACCESS);
            smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_VALIDATE_ADDRESS_FAILED);
            smc_occp_handle_error_response(drv, drv_type, hdr, Invalid_Address);
            return OCCP_ERROR_ACCESS_VIOLATION;
        }

        simputshex64("Manifest address (aligned): ", address);

        /* Check if manifest address access is allowed (respects current security mode) */
        ret = smc_occp_check_addr_access_allowed(
            address, sizeof(uint64_t)); /* Minimum manifest header size */
        if (ret != OCCP_ERROR_NONE) {
            simputs("VALIDATE_AND_BOOT: Manifest address access denied\n");
            smc_post_code_set_error(POST_CODE_ERROR_ACCESS);
            smc_status_report(SMC_STATUS_TYPE_ERROR, SMC_OCCP_ERROR_VALIDATE_ADDRESS_FAILED);
            smc_occp_handle_error_response(drv, drv_type, hdr, Invalid_Address);
            return OCCP_ERROR_ACCESS_VIOLATION;
        }
        validate_response_header.body_crc_present = false; // No body CRC for validated response
        validate_response_header.i3c_flags = 0;            // Reserved
        validate_response_header.hdr.error = 0;            // No error
        validate_response_header.hdr.flags = hdr.flags;    // Echo back flags from request
        validate_response_header.hdr.app_id = hdr.app_id;  // Echo back app_id from request
        validate_response_header.hdr.msg_id = hdr.msg_id;  // Echo back msg_id from request
        validate_response_header.hdr.length = 0;           // No body for validated response
        // Calculate header CRC
        uint8_t *hdr_ptr = ((uint8_t *)&validate_response_header) + 1;
        validate_response_header.hdr_crc = calculate_crc8(hdr_ptr, 7);
        // Set response ready state before sending
        smc_post_code_set_occp_state(POST_CODE_OCCP_STATE_RESP_READY);

        smc_occp_send_to_bus(drv, drv_type, (uint8_t *)&validate_response_header,
                             sizeof(validate_response_header), TRANSPORT_TIMEOUT);
        /* Set manifest address in scratch register (function converts to offset internally) */
        smc_scratchpad_set_manifest_offset(address);
        smc_scratchpad_signal_manifest_ready();
        while (true) {
            __asm__("wfi");
        }
    }
    return ret;
}

static uint64_t smc_occp_determine_i3c_address(uint8_t efuse_slot_id) {
    /**
     * I3C ID assignment flow is:
     * Use 64-bit provisional ID in eFuses if it exist.
     * Use 7-bit legacy ID in eFuses if it exists.
     * Use 7-bit ID from RESET_UNIT_CHIP_ID register and Chip id straps as fallback.
     */
    uint64_t determined_pid = 0;
    uint64_t pid0 = smc_efuse_get_i2c_i3c_id(efuse_slot_id);

    if (pid0 == 0x0) {
        determined_pid = smc_strap_get_chip_id();
        CHIP_CONFIG_CHIP_ID_reg_u chip_id = {0};
        chip_id.val = read_reg(SMC_MISC_WRAP_CHIP_CONFIG_CHIP_ID_REG_ADDR);
        determined_pid |= (chip_id.f.chip_id << 5);
        simputs("No 64-bit I3C/I2C ID found in eFuses, using straps and RESET_UNIT_CHIP_ID\n");
        simputshex64("Determined I3C/I2C ID from Straps: ", determined_pid);
    } else {
        determined_pid = pid0;
        simputshex64("Determined I3C/I2C ID from Efuse: ", determined_pid);
    }

    return determined_pid;
}

#ifndef SMC_OCCP_DISABLE_I3C_INIT
static int smc_occp_init_i3c_channel(bool use_channel, uint8_t peripheral_controller_id,
                                     uint64_t i3c_id) {
    int ret = OCCP_ERROR_NONE;

    simputshex16("initialize I3C channel: ", peripheral_controller_id);

    if (use_channel) {
        /* Get efuse drive strength for I3C GPIO pins based on controller ID */

        enable_i3c_gpio_overrides(peripheral_controller_id);

        I3C_Driver *drv = I3C_GetDriverInstance(peripheral_controller_id);
        if (drv->init(drv, peripheral_controller_id, i3c_id, SUBORDINATE) != I3C_OK ||
            drv->start(drv) != I3C_OK) {
            ret = OCCP_ERROR_INTERFACE_ERROR;
        }
        if (ret == OCCP_ERROR_NONE) {
            // simputshex16("Initialized I3C Channel: ", peripheral_controller_id);
            g_smc_active_interfaces.channel_drivers[g_smc_active_interfaces.num_channels] =
                (void *)drv;
            g_smc_active_interfaces.type[g_smc_active_interfaces.num_channels] = DRIVER_TYPE_I3C;
            g_smc_active_interfaces.num_channels++;
        } else {
            simputshex16("Failed to initialize I3C channel: ", peripheral_controller_id);
        }
    }
    return ret;
}
#endif

static int smc_occp_init_i2c_channel(bool use_channel, uint8_t controller_id, uint8_t i2c_addr) {
    int ret = OCCP_ERROR_INTERFACE_ERROR;
    if (use_channel) {
        I2C_Driver *i2cdrv = I2C_GetDriverInstance(controller_id);
        if (i2cdrv->init_target(i2cdrv, i2c_addr) != I2C_OK) {
            // simputshex16("Failed to initialize I2C channel: ", controller_id);
            ret = OCCP_ERROR_INTERFACE_ERROR;
        } else {
            g_smc_active_interfaces.channel_drivers[g_smc_active_interfaces.num_channels] =
                (void *)i2cdrv;
            g_smc_active_interfaces.type[g_smc_active_interfaces.num_channels] = DRIVER_TYPE_I2C;
            g_smc_active_interfaces.num_channels++;
            ret = OCCP_ERROR_NONE;
        }
    }
    return ret;
}

static int smc_occp_read_from_bus_4byte_aligned_or_complete_stream(
    interface_driver_t drv, driver_type_t drv_type, uint8_t *buffer, size_t length,
    uint32_t timeout, bool expect_excess_bytes, bool is_flush) {
    I2C_Driver *i2c_drv = (I2C_Driver *)drv;
    I3C_Driver *i3c_drv = (I3C_Driver *)drv;
    size_t bytes_received;
    I2C_Status i2c_status;
    I3C_Status i3c_status;

    if (drv_type == DRIVER_TYPE_I2C) {
        bool expect_start_det = expect_excess_bytes && !is_flush;
        bool expect_stop_det = !expect_excess_bytes;
        i2c_status = i2c_drv->write_target(i2c_drv, buffer, length, &bytes_received, timeout,
                                           expect_start_det, expect_stop_det);
        if (i2c_status == I2C_OK) {
            return OCCP_ERROR_NONE;
        } else if (i2c_status == I2C_ERR_INCOMPLETE) {
            return OCCP_ERROR_TRANSPORT_INCOMPLETE;
        } else if (i2c_status == I2C_ERR_OVERFLOW) {
            return OCCP_ERROR_TRANSPORT_OVERFLOW;
        } else if (i2c_status == I2C_ERR_TIMEOUT) {
            return OCCP_ERROR_TIMEOUT;
        }
        simputs("smc_occp_read_from_bus: Error writing to buffer from I2C bus\n");
        /* Fail-safe: an unmapped driver status (e.g. I2C_ERR_HW, or any future code)
         * must not fall through as success -- that silently accepted corrupt/absent data. */
        return OCCP_ERROR_INTERFACE_ERROR;
    } else if (drv_type == DRIVER_TYPE_I3C) {
        i3c_status = i3c_drv->receive_payload_stream(i3c_drv, buffer, length, &bytes_received,
                                                     timeout, expect_excess_bytes, is_flush);
        if (i3c_status == I3C_OK) {
            return OCCP_ERROR_NONE;
        } else if (i3c_status == I3C_ERR_INCOMPLETE) {
            return OCCP_ERROR_TRANSPORT_INCOMPLETE;
        } else if (i3c_status == I3C_ERR_OVERFLOW) {
            return OCCP_ERROR_TRANSPORT_OVERFLOW;
        } else if (i3c_status == I3C_ERR_TIMEOUT) {
            return OCCP_ERROR_TIMEOUT;
        }
        simputs("smc_occp_read_from_bus: Error receiving payload from I3C bus\n");
        /* Fail-safe: an unmapped driver status (e.g. I3C_ERR_HW, or any future code)
         * must not fall through as success -- that silently accepted corrupt/absent data. */
        return OCCP_ERROR_INTERFACE_ERROR;
    }
    return OCCP_ERROR_NONE;
}

static int smc_occp_send_to_bus(interface_driver_t drv, driver_type_t drv_type, const uint8_t *data,
                                size_t length, uint32_t timeout) {
    simputshex16("Sending OCCP response with length: ", (uint16_t)length);

    I2C_Driver *i2c_drv = (I2C_Driver *)drv;
    I3C_Driver *i3c_drv = (I3C_Driver *)drv;

    if (drv_type == DRIVER_TYPE_I2C) {
        if (i2c_drv->read_target(i2c_drv, data, length, timeout) != I2C_OK) {
            simputs("smc_occp_send_to_bus: Error writing to I2C bus\n");
            return OCCP_ERROR_INTERFACE_ERROR;
        }
        return OCCP_ERROR_NONE;
    } else if (drv_type == DRIVER_TYPE_I3C) {
        i3c_drv->set_payload_length(i3c_drv, (uint16_t)length);

        if (i3c_drv->fifo_write(i3c_drv, data, length) != I3C_OK) {
            simputs("smc_occp_send_to_bus: Error writing to fifo\n");
            return OCCP_ERROR_INTERFACE_ERROR;
        }
    }
    return OCCP_ERROR_NONE;
}

static uint8_t smc_occp_check_addr_access_allowed(uint64_t addr, uint16_t access_size) {
    /* Note: Address alignment is handled by the command handlers before calling this function.
     * checks here are redundant */

    /* Check for zero-length access */
    if (access_size == 0) {
        simputs("Zero-length access not allowed\n");
        smc_post_code_set_error(POST_CODE_ERROR_ACCESS);
        return OCCP_ERROR_ACCESS_VIOLATION;
    }

    /* Check for address arithmetic overflow before performing addition */
    if (addr > (UINT64_MAX - access_size)) {
        simputs("Address arithmetic would overflow\n");
        smc_post_code_set_error(POST_CODE_ERROR_ACCESS);
        return OCCP_ERROR_ACCESS_VIOLATION;
    }

    /* Safe to perform address arithmetic now */
    uint64_t end_addr = addr + access_size;

    /* Defense-in-depth: Always protect ROM-owned regions, even in unsecure mode */
    if (addr < SMC_ROM_STACK_END && end_addr > SMC_ROM_DATA_BASE) {
        simputshex64("Access denied - ROM region protection - start addr: ", addr);
        simputshex64("Access denied - ROM region protection - end addr: ", end_addr);
        simputshex64("ROM data base: ", SMC_ROM_DATA_BASE);
        simputshex64("ROM stack end: ", SMC_ROM_STACK_END);
        simputs("Accesses to ROM-owned memory regions (data/bss/stack) denied\n");
        smc_post_code_set_error(POST_CODE_ERROR_ACCESS);
        return OCCP_ERROR_ACCESS_VIOLATION;
    }

    if (smc_security_is_secure_mode()) {
        /* In secured mode, only allow access to OCCP-designated SRAM regions. */
        if (addr < SMC_SRAM_OCCP_BASE_ADDR || end_addr > SMC_SRAM_STACK_LIMIT_ADDR) {
            simputshex64("Access denied - secure mode boundary - start addr: ", addr);
            simputshex64("Access denied - secure mode boundary - end addr: ", end_addr);
            simputshex64("OCCP SRAM base: ", SMC_SRAM_OCCP_BASE_ADDR);
            simputshex64("OCCP SRAM limit: ", SMC_SRAM_STACK_LIMIT_ADDR);
            simputs("Accesses outside of OCCP-accessible SRAM denied in secured mode\n");
            smc_post_code_set_error(POST_CODE_ERROR_SRAM);
            return OCCP_ERROR_ACCESS_VIOLATION;
        }
    }

    return OCCP_ERROR_NONE;
}

static int smc_occp_flush_interface_fifo(interface_driver_t drv, driver_type_t drv_type) {
    uint32_t flush_count = 0;
    if (!drv) {
        return 0;
    }

    simputs("OCCP: Flushing interface FIFO due to header error\n");

    if (drv_type == DRIVER_TYPE_I2C) {
        I2C_Driver *i2c_drv = (I2C_Driver *)drv;
        const uint32_t MAX_FLUSH_BYTES = OCCP_MAX_MSG_SIZE + 32; /* Conservative limit */
        uint32_t timeout_counter = 0;

        /* Flush I2C RX FIFO with safety limits */
        while (flush_count < MAX_FLUSH_BYTES && timeout_counter < TRANSPORT_TIMEOUT) {
            if (i2c_drv->check_rx_fifo(i2c_drv) > 0) {
                uint8_t dummy_byte;
                if (smc_occp_read_from_bus_4byte_aligned_or_complete_stream(
                        drv, drv_type, &dummy_byte, 1, TRANSPORT_TIMEOUT, 1, 1) ==
                    OCCP_ERROR_NONE) {
                    flush_count++;
                } else {
                    break; /* Stop on read error */
                }
                // reset timeout if we read a byte
                timeout_counter = 0;
            } else {
                uintptr_t intr_state_addr = SMC_I2C_WRAP_I2C_0__REG_MAP_BASE_ADDR +
                                            (uintptr_t)i2c_drv->ctx.controller_id *
                                                (uintptr_t)(SMC_I2C_WRAP_I2C_1__REG_MAP_BASE_ADDR -
                                                            SMC_I2C_WRAP_I2C_0__REG_MAP_BASE_ADDR) +
                                            SMC_I2C_WRAP_I2C_0__INTR_STATE_REG_OFFSET;
                I2C_INTR_STATE_reg_u intr_state = {.val = read_reg(intr_state_addr)};
                if (intr_state.f.unexp_stop) {
                    I2C_INTR_STATE_reg_u clr = {.val = 0};
                    clr.f.unexp_stop = 1;
                    write_reg(intr_state_addr, clr.val);
                }
                timeout_counter++;
            }
        }

        simputshex32("OCCP: Flushed I2C FIFO bytes: ", flush_count);
    } else if (drv_type == DRIVER_TYPE_I3C) {
        I3C_Driver *i3c_drv = (I3C_Driver *)drv;
        const uint32_t MAX_FLUSH_BYTES = OCCP_MAX_MSG_SIZE + 32; /* Conservative limit */

        /* Frame-aware flush: let the DRIVER decide how much belongs to dead frames and
         * report it per 4-byte step; got==0 means its frame ledger is clean -> done. The previous
         * loop drained anything that appeared within a TRANSPORT_TIMEOUT quiet window (and reset
         * the window on every byte), so a NEW command sent by a compliant controller right after
         * our error response was swallowed whole -> both sides waited forever
         * (smc_occp_zero_length_rw_test). The swap/HCI driver drains by its frame accounting
         * (exact, instant when clean); the Cadence driver's stream read keeps its own
         * fill-level/timeout behavior inside the same call, so its net behavior is unchanged. */
        while (flush_count < MAX_FLUSH_BYTES) {
            uint8_t dummy_data[4]; /* I3C reads are typically 4-byte aligned */
            size_t got = 0;
            i3c_drv->receive_payload_stream(i3c_drv, dummy_data, sizeof(dummy_data), &got,
                                            TRANSPORT_TIMEOUT, 1, 1);
            if (got == 0) {
                break; /* ledger clean (or nothing arrived within the driver's own bound) */
            }
            flush_count += (uint32_t)got;
        }

        simputshex32("OCCP: Flushed I3C FIFO bytes: ", flush_count);
    }
    return flush_count;
}
