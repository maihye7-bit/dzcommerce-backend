# Bootstrap scripts

## Owner bootstrap

Create an owner login for an existing store:

```powershell
python scripts/create_owner.py --store-slug dzcommerce --username admin --password "كلمة_سر"
```

The `--username` value is stored in the existing `users.email` login column and
may be a username such as `admin`. The script links that user to the selected
store through `store_users` with the `owner` role. It hashes the password using
the application's Passlib `bcrypt_sha256` scheme; the plaintext password is
never printed.

Run the command from the project root after configuring `DATABASE_URL` and
applying the Alembic migrations. The store must already exist. A username
already present in the database cannot be reused, and rerunning for an owner
already linked to the store exits with a duplicate message.

## Super-admin bootstrap

Promote an existing user to the global dashboard super-admin role:

```powershell
python scripts/make_super_admin.py --username admin
```

The user is updated in-place in the existing `users` table and gains the
`is_super_admin` flag without creating any new store membership. This is intended
for the global dashboard only and does not alter the store owner permissions.

Because command-line arguments may be visible in shell history or process
inspection, use a temporary terminal/session and avoid sharing the command
while it contains a real password. Do not put a production password in source
control or logs.
