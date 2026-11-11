# About / Release Instructions

Last updated: 2026-09-03

## About button requirements

- Add an About button using the same application version as the current release.
- The About popup must be lightweight and viewer-style, with no changes to unrelated features.
- The popup must display:
  - Application purpose
  - Version
  - Open source software used
  - Build/creation date in year-month-day format
  - Creator: Hwang.seonmun

## Release packaging requirements

- Create the installer/package for the same version after adding or updating the About popup.
- Do not modify unrelated behavior or features while preparing this release.
- Prefer PyInstaller onedir packaging with UPX disabled for Windows security software compatibility.
- Install the complete `dist/NC_Tool_List` folder, including `_internal`, rather than a single self-extracting executable.
- Prefer TSERP-style installation under `C:\NC_Tool_List` when matching existing accepted plant PC deployment behavior; keep HKLM file association writes disabled unless explicitly needed.

## Version history maintenance

- Every time a new version is created, append a record here.
- Each record must include:
  - Version
  - Release/build date
  - Summary of the version change
  - Open source software used or changed in that version
  - Installer/package creation status

## Version history

### 2026-09-03

- Version: 1.4.2
- Release/build date: 2026-09-03
- Summary: Added a lightweight About popup viewer with application purpose, version, build/creation date, creator, and open source usage.
- Creator displayed: Hwang.seonmun
- Scope: About UI and installer/package only. No unrelated feature changes.
- Open source used: Python, PyQt5, pyqtgraph, NumPy, PyOpenGL, ReportLab, PyInstaller, Inno Setup.
- Installer/package: Recreated `installer/NC_Tool_List_Setup_v1.4.2.exe` from PyInstaller onedir output `dist/NC_Tool_List/NC_Tool_List.exe`.
- Packaging note: Changed from single-file PyInstaller output to onedir output with UPX disabled, matching the TSERP-style deployment structure more closely.
- Installer hardening: Switched installer target to TSERP-style `C:\NC_Tool_List` with no HKLM file association registry writes after security software still removed files during installation.
- C:\\NC_Tool_List install verification: Silent install completed, `C:\NC_Tool_List\NC_Tool_List.exe` and `C:\NC_Tool_List\_internal` were created, and installed app launch passed.
- Verification: Unit tests passed, built app launch passed, installer install/run/uninstall/reinstall passed.
- Installer SHA-256: 4969694A2761CE838AE33D131127FED9B41DAF792ACF574E42C809D62881B18F
- Portable ZIP: Created `installer/NC_Tool_List_Portable_v1.4.2.zip` for no-installer deployment.
- Portable ZIP SHA-256: F13AC4E04F1D4D912B53B9B92D667893DF829924B9CEC1ED8B9AC6F478A9779B
- App SHA-256: 0769E952A85CF2321133FD78F1A0BA5154749FEDA1F016816684A205463AB8D4
- Runtime hardening: Added startup logging, software OpenGL preference, OpenGL viewer fallback, and reduced bundled OpenGL submodules after installed app was reported to exit immediately on secured PCs.
- OpenGL fallback log path: `%LOCALAPPDATA%\NC_Tool_List\startup.log`.
- Signature status: Installer and app executable are unsigned; code signing is still required for maximum SmartScreen/endpoint trust.
