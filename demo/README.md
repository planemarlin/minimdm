# Demo Data

Sample data for the `nordkraft` schema — a fictional furniture distribution company.
Use these files to populate a fresh miniMDM instance for screenshots, demos, or exploration.

## Schema

The `nordkraft` schema is defined in `config/minimdm.example.yaml` as a second schema
alongside the built-in example. Copy it into your `config/minimdm.yaml` to use it.

## Import order

Import in this order so that parent and reference relationships can be linked after import:

1. **Product Categories** — `product_categories.csv`
2. **Suppliers** — `suppliers.csv`
3. **Customers** — `customers.csv`
4. **Products** — `products.csv`

## Importing

In the miniMDM UI, navigate to an object, click **Import**, choose CSV, and upload the
corresponding file. Use the `code` or `sku` field as the upsert key if you want to
re-import without creating duplicates.

## Linking products to categories and suppliers

The `products.csv` file does not include the parent category or preferred supplier columns
because those require UUIDs that are only known after import. After importing, open each
product record and set the **Product Category** (parent) and **Preferred Supplier**
(reference) fields manually, or export the categories/suppliers to get their UUIDs and
re-import products with those columns filled in.
