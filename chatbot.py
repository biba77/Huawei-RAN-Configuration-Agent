"""
Run interactively:  python3 chatbot.py huawei_enodeb_SITE001_clean.xml
"""

import sys
import os
import csv
import difflib
from datetime import datetime, timezone

from xml_engine import RANConfig, UnknownCellError, UnknownParameterError
from mml_generator import generate_mml
from nl_parser import parse_rule_based, IntentParseError
from db_engine import build_db_from_xml, sync_change_to_db, log_change_to_db

AUDIT_LOG_CSV = "audit_log.csv"
DB_PATH = "ran_config.db"


def _log_change_csv(local_cell_id, parameter, old_value, new_value, mml, request_text, timestamp):
    file_exists = os.path.exists(AUDIT_LOG_CSV)
    with open(AUDIT_LOG_CSV, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp_utc", "request_text", "local_cell_id",
                              "parameter", "old_value", "new_value", "mml_command"])
        writer.writerow([timestamp, request_text, local_cell_id, parameter,
                          old_value, new_value, mml])


def _diff_preview(before_text: str, after_text: str) -> str:
    diff = difflib.unified_diff(
        before_text.splitlines(keepends=True),
        after_text.splitlines(keepends=True),
        fromfile="before", tofile="after", n=1,
    )
    lines = [l for l in diff if not l.startswith(("---", "+++", "@@"))]
    return "".join(lines).rstrip("\n")


def preview_request(config: RANConfig, request_text: str):
    intent = parse_rule_based(request_text)

    before_text = config.to_pretty_string()
    change = config.set_parameter(
        intent["local_cell_id"], intent["parameter"], intent["value"]
    )
    after_text = config.to_pretty_string()

    mml = generate_mml(change)
    diff_text = _diff_preview(before_text, after_text)
    return change, mml, diff_text


def run_interactive(xml_path: str):
    if not os.path.exists(DB_PATH):
        print(f"No DB found at {DB_PATH} -- building it from {xml_path}...")
        build_db_from_xml(xml_path, DB_PATH)

    config = RANConfig(xml_path)
    print(f"Loaded {xml_path}. Type a command (or 'quit').")
    print("Example: Change tilt to 4 degrees on Cell 1\n")

    while True:
        try:
            request_text = input("engineer> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not request_text:
            continue
        if request_text.lower() in ("quit", "exit"):
            break

        try:
            change, mml, diff_text = preview_request(config, request_text)
        except (IntentParseError, UnknownCellError, UnknownParameterError) as e:
            print(f"✘ Could not apply that change: {e}")
            continue

        print("\n--- PREVIEW (not yet saved) ---")
        print(f"Cell {change.local_cell_id} — {change.parameter}: "
              f"{change.old_value} → {change.new_value}")
        print(f"MML: {mml}")
        print("Diff:")
        print(diff_text if diff_text else "  (no visible text diff)")
        print("--------------------------------")

        confirm = input("Apply this change? [y/N] ").strip().lower()
        if confirm == "y":
            timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

            out = config.save(xml_path)                          # 1. XML
            sync_change_to_db(DB_PATH, change)                    # 2. DB
            log_change_to_db(DB_PATH, change, mml, request_text, timestamp)  # 2b. DB audit
            _log_change_csv(change.local_cell_id, change.parameter,          # 3. CSV
                             change.old_value, change.new_value, mml,
                             request_text, timestamp)

            print(f"✔ Saved -> {out}  |  DB synced -> {DB_PATH}\n")
        else:
            config.set_parameter(change.local_cell_id, change.parameter, change.old_value)
            print("✘ Discarded. File and DB unchanged.\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 chatbot.py <xml_file>")
        sys.exit(1)
    run_interactive(sys.argv[1])
