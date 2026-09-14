# Database migrations

Set `DATABASE_URL` and run from the repository root:

```shell
alembic upgrade head
```

The runner accepts `postgresql+asyncpg://` URLs and uses psycopg2 while applying migrations.
