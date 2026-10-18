/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef TYFZA1_CONFIG_H
#define TYFZA1_CONFIG_H
#ifndef __ASSEMBLY__
#include <asm/arch/registers.h>
#endif
#define CFG_SYS_SDRAM_BASE 0
#define CORTINA_UART_CLOCK 125000000
#define CFG_SYS_NAND_BASE 0xe0000000
#define NI_XRAM_BASE 0xf4500000
#define CONFIG_SYS_MAX_NAND_CHIPS 1
#define CONFIG_CORTINA_FLASH_CTRL_BASE 0xf4324000
#define CONFIG_NI_PHY_ADDR_GMAC0 1
#define CONFIG_NI_PHY_ADDR_GMAC1 2
#define CONFIG_NI_PHY_ADDR_GMAC2 3
#define CA_REG_READ(addr) readl((unsigned long)(addr))
#define CA_REG_WRITE(value, addr) writel((value), (unsigned long)(addr))
#define KSEG1_ATU_XLAT(addr) (addr)
#endif
