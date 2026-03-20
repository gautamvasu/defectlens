# Bug Title Agent

A CLI tool that suggests better bug titles using Claude AI. Give it a task number and a vague bug title, and it returns clear, concise, and descriptive alternatives.

## Setup

1. **Clone the repo and create a virtual environment:**
   ```bash
   cd bug_title_agent
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Add your API key:**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and add your Anthropic API key (get one at https://console.anthropic.com/).

## Usage

**Single title:**
```bash
source venv/bin/activate
python3 bug_title_agent.py "T12345" "login not working"
```

**Interactive mode (process multiple titles):**
```bash
source venv/bin/activate
python3 bug_title_agent.py
```

## Example

```
$ python3 bug_title_agent.py "T12345" "login not working"

============================================================
  Task: T12345
  Current Title: login not working
============================================================

Generating better titles...

1. "Authentication fails with blank error on login form submission"
2. "Users unable to sign in — credentials rejected without error message"
3. "Login page returns no response after entering valid credentials"
```
