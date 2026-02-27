#!/usr/bin/env python3
"""
generate_prompts.py — Render the master prompt template for each state.

Usage:
    python scripts/generate_prompts.py              # generate all states
    python scripts/generate_prompts.py --state CA   # one state only
    python scripts/generate_prompts.py --overwrite  # overwrite existing prompts

Output: prompts/{state_folder}_prompt.txt
"""

import argparse
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATES_FILE = os.path.join(PROJECT_ROOT, "states.json")
TEMPLATE_FILE = os.path.join(PROJECT_ROOT, "templates", "prompt_template.txt")
PROMPTS_DIR = os.path.join(PROJECT_ROOT, "prompts")

USDA_FALLBACK_URL = "https://www.fns.usda.gov/snap/state-directory"

FALLBACK_NOTE = (
    "\nNOTE: No direct state SNAP URL is recorded for {STATE_NAME}. "
    "The START URL above is the USDA SNAP State Directory. "
    "Your first task is to find and click the {STATE_NAME} link on that page, "
    "then proceed with data collection from the state's own website.\n"
)


def load_states():
    with open(STATES_FILE) as f:
        return json.load(f)["states"]


def load_template():
    if not os.path.exists(TEMPLATE_FILE):
        print(f"ERROR: Template not found at {TEMPLATE_FILE}")
        sys.exit(1)
    with open(TEMPLATE_FILE) as f:
        return f.read()


def render_prompt(template, state):
    snap_url = state.get("snap_url", "").strip()
    state_name = state["name"]

    if not snap_url:
        snap_url = USDA_FALLBACK_URL
        extra_note = FALLBACK_NOTE.format(STATE_NAME=state_name)
    else:
        extra_note = ""

    # Add county note if applicable
    county_note = ""
    if state.get("county_administered"):
        county_note = (
            f"\nNOTE: {state_name} administers SNAP at the county level. "
            "The state website provides general policy information. "
            "Note any county-level variation and mention it in ATLAS NOTES.\n"
        )

    # Add login note if applicable
    login_note = ""
    if state.get("requires_login") and state.get("login_notes"):
        login_note = f"\nNOTE: {state['login_notes']}\n"

    prompt = template.replace("{STATE_NAME}", state_name)
    prompt = prompt.replace("{SNAP_URL}", snap_url)

    # Insert extra notes after BROWSING INSTRUCTIONS header if present
    if extra_note or county_note or login_note:
        notes_block = "\n---\n\nADDITIONAL CONTEXT FOR THIS STATE\n" + extra_note + county_note + login_note
        # Insert before DATA TO COLLECT section
        prompt = prompt.replace("\n---\n\nDATA TO COLLECT", notes_block + "\n---\n\nDATA TO COLLECT", 1)

    return prompt


def main():
    parser = argparse.ArgumentParser(description="Generate per-state Atlas prompts.")
    parser.add_argument("--state", metavar="ABBREV", help="Generate for one state only (e.g. CA)")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing prompt files")
    args = parser.parse_args()

    os.makedirs(PROMPTS_DIR, exist_ok=True)

    states = load_states()
    template = load_template()

    if args.state:
        states = [s for s in states if s["abbreviation"].upper() == args.state.upper()]
        if not states:
            print(f"ERROR: No state found with abbreviation '{args.state}'")
            sys.exit(1)

    generated = 0
    skipped = 0

    for state in states:
        folder = state["folder_name"]
        out_path = os.path.join(PROMPTS_DIR, f"{folder}_prompt.txt")

        if os.path.exists(out_path) and not args.overwrite:
            skipped += 1
            continue

        prompt = render_prompt(template, state)

        with open(out_path, "w") as f:
            f.write(prompt)

        print(f"  Generated: prompts/{folder}_prompt.txt")
        generated += 1

    print(f"\nDone. {generated} prompts generated, {skipped} skipped (use --overwrite to regenerate).")
    if generated > 0:
        print(f"\nNext step: open a prompt file in prompts/, paste it into ChatGPT Atlas,")
        print(f"then save the output to data/{{state}}/agent_output.md")


if __name__ == "__main__":
    main()
