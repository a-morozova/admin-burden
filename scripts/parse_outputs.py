#!/usr/bin/env python3
"""
parse_outputs.py — Parse agent_output.md files into structured metadata.json.

Run this after saving each agent_output.md to validate the parse and
produce structured JSON for later comparative analysis.

Usage:
    python scripts/parse_outputs.py              # parse all states
    python scripts/parse_outputs.py --state CA   # one state only
    python scripts/parse_outputs.py --strict     # exit with error code if any field fails
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATES_FILE = os.path.join(PROJECT_ROOT, "states.json")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")
PARSE_LOG = os.path.join(LOGS_DIR, "parse_log.json")

PLACEHOLDER_MARKER = "Not yet collected."
NOT_SPECIFIED = "not specified on website"


def load_states():
    with open(STATES_FILE) as f:
        return json.load(f)["states"]


def load_log():
    if os.path.exists(PARSE_LOG):
        with open(PARSE_LOG) as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []
    return []


def save_log(log):
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(PARSE_LOG, "w") as f:
        json.dump(log, f, indent=2)


def normalize(value):
    """Normalize a field value: strip whitespace, return None if not-specified."""
    if value is None:
        return None
    v = value.strip()
    if v.lower() in (NOT_SPECIFIED, "n/a", "none", "unclear", ""):
        return None
    return v


def to_bool(value):
    """Convert Yes/No/Unclear strings to True/False/None."""
    if value is None:
        return None
    v = value.strip().lower()
    if v in ("yes", "true", "1"):
        return True
    if v in ("no", "false", "0"):
        return False
    return None  # Unclear or not specified


def split_sections(text):
    """Split document into sections by ## headers. Returns dict of section_name -> content."""
    sections = {}
    current_key = "_preamble"
    current_lines = []

    for line in text.splitlines():
        m = re.match(r'^##\s+(.+)', line)
        if m:
            sections[current_key] = "\n".join(current_lines)
            current_key = m.group(1).strip().upper()
            current_lines = []
        else:
            current_lines.append(line)

    sections[current_key] = "\n".join(current_lines)
    return sections


def get_subsection(section_text, subsection_name):
    """Extract content under a ### subsection."""
    pattern = re.compile(
        r'###\s+' + re.escape(subsection_name) + r'\s*\n(.*?)(?=###|\Z)',
        re.IGNORECASE | re.DOTALL
    )
    m = pattern.search(section_text)
    return m.group(1).strip() if m else ""


def extract_field(text, field_name):
    """Extract value from '**Field Name:** value' pattern."""
    pattern = re.compile(
        r'\*\*' + re.escape(field_name) + r':\*\*\s*(.+)',
        re.IGNORECASE
    )
    m = pattern.search(text)
    return normalize(m.group(1)) if m else None


def extract_list_items(text):
    """Extract bullet list items (lines starting with '-' or '*')."""
    items = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("- ") or line.startswith("* "):
            item = line[2:].strip()
            if item and item.lower() != NOT_SPECIFIED:
                items.append(item)
    return items


def extract_numbered_steps(text):
    """Extract numbered list items."""
    steps = []
    for line in text.splitlines():
        m = re.match(r'^\d+\.\s+(.+)', line.strip())
        if m:
            step = m.group(1).strip()
            if step.lower() != NOT_SPECIFIED:
                steps.append(step)
    return steps


def extract_form_table(section_text):
    """Parse markdown pipe table from FORMS section."""
    forms = []
    lines = [l.strip() for l in section_text.splitlines() if l.strip().startswith("|")]

    # Skip header and separator rows
    data_rows = []
    for line in lines:
        cells = [c.strip() for c in line.strip("|").split("|")]
        # Skip separator row (---)
        if all(re.match(r'^[-:]+$', c) for c in cells if c):
            continue
        # Skip header row
        if cells and cells[0].lower() in ("form name", "form name "):
            continue
        if len(cells) >= 6:
            data_rows.append(cells)

    for row in data_rows:
        if len(row) < 6:
            continue
        name, form_num, desc, lang, url, file_type = row[:6]
        # Skip rows that are clearly not data
        if name.lower() in ("", "not specified on website"):
            continue
        forms.append({
            "name": normalize(name),
            "form_number": normalize(form_num),
            "description": normalize(desc),
            "language": normalize(lang),
            "url": normalize(url),
            "file_type": normalize(file_type)
        })

    return forms


def count_assets(state_folder):
    """Count downloaded files in pages/ and forms/ subdirectories."""
    pages_dir = os.path.join(DATA_DIR, state_folder, "pages")
    forms_dir = os.path.join(DATA_DIR, state_folder, "forms")

    pages_downloaded = len(os.listdir(pages_dir)) if os.path.isdir(pages_dir) else 0
    forms_downloaded = len(os.listdir(forms_dir)) if os.path.isdir(forms_dir) else 0
    return pages_downloaded, forms_downloaded


def parse_urls_section(section_text):
    """Count referenced pages and downloads."""
    pages_sub = get_subsection(section_text, "Pages Visited")
    downloads_sub = get_subsection(section_text, "Downloadable Assets")

    page_urls = re.findall(r'https?://\S+', pages_sub)
    download_urls = re.findall(r'https?://\S+', downloads_sub)

    return len(page_urls), len(download_urls)


def parse_state(state, strict=False):
    folder = state["folder_name"]
    md_path = os.path.join(DATA_DIR, folder, "agent_output.md")
    meta_path = os.path.join(DATA_DIR, folder, "metadata.json")

    warnings = []
    errors = []

    if not os.path.exists(md_path):
        return None, ["agent_output.md not found"], []

    with open(md_path) as f:
        content = f.read()

    if PLACEHOLDER_MARKER in content:
        return None, [], ["agent_output.md is a placeholder — not yet collected"]

    sections = split_sections(content)

    # --- Preamble ---
    preamble = sections.get("_preamble", "")
    collected_date = extract_field(preamble, "Collected")
    source_url = extract_field(preamble, "Source URL")
    if not collected_date:
        warnings.append("Collected date not found in preamble")
    if not source_url:
        warnings.append("Source URL not found in preamble")

    # --- Application Process ---
    app_section = sections.get("APPLICATION PROCESS", "")
    if not app_section:
        errors.append("APPLICATION PROCESS section missing")

    online_available = to_bool(extract_field(app_section, "Online Application Available"))
    online_url = extract_field(app_section, "Online Application URL")
    online_doc = to_bool(extract_field(app_section, "Online Document Submission Available"))
    online_doc_notes = extract_field(app_section, "Online Document Submission Notes")

    steps_sub = get_subsection(app_section, "Steps")
    steps = extract_numbered_steps(steps_sub)
    if not steps:
        # Try plain numbered from the full section
        steps = extract_numbered_steps(app_section)
    if not steps:
        warnings.append("No numbered steps found in APPLICATION PROCESS")

    # --- Required Documents ---
    docs_section = sections.get("REQUIRED DOCUMENTS", "")
    if not docs_section:
        errors.append("REQUIRED DOCUMENTS section missing")
    doc_items = extract_list_items(docs_section)
    docs_specified = len(doc_items) > 0

    # --- Interview Requirements ---
    interview_section = sections.get("INTERVIEW REQUIREMENTS", "")
    if not interview_section:
        errors.append("INTERVIEW REQUIREMENTS section missing")

    interview_required = to_bool(extract_field(interview_section, "Interview Required"))
    interview_type_raw = extract_field(interview_section, "Interview Type Options")
    interview_types = []
    if interview_type_raw:
        for t in re.split(r'[,/]', interview_type_raw):
            t = t.strip().lower()
            if t in ("phone", "in-person", "in person", "both"):
                interview_types.append(t.replace("in person", "in-person"))

    sched_sub = get_subsection(interview_section, "Scheduling")
    how_to_schedule = extract_field(sched_sub, "How to Schedule")
    scheduling_url = extract_field(sched_sub, "Scheduling URL")

    timing_sub = get_subsection(interview_section, "Timing and Hours")
    when_conducted = extract_field(timing_sub, "When Interviews Are Conducted")
    evening_weekend = to_bool(extract_field(timing_sub, "Evening or Weekend Hours Available"))
    hours_notes = extract_field(timing_sub, "Hours Notes")

    reminder_sub = get_subsection(interview_section, "Reminder Process")
    reminders_sent = to_bool(extract_field(reminder_sub, "Reminders Sent"))
    reminder_method = extract_field(reminder_sub, "Reminder Method")

    reschedule_sub = get_subsection(interview_section, "Rescheduling")
    reschedule_available = to_bool(extract_field(reschedule_sub, "Reschedule Available"))
    reschedule_method = extract_field(reschedule_sub, "How to Reschedule")
    reschedule_url = extract_field(reschedule_sub, "Reschedule URL")

    penalty_sub = get_subsection(interview_section, "Missed Interview Penalties")
    penalty = extract_field(penalty_sub, "Penalty for Missing Interview")
    good_cause = to_bool(extract_field(penalty_sub, "Good Cause Exceptions"))
    good_cause_notes = extract_field(penalty_sub, "Good Cause Notes")

    # --- Forms ---
    forms_section = sections.get("FORMS", "")
    if not forms_section:
        errors.append("FORMS section missing")

    total_forms_raw = extract_field(forms_section, "Total Forms Found")
    total_forms = None
    if total_forms_raw:
        m = re.search(r'\d+', total_forms_raw)
        total_forms = int(m.group()) if m else None

    form_list = extract_form_table(forms_section)
    if total_forms is None and form_list:
        total_forms = len(form_list)
        warnings.append("Total Forms Found field missing; inferred from table row count")

    # --- Language Access ---
    lang_section = sections.get("LANGUAGE ACCESS", "")
    if not lang_section:
        errors.append("LANGUAGE ACCESS section missing")

    website_langs_raw = extract_field(lang_section, "Languages Supported on Website")
    form_langs_raw = extract_field(lang_section, "Languages Supported on Forms")
    translation_method = extract_field(lang_section, "Translation Method")
    lang_notes = extract_field(lang_section, "Language Access Notes")

    def split_langs(raw):
        if not raw:
            return None
        if raw.lower() in ("english only",):
            return ["English"]
        return [l.strip() for l in re.split(r'[,;]', raw) if l.strip()]

    website_langs = split_langs(website_langs_raw)
    form_langs = split_langs(form_langs_raw)

    # --- Complexity ---
    complexity_section = sections.get("COMPLEXITY ASSESSMENT", "")
    if not complexity_section:
        warnings.append("COMPLEXITY ASSESSMENT section missing")

    steps_count_raw = extract_field(complexity_section, "Estimated Number of Steps")
    steps_count = None
    if steps_count_raw:
        m = re.search(r'\d+', steps_count_raw)
        steps_count = int(m.group()) if m else None
    if steps_count is None and steps:
        steps_count = len(steps)

    forms_count_raw = extract_field(complexity_section, "Estimated Total Forms to Complete")
    forms_count = None
    if forms_count_raw:
        m = re.search(r'\d+', forms_count_raw)
        forms_count = int(m.group()) if m else None

    reading_level = extract_field(complexity_section, "Estimated Reading Level")
    reading_notes = extract_field(complexity_section, "Reading Level Notes")

    # --- URLs Referenced ---
    urls_section = sections.get("URLS REFERENCED", "")
    pages_ref, downloads_ref = parse_urls_section(urls_section) if urls_section else (0, 0)

    # --- Asset counts on disk ---
    pages_dl, forms_dl = count_assets(folder)

    # --- Build metadata ---
    metadata = {
        "state": state["name"],
        "abbreviation": state["abbreviation"],
        "collected_date": collected_date,
        "source_url": source_url,
        "application": {
            "online_available": online_available,
            "online_url": online_url,
            "online_doc_submission": online_doc,
            "online_doc_submission_notes": online_doc_notes,
            "steps_count": steps_count,
            "steps": steps
        },
        "documents": {
            "specified_on_website": docs_specified,
            "document_list": doc_items
        },
        "interview": {
            "required": interview_required,
            "type_options": interview_types or None,
            "scheduling_who_initiates": how_to_schedule,
            "scheduling_url": scheduling_url,
            "hours_specified": when_conducted is not None,
            "hours_description": when_conducted,
            "evening_weekend_hours": evening_weekend,
            "hours_notes": hours_notes,
            "reminders_sent": reminders_sent,
            "reminder_method": reminder_method,
            "reschedule_available": reschedule_available,
            "reschedule_method": reschedule_method,
            "reschedule_url": reschedule_url,
            "missed_interview_penalty": penalty,
            "good_cause_exceptions": good_cause,
            "good_cause_notes": good_cause_notes
        },
        "forms": {
            "total_count": total_forms,
            "form_list": form_list
        },
        "language_access": {
            "website_languages": website_langs,
            "form_languages": form_langs,
            "translation_method": translation_method,
            "notes": lang_notes
        },
        "complexity": {
            "steps_count": steps_count,
            "forms_to_complete": forms_count,
            "reading_level": reading_level,
            "reading_level_notes": reading_notes
        },
        "assets": {
            "pages_referenced": pages_ref,
            "downloads_referenced": downloads_ref,
            "pages_downloaded": pages_dl,
            "forms_downloaded": forms_dl
        },
        "parse_status": {
            "parsed": len(errors) == 0,
            "parse_timestamp": datetime.now(timezone.utc).isoformat(),
            "warnings": warnings,
            "errors": errors
        }
    }

    # Write metadata
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)

    return metadata, warnings, errors


def main():
    parser = argparse.ArgumentParser(description="Parse agent_output.md into metadata.json.")
    parser.add_argument("--state", metavar="ABBREV", help="Parse one state only (e.g. CA)")
    parser.add_argument("--strict", action="store_true", help="Exit with error code if any parse error")
    args = parser.parse_args()

    states = load_states()
    if args.state:
        states = [s for s in states if s["abbreviation"].upper() == args.state.upper()]
        if not states:
            print(f"ERROR: No state found with abbreviation '{args.state}'")
            sys.exit(1)

    print("=== parse_outputs ===\n")

    log = load_log()
    total_errors = 0
    total_warnings = 0
    processed = 0
    skipped = 0

    for state in states:
        meta, warnings, errors = parse_state(state, strict=args.strict)

        if meta is None and not errors:
            skipped += 1
            continue
        if meta is None:
            # Placeholder or not found
            reason = errors[0] if errors else "unknown"
            print(f"  [{state['abbreviation']}] Skipping: {reason}")
            skipped += 1
            continue

        processed += 1
        total_warnings += len(warnings)
        total_errors += len(errors)

        status_icon = "OK" if not errors else "ERRORS"
        warn_str = f", {len(warnings)} warnings" if warnings else ""
        err_str = f", {len(errors)} errors" if errors else ""
        print(f"  [{state['abbreviation']}] {state['name']}: {status_icon}{warn_str}{err_str}")

        for w in warnings:
            print(f"    WARN: {w}")
        for e in errors:
            print(f"    ERROR: {e}")

        # Append to parse log
        log.append({
            "state": state["name"],
            "abbreviation": state["abbreviation"],
            "parse_timestamp": datetime.now(timezone.utc).isoformat(),
            "warnings": warnings,
            "errors": errors
        })

    save_log(log)

    print(f"\nDone. {processed} parsed, {skipped} skipped.")
    print(f"Total warnings: {total_warnings}, Total errors: {total_errors}")
    print(f"Log updated: {PARSE_LOG}")

    if args.strict and total_errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
