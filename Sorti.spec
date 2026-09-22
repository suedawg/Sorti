# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

SPEC_DIR = Path(SPECPATH).resolve()

onnx_datas = collect_data_files('onnxruntime')
onnx_binaries = collect_dynamic_libs('onnxruntime')
fastembed_submodules = collect_submodules('fastembed')

webview_datas = collect_data_files('webview')
webview_binaries = collect_dynamic_libs('webview')
webview_submodules = [sm for sm in collect_submodules('webview') if 'android' not in sm and 'gtk' not in sm and 'qt' not in sm and 'cocoa' not in sm]

pythonnet_datas = collect_data_files('pythonnet')
pythonnet_binaries = collect_dynamic_libs('pythonnet')
pythonnet_submodules = collect_submodules('pythonnet')

clr_loader_datas = collect_data_files('clr_loader')
clr_loader_binaries = collect_dynamic_libs('clr_loader')
clr_loader_submodules = collect_submodules('clr_loader')

datas = [
    (str(SPEC_DIR / 'ui'), 'ui'),
    (str(SPEC_DIR / 'model_cache'), 'model_cache'),
    (str(SPEC_DIR / 'Sorti.ico'), '.'),
] + onnx_datas + webview_datas + pythonnet_datas + clr_loader_datas

binaries = onnx_binaries + webview_binaries + pythonnet_binaries + clr_loader_binaries

hiddenimports = [
    'win32com.client',
    'pythoncom',
    'fastembed',
    'onnxruntime',
    'tokenizers',
    'webview',
    'webview.platforms.winforms',
    'webview.platforms.edgechromium',
    'clr',
    'pythonnet',
    'clr_loader',
    'pypdfium2',
    'winocr',
    'pypdf',
    'PIL',
] + fastembed_submodules + webview_submodules + pythonnet_submodules + clr_loader_submodules

a = Analysis(
    [str(SPEC_DIR / 'app.py')],
    pathex=[str(SPEC_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'scipy', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Sorti',
    icon=str(SPEC_DIR / 'Sorti.ico'),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
