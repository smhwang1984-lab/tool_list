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

### 2026-09-04 (latest)

- Version: 1.4.5
- Release/build date: 2026-09-04
- Summary: Fixed G02/G03 circular interpolation defects across 3/4/5-axis, and improved the process filter list's readability.
- Creator displayed: Hwang.seonmun
- Open source used: Python, PyQt5, pyqtgraph, NumPy, PyOpenGL, ReportLab, PyInstaller, Inno Setup (unchanged).
- Context: G2/G3 arc code already existed in `nc_viewer_widget.py` (`_arc_points`), but had several defects reported by the user as "arcs not rendering correctly" across 3/4/5-axis programs. User confirmed 3-axis I/J/R arcs were already fine, which matched the root-cause analysis (the 4/5-axis rotation matrix is only non-identity for 4/5-axis machines, so the coordinate-frame bug below was invisible on 3-axis).
- Arc fixes in `nc_viewer_widget.py`:
  - **4/5-axis coordinate-frame bug (the actual reported defect):** the arc's start point was captured pre-rotation while its end point was already rotated by the active 4/5-axis matrix, so the two endpoints lived in different coordinate spaces and the interpolated arc was garbled. Fixed by building the whole arc in the pre-rotation ("local") frame — matching `start_pt` — and rotating every generated arc point as one batch with `active_matrix`, the same pattern the existing canned-cycle code already used. Verified empirically: the pre-fix code produced a ~14-unit discontinuity jump between a rapid move's endpoint and the following arc's first point once a G68.2/G53.1 tilt was active; the fix reduces this to a normal small interpolation step. Lathe arcs were left untouched (no rotation matrix involved there).
  - Full-circle arcs (`G02 I.. J..` with no X/Y/Z word) previously never entered the motion-parsing block at all and were silently dropped; now detected via the presence of I/J/K parameters (guarded against colliding with the unrelated G68.2 I/J/K tilt-vector usage).
  - G17/G18/G19 plane selection is now tracked and honored — arcs on G18 (ZX, using I/K) and G19 (YZ, using J/K) planes are computed in their own plane instead of always assuming XY.
  - Segment count switched from a fixed angle-based formula (which turned very short arcs, e.g. small corner fillets, into a single straight line) to chord-error-based adaptive resolution with a minimum segment floor, so short arcs stay curved and long arcs don't over-generate points.
  - The arc's final point is snapped exactly to the commanded end coordinate rather than the parametric circle formula, so small I/J rounding no longer leaves a visible gap to the next segment.
- Filter list readability (`nc_viewer_widget.py` + `NC_Tool_List.py`): per-tool color moved from the list item's text color (low contrast against the default light background) to a small color-swatch icon (`color_chip_icon`) next to the label; the list now uses a larger bold font and a high-contrast selected-row style (blue background, white text) matching the app's existing button color scheme.
- Verification: 28 unit tests passed (22 existing + 6 new arc regression tests covering G02/G03 direction, short-arc minimum segments, full circles, G18/G19 planes, helical Z interpolation, and the 4/5-axis coordinate-frame fix specifically). Offscreen-rendered screenshot confirmed arcs draw as curves (including a complete circle from a single I/J-only line) and the filter list shows color chips with readable bold selected rows. Rebuilt frozen exe launched and logged a healthy GL context.
- Installer/package: Created `installer/NC_Tool_List_Setup_v1.4.5.exe` and `installer/NC_Tool_List_Portable_v1.4.5.zip`.
- Installer SHA-256: 31C8DAD8C5EE5A51CA20F032F4BF46754EA7C791AEADCE50242D5DDFCEF88BF5
- Portable ZIP SHA-256: 66EBE6DD72BD287D3153EC75EB2DD25292E630EAD756EBB41982887C36AA1857
- App SHA-256: B93CEE89C8E73A5DEC401A9CC6206F3AD72E77189E1970AD8481406F1F501DA9
- Signature status: still unsigned.
- Out of scope (left untouched): lathe (2-axis) coordinate mapping; G90/G91 incremental-mode support for ordinary moves.

### 2026-09-04 (v1.4.4)

- Version: 1.4.4
- Release/build date: 2026-09-04
- Summary: Fixed the v1.4.3 regression that made the 3D viewer render a fully black screen with no toolpath lines on a normally working PC.
- Creator displayed: Hwang.seonmun
- Open source used: Python, PyQt5, pyqtgraph, NumPy, PyOpenGL, ReportLab, PyInstaller, Inno Setup (unchanged).
- Root cause (measured, not guessed): v1.4.3 added `os.environ.setdefault('QT_OPENGL', 'software')` and `QApplication.setAttribute(Qt.AA_UseSoftwareOpenGL, True)` as secured-PC hardening. That makes Qt build its context on `opengl32sw.dll` (Mesa llvmpipe) while pyqtgraph's PyOpenGL keeps dispatching into the system `opengl32.dll`. PyOpenGL therefore has no current context and every GL call fails — `GLError 1282 (GL_INVALID_OPERATION)` starting at `glClearColor`, so even the configured background never paints. Qt's `paintGL` swallows the exception, leaving a black viewport instead of a crash. `nc_viewer_widget.py` was unchanged since v1.4.2, confirming the regression came from these two lines.
- A/B measurement on the affected PC (offscreen `grabFramebuffer` pixel sampling of the real viewer widget):
  - Fixed build: 23 distinct colors, background `#21252B` 89.1%, pure black 0.0% → lines rendered.
  - v1.4.3 setting: 1 distinct color, background 0.0%, pure black 100.0% → blank black screen.
- Fix:
  - Removed both software-OpenGL lines from `NC_Tool_List.py`. This forcing never delivered its intended benefit either — the secured PC still crashed with it in place — so there is no trade-off in removing it.
  - Restored `collect_submodules('OpenGL')` in `NC_Tool_List.spec` and dropped the `OpenGL.raw.GLX` / `OpenGL.raw.GLES1-3` / `OpenGL.raw.GLUT` excludes added in v1.4.3. PyOpenGL resolves submodules dynamically, so these only break the frozen build — source runs would not reveal it. `OpenGL.Tk` / `OpenGL.GLUT` excludes and the `OpenGL\DLLS` folder exclusion are kept (genuinely unused).
  - Inverted the unit test that previously asserted `QT_OPENGL == 'software'` — it was locking the bug in. It now guards against software-OpenGL forcing ever returning.
- New diagnostic: the app logs `OpenGL vendor=... renderer=... version=...` to `startup.log` the first time Viewer mode opens. The packaged app has no console, which is why this class of GL failure was invisible until a user reported it; the log line now makes it checkable on any PC.
- Kept from v1.4.3: onedir + `upx=False`, exe version resource (`version_info.txt`), installer `VersionInfo*`/icon settings, startup logging, viewer fallback screen.
- Verification: 22 unit tests passed; offscreen render check confirmed lines draw; rebuilt frozen exe launched and logged a healthy hardware context (`vendor=Intel renderer=Intel(R) Iris(R) Plus Graphics version=4.6.0`), which also validates the `.spec` restoration in the packaged build.
- Installer/package: Created `installer/NC_Tool_List_Setup_v1.4.4.exe` and `installer/NC_Tool_List_Portable_v1.4.4.zip`.
- Installer SHA-256: 5BB4B17D426C0293AC563568850F1E5F713DA40FD7DDC5557019B8DF4F595608
- Portable ZIP SHA-256: 94ED0500413368DF1E67957A590AC4F826FE5EE42DECB6E4A685B6593EB9D07F
- App SHA-256: EE12403F94A075AB334946EB9B3389D1033ED12BE61A49AC0AEBC2F9B53104CB
- Signature status: still unsigned.

### 2026-09-04

- Version: 1.4.3
- Release/build date: 2026-09-04
- Summary: Version bump only; hardened installer/build configuration against Windows security software false positives.
- Creator displayed: Hwang.seonmun
- Scope: About popup version/date fields, `.iss`, `.spec` only. No unrelated feature changes.
- Open source used: Python, PyQt5, pyqtgraph, NumPy, PyOpenGL, ReportLab, PyInstaller, Inno Setup (unchanged).
- Packaging hardening:
  - Excluded leftover `OpenGL\DLLS` license/README text files from `a.datas` (previously only `a.binaries` was filtered), completing the cleanup noted as outstanding after v1.4.2.
  - Embedded a Windows version-info resource (`version_info.txt`: CompanyName, FileDescription, FileVersion, ProductName, ProductVersion, LegalCopyright) into `NC_Tool_List.exe` via PyInstaller's `version=` option, since an unsigned executable with no version metadata is a common heuristic AV/SmartScreen flag.
  - Installer (`NC_Tool_List.iss`): added `SetupIconFile`, `UninstallDisplayIcon`, and explicit `VersionInfoVersion`/`VersionInfoCompany`/`VersionInfoDescription`/`VersionInfoProductName`/`VersionInfoProductVersion` so the setup EXE also carries legitimate-looking metadata.
- Verification: All 22 unit tests passed. Rebuilt with PyInstaller onedir; confirmed `dist/NC_Tool_List/_internal/OpenGL` no longer exists (freeglut/gle DLLs and their license/README text are fully gone). Launched the built exe; `startup.log` showed a clean start (`Starting NC 공구 리스트 생성기 v1.4.3`, frozen=True) with no traceback, and the process was closed normally.
- Installer/package: Recreated `installer/NC_Tool_List_Setup_v1.4.3.exe` from PyInstaller onedir output `dist/NC_Tool_List/NC_Tool_List.exe`. Also recreated `installer/NC_Tool_List_Portable_v1.4.3.zip`.
- Installer SHA-256: 587ED5C5A195A917EB9C3080738BBFE0D6FE0A038F2334686DB8E3B48DFF5FA5
- Portable ZIP SHA-256: DF6BDAF97CFD26B349C0CB245A76710C25CE8FFCC219AD04755A937B8526F4F0
- App SHA-256: A40B176D5B3B98C2A1E829163F960DA35AB89EA9A6F812EAD8477E532304965F
- Not yet done for 1.4.3: an actual admin-elevated install/uninstall pass to `C:\NC_Tool_List` (skipped here to avoid making a system-level change to this machine without confirmation).
- Signature status: still unsigned; code signing remains the real fix for SmartScreen/"Unknown Publisher" — see "보안 PC 대응 판단" 근본 해결책.

### Field test on one secured plant PC (2026-09-04)

- Install succeeded via `NC_Tool_List_Setup_v1.4.3.exe`; the window flashed and closed immediately on launch, but only on this one PC — other PCs tested fine.
- `startup.log` on the affected PC showed only the `Starting NC 공구 리스트 생성기 v1.4.3` line with no exception/traceback recorded, meaning the process died before or during Qt/window init, not from a caught Python exception.
- Windows Event Viewer (`Application` log, exported as evtx) showed:
  - `Application Error` (Id 1000): Faulting application `NC_Tool_List.exe` 1.4.3.0, faulting module `ntdll.dll`, exception code `0xC0000409` (STATUS_STACK_BUFFER_OVERRUN / __fastfail).
  - `Windows Error Reporting` (Id 1001): Fault bucket type 5, Event Name `BEX64`.
- AhnLab V3 was installed on the affected PC but showed no threat/detection record. Tested with the app path excluded from AhnLab, and again with AhnLab real-time protection fully disabled — the exact same crash still occurred both times.
- Conclusion: ruled out AhnLab as the cause. The crash is treated as specific to that one PC's environment (background hooking agent other than AhnLab, or a GPU/graphics driver incompatibility with the bundled software-OpenGL fallback) rather than a defect introduced in v1.4.3 — the app starts cleanly (per `startup.log`) and only this one PC, among those tested, reproduces it.
- Follow-up if this recurs: identify any other security/monitoring agent (keyboard-security, document DRM, asset-management) on the affected PC, and/or test the app in Windows Safe Mode there to isolate a background hook vs. a graphics-driver cause.

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
