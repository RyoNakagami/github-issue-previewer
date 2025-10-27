import re
from mdformat import text as mdformat_text
import os
import yaml
import webbrowser
import socketserver
import threading
import signal
import time
import subprocess
import json
from http.server import SimpleHTTPRequestHandler
from jinja2 import Template
from markdown_it import MarkdownIt
from markdownify import markdownify as md
from pathlib import Path
from typing import Optional
import shutil
import typer
from bs4 import BeautifulSoup

app = typer.Typer(help="Live preview GitHub issue template YAML", add_completion=False)

# =============================
# Paths
# =============================
BASE_DIR = Path(__file__).resolve().parent
STYLE_DIR = BASE_DIR / "style_template"
HTML_TEMPLATE = STYLE_DIR / "github-issue-template.html"
CSS_TEMPLATE = STYLE_DIR / "github-issue-template.css"
CURRENT_DIR = Path.cwd()


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

    # Initialize markdown parser
    md = MarkdownIt()

    # Process markdown content in body elements
    if "body" in data:
        for item in data["body"]:
            if item.get("type") == "markdown" and "attributes" in item:
                if "value" in item["attributes"]:
                    item["attributes"]["html"] = md.render(item["attributes"]["value"])

            # Parse description field as markdown for all item types
            if "attributes" in item and "description" in item["attributes"]:
                desc = item["attributes"]["description"]
                if desc:
                    item["attributes"]["description_html"] = md.render(desc)

    # Process top-level description field as markdown if it exists
    if "description" in data and data["description"]:
        data["description_html"] = md.render(data["description"])
    else:
        data["description_html"] = ""

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


def hybrid_markdown_formatter(original_md: str) -> str:
    """
    Format Markdown nicely while preserving explicit numbered lists.
    """
    # 1️⃣ Run mdformat (this will normalize lists to all "1.")
    try:
        formatted = mdformat_text(original_md)
    except Exception as e:
        print(f"⚠️ mdformat failed, using unformatted markdown: {e}")
        return original_md

    # 2️⃣ Extract original list numbering
    # Map: line index (without blank lines) → actual number
    original_numbers = {}
    for idx, line in enumerate(original_md.splitlines()):
        m = re.match(r"^(\s*)(\d+)\.\s+", line)
        if m:
            original_numbers[idx] = int(m.group(2))

    # 3️⃣ Reinsert numbers back into formatted markdown
    formatted_lines = formatted.splitlines()
    new_lines = []
    num_iter = iter(original_numbers.values())
    current_num = None

    for line in formatted_lines:
        m = re.match(r"^(\s*)1\.\s+", line)
        if m:
            try:
                # Replace "1." with actual original number
                current_num = next(num_iter)
                prefix = f"{m.group(1)}{current_num}. "
                line = re.sub(r"^(\s*)1\.\s+", prefix, line)
            except StopIteration:
                pass
        new_lines.append(line)

    return "\n".join(new_lines).strip() + "\n"


# =============================
# HTTP Server
# =============================
class ThreadedTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    reload_file: Optional[Path] = None
    yaml_file: Optional[Path] = None
    output_path: Optional[Path] = None


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

    def do_POST(self):
        """Handle POST requests for exporting edited content as Markdown"""
        if self.path == "/export":
            try:
                # Read the POST data
                content_length = int(self.headers.get("Content-Length", 0))
                post_data = self.rfile.read(content_length).decode("utf-8")
                data = json.loads(post_data)

                html_content = data.get("html", "")

                # Remove elements with specific tags AND id ending with -not-exported
                tags_to_remove = ["div", "section", "p", "e", "button", "span"]
                pattern = (
                    r'<({tags})[^>]*id="[^"]*-not-exported"[^>]*>.*?</\1>'.format(
                        tags="|".join(tags_to_remove)
                    )
                )

                html_content = re.sub(pattern, "", html_content, flags=re.DOTALL | re.IGNORECASE)

                # === Extract <input id="issue-title"> and make it H1 ===
                soup = BeautifulSoup(html_content, "html.parser")
                 # 4️⃣ Find issue title input/div/etc.
                issue_title = soup.find(id="issue-title-exported")
                if issue_title:
                    title_text = issue_title.get_text(strip=True)
                    title_text = title_text.strip()
                    issue_title.extract()  # safer than decompose for self-closing

                # 5️⃣ Convert rest of HTML to Markdown
                markdown_body = md(str(soup), heading_style="ATX").strip()

                # 6️⃣ Build final Markdown
                if title_text:
                    markdown_content = f"# {title_text}\n\n{markdown_body}"
                else:
                    markdown_content = markdown_body

                if self.server.output_path:
                    output_file = Path(self.server.output_path).resolve()
                elif self.server.yaml_file:
                    output_file = self.server.yaml_file.with_suffix(".exported.md")
                else:
                    output_file = None

                if output_file:
                    try:
                        formatted_md = hybrid_markdown_formatter(markdown_content)
                    except Exception as e:
                        print(f"⚠️ mdformat failed, using unformatted markdown: {e}")
                        formatted_md = markdown_content

                    output_file.write_text(formatted_md, encoding="utf-8")

                    response = {
                        "success": True,
                        "message": f"Exported to {output_file.name}",
                        "path": str(output_file),
                    }
                else:
                    response = {
                        "success": False,
                        "message": "No valid output path or YAML file available",
                    }

                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps(response).encode("utf-8"))

            except Exception as e:
                error_response = {"success": False, "message": f"Error: {str(e)}"}
                self.send_response(500)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(error_response).encode("utf-8"))
        else:
            self.send_error(404)


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
    output_path: Optional[Path] = typer.Option(
        None, "--output-path", "-o", help="Optional Markdown export path"
    ),
):
    """Start a live HTML preview of a GitHub Issue Template YAML file."""

    # Resolve yaml_file to absolute path
    yaml_file = Path(yaml_file).resolve()
    if not yaml_file.exists():
        typer.echo(f"❌ YAML file not found: {yaml_file}")
        raise typer.Exit(code=1)

    html_file = yaml_file.with_suffix(".html")
    tmp_dir = Path("/tmp")
    reload_file = (
        tmp_dir if tmp_dir.exists() else html_file.parent
    ) / f"{yaml_file.stem}_reload.txt"

    # Change to yaml file's directory for relative path resolution
    os.chdir(yaml_file.parent)
    free_port(port)

    with open(HTML_TEMPLATE, "r", encoding="utf-8") as f:
        html_template = f.read()

    generate_html(yaml_file, html_file, CSS_TEMPLATE, reload_file, html_template)

    server = ThreadedTCPServer(("localhost", port), Handler)
    server.reload_file = reload_file
    server.yaml_file = yaml_file
    server.output_path =  (CURRENT_DIR / output_path).resolve()if output_path else None
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
