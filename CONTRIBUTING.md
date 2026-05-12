# Contributing to VanillaDB

Thanks for your interest. Here's how to get set up and what we're looking for.

## What we're looking for

- Bug fixes with a clear reproduction case
- New ingestion adapters (sources worth supporting)
- LLM provider integrations
- Performance improvements to the agent pipeline or search layer

Open an issue before starting large changes. We'd rather talk design first than review a big PR that goes in a different direction.

## Dev environment

**Requirements:** Node.js 20+, Python 3.10+, Rust (via [rustup](https://rustup.rs))

```bash
git clone https://github.com/sanalvre/VanillaDB
cd VanillaDB

# Frontend
npm install

# Python sidecar
cd sidecar
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[agents,ingestion,dev]"
cd ..
```

Start the full app in dev mode:

```bash
npm run tauri dev
```

## Running tests

```bash
# Python
cd sidecar && pytest ../tests/python/ -v

# TypeScript
npx vitest run
```

All tests must pass before submitting a PR.

## Code style

- Python: follow existing patterns — type hints on public functions, docstrings on non-obvious logic, no external dependencies unless truly necessary
- TypeScript: match the surrounding file's style, keep components focused
- No new dependencies without discussion — the binary size and startup time matter

## Adding an ingestion adapter

Ingestion adapters live in `sidecar/services/ingestion/`. A new adapter should:

1. Accept a URL or file path and return `IngestResult(success, output_path, title, body, error)`
2. Write output to `clean-vault/raw/` via the path passed in
3. Handle errors gracefully — never raise from the adapter itself
4. Be registered in `detect_source_type()` in `normalizer.py`

## Architecture decisions to be aware of

- The Python sidecar is the sole owner of SQLite — the frontend never touches the DB directly
- All vault paths are stored as forward-slash relative paths (`clean-vault/raw/file.md`)
- The knowledge graph lives in SQLite (`graph_nodes`, `graph_edges`, `graph_source_map`) — not a JSON file
- Agents write to `staging/` only; `fileback.py` promotes to `concepts/` after human approval

## Commit style

Use imperative present tense: `Add PubMed ingestion adapter`, not `Added` or `Adding`.

## License

By contributing you agree your changes will be released under the project's [MIT license](LICENSE).
