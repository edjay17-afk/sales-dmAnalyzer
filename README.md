# BM & Sales Analyzer

Local Flask web app for analyzing **OR Sales Monitor** and **Bad Merchandise (BM)** PDF reports across store categories, tracking shrinkage against a 31-day baseline, and generating 7-day order suggestions.

## Features

- **PDF Ingestion & SQLite History** — Upload OR Sales Monitor and Bad Merchandise PDFs in any order. Parsed line items are stored in `data/analyzer.db`; re-uploading a day or slip replaces its previous entry.
- **Period & Category Reporting** — Filter by date range and any combination of categories (with quick-select presets for **Hot Meals + Fresh Food** and **Hot Meals + Fresh Food + Crunch Time**).
- **Interactive Analysis** — Overview KPIs, daily sales vs. BM cost SVG charts, category breakdown, previous-period/baseline comparisons, top BM items, low-wastage items, top sellers, and searchable/sortable 7-day order suggestions (`Increase`, `Hold`, `Trim`, `Cut`, `Pause`).
- **Exports** — Download formatted A4 PDF briefs (`/report.pdf`) with Matplotlib charts or full product-level CSVs (`/report.csv`).
- **Authentication** — Session-based `/login` and `/logout` backed by Werkzeug password hashes in SQLite.

## Requirements

- Python 3.10+
- Packages: `flask`, `pdfplumber`, `reportlab`, `matplotlib`

```bash
pip install flask pdfplumber reportlab matplotlib
```

## Running Locally

On Windows, double-click `run.bat` or run:

```bash
python app.py
```

The app starts on `http://127.0.0.1:5412` and opens in your default browser.

### Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `ANALYZER_PORT` | `5412` | Local port for the Flask server |
| `ANALYZER_DB` | `data/analyzer.db` | Path to the SQLite database file |
| `ANALYZER_SECRET` | random per run | Flask session signing key |

## Tests

```bash
python tests/test_known_week.py
```

## Project Structure

```text
├── app.py                  # Flask routes, auth guard, and server entrypoint
├── run.bat                 # Windows launcher (restarts port 5412 listener)
├── seed_history.py         # Bulk-import helper for local PDF folders
├── analyzer/
│   ├── analysis.py         # Sales, BM, baseline, and order-suggestion logic
│   ├── charts.py           # Matplotlib PNG charts for PDF export
│   ├── charts_svg.py       # Inline SVG charts for web reports
│   ├── db.py               # SQLite schema, queries, and user auth helpers
│   ├── parsers.py          # OR Sales Monitor & Bad Merchandise PDF parsers
│   ├── pdf_report.py       # ReportLab A4 PDF builder
│   └── viewmodel.py        # Display headlines, KPIs, and order briefs
├── static/
│   ├── favicon.svg         # App icon
│   └── style.css           # Light-mode ledger stylesheet
├── templates/
│   ├── base.html           # Shared topbar layout
│   ├── index.html          # PDF upload and history coverage view
│   ├── login.html          # Sign-in page
│   └── report.html         # Analysis report view
└── tests/
    └── test_known_week.py  # Regression checks against verified PDF totals
```
