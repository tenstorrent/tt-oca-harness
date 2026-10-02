// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP hello-world boot firmware: open the outbound filter, print a banner over
// the testbench mailbox, and return PASS. It uses only the open drivers, no libc.

#include "sep_mailbox.h"
#include "sep_outbound_filter.h"

int main(void) {
    sep_outbound_filter_init();
    sep_mbx_puts("Hello from SEP OSS firmware!\n");
    return 0; // crt0.s writes the PASS completion magic on a 0 return
}
