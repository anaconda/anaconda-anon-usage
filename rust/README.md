# anaconda-anon-usage (Rust crate)

Rust implementation of the Anaconda Anonymous Usage (AAU) token system.
Produces token strings identical to the Python
[anaconda-anon-usage](https://github.com/anaconda/anaconda-anon-usage) package.

## Token format

```
aau/{version} c/{client} s/{session} e/{env} [a/{cloud}] [o/{org}] [m/{machine}] [i/{installer}]
```

| Prefix | Description | Persistence |
|--------|-------------|-------------|
| `c/` | Client (installation) identity | File-backed, tied to MAC address |
| `s/` | Session (process) identity | Random per-process |
| `e/` | Conda environment identity | File-backed per-prefix |
| `a/` | Anaconda Cloud user (from caller-provided JWT) | Caller-provided |
| `o/` | Organization token(s) | Config files or env var |
| `m/` | Machine token(s) | Config files or env var |
| `i/` | Installer token(s) | Config files or env var |

## Library usage

```rust
use anaconda_anon_usage::{Config, token_string, token_details, search_path};

let config = Config {
    env_prefix: Some("/path/to/env".into()),
    ..Default::default()
};

// Simple token string (for User-Agent headers)
let ua = token_string(&config);

// Per-token details (for diagnostics)
for entry in token_details(&config) {
    println!("  {}/{} ({}) <- {}", entry.prefix, entry.value, entry.label, entry.source);
}

// System token search path
for path in search_path() {
    println!("  {}", path.display());
}
```

## Building

```bash
cd rust
cargo build                      # library only
cargo build --features cli       # library + CLI binary
cargo build --features cli --release
```

The crate version is derived automatically from the repository's git tags
using the same PEP 440 convention as Python's versioneer:

| State | Version |
|-------|---------|
| On tag | `0.7.6` |
| Past tag | `0.7.6+3.gabcdef0` |

This requires `fetch-depth: 0` in CI checkouts so that `git describe --tags` works.

## Testing

### Rust unit tests

```bash
cd rust
cargo test --features cli --verbose
```

Unit tests cover token generation, JWT parsing, file I/O,
deferred writes, and validation logic.

### Linting

```bash
cargo fmt --check
cargo clippy --features cli -- -D warnings
```

Both are enforced by pre-commit hooks and CI.

### Python parity tests

From the repository root (requires the Python `anaconda-anon-usage` package
installed and the Rust binary built):

```bash
cd rust && cargo build --features cli
cd ..
pytest tests/test_rust_parity.py -v
```

30 parity tests verify that the Rust crate produces identical tokens to the
Python package across all token types, including version alignment, format
validation, file-backed token reads, environment variable handling,
deduplication, and JWT extraction.

## CLI (testing/debugging)

The crate includes an optional CLI binary, gated behind the `cli` feature
(which enables `tracing-subscriber` for log output):

```bash
# Build the CLI
cargo build --features cli

# Full token string (default)
anaconda-anon-usage

# With provenance details
anaconda-anon-usage --detail

# With a specific conda prefix
anaconda-anon-usage --prefix /path/to/env

# Supply an Anaconda Cloud JWT (extracts a/ token)
anaconda-anon-usage --jwt <jwt-string>

# Show the system token search path
anaconda-anon-usage --paths

# Generate a random token
anaconda-anon-usage --random

# Print the crate version
anaconda-anon-usage --version

# Enable debug logging
anaconda-anon-usage --verbose
```

## Architecture

```
rust/
  Cargo.toml
  build.rs          # Version from git describe
  src/
    lib.rs          # Public API: Config, token_string(), token_details(), search_path()
    tokens.rs       # Token collection, JWT parsing, search paths, caching
    utils.rs        # File I/O, random_token(), saved_token(), deferred writes
    main.rs         # CLI binary (behind `cli` feature)
```

### Known divergences from Python

- **Anaconda Cloud token**: The Python package reads keyrings via `anaconda-auth`
  to obtain the JWT. The Rust crate does not read keyrings — the caller must
  provide the JWT via `Config.anaconda_jwt`. This keeps auth concerns out of
  the token-generation crate.

- **Search paths**: Both implementations compute config search paths
  deterministically from standard system directories, `$CONDA_ROOT` (derived
  from `$CONDA_EXE`, `$CONDA_PYTHON_EXE`, or `condabin` in `$PATH`),
  `$XDG_CONFIG_HOME/conda`, `~/.config/conda`, `~/.conda`, and
  `$CONDA_PREFIX`. Neither imports conda. The parity tests verify that
  Rust tokens are a subset of Python tokens for system token types.

- **Default environment prefix**: Python defaults to `sys.prefix` when no
  prefix is specified. The Rust crate defaults to `$CONDA_PREFIX`, since
  `sys.prefix` is a Python-specific concept.

- **Windows HOME isolation**: The Rust `dirs` crate resolves the home directory
  via the Windows API (`FOLDERID_Profile`), ignoring the `USERPROFILE`
  environment variable. This means parity tests that rely on temporary HOME
  directories are skipped on Windows.
