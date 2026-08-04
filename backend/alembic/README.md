# Application database migrations

Alembic owns the application schema. A new database is initialized with only
`pgcrypto`; the baseline revision creates all tables, indexes, constraints, and
the probability skill seed. Existing unversioned databases are adopted by that
revision: known additive columns and missing tables are reconciled, the message
foreign key is normalized to `ON DELETE CASCADE`, and incompatible or unsafe
database changes fail rather than being stamped.

Run migrations from `backend/`:

```bash
alembic upgrade head
alembic current
alembic check
```

Set `DATABASE_URL` for a non-local database. API and worker startup only verify
the revision and never mutate schema; run the migration job first.
