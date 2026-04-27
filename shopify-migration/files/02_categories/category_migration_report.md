# Category + Section → Shopify Custom Collections — Migration Report

**Generated:** 2026-04-27
**Output:** `matrixify_categories_import.csv` (Matrixify Custom Collections sheet)
**Source:** Live rows (`Deleted=0`) from `Category` and `Section` tables, AspDotNetStorefront-style schema.

---

## 1. Counts

| Source table | Total rows | Live (`Deleted=0`) | Published (`Deleted=0 AND Published=1`) | In CSV |
|---|---:|---:|---:|---:|
| `Category` | 268 | 256 | 205 | 256 |
| `Section`  | 86  | 86  | 79  | 86  |
| **Total**  | 354 | 342 | 284 | **342** |

CSV row count: **342**, all unique `Handle`s. 284 rows published (`Published`=`TRUE`), 58 draft (`FALSE`).

---

## 2. Decisions (locked with user)

| Topic | Decision | Reason |
|---|---|---|
| **Scope** | Include all live rows (`Deleted=0`) | Keeps unpublished collections so admin can review/publish in Shopify. Avoids a second migration pass. |
| **Slug dedupe** | First by `(source_type asc, source_id asc)` keeps natural slug; later collisions get `-2`, `-3`, `-N`. | Deterministic, SEO-clean for the winner. `category` < `section` alphabetically, so Category wins cross-source ties. |
| **Sort Order** | All rows: `Manual` | Source uses explicit `DisplayOrder` integers; `Manual` matches that intent. Legacy value preserved as a metafield. |
| **Metafield namespace** | `migration.*` for legacy data, plus the Shopify built-ins (`title_tag`, `description_tag`) for SEO and `seo.keywords` for keywords. | Matches `02-matrixify-migration-plan.md` §4.3. |
| **Image Src** | Column omitted entirely | 0 of 342 live rows have `ImageFilenameOverride` populated. Per Matrixify docs, omitting the column leaves the image unchanged on re-import. |
| **Output format** | CSV (UTF-8, no BOM, RFC-4180 quoting) | User preference. Filename contains `categories` so Matrixify's "Custom Collections" sheet can be selected at import time. |

---

## 3. Column mapping (DB → Matrixify)

| Source column | Matrixify column | Notes |
|---|---|---|
| `Name` | `Title` | Required. Direct passthrough. |
| `SEName` (deduped) | `Handle` | Lowercased, suffix `-N` on collisions. See §4. |
| — | `Command` | Constant `NEW` (fail-fast on existing-handle collision). |
| `Description` (fallback `Summary`) | `Body HTML` | Pass-through. Matrixify auto-converts plain text to HTML and strips `_x000D_`. 29% have Description; 1% have Summary. |
| — | `Sort Order` | Constant `Manual`. |
| `Published` | `Published` | `1` → `TRUE`, else `FALSE`. |
| — | `Published Scope` | Constant `web` (Online Store only — no POS). |
| `SETitle` | `Metafield: title_tag [single_line_text_field]` | Shopify built-in SEO title. 90% populated. |
| `SEDescription` | `Metafield: description_tag [string]` | Shopify built-in SEO description. 71% populated. |
| `SEKeywords` | `Metafield: seo.keywords [single_line_text_field]` | 89% populated. Custom namespace (Shopify removed keywords from native SEO). |
| `'category'` / `'section'` | `Metafield: migration.legacy_source [single_line_text_field]` | Origin table flag. |
| `CategoryID` / `SectionID` | `Metafield: migration.legacy_id [number_integer]` | Source PK for traceability. |
| `CategoryGUID` / `SectionGUID` | `Metafield: migration.legacy_guid [single_line_text_field]` | Stable cross-system identifier (UUID). |
| `ParentCategoryID` / `ParentSectionID` | `Metafield: migration.legacy_parent_id [number_integer]` | `0` = root. Hierarchy is data-only; Shopify Collections are flat. |
| `DisplayOrder` | `Metafield: migration.legacy_display_order [number_integer]` | Preserved for any later sort script. |
| Computed breadcrumb | `Metafield: migration.source_path [single_line_text_field]` | e.g. `Sports Trophies > Football`. Walks `parent_id` chain. |

### Columns intentionally **omitted**
- `ID` — leave empty on first import (Shopify generates it).
- `Image Src`, `Image Width`, `Image Height`, `Image Alt Text` — 0 source rows have images.
- `Template Suffix` — no theme-template mapping decided yet.
- Linked `Product:` columns — handled in a separate file (see `02-matrixify-migration-plan.md` File B `06_product_collection_links.xlsx`).

---

## 4. Handle dedupe — 23 collisions resolved

The source has 21 distinct slug groups with > 1 occurrence (3 cross-source, 18 within Category alone, 0 within Section). With one slug at multiplicity 4, that's **23 dupes** that need a suffix.

Audit trail is in `_handle_remap.csv`. Highlights:

| Original SEName | Winner (kept slug) | Losers |
|---|---|---|
| `mascot-bobblehead-trophies` | CategoryID 23 (under "Trophies") | -2: 135, -3: 223, -4: 262 |
| `cup-trophies` | CategoryID 57 | -2: SectionID 65 |
| `custom-awards` | CategoryID 184 | -2: SectionID 98 |
| `t-shirts` | CategoryID 299 | -2: SectionID 68 |
| 17 other within-Category dupes | lower CategoryID | higher gets `-2` |

Matrixify will lowercase and strip non-URL chars on import as well — our slugs already comply, so no further normalization expected.

---

## 5. Hierarchy

- Category max depth: **3** (e.g. `Trophies > Mascot Trophies > Mascot Bobblehead Trophies`).
- Section max depth: **2**.
- 0 orphans, 0 cycles. All `parent_id != 0` rows resolve to a live row in the import set.

Shopify Collections have no native parent/child relationship. The hierarchy is preserved as **data only** via two metafields:
- `migration.legacy_parent_id` (raw int — for round-trip / scripted re-parenting).
- `migration.source_path` (human-readable breadcrumb — for storefront breadcrumb apps or Liquid templates that read from a metafield).

---

## 6. Validation

`validate_categories_csv.py` checks:
- UTF-8 (no BOM).
- Header matches expected column list and order.
- Row count = 342.
- All `Handle`s unique and match `^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$`.
- `Command` ∈ Matrixify enum, `Sort Order` ∈ Matrixify enum, `Published` ∈ {`TRUE`,`FALSE`}.
- `legacy_source` ∈ {`category`,`section`}.
- `legacy_id` is positive int, `legacy_parent_id` is non-negative int, `legacy_guid` is UUID.
- Required fields non-empty: `Handle`, `Command`, `Title`, `Sort Order`, `Published`, the legacy_* metafields.
- Soft check: every non-zero `legacy_parent_id` resolves to a row in the import.

**Result:** all checks pass.

---

## 7. How to import

1. Verify the CSV in a Matrixify dev/staging store first.
2. In Matrixify → New Import → upload `matrixify_categories_import.csv`.
3. The app may auto-detect the sheet as "Custom Collections" because of the column shape; if not, manually pick "Custom Collections" in the Import setup UI.
4. Default Import Options are fine. Do NOT enable "Transliterate Handles" (already English).
5. Check the Import Results file for any failed rows and fix at the row level (re-import only the failures).

After a successful import, the `migration.legacy_*` metafields can be used for:
- Reverse-mapping product↔collection links (next phase).
- Reconstructing breadcrumb navigation in the Shopify theme via `metafield: migration.source_path`.
- Eventually deleting the metafields once the migration is fully cut over.

---

## 8. Files in this folder

| File | Purpose |
|---|---|
| `_staging_source.csv` | Raw export from `Category` ∪ `Section` (live rows, 342 rows). Generated via tropy-db MCP. |
| `build_categories_csv.py` | Transforms staging CSV → Matrixify CSV. Idempotent. |
| `matrixify_categories_import.csv` | **The deliverable.** Upload this to Matrixify. |
| `_handle_remap.csv` | Audit trail of slug dedupe decisions. |
| `validate_categories_csv.py` | Validates the deliverable against expected shape. |
| `category_migration_report.md` | This file. |

To regenerate from scratch:
```sh
# 1. (optional) re-export source via tropy-db MCP exportQueryToCsv into _staging_source.csv
python build_categories_csv.py
python validate_categories_csv.py
```
