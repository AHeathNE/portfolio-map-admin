# Portfolio Map Admin

A small local tool for managing the content behind a portfolio map site — a
scatter-chart portfolio where each point is a project, positioned by two axes
(e.g. Irreverent ↔ Reverent, Low Fidelity ↔ High Fidelity) and colored by category.

This repo is just the admin tool. It doesn't host or publish the site itself —
it edits a `data/nodes.json` + `data/categories.json` + `images/` folder that
you point it at, and that folder is what you'd deploy (GitHub Pages, Netlify,
a plain file upload, anything that serves static files). The two are
deliberately decoupled: the site never links back to this admin, and this
admin can be pointed at any site folder on your machine.

## Quick start

Requires Python 3 (no other dependencies — the whole thing is the standard library).

```bash
git clone https://github.com/AHeathNE/portfolio-map-admin.git
cd portfolio-map-admin
python3 server.py
```

That opens `http://localhost:8420` in your browser automatically. On macOS you
can also just double-click `run.command`; on Windows, double-click `run.bat`.

The first time it runs, it looks for a sibling `../site` folder. If that
doesn't exist, it'll ask you to point it at one — type the path to an
existing site folder, or an empty/new folder to scaffold a fresh site there
(from `site-template/`). **Don't open `index.html` directly as a file** — it
needs the Python server running to read or save anything.

## What it does

- Add, edit, and delete projects (title, position on the chart, description,
  tags, an optional link, an optional thumbnail image)
- Define categories with a name and color — assign one to a project and it's
  reflected on the map, with a legend explaining what each color means
- Everything is saved straight to the target folder's `data/*.json` and
  `images/` — no database, just files you can read, diff, and hand-edit

## Project layout

```
server.py          local server: serves this UI + a JSON API for the target folder
index.html/js/css  the admin UI
site-template/      seed files copied into a folder the first time it's used
config.json         which folder you last pointed the admin at (gitignored)
```
