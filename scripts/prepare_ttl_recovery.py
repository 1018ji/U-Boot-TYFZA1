#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build a Kermit-loadable recovery script for official TYFZA1 U-Boot 1.4."""
import argparse
import hashlib
from pathlib import Path
import struct
import zlib

BUNDLE_SHA256 = 'e340dc0ea985a6cfe5aa41b0815c9b8559e3ce554f9370783468a2cfc5df6b46'
BOOT, FIP, HEADER = 0x200000, 0xc0000, 16
LOAD, PAYLOAD = 0x11000000, 0x20000
CURRENT, READBACK, SCRATCH = 0x10000000, 0x10200000, 0x10300000
BL2 = bytes.fromhex('5ff9ec0b4d223e4da544c39d81c73f0a')
BL31 = bytes.fromhex('47d4086d4cfe98469b952950cbbd5a00')


def fip_entries(image):
    data = image[0x40000:0x100000]
    entries = {}
    for pos in range(16, 16 + 32 * 40, 40):
        uid, offset, size, _ = struct.unpack_from('<16sQQQ', data, pos)
        if uid == bytes(16):
            break
        if not size or offset > FIP or size > FIP - offset:
            raise ValueError('Invalid FIP payload bounds')
        entries[uid] = (offset, size)
    if BL2 not in entries or BL31 not in entries:
        raise ValueError('Missing BL2/BL31')
    return entries


def fixed_layout_ranges():
    """Same variable fields as formats.c; all other non-FIP bytes must match."""
    variable = []
    for h, e in ((0x200, 0x400), (0x1ffe00, 0x1fbe00)):
        variable.extend((h + a, h + b) for a, b in ((16, 20), (56, 72), (88, 92)))
        variable.extend((e + i * 128 + 16, e + i * 128 + 32) for i in range(128))
        variable.extend((e + i * 128 + 40, e + i * 128 + 48) for i in range(2))
    for begin, end in ((0, 0x40000), (0x1c0000, BOOT)):
        at = begin
        for left, right in sorted(variable):
            if right <= begin or left >= end:
                continue
            if at < left:
                yield at, left - at
            at = max(at, right)
        if at < end:
            yield at, end - at


def recovery_script(bundle):
    if len(bundle) != HEADER + 2 * BOOT or bundle[:HEADER] != b'TYFZA1-UBOOT-V1\0':
        raise ValueError('Expected the complete official universal.bin, not .run or a boot backup')
    if hashlib.sha256(bundle).hexdigest() != BUNDLE_SHA256:
        raise ValueError('SHA256 differs from official v1.4; download its universal.bin again')
    images = [bundle[HEADER + i * BOOT:HEADER + (i + 1) * BOOT] for i in range(2)]
    entries = [fip_entries(image) for image in images]
    for image in images:
        if image[0x40000:0x100000] != image[0x100000:0x1c0000]:
            raise ValueError('Redundant FIPs differ')

    lines = [
        'echo TTL recovery for TYFZA1 - official U-Boot 1.4',
        'setenv ttl_old_ids "${mtdids}"',
        'setenv ttl_old_parts "${mtdparts}"',
        "setenv ttl_cleanup 'setenv mtdids \"${ttl_old_ids}\"; setenv mtdparts \"${ttl_old_parts}\"'",
    ]

    def check(command, reason):
        lines.append(f'if {command}; then true; else echo TTL STOP: {reason}; run ttl_cleanup; exit 1; fi')

    base = LOAD + PAYLOAD
    check('base 0', 'cannot reset memory command base')
    check(f'hash sha256 {base:x} {len(bundle):x} ttl_hash && '
          f'itest.s "${{ttl_hash}}" == {BUNDLE_SHA256}', 'package checksum failed')
    check('nand device 0', 'cannot select NAND0')
    check('setenv mtdids nand0=nand0 && setenv mtdparts "mtdparts=nand0:2m(boot)"',
          'cannot set temporary boot partition')
    # Reading all 2 MiB through a 2 MiB partition refuses any bad-block skip.
    check(f'nand read {CURRENT:x} boot {BOOT:x}', 'boot read failed or boot contains bad blocks')

    lines.extend(['setenv ttl_image', 'setenv ttl_variant'])
    for index, variant in enumerate(('4ge', '2p5g')):
        image_addr = base + HEADER + index * BOOT
        conditions = []
        for old_fip in (0x40000, 0x100000):
            conditions.append(f'cmp.b {CURRENT + old_fip:x} {image_addr + 0x40000:x} 60')
            for uid in (BL2, BL31):
                offset, size = entries[index][uid]
                conditions.append(f'cmp.b {CURRENT + old_fip + offset:x} '
                                  f'{image_addr + 0x40000 + offset:x} {size:x}')
        lines.append(('if ' if index == 0 else 'elif ') + ' && '.join(conditions) + '; then')
        lines.extend([f'setenv ttl_image {image_addr:x}', f'setenv ttl_variant {variant}'])
    lines.append('else echo TTL STOP: early firmware does not match; run ttl_cleanup; exit 1; fi')
    lines.append('echo Matching early firmware: ${ttl_variant}')

    for offset, size in fixed_layout_ranges():
        check(f'setexpr ttl_ptr ${{ttl_image}} + {offset:x} && '
              f'cmp.b {CURRENT + offset:x} ${{ttl_ptr}} {size:x}', 'GPT or reserved layout differs')
    for header, table in ((0x200, 0x400), (0x1ffe00, 0x1fbe00)):
        h, e = CURRENT + header, CURRENT + table
        check(f'cp.b {h:x} {SCRATCH:x} 5c && mw.l {SCRATCH + 16:x} 0 && '
              f'hash crc32 {SCRATCH:x} 5c ttl_crc && itest.l ${{ttl_crc}} == *{h + 16:x}',
              'GPT header CRC differs')
        check(f'hash crc32 {e:x} 4000 ttl_crc && itest.l ${{ttl_crc}} == *{h + 88:x}',
              'GPT table CRC differs')
        for index, start in enumerate((0x40000, 0x100000)):
            # Both official variants must fit the existing partition length.
            used = max(max(off + size for off, size in items.values()) for items in entries)
            first, limit = start // 512, (start + FIP) // 512
            minimum = first + (used + 511) // 512 - 1
            last = e + index * 128 + 40
            check(f'itest.l *{last + 4:x} == 0 && itest.l *{last:x} -ge {minimum:x} && '
                  f'itest.l *{last:x} -lt {limit:x}', 'GPT FIP capacity is invalid')
    for index in range(2):
        check(f'cmp.l {CURRENT + 0x400 + index * 128 + 40:x} '
              f'{CURRENT + 0x1fbe00 + index * 128 + 40:x} 2', 'primary and backup FIP lengths differ')

    lines.append('if itest.s "${ttl_action}" == write; then true; else '
                 'echo TTL CHECK OK - no Flash changed; run ttl_cleanup; exit 0; fi')
    check('setenv mtdparts "mtdparts=nand0:768k@0x40000(ttl_fip0),768k@0x100000(ttl_fip1)"',
          'cannot set bounded FIP partitions')
    for copy in (0, 1):
        check(f'nand read {READBACK:x} ttl_fip{copy} {FIP:x}', 'FIP preflight read failed')
    check('setexpr ttl_fip ${ttl_image} + 40000', 'cannot locate new FIP')
    for copy in (1, 0):
        check(f'nand erase.part ttl_fip{copy}', f'FIP{copy} erase failed - keep power on')
        check(f'nand write ${{ttl_fip}} ttl_fip{copy} {FIP:x}', f'FIP{copy} write failed - keep power on')
        check(f'nand read {READBACK:x} ttl_fip{copy} {FIP:x} && '
              f'cmp.b {READBACK:x} ${{ttl_fip}} {FIP:x}', f'FIP{copy} readback failed - keep power on')
        lines.append(f'echo FIP{copy} written and read back')
    lines.extend(['run ttl_cleanup', 'echo "TTL WRITE OK - U-Boot 1.4 installed; reset manually"'])
    return ('\n'.join(lines) + '\n').encode('ascii')


def prepare(bundle):
    script = recovery_script(bundle)
    # Legacy script length table selects only the ASCII script. The image CRC
    # also covers the embedded, pinned universal package after the padding.
    body = struct.pack('>II', len(script), 0) + script
    if len(body) > PAYLOAD - 64:
        raise ValueError('Recovery script exceeds its reserved prefix')
    body += bytes(PAYLOAD - 64 - len(body)) + bundle
    fields = [0x27051956, 0, 0, len(body), 0, 0, zlib.crc32(body), 17, 22, 6, 0,
              b'TYFZA1 TTL recovery 1.4']
    header = struct.pack('>7I4B32s', *fields)
    fields[1] = zlib.crc32(header)
    return struct.pack('>7I4B32s', *fields) + body


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('--output', type=Path, default=Path('tyfza1-ttl-recovery.scr'))
    args = parser.parse_args()
    if args.output.resolve() == args.bundle.resolve():
        parser.error('Output must not overwrite universal.bin')
    try:
        data = prepare(args.bundle.read_bytes())
    except ValueError as error:
        parser.exit(1, str(error) + '\n')
    args.output.write_bytes(data)
    print(f'{args.output}: {len(data)} bytes; SHA256 {hashlib.sha256(data).hexdigest()}')
    print('Kermit: loadb 11000000; then send this .scr file (binary/Kermit).')
    print('Check only: setenv verify yes; setenv ttl_action check; source 11000000')
    print('Write after CHECK OK: setenv ttl_action write; source 11000000')
