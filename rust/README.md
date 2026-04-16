# anaconda-anon-usage (Rust crate)

Rust implementation of the Anaconda Anonymous Usage (AAU) token system.
Produces token strings identical to the Python
[anaconda-anon-usage](https://github.com/anaconda/anaconda-anon-usage) package.

## Token format

```
[prefix...] [reqwest/{ver}] [platform...] [rattler/{ver}] aau/{version} c/{client} s/{session} e/{env} [a/{cloud}] [o/{org}] [m/{machine}] [i/{installer}]
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

Optional tokens prepended before `aau/`:

| Token | Source | Position |
|-------|--------|----------|
| Prefix entries | `Config.prefix` (e.g., `"ana/0.1.0"`) | First |
| `reqwest/{ver}` | `reqwest` feature or `Config.reqwest_version` | Before platform |
| Platform tokens | `Config.platform` (e.g., `Darwin/25.2.0 OSX/26.2 rustc/1.82.0`) | Before rattler |
| `rattler/{ver}` | `rattler` feature or `Config.rattler_version` | Before aau |

## Library usage

### Initialization

The crate uses deferred writes to persist tokens for conda environments
that are created during the current process. Use `init()` to return a
`FlushGuard` that flushes deferred writes when dropped:

```rust
fn main() {
    let _aau = anaconda_anon_usage::init();
    // ... rest of program ...
    // deferred writes flushed automatically when _aau is dropped
}
```

If you cannot use RAII (e.g., in FFI contexts), call
`finalize_deferred_writes()` manually before exit:

```rust
anaconda_anon_usage::finalize_deferred_writes().ok();
```

### Setting the environment prefix

The `e/` environment token requires a conda environment prefix. You can
provide it per-call via `Config::env_prefix`, or set it globally with
`set_env_prefix()`. The resolution order is:

1. `Config::env_prefix` (explicit per-call)
2. Global value from `set_env_prefix()`
3. `$CONDA_PREFIX` environment variable

The global setter is useful when the prefix becomes known at a different
point in the program than where tokens are generated:

```rust
// Early in bootstrap, once the target prefix is known:
anaconda_anon_usage::set_env_prefix("/home/user/.cx");

// Later, in HTTP client construction — picks up the global automatically:
let config = Config::default();
let ua = anaconda_anon_usage::token_string(&config);
```

Read it back with `get_env_prefix()` if needed:

```rust
if let Some(prefix) = anaconda_anon_usage::get_env_prefix() {
    println!("Current env prefix: {}", prefix);
}
```

### Generating tokens

```rust
use anaconda_anon_usage::{Config, token_string, token_details};

fn main() {
    let _aau = anaconda_anon_usage::init();

    let config = Config {
        env_prefix: Some("/path/to/env".into()),
        anaconda_jwt: Some("eyJ...".into()),
        ..Default::default()
    };

    // Full token string (for User-Agent headers)
    let ua = token_string(&config);

    // Per-token details (for diagnostics)
    for entry in token_details(&config) {
        println!("  {}/{} ({}) <- {}", entry.prefix, entry.value, entry.label, entry.source);
    }
}
```

### Platform and prefix tokens

To include platform identification and application-specific tokens:

```rust
use anaconda_anon_usage::{Config, token_string};

let config = Config {
    prefix: Some("ana/0.1.0".into()),
    platform: true,
    ..Default::default()
};

let ua = token_string(&config);
// "ana/0.1.0 Darwin/25.2.0 OSX/26.2 rustc/1.82.0 aau/0.7.6 c/... s/..."
```

### Runtime version overrides

Rattler and reqwest versions can be provided at runtime via `Config`, which
takes precedence over the compile-time versions from Cargo features:

```rust
let config = Config {
    prefix: Some("myapp/1.0".into()),
    platform: true,
    rattler_version: Some("0.40.5".into()),
    reqwest_version: Some("0.12.5".into()),
    ..Default::default()
};

let ua = token_string(&config);
// "myapp/1.0 reqwest/0.12.5 Darwin/25.2.0 OSX/26.2 rustc/1.82.0 rattler/0.40.5 aau/0.7.6 c/... s/..."
```

## Cargo features

| Feature | Dependencies | Effect |
|---------|-------------|--------|
| `cli` | `tracing-subscriber` | Enables the CLI binary |
| `platform` | none | Sets `Config::platform` default to `true` |
| `rattler` | none | `build.rs` extracts rattler version from consumer's `Cargo.lock` |
| `reqwest` | none | `build.rs` extracts reqwest version from consumer's `Cargo.lock` |

The `rattler` and `reqwest` features add zero dependencies and impose no
version constraints on the consumer. They signal `build.rs` to scrape the
workspace `Cargo.lock` for the named crate's version, which is then
embedded as a compile-time constant. If the crate is not found in the lock
file, the token is silently omitted.

### Example: consuming from ana-cli

```toml
[dependencies]
anaconda-anon-usage = { path = "../anaconda-anon-usage/rust", features = ["platform", "rattler", "reqwest"] }
```

```rust
let config = Config {
    prefix: Some(format!("ana/{}", VERSION)),
    env_prefix: Some(env_path),
    anaconda_jwt: get_api_key().ok(),
    ..Default::default()  // platform=true from feature flag
};
let ua = anaconda_anon_usage::token_string(&config);
```

### Example: consuming from conda-express (cx)

```toml
[dependencies]
anaconda-anon-usage = { version = "0.8.0-pre.7", features = ["platform", "rattler", "reqwest"] }
```

```rust
// In main():
let _aau = anaconda_anon_usage::init();

// Once the target prefix is known:
anaconda_anon_usage::set_env_prefix(prefix.to_string_lossy());

// In HTTP client construction — no env_prefix needed in Config:
let config = Config {
    prefix: Some(format!("cx/{}", env!("CARGO_PKG_VERSION"))),
    ..Default::default()
};
let ua = anaconda_anon_usage::token_string(&config);
client_builder.user_agent(&ua).build();
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

The parity tests are unaffected by the `platform`, `rattler`, and `reqwest`
features. The test parser only examines single-character token prefixes
(`c/`, `s/`, `e/`, etc.) and the CLI defaults `--platform` to off, so
platform and version tokens are invisible to the comparison.

## CLI (testing/debugging)

The crate includes an optional CLI binary, gated behind the `cli` feature:

```bash
# Build the CLI
cargo build --features cli

# Full token string (default)
anaconda-anon-usage

# With provenance details
anaconda-anon-usage --detail

# With a specific conda environment prefix
anaconda-anon-usage --env-prefix /path/to/env

# Supply an Anaconda Cloud JWT (extracts a/ token)
anaconda-anon-usage --jwt <jwt-string>

# Include platform tokens
anaconda-anon-usage --platform

# Prepend application-specific tokens
anaconda-anon-usage --ua-prefix "ana/0.1.0"

# Include rattler/reqwest version tokens
anaconda-anon-usage --rattler 0.40.5 --reqwest 0.12.5

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
  build.rs          # Version from git describe; rustc/rattler/reqwest version extraction
  src/
    lib.rs          # Public API: Config, token_string(), token_details(), init(), FlushGuard, set_env_prefix(), get_env_prefix()
    tokens.rs       # Token collection, JWT parsing, search paths, caching
    utils.rs        # File I/O, random_token(), saved_token(), deferred writes
    platform.rs     # Platform detection: kernel, OS distro, libc, rustc version
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
  prefix is specified. The Rust crate checks `Config::env_prefix`, then the
  global set via `set_env_prefix()`, then `$CONDA_PREFIX`. The global setter
  allows consumers to supply the prefix early (e.g., during bootstrap) so
  that later calls to `token_string()` include the `e/` token automatically.

- **Windows HOME isolation**: The Rust `dirs` crate resolves the home directory
  via the Windows API (`FOLDERID_Profile`), ignoring the `USERPROFILE`
  environment variable. This means parity tests that rely on temporary HOME
  directories are skipped on Windows.

- **Platform/version tokens**: The `platform`, `rattler`, and `reqwest`
  features are Rust-only additions not present in the Python package. These
  tokens are prepended before `aau/` and do not affect parity with Python
  for the core AAU token types.
