/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef TYFZA1_RECOVERY_H
#define TYFZA1_RECOVERY_H
#include <linux/types.h>
int tyfza1_reset_held(void);
void tyfza1_boot_leds(void);
int tyfza1_install_system(ulong address, size_t size, void (*poll)(void));
int tyfza1_check_fit(ulong address, size_t size);
int tyfza1_boot_upload(ulong address, size_t size);
int tyfza1_validate_loader(ulong address, size_t size);
int tyfza1_loader_certificates(const void *loader, size_t size);
int tyfza1_install_loader(ulong address, size_t size, bool bl2, void (*poll)(void));
int tyfza1_rebuild_ubi(void (*poll)(void));
struct tyfza1_restore_status {
	bool active;
	u32 id;
	size_t next, total;
};
const struct tyfza1_restore_status *tyfza1_restore_status(void);
int tyfza1_restore_job(const char *operation, ulong address, size_t size,
		       size_t total, size_t offset, u32 id, void (*poll)(void));
#endif
