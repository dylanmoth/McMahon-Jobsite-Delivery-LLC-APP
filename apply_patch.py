from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"Could not locate integration point: {label}")
    return text.replace(old, new, 1)


def patch_init(path: Path) -> None:
    path.write_text(
        '"""McMahon Dispatch desktop application."""\n\n'
        'from mcmahon_dispatch.core.version import __version__\n\n'
        '__all__ = ["__version__"]\n',
        encoding="utf-8",
    )


def patch_config(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from platformdirs import PlatformDirs\n",
        "from platformdirs import PlatformDirs\n\n"
        "from mcmahon_dispatch.core.version import (\n"
        "    APP_NAME,\n"
        "    COMPANY_NAME,\n"
        "    GITHUB_RELEASES_API,\n"
        "    __version__,\n"
        ")\n",
        "config version imports",
    )
    text = replace_once(
        text,
        "    inactivity_lock_minutes: int\n    paths: AppPaths\n",
        "    inactivity_lock_minutes: int\n"
        "    update_api_url: str\n"
        "    paths: AppPaths\n",
        "AppConfig update URL field",
    )
    text = text.replace('            app_name="McMahon Dispatch",', "            app_name=APP_NAME,")
    text = re.sub(
        r'            app_version="[^"]+",',
        "            app_version=__version__,",
        text,
        count=1,
    )
    text = text.replace(
        '            organization_name="McMahon Jobsite Delivery LLC",',
        "            organization_name=COMPANY_NAME,",
    )
    text = replace_once(
        text,
        "            inactivity_lock_minutes=max(1, int(os.getenv(\"MCMAHON_INACTIVITY_LOCK_MINUTES\", \"15\"))),\n"
        "            paths=paths,\n",
        "            inactivity_lock_minutes=max(1, int(os.getenv(\"MCMAHON_INACTIVITY_LOCK_MINUTES\", \"15\"))),\n"
        "            update_api_url=os.getenv(\n"
        "                \"MCMAHON_UPDATE_API_URL\", GITHUB_RELEASES_API\n"
        "            ).strip(),\n"
        "            paths=paths,\n",
        "AppConfig update URL value",
    )
    path.write_text(text, encoding="utf-8")


def patch_settings(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '        "security.inactivity_lock_minutes": 15,\n',
        '        "security.inactivity_lock_minutes": 15,\n'
        '        "updates.auto_check": True,\n'
        '        "updates.last_checked_at": "",\n',
        "update settings defaults",
    )
    path.write_text(text, encoding="utf-8")


def patch_main_window(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from mcmahon_dispatch.ui.theme.theme_manager import ThemeManager\n",
        "from mcmahon_dispatch.ui.theme.theme_manager import ThemeManager\n"
        "from mcmahon_dispatch.ui.update_controller import UpdateController\n",
        "update controller import",
    )
    text = replace_once(
        text,
        "        self.theme_manager = theme_manager\n",
        "        self.theme_manager = theme_manager\n"
        "        self.update_controller = UpdateController(self, config, self.settings)\n",
        "update controller creation",
    )
    text = replace_once(
        text,
        "        self.user_badge = QLabel(user.display_name)\n",
        '        self.update_button = QPushButton("Check for Updates")\n'
        '        self.update_button.setObjectName("secondary")\n'
        '        self.update_button.setToolTip("Check for a newer signed release")\n'
        '        self.update_button.clicked.connect(\n'
        '            lambda: self.update_controller.check(manual=True)\n'
        '        )\n\n'
        "        self.user_badge = QLabel(user.display_name)\n",
        "update button creation",
    )
    text = replace_once(
        text,
        "        self.navigate(start_route if self._route_available(start_route) else \"dashboard\")\n",
        "        self.navigate(start_route if self._route_available(start_route) else \"dashboard\")\n"
        "        self.update_controller.schedule_automatic_check()\n",
        "automatic update scheduling",
    )
    text = replace_once(
        text,
        "        top_bar_layout.addStretch(1)\n        top_bar_layout.addWidget(self.user_badge)\n",
        "        top_bar_layout.addStretch(1)\n"
        "        top_bar_layout.addWidget(self.update_button)\n"
        "        top_bar_layout.addWidget(self.user_badge)\n",
        "update button placement",
    )
    path.write_text(text, encoding="utf-8")


def patch_pyproject(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = re.sub(
        r'(?m)^version = "\d+\.\d+\.\d+"\n',
        'dynamic = ["version"]\n',
        text,
        count=1,
    )
    if "[tool.hatch.version]" not in text:
        marker = '[project.scripts]\nmcmahon-dispatch = "mcmahon_dispatch.__main__:main"\n'
        text = replace_once(
            text,
            marker,
            marker + '\n[tool.hatch.version]\npath = "src/mcmahon_dispatch/core/version.py"\n',
            "Hatch dynamic version",
        )
    path.write_text(text, encoding="utf-8")


def patch_gitignore(path: Path) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    additions = "\n# Release outputs\nbuild/pyinstaller/\nbuild/version_info.txt\ndist/\nrelease/\n*.spec.bak\n"
    if "release/" not in text:
        text = text.rstrip() + additions
    path.write_text(text.lstrip(), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project",
        type=Path,
        default=Path(r"C:\Users\thedy\OneDrive\Desktop\MJD BUSINESS\McMahonDispatch"),
    )
    args = parser.parse_args()
    project = args.project.resolve()
    payload = Path(__file__).resolve().parent / "payload"
    if not (project / "src/mcmahon_dispatch").is_dir():
        raise RuntimeError(f"McMahon Dispatch project not found at {project}")

    backup_root = project / "backups" / "release-patch-v1.3.0"
    backup_root.mkdir(parents=True, exist_ok=True)
    modified = [
        "src/mcmahon_dispatch/__init__.py",
        "src/mcmahon_dispatch/core/config.py",
        "src/mcmahon_dispatch/services/settings_service.py",
        "src/mcmahon_dispatch/ui/main_window.py",
        "pyproject.toml",
        ".gitignore",
        "README.md",
    ]
    for relative in modified:
        source = project / relative
        if source.exists():
            destination = backup_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    for source in payload.rglob("*"):
        if source.is_file():
            destination = project / source.relative_to(payload)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    patch_init(project / "src/mcmahon_dispatch/__init__.py")
    patch_config(project / "src/mcmahon_dispatch/core/config.py")
    patch_settings(project / "src/mcmahon_dispatch/services/settings_service.py")
    patch_main_window(project / "src/mcmahon_dispatch/ui/main_window.py")
    patch_pyproject(project / "pyproject.toml")
    patch_gitignore(project / ".gitignore")

    print("McMahon Dispatch v1.3.0 production release patch applied successfully.")
    print(f"Backups of modified files: {backup_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
