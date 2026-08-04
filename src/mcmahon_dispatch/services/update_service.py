from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from mcmahon_dispatch.core.version import APP_NAME, GITHUB_RELEASES_API, __version__


class UpdateError(RuntimeError):
    """Raised when the update service cannot safely complete an operation."""


@dataclass(frozen=True, slots=True)
class ReleaseAsset:
    name: str
    download_url: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    version: str
    release_name: str
    notes: str
    published_at: str
    installer: ReleaseAsset
    checksum: ReleaseAsset
    web_url: str


ProgressCallback = Callable[[int, int], None]


class UpdateService:
    """GitHub Releases based updater with mandatory SHA-256 verification.

    The application never replaces its own files directly. It downloads a signed
    Inno Setup installer, verifies the published checksum, then launches the
    installer after the user explicitly approves installation.
    """

    INSTALLER_PATTERN = re.compile(
        r"^McMahonDispatch-Setup-(?P<version>\d+\.\d+\.\d+)\.exe$",
        re.IGNORECASE,
    )
    MAX_MANIFEST_BYTES = 2 * 1024 * 1024
    MAX_INSTALLER_BYTES = 500 * 1024 * 1024
    ALLOWED_INITIAL_HOSTS = {"api.github.com", "github.com"}

    def __init__(
        self,
        *,
        current_version: str = __version__,
        releases_api_url: str = GITHUB_RELEASES_API,
        cache_directory: Path,
        timeout_seconds: int = 20,
    ) -> None:
        self.current_version = current_version
        self.releases_api_url = releases_api_url
        self.cache_directory = cache_directory
        self.timeout_seconds = timeout_seconds

    def check(self) -> UpdateInfo | None:
        if os.getenv("MCMAHON_DISABLE_UPDATES", "").strip().lower() in {"1", "true", "yes"}:
            return None

        payload = self._read_json(self.releases_api_url)
        if payload.get("draft") or payload.get("prerelease"):
            return None

        version = self._normalize_version(str(payload.get("tag_name", "")))
        if not version:
            raise UpdateError("The latest release does not contain a valid semantic version tag.")
        if self._version_tuple(version) <= self._version_tuple(self.current_version):
            return None

        installer: ReleaseAsset | None = None
        checksum: ReleaseAsset | None = None
        for raw_asset in payload.get("assets", []):
            if not isinstance(raw_asset, dict):
                continue
            asset = ReleaseAsset(
                name=str(raw_asset.get("name", "")),
                download_url=str(raw_asset.get("browser_download_url", "")),
                size_bytes=int(raw_asset.get("size", 0) or 0),
            )
            match = self.INSTALLER_PATTERN.match(asset.name)
            if match and match.group("version") == version:
                installer = asset
            if asset.name.lower() in {
                f"mcmahondispatch-setup-{version}.exe.sha256".lower(),
                "sha256sums.txt",
            }:
                checksum = asset

        if installer is None:
            raise UpdateError(f"Release {version} is missing McMahonDispatch-Setup-{version}.exe.")
        if checksum is None:
            raise UpdateError(f"Release {version} is missing a SHA-256 checksum asset.")
        if installer.size_bytes <= 0 or installer.size_bytes > self.MAX_INSTALLER_BYTES:
            raise UpdateError("The update installer has an invalid or unsafe file size.")

        return UpdateInfo(
            version=version,
            release_name=str(payload.get("name") or f"{APP_NAME} {version}"),
            notes=str(payload.get("body") or ""),
            published_at=str(payload.get("published_at") or ""),
            installer=installer,
            checksum=checksum,
            web_url=str(payload.get("html_url") or ""),
        )

    def download(
        self,
        update: UpdateInfo,
        progress: ProgressCallback | None = None,
    ) -> Path:
        self.cache_directory.mkdir(parents=True, exist_ok=True)
        target = self.cache_directory / update.installer.name
        partial = target.with_suffix(target.suffix + ".part")

        expected_hash = self._download_expected_hash(update)
        request = self._request(update.installer.download_url)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                final_url = response.geturl()
                self._validate_redirect_target(final_url)
                total = int(response.headers.get("Content-Length") or update.installer.size_bytes)
                if total <= 0 or total > self.MAX_INSTALLER_BYTES:
                    raise UpdateError("The update download reported an unsafe file size.")
                downloaded = 0
                digest = hashlib.sha256()
                with partial.open("wb") as handle:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        downloaded += len(chunk)
                        if downloaded > self.MAX_INSTALLER_BYTES:
                            raise UpdateError("The update exceeded the maximum allowed size.")
                        digest.update(chunk)
                        handle.write(chunk)
                        if progress is not None:
                            progress(downloaded, total)
                    handle.flush()
                    os.fsync(handle.fileno())
        except (OSError, urllib.error.URLError) as exc:
            partial.unlink(missing_ok=True)
            raise UpdateError(f"Unable to download the update: {exc}") from exc

        if digest.hexdigest().lower() != expected_hash.lower():
            partial.unlink(missing_ok=True)
            raise UpdateError(
                "The downloaded installer failed SHA-256 verification and was deleted."
            )

        os.replace(partial, target)
        return target

    @staticmethod
    def launch_installer(installer_path: Path) -> None:
        if not installer_path.is_file():
            raise UpdateError("The downloaded installer could not be found.")
        try:
            subprocess.Popen(
                [
                    str(installer_path),
                    "/SP-",
                    "/SILENT",
                    "/CLOSEAPPLICATIONS",
                    "/RESTARTAPPLICATIONS",
                ],
                close_fds=True,
            )
        except OSError as exc:
            raise UpdateError(f"Unable to launch the update installer: {exc}") from exc

    def _download_expected_hash(self, update: UpdateInfo) -> str:
        raw = self._read_bytes(
            update.checksum.download_url,
            max_bytes=self.MAX_MANIFEST_BYTES,
        ).decode("utf-8", errors="strict")
        installer_name = update.installer.name.lower()
        candidates: list[str] = []
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            parts = stripped.replace("*", " ").split()
            if parts and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
                if len(parts) == 1 or installer_name in " ".join(parts[1:]).lower():
                    candidates.append(parts[0].lower())
        if len(candidates) != 1:
            raise UpdateError("The release checksum file is missing or ambiguous.")
        return candidates[0]

    def _read_json(self, url: str) -> dict:
        raw = self._read_bytes(url, max_bytes=self.MAX_MANIFEST_BYTES)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UpdateError("The update service returned invalid JSON.") from exc
        if not isinstance(value, dict):
            raise UpdateError("The update service returned an unexpected response.")
        return value

    def _read_bytes(self, url: str, *, max_bytes: int) -> bytes:
        request = self._request(url)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                self._validate_redirect_target(response.geturl())
                data = response.read(max_bytes + 1)
        except (OSError, urllib.error.URLError) as exc:
            raise UpdateError(f"Unable to contact the update service: {exc}") from exc
        if len(data) > max_bytes:
            raise UpdateError("The update response exceeded the maximum allowed size.")
        return data

    def _request(self, url: str) -> urllib.request.Request:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise UpdateError("Update URLs must use HTTPS.")
        if parsed.hostname not in self.ALLOWED_INITIAL_HOSTS:
            raise UpdateError("The update URL is not hosted by an approved provider.")
        return urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"McMahon-Dispatch/{self.current_version}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    @staticmethod
    def _validate_redirect_target(url: str) -> None:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise UpdateError("The update service redirected to an unsafe URL.")
        allowed = (
            parsed.hostname == "github.com"
            or parsed.hostname == "api.github.com"
            or parsed.hostname.endswith(".githubusercontent.com")
            or parsed.hostname.endswith(".github.com")
        )
        if not allowed:
            raise UpdateError("The update service redirected to an unapproved host.")

    @staticmethod
    def _normalize_version(value: str) -> str | None:
        cleaned = value.strip().lower()
        if cleaned.startswith("v"):
            cleaned = cleaned[1:]
        return cleaned if re.fullmatch(r"\d+\.\d+\.\d+", cleaned) else None

    @staticmethod
    def _version_tuple(value: str) -> tuple[int, int, int]:
        normalized = UpdateService._normalize_version(value)
        if normalized is None:
            raise UpdateError(f"Invalid application version: {value}")
        return tuple(int(part) for part in normalized.split("."))  # type: ignore[return-value]
