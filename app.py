import os
import re
import subprocess
import json
import streamlit as st
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

SYSTEM_PROMPT = """You are a Bug Report Review Agent. Your output MUST use proper markdown formatting with line breaks between items. NEVER output bulleted items or numbered items in a single paragraph.

## Mandatory Tags
If mandatory tag results are provided, include them as-is in your output under a "## Mandatory Tags" heading before the checklist gap analysis.

## Part 1: Checklist Gap Analysis

First line after the heading must be:
Overall completeness score: X/Y items covered (Z%)

Then output each checklist item as a markdown bullet, one per line:
- 🟢 **PRESENT**: <item> — if fully covered
- 🟡 **PARTIALLY PRESENT**: <item> — <what is incomplete>
- 🔴 **MISSING**: <item> — <what to add>

If no log signals are provided, always include:
- 🔴 **MISSING**: Log attachment (bugreport/logcat) — No log file was attached. Please attach relevant logs for debugging.

If no checklist is provided, assess for: steps to reproduce, expected vs actual behavior, environment info, severity, log attachment, and screenshots.

## Part 2: Suggested Defect Title

### Analysis
Write a short paragraph analyzing the current title's weaknesses.

### Suggestions
Output exactly 3 suggestions as a numbered list:
1. 💡 **SUGGESTION**: "<best title>"
2. 💡 **SUGGESTION**: "<second best title>"
3. 💡 **SUGGESTION**: "<third title>"

### Why the top suggestion is best
Write a short paragraph explaining why.

FORMATTING RULES:
- Each bullet or numbered item MUST be on its own line
- Do NOT add extra blank lines between list items
- NEVER combine multiple items into one paragraph
- Use markdown headings (##, ###) to separate sections"""

PROVIDERS = {
    "MetaGen (Internal)": {
        "key_env": "METAGEN_API_KEY",
        "placeholder": "LLM|...",
        "help": "Get your key at https://metagen-llm-api-keys.nest.x2p.facebook.net/ (Meta VPN required)",
    },
    "Ollama (Local — No API Key)": {
        "key_env": None,
        "placeholder": "",
        "help": "Runs Llama locally via Ollama. No API key needed. Install from ollama.com/download",
    },
}


def get_default_key(env_var):
    try:
        key = st.secrets.get(env_var, "")
    except Exception:
        key = ""
    if not key:
        key = os.environ.get(env_var, "")
    return key


def fetch_task_details(task_number):
    """Fetch task title, description, creator, tags, and status from Meta Phabricator using jf CLI."""
    number = task_number.strip().lstrip("Tt")
    try:
        result = subprocess.run(
            [
                "jf", "graphql", "--query",
                f'{{ task(number: {number}) {{ name, is_closed, task_description {{ text }}, task_creator {{ name, unixname }}, tags {{ nodes {{ name }} }} }} }}',
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            task = data.get("task")
            if task:
                name = task.get("name", "")
                is_closed = task.get("is_closed", False)
                description = ""
                task_desc = task.get("task_description")
                if task_desc:
                    description = task_desc.get("text", "")
                creator = task.get("task_creator") or {}
                creator_name = creator.get("name", "")
                creator_unixname = creator.get("unixname", "")
                tags_nodes = (task.get("tags") or {}).get("nodes") or []
                tags = [t.get("name", "") for t in tags_nodes]
                return name, description, creator_name, creator_unixname, tags, is_closed
        return None, None, None, None, [], False
    except Exception:
        return None, None, None, None, [], False


def send_gchat_message(unixname, message_text):
    """Send a Google Chat DM to a user using the gchat CLI."""
    import tempfile
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(message_text)
            tmp_path = f.name
        result = subprocess.run(
            ["/opt/facebook/bin/gchat", "chat", "send", unixname, "--text-file", tmp_path],
            capture_output=True,
            text=True,
            timeout=60,
        )
        os.unlink(tmp_path)
        if result.returncode == 0:
            return True, "Message sent successfully"
        else:
            return False, f"gchat error: {result.stderr or result.stdout}"
    except FileNotFoundError:
        return False, "gchat CLI not found at /opt/facebook/bin/gchat"
    except subprocess.TimeoutExpired:
        return False, "gchat command timed out. Try again."
    except Exception as e:
        return False, f"Send failed: {e}"


def parse_log(log_text):
    """Extract key error signals from bugreport/logcat logs."""
    signals = []
    lines = log_text.splitlines()

    fatal_pattern = re.compile(r"(FATAL EXCEPTION|FATAL|AndroidRuntime|CRASH|panic|kernel panic)", re.IGNORECASE)
    anr_pattern = re.compile(r"(ANR in|Application Not Responding|Input dispatching timed out)", re.IGNORECASE)
    exception_pattern = re.compile(r"(Exception|Error|Throwable):\s*(.+)", re.IGNORECASE)
    tombstone_pattern = re.compile(r"(signal \d+ \(SIG\w+\)|Abort message:|backtrace:)", re.IGNORECASE)
    native_crash_pattern = re.compile(r"(DEBUG\s*:\s*pid:|*** *** *** *** *** ***)", re.IGNORECASE)

    context_window = 3
    for i, line in enumerate(lines):
        matched = False
        for pattern, label in [
            (fatal_pattern, "FATAL"),
            (anr_pattern, "ANR"),
            (native_crash_pattern, "NATIVE_CRASH"),
            (tombstone_pattern, "TOMBSTONE"),
        ]:
            if pattern.search(line):
                start = max(0, i - context_window)
                end = min(len(lines), i + context_window + 1)
                snippet = "\n".join(lines[start:end])
                signals.append(f"[{label}]\n{snippet}")
                matched = True
                break
        if not matched and exception_pattern.search(line):
            start = max(0, i)
            end = min(len(lines), i + 6)
            snippet = "\n".join(lines[start:end])
            signals.append(f"[EXCEPTION]\n{snippet}")

    # Deduplicate and limit
    seen = set()
    unique_signals = []
    for s in signals:
        key = s[:200]
        if key not in seen:
            seen.add(key)
            unique_signals.append(s)
        if len(unique_signals) >= 10:
            break

    return unique_signals


def check_mandatory_tags(mandatory_tags, actual_tags):
    """Compare mandatory tags against actual task tags. Returns formatted results."""
    if not mandatory_tags:
        return None
    actual_lower = {t.lower().strip() for t in actual_tags}
    results = []
    present_count = 0
    for tag in mandatory_tags:
        tag_clean = tag.strip()
        if not tag_clean:
            continue
        if tag_clean.lower() in actual_lower:
            results.append(f"- 🟢 **PRESENT**: Tag `{tag_clean}`")
            present_count += 1
        else:
            results.append(f"- 🔴 **MISSING**: Tag `{tag_clean}` — This mandatory tag is not applied to the task.")
    total = len([t for t in mandatory_tags if t.strip()])
    if total > 0:
        pct = (present_count / total) * 100
        if pct >= 80:
            score_color = "#198754"
        elif pct >= 50:
            score_color = "#d4930d"
        else:
            score_color = "#dc3545"
        results.append(f'<div style="color:{score_color};font-weight:bold;font-size:1.15em;margin:1em 0;">Mandatory tags score: {present_count}/{total} present ({pct:.0f}%)</div>')
    # Put score at the top, then list individual tag items
    tag_items = results[:-1]
    score_line = results[-1]
    return score_line + "\n\n" + "\n\n".join(tag_items)


def build_user_prompt(task_number, current_title, description, log_summary=None, checklist=None, tags=None, mandatory_tag_results=None):
    prompt = f'Task Number: {task_number}\nCurrent Bug Title: "{current_title}"'
    if tags:
        prompt += f"\n\nTask Tags: {', '.join(tags)}"
    if description:
        prompt += f"\n\nTask Description:\n{description}"
    if log_summary:
        prompt += f"\n\nParsed Log Signals (extracted from attached bugreport/logcat):\n{log_summary}"
    if mandatory_tag_results:
        prompt += f"\n\nMandatory Tag Check Results (include as-is in output):\n{mandatory_tag_results}"
    if checklist:
        prompt += f"\n\nBug Report Checklist (required information):\n{checklist}"
    prompt += "\n\nPlease review this task: first show mandatory tag results (if any), then provide the checklist gap analysis, then suggest a defect title that clearly explains the intent of the defect based on the description and logs."
    return prompt


def call_metagen(api_key, task_number, current_title, description, log_summary=None, checklist=None, tags=None, mandatory_tag_results=None):
    import urllib.request

    payload = json.dumps({
        "model": "Llama-4-Scout-17B-16E-Instruct-FP8",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(task_number, current_title, description, log_summary, checklist, tags, mandatory_tag_results)},
        ],
        "max_tokens": 1024,
    })
    req = urllib.request.Request(
        "https://api.llama.com/compat/v1/chat/completions",
        data=payload.encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]


def call_ollama(api_key, task_number, current_title, description, log_summary=None, checklist=None, tags=None, mandatory_tag_results=None):
    import urllib.request
    import urllib.error

    payload = json.dumps({
        "model": "llama3.1:8b",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(task_number, current_title, description, log_summary, checklist, tags, mandatory_tag_results)},
        ],
        "stream": False,
    })
    req = urllib.request.Request(
        "http://localhost:11434/api/chat",
        data=payload.encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["message"]["content"]
    except urllib.error.URLError:
        raise ConnectionError(
            "Cannot connect to Ollama. Make sure Ollama is running:\n"
            "1. Install from ollama.com/download\n"
            "2. Open the Ollama app\n"
            "3. Run: ollama pull llama3.1:8b"
        )


CALL_FUNCTIONS = {
    "MetaGen (Internal)": call_metagen,
    "Ollama (Local — No API Key)": call_ollama,
}


st.set_page_config(page_title="DefectLens", page_icon="🔍", layout="centered")

st.markdown("""
<style>
    section[data-testid="stSidebar"] {
        min-width: 380px;
        max-width: 420px;
    }
    .stMarkdown strong {font-weight: 700;}
    div[data-testid="stButton"].notify-btn button {
        background-color: #198754 !important;
        color: white !important;
        border: none !important;
        padding: 0.5rem 1rem !important;
        font-size: 1rem !important;
        font-weight: 600 !important;
        border-radius: 0.5rem !important;
        width: 100% !important;
    }
    div[data-testid="stButton"].notify-btn button:hover {
        background-color: #146c43 !important;
        color: white !important;
    }
</style>
""", unsafe_allow_html=True)

st.title("🔍 DefectLens")
st.markdown("Review a task for completeness against your checklist and get a better defect title based on description and logs.")

st.divider()

with st.sidebar:
    st.header("Settings")
    provider = st.selectbox("AI Provider", list(PROVIDERS.keys()))
    provider_config = PROVIDERS[provider]

    if provider_config["key_env"] is None:
        api_key = "local"
        st.success("No API key needed — runs locally via Ollama.")
        with st.expander("Ollama Setup Instructions"):
            st.markdown("""
1. **Download & Install** Ollama from [ollama.com/download](https://ollama.com/download)
2. **Open** the Ollama app
3. **Pull the model** — run in terminal:
   ```
   ollama pull llama3.1:8b
   ```
4. Make sure Ollama is **running** before clicking Review Task
""")
    else:
        default_key = get_default_key(provider_config["key_env"])
        if default_key:
            st.success("API key configured.")
            api_key = default_key
        else:
            api_key = st.text_input(
                "API Key",
                type="password",
                placeholder=provider_config["placeholder"],
                help=provider_config["help"],
            )
            if api_key:
                st.success("API key set!")
            else:
                st.info(f"Enter your API key. {provider_config['help']}")

task_number = st.text_input("Task Number", placeholder="T12345")

fetched_title = None
fetched_description = None
creator_name = None
creator_unixname = None
fetched_tags = []
task_is_closed = False
if task_number:
    with st.spinner("Fetching task details..."):
        fetched_title, fetched_description, creator_name, creator_unixname, fetched_tags, task_is_closed = fetch_task_details(task_number)
    if fetched_title:
        st.success(f"Fetched title: **{fetched_title}**")
    if task_is_closed:
        st.warning("This task is **Closed**. Only open tasks can be reviewed.")
    if creator_name:
        st.info(f"Creator: **{creator_name}** ({creator_unixname})")
    if fetched_description:
        with st.expander("Task Description (fetched)", expanded=False):
            st.text(fetched_description[:2000])

current_title = st.text_input(
    "Current Bug Title",
    value=fetched_title or "",
    placeholder="login not working",
    help="Auto-filled from task number, or enter manually",
)

description = st.text_area(
    "Bug Description (optional - helps generate better titles)",
    value=fetched_description or "",
    placeholder="Describe the bug in detail...",
    height=150,
    help="Auto-filled from task, or enter manually. More detail = better suggestions.",
)

st.subheader("Log Attachment")
uploaded_log = st.file_uploader(
    "Upload bugreport or logcat log file",
    type=["txt", "log", "zip", "gz"],
    help="Upload a bugreport or logcat file. The tool will parse it for errors, crashes, and ANRs to improve title suggestions.",
)

log_summary = None
if uploaded_log:
    try:
        if uploaded_log.name.endswith(".gz"):
            import gzip
            log_text = gzip.decompress(uploaded_log.read()).decode("utf-8", errors="replace")
        elif uploaded_log.name.endswith(".zip"):
            import zipfile
            import io
            with zipfile.ZipFile(io.BytesIO(uploaded_log.read())) as zf:
                text_parts = []
                for name in zf.namelist():
                    if any(kw in name.lower() for kw in ["logcat", "main", "system", "crash", "anr", "tombstone", "bugreport"]):
                        text_parts.append(zf.read(name).decode("utf-8", errors="replace"))
                log_text = "\n".join(text_parts) if text_parts else zf.read(zf.namelist()[0]).decode("utf-8", errors="replace")
        else:
            log_text = uploaded_log.read().decode("utf-8", errors="replace")

        signals = parse_log(log_text)
        if signals:
            log_summary = "\n\n".join(signals)
            st.success(f"Parsed {len(signals)} error signal(s) from log.")
            with st.expander("Parsed Log Signals", expanded=False):
                st.code(log_summary, language="text")
        else:
            st.info("No crash/error signals found in the log file.")
    except Exception as e:
        st.error(f"Failed to parse log file: {e}")

st.subheader("Bug Report Checklist")
checklist_source = st.radio(
    "Checklist source",
    ["Paste manually", "Upload file", "Google Sheet link"],
    horizontal=True,
)

checklist_text = None

if checklist_source == "Upload file":
    uploaded_checklist = st.file_uploader(
        "Upload checklist file",
        type=["txt", "md", "csv", "xlsx", "xls"],
        help="Upload a checklist file (.txt, .md, .csv, .xlsx) listing required information for a complete bug report.",
        key="checklist_uploader",
    )
    if uploaded_checklist:
        try:
            if uploaded_checklist.name.endswith((".xlsx", ".xls")):
                import pandas as pd
                df = pd.read_excel(uploaded_checklist)
                checklist_text = df.to_string(index=False)
            elif uploaded_checklist.name.endswith(".csv"):
                import pandas as pd
                df = pd.read_csv(uploaded_checklist)
                checklist_text = df.to_string(index=False)
            else:
                checklist_text = uploaded_checklist.read().decode("utf-8", errors="replace")
            st.success("Checklist loaded.")
            with st.expander("Checklist Contents", expanded=False):
                st.markdown(checklist_text)
        except Exception as e:
            st.error(f"Failed to read checklist: {e}")

elif checklist_source == "Google Sheet link":
    sheet_url = st.text_input(
        "Google Sheet URL",
        placeholder="https://docs.google.com/spreadsheets/d/...",
        help="Paste a Google Sheet link. The sheet must be accessible (shared within Meta).",
    )
    if sheet_url:
        try:
            import pandas as pd
            # Convert Google Sheet URL to CSV export URL
            if "/edit" in sheet_url:
                csv_url = sheet_url.split("/edit")[0] + "/export?format=csv"
            elif "/pubhtml" in sheet_url:
                csv_url = sheet_url.split("/pubhtml")[0] + "/export?format=csv"
            else:
                csv_url = sheet_url.rstrip("/") + "/export?format=csv"
            with st.spinner("Fetching Google Sheet..."):
                df = pd.read_csv(csv_url)
                checklist_text = df.to_string(index=False)
            st.success("Google Sheet loaded.")
            with st.expander("Checklist Contents", expanded=False):
                st.dataframe(df)
        except Exception as e:
            st.error(f"Failed to fetch Google Sheet: {e}. Make sure the sheet is shared/accessible.")

else:
    checklist_text = st.text_area(
        "Paste your checklist here",
        placeholder="- Steps to reproduce\n- Expected behavior\n- Actual behavior\n- Device/OS info\n- Screenshots/logs attached\n- Severity/priority\n- Build version",
        height=120,
        help="List the required information items for a complete bug report.",
    )
    if not checklist_text:
        checklist_text = None

st.subheader("Mandatory Tags")
tags_source = st.radio(
    "Mandatory tags source",
    ["Paste manually", "Upload file", "Google Sheet link"],
    horizontal=True,
    key="tags_source",
)

mandatory_tags_input = None

if tags_source == "Paste manually":
    mandatory_tags_input = st.text_area(
        "Enter mandatory tags (one per line)",
        placeholder="severity\ncomponent\nplatform\nteam\nproduct-area",
        height=120,
        help="List tags that must be present on every task. One tag per line.",
    )

elif tags_source == "Upload file":
    uploaded_tags = st.file_uploader(
        "Upload mandatory tags file",
        type=["txt", "md", "csv", "xlsx", "xls"],
        help="Upload a file with mandatory tags. One tag per line (txt/md) or one column (csv/xlsx).",
        key="tags_uploader",
    )
    if uploaded_tags:
        try:
            if uploaded_tags.name.endswith((".xlsx", ".xls")):
                import pandas as pd
                df = pd.read_excel(uploaded_tags)
                mandatory_tags_input = "\n".join(df.iloc[:, 0].dropna().astype(str).tolist())
            elif uploaded_tags.name.endswith(".csv"):
                import pandas as pd
                df = pd.read_csv(uploaded_tags)
                mandatory_tags_input = "\n".join(df.iloc[:, 0].dropna().astype(str).tolist())
            else:
                mandatory_tags_input = uploaded_tags.read().decode("utf-8", errors="replace")
            st.success("Mandatory tags loaded.")
        except Exception as e:
            st.error(f"Failed to read tags file: {e}")

else:
    tags_sheet_url = st.text_input(
        "Google Sheet URL for mandatory tags",
        placeholder="https://docs.google.com/spreadsheets/d/...",
        help="Paste a Google Sheet link. First column will be used as tag names.",
        key="tags_sheet_url",
    )
    if tags_sheet_url:
        try:
            import pandas as pd
            if "/edit" in tags_sheet_url:
                csv_url = tags_sheet_url.split("/edit")[0] + "/export?format=csv"
            elif "/pubhtml" in tags_sheet_url:
                csv_url = tags_sheet_url.split("/pubhtml")[0] + "/export?format=csv"
            else:
                csv_url = tags_sheet_url.rstrip("/") + "/export?format=csv"
            with st.spinner("Fetching Google Sheet..."):
                df = pd.read_csv(csv_url)
                mandatory_tags_input = "\n".join(df.iloc[:, 0].dropna().astype(str).tolist())
            st.success("Mandatory tags loaded from Google Sheet.")
        except Exception as e:
            st.error(f"Failed to fetch Google Sheet: {e}")

mandatory_tags = [t.strip() for t in mandatory_tags_input.splitlines() if t.strip()] if mandatory_tags_input else []

# Clear review state if task number changed
if task_number != st.session_state.get("last_task_number", ""):
    for key in ["last_review_result", "last_review_colored", "last_task_number", "last_creator_unixname", "last_creator_name"]:
        st.session_state.pop(key, None)


def colorize_result(result):
    """Apply color coding to review result. Converts to pure HTML."""
    # Force newline before EVERY status emoji — unconditionally
    result = re.sub(r'(🟢)', r'\n- 🟢', result)
    result = re.sub(r'(🟡)', r'\n- 🟡', result)
    result = re.sub(r'(🔴)', r'\n- 🔴', result)
    # Force newline before numbered suggestions
    result = re.sub(r'(\d+\.\s*💡)', r'\n\1', result)
    # Force newline before headings
    result = re.sub(r'(#{2,3}\s)', r'\n\1', result)
    # Force newline before score lines
    result = re.sub(r'(Overall completeness score:)', r'\n\1', result)
    # Clean up: remove duplicate dashes like "- - 🟢" → "- 🟢"
    result = re.sub(r'-\s*-\s*(🟢|🟡|🔴)', r'- \1', result)

    # Build HTML line by line
    lines = result.split('\n')
    html_parts = []
    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Convert markdown bold **text** to <strong>
        line = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line)
        # Convert markdown code `text` to <code>
        line = re.sub(r'`(.+?)`', r'<code>\1</code>', line)

        # Headings
        if line.startswith('### '):
            html_parts.append(f'<h3>{line[4:]}</h3>')
        elif line.startswith('## '):
            html_parts.append(f'<h2>{line[3:]}</h2>')
        # Checklist bullet items — match on emoji anywhere in line
        elif '🟢' in line:
            content = re.sub(r'^-\s*', '', line)
            content = re.sub(r'🟢\s*<strong>PRESENT</strong>', '<span style="color:#198754;font-weight:bold;">🟢 PRESENT</span>', content)
            content = re.sub(r'🟢\s*PRESENT\*\*', '<span style="color:#198754;font-weight:bold;">🟢 PRESENT</span>', content)
            html_parts.append(f'<div style="padding:4px 0 4px 20px;">• {content}</div>')
        elif '🟡' in line:
            content = re.sub(r'^-\s*', '', line)
            content = re.sub(r'🟡\s*<strong>PARTIALLY PRESENT</strong>', '<span style="color:#d4930d;font-weight:bold;">🟡 PARTIALLY PRESENT</span>', content)
            content = re.sub(r'🟡\s*PARTIALLY PRESENT\*\*', '<span style="color:#d4930d;font-weight:bold;">🟡 PARTIALLY PRESENT</span>', content)
            html_parts.append(f'<div style="padding:4px 0 4px 20px;">• {content}</div>')
        elif '🔴' in line:
            content = re.sub(r'^-\s*', '', line)
            content = re.sub(r'🔴\s*<strong>MISSING</strong>', '<span style="color:#dc3545;font-weight:bold;">🔴 MISSING</span>', content)
            content = re.sub(r'🔴\s*MISSING\*\*', '<span style="color:#dc3545;font-weight:bold;">🔴 MISSING</span>', content)
            html_parts.append(f'<div style="padding:4px 0 4px 20px;">• {content}</div>')
        # Numbered suggestion items
        elif re.match(r'^\d+\.\s*💡', line):
            line = re.sub(r'💡\s*<strong>SUGGESTION</strong>', '<span style="color:#0d6efd;font-weight:bold;">💡 SUGGESTION</span>', line)
            line = re.sub(r'💡\s*SUGGESTION\*\*', '<span style="color:#0d6efd;font-weight:bold;">💡 SUGGESTION</span>', line)
            html_parts.append(f'<div style="padding:4px 0 4px 20px;">{line}</div>')
        # Overall completeness score
        elif 'completeness score:' in line.lower() or line.startswith('Overall'):
            pct_match = re.search(r'\((\d+)%\)', line)
            if pct_match:
                pct = int(pct_match.group(1))
            else:
                nums = re.search(r'(\d+)/(\d+)', line)
                pct = int(int(nums.group(1)) / int(nums.group(2)) * 100) if nums and int(nums.group(2)) > 0 else 0
            color = "#198754" if pct >= 80 else "#d4930d" if pct >= 50 else "#dc3545"
            html_parts.append(f'<div style="color:{color};font-weight:bold;font-size:1.15em;margin:1em 0;">{line}</div>')
        # Regular paragraph
        else:
            html_parts.append(f'<p>{line}</p>')

    return '\n'.join(html_parts)


if st.button("Review Task", type="primary", use_container_width=True):
    if task_is_closed:
        st.error(f"Task {task_number} is **Closed**. Cannot review a closed task.")
    elif not api_key:
        st.warning("Please enter your API key in the sidebar.")
    elif not task_number or not current_title:
        st.warning("Please enter both a task number and title.")
    else:
        with st.spinner("Reviewing task..."):
            try:
                mtr = check_mandatory_tags(mandatory_tags, fetched_tags) if mandatory_tags else None
                result = CALL_FUNCTIONS[provider](api_key, task_number, current_title, description, log_summary, checklist_text, fetched_tags, mtr)
                st.session_state["last_review_result"] = result
                st.session_state["last_review_colored"] = colorize_result(result)
                st.session_state["last_task_number"] = task_number
                st.session_state["last_creator_unixname"] = creator_unixname
                st.session_state["last_creator_name"] = creator_name
            except Exception as e:
                st.error(f"Error: {e}")

# Display review result from session state
if st.session_state.get("last_review_colored") and st.session_state.get("last_task_number") == task_number:
    st.divider()
    st.subheader(f"Review for {st.session_state['last_task_number']}")
    st.markdown(st.session_state["last_review_colored"], unsafe_allow_html=True)

# Notify creator button
if st.session_state.get("last_review_result") and st.session_state.get("last_creator_unixname") and st.session_state.get("last_task_number") == task_number:
    st.divider()
    notify_creator = st.session_state.get("last_creator_name") or st.session_state["last_creator_unixname"]
    st.markdown('<style>div[data-testid="stButton"]:last-of-type button {background-color: #198754 !important; color: white !important; border: none !important; padding: 0.5rem 1rem !important; font-size: 1rem !important; font-weight: 600 !important; border-radius: 0.5rem !important;}</style>', unsafe_allow_html=True)
    if st.button(f"Notify {notify_creator} on Google Chat", type="primary", use_container_width=True):
        review = st.session_state["last_review_result"]
        gchat_msg = f"Hi! Your task {task_number} has been reviewed by DefectLens.\n\n{review}"
        with st.spinner("Sending Google Chat message..."):
            success, msg = send_gchat_message(
                st.session_state["last_creator_unixname"],
                gchat_msg,
            )
        if success:
            st.success(f"Notified {notify_creator} on Google Chat!")
        else:
            st.error(f"Failed to notify: {msg}")

st.divider()
st.caption("DefectLens — Powered by MetaGen & Llama")
st.caption("Oncall: Vasu Gautam (vgautam) — please connect in case of any issues/suggestions")
