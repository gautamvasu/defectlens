#!/usr/bin/env python3
"""Bug Title Agent - Suggests better bug titles given a task number and current title."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv(Path(__file__).parent / ".env")
client = Anthropic()

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


def suggest_titles(task_number: str, current_title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  Task: {task_number}")
    print(f"  Current Title: {current_title}")
    print(f"{'='*60}\n")
    print("Generating better titles...\n")

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Task Number: {task_number}\nCurrent Bug Title: \"{current_title}\"\n\nPlease suggest better titles.",
            }
        ],
    )

    print(message.content[0].text)
    print()


def interactive_mode():
    print("\n" + "=" * 60)
    print("  Bug Title Improvement Agent")
    print("  Type 'quit' or 'q' to exit")
    print("=" * 60)

    while True:
        print()
        task_number = input("Enter task number: ").strip()
        if task_number.lower() in ("quit", "q"):
            print("Goodbye!")
            break

        current_title = input("Enter current bug title: ").strip()
        if current_title.lower() in ("quit", "q"):
            print("Goodbye!")
            break

        if not task_number or not current_title:
            print("Both task number and title are required. Try again.")
            continue

        suggest_titles(task_number, current_title)


def main():
    if len(sys.argv) == 3:
        suggest_titles(sys.argv[1], sys.argv[2])
    elif len(sys.argv) == 1:
        interactive_mode()
    else:
        print("Usage:")
        print(f"  {sys.argv[0]} <task_number> <current_title>")
        print(f"  {sys.argv[0]}  (interactive mode)")
        sys.exit(1)


if __name__ == "__main__":
    main()
