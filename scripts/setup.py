#!/usr/bin/env python3
"""
setup.py — Create the admin-burden folder structure for all 50+DC states.

Run this once before starting data collection:
    python scripts/setup.py

Safe to re-run: existing files/folders are never overwritten.
"""

import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATES_FILE = os.path.join(PROJECT_ROOT, "states.json")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
PROMPTS_DIR = os.path.join(PROJECT_ROOT, "prompts")
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")
ANALYSIS_DIR = os.path.join(PROJECT_ROOT, "analysis")

REQUIRED_FIELDS = [
    "name", "abbreviation", "folder_name", "snap_url",
    "snap_portal_url", "county_administered", "requires_login",
    "login_notes", "notes", "status", "last_collected", "known_issues"
]

PLACEHOLDER_AGENT_OUTPUT = """\
# Pending — {state_name}

Not yet collected. Paste ChatGPT Atlas output here after running the prompt for this state.
"""

SKELETON_METADATA = {
    "state": None,
    "abbreviation": None,
    "status": "pending",
    "parsed": False
}


def load_states():
    if not os.path.exists(STATES_FILE):
        print(f"ERROR: states.json not found at {STATES_FILE}")
        sys.exit(1)
    with open(STATES_FILE) as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"ERROR: states.json is malformed JSON: {e}")
            sys.exit(1)
    if "states" not in data or not isinstance(data["states"], list):
        print("ERROR: states.json must have a top-level 'states' array.")
        sys.exit(1)
    return data["states"]


def validate_state(state, idx):
    errors = []
    for field in REQUIRED_FIELDS:
        if field not in state:
            errors.append(f"Missing field: '{field}'")
    folder = state.get("folder_name", "")
    if " " in folder:
        errors.append(f"folder_name '{folder}' contains spaces (use underscores)")
    if folder and not folder.replace("_", "").isalnum():
        errors.append(f"folder_name '{folder}' contains special characters")
    url = state.get("snap_url", "")
    if url and not url.startswith("http"):
        errors.append(f"snap_url '{url}' does not look like a valid URL")
    if errors:
        name = state.get("name", f"entry #{idx}")
        for e in errors:
            print(f"  WARN [{name}]: {e}")
    return errors


def make_dir(path):
    os.makedirs(path, exist_ok=True)


def create_state_structure(state):
    folder = state["folder_name"]
    state_dir = os.path.join(DATA_DIR, folder)
    pages_dir = os.path.join(state_dir, "pages")
    forms_dir = os.path.join(state_dir, "forms")

    make_dir(state_dir)
    make_dir(pages_dir)
    make_dir(forms_dir)

    # Placeholder agent_output.md — only create if not already a real file
    output_path = os.path.join(state_dir, "agent_output.md")
    if not os.path.exists(output_path):
        with open(output_path, "w") as f:
            f.write(PLACEHOLDER_AGENT_OUTPUT.format(state_name=state["name"]))

    # Skeleton metadata.json
    meta_path = os.path.join(state_dir, "metadata.json")
    if not os.path.exists(meta_path):
        meta = dict(SKELETON_METADATA)
        meta["state"] = state["name"]
        meta["abbreviation"] = state["abbreviation"]
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)


def init_log_file(path, default):
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump(default, f, indent=2)


def main():
    print("=== admin-burden setup ===\n")

    states = load_states()

    # Validate all entries
    print(f"Validating {len(states)} state entries...")
    all_errors = []
    for i, state in enumerate(states):
        errs = validate_state(state, i)
        all_errors.extend(errs)

    expected_count = 51  # 50 states + DC
    if len(states) != expected_count:
        print(f"  WARN: Expected {expected_count} entries (50 states + DC), found {len(states)}")
    else:
        print(f"  OK: {len(states)} entries found")

    if all_errors:
        print(f"  {len(all_errors)} validation warning(s) — continuing anyway\n")
    else:
        print("  All entries valid\n")

    # Create top-level dirs
    for d in [DATA_DIR, PROMPTS_DIR, LOGS_DIR, ANALYSIS_DIR]:
        make_dir(d)

    # analysis/.gitkeep
    gitkeep = os.path.join(ANALYSIS_DIR, ".gitkeep")
    if not os.path.exists(gitkeep):
        open(gitkeep, "w").close()

    # Initialize log files
    init_log_file(os.path.join(LOGS_DIR, "download_log.json"), [])
    init_log_file(os.path.join(LOGS_DIR, "parse_log.json"), [])

    # Create per-state directories
    print("Creating state directories...")
    created = 0
    skipped = 0
    for state in states:
        folder = state["folder_name"]
        state_dir = os.path.join(DATA_DIR, folder)
        existed = os.path.isdir(state_dir)
        create_state_structure(state)
        if existed:
            skipped += 1
        else:
            created += 1
            print(f"  Created: data/{folder}/")

    print(f"\nDone. {created} new state directories created, {skipped} already existed.")
    print(f"Next step: run  python scripts/generate_prompts.py")


if __name__ == "__main__":
    main()
