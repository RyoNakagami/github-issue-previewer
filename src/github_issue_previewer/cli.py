import os
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
import shutil
import typer

app = typer.Typer(help="Live preview GitHub issue template YAML", add_completion=False)

# =============================
# Paths
# =============================
BASE_DIR = Path(__file__).resolve().parent
STYLE_DIR = BASE_DIR / "style_template"
HTML_TEMPLATE = STYLE_DIR / "github-issue-template.html"
CSS_TEMPLATE = STYLE_DIR / "github-issue-template.css"


# =============================
# Utility Functions
# =============================
def free_port(port: int):
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


def cleanup(temp_html: Path, css_file: Path, reload_file: Path, port: int):
    """Remove temporary files and release resources"""
    for path in [temp_html, css_file, reload_file]:
        if path.exists():
            try:
                path.unlink()
                print(f"🗑 Deleted {path}")
            except Exception as e:
                print(f"⚠️ Failed to delete {path}: {e}")
    free_port(port)


def generate_html(
    yaml_file: Path,
    html_file: Path,
    css_file: Path,
    reload_file: Path,
    html_template: str,
):
    """
    Render YAML as HTML using Jinja2 template.

    Loads data from a YAML file, updates it with default fields, renders it to HTML using
    the provided Jinja2 template, copies the CSS file, and writes the output HTML and reload
    timestamp files.

    Args:
        yaml_file (Path): Path to the input YAML file.
        html_file (Path): Path to the output HTML file.
        css_file (Path): Path to the CSS file to copy.
        reload_file (Path): Path to the reload timestamp file.
        html_template (str): Jinja2 template string for HTML rendering.
    """
    css_dest = html_file.parent / css_file.name
    shutil.copy2(css_file, css_dest)

    with open(yaml_file, "r") as f:
        data = yaml.safe_load(f)

    data.update(
        {
            "assignees": data.get("assignees", []),
            "labels": data.get("labels", []),
            "projects": data.get("projects", []),
            "milestone": data.get("milestone", ""),
            "title": data.get("title", ""),
        }
    )

    html = Template(html_template).render(css=css_file.name, **data)
    html_file.write_text(html, encoding="utf-8")
    reload_file.write_text(str(time.time()), encoding="utf-8")
    print(f"Rendered {html_file}")


# =============================
# HTTP Server
# =============================
class ThreadedTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    reload_file: Optional[Path] = None


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=os.getcwd(), **kwargs)
        self.reload_file = None

    server: ThreadedTCPServer

    def log_message(self, format, *args):
        pass

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
# Typer main function (direct argument version)
# =============================


@app.command()
def preview(
    yaml_file: Path = typer.Argument(
        ..., exists=True, help="Path to issue_template.yml"
    ),
    browser: Optional[str] = typer.Option(
        None, "--browser", help="Browser path (optional)"
    ),
    port: int = typer.Option(8000, "--port", "-p", help="Port number"),
):
    """Start a live HTML preview of a GitHub Issue Template YAML file."""

    html_file = yaml_file.with_suffix(".html")
    tmp_dir = Path("/tmp")
    reload_file = (
        tmp_dir if tmp_dir.exists() else html_file.parent
    ) / f"{yaml_file.stem}_reload.txt"

    os.chdir(yaml_file.parent)
    free_port(port)

    with open(HTML_TEMPLATE, "r", encoding="utf-8") as f:
        html_template = f.read()

    generate_html(yaml_file, html_file, CSS_TEMPLATE, reload_file, html_template)

    server = ThreadedTCPServer(("localhost", port), Handler)
    server.reload_file = reload_file
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    url = f"http://localhost:{port}/{html_file.name}"
    try:
        if browser:
            webbrowser.register("custom", None, webbrowser.BackgroundBrowser(browser))
            webbrowser.get("custom").open(url)
        else:
            webbrowser.open(url)
    except Exception as e:
        typer.echo(f"⚠️ Could not open browser: {e}")

    typer.echo(f"✅ Live preview running at {url}. Press Ctrl+C to stop...")

    last_mtime = yaml_file.stat().st_mtime
    try:
        while True:
            time.sleep(1)
            if yaml_file.stat().st_mtime != last_mtime:
                typer.echo("♻️ YAML changed, updating preview...")
                generate_html(
                    yaml_file, html_file, CSS_TEMPLATE, reload_file, html_template
                )
                last_mtime = yaml_file.stat().st_mtime
    except KeyboardInterrupt:
        css_file = html_file.parent / CSS_TEMPLATE.name
        typer.echo("\n🛑 Shutting down server...")
        server.shutdown()
        server.server_close()
        cleanup(html_file, css_file, reload_file, port)
        typer.echo("✅ Port released. Goodbye!")


def main():
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
