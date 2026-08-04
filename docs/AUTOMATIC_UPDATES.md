# Automatic Updates

McMahon Dispatch checks the repository's latest stable GitHub Release at startup no more than once every 24 hours. Users can also select **Check for Updates** from the top-right application bar.

## Security controls

- HTTPS is mandatory.
- Only GitHub and GitHub-controlled download hosts are accepted.
- Draft and prerelease versions are ignored by the stable channel.
- The installer file name must match `McMahonDispatch-Setup-X.Y.Z.exe`.
- A matching `.sha256` file or `SHA256SUMS.txt` must be present.
- The installer is deleted if its SHA-256 hash does not match.
- Installation requires a user confirmation.
- The installer should also carry a valid Authenticode signature.

SHA-256 protects download integrity. Authenticode verifies publisher identity. Production releases should use both.

## Disable automatic checks

Set the user setting `updates.auto_check` to false, or set:

```powershell
$env:MCMAHON_DISABLE_UPDATES = "true"
```

Manual checks remain unavailable while the environment variable is active.

## Release naming contract

Upload these assets to the GitHub Release:

```text
McMahonDispatch-Setup-1.3.0.exe
McMahonDispatch-Setup-1.3.0.exe.sha256
```

The tag must be `v1.3.0` or `1.3.0`.

## Failure behavior

Network, API, parsing, and verification failures do not prevent the application from launching. Automatic checks fail quietly and are logged. Manual checks display a safe error message.
