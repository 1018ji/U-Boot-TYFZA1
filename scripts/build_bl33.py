#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Wrap U-Boot as a bounded, self-relocating AArch64 LZMA BL33 payload."""
import argparse
import hashlib
import json
import lzma
import os
from pathlib import Path
import struct
import subprocess
import zlib

ROOT = Path(__file__).resolve().parents[1]


def build(input_path, output_path, qemu=False):
    data = Path(input_path).read_bytes()
    if not data or len(data) > 0x800000:
        raise ValueError("Expected a non-empty U-Boot image no larger than 8 MiB")
    work = ROOT / "build/bl33" / ("qemu" if qemu else "tyfza1")
    work.mkdir(parents=True, exist_ok=True)
    sdk = work / "sdk"
    sdk.mkdir(exist_ok=True)
    reference = ROOT / "sources/uboot-an758x"
    pinned = json.loads((ROOT / "source-lock.json").read_text())["reference"]["commit"]
    for name in ("LzmaDec.c", "LzmaDec.h", "7zTypes.h", "Compiler.h", "Precomp.h"):
        (sdk / name).write_bytes(subprocess.check_output(["git", "-C", str(reference),
            "show", f"{pinned}:lib/lzma/{name}"]))
    decoder = sdk / "LzmaDec.c"
    text = decoder.read_text().replace("#include <config.h>", "")
    text = text.replace("#include <watchdog.h>", "").replace("#include <linux/string.h>", "#include <string.h>")
    text = text.replace("schedule();", "((void)0);")
    decoder.write_text(text)
    compressed = lzma.compress(data, format=lzma.FORMAT_ALONE, filters=[{
        "id": lzma.FILTER_LZMA1, "dict_size": 1 << 20, "lc": 3, "lp": 0, "pb": 2,
        "mode": lzma.MODE_NORMAL, "nice_len": 128, "mf": lzma.MF_BT4}])
    compressed = compressed[:5] + struct.pack("<Q", len(data)) + compressed[13:]
    assert lzma.decompress(compressed, format=lzma.FORMAT_ALONE) == data
    payload = work / "payload.lzma"
    payload.write_bytes(compressed)
    run, execute, stack = (0x41000000, 0x48000000, 0x4f000000) if qemu else (0x04000000, 0x08000000, 0x01000000)
    config = {
        "RUN_ADDR": run, "EXEC_ADDR": execute, "STACK_TOP": stack,
        "PLAIN_SIZE": len(data), "PLAIN_CRC": zlib.crc32(data), "LOADER_QEMU": int(qemu),
        "UART_BASE": 0x09000000 if qemu else 0xf43291b0,
        "UART_DATA": 0 if qemu else 0x10, "UART_FULL": 1 << (5 if qemu else 2),
    }
    (work / "loader-config.h").write_text("".join(f"#define {key} {value:#x}\n" for key, value in config.items()))
    (work / "payload.S").write_text('.section .rodata.payload,"a"\n.balign 16\n.global payload_start,payload_end\npayload_start:\n.incbin "' + str(payload) + '"\npayload_end:\n')
    (work / "linker.lds").write_text(f"""ENTRY(_start)
PHDRS {{ code PT_LOAD FLAGS(5); data PT_LOAD FLAGS(6); }}
SECTIONS {{
 . = {execute:#x};
 .text : {{ KEEP(*(.text.start)) *(.text*) }} :code
 .rodata : {{ *(.rodata*) }} :code
 .data : {{ *(.data*) }} :data
 .tail : {{ BYTE(0); . = ALIGN(16); }} :data
 _image_end = .;
 .bss (NOLOAD) : {{ . = ALIGN(16); __bss_start = .; *(.bss*) *(COMMON) . = ALIGN(16); __bss_end = .; }} :data
 /DISCARD/ : {{ *(.comment*) *(.note*) *(.eh_frame*) }}
}}
""")
    prefix = os.environ.get("CROSS_COMPILE", "aarch64-linux-gnu-")
    flags = ["-Os", "-ffreestanding", "-fno-builtin", "-fno-stack-protector", "-fno-pie",
             "-mgeneral-regs-only", "-mstrict-align", "-ffunction-sections", "-fdata-sections", "-Wall", "-Wextra", "-Werror",
             "-DZ7_LZMA_SIZE_OPT", "-I" + str(work), "-I" + str(sdk)]
    objects = []
    for name, source in [("start", ROOT / "loader/start.S"), ("main", ROOT / "loader/main.c"),
                         ("decoder", decoder), ("payload", work / "payload.S")]:
        obj = work / (name + ".o")
        subprocess.run([prefix + "gcc", *flags, "-c", str(source), "-o", str(obj)], check=True)
        objects.append(str(obj))
    elf = work / "bl33.elf"
    subprocess.run([prefix + "ld", "--gc-sections", "--build-id=none", "-T", str(work / "linker.lds"),
                    *objects, "-o", str(elf)], check=True)
    symbols = subprocess.check_output([prefix + "nm", "-n", str(elf)], text=True)
    addresses = {line.split()[2]: int(line.split()[0], 16) for line in symbols.splitlines() if len(line.split()) == 3}
    if addresses["__bss_end"] >= execute + 0x1000000 or run + len(data) >= execute:
        raise ValueError("BL33 workspace overlaps its source or a reserved RAM boundary")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([prefix + "objcopy", "-O", "binary", str(elf), str(output_path)], check=True)
    image = output_path.read_bytes()
    if len(image) != addresses["_image_end"] - execute:
        raise ValueError("Loader relocation length differs from the emitted image")
    report = {"plain_bytes": len(data), "plain_sha256": hashlib.sha256(data).hexdigest(),
              "lzma_bytes": len(compressed), "bl33_bytes": len(image), "bl33_sha256": hashlib.sha256(image).hexdigest(),
              "run_address": hex(run), "relocation_address": hex(execute), "stack_top": hex(stack),
              "workspace_end": hex(addresses["__bss_end"]), "qemu_fixture": qemu}
    output_path.with_suffix(output_path.suffix + ".json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--qemu", action="store_true", help="Use the QEMU virt RAM map for emulator tests only")
    args = parser.parse_args()
    build(args.input, args.output, args.qemu)
