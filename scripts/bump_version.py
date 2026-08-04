from __future__ import annotations

import argparse
import re
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Update McMahon Dispatch's single source version.")
    parser.add_argument("version", help="Semantic version, for example 1.4.0")
    args = parser.parse_args()
    if not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
        raise SystemExit("Version must use MAJOR.MINOR.PATCH.")

    path = Path("src/mcmahon_dispatch/core/version.py")
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(
        r'__version__ = "\d+\.\d+\.\d+"',
        f'__version__ = "{args.version}"',
        text,
        count=1,
    )
    if count != 1:
        raise SystemExit("Could not find __version__ in version.py.")
    path.write_text(updated, encoding="utf-8")
    print(f"Version updated to {args.version}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
