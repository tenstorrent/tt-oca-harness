/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "metal/atomic.h"
#include "metal/lock.h"
#include "smc_io.h"
#include "smc_test.h"

#define BLOCKED_REQUEST 0xbadcab1e
#define PAD2SOC_MASK 0x80000000

#define TOTAL_GPIOS 65

#define GPIO_INTF_DATA_CTRL_OFF \
    (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0))
#define GPIO_INTF_ACCESS_FILTER_OFF \
    (SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0))
#define GPIO_CTRL_CONTROL_OFF \
    (SMC_TOP_GPIO_CTRL_CONTROL_BASE_ADDR(0) - SMC_TOP_GPIO_CTRL_BASE_ADDR(0))

/* Reset-default expectations for the GPIO_SANITY checks. */
#define EXP_ACCESS_FILTER 0x00010100u
#define EXP_DATA_CTRL 0x00000000u
#define EXP_CONTROL 0x00100002u

/* LIVE pin handshake with cocotb (scratch 9=req, 11=ack). */
#define LIVE_SCR_REQ 9
#define LIVE_SCR_ACK 11
#define LIVE_REQ_REG_OUT 0xAE600001u
#define LIVE_REQ_DIR_10 0xAE600010u
#define LIVE_REQ_DIR_01 0xAE600011u
#define LIVE_ACK_OK 0xACC00001u
#define LIVE_ACK_FAIL 0xDEADF001u
#define LIVE_ACK_BOUND 200000u

/*
 * LIVE pad observation uses scratch 9/11 with the nonfree SMC TB observer.
 * The open wrap loader has no observer — wait_live_ack times out there.
 */

static void fail_gpio(uint32_t code, const char *msg) {
    write_scratch(0, code);
    simputs("  ERROR: ");
    simputs(msg);
    simputs("\n");
    test_fail(0);
}

static void wait_live_ack(uint32_t req) {
    uint32_t i;
    uint32_t ack;

    write_scratch(LIVE_SCR_ACK, 0);
    write_scratch(LIVE_SCR_REQ, req);
    for (i = 0; i < LIVE_ACK_BOUND; i++) {
        ack = read_scratch(LIVE_SCR_ACK);
        if (ack == LIVE_ACK_OK) {
            write_scratch(LIVE_SCR_REQ, 0);
            write_scratch(LIVE_SCR_ACK, 0);
            return;
        }
        if (ack == LIVE_ACK_FAIL) {
            write_scratch(2, ack);
            fail_gpio(0xBAD00101u, "LIVE TB ack FAIL (needs nonfree observer)");
        }
    }
    write_scratch(2, req);
    write_scratch(3, LIVE_ACK_BOUND);
    fail_gpio(0xBAD00102u, "LIVE TB ack TIMEOUT (open wrap has no pad observer)");
}

/*
 * RST-DEFAULTS + INTF-BANK before mutating filters / pad loopback.
 * LIVE CHK-REG-OUT / CHK-DIR need pad-pin observation (cocotb).
 */
void test_rst_defaults(void) {
    uint32_t af;
    uint32_t dc;
    uint32_t ctrl;

    /* S1 CHK-RST-AF */
    af = read_gpio(0, GPIO_INTF_ACCESS_FILTER_OFF);
    write_scratch(2, af);
    if (af != EXP_ACCESS_FILTER) {
        fail_gpio(0xBAD00110u, "CHK-RST-AF ACCESS_FILTER mismatch");
    }
    simputs("  CHK-RST-AF: ACCESS_FILTER=0x00010100\n");

    /* S2 CHK-RST-DC — mask pad2core (bit31); it is HW-updated from the pad. */
    dc = read_gpio(0, GPIO_INTF_DATA_CTRL_OFF);
    write_scratch(2, dc);
    if ((dc & 0x7FFFFFFFu) != (EXP_DATA_CTRL & 0x7FFFFFFFu)) {
        fail_gpio(0xBAD00111u, "CHK-RST-DC DATA_CTRL programmable fields mismatch");
    }
    simputs("  CHK-RST-DC: DATA_CTRL programmable fields ok (pad2core masked)\n");

    /* S3 CHK-RST-CTRL — exact default; strap capture may differ; report observed. */
    ctrl = read_gpio_shim(0, GPIO_CTRL_CONTROL_OFF);
    write_scratch(2, ctrl);
    if (ctrl != EXP_CONTROL) {
        simputs("  ERROR: CHK-RST-CTRL CONTROL mismatch observed=");
        simputshex32("", ctrl);
        simputs(" expect=");
        simputshex32("", EXP_CONTROL);
        simputs("\n");
        fail_gpio(0xBAD00112u, "CHK-RST-CTRL CONTROL mismatch");
    }
    simputs("  CHK-RST-CTRL: CONTROL=0x00100002\n");
}

/* S4 + LIVE CHK-REG-OUT via TB pin sample. */
void test_reg_out_program(void) {
    gpio_intf__DATA_CTRL_t dc;

    dc.w = read_gpio(11, GPIO_INTF_DATA_CTRL_OFF);
    dc.f.interface_enable = 1;
    dc.f.enable_rx_tx = 1; /* 2'b01 core2pad_en */
    dc.f.core2pad = 1;
    write_gpio(11, GPIO_INTF_DATA_CTRL_OFF, dc.w);

    dc.w = read_gpio(11, GPIO_INTF_DATA_CTRL_OFF);
    if ((dc.f.interface_enable != 1) || (dc.f.enable_rx_tx != 1) || (dc.f.core2pad != 1)) {
        write_scratch(2, dc.w);
        fail_gpio(0xBAD00120u, "REG-OUT DATA_CTRL program readback fail");
    }
    wait_live_ack(LIVE_REQ_REG_OUT);
    simputs("  CHK-REG-OUT: core2pad_o=1 core2pad_en=1\n");
}

/* S6 direction switch + LIVE enable observe via TB. */
void test_dir_switch_csr(void) {
    gpio_intf__DATA_CTRL_t dc;
    uint32_t rb;

    dc.w = read_gpio(11, GPIO_INTF_DATA_CTRL_OFF);
    dc.f.interface_enable = 1;
    dc.f.enable_rx_tx = 2; /* 2'b10: pad2core_en */
    write_gpio(11, GPIO_INTF_DATA_CTRL_OFF, dc.w);
    rb = read_gpio(11, GPIO_INTF_DATA_CTRL_OFF);
    if (((rb >> 4) & 0x3u) != 2u) {
        write_scratch(2, rb);
        fail_gpio(0xBAD00121u, "DIR enable_rx_tx=10 readback stale");
    }
    wait_live_ack(LIVE_REQ_DIR_10);

    dc.w = rb;
    dc.f.enable_rx_tx = 1; /* 2'b01: core2pad_en */
    write_gpio(11, GPIO_INTF_DATA_CTRL_OFF, dc.w);
    rb = read_gpio(11, GPIO_INTF_DATA_CTRL_OFF);
    if (((rb >> 4) & 0x3u) != 1u) {
        write_scratch(2, rb);
        fail_gpio(0xBAD00122u, "DIR enable_rx_tx=01 readback stale");
    }
    wait_live_ack(LIVE_REQ_DIR_01);
    simputs("  CHK-DIR: enable_rx_tx 10->01 live enables ok\n");
}

/* S7 intf-bank round-trip + ctrl-bank non-alias */
void test_intf_bank(void) {
    uint32_t ctrl_before;
    uint32_t ctrl_after;
    gpio_intf__DATA_CTRL_t dc;
    uint32_t rb;

    ctrl_before = read_gpio_shim(5, GPIO_CTRL_CONTROL_OFF);

    dc.w = read_gpio(5, GPIO_INTF_DATA_CTRL_OFF);
    dc.f.interface_enable = 1;
    dc.f.core2pad = 1;
    write_gpio(5, GPIO_INTF_DATA_CTRL_OFF, dc.w);
    rb = read_gpio(5, GPIO_INTF_DATA_CTRL_OFF);
    if ((rb & 0x7FFFFFFFu) != (dc.w & 0x7FFFFFFFu)) {
        write_scratch(2, rb);
        fail_gpio(0xBAD00123u, "CHK-INTF-BANK DATA_CTRL round-trip fail");
    }

    ctrl_after = read_gpio_shim(5, GPIO_CTRL_CONTROL_OFF);
    if (ctrl_after != ctrl_before) {
        write_scratch(2, ctrl_before);
        write_scratch(3, ctrl_after);
        fail_gpio(0xBAD00124u, "CHK-INTF-BANK aliased into ctrl-bank CONTROL");
    }
    simputs("  CHK-INTF-BANK: intf DATA_CTRL round-trip; ctrl CONTROL unchanged\n");
}

void test_rw_core2pad(void) {

    gpio_intf__DATA_CTRL_t gpio_intf;

    for (int gpio_num = 0; gpio_num < TOTAL_GPIOS; gpio_num++) {

        uint32_t read_data_control = read_gpio(
            gpio_num, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));

        gpio_intf.w = read_data_control;

        if (gpio_num ==
            61) { // this gpio is being used for cool_reset, use 0 as data to avoid resetting itself
            gpio_intf.f.core2pad = 0;
            gpio_intf.f.interface_enable = 0;
        } else {
            gpio_intf.f.core2pad = 1;
            gpio_intf.f.interface_enable = 1;
        }

        write_gpio(gpio_num,
                   (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)),
                   gpio_intf.w);

        uint32_t read_data_control_updated = read_gpio(
            gpio_num, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));

        write_scratch(1, gpio_num);
        write_scratch(1, gpio_intf.w);
        write_scratch(2, read_data_control_updated);

        // bitwise and to not check bits that are HW writable
        if (gpio_intf.w != (read_data_control_updated & 0x7FFFFFFF)) {
            fail_gpio(0xBAD00130u, "core2pad DATA_CTRL readback mismatch");
        }
    }
}

void test_read_filter(void) {

    //// Change read permissions on GPIO 0 ////

    gpio_intf__ACCESS_FILTER_t gpio_filter_0;

    gpio_filter_0.w = read_gpio(
        0, (SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
    gpio_filter_0.f.read_filter_enable = 1;

    gpio_filter_0.f.arprot_requirement = 2; // 3'b010 which is default
    write_gpio(0, (SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)),
               gpio_filter_0.w); // set the new filter

    // read back the filter to check it was written correctly
    uint32_t read_filter = read_gpio(
        0, (SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
    if (read_filter != gpio_filter_0.w) {
        fail_gpio(0xBAD00140u, "read filter program readback fail");
    }

    uint32_t read_data_allowed =
        read_gpio(0, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
    write_scratch(3, read_data_allowed);

    if (read_data_allowed == BLOCKED_REQUEST) {
        fail_gpio(0xBAD00141u, "read filter blocked allowed transaction");
    }

    // Set prot to be 4
    gpio_filter_0.f.arprot_requirement = 4;
    write_gpio(0, (SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)),
               gpio_filter_0.w); // set the new filter

    // read back the filter, it should not be read back as the filter is set
    read_filter = read_gpio(
        0, (SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
    if (read_filter == gpio_filter_0.w) {
        fail_gpio(0xBAD00142u, "read filter should block filter CSR readback");
    }

    // Try and read - should be blocked
    uint32_t read_data_blocked =
        read_gpio(0, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
    write_scratch(4, read_data_blocked);

    if (read_data_blocked != BLOCKED_REQUEST) {
        fail_gpio(0xBAD00143u, "read filter did not block DATA_CTRL read");
    }
}

void test_write_filter(void) {

    //// Change write permissions on GPIO 1 ////

    for (int i = 0; i < 4; i++) {
        write_scratch(i, 0x22222222);
    }

    gpio_intf__ACCESS_FILTER_t gpio_filter_1;
    gpio_intf__DATA_CTRL_t gpio_intf_1;

    gpio_intf_1.w =
        read_gpio(1, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
    gpio_filter_1.w = read_gpio(
        1, (SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
    gpio_filter_1.f.write_filter_enable = 1;
    gpio_filter_1.f.awprot_requirement = 2;

    write_gpio(1, (SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)),
               gpio_filter_1.w); // set the new filter with write filter enabled

    // read back the filter to check it was written correctly
    uint32_t read_filter = read_gpio(
        1, (SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
    if (read_filter != gpio_filter_1.w) {
        fail_gpio(0xBAD00150u, "write filter program readback fail");
    }

    gpio_intf_1.f.core2pad = 1;
    gpio_intf_1.f.interface_enable = 1;
    write_gpio(1, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)),
               gpio_intf_1.w); // since correct prot (secure transaction), should write
    uint32_t read_data_allowed =
        read_gpio(1, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));

    if (read_data_allowed != gpio_intf_1.w) { // should be equal
        write_scratch(2, gpio_intf_1.w);
        write_scratch(3, read_data_allowed);
        fail_gpio(0xBAD00151u, "write filter allowed write did not land");
    }

    gpio_filter_1.f.awprot_requirement =
        4; // only transactions with prot = 4 should be allowed to write
    write_gpio(1, (SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)),
               gpio_filter_1.w); // set the new filter

    // read back the filter to check it was written correctly
    read_filter = read_gpio(
        1, (SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
    if (read_filter != gpio_filter_1.w) {
        fail_gpio(0xBAD00152u, "write filter prot=4 program readback fail");
    }

    gpio_intf_1.f.core2pad = 0; // try and write a 0
    write_gpio(1, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)),
               gpio_intf_1.w);
    uint32_t read_data_unchanged =
        read_gpio(1, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));

    if (read_data_unchanged ==
        gpio_intf_1.w) { // if they are equal then the write occurred and the filter did not work
        write_scratch(2, gpio_intf_1.w);
        write_scratch(3, read_data_unchanged);
        fail_gpio(0xBAD00153u, "write filter failed to block write");
    }
}

void test_rx_tx(void) {
    uint32_t read_data_24;
    uint32_t pad2core_bit;
    int level;

    for (int i = 0; i < 4; i++) {
        write_scratch(i, 0x33333333);
    }

    /* Loopback path: GPIO11 drives core2pad → pad; GPIO24 samples pad2core. */
    gpio_intf__DATA_CTRL_t gpio_intf_11; /* GPIO 11 */
    gpio_intf__DATA_CTRL_t gpio_intf_24; /* GPIO 24 */

    gpio_intf_11.w =
        read_gpio(11, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
    gpio_intf_24.w =
        read_gpio(24, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));

    gpio_intf_24.f.enable_rx_tx = 2; /* 2'b10: TX enabled - pad2core_en */
    gpio_intf_24.f.interface_enable = 1;

    gpio_intf_11.f.enable_rx_tx = 1; /* 2'b01: RX enabled - core2pad_en */
    gpio_intf_11.f.interface_enable = 1;

    write_gpio(24, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)),
               gpio_intf_24.w);

    /* CHK-PAD-IN: pad2core must follow the driven core2pad at both levels. */
    for (level = 0; level < 2; level++) {
        gpio_intf_11.f.core2pad = (uint32_t)level;
        write_gpio(11, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)),
                   gpio_intf_11.w);

        read_data_24 = read_gpio(
            24, (SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR(0) - SMC_TOP_GPIO_INTF_BASE_ADDR(0)));
        pad2core_bit = read_data_24 & PAD2SOC_MASK;

        if (level == 0) {
            if (pad2core_bit != 0u) {
                write_scratch(2, read_data_24);
                fail_gpio(0xBAD00160u, "pad2core expect=0 got=1");
            }
        } else {
            if (pad2core_bit != PAD2SOC_MASK) {
                write_scratch(2, read_data_24);
                fail_gpio(0xBAD00161u, "pad2core expect=1 got=0");
            }
        }
    }

    simputs("  CHK-PAD-IN: levels=0,1 ok\n");
}

int main(void) {

    /* Contract RST first (before any mutation). */
    test_rst_defaults();

    /*
     * The all-GPIO DATA_CTRL walk and the filter checks run before PAD-IN/DIR:
     * those leave GPIO11/24 in enable_rx_tx=10, and in that mode the core2pad
     * writeback in test_rw_core2pad does not read back.
     */
    test_rw_core2pad();
    test_read_filter();
    test_write_filter();

    /* S4-S7 producers; the LIVE REG-OUT/DIR tokens require the TB pad observer. */
    test_reg_out_program();
    test_rx_tx();
    test_dir_switch_csr();
    test_intf_bank();

    simputs("  CHK-TIMEOUT-PATHS: live_ack bound=200000 fail_on_expiry last=ok\n");
    simputs("  CHK-NONVAC: order=RST_AF<RST_DC<RST_CTRL<REG_OUT<PAD_IN<DIR<INTF_BANK\n");

    test_pass(0);

    while (true) {
        __asm__("wfi");
    }

    return 0;
}

int other_main(int hartid) {
    while (true) {
        __asm__("wfi");
    }
}

int secondary_main(void) {
    int hartid = metal_cpu_get_current_hartid();

    if (hartid == 0) {
        return main();
    } else {
        return other_main(hartid);
    }
}
