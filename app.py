import os
import streamlit as st
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

SYSTEM_PROMPT = """You are a Bug Title Improvement Agent. Your job is to take a bug's current title and suggest better alternatives.

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
2. 3 improved title suggestions ranked from best to good
3. A brief explanation of why the top suggestion is best

Keep your response focused and practical."""

PROVIDERS = {
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


def call_gemini(api_key, task_number, current_title):
    import google.generativeai as genai

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")
    prompt = f'{SYSTEM_PROMPT}\n\nTask Number: {task_number}\nCurrent Bug Title: "{current_title}"\n\nPlease suggest better titles.'
    response = model.generate_content(prompt)
    return response.text


def call_claude(api_key, task_number, current_title):
    from anthropic import Anthropic

    client = Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f'Task Number: {task_number}\nCurrent Bug Title: "{current_title}"\n\nPlease suggest better titles.',
            }
        ],
    )
    return message.content[0].text


st.set_page_config(page_title="Bug Title Agent", page_icon="🐛", layout="centered")

st.title("🐛 Bug Title Agent")
st.markdown("Enter a task number and current bug title to get better title suggestions.")

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

col1, col2 = st.columns([1, 3])
with col1:
    task_number = st.text_input("Task Number", placeholder="T12345")
with col2:
    current_title = st.text_input("Current Bug Title", placeholder="login not working")

if st.button("Suggest Better Titles", type="primary", use_container_width=True):
    if not api_key:
        st.warning("Please enter your API key in the sidebar.")
    elif not task_number or not current_title:
        st.warning("Please enter both a task number and current title.")
    else:
        with st.spinner("Generating better titles..."):
            try:
                if provider == "Gemini (Free)":
                    result = call_gemini(api_key, task_number, current_title)
                else:
                    result = call_claude(api_key, task_number, current_title)

                st.divider()
                st.subheader(f"Suggestions for {task_number}")
                st.markdown(result)
            except Exception as e:
                st.error(f"Error: {e}")

st.divider()
st.caption("Powered by Claude AI & Google Gemini")
