# ADR 0027: Railway build and deploy settings live in the dashboard

**Status:** accepted, 2026-11-27. Supersedes the "pinned in `railway.json`"
part of [ADR 0004](0004-dockerfile-build-and-healthcheck.md); its decision
(build from the Dockerfile, healthcheck before taking traffic) stands.

**Context.** Railway deprecated config as code (`railway.json` /
`railway.toml`): new services can't use it, and existing services stop reading
it on 2026-12-01. The web service's dashboard still said Nixpacks with no
healthcheck under its `railway.json`, so its first deploy after the cutoff
would have built without the Dockerfile (no `collectstatic`, no `migrate`) and
taken traffic unchecked. Railway's replacement, Infrastructure as Code
(`.railway/railway.ts`), is project-wide by default (a whole-project file
deletes every service it omits; this project has 19 from several repos) and is
applied only by the CLI or a GitHub Action, not on push.

**Decision.**
- The Railway dashboard is the source of truth for build and deploy settings.
  The values are written down in `docs/operations/configuration.md` ("Railway
  build and deploy"), and changes to them are made there and in that table.
- On 2026-11-27 the web service's dashboard was set to the values
  `railway.json` held (builder Dockerfile, `Dockerfile`, healthcheck `/`,
  180 s) and deployed, before the files were removed.
- `railway.json`, `railway.worker.json` and `roombot/railway.json` are
  deleted, and a test fails if a Railway config file is added back.
- Infrastructure as Code (per-repo `partial` files) can come later in its own
  RFC; it isn't needed to keep deploys working.

**Consequences.**
- A settings change is no longer reviewed in a PR. The docs table is the
  record; keep it in step with the dashboard.
- New services (like `roombot`) are set up by hand from that table.
