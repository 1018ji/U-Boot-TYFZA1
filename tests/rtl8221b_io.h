/* SPDX-License-Identifier: GPL-2.0-only */
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include <errno.h>
#include <stdarg.h>
static int io_printf(const char *format, ...) { (void)format; return 0; }
#define printf io_printf
static int io_puts(const char *text) { (void)text; return 0; }
#define puts io_puts
typedef uint16_t u16;
#define BIT(n) (1U << (n))
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define MDIO_MMD_PMAPMD 1
#define MDIO_MMD_PCS 3
#define MDIO_MMD_AN 7
#define MDIO_MMD_VEND1 30
#define MDIO_MMD_VEND2 31
#define MDIO_CTRL1 0
#define MDIO_STAT1 1
#define MII_PHYSID2 3
#define MDIO_CTRL1_LPOWER BIT(11)
#define MDIO_AN_CTRL1_ENABLE BIT(12)
#define MDIO_AN_CTRL1_RESTART BIT(9)
#define MDIO_STAT1_LSTATUS BIT(2)
#define SPEED_10 10
#define SPEED_100 100
#define SPEED_1000 1000
#define SPEED_2500 2500
#define DUPLEX_HALF 0
#define DUPLEX_FULL 1
#define PHY_GBIT_FEATURES 1
#define SUPPORTED_2500baseX_Full BIT(15)
#define PHY_10G_FEATURES (PHY_GBIT_FEATURES | BIT(20))
#define MDIO_DEVAD_NONE (-1)
#define MII_MMD_DATA 14
struct phy_driver;
struct phy_device { bool is_c45; int addr, link, speed, duplex; struct phy_driver *drv; };
struct phy_driver {
	const char *name;
	unsigned int uid, mask, features, mmds;
	int (*config)(struct phy_device *), (*startup)(struct phy_device *), (*shutdown)(struct phy_device *);
	int (*read_mmd)(struct phy_device *, int, int);
	int (*write_mmd)(struct phy_device *, int, int, u16);
};
#define U_BOOT_PHY_DRIVER(name) struct phy_driver name
static int genphy_shutdown(struct phy_device *p) { (void)p; return 0; }
static unsigned int revision, version, count, accesses, fail_at, timeout_reg;
static unsigned int reject_reg;
static u16 registers[32][65536];
static unsigned int events[8192][4];
static bool link_up;
static u16 physr;
static int event(unsigned int kind, unsigned int mmd, unsigned int reg, unsigned int value)
{
	if (count >= 8192) return -ENOSPC;
	events[count][0] = kind; events[count][1] = mmd;
	events[count][2] = reg; events[count++][3] = value;
	return ++accesses == fail_at ? -EIO : 0;
}
static int phy_read(struct phy_device *phy, int mmd, unsigned int reg)
{
	if (mmd == MDIO_DEVAD_NONE) return 0xffff;
	unsigned int value = registers[mmd][reg];
	(void)phy;
	if (mmd == 31 && reg == 0xa420) value = timeout_reg == reg ? 0 : 3;
	if (mmd == 1 && reg == 3) value = 0xc840 | revision;
	if (mmd == 31 && reg == 0xa438 && registers[31][0xa436] == 0x801e) value = version;
	if (mmd == 31 && reg == 0xb800) {
		value = registers[31][0xb820] & 0x10 ? 0x40 : 0;
		if (timeout_reg == reg) value ^= 0x40;
	}
	if (mmd == 31 && reg == 0xa434) value = timeout_reg == reg ? 0 : physr;
	if (mmd == 1 && reg == 1) value = link_up ? 4 : 0;
	return event('r', mmd, reg, value) < 0 ? -EIO : (int)value;
}
static int phy_write(struct phy_device *phy, int mmd, int reg, u16 value)
{
	if (mmd == MDIO_DEVAD_NONE) return -EOPNOTSUPP;
	int ret = event('w', mmd, reg, value);
	(void)phy;
	if (!ret && (unsigned int)reg != reject_reg &&
	    !(reject_reg == 0x10000 && mmd == 1 && reg == 0 && !(value & 0x800)))
		registers[mmd][reg] = value;
	return ret;
}
static void phy_mmd_start_indirect(struct phy_device *phy, int mmd, int reg)
{ (void)phy; (void)mmd; (void)reg; }
#define read_poll_timeout(op, val, condition, delay, timeout, args...) ({ \
	int result = -ETIMEDOUT; \
	for (int attempt = 0; attempt < 3; attempt++) { \
		val = op(args); if (condition) { result = 0; break; } \
	} result; \
})
