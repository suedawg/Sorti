"""
Taxonomy Management Engine for Sorti.
Discovers and manages study folder hierarchies (Courses, Seminars, Topics)
and handles keyword associations for classification.
"""

from pathlib import Path
import json
import re
from typing import Dict, List, Any, Optional

IGNORED_FOLDERS = {
    "_originals", "_archive", "_unsorted", "_bin",
    ".git", ".venv", "__pycache__", "dist", "build", "tools",
    "config", ".config", ".sorti", "sorti"
}

class TaxonomyManager:
    def __init__(self, root_dir: Optional[Path] = None, config_file: Optional[Path] = None):
        if root_dir is None:
            root_dir = Path.cwd()
        self.root_dir = Path(root_dir).resolve()
        if config_file:
            self.config_file = Path(config_file).resolve()
        else:
            self.config_file = self.root_dir / ".sorti" / "taxonomy.json"
        self.aliases: Dict[str, List[str]] = {}
        self.load_config()

    def load_config(self) -> None:
        """Load keyword aliases from JSON config if present."""
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.aliases = data.get("aliases", {})
            except Exception:
                self.aliases = {}
        else:
            self.aliases = {}

    def save_config(self) -> None:
        """Persist keyword aliases to disk."""
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump({"aliases": self.aliases}, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[TaxonomyManager] Failed to save config: {e}")

    def get_taxonomy_tree(self) -> List[Dict[str, Any]]:
        """
        Scans the root directory and builds a hierarchical tree of Courses and Subfolders.
        Strictly ignores internal and system directories.
        """
        if not self.root_dir.exists():
            return []

        tree = []
        for item in sorted(self.root_dir.iterdir(), key=lambda p: p.name.lower()):
            if not item.is_dir():
                continue
            if item.name.lower() in IGNORED_FOLDERS or item.name.startswith("."):
                continue

            course_node = {
                "name": item.name,
                "path": str(item.relative_to(self.root_dir)),
                "full_path": str(item),
                "aliases": self.aliases.get(item.name, []),
                "subfolders": [],
                "file_count": 0
            }

            # Scan child folders (e.g. Seminars, Readings, Lectures)
            for child in sorted(item.iterdir(), key=lambda p: p.name.lower()):
                if child.is_dir() and not child.name.startswith("."):
                    sub_files = [f for f in child.iterdir() if f.is_file()]
                    sub_node = {
                        "name": child.name,
                        "path": str(child.relative_to(self.root_dir)),
                        "full_path": str(child),
                        "file_count": len(sub_files),
                        "files": [{"name": f.name, "size": f.stat().st_size} for f in sub_files]
                    }
                    course_node["subfolders"].append(sub_node)
                elif child.is_file():
                    course_node["file_count"] += 1

            tree.append(course_node)

        return tree

    def create_folder(self, relative_path: str) -> Dict[str, Any]:
        """
        Safely creates a new course or seminar subfolder within root_dir.
        """
        clean_path = Path(relative_path.strip().replace("\\", "/"))
        # Guard against directory traversal
        target_path = (self.root_dir / clean_path).resolve()
        if not str(target_path).startswith(str(self.root_dir)):
            raise ValueError("Target path must be within the study root directory.")

        target_path.mkdir(parents=True, exist_ok=True)
        return {
            "name": target_path.name,
            "relative_path": str(target_path.relative_to(self.root_dir)),
            "created": True
        }

    def set_aliases(self, course_name: str, aliases: List[str]) -> None:
        """Assign custom keyword aliases to a course folder for smarter matching."""
        clean_aliases = [a.strip().lower() for a in aliases if a.strip()]
        self.aliases[course_name] = clean_aliases
        self.save_config()
