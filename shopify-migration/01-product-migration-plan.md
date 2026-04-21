# Product Migration Plan — Source DB → Shopify

> **Scope of this document:** field-by-field mapping of the source database (`database-knowledge/`) to the Shopify Admin API product model. This is **step 1 — data relation mapping only**. It does not include the ETL tooling, scripts, or execution plan; those will be produced after the mapping is approved.
>
> **Sources used**
> - Source DB: [`database-knowledge/02-tables-and-columns.csv`](../database-knowledge/02-tables-and-columns.csv), [`database-knowledge/03-tables-summary.csv`](../database-knowledge/03-tables-summary.csv), [`database-knowledge/03-primary-keys.csv`](../database-knowledge/03-primary-keys.csv), [`database-knowledge/01-full-schema.sql`](../database-knowledge/01-full-schema.sql).
> - Shopify: Admin GraphQL API official documentation (shopify.dev), accessed through the Shopify Dev MCP.
>
> **Rules followed**
> - Nothing is invented. If the source schema doesn't contain the data or the Shopify model doesn't expose a target, the item goes to **Pending Decisions** instead of being "best-guessed" into a field.
> - Column-level mappings are only listed when both sides are confirmed by the sources above.

---

## 1. Source-side model (what we have in the DB)

These are the tables directly involved in representing a product. Column lists reflect `02-tables-and-columns.csv`.

### 1.1 Core product tables

| Source table | Role | Primary key | Notes from `02-tables-and-columns.csv` |
|---|---|---|---|
| `Product` | Parent product record | `ProductID` | 64 columns. Holds title, descriptions, SEO fields, product-level flags (e.g. `IsAKit`, `HidePriceUntilCart`, `IsCalltoOrder`, `RequiresTextOption`), and housekeeping (`CreatedOn`, `UpdatedOn`, `Deleted`). |
| `ProductVariant` | Priced/SKU'd variant under a product | `VariantID` | 57 columns. Holds `Price`, `SalePrice`, `MSRP`, `Cost`, `Weight`, `SKUSuffix`, `Colors`, `Sizes`, `ColorSKUModifiers`, `SizeSKUModifiers`, `Inventory`, `GTIN`, `IsDownload`/`DownloadLocation`, `IsRecurring`/`RecurringInterval`/`RecurringIntervalType`, `RewardPoints`, `RestrictedQuantities`, `MinimumQuantity`, `CustomerEntersPrice`, `Condition`. |
| `Inventory` | Per-combination stock (Color × Size) | `InventoryID` | Holds `VariantID`, `Color`, `Size`, `Quan`, `VendorFullSKU`, `VendorID`, `WarehouseLocation`, `WeightDelta`, `GTIN`. This is where the effective "variant" breakdown lives when `ProductVariant.Colors`/`Sizes` is a delimited list. |
| `ProductType` | Taxonomy type (also carries `TaxClassID`) | `ProductTypeID` | Columns: `Name`, `DisplayOrder`, `TaxClassID`. |

### 1.2 Taxonomy / grouping tables (many-to-many join tables in bold)

| Source table | Role | Primary key |
|---|---|---|
| `Category` (hierarchical via `ParentCategoryID`) | Storefront category tree | `CategoryID` |
| `Section` (hierarchical via `ParentSectionID`) | Secondary grouping | `SectionID` |
| `Manufacturer` (hierarchical via `ParentManufacturerID`) | Brand | `ManufacturerID` |
| `Genre` (hierarchical via `ParentGenreID`) | Additional grouping | `GenreID` |
| `Vector` | Additional grouping | `VectorID` |
| `Library` (hierarchical via `ParentLibraryID`) | Content/grouping | `LibraryID` |
| **`ProductCategory`** | Product ↔ Category | composite |
| **`ProductSection`** | Product ↔ Section | composite |
| **`ProductManufacturer`** | Product ↔ Manufacturer | composite |
| **`ProductGenre`** | Product ↔ Genre | composite |
| **`ProductVector`** | Product ↔ Vector | composite |

### 1.3 Kits (bundles) and related

| Source table | Role | Primary key |
|---|---|---|
| `KitGroup` | A group inside a kit (belongs to a `Product` where `IsAKit=1`) | `KitGroupID` |
| `KitGroupType` | Group type (dropdown, checklist, etc.) | `KitGroupTypeID` |
| `KitItem` | Selectable option inside a `KitGroup` (with `PriceDelta`, `WeightDelta`, optional `InventoryVariantID`) | `KitItemID` |

### 1.4 Other directly-product-related tables

| Source table | Role |
|---|---|
| `Rating` | Reviews and ratings per product. |
| `ProductView` | Analytics (customer view events). |
| `ProductCustomerLevel` | Product ↔ customer tier (tiered pricing / visibility). |
| `ProductStore` | Product ↔ Store (multi-store scoping). |
| `ProductLocaleSetting` | Product ↔ Locale (localized copy). |

---

## 2. Target-side model (Shopify Admin API)

Confirmed from Shopify Admin GraphQL documentation.

- **`Product`** — top-level object. Create/update inputs (`ProductCreateInput`, `ProductUpdateInput`, `ProductSetInput`) expose: `title`, `handle`, `descriptionHtml`, `productType`, `vendor`, `tags`, `status` (`ACTIVE` / `DRAFT` / `ARCHIVED`), `seo` (`title`, `description`), `category` (taxonomy), `collectionsToJoin` / `collectionsToLeave`, `productOptions`, `metafields`, `templateSuffix`, `giftCard`, `requiresSellingPlan`.
- **`ProductOption`** — up to **three** per product, no limit on option values. Created through `productOptionsCreate` or inline via `productSet`.
- **`ProductVariant`** — one per option-value combination. Create/update inputs expose: `sku`, `barcode`, `price`, `compareAtPrice`, `taxable`, `taxCode`, `inventoryPolicy` (`DENY` / `CONTINUE`), `inventoryItem` (see below), `inventoryQuantities` (per location), `optionValues` (links variant to option values), `metafields`, `requiresComponents`.
- **`InventoryItem`** — carries `cost` (unit cost), `tracked`, `countryCodeOfOrigin`, `provinceCodeOfOrigin`, `harmonizedSystemCode`, `countryHarmonizedSystemCodes`, and measurement (weight).
- **`Collection`** — grouping entity. Two kinds: **Custom** (manual membership) and **Smart** (rule-based). Has `title`, `handle`, `descriptionHtml`, `image`, `seo`, `templateSuffix`, `sortOrder`, `ruleSet` (smart only), `publications`.
- **`Metafield`** — extensible key/value attached to almost any resource (owner types include `PRODUCT`, `PRODUCTVARIANT`, `COLLECTION`, and more). Defined by `MetafieldDefinition` (type, validations, access).
- **Media** — attached to a product through `productSet` / `productUpdate` (image/video/3D). Each media item supports `alt`. Variant-level image is done by linking media to variants.

> Important Shopify constraints observed in the docs and to be remembered during mapping:
> - Maximum **3 options per product**.
> - `tags` on a product is a single list of strings (updates overwrite; use `tagsAdd` to append).
> - Total inventory quantities across all variants in a single `productSet` mutation can't exceed 50,000.

---

## 3. Entity-level mapping (DB → Shopify)

| Source entity | Target Shopify entity | Relationship type | Notes |
|---|---|---|---|
| `Product` | `Product` | 1:1 | One Shopify product per source `Product` row (filter `Deleted=0`, see §6). |
| `ProductVariant` + `Inventory` | `ProductVariant` (+ `InventoryItem`, `InventoryLevel`) | N:1 to Shopify Product | The effective variant list is the **cartesian product** of `Colors` × `Sizes` expressed in `ProductVariant`, plus any extra combinations materialized in `Inventory`. Reconciliation rule — see §5.1. |
| `ProductType` | `Product.productType` (string) | N:1 | Lookup `ProductType.Name` by `Product.ProductTypeID`. |
| `Manufacturer` (via `ProductManufacturer`) | `Product.vendor` (string) | N:1 | Shopify `vendor` is a single string per product. If a product has multiple manufacturers in the source, see **Pending P-02**. |
| `Category` (via `ProductCategory`) | `Collection` (Custom) + `Product.collectionsToJoin` | N:N | Each `Category` row becomes one Custom Collection. Hierarchy — see **Pending P-01**. |
| `Section` (via `ProductSection`) | `Collection` (Custom) + `Product.collectionsToJoin` | N:N | Same as Category. Hierarchy — see **Pending P-01**. |
| `Genre` (via `ProductGenre`) | `Collection` (Custom) + `Product.collectionsToJoin` | N:N | Same as Category. |
| `Vector` (via `ProductVector`) | `Collection` (Custom) + `Product.collectionsToJoin` | N:N | Same as Category. |
| `Library` | — | — | **Pending P-03** — role of `Library` vs `Category` not confirmed from schema alone. |
| `KitGroup` + `KitItem` + `KitGroupType` (products where `IsAKit=1`) | Product bundles via `productBundleCreate` (Shopify fixed bundles) | — | **Pending P-04** — source kits support `IsRequired`, `IsReadOnly`, `TextOptionMaxLength`, `PriceDelta`, `WeightDelta`, `InventoryVariantID`, which don't all map to Shopify fixed bundles. |
| `Rating` | Reviews app (Shopify Product Reviews, Judge.me, etc.) | 1:N | **Pending P-05** — out of scope for core product import; handled after product import via an app's own import path. |
| `ProductView` | — | — | Analytics/session data. Not migrated. |
| `ProductCustomerLevel` | B2B Catalog / Price List | — | **Pending P-06** — customer-tier pricing depends on plan (Shopify Plus B2B) and out of scope for the core Product object. |
| `ProductStore` | Markets / Publications | — | **Pending P-07** — multi-store scope needs to be confirmed (single Shopify store vs. Markets vs. multiple stores). |
| `ProductLocaleSetting` | Translated content (`Translation` resource) | N:N | **Pending P-08** — localized copy migration is a separate track. |

---

## 4. Field-by-field mapping

Legend:
- ✅ direct mapping, confirmed by both schemas.
- 🧩 mapped with transformation (see the Notes column).
- 🏷️ mapped to a **metafield** (keeps the data; no native Shopify field).
- ⚠️ mapped only conditionally or with loss — see Pending.
- ❓ no confirmed target — see Pending.

### 4.1 `Product` → Shopify `Product`

| DB column | DB type | Shopify target | Kind | Notes |
|---|---|---|---|---|
| `ProductID` | int | metafield `migration.legacy_product_id` (namespace/key TBD) | 🏷️ | Needed so that product joins, external links, and re-runs can resolve source → target. |
| `ProductGUID` | uniqueidentifier | metafield `migration.legacy_product_guid` | 🏷️ | Preserves original identifier. |
| `Name` | nvarchar(400) | `title` | ✅ | |
| `Summary` | nvarchar(MAX) | metafield `product.summary` | 🏷️ | Shopify has no separate "summary" field distinct from `descriptionHtml`. Using a metafield keeps the data. |
| `Description` | nvarchar(MAX) | `descriptionHtml` | ✅ | Source is HTML-capable; Shopify accepts HTML. |
| `SEKeywords` | nvarchar(MAX) | metafield `seo.keywords` | 🏷️ | Shopify `seo` input only has `title` and `description`; no native keywords field. |
| `SEDescription` | nvarchar(MAX) | `seo.description` | ✅ | |
| `SETitle` | nvarchar(MAX) | `seo.title` | ✅ | |
| `SEName` | nvarchar(150) | `handle` | 🧩 | Must be lowercased, URL-safe, hyphenated. Shopify autogenerates from `title` if omitted; explicitly carrying `SEName` preserves existing URLs. Source→target URL redirects are a separate concern. |
| `SEAltText` | nvarchar(MAX) | media `alt` on the **primary** image | ⚠️ | Shopify's image `alt` is per-media; the source stores one product-level value. Apply to the first/primary image only. |
| `SKU` | nvarchar(50) | feeds `ProductVariant.sku` (see §4.2) | 🧩 | In Shopify, SKU is per-variant, not per-product. The source product-level `SKU` combines with `ProductVariant.SKUSuffix` + `Colors`/`Sizes` SKU modifiers to form the final SKU. |
| `ManufacturerPartNumber` | nvarchar(450) | metafield `product.manufacturer_part_number` | 🏷️ | No first-class Shopify field. `barcode` is used for GTIN/UPC, not MPN. |
| `ProductTypeID` | int | `productType` | 🧩 | Resolve `ProductType.Name`. |
| `TaxClassID` | int | — | ⚠️ | **Pending P-09** — Shopify taxation is configured at store/location level or via tax overrides per collection; source-side tax class doesn't have a 1:1 product field. |
| `Published` | tinyint | `status` | 🧩 | `Published=1 & Deleted=0` → `ACTIVE`. `Published=0 & Deleted=0` → `DRAFT`. `Deleted=1` → `ARCHIVED` (or skip entirely; **Pending P-10**). |
| `Deleted` | tinyint | see `Published` row | 🧩 | |
| `IsFeatured` | tinyint | `tags` (add `"featured"`) | 🧩 | Featured flag has no dedicated Shopify field; tag is the idiomatic equivalent. |
| `IsFeaturedTeaser` | ntext | metafield `product.featured_teaser` | 🏷️ | |
| `IsAKit` | tinyint | routes to bundle migration pipeline | ⚠️ | **Pending P-04**. If `IsAKit=1`, the source record is a bundle parent and maps to `productBundleCreate`, not a plain product. |
| `TrackInventoryBySizeAndColor` | tinyint | feeds variant materialization (see §5.1) | 🧩 | Controls whether a product has variants at all. |
| `TrackInventoryBySize` / `TrackInventoryByColor` | tinyint | feeds variant materialization | 🧩 | Same — see §5.1. |
| `SizeOptionPrompt` / `ColorOptionPrompt` | nvarchar(MAX) | `ProductOption.name` for that option | 🧩 | When present and non-empty, use the prompt text as the option name instead of the default "Size"/"Color". |
| `TextOptionPrompt` | nvarchar(MAX) | — | ❓ | **Pending P-11** — text option (engraving) prompt is consumed at checkout via line item properties, which are theme/app concerns, not Product API. |
| `RequiresTextOption` / `TextOptionMaxLength` | tinyint / int | — | ❓ | **Pending P-11**. |
| `XmlPackage` | nvarchar(100) | `templateSuffix` | ⚠️ | **Pending P-12** — `XmlPackage` names identify a storefront rendering template in the source; they may or may not have a Shopify theme template with the same slug. Direct copy is not safe. |
| `TemplateName` | nvarchar(50) | `templateSuffix` | ⚠️ | Same as `XmlPackage`. **Pending P-12**. |
| `SalesPromptID` | int | — | ❓ | **Pending P-13** — Not a product-level Shopify field. |
| `ColWidth` | int | — | ❌ | Storefront layout setting; not migrated. |
| `ShowInProductBrowser` | int | publication scoping / tag | ⚠️ | **Pending P-14** — affects visibility in a product browser UI; Shopify analogue depends on whether we use a "hidden" tag or unpublishing from the Online Store publication. |
| `ShowBuyButton` | int | — | ⚠️ | **Pending P-15** — no direct Shopify flag; closest analogue is `inventoryPolicy=DENY` with zero stock, or a custom theme. |
| `HidePriceUntilCart` | tinyint | — | ❓ | **Pending P-16** — theme-level behavior. |
| `IsCalltoOrder` | tinyint | `tags` (add `"call-to-order"`) | 🧩 | **Pending P-17** — tag is the minimum migration; UX requires theme. |
| `RequiresRegistration` | tinyint | — | ⚠️ | **Pending P-18** — Shopify has customer accounts but product-level "requires login" is not native. |
| `Wholesale` | tinyint | B2B Catalog / tag | ⚠️ | **Pending P-19** — depends on B2B strategy. |
| `ExcludeFromPriceFeeds` | tinyint | metafield `product.exclude_from_feeds` | 🏷️ | Downstream feed apps (Google, Facebook) can read this metafield to decide inclusion. |
| `FroogleDescription` | nvarchar(MAX) | metafield `google.description` | 🏷️ | Google Merchant apps typically read from a metafield. |
| `GoogleCheckoutAllowed` | tinyint | — | ❌ | Google Checkout is retired. Not migrated. |
| `QuantityDiscountID` | int | — | ❓ | **Pending P-20** — quantity discounts in Shopify are discount/price rules or B2B volume pricing, not a product field. |
| `RelatedProducts` | nvarchar(MAX) | metafield `product.related_products` (list of product references) | 🏷️ | Shopify's "Related products" widget is typically app- or theme-driven. Metafield of type `list.product_reference` captures the link. **Pending P-21** — requires a second pass after all products are created to resolve IDs. |
| `UpsellProducts` | nvarchar(MAX) | metafield `product.upsell_products` | 🏷️ | Same caveat as `RelatedProducts`. |
| `UpsellProductDiscountPercentage` | money | metafield `product.upsell_discount_pct` | 🏷️ | |
| `RelatedDocuments` | nvarchar(MAX) | — | ❓ | **Pending P-22** — documents are a separate entity; mapping depends on whether docs become `File` uploads or metaobjects. |
| `RequiresProducts` | nvarchar(MAX) | — | ❓ | **Pending P-23** — "requires other products to be in cart" is not a native Shopify product attribute. |
| `Notes` | nvarchar(MAX) | metafield `product.internal_notes` (admin-only access) | 🏷️ | Internal/private. |
| `MiscText` | nvarchar(MAX) | metafield `product.misc_text` | 🏷️ | |
| `WarehouseLocation` | nvarchar(100) | feeds `InventoryItem` / location assignment | ⚠️ | **Pending P-24** — Shopify uses discrete `Location` entities. Free-text WarehouseLocation must be resolved to a real `Location` ID before inventory can be written. |
| `RequiresAdditionalProductionTime` | tinyint | metafield `product.requires_additional_production_time` | 🏷️ | |
| `AdditionalProductDays` | int | metafield `product.additional_production_days` | 🏷️ | |
| `SwatchImageMap` | nvarchar(MAX) | — | ❓ | **Pending P-25** — Shopify supports "swatch" images per option value, but the schema (`ProductOptionValueSwatch`) is a separate Shopify feature; mapping from a serialized string needs format confirmation. |
| `ImageFilenameOverride` | nvarchar(MAX) | media source | 🧩 | Treated as the primary image filename when uploading media. The actual file list comes from source file storage (see **Pending P-26**). |
| `ExtensionData` / `ExtensionData2`..`5` | nvarchar(MAX) | metafield `product.extension_data_1..5` (only if non-empty) | 🏷️ | Generic extension slots are preserved verbatim; interpretation is out of scope. |
| `Looks` | int | — | ❌ | View counter, not migrated. |
| `Notes`, `ColWidth`, `PageSize`, `SkinID`, `IsImport`, `IsSystem` | — | — | ❌ | Internal/admin/display housekeeping, not migrated. |
| `CreatedOn` | datetime | metafield `migration.source_created_on` | 🏷️ | Shopify sets its own `createdAt`; preserve the source timestamp in a metafield. |
| `UpdatedOn` | datetime | metafield `migration.source_updated_on` | 🏷️ | Same. |

### 4.2 `ProductVariant` (+ `Inventory`) → Shopify `ProductVariant`

> Before mapping: the **variant materialization rule** (how many Shopify variants each DB product produces) is defined in §5.1. This table assumes the variants have already been materialized and we are mapping **one target variant**.

| DB column | DB type | Shopify target | Kind | Notes |
|---|---|---|---|---|
| `VariantID` | int | metafield `migration.legacy_variant_id` | 🏷️ | |
| `VariantGUID` | uniqueidentifier | metafield `migration.legacy_variant_guid` | 🏷️ | |
| `Name` | nvarchar(400) | — | ⚠️ | In Shopify, a variant's "title" is derived from its option values; it can't be set directly in `ProductVariantsBulkInput`/`ProductVariantSetInput`. **Pending P-27**. |
| `Description` | nvarchar(MAX) | metafield `variant.description` | 🏷️ | Variants don't have their own `descriptionHtml` in Shopify. |
| `SEKeywords` / `SEDescription` / `SEName` | nvarchar(MAX) | — | ❌ | Shopify SEO exists only at Product level. Not mapped at variant level. |
| `ProductID` | int | parent product resolution | 🧩 | Used to find the Shopify Product GID. |
| `IsDefault` | int | `position = 1` on the target variant | 🧩 | Shopify positions variants; the default (`IsDefault=1`) becomes `position=1`. |
| `SKUSuffix` | nvarchar(50) | feeds `sku` (see §5.2) | 🧩 | |
| `Colors` / `Sizes` | nvarchar(MAX) | `ProductOption` values | 🧩 | Parsed as delimited lists, feeds option value creation. |
| `ColorSKUModifiers` / `SizeSKUModifiers` | nvarchar(MAX) | feeds `sku` (see §5.2) | 🧩 | |
| `ManufacturerPartNumber` | nvarchar(450) | metafield `variant.manufacturer_part_number` | 🏷️ | |
| `Price` | money | `price` | ✅ | Currency is store-wide; no currency code on the money field in the source. **Pending P-28**. |
| `SalePrice` | money | `price` (while sale active) | 🧩 | Shopify convention: `price` is the customer-facing sell price; `compareAtPrice` is the higher reference price shown struck-through. See §5.3 for the exact promotion logic. |
| `MSRP` | money | `compareAtPrice` (fallback when no sale) | 🧩 | See §5.3. |
| `Cost` | money | `inventoryItem.cost` | ✅ | |
| `Weight` | money | `inventoryItem.measurement.weight` | 🧩 | **Pending P-29** — unit (lb/kg/g/oz) is not captured in the source column; need to confirm the shop's weight unit convention. |
| `Dimensions` | nvarchar(100) | metafield `variant.dimensions` | 🏷️ | Free-text; Shopify has no structured variant dimensions field. |
| `Inventory` | int | `inventoryQuantities` at one `Location` when **no Color/Size tracking** | 🧩 | When `TrackInventoryBySizeAndColor=1`, this field is ignored and per-combination stock comes from the `Inventory` table instead. |
| `DisplayOrder` | int | variant `position` | 🧩 | Tie-break: `IsDefault=1` wins over `DisplayOrder`. |
| `IsTaxable` | tinyint | `taxable` | ✅ | |
| `IsShipSeparately` | tinyint | — | ⚠️ | **Pending P-30** — no native Shopify flag; can be modeled via Shopify Shipping Profiles or custom logic. |
| `IsDownload` / `DownloadLocation` | tinyint / nvarchar(MAX) | Digital Downloads app | ⚠️ | **Pending P-31** — Shopify's Product API doesn't host downloads natively; the Shopify "Digital Downloads" app or a third-party app is required. |
| `FreeShipping` | tinyint | shipping profile assignment | ⚠️ | **Pending P-30**. |
| `Published` | tinyint | variant existence / product `status` | 🧩 | Shopify variants don't have their own `status`. If every variant under a product has `Published=0`, product `status` should be `DRAFT`; partially-unpublished variants need a policy — **Pending P-32**. |
| `IsSecureAttachment` | tinyint | — | ❓ | **Pending P-33**. |
| `IsRecurring` / `RecurringInterval` / `RecurringIntervalType` | tinyint / int / int | Selling Plans | ⚠️ | **Pending P-34** — Shopify subscriptions go through Selling Plan Groups + a subscriptions app; the source's per-variant boolean doesn't cleanly map. |
| `RewardPoints` / `Points` | int | Loyalty app | ❌ | **Pending P-35** — not a product API concern. |
| `SEAltText` | nvarchar(MAX) | variant media `alt` | 🧩 | Apply only if the variant has its own image. |
| `RestrictedQuantities` | nvarchar(250) | metafield `variant.restricted_quantities` | 🏷️ | Enforcement at checkout is a separate concern. **Pending P-36**. |
| `MinimumQuantity` | int | metafield `variant.min_qty` | 🏷️ | Enforcement requires a Shopify Function or theme/script. **Pending P-37**. |
| `CustomerEntersPrice` / `CustomerEntersPricePrompt` | tinyint / nvarchar(MAX) | — | ❓ | **Pending P-38** — no native Shopify equivalent. |
| `Condition` | tinyint | metafield `variant.condition` (or `tags` at product level) | 🏷️ | Enum mapping (new/used/refurbished) needs source legend — **Pending P-39**. |
| `GTIN` | nvarchar(14) | `barcode` | ✅ | |
| `HasTurboPartnerService` | int | metafield `variant.has_turbo_partner_service` | 🏷️ | Business-specific flag. |
| `DownloadValidDays` | int | digital downloads app config | ⚠️ | **Pending P-31**. |
| `ImageFilenameOverride` | nvarchar(MAX) | variant-media link | 🧩 | Upload media, then link to the variant. |
| `ExtensionData`..`ExtensionData5` | nvarchar(MAX) | metafields | 🏷️ | |
| `IsImport`, `IsSystem` | — | — | ❌ | Housekeeping, not migrated. |
| `CreatedOn` / `UpdatedOn` | datetime | metafields `migration.source_created_on` / `source_updated_on` | 🏷️ | |

### 4.3 `Inventory` (per Color × Size) → Shopify `ProductVariant` + `InventoryLevel`

| DB column | DB type | Shopify target | Kind | Notes |
|---|---|---|---|---|
| `InventoryID` | int | metafield `migration.legacy_inventory_id` on variant | 🏷️ | |
| `VariantID` | int | parent `ProductVariant` resolution | 🧩 | |
| `Color` | nvarchar(100) | `optionValues` (value for "Color" option) | 🧩 | |
| `Size` | nvarchar(100) | `optionValues` (value for "Size" option) | 🧩 | |
| `Quan` | int | `inventoryQuantities.quantity` at a specific `Location` | 🧩 | **Pending P-24** — target `Location` must be resolved from `WarehouseLocation`. |
| `VendorFullSKU` | nvarchar(50) | `sku` (override when present) | 🧩 | See §5.2 for the exact rule between computed SKU vs. `VendorFullSKU`. **Pending P-40**. |
| `VendorID` | nvarchar(50) | metafield `inventory.vendor_id` | 🏷️ | |
| `WarehouseLocation` | nvarchar(MAX) | `Location` resolution | 🧩 | **Pending P-24**. |
| `WeightDelta` | money | adjusts `inventoryItem.measurement.weight` | 🧩 | The source models weight per combination as `Variant.Weight + WeightDelta`. Shopify has no "delta"; the computed absolute weight goes onto the `InventoryItem`. |
| `GTIN` | nvarchar(14) | `barcode` (overrides variant-level GTIN if present) | 🧩 | |
| `ExtensionData` | nvarchar(MAX) | metafield `variant.inventory_extension_data` | 🏷️ | |
| `CreatedOn` / `UpdatedOn` | datetime | metafields | 🏷️ | |

### 4.4 `Category` → Shopify `Collection` (Custom)

| DB column | Shopify target | Kind | Notes |
|---|---|---|---|
| `CategoryID` | metafield `migration.legacy_category_id` on the collection | 🏷️ | |
| `Name` | `title` | ✅ | |
| `Summary` | metafield `collection.summary` | 🏷️ | |
| `Description` | `descriptionHtml` | ✅ | |
| `SEKeywords` | metafield `seo.keywords` on collection | 🏷️ | |
| `SEDescription` | `seo.description` | ✅ | |
| `SETitle` | `seo.title` | ✅ | |
| `SEName` | `handle` | 🧩 | Same rules as product handle. |
| `SEAltText` | collection `image.altText` | 🧩 | If `ImageFilenameOverride` is set. |
| `ImageFilenameOverride` | collection `image` | 🧩 | Upload + attach. |
| `ParentCategoryID` | — | ⚠️ | **Pending P-01** — Shopify collections are flat. Hierarchy is typically modeled via handle prefixes, metafields, or a navigation menu; the final choice affects SEO/URLs. |
| `DisplayPrefix` | — | ❓ | **Pending P-41** — source behavior of `DisplayPrefix` not confirmed from schema alone. |
| `DisplayOrder` | — | ⚠️ | **Pending P-42** — collection ordering on the storefront comes from the navigation menu and theme sort keys; there's no global "display order" field on `Collection`. |
| `SortByLooks` / `PageSize` / `ColWidth` / `SkinID` / `TemplateName` | — | ❌ | Storefront layout; handled by theme. `TemplateName` → `templateSuffix` only if confirmed (**Pending P-12**). |
| `Published` / `Deleted` | `publications` + `status` via `publishablePublish` | 🧩 | Collections are unpublished by default; must explicitly publish. Deleted rows are skipped. |
| `Wholesale` | — | ⚠️ | **Pending P-19**. |
| `ShowInProductBrowser` | — | ⚠️ | Same as Product equivalent. |
| `AllowSectionFiltering` / `AllowManufacturerFiltering` / `AllowProductTypeFiltering` | — | ❌ | Theme-level feature. |
| `QuantityDiscountID` | — | ❓ | **Pending P-20**. |
| `TaxClassID` | — | ❓ | **Pending P-09**. |
| `XmlPackage` | `templateSuffix` | ⚠️ | **Pending P-12**. |
| `ExtensionData` | metafield `collection.extension_data` | 🏷️ | |
| `CreatedOn` / `UpdatedOn` | metafields | 🏷️ | |

### 4.5 `Manufacturer` → Shopify `Product.vendor` + (optional) `Collection`

The primary mapping is **scalar**: `Manufacturer.Name` → `Product.vendor` string on each related product (via `ProductManufacturer`).

Secondary (richer) data on `Manufacturer` (address, `URL`, `Email`, `Description`, `SEName`, `ImageFilenameOverride`, etc.) has **no native Shopify target** at the Product level and would be lost without one of the following strategies — **Pending P-02**:

- Create one Custom Collection per manufacturer and carry descriptive fields there.
- Model manufacturers as a **metaobject** ("Brand") referenced from products via a metafield.

### 4.6 `Section`, `Genre`, `Vector`, `Library` → Shopify `Collection`

Treated the same as `Category`, each row becoming a Custom Collection joined by its mapping table. Hierarchy and `Library` role are captured in **Pending P-01** and **P-03**.

### 4.7 Kits (`KitGroup` / `KitItem` / `KitGroupType` / `Product.IsAKit=1`)

Not a flat column mapping — a product with `IsAKit=1` plus its kit tables becomes a **bundle** in Shopify, created through `productBundleCreate`. See **Pending P-04** for gaps: Shopify fixed bundles don't natively express `IsRequired`, `IsReadOnly`, `TextOptionMaxLength`, `PriceDelta`, `WeightDelta`, `InventoryVariantID`.

### 4.8 `ProductType` → `Product.productType`

Scalar: `ProductType.Name` (looked up by `Product.ProductTypeID`) populates `Product.productType`. `DisplayOrder` isn't migrated. `TaxClassID` is **Pending P-09**.

---

## 5. Transformation rules (non-trivial)

### 5.1 Variant materialization

The source schema has **three** places where per-variant data lives and they must be reconciled deterministically:

1. `ProductVariant` rows — one or more per product. Each holds a delimited `Colors` and `Sizes` list.
2. `Inventory` rows — per-combination stock, keyed by `(VariantID, Color, Size)`.
3. `Product.TrackInventoryBySizeAndColor` / `TrackInventoryBySize` / `TrackInventoryByColor` — flags controlling how the above are interpreted.

Proposed rule (to validate):

- If `TrackInventoryBySizeAndColor=1`: the Shopify variant set is the **set of `(Color, Size)` pairs that appear in `Inventory` for the product**, across all source `ProductVariant` rows. Stock comes from `Inventory.Quan`; SKU is computed per §5.2.
- If `TrackInventoryBySize=1` and `TrackInventoryByColor=0` (or vice versa): Shopify variants are keyed only on the tracked axis; the other axis either doesn't exist or is a single unnamed value.
- If both are 0 and there is exactly one `ProductVariant`: single-variant product (no `ProductOption`s). Stock comes from `ProductVariant.Inventory`.
- If both are 0 and there are multiple `ProductVariant` rows: each source variant becomes a Shopify variant keyed on its `Name` — but this needs **Pending P-43** to confirm, because Shopify still needs at least one `ProductOption` in that case, and source `ProductVariant.Name` is not itself an option value.

Shopify hard limit: **3 options max** per product. If the source product would produce more than 3 option axes, one or more are merged or dropped — **Pending P-44**.

### 5.2 SKU composition

The source builds an effective SKU by concatenating parts. The pieces we see in the schema:

- `Product.SKU` (product-level base).
- `ProductVariant.SKUSuffix`.
- `ProductVariant.ColorSKUModifiers` and `SizeSKUModifiers` — these are delimited modifier strings aligned with `Colors`/`Sizes`, one modifier per value.
- `Inventory.VendorFullSKU` — if present on the `(VariantID, Color, Size)` row, this may be intended to **override** the computed SKU (e.g. vendor's own SKU).

Proposed rule (to validate — **Pending P-40** and **P-45**):

1. If `Inventory.VendorFullSKU` exists for the combination → use it verbatim as the Shopify `sku`.
2. Otherwise → compute `sku = Product.SKU + ProductVariant.SKUSuffix + ColorSKUModifier(forColor) + SizeSKUModifier(forSize)`.

The exact **delimiter and alignment** between `Colors` and `ColorSKUModifiers` needs to be confirmed from production data (both are free-form nvarchar). This is **Pending P-45**.

### 5.3 Price / SalePrice / MSRP → price / compareAtPrice

Shopify's `price` is what the customer pays; `compareAtPrice` is the reference (struck-through) price. The source has three money columns with overlapping semantics.

Proposed rule (to validate — **Pending P-46**):

- If `SalePrice` is not null and > 0 and < `Price` → `price = SalePrice`, `compareAtPrice = Price`.
- Else if `MSRP` is not null and > `Price` → `price = Price`, `compareAtPrice = MSRP`.
- Else → `price = Price`, `compareAtPrice = null`.

This rule hinges on how the source actually drives store-visible pricing (does the storefront use `SalePrice` whenever non-null, or does it gate sales on a separate schedule?). **Pending P-46** — confirm with the source storefront logic.

### 5.4 Handle / SEName uniqueness

Shopify enforces handle uniqueness. If two source rows produce the same normalized `SEName`, a deterministic suffix strategy is needed (e.g. append `-2`, `-3`). **Pending P-47**.

### 5.5 Taxonomy hierarchy

Shopify Collections are flat. The source has four hierarchical taxonomies (`Category`, `Section`, `Manufacturer`, `Genre`, plus `Library`). Options:

a. Flatten — each node is a Collection; parent/child link stored only as a metafield.
b. Flatten + path — handle becomes `parent/child` (not supported; handles can't contain `/`). Alt: `parent-child`.
c. Menu-driven — hierarchy is modeled exclusively in the theme's navigation menu, not on collections themselves.

This is a product-of-migration decision, not a schema fact — **Pending P-01**.

### 5.6 Images / media

The source stores filenames in `Product.ImageFilenameOverride`, `ProductVariant.ImageFilenameOverride`, and implicitly via `Product.SwatchImageMap`. The actual image **bytes** are not in the DB. The plan requires a separate inventory of the source image storage (CDN or filesystem) before media can be uploaded to Shopify. **Pending P-26**.

---

## 6. Filters applied at extract time (what we ship to Shopify)

- `Product.Deleted = 0` (unless archival policy P-10 decides otherwise).
- `Product.IsSystem = 0` (exclude system records).
- Kit parents (`Product.IsAKit = 1`) route to the bundle pipeline, not the regular product pipeline.
- `ProductVariant.Deleted = 0`.
- Categories/Sections/Genres/Vectors/Libraries with `Deleted = 1` are skipped, and their `ProductCategory`/etc. joins are dropped.

---

## 7. Pending Decisions (must be answered before coding the importer)

Nothing below is assumed. Each one needs a concrete answer before the corresponding column becomes executable.

| ID | Pending topic | Blocking what |
|---|---|---|
| P-01 | How to represent the `Category` / `Section` / `Genre` / `Manufacturer` / `Library` hierarchy in Shopify's flat Collection model. | Category/Section/Genre/Manufacturer/Library mapping. |
| P-02 | Products with multiple manufacturers (source N:N): choose one vendor, or model manufacturer as a metaobject. | Vendor field + Manufacturer mapping. |
| P-03 | Role of `Library` vs. `Category` / `Section`. | Whether `Library` becomes Collections at all. |
| P-04 | Mapping Kits with `IsRequired`, `IsReadOnly`, `TextOptionMaxLength`, `PriceDelta`, `WeightDelta`, `InventoryVariantID` onto Shopify fixed bundles (which don't support all of these). | Kit migration. |
| P-05 | Reviews migration (`Rating`, `RatingCommentHelpfulness`, `CompunixReviews*`) target app. | Not blocking product migration; flagged. |
| P-06 | B2B / customer-tier pricing (`ProductCustomerLevel`, `CustomerLevel`, `Wholesale`). | Pricing decisions. |
| P-07 | Multi-store (`ProductStore`): single Shopify store, Markets, or multiple stores. | Scope of export. |
| P-08 | Localization migration (`ProductLocaleSetting`, `LocalizedObjectName`, `StringResource`). | Translated content. |
| P-09 | Tax classes (`TaxClass`, `TaxClassID` on Product/Category/ProductType). | Tax configuration. |
| P-10 | Whether `Deleted=1` rows go as `ARCHIVED` or are skipped. | Extract filter. |
| P-11 | Engraving / text options (`Product.RequiresTextOption`, `TextOptionMaxLength`, `TextOptionPrompt`, `EngravingText*`, `ProductEngraving`, `EngravingProductFormData`, `fsHeaderPlateEngravingText`) — mapping strategy (line item properties via theme vs. product options). | Engraved products migration. |
| P-12 | Safe mapping of `XmlPackage` / `TemplateName` to `templateSuffix`. | Custom-template products. |
| P-13 | Sales prompts (`SalesPrompt`, `SalesPromptID`). | Those products' display. |
| P-14 | `ShowInProductBrowser` target (tag vs. unpublish). | Visibility. |
| P-15 | `ShowBuyButton` target. | UX for non-purchasable products. |
| P-16 | `HidePriceUntilCart`. | Theme work. |
| P-17 | `IsCalltoOrder` UX beyond the tag. | Theme work. |
| P-18 | `RequiresRegistration`. | Gated products. |
| P-19 | Wholesale strategy (`Wholesale`, `AffiliateStore`, `CustomerLevel`). | Pricing tracks. |
| P-20 | Quantity discounts (`QuantityDiscount`, `QuantityDiscountTable`, `QuantityDiscountID`). | Discount migration. |
| P-21 | Two-pass resolution for `RelatedProducts` / `UpsellProducts` metafield references. | Related/upsell data. |
| P-22 | `RelatedDocuments` / `Document` / `DocumentType` migration. | Docs attached to products. |
| P-23 | `RequiresProducts` (must-buy-with). | Cart logic. |
| P-24 | `WarehouseLocation` (free text) → Shopify `Location` (discrete entities). | All inventory writes. |
| P-25 | `SwatchImageMap` parsing format and mapping to Shopify swatches. | Color swatches. |
| P-26 | Source image file inventory (bytes aren't in the DB — `ImageFilenameOverride` is a filename). | All media uploads. |
| P-27 | Variant-level `Name` not settable in Shopify (derived from option values). | Loss of variant `Name`. |
| P-28 | Currency of `Price` / `SalePrice` / `MSRP` / `Cost` (source has no currency code per row). | Price mapping. |
| P-29 | Source weight unit (source `Weight` column has no unit). | Shipping accuracy. |
| P-30 | `IsShipSeparately` / `FreeShipping` via Shipping Profiles. | Shipping rules. |
| P-31 | `IsDownload` / `DownloadLocation` / `DownloadValidDays` → Digital Downloads app. | Digital products. |
| P-32 | Partially-published variants (`ProductVariant.Published` mixed across a product). | Status per variant. |
| P-33 | `IsSecureAttachment` meaning. | Attachment handling. |
| P-34 | Subscriptions (`IsRecurring`, `RecurringInterval`, `RecurringIntervalType`) → Selling Plan Groups. | Subscription products. |
| P-35 | Loyalty / reward points target app (`RewardPoints`, `Points`). | Loyalty integration. |
| P-36 | `RestrictedQuantities` enforcement mechanism. | Cart validation. |
| P-37 | `MinimumQuantity` enforcement (Shopify Function vs. theme). | Cart validation. |
| P-38 | `CustomerEntersPrice` + `CustomerEntersPricePrompt`. | "Name your price" products. |
| P-39 | `Condition` enum legend (0/1/2/... → new/used/refurbished). | Product classification. |
| P-40 | `Inventory.VendorFullSKU` — override of computed SKU or separate field. | SKU composition. |
| P-41 | `Category.DisplayPrefix` meaning. | Collection titles. |
| P-42 | Global collection `DisplayOrder`. | Storefront order. |
| P-43 | Multiple `ProductVariant` rows under a product when neither Size nor Color tracking is on. | Variant materialization. |
| P-44 | Products that exceed Shopify's 3-option limit (Color + Size + something else). | Variant materialization. |
| P-45 | Delimiters and alignment of `Colors` / `Sizes` with `ColorSKUModifiers` / `SizeSKUModifiers`. | SKU composition. |
| P-46 | Exact source logic that decides when `SalePrice` is active (schedule? flag? unconditional?). | price/compareAtPrice rule. |
| P-47 | Handle collision strategy. | Unique handles. |

---

## 8. Open questions to the product owner (highest priority)

These are the ones that need to be answered first because **every other decision hinges on them**:

1. **P-07** — Are we migrating to one Shopify store or several? If one, do the `ProductStore` rows collapse, or do they drive Markets?
2. **P-24 / P-26** — Where does the source image storage live, and how do we resolve `WarehouseLocation` free text to Shopify `Location` IDs?
3. **P-28 / P-29** — Currency and weight units of the source.
4. **P-46** — Is `SalePrice` authoritative whenever non-null, or is there a separate "sale active" flag we haven't surfaced yet?
5. **P-04** — Do we need full kit fidelity (delta pricing, required/readonly groups), or is a "loose" bundle acceptable?

Once those five are answered, ~60% of the remaining Pendings resolve or become trivial.

---

## 9. What this document does **not** cover

- The order / customer / discount / review migrations (separate plans).
- The ETL tooling, batching, rate-limit strategy, or idempotency design.
- Redirect map from source product URLs to Shopify handles.
- Storefront theme work (none of the theme-level Pendings above will be solved in this plan).
