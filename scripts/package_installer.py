#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Package the Linux flasher and universal loader as one self-extracting file."""
import argparse
import gzip
import hashlib
import io
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def package(directory):
    directory = Path(directory)
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode='w', format=tarfile.USTAR_FORMAT) as target:
        for name, mode in [('tyfza1-flash-uboot', 0o700), ('tyfza1-uboot-universal.bin', 0o600)]:
            data = (directory / name).read_bytes()
            entry = tarfile.TarInfo(name)
            entry.size, entry.mode = len(data), mode
            target.addfile(entry, io.BytesIO(data))
    payload = gzip.compress(archive.getvalue(), mtime=0)
    header = (ROOT / 'scripts/install_uboot.sh').read_text()
    header = header.replace('@PAYLOAD_LINE@', str(header.count('\n') + 1))
    header = header.replace('@PAYLOAD_SHA256@', hashlib.sha256(payload).hexdigest())
    output = directory / 'tyfza1-uboot-install.run'
    output.write_bytes(header.encode() + payload)
    output.chmod(0o755)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', nargs='?', type=Path, default=ROOT / 'output/release')
    print(package(parser.parse_args().directory))
