# ERPNext Migration (v12 → v16)

## 1. Apps

```json
{
	"frappe": "v16.0.0-beta.2",
	"erpnext": "v16.0.0-beta.2",
	"rohit_common": "fix--for-version-15",
	"india_compliance": "16.2.0"
}
```

## 2. Restore Backup

```bench --site testing.localhost restore ./RIGPL_BACK/backup.sql.gz --force```

## 3. Run Pre-Migrate Fix

```bench --site testing.localhost mariadb < apps/rohit_common/rohit_common/scripts/pre_migrate_fix.sql```

## 4. Migrate

```bench --site testing.localhost migrate --skip-failing```