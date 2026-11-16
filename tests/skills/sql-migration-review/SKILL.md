---
name: sql-migration-review
description: Reviews SQL schema migrations for locking, data loss and rollback safety before they run in production. Use when a pull request adds or changes a database migration.
---

# SQL migration review

1. Read every migration file in the change. Note which tables it touches and roughly how many rows they hold.
2. Flag operations that lock large tables (adding a column with a default on old engines, building an index without CONCURRENTLY, changing a column type).
3. Flag anything that drops or truncates data, and ask whether a backup or a two-step deploy is planned.
4. Check that a down migration exists and actually reverses the up migration.
5. Report findings as a short list, most dangerous first.
