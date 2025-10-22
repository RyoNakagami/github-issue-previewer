import os
import sys
import yaml
import webbrowser
import socketserver
import threading
import signal
import time
import subprocess
from http.server import SimpleHTTPRequestHandler
from jinja2 import Template
from pathlib import Path
from typing import Optional
import argparse
import shutil


# =============================
# Paths
# =============================
BASE_DIR = Path(__file__).resolve().parent
STYLE_DIR = BASE_DIR / "style_template"
HTML_TEMPLATE = STYLE_DIR / "github-issue-template.html"
CSS_TEMPLATE = STYLE_DIR / "github-issue-template.css"


# =============================
# CLI Arguments
# =============================
def parse_args():
    parser = argparse.ArgumentParser(
        description="Live preview GitHub issue template YAML"
    )
    parser.add_argument("yaml_file", help="Path to issue_template.yml")
    parser.add_argument("--browser", help="Browser path (optional)")
    parser.add_argument("--port", type=int, default=8000, help="Port number")
    return parser.parse_args()


# =============================
# Utility Functions
# =============================
def free_port(port: int):
    """Kill existing process on the same port (useful for live reload)"""
    try:
        pid_output = subprocess.check_output(
            ["lsof", "-ti", f":{port}"], text=True
        ).strip()
        for pid in pid_output.splitlines():
            if pid:
                print(f"Killing process on port {port} (PID {pid})")
                os.kill(int(pid), signal.SIGKILL)
        time.sleep(0.5)
    except subprocess.CalledProcessError:
        pass


def cleanup(temp_html: Path, reload_file: Path, port: int):
    """Remove temporary files and release resources"""
    for path in [temp_html, reload_file]:
        if path.exists():
            try:
                path.unlink()
                print(f"🗑 Deleted {path}")
            except Exception as e:
                print(f"⚠️ Failed to delete {path}: {e}")
    free_port(port)


# =============================
# HTML Generator
# =============================
def generate_html(
    yaml_file: Path,
    html_file: Path,
    css_name: str,
    reload_file: Path,
    html_template: str,
):
    """Render YAML as HTML using Jinja2 template"""
    with open(yaml_file, "r") as f:
        data = yaml.safe_load(f)

    # Provide default fields
    data.update(
        {
            "assignees": data.get("assignees", []),
            "labels": data.get("labels", []),
            "projects": data.get("projects", []),
            "milestone": data.get("milestone", ""),
            "title": data.get("title", ""),
        }
    )

    html = Template(html_template).render(css=css_name, **data)
    html_file.write_text(html, encoding="utf-8")
    reload_file.write_text(str(time.time()), encoding="utf-8")
    print(f"Rendered {html_file}")


# =============================
# HTTP Server
class ThreadedTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    reload_file: Optional[Path] = None  # Class attribute for storing reload file path
    reload_file = None  # Class attribute for storing reload file path


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=os.getcwd(), **kwargs)
        self.reload_file = None  # Instance attribute for storing reload file path

    server: ThreadedTCPServer  # Type hint to recognize custom attribute

    def log_message(self, format, *args):
        pass  # suppress logs

    def do_GET(self):
        if self.path.startswith("/reload.txt"):
            try:
                if self.server.reload_file is None:
                    self.send_error(404)
                    return
                with open(self.server.reload_file, "r") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write(content.encode("utf-8"))
            except Exception:
                self.send_error(404)
        else:
            super().do_GET()


# =============================
# Main Entry Point
# =============================
def main():
    args = parse_args()
    yaml_file = Path(args.yaml_file).resolve()

    if not yaml_file.exists():
        print(f"❌ YAML file not found: {yaml_file}")
        sys.exit(1)

    html_file = yaml_file.with_suffix(".html")
    port = args.port
    tmp_dir = Path("/tmp")
    reload_file = (
        tmp_dir if tmp_dir.exists() else html_file.parent
    ) / f"{yaml_file.stem}_reload.txt"

    # Copy CSS next to generated HTML
    css_dest = html_file.parent / CSS_TEMPLATE.name
    shutil.copy2(CSS_TEMPLATE, css_dest)

    os.chdir(yaml_file.parent)
    free_port(port)

    with open(HTML_TEMPLATE, "r", encoding="utf-8") as f:
        html_template = f.read()

    generate_html(yaml_file, html_file, CSS_TEMPLATE.name, reload_file, html_template)

    # Start threaded server
    server = ThreadedTCPServer(("localhost", port), Handler)
    server.reload_file = reload_file
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    url = f"http://localhost:{port}/{html_file.name}"
    try:
        if args.browser:
            webbrowser.register(
                "custom", None, webbrowser.BackgroundBrowser(args.browser)
            )
            webbrowser.get("custom").open(url)
        else:
            webbrowser.open(url)
    except Exception as e:
        print(f"⚠️ Could not open browser: {e}")

    print(f"✅ Live preview running at {url}. Press Ctrl+C to stop...")

    # Watch YAML file for changes
    last_mtime = yaml_file.stat().st_mtime
    try:
        while True:
            time.sleep(1)
            if yaml_file.stat().st_mtime != last_mtime:
                print("♻️ YAML changed, updating preview...")
                generate_html(
                    yaml_file, html_file, CSS_TEMPLATE.name, reload_file, html_template
                )
                last_mtime = yaml_file.stat().st_mtime
    except KeyboardInterrupt:
        print("\n🛑 Shutting down server...")
        server.shutdown()
        server.server_close()
        cleanup(html_file, reload_file, port)
        print("✅ Port released. Goodbye!")


if __name__ == "__main__":
    main()
