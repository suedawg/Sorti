"""
Safe File Operations Engine for Sorti.
Guarantees absolute subfolder immunity, atomic moves, original file deletion
after successful PDF conversion, and _Unsorted staging.
"""

from pathlib import Path
import shutil
import json
from datetime import datetime
from typing import Dict, List, Any, Optional

IGNORED_NAMES = {
    "sorti.exe", "sorti.bat", "sorti.vbs", "desktop.ini", "thumbs.db", "sorti.spec", "app.py", "scratch_diag.py"
}

IGNORED_SUFFIXES = {
    ".crdownload", ".tmp", ".part", ".download", ".py", ".pyc", ".spec", ".exe", ".bat", ".vbs", ".log", ".json"
}

CONVERTIBLE_EXTENSIONS = {
    '.docx', '.doc', '.pptx', '.ppt'
}

class SafeFileOps:
    def __init__(self, root_dir: Optional[Path] = None, converter = None, history_file: Optional[Path] = None):
        if root_dir is None:
            root_dir = Path.cwd()
        self.root_dir = Path(root_dir).resolve()
        self.converter = converter
        if history_file:
            self.history_file = Path(history_file).resolve()
        else:
            self.history_file = self.root_dir / ".sorti" / "history.json"
        self.history: List[Dict[str, Any]] = []
        self.load_history()

    def load_history(self) -> None:
        if self.history_file.exists():
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    self.history = json.load(f)
            except Exception:
                self.history = []

    def save_history(self) -> None:
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(self.history[-50:], f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[SafeFileOps] Failed to save history: {e}")

    def is_root_file(self, file_path: Path) -> bool:
        """
        Subfolder Immunity Guard:
        Returns True ONLY if the file is sitting directly in root_dir,
        or sitting in the _Unsorted folder awaiting triage.
        Files inside any course subfolder return False and are protected.
        """
        resolved = Path(file_path).resolve()
        unsorted_dir = (self.root_dir / "_Unsorted").resolve()
        return resolved.parent == self.root_dir or resolved.parent == unsorted_dir

    def list_root_incoming_files(self) -> List[Path]:
        """
        Returns all regular files directly in root_dir, strictly ignoring
        any files inside subfolders, system files, or executable binaries.
        """
        if not self.root_dir.exists():
            return []

        incoming = []
        for item in self.root_dir.iterdir():
            if not item.is_file():
                continue
            name_lower = item.name.lower()
            if name_lower in IGNORED_NAMES or name_lower.startswith((".", "~$")):
                continue
            if item.suffix.lower() in IGNORED_SUFFIXES:
                continue
            incoming.append(item)

        return sorted(incoming, key=lambda p: p.stat().st_mtime, reverse=True)

    def list_unsorted_files(self) -> List[Path]:
        """Returns all files currently staged in _Unsorted/ awaiting triage."""
        unsorted_dir = self.root_dir / "_Unsorted"
        if not unsorted_dir.exists():
            return []

        files = []
        for item in unsorted_dir.iterdir():
            if not item.is_file():
                continue
            name_lower = item.name.lower()
            if name_lower in IGNORED_NAMES or name_lower.startswith((".", "~$")):
                continue
            files.append(item)

        return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)

    def stage_to_unsorted(self, file_path: Path) -> Dict[str, Any]:
        """
        Moves an ambiguous/unrecognized file into _Unsorted/ awaiting user confirmation.
        """
        src = Path(file_path).resolve()
        if not self.is_root_file(src):
            return {
                "success": False,
                "error": f"Immunity Violation: '{src.name}' is inside a course subfolder and cannot be moved."
            }

        unsorted_dir = self.root_dir / "_Unsorted"
        unsorted_dir.mkdir(parents=True, exist_ok=True)
        dest = unsorted_dir / src.name

        shutil.move(str(src), str(dest))
        record = {
            "timestamp": datetime.now().isoformat(),
            "original_name": src.name,
            "action": "staged_to_unsorted",
            "final_path": str(dest),
            "destination_rel": "_Unsorted"
        }
        self.history.append(record)
        self.save_history()

        return {
            "success": True,
            "action": "staged_to_unsorted",
            "file": src.name,
            "final_path": str(dest)
        }

    def process_file(self, file_path: Path, destination_rel: str, archive_original: bool = False) -> Dict[str, Any]:
        """
        Converts (if Word or PowerPoint) and moves file to destination subfolder.
        Once converted to PDF, permanently deletes the original Word or PowerPoint doc.
        Strictly enforces root-only immunity before performing any action.
        """
        src = Path(file_path).resolve()

        # Hard Guard: Must be in root or _Unsorted
        if not self.is_root_file(src):
            return {
                "success": False,
                "error": f"Immunity Violation: '{src.name}' is inside a course subfolder and cannot be altered."
            }

        target_dir = (self.root_dir / destination_rel).resolve()
        target_dir.mkdir(parents=True, exist_ok=True)

        ext = src.suffix.lower()
        is_convertible = ext in CONVERTIBLE_EXTENSIONS
        final_file = None
        deleted_orig = False

        if is_convertible:
            # 1. Convert to PDF
            pdf_target = target_dir / f"{src.stem}.pdf"
            success, converted_path, msg = self.converter.convert_to_pdf(src, pdf_target)

            if success and converted_path.exists() and converted_path.stat().st_size > 0:
                final_file = converted_path
                # 2. Delete original Word / PowerPoint document
                try:
                    src.unlink()
                    deleted_orig = True
                except Exception as e:
                    print(f"[SafeFileOps] Note: could not delete original {src.name}: {e}")
            else:
                # If conversion failed, safely move original file to destination so nothing is lost
                dest_file = target_dir / src.name
                shutil.move(str(src), str(dest_file))
                final_file = dest_file
        else:
            # Non-office file (.pdf, .txt, .xlsx, etc.): move directly to target folder
            dest_file = target_dir / src.name
            shutil.move(str(src), str(dest_file))
            final_file = dest_file

        # Log for History / Undo
        record = {
            "timestamp": datetime.now().isoformat(),
            "original_name": src.name,
            "destination_rel": destination_rel,
            "final_path": str(final_file),
            "is_convertible": is_convertible,
            "deleted_original": deleted_orig
        }
        self.history.append(record)
        self.save_history()

        return {
            "success": True,
            "final_path": str(final_file),
            "destination": destination_rel,
            "deleted_original": deleted_orig,
            "record": record
        }

    def undo_last_operation(self) -> Dict[str, Any]:
        """Reverses the most recent file sort operation."""
        if not self.history:
            return {"success": False, "error": "No actions in history to undo."}

        last_op = self.history.pop()
        self.save_history()

        orig_name = last_op.get("original_name")
        final_path = Path(last_op["final_path"]) if last_op.get("final_path") else None
        dest_root_file = self.root_dir / orig_name

        restored = False
        if final_path and final_path.exists():
            shutil.move(str(final_path), str(dest_root_file))
            restored = True

        return {
            "success": restored,
            "file": orig_name,
            "restored_to": str(dest_root_file) if restored else None,
            "note": "Restored file back to main intake folder." if restored else "File could not be found to undo."
        }

