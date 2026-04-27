"""Build the Matrixify Custom Collections CSV from the source DB staging dump.

Inputs:  ./_staging_source.csv  (exported via tropy-db MCP)
Outputs: ./matrixify_categories_import.csv
         ./_handle_remap.csv     (audit trail of slug dedupe decisions)

Decisions locked with user 2026-04-27:
- Scope: live (Deleted=0). 256 Category + 86 Section = 342 rows.
- Slug dedupe: keep natural slug for first by (source_type asc, source_id asc);
  later collisions get -2, -3, -N. Cross-source ties resolve Category before Section.
- Sort Order: 'Manual' for all rows; legacy DisplayOrder preserved as metafield.
- Metafield namespace: 'migration.*' per shopify-migration/02-matrixify-migration-plan.md sec 4.3.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "_staging_source.csv"
OUT = HERE / "matrixify_categories_import.csv"
REMAP = HERE / "_handle_remap.csv"

OUTPUT_COLUMNS = [
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


def load_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    for r in rows:
        r["source_id"] = int(r["source_id"])
        r["parent_id"] = int(r["parent_id"])
        r["DisplayOrder"] = int(r["DisplayOrder"]) if r["DisplayOrder"] else 0
        r["Published"] = int(r["Published"]) if r["Published"] else 0
    return rows


def assign_handles(rows: list[dict]) -> list[dict]:
    """Assign final Handle in dedupe order: source_type asc, source_id asc.

    'category' sorts before 'section' alphabetically, so Category wins
    cross-source collisions. Within a source, lower IDs win.
    """
    ordered = sorted(rows, key=lambda r: (r["source_type"], r["source_id"]))
    seen: dict[str, int] = {}
    for r in ordered:
        slug = (r["SEName"] or "").strip().lower()
        if not slug:
            slug = "untitled"
        if slug not in seen:
            seen[slug] = 1
            r["_handle"] = slug
            r["_handle_collision"] = False
        else:
            seen[slug] += 1
            r["_handle"] = f"{slug}-{seen[slug]}"
            r["_handle_collision"] = True
    return rows


def build_path(rows: list[dict]) -> None:
    """Compute migration.source_path breadcrumb (e.g. 'Sports Trophies > Football')."""
    by_key: dict[tuple[str, int], dict] = {(r["source_type"], r["source_id"]): r for r in rows}
    for r in rows:
        names: list[str] = []
        seen: set[tuple[str, int]] = set()
        cursor = r
        while True:
            key = (cursor["source_type"], cursor["source_id"])
            if key in seen:
                break  # cycle guard (defensive — DB has 0 orphans, but be safe)
            seen.add(key)
            names.append(cursor["Name"])
            pid = cursor["parent_id"]
            if pid == 0:
                break
            parent_key = (cursor["source_type"], pid)
            parent = by_key.get(parent_key)
            if parent is None:
                break  # parent deleted
            cursor = parent
        r["_path"] = " > ".join(reversed(names))


def body_html(r: dict) -> str:
    """Pick Description, fallback Summary, fallback empty.

    Matrixify auto-wraps plain text in <p> and strips _x000D_, so pass through as-is.
    """
    desc = (r.get("Description") or "").strip()
    if desc:
        return desc
    summary = (r.get("Summary") or "").strip()
    return summary


def transform(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        out.append({
            "Handle": r["_handle"],
            "Command": "NEW",
            "Title": r["Name"],
            "Body HTML": body_html(r),
            "Sort Order": "Manual",
            "Published": "TRUE" if r["Published"] == 1 else "FALSE",
            "Published Scope": "web",
            "Metafield: title_tag [single_line_text_field]": r.get("SETitle") or "",
            "Metafield: description_tag [string]": r.get("SEDescription") or "",
            "Metafield: seo.keywords [single_line_text_field]": r.get("SEKeywords") or "",
            "Metafield: migration.legacy_source [single_line_text_field]": r["source_type"],
            "Metafield: migration.legacy_id [number_integer]": r["source_id"],
            "Metafield: migration.legacy_guid [single_line_text_field]": r["source_guid"],
            "Metafield: migration.legacy_parent_id [number_integer]": r["parent_id"],
            "Metafield: migration.legacy_display_order [number_integer]": r["DisplayOrder"],
            "Metafield: migration.source_path [single_line_text_field]": r["_path"],
        })
    return out


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def write_remap(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(["source_type", "source_id", "Name", "original_SEName", "final_handle", "collision"])
        for r in sorted(rows, key=lambda x: (x["source_type"], x["source_id"])):
            writer.writerow([
                r["source_type"], r["source_id"], r["Name"],
                r["SEName"], r["_handle"], "Y" if r["_handle_collision"] else "",
            ])


def main() -> int:
    if not SRC.exists():
        print(f"ERROR: staging file not found at {SRC}", file=sys.stderr)
        return 2
    rows = load_rows(SRC)
    assign_handles(rows)
    build_path(rows)
    out_rows = transform(rows)
    write_csv(OUT, OUTPUT_COLUMNS, out_rows)
    write_remap(REMAP, rows)
    collisions = sum(1 for r in rows if r["_handle_collision"])
    print(f"wrote {OUT.name}: {len(out_rows)} rows, {collisions} handle collisions resolved")
    print(f"wrote {REMAP.name}: dedupe audit trail")
    return 0


if __name__ == "__main__":
    sys.exit(main())
