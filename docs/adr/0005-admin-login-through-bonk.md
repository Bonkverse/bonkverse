# ADR 0005: Admins sign in through bonk.io

**Status:** accepted, 2026-11-03 (#26)

**Context.** Site accounts have no usable password: login goes through bonk.io,
and bonk.io passwords are never stored. The Django admin assumed password login
and `PermissionsMixin`, so `/admin/` crashed for everyone.

**Decision.**
- `BonkUser` gets `PermissionsMixin`.
- `/admin/login/` redirects to the site's bonk.io login and back.
- Superusers are made with `manage.py grant_admin <username>`, never with a
  password.

**Consequences.**
- One way to sign in.
- Admin access depends on bonk.io's login being up.
- Roles are `is_staff` (re-render, admin shell), `is_superuser` (everything),
  and groups for scoped access (e.g. moderators).
- A future Bonkverse-styled staff dashboard reuses these roles.
