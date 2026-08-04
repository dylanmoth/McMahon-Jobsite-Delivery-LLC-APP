from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    major, minor, patch = (int(part) for part in args.version.split("."))
    content = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({major}, {minor}, {patch}, 0),
    prodvers=({major}, {minor}, {patch}, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName', 'McMahon Jobsite Delivery LLC'),
          StringStruct('FileDescription', 'McMahon Dispatch'),
          StringStruct('FileVersion', '{args.version}'),
          StringStruct('InternalName', 'McMahon Dispatch'),
          StringStruct('LegalCopyright', 'Copyright © 2026 McMahon Jobsite Delivery LLC'),
          StringStruct('OriginalFilename', 'McMahon Dispatch.exe'),
          StringStruct('ProductName', 'McMahon Dispatch'),
          StringStruct('ProductVersion', '{args.version}')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
