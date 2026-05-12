# vanilla-sidecar.spec — PyInstaller build spec for the VanillaDB Python sidecar.
#
# Usage (run from the sidecar/ directory):
#   pyinstaller vanilla-sidecar.spec --noconfirm --clean
#
# Output: dist/vanilla-sidecar[.exe]
# CI copies it to: src-tauri/binaries/vanilla-sidecar-<target-triple>[.exe]

block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=[
        # uvicorn loads these dynamically — must be listed explicitly
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.loops.asyncio",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "uvicorn.lifespan.off",
        # anyio / starlette internals
        "anyio",
        "anyio._backends",
        "anyio._backends._asyncio",
        # SQLAlchemy SQLite dialect (loaded dynamically by URL string)
        "sqlalchemy.dialects.sqlite",
        # sqlite-vec loads as a native extension — no hidden import needed,
        # but the load_extension call must be allowed at runtime
        # ddgs loaded via importlib.import_module() in browser_research.py
        "ddgs",
        "ddgs.utils",
        # tomli/tomli_w loaded by config_loader for Python < 3.11 compat
        "tomli",
        "tomli_w",
        # python-multipart required by FastAPI File/UploadFile endpoints (voice/transcribe)
        "multipart",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Large optional deps not needed in the frozen binary —
        # the sidecar code already guards these with try/except ImportError
        "matplotlib",
        "PIL",
        "cv2",
        "torch",
        "transformers",
        # rich causes PyInstaller bytecode scan crash on Python 3.10.0;
        # uvicorn uses it only for pretty console output — not needed in binary
        "rich",
        # scipy/numpy/pandas are transitive deps pulled from the environment;
        # PyInstaller crashes scanning scipy's compiled .pyc on Python 3.10.0
        "scipy",
        "numpy",
        "pandas",
        # pytest and test infra — never needed at runtime
        "pytest",
        "py",
        # av (audio/video) not used by sidecar
        "av",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="vanilla-sidecar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # Keep console=True so the Tauri shell plugin can read stdout/stderr
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
