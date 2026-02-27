#!/usr/bin/env python3
"""
download_assets.py — Download HTML pages and forms referenced in agent_output.md.

Run this promptly after saving each agent_output.md — some state form URLs
use time-limited signed links that expire within hours.

Usage:
    python scripts/download_assets.py              # process all states
    python scripts/download_assets.py --state CA   # one state only
    python scripts/download_assets.py --dry-run    # preview without downloading
    python scripts/download_assets.py --delay 3   # seconds between requests (default: 2)
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATES_FILE = os.path.join(PROJECT_ROOT, "states.json")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")
DOWNLOAD_LOG = os.path.join(LOGS_DIR, "download_log.json")

MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_REDIRECTS = 5

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

FORM_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".odt", ".rtf"}

# Regex patterns for parsing agent_output.md
RE_DOWNLOADABLE = re.compile(r'-\s+(https?://\S+?):\s+(\S+?)\s+—\s+(.+)', re.IGNORECASE)
RE_PAGE = re.compile(r'-\s+(https?://\S+?):\s+(.+)', re.IGNORECASE)

PLACEHOLDER_MARKER = "Not yet collected."


def load_states():
    with open(STATES_FILE) as f:
        return json.load(f)["states"]


def load_log():
    if os.path.exists(DOWNLOAD_LOG):
        with open(DOWNLOAD_LOG) as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []
    return []


def save_log(log):
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(DOWNLOAD_LOG, "w") as f:
        json.dump(log, f, indent=2)


def is_placeholder(content):
    return PLACEHOLDER_MARKER in content


def parse_agent_output(md_path):
    with open(md_path) as f:
        content = f.read()

    if is_placeholder(content):
        return None, None

    downloads = []
    pages = []

    in_urls_section = False
    in_downloads = False
    in_pages = False

    for line in content.splitlines():
        stripped = line.strip()

        if re.match(r'^##\s+URLS REFERENCED', stripped, re.IGNORECASE):
            in_urls_section = True
            continue
        if in_urls_section and re.match(r'^##\s+', stripped):
            in_urls_section = False
            continue

        if in_urls_section:
            if re.match(r'^###\s+Downloadable Assets', stripped, re.IGNORECASE):
                in_downloads = True
                in_pages = False
                continue
            if re.match(r'^###\s+Pages Visited', stripped, re.IGNORECASE):
                in_pages = True
                in_downloads = False
                continue
            if re.match(r'^###', stripped):
                in_downloads = False
                in_pages = False
                continue

            if in_downloads:
                m = RE_DOWNLOADABLE.match(stripped)
                if m:
                    downloads.append({
                        "url": m.group(1),
                        "suggested_filename": m.group(2),
                        "description": m.group(3).strip()
                    })
            elif in_pages:
                m = RE_PAGE.match(stripped)
                if m:
                    pages.append({
                        "url": m.group(1),
                        "description": m.group(2).strip()
                    })

    return pages, downloads


def sanitize_filename(url, suggested, max_len=80):
    """Derive a safe filename from suggested name or URL."""
    # Prefer Content-Disposition, but we handle that at download time
    name = suggested or ""

    # If suggested looks like a real filename, use it
    if name and "." in name and not name.startswith("http"):
        name = os.path.basename(name.split("?")[0])
    else:
        # Derive from URL
        parsed = urllib.parse.urlparse(url)
        name = os.path.basename(parsed.path.rstrip("/")) or "page"
        if "." not in name:
            name += ".html"

    # Strip query string artifacts
    name = name.split("?")[0]

    # Replace unsafe chars
    name = re.sub(r'[^\w.\-]', '_', name)
    name = name[:max_len]
    return name or "download"


def get_destination(folder_name, filename):
    ext = os.path.splitext(filename)[1].lower()
    if ext in FORM_EXTENSIONS:
        return os.path.join(DATA_DIR, folder_name, "forms", filename)
    return os.path.join(DATA_DIR, folder_name, "pages", filename)


def download_url(url, dest_path, dry_run=False, delay=2):
    result = {
        "url": url,
        "dest": dest_path,
        "status": None,
        "bytes": None,
        "error": None,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    if dry_run:
        print(f"    [dry-run] Would download: {url}")
        print(f"              → {dest_path}")
        result["status"] = "dry-run"
        return result

    if os.path.exists(dest_path):
        result["status"] = "skipped (already exists)"
        return result

    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_USER_AGENT})

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            # Check Content-Disposition for a better filename
            cd = response.headers.get("Content-Disposition", "")
            cd_match = re.search(r'filename[^;=\n]*=(["\']?)([^"\'\n;]+)', cd)
            if cd_match:
                cd_filename = cd_match.group(2).strip()
                # Reroute to correct folder based on real filename
                dest_dir = os.path.dirname(dest_path)
                ext = os.path.splitext(cd_filename)[1].lower()
                if ext in FORM_EXTENSIONS:
                    dest_dir = dest_dir.replace("/pages", "/forms").replace("\\pages", "\\forms")
                else:
                    dest_dir = dest_dir.replace("/forms", "/pages").replace("\\forms", "\\pages")
                dest_path = os.path.join(dest_dir, sanitize_filename(url, cd_filename))
                result["dest"] = dest_path

            # Check file size
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_FILE_SIZE_BYTES:
                result["status"] = "skipped (>50MB)"
                result["error"] = f"Content-Length: {content_length} bytes"
                return result

            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            data = response.read(MAX_FILE_SIZE_BYTES + 1)
            if len(data) > MAX_FILE_SIZE_BYTES:
                result["status"] = "skipped (>50MB)"
                return result

            with open(dest_path, "wb") as f:
                f.write(data)

            result["status"] = "success"
            result["bytes"] = len(data)

    except urllib.error.HTTPError as e:
        if e.code == 429:
            print(f"    Rate limited (429). Waiting 30s...")
            time.sleep(30)
            try:
                with urllib.request.urlopen(req, timeout=30) as response:
                    data = response.read(MAX_FILE_SIZE_BYTES + 1)
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    with open(dest_path, "wb") as f:
                        f.write(data)
                    result["status"] = "success (after 429 retry)"
                    result["bytes"] = len(data)
            except Exception as retry_err:
                result["status"] = "error"
                result["error"] = f"429 retry failed: {retry_err}"
        else:
            result["status"] = "error"
            result["error"] = f"HTTP {e.code}: {e.reason}"

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    return result


def process_state(state, dry_run=False, delay=2):
    folder = state["folder_name"]
    md_path = os.path.join(DATA_DIR, folder, "agent_output.md")

    if not os.path.exists(md_path):
        return []

    pages, downloads = parse_agent_output(md_path)
    if pages is None and downloads is None:
        print(f"  [{state['abbreviation']}] Skipping — agent_output.md is a placeholder")
        return []

    print(f"  [{state['abbreviation']}] {state['name']}: {len(pages or [])} pages, {len(downloads or [])} downloadable assets")

    results = []
    timestamp = datetime.now(timezone.utc).isoformat()

    for asset in (downloads or []):
        filename = sanitize_filename(asset["url"], asset["suggested_filename"])
        dest = get_destination(folder, filename)
        print(f"    FORM/ASSET: {filename}")
        r = download_url(asset["url"], dest, dry_run=dry_run, delay=delay)
        r["type"] = "asset"
        r["description"] = asset["description"]
        results.append(r)
        if not dry_run and r["status"] == "success":
            time.sleep(delay)

    for page in (pages or []):
        filename = sanitize_filename(page["url"], None)
        if not filename.endswith(".html"):
            filename = filename.rstrip(".") + ".html"
        dest = os.path.join(DATA_DIR, folder, "pages", filename)
        print(f"    PAGE: {filename}")
        r = download_url(page["url"], dest, dry_run=dry_run, delay=delay)
        r["type"] = "page"
        r["description"] = page["description"]
        results.append(r)
        if not dry_run and r["status"] == "success":
            time.sleep(delay)

    success = sum(1 for r in results if "success" in (r.get("status") or ""))
    errors = sum(1 for r in results if r.get("status") == "error")
    skipped = sum(1 for r in results if "skipped" in (r.get("status") or ""))
    print(f"    → {success} downloaded, {skipped} skipped, {errors} errors")

    return [{
        "state": state["name"],
        "abbreviation": state["abbreviation"],
        "run_timestamp": timestamp,
        "assets": results
    }]


def main():
    parser = argparse.ArgumentParser(description="Download assets from agent_output.md files.")
    parser.add_argument("--state", metavar="ABBREV", help="Process one state only (e.g. CA)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without downloading")
    parser.add_argument("--delay", type=float, default=2.0, help="Seconds between requests (default: 2)")
    args = parser.parse_args()

    states = load_states()
    if args.state:
        states = [s for s in states if s["abbreviation"].upper() == args.state.upper()]
        if not states:
            print(f"ERROR: No state found with abbreviation '{args.state}'")
            sys.exit(1)

    print(f"=== download_assets {'(DRY RUN) ' if args.dry_run else ''}===\n")

    log = load_log()
    new_entries = []

    for state in states:
        entries = process_state(state, dry_run=args.dry_run, delay=args.delay)
        new_entries.extend(entries)

    if not args.dry_run and new_entries:
        log.extend(new_entries)
        save_log(log)
        print(f"\nLog updated: {DOWNLOAD_LOG}")

    print("\nDone.")


if __name__ == "__main__":
    main()
