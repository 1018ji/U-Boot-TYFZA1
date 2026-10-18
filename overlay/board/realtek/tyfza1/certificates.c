// SPDX-License-Identifier: GPL-2.0-only
#include "certificates.h"
#include <string.h>

struct der {
	const unsigned char *raw, *data;
	size_t size, length;
	unsigned int tag;
};
struct cert {
	struct der tbs, key, signature;
	struct { unsigned int id; struct der value; } extensions[4];
	unsigned int count;
};

static int take(const unsigned char **at, size_t *left, struct der *item)
{
	const unsigned char *p = *at;
	size_t header = 2, count, length = 0, i;
	if (*left < 2) return -1;
	item->tag = p[0];
	if (!(p[1] & 128)) length = p[1];
	else {
		count = p[1] & 127;
		if (!count || count > 4 || count > *left - header || !p[2]) return -1;
		for (i = 0; i < count; i++) length = (length << 8) | p[2+i];
		if (length < 128) return -1;
		header += count;
	}
	if (length > *left - header) return -1;
	*item = (struct der) { p, p + header, header + length, length, item->tag };
	*at += item->size;
	*left -= item->size;
	return 0;
}

static int same(const struct der *a, const struct der *b)
{
	return a->size == b->size && !memcmp(a->raw, b->raw, a->size);
}

static int signature_algorithm(const struct der *algorithm)
{
	/* SHA256/MGF1-SHA256, 32-byte salt; old/new OpenSSL encode NULL differently. */
	static const unsigned char legacy[] = {
		0x30,0x3d,0x06,0x09,0x2a,0x86,0x48,0x86,0xf7,0x0d,0x01,0x01,0x0a,0x30,0x30,
		0xa0,0x0d,0x30,0x0b,0x06,0x09,0x60,0x86,0x48,0x01,0x65,0x03,0x04,0x02,0x01,
		0xa1,0x1a,0x30,0x18,0x06,0x09,0x2a,0x86,0x48,0x86,0xf7,0x0d,0x01,0x01,0x08,
		0x30,0x0b,0x06,0x09,0x60,0x86,0x48,0x01,0x65,0x03,0x04,0x02,0x01,0xa2,0x03,0x02,0x01,0x20
	};
	static const unsigned char modern[] = {
		0x30,0x41,0x06,0x09,0x2a,0x86,0x48,0x86,0xf7,0x0d,0x01,0x01,0x0a,0x30,0x34,
		0xa0,0x0f,0x30,0x0d,0x06,0x09,0x60,0x86,0x48,0x01,0x65,0x03,0x04,0x02,0x01,0x05,0x00,
		0xa1,0x1c,0x30,0x1a,0x06,0x09,0x2a,0x86,0x48,0x86,0xf7,0x0d,0x01,0x01,0x08,
		0x30,0x0d,0x06,0x09,0x60,0x86,0x48,0x01,0x65,0x03,0x04,0x02,0x01,0x05,0x00,0xa2,0x03,0x02,0x01,0x20
	};
	return (algorithm->size == sizeof(legacy) && !memcmp(algorithm->raw, legacy, sizeof(legacy))) ||
	       (algorithm->size == sizeof(modern) && !memcmp(algorithm->raw, modern, sizeof(modern)));
}

static int extension_id(const struct der *oid)
{
	static const unsigned char prefix[] = { 0x2b,6,1,4,1,0xa0,0x20,0x90,0x34 };
	unsigned int id = 0;
	size_t i;
	if (oid->tag != 6 || oid->length <= sizeof(prefix) ||
	    oid->length > sizeof(prefix) + 2 || memcmp(oid->data, prefix, sizeof(prefix))) return -1;
	for (i = sizeof(prefix); i < oid->length; i++) {
		id = id * 128 + (oid->data[i] & 127);
		if ((i + 1 < oid->length) != !!(oid->data[i] & 128)) return -1;
	}
	return id;
}

static int parse_cert(const struct tyf_payload *input, struct cert *cert, const struct tyf_crypto *crypto)
{
	const unsigned char *p = input->data, *q;
	size_t left = input->size, n;
	struct der sequence, algorithm, signature, inner, item, ext, oid, critical, value, rsa_key;
	unsigned char hash[32];
	unsigned int i, id;
	static const unsigned int fields[] = { 0xa0,2,0x30,0x30,0x30,0x30,0x30 };
	if (left > 4096 || take(&p, &left, &sequence) || left || sequence.tag != 0x30) return -1;
	p = sequence.data; left = sequence.length;
	if (take(&p, &left, &cert->tbs) || cert->tbs.tag != 0x30 ||
	    take(&p, &left, &algorithm) || !signature_algorithm(&algorithm) ||
	    take(&p, &left, &signature) || left || signature.tag != 3 ||
	    signature.length != 257 || signature.data[0]) return -1;
	cert->signature = signature;
	p = cert->tbs.data; left = cert->tbs.length;
	for (i = 0; i < sizeof(fields)/sizeof(fields[0]); i++) {
		if (take(&p, &left, &item) || item.tag != fields[i]) return -1;
		if (i == 0 && (item.length != 3 || memcmp(item.data, "\x02\x01\x02", 3))) return -1;
		if (i == 2 && !same(&item, &algorithm)) return -1;
		if (i == 6) cert->key = item;
	}
	if (take(&p, &left, &item) || left || item.tag != 0xa3) return -1;
	p = item.data; left = item.length;
	if (take(&p, &left, &sequence) || left || sequence.tag != 0x30) return -1;
	p = sequence.data; left = sequence.length; cert->count = 0;
	while (left) {
		if (take(&p, &left, &ext) || ext.tag != 0x30) return -1;
		q = ext.data; n = ext.length;
		if (take(&q, &n, &oid)) return -1;
		/* cert_create adds these non-critical X.509 bookkeeping fields. */
		if (oid.tag == 6 && oid.length == 3 && oid.data[0] == 0x55 && oid.data[1] == 0x1d &&
		    (oid.data[2] == 14 || oid.data[2] == 35 || oid.data[2] == 19)) {
			if (take(&q, &n, &value) || value.tag != 4 || n) return -1;
			continue;
		}
		if (cert->count == 4 || (int)(id = extension_id(&oid)) < 0 ||
		    take(&q, &n, &critical) || critical.tag != 1 || critical.length != 1 ||
		    critical.data[0] != 0xff || take(&q, &n, &value) || value.tag != 4 || n) return -1;
		for (i = 0; i < cert->count; i++) if (cert->extensions[i].id == id) return -1;
		q = value.data; n = value.length;
		if (take(&q, &n, &inner) || n) return -1;
		cert->extensions[cert->count].id = id;
		cert->extensions[cert->count++].value = inner;
	}
	/* U-Boot's key parser consumes PKCS#1, inside the SPKI BIT STRING. */
	p = cert->key.data; left = cert->key.length;
	if (take(&p, &left, &algorithm) || take(&p, &left, &item) || left ||
	    item.tag != 3 || item.length < 2 || item.data[0]) return -1;
	p = item.data + 1; left = item.length - 1;
	if (take(&p, &left, &rsa_key) || left || rsa_key.tag != 0x30) return -1;
	crypto->sha256(cert->tbs.raw, cert->tbs.size, hash);
	return crypto->verify_pss(rsa_key.raw, rsa_key.size, hash, signature.data + 1, 256);
}

static const struct der *find(const struct cert *cert, unsigned int id)
{
	unsigned int i;
	for (i = 0; i < cert->count; i++) if (cert->extensions[i].id == id) return &cert->extensions[i].value;
	return NULL;
}

static int key_link(const struct cert *parent, unsigned int id, const struct cert *child)
{
	const struct der *key = find(parent, id);
	return key && same(key, &child->key) ? 0 : -1;
}

int tyf_verify_certificates(const void *loader, size_t size, const struct tyf_crypto *crypto)
{
	static const unsigned char ids[6][16] = {
		{0x82,0x7e,0xe8,0x90,0xf8,0x60,0xe4,0x11,0xa1,0xb4,0x77,0x7a,0x21,0xb4,0xf9,0x4c},
		{0x8a,0xb8,0xbe,0xcc,0xf9,0x60,0xe4,0x11,0x9a,0xd0,0xeb,0x48,0x22,0xd8,0xdc,0xf8},
		{0x8a,0xd5,0x83,0x2a,0xfb,0x60,0xe4,0x11,0x8a,0xaf,0xdf,0x30,0xbb,0xc4,0x98,0x59},
		{0xd6,0xe2,0x69,0xea,0x5d,0x63,0xe4,0x11,0x8d,0x8c,0x9f,0xba,0xbe,0x99,0x56,0xa5},
		{0xe2,0xb2,0x0c,0x20,0x5e,0x63,0xe4,0x11,0x9c,0xe8,0xab,0xcc,0xf9,0x2b,0xb6,0x66},
		{0x8e,0xc4,0xc1,0xf3,0x5d,0x63,0xe4,0x11,0xa7,0xa9,0x87,0xee,0x40,0xb2,0x3f,0xa7},
	};
	static const unsigned int allowed[6][4] = {
		{1,302,303,0}, {1,501,0,0}, {2,1101,0,0}, {1,201,202,203}, {1,603,0,0}, {2,1201,0,0}
	};
	static const unsigned int hash_ids[] = { 201,603,1201 };
	static const unsigned char digest_prefix[] = {
		0x30,0x31,0x30,0x0d,0x06,0x09,0x60,0x86,0x48,0x01,0x65,0x03,0x04,0x02,0x01,0x05,0,4,0x20
	};
	const unsigned char *base = loader, *p;
	struct tyf_fip fw;
	struct tyf_payload input[6] = {0}, images[3];
	struct cert certs[6];
	const struct der *value;
	size_t pos;
	unsigned int found = 0, i, j, copy;
	unsigned char hash[32];
	if (tyf_parse_loader(loader, size, &fw)) return -1;
	for (copy = 0; copy < 2; copy++) {
		base = (const unsigned char *)loader + (copy ? TYF_FIP1_OFFSET : TYF_FIP0_OFFSET);
		found = 0;
		for (pos = 16; pos < 16 + 32 * 40; pos += 40) {
			uint64_t offset = 0, length = 0;
			if (!memcmp(base + pos, (unsigned char[16]){0}, 16)) break;
			for (i = 0; i < 8; i++) { offset |= (uint64_t)base[pos+16+i] << (8*i); length |= (uint64_t)base[pos+24+i] << (8*i); }
			for (j = 0; j < 6; j++) if (!memcmp(base + pos, ids[j], 16)) {
				if (copy && (input[j].size != length || memcmp(input[j].data, base + offset, length))) return -1;
				input[j] = (struct tyf_payload) { base + offset, length }; found |= 1U << j;
			}
		}
		if (found != 63) return -1;
	}
	for (i = 0; i < 6; i++) {
		if (parse_cert(&input[i], &certs[i], crypto)) return -1;
		for (j = 0; j < 4 && allowed[i][j]; j++) if (!find(&certs[i], allowed[i][j])) return -1;
		if (j != certs[i].count) return -1;
		value = find(&certs[i], allowed[i][0]);
		if (value->size != 3 || memcmp(value->raw, "\x02\x01\x00", 3)) return -1;
	}
	if (!same(&certs[0].key, &certs[3].key) || key_link(&certs[0],302,&certs[1]) ||
	    key_link(&certs[0],303,&certs[2]) || key_link(&certs[1],501,&certs[4]) ||
	    key_link(&certs[2],1101,&certs[5])) return -1;
	images[0] = fw.bl2; images[1] = fw.bl31; images[2] = fw.bl33;
	for (i = 0; i < 3; i++) {
		value = find(&certs[3+i], hash_ids[i]);
		if (value->size != 51 || memcmp(value->raw, digest_prefix, sizeof(digest_prefix))) return -1;
		p = value->raw + sizeof(digest_prefix);
		crypto->sha256(images[i].data, images[i].size, hash);
		if (memcmp(p, hash, sizeof(hash))) return -1;
	}
	return 0;
}
