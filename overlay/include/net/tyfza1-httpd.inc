/* SPDX-License-Identifier: GPL-2.0-only */
/* Included after the common HTTP service state, in the same translation unit. */
static char tyf_restore_operation[24];
static size_t tyf_restore_total, tyf_restore_offset;
static u32 tyf_restore_id;

static int tyf_http_parse_restore(struct http_json_request *request,
				const char *operation, u64 upload)
{
	u64 total, offset, id;
	bool start = !strcmp(operation, "restore-start");
	bool chunk = !strcmp(operation, "restore-chunk");
	bool finish = !strcmp(operation, "restore-finish");
	bool cancel = !strcmp(operation, "restore-cancel");
	if (!start && !chunk && !finish && !cancel)
		return tyfza1_restore_status()->active ? -EBUSY : 1;
	if (json_uint(request, "total", &total) || total > SIZE_MAX ||
	    json_uint(request, "offset", &offset) || offset > SIZE_MAX ||
	    json_uint(request, "restore_id", &id) || id > 0xffffffffU)
		return -EINVAL;
	if ((start || chunk) && (!buffer_size || upload != upload_id)) return -EINVAL;
	strlcpy(tyf_restore_operation, operation, sizeof(tyf_restore_operation));
	tyf_restore_total = total;
	tyf_restore_offset = offset;
	tyf_restore_id = id;
	job_kind = HTTP_JOB_TYF_RESTORE;
	return 0;
}

static void tyf_http_restore_info(struct http_json *json)
{
	const struct tyfza1_restore_status *state = tyfza1_restore_status();
	json_printf(json, ",\"restore_active\":%s,\"restore_id\":%u,"
		    "\"restore_offset\":%zu,\"restore_total\":%zu",
		    state->active ? "true" : "false", state->id, state->next, state->total);
}

static bool tyf_http_upload_safe(ulong address, size_t size)
{
	static const struct { ulong begin, end; } reserved[] = {
		{ 0, 0x1000 }, { 0x02000000, 0x02400000 },
		{ 0x09000000, 0x0aa50000 }, { 0x0bc48000, 0x0bc58000 },
		{ 0x0eeff000, 0x10000000 },
	};
	unsigned int i;
	if (!size || address + size < address) return false;
	for (i = 0; i < ARRAY_SIZE(reserved); i++)
		if (address < reserved[i].end && address + size > reserved[i].begin) return false;
	return true;
}
