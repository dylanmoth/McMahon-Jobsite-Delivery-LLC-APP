# User Guide

## Starting the application

Use the **McMahon Dispatch** desktop shortcut or Start menu entry. The application stores business data locally and can operate without internet access. Internet access is used only for optional update checks and external links.

## Signing in

Enter your assigned username and password. The remembered-login option stores a protected device token, not the password. Use **Forget Remembered Login** in My Profile when a device changes ownership.

## Navigation

Use the permanent menu button in the upper-left or press `Ctrl+B`. Available pages depend on the signed-in user's role and permissions.

## Backups

Before major upgrades, copy the application-data directory while McMahon Dispatch is closed:

```text
%LOCALAPPDATA%\McMahon Jobsite Delivery LLC\McMahon Dispatch
```

The `data`, `documents`, and `backups` folders contain the most important business records.

## Updates

When an update is available, McMahon Dispatch displays the installed and available versions. Choose **Yes** to download. After verification, approve installation. The application closes while the installer updates program files.

## Uninstalling

Windows Settings → Apps → Installed apps → McMahon Dispatch → Uninstall.

Uninstalling removes program files and shortcuts but intentionally preserves the database, documents, settings, logs, and backups.
