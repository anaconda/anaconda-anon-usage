//! Anaconda Anonymous Usage (AAU) token generation for the conda ecosystem.
//!
//! Generates anonymous telemetry tokens compatible with the Python
//! [anaconda-anon-usage](https://github.com/anaconda/anaconda-anon-usage) package.
//!
//! # Token string format
//!
//! `[prefix...] [platform...] aau/{version} c/{client} s/{session} e/{env} [a/{cloud}] [o/{org}] [m/{machine}] [i/{installer}]`
//!
//! # Usage
//!
//! ```no_run
//! use anaconda_anon_usage::{Config, token_string, token_details};
//!
//! let config = Config {
//!     env_prefix: Some("/path/to/env".into()),
//!     anaconda_jwt: None, // provide a JWT to include the a/ token
//!     prefix: Some("ana/0.1.0 rattler/0.40.5".into()),
//!     platform: true,
//!     ..Default::default()
//! };
//!
//! // Full token string (for User-Agent headers)
//! // e.g., "ana/0.1.0 rattler/0.40.5 Darwin/25.2.0 OSX/26.2 aau/0.7.6 c/... s/..."
//! let tokens = token_string(&config);
//!
//! // Per-token details (for diagnostics)
//! for entry in token_details(&config) {
//!     println!("  {}/{} ({}) <- {}", entry.prefix, entry.value, entry.label, entry.source);
//! }
//! ```

pub mod platform;
mod tokens;
mod utils;

use std::path::PathBuf;
use std::sync::{LazyLock, Mutex};

/// AAU version — derived from the repository's git tag at build time.
pub const VERSION: &str = env!("AAU_VERSION");

/// Rustc version used to compile the crate (e.g., "1.82.0").
/// Empty string if detection failed.
pub const RUSTC_VERSION: &str = env!("RUSTC_VERSION");

/// Rattler version extracted from the consumer's Cargo.lock at build time.
/// Only populated when the `rattler` feature is enabled.
#[cfg(feature = "rattler")]
pub const RATTLER_VERSION: &str = env!("RATTLER_VERSION");

/// Reqwest version extracted from the consumer's Cargo.lock at build time.
/// Only populated when the `reqwest` feature is enabled.
#[cfg(feature = "reqwest")]
pub const REQWEST_VERSION: &str = env!("REQWEST_VERSION");

/// Configuration for AAU token generation.
#[derive(Debug, Clone)]
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

    /// If `true`, platform tokens (e.g., `Darwin/25.2.0 OSX/26.2 rustc/1.82.0`)
    /// are included in the token string. Defaults to `true` when the `platform`
    /// feature is enabled, `false` otherwise.
    pub platform: bool,

    /// An arbitrary string to prepend to the final token string.
    /// Each whitespace-delimited word becomes its own entry in the token
    /// `Vec`, preserving `name/value` structure where present.
    /// Example: `"ana/0.1.0"`.
    pub prefix: Option<String>,

    /// Rattler version to include in the token string. If `Some`, this
    /// overrides the compile-time version from the `rattler` feature.
    /// If `None`, falls back to the compile-time constant (when the
    /// `rattler` feature is enabled) or is omitted entirely.
    pub rattler_version: Option<String>,

    /// Reqwest version to include in the token string. If `Some`, this
    /// overrides the compile-time version from the `reqwest` feature.
    /// If `None`, falls back to the compile-time constant (when the
    /// `reqwest` feature is enabled) or is omitted entirely.
    pub reqwest_version: Option<String>,
}

#[allow(clippy::derivable_impls)] // platform field depends on cfg!(feature = "platform")
impl Default for Config {
    fn default() -> Self {
        Self {
            env_prefix: None,
            anaconda_jwt: None,
            platform: cfg!(feature = "platform"),
            prefix: None,
            rattler_version: None,
            reqwest_version: None,
        }
    }
}

/// A collected token with its provenance (where it came from).
pub struct TokenEntry {
    /// Token name/prefix (e.g., `"c"`, `"aau"`, `"Darwin"`, `"ana"`).
    pub prefix: String,
    /// Human-readable token type (e.g., `"client"`, `"session"`, `"platform"`).
    pub label: String,
    /// The token value (e.g., base64url-encoded token, version string, etc.).
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

/// Global environment prefix, set via [`set_env_prefix`].
///
/// Consulted by token generation when `Config::env_prefix` is `None`,
/// before falling back to `$CONDA_PREFIX`.
static ENV_PREFIX: LazyLock<Mutex<Option<String>>> = LazyLock::new(|| Mutex::new(None));

/// Store the conda/pixi environment prefix for token generation.
///
/// Call this once the target environment prefix is known. The value is
/// used as a fallback when `Config::env_prefix` is `None` (and takes
/// precedence over the `$CONDA_PREFIX` environment variable).
pub fn set_env_prefix(prefix: impl Into<String>) {
    *ENV_PREFIX.lock().unwrap_or_else(|e| e.into_inner()) = Some(prefix.into());
}

/// Read the global environment prefix, if set.
pub(crate) fn get_env_prefix() -> Option<String> {
    ENV_PREFIX.lock().unwrap_or_else(|e| e.into_inner()).clone()
}

#[derive(Debug, Clone)]
pub(crate) struct DeferredWrite {
    pub must_exist: Option<PathBuf>,
    pub filepath: PathBuf,
    pub token: String,
    pub label: String,
}

/// Build the full token string.
///
/// Format: `[prefix...] [reqwest/{ver}] [platform...] [rattler/{ver}] aau/{version} c/{client} s/{session} e/{env} [a/{cloud}] [o/{org}] [m/{machine}] [i/{installer}]`
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
                prefix: "aau".into(),
                label: "version".into(),
                value: VERSION.to_string(),
                source: "build".into(),
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
