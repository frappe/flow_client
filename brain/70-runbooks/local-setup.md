---
type: runbook
measured: 2026-09-19 on Ubuntu 26.04 (WSL2), laptop MSI
---
# Local setup — the Flow bench

Full rationale: `FLOW-LOCAL-BENCH-19SEP.md` (outside the repo). Versions match production:
Frappe **v16.31.0**, MariaDB **11.8.8**, litellm **1.83.7**; Python 3.14 (uv-managed), Node 24 via nvm.

Root-only prerequisites (Ubuntu doesn't ship them; GitHub's CI runner does):
`pkg-config default-libmysqlclient-dev mariadb-client` — plus `jq` for the harness hooks.

```bash
# services — same images as upstream CI, bound to 127.0.0.1 only
docker start flow-dev-mariadb flow-dev-redis

# every shell
export PATH="$HOME/.local/bin:$PATH"

# rebuild from scratch (only if ~/code/flow-bench is gone)
( . "$HOME/.nvm/nvm.sh" && nvm use 24 && cd ~/code && bench init flow-bench --frappe-branch v16.31.0 --python "$(uv python find 3.14)" --skip-redis-config-generation )
( cd ~/code/flow-bench && bench set-config -g redis_cache redis://127.0.0.1:6379 && bench set-config -g redis_queue redis://127.0.0.1:6379 && bench set-config -g redis_socketio redis://127.0.0.1:6379 )
( cd ~/code/flow-bench && ln -s ~/code/veyqon-flow apps/flow && uv pip install -e apps/flow --python env/bin/python && printf 'frappe\nflow\n' > sites/apps.txt )
( cd ~/code/flow-bench && bench new-site flow.localhost --db-root-username root --db-root-password root --admin-password admin --mariadb-user-host-login-scope='%' && bench --site flow.localhost install-app flow && bench --site flow.localhost set-config allow_tests true )
```

### Test-only dependency: freezegun (added 19 Sep 2026)

Frappe v16.31.0 declares `freezegun~=1.5.1` in its `test` extra
(`apps/frappe/pyproject.toml:132-138`) and pins `~=1.5.5` for bench
(`apps/frappe/pyproject.toml:159`), and `self.freeze_time(...)`
(`apps/frappe/frappe/tests/classes/context_managers.py:26-44`) is built on it — but bench installs
every app with a bare editable install and no extras (`uv pip install -e {app_path}`,
`~/.local/share/uv/tools/frappe-bench/lib/python3.14/site-packages/bench/app.py:939`), so the `test`
extra is never pulled in: freezegun is absent on a fresh bench and any test that freezes time errors
on import. Install it into the bench env, not into this repo:

```bash
( cd ~/code/flow-bench && uv pip install 'freezegun~=1.5.1' --python env/bin/python )
```

Measured 19 Sep 2026: bench env has freezegun 1.5.5. It is a *test* dependency only — nothing in
`flow/` imports it at runtime, and it is deliberately NOT added to this app's `pyproject.toml`,
because the version that matters is the one the platform already declares.

**Wanted, not done:** `scripts/doctor.sh` has no check for freezegun, so a rebuilt bench would fail
tests with an ImportError rather than a clear DOCTOR=RED. The harness is owner-only; noted for him.

`root`/`admin` are throwaway local values for a database only this laptop can reach. Never reuse them.

Gotchas measured on 19 Sep 2026:
- `bench init` exits 0 after failing and rolling back. Judge by `import frappe, MySQLdb`.
- `bench run-tests` exits 0 when zero tests are discovered. Use `scripts/run-tests.sh`.
- Ports 8000–8005/9000–9005 are taken by `devcontainer-frappe-1`. Tests don't need them; before
  `bench start`, move this bench's `webserver_port`/`socketio_port`.

[[MOC]]
