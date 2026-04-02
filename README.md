# DefectLens

A Meta-internal tool that reviews bug reports for completeness and suggests better defect titles. It checks your task against a checklist, verifies mandatory tags, parses logs for error signals, and notifies the creator on Google Chat about gaps found.

Powered by **MetaGen & Llama** — fully internal, no external API dependencies.

## Features

- **Checklist Gap Analysis** — Compare bug reports against a configurable checklist. Missing items flagged in red, partial in amber, present in green.
- **Mandatory Tag Check** — Define required tags and verify they are applied to the task.
- **Log Parsing** — Upload bugreport/logcat files (.txt, .log, .gz, .zip). Automatically extracts crashes, ANRs, exceptions, and tombstones.
- **Defect Title Suggestions** — Suggests clear, concise titles based on description and log signals.
- **Google Chat Notification** — Send review results directly to the task creator via Google Chat DM.
- **Auto-fetch from Phabricator** — Pulls task title, description, creator, and tags from Phabricator using `jf`.

## Setup

1. **Clone the repo and create a virtual environment:**
   ```bash
   cd defectlens
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Get your MetaGen API key:**
   - Connect to Meta VPN
   - Visit https://metagen-llm-api-keys.nest.x2p.facebook.net/
   - Click **"Create API Key"**
   - Create a MetaGen entitlement and link it to your Llama API App ID (see [MetaGen docs](https://www.internalfb.com/wiki/MetaGen/Getting_Started/MetaGen_for_Researchers/) for details)

3. **Add your API key:**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and add your MetaGen API key:
   ```
   METAGEN_API_KEY=your-key-here
   ```

## Usage

```bash
source venv/bin/activate
streamlit run app.py --server.headless true
```
Opens at `http://localhost:8501`.

## How It Works

1. **Enter a task number** — DefectLens fetches the title, description, creator, and tags from Phabricator.
2. **Upload a log file** (optional) — Bugreport or logcat files are parsed for crash/error signals.
3. **Provide a checklist** (optional) — Paste, upload a file (.txt, .csv, .xlsx), or link a Google Sheet.
4. **Define mandatory tags** (optional) — Paste, upload, or link a Google Sheet with required tags.
5. **Click "Review Task"** — Get a full review with:
   - Mandatory tag check (present/missing)
   - Checklist gap analysis with color-coded results
   - Suggested defect titles in bold blue
6. **Notify creator** — Send the review to the task creator on Google Chat with one click.

## Example Output

```
## Mandatory Tags
- PRESENT: Tag `severity`
- MISSING: Tag `platform` — This mandatory tag is not applied to the task.

Mandatory tags score: 1/2 present.

## Checklist Gap Analysis
- PRESENT: Steps to reproduce
- MISSING: Expected vs actual behavior — Please describe what should happen and what actually happens.
- MISSING: Log attachment (bugreport/logcat) — No log file was attached.

Overall completeness score: 1/3 items covered.

## Suggested Defect Title
SUGGESTION: "Camera preview freezes on Pixel 8 after switching to video mode"
```

## Requirements

- Python 3.9+
- Meta VPN (for MetaGen API access)
- MetaGen API key
- `jf` CLI (for Phabricator integration)
- `gchat` CLI at `/opt/facebook/bin/gchat` (for Google Chat notifications)
