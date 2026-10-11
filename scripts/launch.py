"""Find a working interpreter and start the local app on an available port."""

import argparse
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RUNTIME_MODULES = (
    "fastapi",
    "uvicorn",
    "fitz",
    "httpx",
    "multipart",
    "bs4",
    "PIL",
    "pydantic",
    "docx",
    "pptx",
    "openpyxl",
)


def runtime_candidates():
    """Use installed-environment metadata; never assume a machine-specific drive."""
    candidates = [os.environ.get("CEA_PYTHON"), ROOT / ".venv" / "Scripts" / "python.exe", sys.executable]
    for key in ("VIRTUAL_ENV", "CONDA_PREFIX"):
        if os.environ.get(key):
            candidates.append(Path(os.environ[key]) / "python.exe")
    conda_list = Path.home() / ".conda" / "environments.txt"
    if conda_list.is_file():
        for line in conda_list.read_text(encoding="utf-8-sig").splitlines():
            if line.strip():
                candidates.append(Path(line.strip()) / ("python.exe" if os.name == "nt" else "bin/python"))
    for directory in os.get_exec_path():
        candidates.append(Path(directory) / ("python.exe" if os.name == "nt" else "python3"))
    seen = set()
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).resolve()
        key = os.path.normcase(str(path))
        if key in seen or not path.is_file() or "windowsapps" in key.lower():
            continue
        seen.add(key)
        yield path


def select_runtime():
    probe = (
        'import sys,importlib; assert sys.version_info >= (3,11), "Python 3.11+ required"; '
        f"[importlib.import_module(m) for m in {RUNTIME_MODULES!r}]"
    )
    failures = []
    for candidate in runtime_candidates():
        try:
            result = subprocess.run(
                [str(candidate), "-c", probe],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=25,
                cwd=ROOT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode == 0:
                return candidate, failures
            lines = result.stderr.strip().splitlines()
            failures.append((candidate, lines[-1] if lines else "Import check failed"))
        except (OSError, subprocess.TimeoutExpired) as exc:
            failures.append((candidate, str(exc)))
    return None, failures


def main():
    parser = argparse.ArgumentParser(description="Start Comprehensive Evaluation Assistant")
    parser.add_argument("--port", type=int, default=8768)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--check", action="store_true", help="Check and print the selected Python environment"
    )
    args = parser.parse_args()
    runtime, failures = select_runtime()
    if runtime is None:
        print("No installed Python environment could import all runtime dependencies.")
        for candidate, reason in failures:
            print(f"  {candidate}: {reason}")
        print(f'Run: "{sys.executable}" -m pip install -r "{ROOT / "requirements.txt"}"')
        return 1
    print(f"Python environment: {runtime}", flush=True)
    if args.check:
        return 0
    if not runtime.samefile(sys.executable):
        return subprocess.call([str(runtime), str(Path(__file__).resolve()), *sys.argv[1:]], cwd=ROOT)
    selected = None
    for port in range(args.port, args.port + 30):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                selected = port
                break
            except OSError:
                pass
    if selected is None:
        raise RuntimeError("No available local port")
    url = f"http://127.0.0.1:{selected}"
    print("Comprehensive Evaluation Assistant: " + url, flush=True)
    if not args.no_browser:

        def open_when_ready():
            import urllib.request

            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    with urllib.request.urlopen(url + "/health", timeout=1) as r:
                        if r.status == 200:
                            webbrowser.open(url)
                            return
                except OSError:
                    time.sleep(0.2)

        threading.Thread(target=open_when_ready, daemon=True).start()
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=selected, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
