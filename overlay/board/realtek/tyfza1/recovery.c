// SPDX-License-Identifier: GPL-2.0-only
#include <config.h>
#include <command.h>
#include <env.h>
#include <image.h>
#include <malloc.h>
#include <memalign.h>
#include <mapmem.h>
#include <mtd.h>
#include <stdio.h>
#include <ubi_uboot.h>
#include <tyfza1_recovery.h>
#include <lzma/LzmaTools.h>
#include <linux/libfdt.h>
#include "formats.h"

static int volume_verify(char *name, const void *data, size_t length,
			 void (*poll)(void))
{
	unsigned char *check = malloc_cache_aligned(0x10000);
	const unsigned char *input = data;
	size_t off, chunk;
	int ret = -ENOMEM;
	if (!check) return ret;
	for (off = 0; off < length; off += chunk) {
		chunk = min_t(size_t, 0x10000, length - off);
		ret = ubi_volume_read_quiet(name, (char *)check, off, chunk);
		if (ret || memcmp(check, input + off, chunk)) {
			ret = ret ? ret : -EIO;
			break;
		}
		poll();
	}
	free(check);
	return ret;
}

static int verify_fit(const struct tyf_payload *image)
{
	const void *data;
	const char *conf = env_get("b_conf"), *variant = env_get("board_variant");
	void *dtb = NULL;
	size_t size;
	u8 comp;
	int node, fdt, images, child, ret = -EINVAL;
	if (!conf || !variant || (strcmp(variant, "4ge") && strcmp(variant, "2p5g")) ||
	    fit_check_format(image->data, image->size)) return -EINVAL;
	images = fdt_path_offset(image->data, FIT_IMAGES_PATH);
	if (images < 0) return -EINVAL;
	fdt_for_each_subnode(child, image->data, images) {
		uintptr_t start = (uintptr_t)image->data, at;
		if (fit_image_get_data(image->data, child, &data, &size)) return -EINVAL;
		at = (uintptr_t)data;
		if (at < start || size > image->size || at - start > image->size - size)
			return -EINVAL;
	}
	if (!fit_all_image_verify(image->data)) return -EINVAL;
	node = fit_conf_get_node(image->data, conf);
	if (node < 0) return node;
	fdt = fit_conf_get_prop_node(image->data, node, FIT_FDT_PROP, IH_PHASE_NONE);
	if (fdt < 0 || fit_image_get_data(image->data, fdt, &data, &size) ||
	    (const unsigned char *)data < image->data || size > image->size ||
	    (const unsigned char *)data - image->data > image->size - size ||
	    fit_image_get_comp(image->data, fdt, &comp)) return -EINVAL;
	if (comp == IH_COMP_LZMA) {
		SizeT output_size = 0x20000;
		dtb = malloc(output_size);
		if (!dtb) return -ENOMEM;
		if (lzmaBuffToBuffDecompress(dtb, &output_size, (unsigned char *)data, size))
			goto out;
		data = dtb;
		size = output_size;
	} else if (comp != IH_COMP_NONE) {
		goto out;
	}
	if (fdt_check_full(data, size)) goto out;
	ret = fdt_node_check_compatible(data, 0, !strcmp(variant, "2p5g") ?
		"tianyi,tyfza1-2p5g" : "tianyi,tyfza1");
	if (ret) ret = -EINVAL;
out:
	free(dtb);
	return ret;
}

int tyfza1_install_system(ulong address, size_t size, void (*poll)(void))
{
	struct tyf_firmware fw;
	const void *input = map_sysmem(address, size);
	const char *committed = env_get("sw_commit");
	char kernel[16], root[16];
	char old_commit[2] = "0", old_active[2] = "0", old_try[2] = "2";
	size_t capacity;
	int slot, ret = -EINVAL;

	if (committed && strcmp(committed, "0") && strcmp(committed, "1")) goto out;
	if (committed) old_commit[0] = committed[0];
	slot = old_commit[0] == '0' ? 1 : 0;
	if (env_get("sw_active")) old_active[0] = env_get("sw_active")[0];
	if (env_get("sw_tryactive")) old_try[0] = env_get("sw_tryactive")[0];
	if (tyf_parse_sysupgrade(input, size, &fw) || verify_fit(&fw.kernel)) {
		puts("Expected a TYFZA1 sysupgrade archive with a matching, hash-verified FIT and SquashFS.\n");
		goto out;
	}
	ret = ubi_part("ubi_device", NULL);
	if (ret) goto out;
	snprintf(kernel, sizeof(kernel), "ubi_k%d", slot);
	snprintf(root, sizeof(root), "ubi_r%d", slot);
	ret = ubi_volume_get_size(kernel, NULL, &capacity);
	if (ret || fw.kernel.size > capacity) { ret = -EFBIG; goto out; }
	ret = ubi_volume_get_size(root, NULL, &capacity);
	if (ret || fw.root.size > capacity) { ret = -EFBIG; goto out; }
	printf("Installing inactive slot %d; current slot and factory volumes are retained.\n", slot);
	ret = ubi_volume_write(root, (void *)fw.root.data, 0, fw.root.size);
	if (!ret) ret = volume_verify(root, fw.root.data, fw.root.size, poll);
	if (ret) goto out;
	ret = ubi_volume_write(kernel, (void *)fw.kernel.data, 0, fw.kernel.size);
	if (!ret) ret = volume_verify(kernel, fw.kernel.data, fw.kernel.size, poll);
	if (ret) goto out;
	/* Commit only after both new volumes have passed independent readback. */
	env_set("sw_commit", slot ? "1" : "0");
	env_set("sw_active", slot ? "1" : "0");
	env_set("sw_tryactive", "2");
	ret = env_save();
	if (ret) {
		env_set("sw_commit", old_commit);
		env_set("sw_active", old_active);
		env_set("sw_tryactive", old_try);
	} else {
		printf("Slot %d written, read back and committed.\n", slot);
	}
out:
	unmap_sysmem(input);
	return ret;
}

static int read_mtd(struct mtd_info *mtd, size_t offset, size_t length, void *out)
{
	size_t done;
	int ret = mtd_read(mtd, offset, length, &done, out);
	if (ret == -EUCLEAN && done == length) ret = 0;
	return ret ? ret : done == length ? 0 : -EIO;
}

int tyfza1_install_loader(ulong address, size_t size, bool bl2, void (*poll)(void))
{
	struct tyf_fip next, old;
	const unsigned char *input = map_sysmem(address, size);
	unsigned char *current = NULL, *check = NULL;
	struct mtd_info *mtd = NULL;
	size_t base, offset, done;
	int copy, ret = -EINVAL;

	/* Taurus keeps BL2, BL31 and BL33 together; AN758x preloader files cannot apply. */
	if (bl2 || tyf_parse_loader(input, size, &next)) goto out;
	mtd_probe_devices();
	mtd = get_mtd_device_nm("boot");
	if (IS_ERR(mtd)) { ret = PTR_ERR(mtd); mtd = NULL; goto out; }
	if (mtd->size != TYF_BOOT_SIZE || mtd->erasesize != 0x20000 ||
	    mtd->writesize != 0x800) goto out;
	current = malloc_cache_aligned(TYF_BOOT_SIZE);
	check = malloc_cache_aligned(mtd->erasesize);
	if (!current || !check) { ret = -ENOMEM; goto out; }
	ret = read_mtd(mtd, 0, TYF_BOOT_SIZE, current);
	if (ret) goto out;
	ret = -EINVAL;
	if (tyf_parse_loader(current, TYF_BOOT_SIZE, &old) ||
	    old.bl2.size != next.bl2.size || old.bl31.size != next.bl31.size ||
	    memcmp(old.bl2.data, next.bl2.data, old.bl2.size) ||
	    memcmp(old.bl31.data, next.bl31.data, old.bl31.size) ||
	    memcmp(current, input, TYF_FIP0_OFFSET) ||
	    memcmp(current + 0x1c0000, input + 0x1c0000, 0x40000)) {
		puts("Loader must preserve this device's GPT, BL2, BL31 and reserved bytes.\n");
		goto out;
	}
	for (offset = TYF_FIP0_OFFSET; offset < 0x1c0000; offset += mtd->erasesize) {
		ret = mtd_block_isbad(mtd, offset);
		if (ret) { ret = ret < 0 ? ret : -EIO; goto out; }
	}
	/* Finish and verify FIP1 before touching FIP0. No offset shifting in boot. */
	for (copy = 1; copy >= 0; copy--) {
		base = copy ? TYF_FIP1_OFFSET : TYF_FIP0_OFFSET;
		for (offset = base; offset < base + TYF_FIP_SIZE; offset += mtd->erasesize) {
			struct erase_info erase = { .mtd = mtd, .addr = offset, .len = mtd->erasesize };
			ret = mtd_erase(mtd, &erase);
			if (ret) goto out;
			ret = mtd_write(mtd, offset, mtd->erasesize, &done, input + offset);
			if (ret || done != mtd->erasesize) { ret = ret ? ret : -EIO; goto out; }
			ret = read_mtd(mtd, offset, mtd->erasesize, check);
			if (ret || memcmp(check, input + offset, mtd->erasesize)) {
				ret = ret ? ret : -EIO;
				goto out;
			}
			poll();
		}
		printf("FIP%d written and read back.\n", copy);
	}
out:
	free(check);
	free(current);
	if (mtd) put_mtd_device(mtd);
	unmap_sysmem(input);
	return ret;
}

struct preserved_volume {
	const char *name;
	size_t size;
	void *data;
};

int tyfza1_rebuild_ubi(void (*poll)(void))
{
	static const struct { const char *name; unsigned int size; } layout[] = {
		{ "ubi_Config", 0x60e000 }, { "ubi_fpga", 0x41e000 },
		{ "ubi_DTB0", 0x5d000 }, { "ubi_k0", 0x60e000 }, { "ubi_r0", 0x2017000 },
		{ "ubi_DTB1", 0x5d000 }, { "ubi_k1", 0x60e000 }, { "ubi_r1", 0x2017000 },
		{ "ubi_framework1", 0x101b000 }, { "ubi_framework2", 0x101b000 },
		{ "ubi_apps", 0x6007000 }, { "rootfs_data", 0x1000000 },
	};
	struct preserved_volume keep[] = {
		{ "ubi_Config", 0, NULL }, { "ubi_fpga", 0, NULL },
		{ "ubi_DTB0", 0, NULL }, { "ubi_DTB1", 0, NULL },
	};
	struct mtd_info *mtd = NULL;
	size_t offset;
	unsigned int i;
	int ret = ubi_part("ubi_device", NULL);
	if (ret) return ret;
	/* Copy all optical/radio identity and FPGA/DT volumes before erasing anything. */
	for (i = 0; i < ARRAY_SIZE(keep); i++) {
		ret = ubi_volume_get_size(keep[i].name, &keep[i].size, NULL);
		if (ret || !keep[i].size || keep[i].size > 0x800000) {
			ret = ret ? ret : -EINVAL; goto out;
		}
		keep[i].data = malloc_cache_aligned(keep[i].size);
		if (!keep[i].data) { ret = -ENOMEM; goto out; }
		ret = ubi_volume_read((char *)keep[i].name, keep[i].data, 0, keep[i].size);
		if (ret) goto out;
		poll();
	}
	ret = ubi_detach();
	if (ret) goto out;
	mtd_probe_devices();
	mtd = get_mtd_device_nm("ubi_device");
	if (IS_ERR(mtd)) { ret = PTR_ERR(mtd); mtd = NULL; goto out; }
	if (mtd->size != 0x0f5c0000 || mtd->erasesize != 0x20000) { ret = -EINVAL; goto out; }
	for (offset = 0; offset < mtd->size; offset += mtd->erasesize) {
		struct erase_info erase = { .mtd = mtd, .addr = offset, .len = mtd->erasesize };
		ret = mtd_block_isbad(mtd, offset);
		if (ret < 0) goto out;
		if (!ret && (ret = mtd_erase(mtd, &erase))) goto out;
		poll();
	}
	put_mtd_device(mtd);
	mtd = NULL;
	ret = ubi_part("ubi_device", NULL);
	if (ret) goto out;
	for (i = 0; i < ARRAY_SIZE(layout); i++) {
		ret = run_commandf("ubi create %s %x d %x", layout[i].name, layout[i].size, i);
		if (ret) goto out;
		poll();
	}
	for (i = 0; i < ARRAY_SIZE(keep); i++) {
		ret = ubi_volume_write((char *)keep[i].name, keep[i].data, 0, keep[i].size);
		if (!ret) ret = volume_verify((char *)keep[i].name, keep[i].data, keep[i].size, poll);
		if (ret) goto out;
	}
	puts("UBI rebuilt; factory, FPGA and board trees restored and read back. Install a system before booting.\n");
out:
	if (mtd) put_mtd_device(mtd);
	for (i = 0; i < ARRAY_SIZE(keep); i++) free(keep[i].data);
	return ret;
}
