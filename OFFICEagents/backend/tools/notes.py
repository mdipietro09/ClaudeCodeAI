"""Shared team notepad — persists to backend/workspace/notes.md.
The Boss can open that file directly too."""

import os
import time

WORKSPACE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "workspace")
NOTES = os.path.join(WORKSPACE, "notes.md")

TOOLS = [
    {
        "name": "save_note",
        "description": "Append a note to the shared team notepad (persists across sessions). "
                       "Sign it with your name. Use for findings, numbers, decisions worth keeping.",
        "parameters": {
            "type": "object",
            "properties": {
                "note": {"type": "string", "description": "the note text, e.g. 'Mave: TAM estimate ~$4B'"},
            },
            "required": ["note"],
        },
    },
    {
        "name": "read_notes",
        "description": "Read the shared team notepad (most recent notes).",
        "parameters": {"type": "object", "properties": {}},
    },
]


def run_save_note(args):
    note = str(args.get("note", "")).strip()
    if not note:
        return "Error: empty note"
    os.makedirs(WORKSPACE, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M")
    with open(NOTES, "a") as f:
        f.write("- [%s] %s\n" % (stamp, note))
    return "Saved."


def run_read_notes(args):
    try:
        with open(NOTES) as f:
            content = f.read()
    except FileNotFoundError:
        return "The notepad is empty."
    return content[-4000:] or "The notepad is empty."
