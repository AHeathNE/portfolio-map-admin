#!/usr/bin/env python3
"""Local server for the portfolio map admin tool.

Serves the admin UI itself (this folder) plus a small JSON API for managing
a *separate* site folder — the actual portfolio map, which can live anywhere
on disk and eventually be published on its own (GitHub Pages, Netlify, a
plain file upload, whatever). The admin never assumes it's sitting next to
that folder: it's told where it is via /api/config and remembers it in
config.json.

If the configured folder is missing site files (a fresh empty folder, or an
existing folder that's only partially set up), the admin fills in whatever's
missing from site-template/ without touching anything that's already there —
so pointing it at a site you already hand-edited after publishing is safe.

Not hardened for production use — this is a local prototyping tool only.
"""

import base64
import json
import mimetypes
import re
import shutil
import threading
import uuid
import webbrowser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote, urlparse

ADMIN_ROOT = Path(__file__).resolve().parent
TEMPLATE_DIR = ADMIN_ROOT / "site-template"
CONFIG_FILE = ADMIN_ROOT / "config.json"
PORT = 8420

_lock = threading.Lock()

EXT_BY_MIME = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/svg+xml": "svg",
}

DATA_URL_RE = re.compile(r"^data:(?P<mime>[\w/+.-]+);base64,(?P<data>.+)$", re.DOTALL)
HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
DEFAULT_CATEGORY_COLOR = "#7dd3fc"


# ---------- config: which site folder the admin is pointed at ----------

def default_config():
    # first run on this machine: guess a sibling "site" folder if one exists,
    # otherwise leave unset and let the admin UI ask for a path
    guess = ADMIN_ROOT.parent / "site"
    target = str(guess) if guess.is_dir() else None
    return {"targetFolder": target, "recentFolders": [target] if target else []}


def load_config():
    if not CONFIG_FILE.exists():
        return default_config()
    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            config = json.load(f)
    except (json.JSONDecodeError, OSError):
        return default_config()
    # tolerate a config.json written before recentFolders existed
    config.setdefault("recentFolders", [])
    if config.get("targetFolder") and config["targetFolder"] not in config["recentFolders"]:
        config["recentFolders"].insert(0, config["targetFolder"])
    return config


def save_config(config):
    with CONFIG_FILE.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")


def target_root():
    folder = load_config().get("targetFolder")
    return Path(folder) if folder else None


def nodes_file(root):
    return root / "data" / "nodes.json"


def categories_file(root):
    return root / "data" / "categories.json"


def images_dir(root):
    return root / "images"


# ---------- scaffolding a site folder from the template ----------

def scaffold_missing(src, dst):
    """Copy anything present in the template but missing from dst. Never
    overwrites a file that's already there — an existing hand-edited site
    is left alone, only genuinely missing pieces get filled in."""
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name == ".gitkeep":
            continue
        target = dst / item.name
        if item.is_dir():
            scaffold_missing(item, target)
        elif not target.exists():
            shutil.copy2(item, target)


# ---------- data helpers ----------

def load_json(path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def save_image_from_data_url(root, data_url):
    match = DATA_URL_RE.match(data_url)
    if not match:
        raise ValueError("Unrecognized image data URL")
    mime = match.group("mime")
    ext = EXT_BY_MIME.get(mime, "png")
    raw = base64.b64decode(match.group("data"))
    img_dir = images_dir(root)
    img_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.{ext}"
    (img_dir / filename).write_bytes(raw)
    return f"images/{filename}"


def delete_image_file(root, image_path):
    if not image_path:
        return
    # only ever remove files inside this site's images/, never follow traversal
    candidate = (root / image_path).resolve()
    img_dir = images_dir(root).resolve()
    if img_dir in candidate.parents and candidate.exists():
        candidate.unlink()


def parse_folder_path(raw_path):
    """Forgiving parsing for a pasted/typed folder path: trims whitespace,
    strips a matching pair of surrounding quotes (common when pasting a path
    copied from Finder/Explorer), expands ~, and resolves a relative path
    against the user's home directory instead of rejecting it outright."""
    text = raw_path.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        text = text[1:-1].strip()
    folder = Path(text).expanduser()
    if not folder.is_absolute():
        folder = Path.home() / folder
    return folder


def add_recent_folder(config, folder_str):
    recents = [f for f in config.get("recentFolders", []) if f != folder_str]
    recents.insert(0, folder_str)
    config["recentFolders"] = recents[:5]
    return config


def clamp(value, lo=-1.0, hi=1.0):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(lo, min(hi, value))


def sanitize_node(root, payload, existing=None):
    node = dict(existing) if existing else {}
    node["title"] = str(payload.get("title", "")).strip() or "Untitled"
    node["x"] = clamp(payload.get("x", node.get("x", 0)))
    node["y"] = clamp(payload.get("y", node.get("y", 0)))
    node["description"] = str(payload.get("description", "")).strip()
    node["link"] = str(payload.get("link", "")).strip()
    node["category"] = str(payload.get("category", node.get("category", ""))).strip()

    tags = payload.get("tags", node.get("tags", []))
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    node["tags"] = [str(t) for t in tags][:8]

    image_data_url = payload.get("imageDataUrl")
    if image_data_url:
        old_image = node.get("image")
        node["image"] = save_image_from_data_url(root, image_data_url)
        if existing and old_image and old_image != node["image"]:
            delete_image_file(root, old_image)
    elif payload.get("removeImage"):
        delete_image_file(root, node.get("image"))
        node["image"] = ""
    elif "image" not in node:
        node["image"] = ""

    return node


def sanitize_category(payload, existing=None):
    cat = dict(existing) if existing else {}
    cat["name"] = str(payload.get("name", "")).strip() or "Untitled"
    color = str(payload.get("color", cat.get("color", DEFAULT_CATEGORY_COLOR))).strip()
    cat["color"] = color if HEX_COLOR_RE.match(color) else cat.get("color", DEFAULT_CATEGORY_COLOR)
    return cat


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ADMIN_ROOT), **kwargs)

    def log_message(self, fmt, *args):
        pass  # keep the terminal quiet; errors still raise/print via default handler

    def end_headers(self):
        # this is a local tool that gets edited and reloaded constantly —
        # stale browser caching of html/css/js is more trouble than it's worth
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _resource_and_id(self):
        # expects /api/<resource>[/<id>]
        path = urlparse(self.path).path
        parts = path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "api":
            resource = parts[1]
            item_id = parts[2] if len(parts) >= 3 else None
            return resource, item_id
        return None, None

    def _require_root(self):
        root = target_root()
        if root is None or not root.is_dir():
            self._send_json(400, {"error": "No site folder configured yet. Set one from the admin header."})
            return None
        return root

    def _serve_site_file(self):
        # /site-files/<relative path inside the target folder> — used so the
        # admin UI can show thumbnails/previews that live in the site folder,
        # which is not necessarily anywhere near this admin's own directory
        root = target_root()
        if root is None:
            self.send_error(404, "No site folder configured")
            return
        rel = unquote(urlparse(self.path).path[len("/site-files/"):])
        candidate = (root / rel).resolve()
        try:
            root_resolved = root.resolve()
        except OSError:
            self.send_error(404)
            return
        if root_resolved not in candidate.parents or not candidate.is_file():
            self.send_error(404)
            return
        ctype = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        data = candidate.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith("/site-files/"):
            self._serve_site_file()
            return
        if path == "/api/config":
            config = load_config()
            self._send_json(200, config)
            return
        if path == "/api/nodes":
            root = self._require_root()
            if root is None:
                return
            with _lock:
                nodes = load_json(nodes_file(root))
            self._send_json(200, nodes)
            return
        if path == "/api/categories":
            root = self._require_root()
            if root is None:
                return
            with _lock:
                categories = load_json(categories_file(root))
            self._send_json(200, categories)
            return
        super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/config":
            try:
                payload = self._read_json_body()
                raw_path = str(payload.get("targetFolder", ""))
                if not raw_path.strip():
                    self._send_json(400, {"error": "A folder path is required."})
                    return
                folder = parse_folder_path(raw_path)
                try:
                    folder.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    self._send_json(400, {"error": f"Couldn't use “{folder}”: {exc.strerror or exc}"})
                    return
                with _lock:
                    scaffold_missing(TEMPLATE_DIR, folder)
                    config = load_config()
                    config["targetFolder"] = str(folder)
                    add_recent_folder(config, str(folder))
                    save_config(config)
                self._send_json(200, config)
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
            return

        resource, _ = self._resource_and_id()
        root = self._require_root()
        if root is None:
            return
        try:
            payload = self._read_json_body()
            if resource == "nodes":
                with _lock:
                    nodes = load_json(nodes_file(root))
                    node = sanitize_node(root, payload)
                    node["id"] = f"n_{uuid.uuid4().hex[:10]}"
                    nodes.append(node)
                    save_json(nodes_file(root), nodes)
                self._send_json(201, node)
            elif resource == "categories":
                with _lock:
                    categories = load_json(categories_file(root))
                    cat = sanitize_category(payload)
                    cat["id"] = f"c_{uuid.uuid4().hex[:8]}"
                    categories.append(cat)
                    save_json(categories_file(root), categories)
                self._send_json(201, cat)
            else:
                self._send_json(404, {"error": "not found"})
        except Exception as exc:  # local tool: surface the error, don't crash the server
            self._send_json(400, {"error": str(exc)})

    def do_PUT(self):
        resource, item_id = self._resource_and_id()
        if not item_id:
            self._send_json(404, {"error": "not found"})
            return
        root = self._require_root()
        if root is None:
            return
        try:
            payload = self._read_json_body()
            if resource == "nodes":
                with _lock:
                    nodes = load_json(nodes_file(root))
                    idx = next((i for i, n in enumerate(nodes) if n.get("id") == item_id), None)
                    if idx is None:
                        self._send_json(404, {"error": "node not found"})
                        return
                    updated = sanitize_node(root, payload, existing=nodes[idx])
                    updated["id"] = item_id
                    nodes[idx] = updated
                    save_json(nodes_file(root), nodes)
                self._send_json(200, updated)
            elif resource == "categories":
                with _lock:
                    categories = load_json(categories_file(root))
                    idx = next((i for i, c in enumerate(categories) if c.get("id") == item_id), None)
                    if idx is None:
                        self._send_json(404, {"error": "category not found"})
                        return
                    updated = sanitize_category(payload, existing=categories[idx])
                    updated["id"] = item_id
                    categories[idx] = updated
                    save_json(categories_file(root), categories)
                self._send_json(200, updated)
            else:
                self._send_json(404, {"error": "not found"})
        except Exception as exc:
            self._send_json(400, {"error": str(exc)})

    def do_DELETE(self):
        resource, item_id = self._resource_and_id()
        if not item_id:
            self._send_json(404, {"error": "not found"})
            return
        root = self._require_root()
        if root is None:
            return
        if resource == "nodes":
            with _lock:
                nodes = load_json(nodes_file(root))
                idx = next((i for i, n in enumerate(nodes) if n.get("id") == item_id), None)
                if idx is None:
                    self._send_json(404, {"error": "node not found"})
                    return
                removed = nodes.pop(idx)
                delete_image_file(root, removed.get("image"))
                save_json(nodes_file(root), nodes)
            self._send_json(200, {"ok": True})
        elif resource == "categories":
            with _lock:
                categories = load_json(categories_file(root))
                idx = next((i for i, c in enumerate(categories) if c.get("id") == item_id), None)
                if idx is None:
                    self._send_json(404, {"error": "category not found"})
                    return
                categories.pop(idx)
                save_json(categories_file(root), categories)
                # nodes referencing the deleted category fall back to "no category"
                nodes = load_json(nodes_file(root))
                changed = False
                for node in nodes:
                    if node.get("category") == item_id:
                        node["category"] = ""
                        changed = True
                if changed:
                    save_json(nodes_file(root), nodes)
            self._send_json(200, {"ok": True})
        else:
            self._send_json(404, {"error": "not found"})


def main():
    mimetypes.add_type("application/json", ".json")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"Admin serving at {url}")
    root = target_root()
    print(f"  Site folder: {root if root else '(not set — configure it from the admin header)'}")
    print("Opening in your browser... (leave this window open — closing it stops the server)")
    threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
