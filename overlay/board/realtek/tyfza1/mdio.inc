/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Taurus Clause45 transactions, matching the native Linux MDIO driver. */
static int tyf_mdio_transfer(u32 address, u16 value, bool read)
{
	u32 status;
	unsigned int elapsed;
	writel(BIT(0), PER_MDIO_CTRL);
	writel(address, PER_MDIO_ADDR);
	if (!read) writel(value, PER_MDIO_WRDATA);
	writel(BIT(7), PER_MDIO_CTRL);
	for (elapsed = 0; elapsed < 50000; elapsed++) {
		status = readl(PER_MDIO_CTRL);
		if (status & BIT(0)) {
			value = read ? readl(PER_MDIO_RDDATA) & 0xffff : 0;
			writel(BIT(0), PER_MDIO_CTRL);
			return value;
		}
		udelay(1);
	}
	printf("MDIO transaction timed out: address=%08x status=%08x\n", address, status);
	return -ETIMEDOUT;
}

static ca_status_t __ca_mdio_c45_write(ca_uint32_t addr, ca_uint32_t devad,
				    ca_uint16_t reg, ca_uint16_t data)
{
	u32 address = addr | devad << 8 | BIT(16);
	int ret = tyf_mdio_transfer(address, reg, false);
	if (ret < 0) return ret;
	return tyf_mdio_transfer(address | 1U << 18, data, false);
}

static ca_status_t __ca_mdio_c45_read(ca_uint32_t addr, ca_uint32_t devad,
				   ca_uint16_t reg, ca_uint16_t *data)
{
	u32 address = addr | devad << 8 | BIT(16);
	int ret = tyf_mdio_transfer(address, reg, false);
	if (ret < 0) return ret;
	ret = tyf_mdio_transfer(address | 3U << 18 | BIT(15), 0, true);
	if (ret < 0) return ret;
	*data = ret;
	return 0;
}
