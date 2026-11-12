# PyInstaller spec: `pyinstaller packaging/flowtype.spec` from the flowtype/ folder.
# Windows -> dist/Flowtype/Flowtype.exe (one folder, no console window); macOS -> dist/Flowtype.app.
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hidden = collect_submodules("flowtype") + ["pynput.keyboard._win32", "pynput.keyboard._darwin", "pynput.mouse._win32", "pynput.mouse._darwin",
                                           "keyring.backends.Windows", "keyring.backends.macOS"]
datas = collect_data_files("faster_whisper")  # the Silero VAD ONNX model ships in faster_whisper/assets
if sys.platform == "win32":
    hidden += ["comtypes.gen", "comtypes.client"]

a = Analysis(["launch.py"], pathex=[".."], hiddenimports=hidden, datas=datas,
             excludes=["tkinter", "matplotlib", "IPython", "pytest"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Flowtype", console=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="Flowtype", upx=False)
if sys.platform == "darwin":
    app = BUNDLE(coll, name="Flowtype.app", bundle_identifier="com.flowtype.dictation", info_plist={
        "LSUIElement": True,  # no Dock icon: it lives in the overlay
        "NSMicrophoneUsageDescription": "Flowtype records while you hold the dictation key, to turn your speech into text.",
        "NSAppleEventsUsageDescription": "Flowtype pastes your dictation into the app you're typing in.",
    })
