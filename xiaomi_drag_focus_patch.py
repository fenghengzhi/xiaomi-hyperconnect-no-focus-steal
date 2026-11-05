#!/usr/bin/env python3
"""Prepare an unsigned, reversible Xiaomi Interconnectivity test copy.

This tool never changes the installed app, preferences, permissions, or system
security settings. It does not sign, install, or launch the modified copy.
Only the exact inspected 3.0.300 (285) universal executable is accepted.
"""

import argparse
import hashlib
import json
import plistlib
from pathlib import Path
import struct
import subprocess


SOURCE_SHA256 = "151c34a603f3e568eff7245830ad3034092cb12eb1e961cbe5ae91af33d1c259"
TARGET_VA = 0x10075FDF4
BEFORE = bytes.fromhex("8d1a0e94")
AFTER = bytes.fromhex("1f2003d5")  # ARM64 NOP
EXECUTABLE = Path("Contents/MacOS/小米互联服务")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def locate_patch(data):
    magic, count = struct.unpack_from(">II", data)
    if magic != 0xCAFEBABE or count != 2:
        raise ValueError("Unexpected universal Mach-O header")
    arm = []
    for i in range(count):
        cpu, subtype, offset, size, alignment = struct.unpack_from(">IIIII", data, 8 + 20 * i)
        if cpu == 0x0100000C:
            arm.append((offset, size))
    if len(arm) != 1:
        raise ValueError("Expected one ARM64 slice")
    slice_offset, slice_size = arm[0]
    if slice_offset + slice_size > len(data):
        raise ValueError("Invalid ARM64 slice extent")
    header = struct.unpack_from("<IIIIIIII", data, slice_offset)
    if header[0] != 0xFEEDFACF:
        raise ValueError("Unexpected ARM64 Mach-O header")
    position = slice_offset + 32
    candidates = []
    for _ in range(header[4]):
        command, command_size = struct.unpack_from("<II", data, position)
        if command_size < 8:
            raise ValueError("Invalid load command")
        if command == 0x19:  # LC_SEGMENT_64
            name = data[position + 8:position + 24].rstrip(b"\0")
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<QQQQ", data, position + 24)
            if name == b"__TEXT" and vmaddr <= TARGET_VA < vmaddr + filesize:
                candidates.append(slice_offset + fileoff + TARGET_VA - vmaddr)
        position += command_size
    if len(candidates) != 1:
        raise ValueError("Target address does not map uniquely to __TEXT")
    offset = candidates[0]
    if data[offset:offset + 4] != BEFORE:
        raise ValueError("Target instruction does not match; refusing to patch")
    return offset, slice_offset


def inspect(source):
    info = plistlib.loads((source / "Contents/Info.plist").read_bytes())
    identity = (info.get("CFBundleIdentifier"), info.get("CFBundleShortVersionString"), info.get("CFBundleVersion"))
    if identity != ("com.xiaomi.hyperConnect", "3.0.300", "285"):
        raise ValueError("Unsupported application identity or version")
    original = (source / EXECUTABLE).read_bytes()
    if digest(original) != SOURCE_SHA256:
        raise ValueError("Executable SHA-256 differs from inspected version; refusing to patch")
    offset, slice_offset = locate_patch(original)
    return original, offset, slice_offset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("/Applications/小米互联服务.app"))
    parser.add_argument("--prepare", type=Path, metavar="NEW_COPY.app", help="Create a new unsigned test copy; otherwise only inspect")
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    original, offset, slice_offset = inspect(source)
    result = {
        "version": "3.0.300 (285)",
        "architecture": "arm64 only; x86_64 unchanged",
        "original_sha256": SOURCE_SHA256,
        "virtual_address": hex(TARGET_VA),
        "universal_file_offset": hex(offset),
        "arm64_file_offset": hex(offset - slice_offset),
        "before": BEFORE.hex(),
        "after": AFTER.hex(),
        "purpose": "Skip the early activateIgnoringOtherApps(true) call in the drag proximity check",
        "runtime_tested": False,
        "installed_application_modified": False,
    }
    if args.prepare is not None:
        destination = args.prepare.absolute()
        if destination.suffix != ".app" or destination.exists() or destination.is_symlink():
            raise ValueError("Destination must be a new, nonexistent .app path")
        if destination.resolve().is_relative_to(source):
            raise ValueError("Destination cannot be inside the source app")
        if destination.resolve().is_relative_to(Path("/Applications")):
            raise ValueError("Prepare the experimental copy outside /Applications")
        report = destination.parent / (destination.stem + ".patch-report.json")
        if report.exists() or report.is_symlink():
            raise ValueError("Patch report already exists; choose a different destination")
        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["/usr/bin/ditto", str(source), str(destination)], check=True)
        target = destination / EXECUTABLE
        copied = target.read_bytes()
        if copied != original:
            raise ValueError("Copied executable differs from inspected source; no patch applied")
        patched = original[:offset] + AFTER + original[offset + 4:]
        target.write_bytes(patched)
        actual = target.read_bytes()
        if actual != patched or actual[:offset] != original[:offset] or actual[offset + 4:] != original[offset + 4:]:
            raise ValueError("Post-patch verification failed")
        if digest((source / EXECUTABLE).read_bytes()) != SOURCE_SHA256:
            raise ValueError("Installed app changed during preparation")
        result.update({
            "prepared_copy": str(destination),
            "patched_sha256": digest(patched),
            "signature": "Invalidated by patch; deliberately not re-signed or launched",
            "rollback": "The installed original remains untouched. Do not run both copies concurrently.",
        })
        with report.open("x", encoding="utf-8") as output:
            output.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
