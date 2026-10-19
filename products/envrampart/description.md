# envrampart

### Catch broken `.env` config before it reaches production.

![envrampart check output](preview.png)

A missing `DATABASE_URL`, `PORT=99999`, `DEBUG=maybe`, or a live API key pasted into
`.env.example` can each cause a failed deploy or a security incident.
**envrampart** checks your env files against a small, readable schema in under a second:
on your laptop, in CI, or when your container starts. It reports every problem with
the file and line number and masks secret values.

It's one small Python package that uses only the standard library. There is nothing to
add to your lockfile, no supply-chain risk, and it works with any stack that reads a
`.env` file: Node, Go, Rails, Django, Laravel, or Docker Compose.

---

## Features

- **Validate**: `envrampart check` handles 13 types (string, int, float, bool, port, url, email, host, path, enum, json, duration, list) with `required`, `default`, `choices`, `pattern`, `min`/`max`, `secret` and `deprecated`
- **Layered and 12-factor friendly**: combine `-e .env -e .env.local`, let real environment variables override, and use `--strict` to reject undeclared keys
- **CI-ready**: output as text, JSON, or GitHub annotations (`--format github`) with clear exit codes
- **Bootstrap fast**: `envrampart init` creates a schema from your existing `.env.example`, inferring types and flagging likely secrets
- **Stay in sync**: `envrampart example` generates a safe `.env.example`, and `envrampart docs` renders a Markdown config table for your README
- **Compare environments**: `envrampart diff staging.env prod.env` shows missing or changed keys and never prints values
- **Stop leaks**: `envrampart scan` finds real-looking AWS, GitHub, Stripe live, Slack, Google and OpenAI-style keys, private keys, and URLs with passwords
- **Strict parser**: `export`, both quote styles, escapes, multi-line values, trailing comments and duplicate-key warnings
- **Zero dependencies**: Python 3.8+, Linux, macOS and Windows, 21 unit tests included

## Quick usage

Describe your config, one line per variable:

```text
# .env.schema
APP_ENV       enum  required choices=development|staging|production
PORT          port  default=8080
DATABASE_URL  url   required secret pattern=^postgres(ql)?://   # Primary database
WORKERS       int   min=1 max=64 default=4
```

Then check it:

```console
$ pip install ./envrampart-1.0.0
$ envrampart init .env.example     # optional: generate a starter schema
$ envrampart check -e .env.broken   # bundled broken example (output excerpt)
  error .env.broken:1 APP_ENV must be one of: development, staging, production (got 'prod')
  error .env.broken:2 PORT must be a port number 1-65535 (got '99999')
  error .env.broken:3 DATABASE_URL must match /^postgres(ql)?:/// (got 'my********pp')
  ...
✘ 13 variable(s) checked against .env.schema: 8 error(s), 3 warning(s)
```

Add it to GitHub Actions in two lines:

```yaml
- run: python3 tools/envrampart.py check --env .env.example --format github
- run: python3 tools/envrampart.py scan .env.example
```

## What's included

`envrampart-1.0.0.zip` contains:

- The `envrampart` package (pip-installable, or copy it into `tools/` with no install)
- A full README covering the schema reference, every command and exit codes
- A worked example with a schema, a valid `.env` and a deliberately broken `.env.broken`
- Recipes: GitHub Actions workflow, pre-commit hook and Docker entrypoint
- Test suite (21 tests, standard library `unittest`)
- Commercial `LICENSE`

## Price

**$19** one-time, covering a team of up to 10 developers.
**Launch price: $14.**

## License summary

- ✅ Unlimited personal, commercial and client projects
- ✅ Modify it, and include it in your repos, CI pipelines and container images
- ✅ One purchase covers one person or a team of up to 10 developers
- ❌ Don't resell, republish, or redistribute the tool itself (for example on PyPI or a public repo)
- Provided as-is, with no warranty. The secret scanner uses heuristics.

---

*© 2026 Persline Templates. No third-party dependencies.*
