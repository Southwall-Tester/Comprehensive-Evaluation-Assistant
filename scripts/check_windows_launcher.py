"""Reproduce Explorer's incomplete Python environment through the actual CMD entry."""

import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    bootstrap = Path(r"C:\Python314\python.exe")
    if os.name != "nt" or not bootstrap.is_file():
        raise SystemExit("This local regression needs the reported Windows Python 3.14 installation.")
    env = os.environ.copy()
    for name in list(env):
        if name.upper().startswith("CONDA") or name in {
            "VIRTUAL_ENV",
            "CEA_PYTHON",
            "PYTHONPATH",
            "PYTHONHOME",
        }:
            env.pop(name, None)
    env["PATH"] = str(bootstrap.parent) + os.pathsep + str(Path(env["SYSTEMROOT"]) / "System32")
    env["PYTHONIOENCODING"] = "utf-8"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    command = [
        env["COMSPEC"],
        "/d",
        "/c",
        str(ROOT / "Start-Assistant.cmd"),
        "--no-browser",
        "--port",
        str(port),
    ]
    with tempfile.TemporaryDirectory(prefix="cea-launch-check-") as folder:
        env["CEA_DATA"] = str(Path(folder) / "workspace")
        with (
            (Path(folder) / "stdout.log").open("w+b") as stdout,
            (Path(folder) / "stderr.log").open("w+b") as stderr,
        ):
            process = subprocess.Popen(
                command,
                cwd=env["SYSTEMROOT"],
                env=env,
                stdout=stdout,
                stderr=stderr,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            try:
                deadline = time.monotonic() + 50
                health = None
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        break
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                            health = json.load(response)
                        break
                    except OSError:
                        time.sleep(0.2)
                stdout.seek(0)
                output = stdout.read().decode("utf8", errors="replace")
                stderr.seek(0)
                error = stderr.read().decode("utf8", errors="replace")
                assert health and health["ok"], output + error
                assert "anaconda" in output.lower(), output
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as response:
                    assert b"/static/app.js" in response.read()
                record = dict(
                    status="passed",
                    bootstrap=str(bootstrap),
                    health=health,
                    path=env["PATH"],
                    command=command,
                    output=output,
                    checks=[
                        "CMD from unrelated working directory",
                        "Conda absent from PATH",
                        "real dependency imports",
                        "server health",
                        "HTML entry",
                    ],
                )
                artifacts = ROOT / "artifacts"
                artifacts.mkdir(exist_ok=True)
                (artifacts / "launcher-check.json").write_text(
                    json.dumps(record, ensure_ascii=False, indent=2), encoding="utf8"
                )
                print(output.strip())
                print("CMD_LAUNCH_PASS: Python314 bootstrap, Conda absent from PATH, health and HTML OK")
            finally:
                if process.poll() is None:
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        capture_output=True,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        check=False,
                    )
                process.wait(timeout=15)


if __name__ == "__main__":
    main()
