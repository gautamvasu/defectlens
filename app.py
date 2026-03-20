import os
import subprocess
import json
import streamlit as st
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

SYSTEM_PROMPT = """You are a Bug Title Improvement Agent. Your job is to take a bug's current title and description, and suggest better title alternatives.

A good bug title should be:
- Clear: Anyone reading it should immediately understand the issue
- Concise: Short enough to scan quickly (ideally under 80 characters)
- Descriptive: Includes the WHAT (component/feature), the WHERE (context), and the problem
- Action-oriented: Describes the symptom or broken behavior, not the fix
- Specific: Avoids vague words like "issue", "problem", "bug", "broken", "not working"

Common patterns for good titles:
- "[Component] Specific symptom when doing X"
- "Feature: unexpected behavior under condition"
- "Action fails/crashes/returns error when condition"

For each input, provide:
1. Analysis of what's wrong with the current title
2. 3 improved title suggestions ranked from best to good (use details from the description to make them accurate and specific)
3. A brief explanation of why the top suggestion is best

Keep your response focused and practical."""

PROVIDERS = {
    "Groq (Free)": {
        "key_env": "GROQ_API_KEY",
        "placeholder": "gsk_...",
        "help": "Get a free key at https://console.groq.com/keys (no credit card needed)",
    },
    "Gemini (Free)": {
        "key_env": "GEMINI_API_KEY",
        "placeholder": "AIza...",
        "help": "Get a free key at https://aistudio.google.com/apikey",
    },
    "Claude (Paid)": {
        "key_env": "ANTHROPIC_API_KEY",
        "placeholder": "sk-ant-api03-...",
        "help": "Get your key at https://console.anthropic.com/settings/keys",
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
    """Fetch task title and description from Meta Phabricator using jf CLI."""
    number = task_number.strip().lstrip("Tt")
    try:
        result = subprocess.run(
            [
                "jf", "graphql", "--query",
                f'{{ task(number: {number}) {{ name, task_description {{ text }} }} }}',
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
                description = ""
                task_desc = task.get("task_description")
                if task_desc:
                    description = task_desc.get("text", "")
                return name, description
        return None, None
    except Exception:
        return None, None


def build_user_prompt(task_number, current_title, description):
    prompt = f'Task Number: {task_number}\nCurrent Bug Title: "{current_title}"'
    if description:
        prompt += f"\n\nTask Description:\n{description}"
    prompt += "\n\nPlease suggest better titles based on the title and description above."
    return prompt


def call_groq(api_key, task_number, current_title, description):
    from groq import Groq

    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=1024,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(task_number, current_title, description)},
        ],
    )
    return response.choices[0].message.content


def call_gemini(api_key, task_number, current_title, description):
    import google.generativeai as genai

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")
    prompt = f'{SYSTEM_PROMPT}\n\n{build_user_prompt(task_number, current_title, description)}'
    response = model.generate_content(prompt)
    return response.text


def call_claude(api_key, task_number, current_title, description):
    from anthropic import Anthropic

    client = Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": build_user_prompt(task_number, current_title, description)},
        ],
    )
    return message.content[0].text


CALL_FUNCTIONS = {
    "Groq (Free)": call_groq,
    "Gemini (Free)": call_gemini,
    "Claude (Paid)": call_claude,
}

st.set_page_config(page_title="Bug Title Agent", page_icon="🐛", layout="centered")

st.title("🐛 Bug Title Agent")
st.markdown("Enter a task number to auto-fetch the title and description, or type manually.")

st.divider()

with st.sidebar:
    st.header("Settings")
    provider = st.selectbox("AI Provider", list(PROVIDERS.keys()))
    provider_config = PROVIDERS[provider]
    default_key = get_default_key(provider_config["key_env"])

    if default_key:
        st.success("API key configured by admin.")
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
if task_number:
    with st.spinner("Fetching task details..."):
        fetched_title, fetched_description = fetch_task_details(task_number)
    if fetched_title:
        st.success(f"Fetched title: **{fetched_title}**")
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

if st.button("Suggest Better Titles", type="primary", use_container_width=True):
    if not api_key:
        st.warning("Please enter your API key in the sidebar.")
    elif not task_number or not current_title:
        st.warning("Please enter both a task number and title.")
    else:
        with st.spinner("Generating better titles..."):
            try:
                result = CALL_FUNCTIONS[provider](api_key, task_number, current_title, description)
                st.divider()
                st.subheader(f"Suggestions for {task_number}")
                st.markdown(result)
            except Exception as e:
                st.error(f"Error: {e}")

st.divider()
st.caption("Powered by Groq, Google Gemini & Claude AI")
