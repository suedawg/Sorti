"""
Sorti Desktop Application Backend.
Zero-dependency, multi-threaded local HTTP server providing REST APIs
and serving the modern Web Dashboard.
"""

from pathlib import Path
import sys
import os
import json
import urllib.parse
import urllib.request
import webbrowser
import threading
import socket
import time
from typing import Any, Dict, List, Tuple, Optional
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

# Safe redirect when compiled without console (console=False)
def setup_logging():
    if getattr(sys, 'frozen', False):
        try:
            base = Path(sys.executable).parent.resolve()
            meta = base / ".sorti"
            meta.mkdir(parents=True, exist_ok=True)
            log_f = open(meta / "sorti_runtime.log", "a", encoding="utf-8", buffering=1)
            sys.stdout = log_f
            sys.stderr = log_f
        except Exception:
            pass
    if sys.stdout is None:
        try:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
        except Exception:
            pass
    if sys.stderr is None:
        try:
            sys.stderr = open(os.devnull, "w", encoding="utf-8")
        except Exception:
            pass

setup_logging()

# Import Sorti Engine
sys.path.insert(0, str(Path(__file__).parent))
from engine.taxonomy import TaxonomyManager
from engine.classifier import DocumentClassifier
from engine.converter import OfficePdfConverter
from engine.file_ops import SafeFileOps

PORT = 5050

def get_base_dir() -> Path:
    """Returns directory where app or executable is located."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent.resolve()
    return Path(__file__).parent.resolve()

def get_ui_dir() -> Path:
    """Returns directory where UI assets (html, css, js) are stored."""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / "ui"
    return Path(__file__).parent.resolve() / "ui"

def get_study_root(base_dir: Path) -> Path:
    """
    Returns the study root folder.
    Defaults to base_dir itself, or reads from .sorti/settings.json if customized.
    """
    settings_file = base_dir / ".sorti" / "settings.json"
    if settings_file.exists():
        try:
            with open(settings_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                custom_root = data.get("study_root")
                if custom_root and Path(custom_root).exists():
                    return Path(custom_root).resolve()
        except Exception:
            pass
    return Path(base_dir).resolve()

def get_sorti_meta_dir(base_dir: Path) -> Path:
    """
    Returns the hidden local metadata directory (.sorti) alongside Sorti.exe.
    Keeps Sorti 100% self-contained and portable with zero AppData footprint.
    Applies the Windows FILE_ATTRIBUTE_HIDDEN (0x02) flag so File Explorer hides it.
    """
    meta_dir = base_dir / ".sorti"
    try:
        meta_dir.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(str(meta_dir), 0x02)
    except Exception:
        pass
    return meta_dir

def cleanup_legacy_config(base_dir: Path, meta_dir: Path):
    """
    Migrates any files from legacy visible 'config/' folder to '.sorti/' and removes 'config/'.
    Ensures the user's study root remains completely spotless.
    """
    legacy_config = base_dir / "config"
    if legacy_config.exists() and legacy_config.is_dir():
        try:
            import shutil
            for item in legacy_config.iterdir():
                target = meta_dir / item.name
                if not target.exists():
                    shutil.move(str(item), str(target))
            shutil.rmtree(legacy_config, ignore_errors=True)
            print("[Sorti] Cleaned up legacy config folder from study root.")
        except Exception as e:
            print(f"[Sorti] Note during legacy config cleanup: {e}")

# Initialize core path instances
BASE_DIR = get_base_dir()
UI_DIR = get_ui_dir()
STUDY_ROOT = get_study_root(BASE_DIR)
META_DIR = get_sorti_meta_dir(BASE_DIR)

ENGINE_READY = threading.Event()
TAXONOMY = None
CLASSIFIER = None
CONVERTER = None
FILE_OPS = None

def init_engine():
    """Initializes heavy machine learning classifier and taxonomy in background."""
    global TAXONOMY, CLASSIFIER, CONVERTER, FILE_OPS
    if ENGINE_READY.is_set():
        return
    try:
        cleanup_legacy_config(BASE_DIR, META_DIR)
        TAXONOMY = TaxonomyManager(STUDY_ROOT, META_DIR / "taxonomy.json")
        CLASSIFIER = DocumentClassifier(TAXONOMY, min_confidence=0.65)
        CONVERTER = OfficePdfConverter()
        FILE_OPS = SafeFileOps(STUDY_ROOT, CONVERTER, META_DIR / "history.json")
        ENGINE_READY.set()
        print("[Sorti Boot] Core engine initialized successfully.")
        threading.Thread(target=async_startup_sweep, daemon=True).start()
    except Exception as e:
        print(f"[Sorti Boot] Engine initialization error: {e}")

def ensure_engine():
    """Ensures backend engine is initialized before operations that require it."""
    if not ENGINE_READY.is_set():
        init_engine()

def sweep_intake(overrides: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """
    Executes a clean, non-intrusive sweep of the main intake folder:
    - User-overridden files (f.name in overrides) are sorted directly to the user-selected destination
      and remembered by the active learning system.
    - Confident files (is_auto_sort=True) are converted to PDF, sorted, and originals deleted.
    - Ambiguous files (is_auto_sort=False) are safely staged into _Unsorted/ awaiting user confirmation.
    """
    ensure_engine()
    incoming = FILE_OPS.list_root_incoming_files()
    sorted_records = []
    staged_unsorted = []
    overrides = overrides or {}

    for f in incoming:
        try:
            if f.name in overrides:
                dest = overrides[f.name]
                if dest and dest != "Requires Triage":
                    CLASSIFIER.learn_user_override(f.name, dest)
                    res = FILE_OPS.process_file(f, dest)
                    sorted_records.append({"file": f.name, "destination": dest, "result": res, "is_override": True})
                    continue

            analysis = CLASSIFIER.classify_file(f)
            if analysis["is_auto_sort"] and analysis["best_match"]:
                dest = analysis["best_match"]["destination"]
                res = FILE_OPS.process_file(f, dest)
                sorted_records.append({"file": f.name, "destination": dest, "result": res})
            else:
                stage_res = FILE_OPS.stage_to_unsorted(f)
                staged_unsorted.append({"file": f.name, "result": stage_res})
        except Exception as e:
            print(f"[Sorti Sweep] Error processing {f.name}: {e}")

    return {
        "sorted_count": len(sorted_records),
        "unsorted_count": len(staged_unsorted),
        "sorted": sorted_records,
        "unsorted": staged_unsorted
    }

class SortiRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        # Quiet standard console logging
        pass

    def send_json_response(self, data: Any, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def send_file_response(self, file_path: Path, content_type: str):
        if not file_path.exists():
            body = b"File Not Found"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        with open(file_path, "rb") as f:
            content = f.read()

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # UI Static Assets
        ui_dir = UI_DIR
        clean_path = path.lstrip("/")
        if not clean_path or clean_path == "index.html":
            self.send_file_response(ui_dir / "index.html", "text/html; charset=utf-8")
            return

        target_file = ui_dir / clean_path
        if target_file.exists() and target_file.is_file():
            mime_types = {
                ".html": "text/html; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".ico": "image/x-icon",
                ".svg": "image/svg+xml",
                ".json": "application/json"
            }
            content_type = mime_types.get(target_file.suffix.lower(), "application/octet-stream")
            self.send_file_response(target_file, content_type)
            return

        # API Endpoints
        if path == "/api/status":
            if not ENGINE_READY.is_set():
                self.send_json_response({
                    "ready": False,
                    "message": "Initializing Sorti Engine...",
                    "study_root": str(STUDY_ROOT),
                    "incoming_count": 0,
                    "unsorted_count": 0,
                    "auto_count": 0,
                    "triage_count": 0,
                    "incoming_files": [],
                    "unsorted_files": [],
                    "history": []
                })
                return

            incoming = FILE_OPS.list_root_incoming_files()
            unsorted = FILE_OPS.list_unsorted_files()

            incoming_analyzed = [CLASSIFIER.classify_file(f) for f in incoming]
            unsorted_analyzed = [CLASSIFIER.classify_file(f) for f in unsorted]

            auto_count = sum(1 for r in incoming_analyzed if r["is_auto_sort"])
            triage_count = len(unsorted) + sum(1 for r in incoming_analyzed if not r["is_auto_sort"])

            self.send_json_response({
                "ready": True,
                "study_root": str(STUDY_ROOT),
                "incoming_count": len(incoming),
                "unsorted_count": len(unsorted),
                "auto_count": auto_count,
                "triage_count": triage_count,
                "incoming_files": incoming_analyzed,
                "unsorted_files": unsorted_analyzed,
                "history": FILE_OPS.history[-15:]
            })
            return

        elif path == "/api/taxonomy":
            if not ENGINE_READY.is_set():
                self.send_json_response({
                    "ready": False,
                    "tree": [],
                    "study_root": str(STUDY_ROOT)
                })
                return
            tree = TAXONOMY.get_taxonomy_tree()
            self.send_json_response({
                "ready": True,
                "tree": tree,
                "study_root": str(STUDY_ROOT)
            })
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            payload = json.loads(body)
        except Exception:
            payload = {}

        if not ENGINE_READY.is_set() and path != "/api/shutdown":
            self.send_json_response({"error": "Engine is still warming up. Please try again in a moment."}, status=503)
            return

        if path == "/api/folders/create":
            folder_path = payload.get("path", "").strip()
            if not folder_path:
                self.send_json_response({"error": "Folder path is required"}, status=400)
                return
            try:
                res = TAXONOMY.create_folder(folder_path)
                self.send_json_response(res)
            except Exception as e:
                self.send_json_response({"error": str(e)}, status=400)
            return

        elif path == "/api/aliases/save":
            course = payload.get("course")
            aliases = payload.get("aliases", [])
            if not course:
                self.send_json_response({"error": "Course name required"}, status=400)
                return
            TAXONOMY.set_aliases(course, aliases)
            self.send_json_response({"success": True, "aliases": TAXONOMY.aliases.get(course, [])})
            return

        elif path == "/api/triage/resolve":
            filename = payload.get("filename")
            destination = payload.get("destination")

            if not filename or not destination:
                self.send_json_response({"error": "Filename and destination required"}, status=400)
                return

            # Check in root first, then in _Unsorted
            src_file = STUDY_ROOT / filename
            if not src_file.exists():
                src_file = STUDY_ROOT / "_Unsorted" / filename

            if not src_file.exists():
                self.send_json_response({"error": f"File '{filename}' not found in study root or _Unsorted."}, status=404)
                return

            # Learn from user manual decision
            CLASSIFIER.learn_user_override(filename, destination)

            res = FILE_OPS.process_file(src_file, destination)
            self.send_json_response(res)
            return

        elif path == "/api/intake/sweep" or path == "/api/sort/all_auto":
            overrides = payload.get("overrides", {})
            res = sweep_intake(overrides=overrides)
            self.send_json_response(res)
            return

        elif path == "/api/undo":
            res = FILE_OPS.undo_last_operation()
            self.send_json_response(res)
            return

        elif path == "/api/shutdown":
            self.send_json_response({"message": "Shutting down Sorti."})
            def _do_shutdown():
                time.sleep(0.15)
                global ACTIVE_WINDOW
                if ACTIVE_WINDOW:
                    try:
                        ACTIVE_WINDOW.destroy()
                    except Exception:
                        pass
                cleanup_active_server(META_DIR)
                os._exit(0)
            threading.Thread(target=_do_shutdown, daemon=True).start()
            return

        self.send_response(404)
        self.end_headers()

MUTEX_HANDLE = None
ACTIVE_WINDOW = None

def acquire_single_instance_lock() -> Tuple[bool, Any]:
    """
    Acquires Windows named mutex 'Local\\Sorti_SingleInstance_Mutex'.
    Returns (is_primary, handle).
    """
    if sys.platform != "win32":
        return True, None
    try:
        import ctypes
        ERROR_ALREADY_EXISTS = 183
        handle = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\Sorti_SingleInstance_Mutex")
        if ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            return False, handle
        return True, handle
    except Exception as e:
        print(f"[Sorti Mutex] Notice: {e}")
        return True, None

def focus_existing_window() -> bool:
    """Brings the running Sorti native desktop window to the foreground."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        found_hwnd = None

        def enum_cb(h, _):
            nonlocal found_hwnd
            if user32.IsWindowVisible(h):
                length = user32.GetWindowTextLengthW(h)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(h, buff, length + 1)
                    if "Sorti" in buff.value:
                        found_hwnd = h
                        return False
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        user32.EnumWindows(WNDENUMPROC(enum_cb), 0)

        if found_hwnd:
            SW_RESTORE = 9
            user32.ShowWindow(found_hwnd, SW_RESTORE)
            user32.SetForegroundWindow(found_hwnd)
            return True
    except Exception as e:
        print(f"[Sorti Focus] Notice: {e}")
    return False

def check_existing_instance(meta_dir: Path) -> bool:
    """
    If another instance of Sorti is alive and responsive, delegates focus to it and returns True.
    """
    active_file = meta_dir / "active_server.json"
    if not active_file.exists():
        return False
    try:
        with open(active_file, "r", encoding="utf-8") as f:
            info = json.load(f)
        url = info.get("url")
        if url:
            req = urllib.request.Request(f"{url}/api/status", headers={"User-Agent": "Sorti-Probe"})
            with urllib.request.urlopen(req, timeout=0.8) as r:
                if r.status in (200, 503):
                    print(f"[Sorti] Existing instance responsive at {url}. Bringing window to focus.")
                    if focus_existing_window():
                        return True
                    webbrowser.open(url)
                    return True
    except Exception:
        pass
    return False

def record_active_server(meta_dir: Path, port: int):
    try:
        data = {
            "pid": os.getpid(),
            "port": port,
            "url": f"http://127.0.0.1:{port}",
            "started_at": time.time()
        }
        with open(meta_dir / "active_server.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

def cleanup_active_server(meta_dir: Path):
    try:
        f = meta_dir / "active_server.json"
        if f.exists():
            f.unlink(missing_ok=True)
    except Exception:
        pass

class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer with address reuse and daemon threads."""
    allow_reuse_address = True
    daemon_threads = True

def find_clean_port(host: str = "127.0.0.1", default_port: int = 5050, max_scan: int = 25) -> int:
    """
    Finds an unequivocally clean port that is neither actively listening nor trapped in TIME_WAIT.
    Does NOT use SO_REUSEADDR during test bind so Windows kernel refuses dirty ports.
    """
    for port in range(default_port, default_port + max_scan):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((host, port))
                return port
        except OSError:
            continue

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]

def create_server(host: str = "127.0.0.1", default_port: int = 5050) -> Tuple[ThreadingHTTPServer, int]:
    clean_port = find_clean_port(host, default_port)
    httpd = ReusableThreadingHTTPServer((host, clean_port), SortiRequestHandler)
    return httpd, clean_port

def sanitize_edge_profile(app_profile_dir: Path):
    """
    Cleans up crash states and session restores that cause Edge to reload 'ERR_CONNECTION_REFUSED'.
    """
    try:
        pref_path = app_profile_dir / "Default" / "Preferences"
        if pref_path.exists():
            try:
                with open(pref_path, "r", encoding="utf-8", errors="ignore") as f:
                    pref = json.load(f)
                if pref.get("profile", {}).get("exit_type") != "Normal":
                    pref.setdefault("profile", {})["exit_type"] = "Normal"
                    with open(pref_path, "w", encoding="utf-8") as f:
                        json.dump(pref, f)
            except Exception:
                pass

        for folder_name in ["Sessions", "Session Storage"]:
            target = app_profile_dir / "Default" / folder_name
            if target.exists():
                import shutil
                shutil.rmtree(target, ignore_errors=True)

        lock = app_profile_dir / "Default" / "LOCK"
        if lock.exists():
            lock.unlink(missing_ok=True)
    except Exception as e:
        print(f"[Sorti] Profile sanitization notice: {e}")

def wait_for_server_ready(host: str, port: int, timeout: float = 25.0) -> bool:
    """
    Probes the server with actual HTTP GET requests until it returns HTTP 200.
    Guarantees browser is never opened before the server is actively serving content.
    """
    url = f"http://{host}:{port}/"
    start = time.time()
    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Sorti-Healthcheck"})
            with urllib.request.urlopen(req, timeout=0.3) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.06)
    return False

def run_server(no_browser: bool = False):
    global MUTEX_HANDLE, ACTIVE_WINDOW
    is_primary, MUTEX_HANDLE = acquire_single_instance_lock()
    if not is_primary:
        print("[Sorti] Another instance of Sorti is already running.")
        for _ in range(6):
            if check_existing_instance(META_DIR):
                print("[Sorti] Existing instance focused. Exiting duplicate process.")
                break
            time.sleep(0.5)
        sys.exit(0)

    httpd, actual_port = create_server("127.0.0.1", PORT)
    record_active_server(META_DIR, actual_port)

    print(f"=====================================================")
    print(f"  Sorti - MoodleDoc Sorter & Course Explorer")
    print(f"  Study Root: {STUDY_ROOT}")
    print(f"  Dashboard: http://127.0.0.1:{actual_port}")
    print(f"=====================================================")

    # Start local HTTP server in a daemon thread so native GUI can own main thread
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    # Start background engine warm-up (classifier, taxonomy, converter)
    threading.Thread(target=init_engine, daemon=True).start()

    if no_browser:
        try:
            while server_thread.is_alive():
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping Sorti server...")
        finally:
            cleanup_active_server(META_DIR)
            httpd.server_close()
    else:
        wait_for_server_ready("127.0.0.1", actual_port, timeout=20.0)

        import webview

        url = f"http://127.0.0.1:{actual_port}"
        ACTIVE_WINDOW = webview.create_window(
            title="Sorti — Academic Document Sorter",
            url=url,
            width=1280,
            height=840,
            min_size=(960, 600),
            background_color="#0f172a",
            text_select=True,
            zoomable=True
        )

        icon_path = None
        if getattr(sys, 'frozen', False):
            base_p = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
            cand = base_p / "Sorti.ico"
            if cand.exists():
                icon_path = str(cand)
        else:
            cand = Path(__file__).parent / "Sorti.ico"
            if cand.exists():
                icon_path = str(cand)

        try:
            # Native Win32 / WebView2 message pump runs directly on the main thread
            webview.start(gui="edgechromium", debug=False, icon=icon_path)
        except Exception as e:
            print(f"[Sorti GUI] Native window exception: {e}. Falling back to default browser.")
            webbrowser.open(url)
            try:
                while server_thread.is_alive():
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
        finally:
            print("[Sorti] Window closed. Cleaning up...")
            cleanup_active_server(META_DIR)
            httpd.server_close()
            os._exit(0)

if __name__ == "__main__":
    no_b = "--no-browser" in sys.argv or "--headless" in sys.argv
    run_server(no_browser=no_b)


