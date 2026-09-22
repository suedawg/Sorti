# Sorti — AI-Powered Academic Document Sorter & Course Explorer

<p align="center">
  <img src="ui/logo.png" alt="Sorti Logo" width="128" height="128">
</p>

<p align="center">
  <strong>Fast, intelligent, 100% offline document sorting for university students.</strong>
</p>

---

## Overview

Sorti is a standalone desktop application that automatically organizes messy downloads (Moodle readings, lecture slides, seminar worksheets, case law PDFs) into your local course folder hierarchy.

- **Zero-Cloud, 100% Private**: Runs entirely on your laptop CPU using local ONNX embeddings (`BAAI/bge-small-en-v1.5`). No API keys, no subscriptions, and no internet required.
- **Smart Two-Zone Sampling**: Reads both thesis summaries (pages 1-3) and deep structural topic headings (pages 4-20) for human-level categorization accuracy.
- **Native OCR Fallback**: Automatically renders and scans Page 1 using Windows native OCR on image-only/scanned PDFs (photocopied law reports, archival texts) with zero extra binary weight.
- **In-App Release Notifications**: Subtle in-app header badge alerts you when updates or bug fixes are published on GitHub.
- **Active Learning**: Learns from your custom manual overrides and preserves folder taxonomy automatically.
- **Native Desktop App**: Runs in a standalone window with Windows 11 Snap Layouts, high-DPI scaling, and drag-and-drop file ingestion.

---

## Download (For Students)

1. Go to [Releases](../../releases/latest).
2. Download `Sorti.exe`.
3. Move `Sorti.exe` into your university semester or degree folder (e.g., `Documents\Year 4 Sem 1`).
4. Double-click `Sorti.exe` to run.
   - *Note on Windows SmartScreen*: Since this is an open-source student build without a commercial Microsoft certificate, Windows will display a prompt: click **More info** -> **Run anyway**.
5. Drag your downloaded readings or PDFs into the window, or click **Scan & Auto-Sort**.

---

## Building from Source

If you want to contribute or build Sorti yourself:

### Prerequisites
- Python 3.11+
- Windows 10/11 (with Microsoft Edge WebView2 runtime installed by default)

### Setup
```bash
# Clone the repository
git clone https://github.com/suedawg/Sorti.git
cd Sorti

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate

# Install dependencies
pip install pywebview fastembed onnxruntime pypdf pillow pyinstaller pythonnet pypdfium2 winocr
```

### Run Locally (Development)
```bash
python app.py
```

### Build Lightweight Installer (Inno Setup — ~120 MB)
```bash
# 1. Compile directory build
pyinstaller Sorti.onedir.spec --noconfirm

# 2. Compile Inno Setup installer
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" Sorti.iss
```
The installer will be generated at `dist-installer/Sorti-Setup-v1.1.0.exe`.

### Build Standalone Executable (One-File Fallback)
```bash
pyinstaller Sorti.spec --noconfirm
```
The single-file binary will be generated at `dist/Sorti.exe`.

---

## License
MIT License
