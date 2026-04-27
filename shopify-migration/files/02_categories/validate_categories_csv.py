"""Validate matrixify_categories_import.csv against expected shape.

Checks:
- File is UTF-8 (no BOM, parses without errors).
- Header columns match expected list exactly, in order.
- Row count matches expected (342 = 256 Category + 86 Section live rows).
- No duplicate Handle.
- Every required field non-empty: Handle, Command, Title, Sort Order, Published.
- Command is in the allowed Matrixify enum.
- Sort Order is in the allowed Matrixify enum.
- Published is TRUE or FALSE.
- legacy_source is 'category' or 'section'.
- legacy_id is a positive integer; legacy_parent_id is a non-negative integer.
- legacy_guid matches uuid format.

Exit code 0 = all checks pass, 1 = checks failed.
"""

from __future__ import annotations

import csv
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGET = HERE / "matrixify_categories_import.csv"

EXPECTED_HEADER = [
    "Handle",
    "Command",
    "Title",
    "Body HTML",
    "Sort Order",
    "Published",
    "Published Scope",
    "Metafield: title_tag [single_line_text_field]",
    "Metafield: description_tag [string]",
    "Metafield: seo.keywords [single_line_text_field]",
    "Metafield: migration.legacy_source [single_line_text_field]",
    "Metafield: migration.legacy_id [number_integer]",
    "Metafield: migration.legacy_guid [single_line_text_field]",
    "Metafield: migration.legacy_parent_id [number_integer]",
    "Metafield: migration.legacy_display_order [number_integer]",
    "Metafield: migration.source_path [single_line_text_field]",
]

EXPECTED_ROWS = 342

ALLOWED_COMMANDS = {"NEW", "MERGE", "UPDATE", "REPLACE", "DELETE", "IGNORE"}
ALLOWED_SORT_ORDERS = {
    "Alphabet", "Alphabet Descending", "Best Selling", "Created",
    "Created Descending", "Manual", "Price", "Price Descending",
}
ALLOWED_PUBLISHED = {"TRUE", "FALSE"}
ALLOWED_LEGACY_SOURCE = {"category", "section"}
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
HANDLE_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


def main() -> int:
    failures: list[str] = []
    warnings: list[str] = []

    if not TARGET.exists():
        print(f"FAIL: {TARGET.name} not found")
        return 1

    raw = TARGET.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        failures.append("file starts with UTF-8 BOM (Matrixify expects clean UTF-8)")
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as e:
        failures.append(f"file is not valid UTF-8: {e}")

    with TARGET.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != EXPECTED_HEADER:
            failures.append(
                f"header mismatch.\n  expected: {EXPECTED_HEADER}\n  actual:   {reader.fieldnames}"
            )
        rows = list(reader)

    if len(rows) != EXPECTED_ROWS:
        failures.append(f"row count {len(rows)} != expected {EXPECTED_ROWS}")

    # Duplicate Handle check
    handle_counts = Counter(r["Handle"] for r in rows)
    dups = [h for h, n in handle_counts.items() if n > 1]
    if dups:
        failures.append(f"duplicate handles: {dups}")

    LEGACY_ID_COL = "Metafield: migration.legacy_id [number_integer]"
    LEGACY_PARENT_COL = "Metafield: migration.legacy_parent_id [number_integer]"
    LEGACY_GUID_COL = "Metafield: migration.legacy_guid [single_line_text_field]"
    LEGACY_SOURCE_COL = "Metafield: migration.legacy_source [single_line_text_field]"
    DISPLAY_ORDER_COL = "Metafield: migration.legacy_display_order [number_integer]"

    required = ["Handle", "Command", "Title", "Sort Order", "Published",
                LEGACY_SOURCE_COL, LEGACY_ID_COL, LEGACY_GUID_COL]

    for i, r in enumerate(rows, start=2):  # row 1 is header
        for col in required:
            if not (r.get(col) or "").strip():
                failures.append(f"row {i} ({r.get('Handle','?')}): {col} is empty")

        if r["Command"] not in ALLOWED_COMMANDS:
            failures.append(f"row {i}: Command '{r['Command']}' not in {ALLOWED_COMMANDS}")
        if r["Sort Order"] not in ALLOWED_SORT_ORDERS:
            failures.append(f"row {i}: Sort Order '{r['Sort Order']}' not in {ALLOWED_SORT_ORDERS}")
        if r["Published"] not in ALLOWED_PUBLISHED:
            failures.append(f"row {i}: Published '{r['Published']}' not in {ALLOWED_PUBLISHED}")
        if r[LEGACY_SOURCE_COL] not in ALLOWED_LEGACY_SOURCE:
            failures.append(f"row {i}: legacy_source '{r[LEGACY_SOURCE_COL]}' not in {ALLOWED_LEGACY_SOURCE}")
        if not HANDLE_RE.match(r["Handle"]):
            failures.append(f"row {i}: Handle '{r['Handle']}' contains invalid characters")

        try:
            lid = int(r[LEGACY_ID_COL])
            if lid <= 0:
                failures.append(f"row {i}: legacy_id {lid} is not positive")
        except (ValueError, TypeError):
            failures.append(f"row {i}: legacy_id '{r[LEGACY_ID_COL]}' is not an integer")

        try:
            pid = int(r[LEGACY_PARENT_COL])
            if pid < 0:
                failures.append(f"row {i}: legacy_parent_id {pid} is negative")
        except (ValueError, TypeError):
            failures.append(f"row {i}: legacy_parent_id '{r[LEGACY_PARENT_COL]}' is not an integer")

        try:
            int(r[DISPLAY_ORDER_COL])
        except (ValueError, TypeError):
            failures.append(f"row {i}: legacy_display_order '{r[DISPLAY_ORDER_COL]}' is not an integer")

        if not UUID_RE.match(r[LEGACY_GUID_COL] or ""):
            failures.append(f"row {i}: legacy_guid '{r[LEGACY_GUID_COL]}' is not a UUID")

    # Soft check: parent integrity (parent_id either 0 or matches an existing legacy_id within same source)
    by_source_id = {(r[LEGACY_SOURCE_COL], int(r[LEGACY_ID_COL])): r for r in rows}
    for r in rows:
        pid = int(r[LEGACY_PARENT_COL])
        if pid != 0:
            key = (r[LEGACY_SOURCE_COL], pid)
            if key not in by_source_id:
                warnings.append(f"row {r['Handle']}: parent_id {pid} ({r[LEGACY_SOURCE_COL]}) not in import set")

    # Source breakdown sanity
    source_counts = Counter(r[LEGACY_SOURCE_COL] for r in rows)
    if source_counts.get("category") != 256 or source_counts.get("section") != 86:
        warnings.append(f"unexpected source split: {dict(source_counts)} (expected category=256, section=86)")

    print(f"rows: {len(rows)}")
    print(f"unique handles: {len(handle_counts)}")
    print(f"source split: {dict(source_counts)}")
    print(f"published TRUE: {sum(1 for r in rows if r['Published']=='TRUE')}")

    if warnings:
        print("\nwarnings:")
        for w in warnings:
            print(f"  - {w}")

    if failures:
        print(f"\n{len(failures)} FAILURES:")
        for f in failures[:25]:
            print(f"  - {f}")
        if len(failures) > 25:
            print(f"  ... and {len(failures) - 25} more")
        return 1

    print("\nOK: all checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
