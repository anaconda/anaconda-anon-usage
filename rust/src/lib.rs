//! Anaconda Anonymous Usage (AAU) token generation for the conda ecosystem.
//!
//! Generates anonymous telemetry tokens compatible with the Python
//! [anaconda-anon-usage](https://github.com/anaconda/anaconda-anon-usage) package.
//!
//! # Token string format
//!
//! `aau/{version} c/{client} s/{session} e/{env} [a/{cloud}] [o/{org}] [m/{machine}] [i/{installer}]`
//!
//! # Usage
//!
//! ```no_run
//! use anaconda_anon_usage::{Config, token_string, token_details};
//!
//! let config = Config {
//!     env_prefix: Some("/path/to/env".into()),
//!     anaconda_jwt: None, // provide a JWT to include the a/ token
//!     ..Default::default()
//! };
//!
//! // Simple token string (for User-Agent headers)
//! let tokens = token_string(&config);
//!
//! // Per-token details (for diagnostics)
//! for entry in token_details(&config) {
//!     println!("  {}/{} ({}) <- {}", entry.prefix, entry.value, entry.label, entry.source);
//! }
//! ```

mod tokens;
mod utils;

use std::path::PathBuf;
use std::sync::{LazyLock, Mutex};

/// AAU version — derived from the repository's git tag at build time.
pub const VERSION: &str = env!("AAU_VERSION");

/// Configuration for AAU token generation.
#[derive(Debug, Clone, Default)]
pub struct Config {
    /// Conda environment prefix (e.g., `/home/user/.ana/envs/default`).
    /// Falls back to `$CONDA_PREFIX` if `None`.
    pub env_prefix: Option<String>,

    /// Raw Anaconda Cloud JWT (OAuth2 access token).
    /// If provided, the `a/` token is extracted from the JWT's `sub` claim.
    /// If `None`, the `a/` token is omitted. The crate does not read keyrings
    /// or perform authentication — the caller is responsible for obtaining
    /// the JWT (e.g., via `anaconda-auth` or `ana-cli`).
    pub anaconda_jwt: Option<String>,
}

/// A collected token with its provenance (where it came from).
pub struct TokenEntry {
    /// Single-character token prefix (`c`, `s`, `e`, `a`, `i`, `o`, `m`).
    pub prefix: &'static str,
    /// Human-readable token type (e.g., `"client"`, `"session"`, `"environment"`).
    pub label: &'static str,
    /// The token value (base64url-encoded).
    pub value: String,
    /// Where this token was read from (file path, env var, or generation method).
    pub source: String,
}

/// Errors that can occur during token generation or persistence.
#[derive(Debug)]
pub enum Error {
    /// Filesystem I/O error (reading/writing token files).
    Io(std::io::Error),
    /// Any other error (e.g., missing home directory).
    Other(String),
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Error::Io(e) => write!(f, "IO error: {}", e),
            Error::Other(e) => write!(f, "{}", e),
        }
    }
}

impl std::error::Error for Error {}

impl From<std::io::Error> for Error {
    fn from(e: std::io::Error) -> Self {
        Error::Io(e)
    }
}

pub(crate) type Result<T> = std::result::Result<T, Error>;

/// Global deferred writes for tokens that couldn't be persisted immediately.
static DEFERRED: LazyLock<Mutex<Vec<DeferredWrite>>> = LazyLock::new(|| Mutex::new(Vec::new()));

#[derive(Debug, Clone)]
pub(crate) struct DeferredWrite {
    pub must_exist: Option<PathBuf>,
    pub filepath: PathBuf,
    pub token: String,
    pub label: String,
}

/// Build the AAU token string.
///
/// Format: `aau/{version} c/{client} s/{session} e/{env} [a/{cloud}] [o/{org}] [m/{machine}] [i/{installer}]`
pub fn token_string(config: &Config) -> String {
    match tokens::token_string(config) {
        Ok(s) => s,
        Err(e) => {
            tracing::error!("Failed to generate AAU tokens: {}", e);
            format!("aau/{}", VERSION)
        }
    }
}

/// Collect all AAU tokens with per-token provenance details.
///
/// Returns individual [`TokenEntry`] values including the `aau/` version entry.
/// The token string can be exactly reproduced from the entries:
/// ```ignore
/// entries.iter().map(|e| format!("{}/{}", e.prefix, e.value)).collect::<Vec<_>>().join(" ")
/// ```
pub fn token_details(config: &Config) -> Vec<TokenEntry> {
    match tokens::token_details(config) {
        Ok(entries) => entries,
        Err(e) => {
            tracing::error!("Failed to generate AAU tokens: {}", e);
            vec![TokenEntry {
                prefix: "aau",
                label: "version",
                value: VERSION.to_string(),
                source: "build".to_string(),
            }]
        }
    }
}

/// Generate a random 22-character URL-safe base64 token.
pub fn random_token() -> String {
    utils::random_token("cli").unwrap_or_default()
}

/// Return the system token search path.
pub fn search_path() -> &'static [std::path::PathBuf] {
    tokens::search_path()
}

/// Flush any deferred token writes to disk.
///
/// Call this at process exit to persist tokens for environments that were
/// created during the current process.
pub fn finalize_deferred_writes() -> std::result::Result<(), Error> {
    utils::final_attempt()
}

/// RAII guard that flushes deferred token writes when dropped.
///
/// Use this at the top of `main()` to ensure deferred writes are flushed
/// on exit, similar to Sentry's guard pattern:
///
/// ```no_run
/// let _aau = anaconda_anon_usage::init();
/// // ... rest of program ...
/// // deferred writes flushed when _aau is dropped
/// ```
pub struct FlushGuard;

impl Drop for FlushGuard {
    fn drop(&mut self) {
        let _ = finalize_deferred_writes();
    }
}

/// Initialize AAU and return a guard that flushes deferred writes on drop.
pub fn init() -> FlushGuard {
    FlushGuard
}
