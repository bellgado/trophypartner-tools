# Matrixify-Oriented Migration Plan — Source DB → Shopify

> **Purpose**: execute the field-level mapping documented in [`01-product-migration-plan.md`](./01-product-migration-plan.md) through **[Matrixify](https://matrixify.app/)**, a bulk import/export app for Shopify (Excel / Google Sheets / CSV).
>
> **Sources used (ONLY)**
> - Matrixify official docs: [matrixify.app/documentation](https://matrixify.app/documentation/), [Products sheet](https://matrixify.app/documentation/products/), [Custom Collections sheet](https://matrixify.app/documentation/custom-collections/), [Command list](https://matrixify.app/documentation/list-of-commands-across-matrixify-sheets/), [Identification rules](https://matrixify.app/tutorials/how-existing-shopify-products-are-identified-when-imported/), [Shopify limits](https://matrixify.app/documentation/shopify-limits/), [Import process](https://matrixify.app/documentation/import-data-to-shopify-with-matrixify/), [Migrate to Shopify](https://matrixify.app/migrate-to-shopify/), [Metafields format](https://matrixify.app/documentation/metafields/), [Minimum columns tutorial](https://matrixify.app/tutorials/minimum-columns-to-update-product/), [Format template](https://matrixify.app/documentation/matrixify-format-template/).
> - Source DB: [`database-knowledge/`](../database-knowledge/).
> - Prior mapping: [`01-product-migration-plan.md`](./01-product-migration-plan.md).
>
> **Rules**
> - Nothing invented. Column names are quoted verbatim from the Matrixify docs. If Matrixify doesn't document a feature we need, it is flagged.
> - Open questions from plan #1 (P-01 … P-47) are **not re-opened here**; every unresolved one still applies and blocks the corresponding piece of the importable file.

---

## 1. Honest valuation — is Matrixify the right tool for this migration?

### 1.1 What Matrixify gives us

- **Bulk import/export** of 18 Shopify data entities: Products, Smart Collections, Custom Collections, Customers, Companies, Discounts, Draft Orders, Orders, Payouts, Pages, Blog Posts, Redirects, Activity, Files, Metaobjects, Menus, Metafields, Shop. ([docs](https://matrixify.app/documentation/))
- **File formats**: Excel (`.xlsx`), Google Sheets, CSV. Up to **20 GB** per file (5 GB for manual upload, 30 GB inside a ZIP). ([import docs](https://matrixify.app/documentation/import-data-to-shopify-with-matrixify/))
- **Partial-column imports**: you only need to include the columns you want to touch. The app updates only the fields whose columns are present. ([products docs](https://matrixify.app/documentation/products/))
- **Per-row `Command` column** (`NEW`, `MERGE`, `UPDATE`, `REPLACE`, `DELETE`, `IGNORE`) plus specialized commands at Variant/Tags/Image level (`MERGE`/`REPLACE`/`DELETE` etc.). ([command list](https://matrixify.app/documentation/list-of-commands-across-matrixify-sheets/))
- **Deterministic identification** of existing products: ID → Handle → Title → Variant ID → Variant SKU → Variant Barcode. ([identification docs](https://matrixify.app/tutorials/how-existing-shopify-products-are-identified-when-imported/))
- **Native metafield support** with inline type hints (`Metafield: namespace.key [type]` and `Variant Metafield: namespace.key [type]`). All Shopify-native metafield types supported. Definitions **do not** have to pre-exist, but the docs recommend creating them first. ([metafield docs](https://matrixify.app/documentation/metafields/))
- **Per-location inventory columns**: `Inventory Available: <Location Name>`, `Inventory On Hand: <Location Name>`, `Inventory Damaged: <Location Name>`, `Inventory Safety Stock: <Location Name>`, `Inventory Quality Control: <Location Name>` (+ `... Adjust` variants).
- **Import Results file** after every run listing each row's status and error message.
- **Recommended migration flow** from a non-Shopify platform: export from source → dry-run import into Matrixify to **generate a Matrixify-format template** → adjust the file → import into Shopify. ([migrate page](https://matrixify.app/migrate-to-shopify/))

### 1.2 What Matrixify is **not**

These are the things the docs we've seen **don't** solve for us, and we must not assume they do:

- **Not an ETL tool that reads our SQL database directly.** We still need a script that queries the source DB and writes the Matrixify-format Excel/CSV files. Matrixify only consumes pre-shaped sheets.
- **Not a transformation engine for our specific business rules.** All the transformation rules from plan #1 §5 (variant materialization, SKU composition, price/compareAtPrice logic, handle normalization, taxonomy flattening) happen in **our generator**, before Matrixify sees the row.
- **No `productBundleCreate` analog documented on the Products sheet we've reviewed.** Our kits (P-04) cannot be assumed to import via Matrixify's Products sheet — confirmation needed. This is **Pending M-01**.
- **No subscription / Selling Plan / Digital Download column documented on the Products sheet we've reviewed.** P-31, P-34 still blocked.
- **No dry-run feature explicitly documented.** The closest is: use `IGNORE` commands or import a small subset first. ([import docs](https://matrixify.app/documentation/import-data-to-shopify-with-matrixify/) describes the import UI with live progress, not a simulated dry run.) **Pending M-02**.
- **No rollback documented.** A failed/partial import is not automatically reverted. Strategy must be: take a Shopify backup, import into a dev store first, verify, then replay into production. **Pending M-03**.
- **Images**: Matrixify accepts `Image Src` (URL) and `Image Attachment`, but whether bytes live in our source storage or in a CDN is still P-26 from plan #1. Matrixify does not fetch images from our database.
- **Handle-change semantics**: the docs confirm Handle can be updated when identified by Variant SKU, but don't document whether Matrixify auto-creates the 301 redirect. **Pending M-04**.

### 1.3 Verdict

For the **core product migration** (Product + Variant + Inventory + Collections + Product↔Collection + Metafields + Images by URL), Matrixify is a **good fit**. It eliminates the need to write Admin-GraphQL calls, handle rate limits, paginate, or manage the bulk operation lifecycle ourselves.

For the **corner cases** — kits/bundles, subscriptions, digital downloads, tax classes, quantity discounts, B2B price lists, reviews — Matrixify is **not a turnkey solution**. Those stay as Pending from plan #1 and either:
- go through Matrixify only partially (e.g. products imported, bundle components configured separately), or
- bypass Matrixify entirely (e.g. reviews via a reviews app's own importer).

Net assessment: buying Matrixify is **justified** as the transport layer. Budget must still account for the generator script and the unsolved corner cases.

---

## 2. Entity → Matrixify sheet map

Each source entity maps to one Matrixify sheet. One spreadsheet file can hold multiple sheets; each sheet maps to one data type.

| Source entity | Matrixify sheet | Notes |
|---|---|---|
| `Product` + `ProductVariant` + `Inventory` + `ProductType` + `ProductManufacturer` (for vendor) | **Products** | One file row per Shopify variant. Rows with the same `Handle` (and empty `ID`) belong to the same product. |
| `Category`, `Section`, `Genre`, `Vector`, `Library` (taxonomies) | **Custom Collections** | One file row per Collection↔Product pair. Repeated `Handle` rows link multiple products. |
| Smart rules (if we decide any taxonomy maps to rule-based) | **Smart Collections** | Not in scope for MVP; tagged products + Custom Collections is the default. |
| `Rating` (reviews) | — | **Not Matrixify**. Imported via the chosen reviews app. |
| `ProductCustomerLevel` | — | **Not Matrixify's Products sheet**. B2B / catalog price lists. See P-06 + catalog columns §4.4. |
| `Document`, `RelatedDocuments` | **Files** sheet (possibly) | **Pending M-05**. |
| Product↔Document relations | Product Metafields (`list.file_reference`) | Requires two-pass import (files first, then product metafields). |

---

## 3. File strategy (what files we actually produce)

We will **not** build one giant file. We build **one Excel workbook per migration phase**, each with the sheets it needs. This keeps import times manageable and makes rollback of a single phase feasible by re-running with `REPLACE` or by undoing with `DELETE` on a known ID set.

### 3.1 File layout

```
shopify-migration/
├── 01-product-migration-plan.md          (field mapping — plan #1)
├── 02-matrixify-migration-plan.md        (this file)
└── files/                                 (produced by generator)
    ├── 01_metafield_definitions.xlsx       (Metafields sheet)
    ├── 02_collections.xlsx                 (Custom Collections sheet — no product links yet)
    ├── 03_products_base.xlsx               (Products sheet — products + variants + option values + cost + weight, no inventory, no images)
    ├── 04_products_images.xlsx             (Products sheet — ID/Handle + image columns only)
    ├── 05_inventory.xlsx                   (Products sheet — ID/Handle/Variant SKU + Inventory columns only, per location)
    ├── 06_product_collection_links.xlsx    (Custom Collections sheet — collection Handle + Product: Handle + Product: Position)
    ├── 07_product_metafields.xlsx          (Products sheet — ID/Handle + Metafield: ... columns only, for cross-references like related products)
    └── 08_redirects.xlsx                   (Redirects sheet — old source URL → new Shopify handle)
```

Why split: Matrixify accepts column-subsets per file ([products docs](https://matrixify.app/documentation/products/)). Splitting lets us:
- re-run one phase without touching another,
- keep each file well under size/time limits,
- run phase N+1 only after phase N passes validation.

### 3.2 File naming convention

`{order}_{entity}_{env}_{YYYYMMDD-HHmm}.xlsx` → e.g. `03_products_base_staging_20260422-1400.xlsx`.

Matrixify recommends including the source platform name in filenames when migrating from a non-Shopify source ([migrate page](https://matrixify.app/migrate-to-shopify/)). We'll prefix the source-data exports (before transformation) with `src_` to distinguish from Matrixify-formatted files.

---

## 4. Column mapping — DB → Matrixify

This section takes each Matrixify column (exact name, from [products docs](https://matrixify.app/documentation/products/)) and says what goes into it, given the DB schema. Where plan #1 left a Pending, we inherit it.

### 4.1 Products sheet — identification & product-level columns

| Matrixify column | Source | Rule | Plan-#1 ref |
|---|---|---|---|
| `ID` | — | **Leave empty on initial import.** Shopify creates the ID; Matrixify's Import Results file returns it. Populate on re-import files. | — |
| `Handle` | `Product.SEName` | Normalize: lowercase, hyphens, strip disallowed chars, enforce **255-char limit** ([limits](https://matrixify.app/documentation/shopify-limits/)). Handle collision → deterministic suffix. | P-47 |
| `Command` | — | `NEW` on first load, `MERGE` on re-imports. | — |
| `Title` | `Product.Name` | Direct. | — |
| `Body HTML` | `Product.Description` | Direct. | — |
| `Vendor` | `Manufacturer.Name` via `ProductManufacturer` | Single-valued. Multiple manufacturers → P-02. | P-02 |
| `Type` | `ProductType.Name` via `Product.ProductTypeID` | Direct. | — |
| `Tags` | Computed: `IsFeatured=1 → "featured"`, `IsCalltoOrder=1 → "call-to-order"`, optional `"wholesale"` if `Wholesale=1` | Comma-separated. Each tag **≤255 chars**. | P-14, P-17, P-19 |
| `Tags Command` | — | `MERGE` (default). `REPLACE` only if we want to overwrite existing tags. | — |
| `Template Suffix` | `Product.XmlPackage` / `TemplateName` | Only populate after P-12 resolves which theme templates exist. | P-12 |
| `Gift Card` | — | Leave empty unless we identify gift-card products in the source. | — |
| `Status` | `Product.Published` + `Product.Deleted` | `Published=1 & Deleted=0 → "active"`; `Published=0 & Deleted=0 → "draft"`; `Deleted=1 →` either skip or `"archived"` (P-10). | P-10 |
| `Published` | — | `TRUE` when `Status=active`. | — |
| `Published At` | — | Leave empty (Shopify sets it). Optionally: `Product.CreatedOn` as a metafield instead. | — |
| `Published Scope` | — | Omit (defaults to `global`). | — |
| `Category: Name` / `Category: ID` | — | **Pending M-06**: Shopify product taxonomy category (separate from Custom Collections) — source has no equivalent; leave empty. | — |
| `Custom Collections` | Not used on Products sheet | Link via the Custom Collections sheet instead (§4.3). | — |

### 4.2 Products sheet — variants, options, inventory, pricing

Each Shopify variant is one row. Rows sharing `Handle` belong to the same product (first row carries product-level columns; subsequent rows only need variant columns + `Handle`).

| Matrixify column | Source | Rule | Plan-#1 ref |
|---|---|---|---|
| `Option1 Name` | `Product.ColorOptionPrompt` (fallback `"Color"`) or `Product.SizeOptionPrompt` (fallback `"Size"`) | Set on **first row** per product. Axis selection follows the variant-materialization rule. | P-43, P-44 |
| `Option1 Value` | `Inventory.Color` or `Inventory.Size` | One per row. Empty-string is not valid for Shopify options. | P-44 |
| `Option2 Name` / `Option2 Value` | Second axis, if any | Same. | |
| `Option3 Name` / `Option3 Value` | Third axis, if any | Max 3 axes per Shopify product ([limits](https://matrixify.app/documentation/shopify-limits/)). Over-limit → P-44. | P-44 |
| `Variant Command` | — | `MERGE` default. `REPLACE` if we're wiping stale variants. | — |
| `Variant ID` | — | Empty on initial load. | — |
| `Variant Position` | `ProductVariant.DisplayOrder` + tie-break `IsDefault=1 → 1` | Integer. | — |
| `Variant SKU` | Computed — §5.1 | Unique recommended but not enforced by Shopify. | P-40, P-45 |
| `Variant Barcode` | `Inventory.GTIN` (fallback `ProductVariant.GTIN`) | 14 chars. | — |
| `Variant Price` | Computed — §5.2 | Up to 2 decimals. | P-28, P-46 |
| `Variant Compare At Price` | Computed — §5.2 | Empty or > `Variant Price`. | P-28, P-46 |
| `Variant Cost` | `ProductVariant.Cost` | Goes to `InventoryItem.cost`. | P-28 |
| `Variant Weight` | `ProductVariant.Weight + Inventory.WeightDelta` | Unit goes to `Variant Weight Unit`. | P-29 |
| `Variant Weight Unit` | Constant (to be chosen: `"g"`, `"kg"`, `"oz"`, `"lb"`) | One store-wide value. | P-29 |
| `Variant Requires Shipping` | `TRUE` unless `ProductVariant.IsDownload=1` | Digital downloads → P-31. | P-31 |
| `Variant Fulfillment Service` | `"manual"` default | Overridden only if a 3P fulfillment service is in use. | — |
| `Variant Shipping Profile` | — | Empty unless `IsShipSeparately=1` / `FreeShipping=1` drive profile selection. | P-30 |
| `Variant Taxable` | `ProductVariant.IsTaxable` | Boolean. | — |
| `Variant Tax Code` | — | Empty unless P-09 resolves to Avalara codes. | P-09 |
| `Variant HS Code` | — | Empty unless source has HS codes (not in schema we've seen). | — |
| `Variant Country of Origin` | — | Empty unless configured. | — |
| `Variant Inventory Tracker` | `"shopify"` when inventory is tracked | `""` (empty) disables tracking. `Product.TrackInventoryBy*` flags decide. | — |
| `Variant Inventory Policy` | `"deny"` (default) or `"continue"` (if source allows backorders) | Source schema doesn't model backorders; default `deny`. | — |
| `Variant Inventory Qty` | **Not used here**. Use per-location columns. | — | — |
| `Inventory Available: <Location Name>` | `Inventory.Quan` for the row's `(Color, Size)` | **Pending M-07**: `<Location Name>` must exactly match a Shopify location name — must be created beforehand. See §5.3. | P-24 |
| `Variant Image` | filename from `ProductVariant.ImageFilenameOverride` | Must match the media uploaded via `Image Src` / `Image Attachment`. | P-26 |
| `Variant Metafield: migration.legacy_variant_id [number_integer]` | `ProductVariant.VariantID` | Carries the source ID for two-pass operations. | — |
| `Variant Metafield: migration.legacy_variant_guid [single_line_text_field]` | `ProductVariant.VariantGUID` | — | — |
| `Variant Metafield: variant.manufacturer_part_number [single_line_text_field]` | `ProductVariant.ManufacturerPartNumber` | — | — |
| `Variant Metafield: variant.dimensions [single_line_text_field]` | `ProductVariant.Dimensions` | — | — |
| `Variant Metafield: variant.min_qty [number_integer]` | `ProductVariant.MinimumQuantity` | Enforcement still P-37. | P-37 |
| `Variant Metafield: variant.restricted_quantities [single_line_text_field]` | `ProductVariant.RestrictedQuantities` | Enforcement still P-36. | P-36 |
| `Variant Metafield: variant.condition [number_integer]` | `ProductVariant.Condition` | Legend still P-39. | P-39 |
| `Variant Metafield: variant.has_turbo_partner_service [boolean]` | `ProductVariant.HasTurboPartnerService` | — | — |

> `Variant Inventory Adjust` vs `Inventory Available: <Location>`: the "Adjust" columns add a delta; the non-adjust columns set absolute values. For a **fresh migration**, always use absolute (`Inventory Available: <Location Name>` or `Inventory On Hand: <Location Name>`). Re-syncs use adjust.

### 4.3 Custom Collections sheet — taxonomies and product links

Two distinct files:

**File A — create collections** (`02_collections.xlsx`, one row per Collection):

| Column | Source | Rule |
|---|---|---|
| `Command` | — | `NEW` on first load. |
| `ID` | — | Empty on first load. |
| `Handle` | `Category.SEName` / `Section.SEName` / `Genre.SEName` / `Vector.SEName` / `Library.SEName` | Normalize; handle-collision strategy needed across all five source taxonomies (P-47). |
| `Title` | `.Name` | — |
| `Body HTML` | `.Description` | — |
| `Sort Order` | — | Default `"manual"` to keep the `Product: Position` we export. Otherwise `"best-selling"`, `"alpha-asc"`, etc. |
| `Template Suffix` | `.XmlPackage` / `.TemplateName` | P-12. |
| `Published` | `.Published` + `.Deleted` | Collections are unpublished by default in Shopify; must be set `TRUE` to show. |
| `Image Src` | `.ImageFilenameOverride` | URL or file reference. P-26. |
| `Image Alt Text` | `.SEAltText` | — |
| `Metafield: migration.legacy_source [single_line_text_field]` | Constant: `"category"` / `"section"` / `"genre"` / `"vector"` / `"library"` | Distinguishes the source taxonomy so we can round-trip. |
| `Metafield: migration.legacy_id [number_integer]` | `.CategoryID` / `.SectionID` / … | — |
| `Metafield: migration.legacy_parent_id [number_integer]` | `.ParentCategoryID` / `.ParentSectionID` / … | Preserves source hierarchy as data (Shopify collections are flat — P-01). |
| `Metafield: seo.keywords [single_line_text_field]` | `.SEKeywords` | — |

**File B — link products** (`06_product_collection_links.xlsx`, one row per Collection↔Product pair):

| Column | Source | Rule |
|---|---|---|
| `Handle` | Collection handle (already imported) | Identifies the target collection. |
| `Command` | — | `MERGE` (don't overwrite collection metadata). |
| `Product: Handle` | Product handle | Matrixify confirms products can be linked by handle. |
| `Product: Position` | `ProductCategory.DisplayOrder` / `ProductSection.DisplayOrder` / … | Requires the collection `Sort Order = "manual"`. |
| `Product: Command` | — | `MERGE` (add if absent). Use `DELETE` only when unlinking. |

### 4.4 Products sheet — B2B / catalog pricing (deferred)

Matrixify exposes catalog-scoped pricing columns: `Price / <Catalog Name>`, `Compare At Price / <Catalog Name>`, `Included / <Catalog Name>`. These map the source's `ProductCustomerLevel` / `CustomerLevel` / `Wholesale` → Shopify B2B Catalogs. **All deferred until P-06 and P-19 resolve.**

---

## 5. Transformation rules executed by the generator

Matrixify consumes ready-to-import rows. The generator (to be built after this plan) owns the transformations. The rules from plan #1 §5 apply as-is; below is their Matrixify-specific restatement.

### 5.1 Variant materialization and SKU composition

For each source `Product` row (unless `IsAKit=1`):

1. Decide the axes using `TrackInventoryBySizeAndColor` / `BySize` / `ByColor` (plan #1 §5.1).
2. Enumerate `(Color, Size)` combinations from `Inventory` (primary) or from `ProductVariant.Colors`/`Sizes` delimited lists when `Inventory` is empty for that axis.
3. For each combination, emit a Matrixify row with:
   - Same `Handle` as the product's first row.
   - `Option1 Name` / `Option1 Value` (+ `Option2 …` if second axis).
   - `Variant SKU` computed per plan #1 §5.2 (`Inventory.VendorFullSKU` wins; otherwise `Product.SKU + SKUSuffix + ColorSKUMod + SizeSKUMod`). Still subject to P-40 and P-45.
   - `Variant Image` set only if the variant has a distinct image.
4. First row carries **all product-level columns**; subsequent rows leave them blank.

### 5.2 Price / Compare At Price

Apply plan #1 §5.3 (still subject to P-46):

- `SalePrice IS NOT NULL AND SalePrice > 0 AND SalePrice < Price` → `Variant Price = SalePrice`, `Variant Compare At Price = Price`.
- Else if `MSRP IS NOT NULL AND MSRP > Price` → `Variant Price = Price`, `Variant Compare At Price = MSRP`.
- Else → `Variant Price = Price`, `Variant Compare At Price` empty.

### 5.3 Locations

Matrixify's inventory columns are **keyed by location name**, e.g. `Inventory Available: Main Warehouse`. This means:

1. Every unique `Product.WarehouseLocation` and `Inventory.WarehouseLocation` value in the source must be resolved to a **real Shopify Location** (existing or created manually in Shopify Admin). This is plan #1's **P-24**, elevated here to **M-07**.
2. The generator accepts a **location map** (CSV/JSON): `source_warehouse_string → shopify_location_name`.
3. The generator emits one `Inventory Available: <Shopify Location Name>` column per mapped location. Rows only populate the relevant location's column.

### 5.4 Handle, Title, Tag normalization

- Handle: lowercase, NFKD-normalize, replace non-alphanumeric runs with `-`, trim to 255 chars, deduplicate with `-2`, `-3`, … suffixes (P-47).
- Title: trim whitespace, collapse double spaces.
- Tags: trim, deduplicate, ensure each ≤255 chars, ensure commas inside a tag are escaped (Matrixify treats commas as tag separators).

### 5.5 Metafield definitions (pre-created)

Matrixify allows metafields without pre-existing definitions, but the docs recommend defining them first ([metafield docs](https://matrixify.app/documentation/metafields/)). We do:

1. Create metafield definitions in Shopify Admin (or via the Metafields sheet) for every key we emit, with the declared type. This gives us validation, admin-UI visibility, and Storefront API access control.
2. Use the **Metafields** sheet to batch-create them (one row per definition).
3. Only then emit the Products/Custom Collections sheets with `Metafield: …` columns.

List of definitions we must create — see §7.

### 5.6 Images

Two supported inputs in Matrixify:
- `Image Src` = **public URL** to the image. Simplest path if source images are publicly fetchable.
- `Image Attachment` = file reference inside a ZIP uploaded alongside the spreadsheet.

The generator must choose **one path per migration**:
- If the source images are on a public CDN → use `Image Src`.
- Otherwise → bundle the original files in a ZIP, reference them by `Image Attachment`. Entire import including the ZIP stays under the **30 GB** limit.

In both cases, `Image Position` orders them (1 = primary), `Image Alt Text` carries alt text (use `Product.SEAltText` for primary image).

P-26 from plan #1 must resolve to one of the above before the generator is built.

---

## 6. Order of operations (the actual migration runbook)

> **Strong recommendation**: do the first end-to-end run on a **development store** before touching production. Shopify offers free dev stores; Matrixify runs there too.

### Phase 0 — Preparation (no imports yet)

1. **Answer the top-5 questions** from plan #1 §8: P-07 (store count), P-24/P-26 (images + locations), P-28/P-29 (currency + weight unit), P-46 (sale-price logic), P-04 (kit fidelity).
2. **Install Matrixify** on the target Shopify store.
3. **Create Shopify Locations** in Admin → Settings → Locations, matching the location map agreed in §5.3.
4. **Create Shopify Metafield definitions** for every `Metafield: …` key listed in §7 — either manually in Admin or via a Matrixify **Metafields** sheet import.
5. **Choose weight unit** store-wide (Admin → Settings → Shipping) — resolves P-29 in the sheet.
6. **Backup the target store** (Matrixify export of all entities) even if empty — baseline for rollback.

### Phase 1 — Collections (without products)

7. Generate `02_collections.xlsx` from `Category`, `Section`, `Genre`, `Vector`, `Library`.
8. Import with `Command=NEW`. Review the **Import Results** file; any failures get corrected and re-run with `Command=MERGE`.
9. Export all Custom Collections back from Matrixify — capture the Shopify `ID` for each, store in the generator's ID-map.

### Phase 2 — Products (base, no inventory, no images)

10. Generate `03_products_base.xlsx` with the columns from §4.1 and §4.2 **except** `Inventory Available: …` and `Image Src` / `Image Attachment` / `Image Position`.
11. Import with `Command=NEW`. Matrixify creates products with 0 inventory and no images.
12. Export all Products → capture Shopify `ID` + `Variant ID` + generated `Handle` per source row. Persist in the ID-map.
13. **Validate**: product count matches expected; sample 20 products in Shopify Admin for correctness.

### Phase 3 — Images

14. Generate `04_products_images.xlsx` — columns: `ID` (from ID-map), `Handle`, `Image Command=MERGE`, `Image Src` (or `Image Attachment`), `Image Position`, `Image Alt Text`, and `Variant Image` (filename) for variant-linked images.
15. Import. Failures here (broken URLs, too-large images, >250 per product) are logged per-row. Fix and re-import with `Image Command=MERGE`.

### Phase 4 — Inventory

16. Generate `05_inventory.xlsx` — columns: `ID`, `Handle`, `Variant SKU`, one `Inventory Available: <Location Name>` column per Shopify location.
17. Import with `Command=MERGE`, `Variant Command=MERGE`. Sets absolute quantities.
18. **Spot-check** in Shopify Admin: pick 10 variants across multiple locations, verify qty.

### Phase 5 — Product ↔ Collection links

19. Generate `06_product_collection_links.xlsx` using the ID-maps from Phase 1 and Phase 2.
20. Import with `Command=MERGE`, `Product: Command=MERGE`. Collections with `Sort Order=manual` honor `Product: Position`.
21. Verify sample collections in Admin.

### Phase 6 — Cross-reference product metafields (related / upsell)

22. Generate `07_product_metafields.xlsx` with `ID` and `Metafield: product.related_products [list.product_reference]`, `Metafield: product.upsell_products [list.product_reference]` — only possible now because all source products have Shopify IDs. Each list value is a `gid://shopify/Product/NNN` string (Matrixify accepts these for reference metafields).
23. Import with `Command=MERGE`.

### Phase 7 — Redirects (SEO preservation)

24. Build a source-URL → Shopify-handle map from the ID-map and the old source URL patterns.
25. Generate `08_redirects.xlsx` (Matrixify **Redirects** sheet).
26. Import with `Command=NEW`.

### Phase 8 — Deferred tracks (not Matrixify on the Products sheet)

These **do not run** through the core Products sheet and are gated on the corresponding Pending:

- **Kits / bundles** (P-04, M-01) — handled via Shopify's `productBundleCreate` mutation or a dedicated bundles app; Matrixify migrates only the bundle **parent product**, the component relationships are created separately.
- **Subscriptions** (P-34) — selling plan groups via a subscriptions app.
- **Digital downloads** (P-31) — Shopify Digital Downloads or equivalent app, with its own importer.
- **Reviews** (P-05) — target reviews app's own importer.
- **B2B catalog pricing** (P-06, P-19) — Matrixify's catalog columns `Price / <Catalog Name>`, etc., after the Catalog itself is created in Shopify Admin.
- **Taxation** (P-09) — Shopify tax settings + overrides, configured per collection in Admin.

### Phase 9 — Cutover

27. Freeze writes on the source store.
28. Re-run Phases 2–5 as deltas (`Command=MERGE`) to catch any last-minute changes since the dev-store test.
29. Publish products — Phase 2 created them with `Status=active` already, so they appear as soon as the Shopify store is made public.
30. Flip DNS / storefront.

---

## 7. Required Shopify Metafield definitions

Emit in Shopify Admin (or via a Matrixify **Metafields** sheet) **before** Phase 2. Owner type and key are normative.

**Product owner**
- `migration.legacy_product_id` — `number_integer`
- `migration.legacy_product_guid` — `single_line_text_field`
- `migration.source_created_on` — `date_time`
- `migration.source_updated_on` — `date_time`
- `product.summary` — `multi_line_text_field`
- `product.manufacturer_part_number` — `single_line_text_field`
- `product.featured_teaser` — `multi_line_text_field`
- `product.misc_text` — `multi_line_text_field`
- `product.internal_notes` — `multi_line_text_field` (admin-only access)
- `product.exclude_from_feeds` — `boolean`
- `product.requires_additional_production_time` — `boolean`
- `product.additional_production_days` — `number_integer`
- `product.related_products` — `list.product_reference`
- `product.upsell_products` — `list.product_reference`
- `product.upsell_discount_pct` — `number_decimal`
- `product.extension_data_1..5` — `multi_line_text_field`
- `google.description` — `multi_line_text_field`
- `seo.keywords` — `single_line_text_field`

**Product Variant owner**
- `migration.legacy_variant_id` — `number_integer`
- `migration.legacy_variant_guid` — `single_line_text_field`
- `variant.manufacturer_part_number` — `single_line_text_field`
- `variant.description` — `multi_line_text_field`
- `variant.dimensions` — `single_line_text_field`
- `variant.min_qty` — `number_integer`
- `variant.restricted_quantities` — `single_line_text_field`
- `variant.condition` — `number_integer` (legend pending P-39)
- `variant.has_turbo_partner_service` — `boolean`
- `variant.inventory_extension_data` — `multi_line_text_field`

**Collection owner**
- `migration.legacy_source` — `single_line_text_field`
- `migration.legacy_id` — `number_integer`
- `migration.legacy_parent_id` — `number_integer`
- `seo.keywords` — `single_line_text_field`
- `collection.summary` — `multi_line_text_field`
- `collection.extension_data` — `multi_line_text_field`

---

## 8. Corner cases and how they're handled

### 8.1 Handle conflicts across different taxonomies

`Category.SEName = "engraved"` and `Section.SEName = "engraved"` would collide on the same Shopify Custom Collection handle. Generator applies suffixes (`engraved-category`, `engraved-section`) **and** records the mapping in the `migration.legacy_source` metafield so the origin is recoverable.

### 8.2 A variant image that belongs to multiple variants

Matrixify's `Variant Image` column takes a single filename per variant row. If multiple variants share an image, each row references the same filename — Matrixify de-duplicates media on the product.

### 8.3 Products with only one variant

No `Option1 Name` / `Option1 Value` needed in Matrixify — Shopify auto-creates a default variant. The row still goes in with the product-level columns only.

### 8.4 Products where `Inventory` has combinations not in `ProductVariant.Colors`/`Sizes`, or vice versa

The generator **unions** both sources (plan #1 §5.1). Any combination only in `Inventory` gets emitted as a variant; any combination only in `Colors × Sizes` with no `Inventory` row is emitted with qty=0 at the default location. Both behaviors are logged for QA.

### 8.5 More than 3 axes (Color + Size + Custom prompt)

Shopify hard limit: 3 options. If a product would need a fourth, the generator **skips the product** and logs it. Resolution is P-44 (either drop an axis, split into separate products, or use variant metafields to carry the 4th axis).

### 8.6 Handle change on re-run

Matrixify confirms: when identified by `Variant SKU`, `Handle` can be updated. Matrixify doesn't auto-create a 301 redirect (**Pending M-04**) — the Redirects sheet run in Phase 7 must cover any changed handles.

### 8.7 SKU duplication across products

Shopify tolerates duplicate SKUs, but Matrixify's SKU-based identification fails when the same SKU exists on multiple products/variants (the docs say "If multiple variants with such SKU are found, then the app will update all of them"). Generator enforces **`ID` or `Handle` identification** wherever we can — reserve SKU-only matching for specific reconciliation tasks.

### 8.8 Failed images (broken URL, >20 MB, >20 MP)

Shopify/Matrixify limits: 250 images per product, 20 MP and 20 MB per image ([limits](https://matrixify.app/documentation/shopify-limits/)). Generator validates source images ahead of time (size + resolution) and logs oversized ones to a quarantine list; the Images file excludes them.

### 8.9 Kit parent product with `IsAKit=1`

Generator **skips** from `03_products_base.xlsx`. Bundle track (Phase 8 / Pending M-01) handles it, potentially after non-bundle products are created (bundle components must exist first).

### 8.10 Rate limits / large imports

Shopify enforces a 1,000 new variants per 24h window once a store crosses 50k variants (Plus excluded — [limits](https://matrixify.app/documentation/shopify-limits/)). Matrixify queues requests but doesn't bypass this. Plan: run initial bulk during the 24h-window budget on a Plus-tier or chunk creation across days on non-Plus.

### 8.11 Partial failures mid-import

Matrixify's Import Results file flags each failed row individually. Re-run policy: keep the same file, set `Command=MERGE` globally, filter to the failed rows, re-import. No cleanup of successful rows needed.

### 8.12 Rollback of a phase

Matrixify doesn't document an automatic rollback. Manual rollback path per phase:
- Phase 1 (Collections): export current collections, filter by `migration.legacy_source` metafield, import with `Command=DELETE`.
- Phase 2 (Products): same pattern filtered by `migration.legacy_product_id` metafield.
- Phase 4 (Inventory): set qty=0 at each location by re-running with zeros.
- Phase 5 (Links): run the links file with `Product: Command=DELETE`.
- Phase 7 (Redirects): export + re-import with `Command=DELETE`.

### 8.13 Two-pass cross-references

`product.related_products` / `product.upsell_products` can only be populated after all target products have Shopify IDs. This is why Phase 6 is separate from Phase 2.

### 8.14 Tag overwrites on re-run

Default `Tags Command=MERGE` preserves existing tags. If the generator recomputes tags and wants to overwrite, use `Tags Command=REPLACE` explicitly and include all tags (missing tags will be removed).

---

## 9. New Pendings specific to Matrixify

These supplement the P-## list from plan #1 and are specific to the Matrixify transport layer.

| ID | Topic | Blocks |
|---|---|---|
| M-01 | Whether Matrixify Products sheet can create a Shopify bundle (component relationships). Docs reviewed do not show it. | Kit migration phase. |
| M-02 | True dry-run capability vs. using `Command=IGNORE` + small subset | Safe testing strategy. |
| M-03 | Automatic rollback for a failed import | Recovery strategy. |
| M-04 | Does Matrixify auto-create 301 redirects when a Handle changes? | Redirect strategy. |
| M-05 | Whether `Document` / `RelatedDocuments` migrate via the Files sheet or need a separate path | Document migration. |
| M-06 | Shopify product-taxonomy `Category: Name` mapping (separate from Custom Collections) | Product categorization for Shop search. |
| M-07 | Authoritative `source WarehouseLocation → Shopify Location Name` map | All inventory writes. |
| M-08 | Currency/decimal format expected by Matrixify in Price columns (locale-dependent? point vs comma?) | Price column formatting. |
| M-09 | Confirmation that `Variant Image` accepts a filename that also appears in `Image Src` | Variant-image linking. |
| M-10 | Matrixify's exact behavior for `Image Command=REPLACE` vs `MERGE` when bytes change but URL doesn't | Incremental image updates. |

---

## 10. Summary — what this plan decided

- **Matrixify is the transport**. The generator (separate project) produces the Excel files.
- **Eight files** (`01` → `08`), one per phase, each with a single concern.
- **Identification**: `ID` after first load; `Handle` as the secondary key; `Variant SKU` only as a fallback.
- **Commands**: `NEW` on first load per phase, `MERGE` thereafter. `REPLACE` only with explicit justification.
- **Location-keyed inventory** requires the source→Shopify location map to exist before Phase 4.
- **All P-## Pendings from plan #1 still apply**, plus 10 Matrixify-specific ones (M-01 … M-10).
- **Kits, subscriptions, downloads, reviews, B2B pricing, tax** do **not** run through the Products sheet in this plan; each has a separate phase and a blocking Pending.

Next step (when this plan is approved): write plan #3 — the generator design (DB-side queries, row-composition pseudocode for each of the 8 files, idempotency and ID-map persistence, and the validation/linting that runs before each Matrixify upload).
