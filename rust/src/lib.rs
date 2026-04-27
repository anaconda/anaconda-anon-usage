//! Anaconda Anonymous Usage (AAU) token generation for the conda ecosystem.
//!
//! Generates anonymous telemetry tokens compatible with the Python
//! [anaconda-anon-usage](https://github.com/anaconda/anaconda-anon-usage) package.
//!
//! # Token string format
//!
//! `[prefix...] [platform...] aau/{version} c/{client} s/{session} e/{env} [a/{cloud}] [o/{org}] [m/{machine}] [i/{installer}]`
//!
//! The string has two distinct regions, exposed as separate APIs:
//!
//! - **Platform UA** ([`platform_ua_string`]): host-tool prefix, platform
//!   info, rattler/reqwest versions. Non-identifying; safe to send to any
//!   domain.
//! - **Identity tokens** ([`identity_tokens`]): `aau/ c/ s/ e/ a/ i/ o/ m/`.
//!   Only appropriate for Anaconda-operated domains where the consumer has
//!   opted in to telemetry.
//!
//! [`token_string`] is the concatenation of both, for callers that want the
//! full User-Agent at an Anaconda-operated domain.
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
//! // Full token string (for User-Agent headers at Anaconda-operated domains)
//! // e.g., "ana/0.1.0 rattler/0.40.5 Darwin/25.2.0 OSX/26.2 aau/0.7.6 c/... s/..."
//! let tokens = token_string(&config);
//!
//! // Non-identifying platform UA (safe for any domain)
//! let platform_ua = anaconda_anon_usage::platform_ua_string(&(&config).into());
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

/// Inputs for the non-identifying portion of the User-Agent.
///
/// All fields are either compile-time-constant or first-boot-static, so a
/// [`PlatformUaConfig`] is safe to hash and use as a cache key.
/// Derived from [`Config`] via `From`/`Into`.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct PlatformUaConfig {
    /// Host-tool prefix (e.g., `"ana/0.1.0"`). Whitespace-delimited words
    /// become individual entries.
    pub prefix: Option<String>,

    /// If `true`, platform tokens (e.g., `Darwin/25.2.0 OSX/26.2 rustc/1.82.0`)
    /// are included. See [`Config::platform`] for the default.
    pub platform: bool,

    /// Rattler version override. Same semantics as [`Config::rattler_version`].
    pub rattler_version: Option<String>,

    /// Reqwest version override. Same semantics as [`Config::reqwest_version`].
    pub reqwest_version: Option<String>,
}

#[allow(clippy::derivable_impls)]
impl Default for PlatformUaConfig {
    fn default() -> Self {
        Self {
            prefix: None,
            platform: cfg!(feature = "platform"),
            rattler_version: None,
            reqwest_version: None,
        }
    }
}

impl From<&Config> for PlatformUaConfig {
    fn from(c: &Config) -> Self {
        Self {
            prefix: c.prefix.clone(),
            platform: c.platform,
            rattler_version: c.rattler_version.clone(),
            reqwest_version: c.reqwest_version.clone(),
        }
    }
}

impl From<Config> for PlatformUaConfig {
    fn from(c: Config) -> Self {
        (&c).into()
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
pub fn get_env_prefix() -> Option<String> {
    ENV_PREFIX.lock().unwrap_or_else(|e| e.into_inner()).clone()
}

#[derive(Debug, Clone)]
pub(crate) struct DeferredWrite {
    pub must_exist: Option<PathBuf>,
    pub filepath: PathBuf,
    pub token: String,
    pub label: String,
}

/// Build the non-identifying portion of the User-Agent.
///
/// Format: `[prefix...] [reqwest/{ver}] [platform...] [rattler/{ver}]`
///
/// Safe to send to any domain — contains only the host-tool prefix,
/// platform information, and crate versions. None of these are
/// user-identifying; all are compile-time-constant or first-boot-static.
///
/// The result is cached per-[`PlatformUaConfig`] for the process lifetime.
pub fn platform_ua_string(config: &PlatformUaConfig) -> String {
    tokens::platform_ua_string(config)
}

/// Build just the identity-bearing portion of the token string.
///
/// Format: `aau/{version} c/{client} s/{session} e/{env} [a/{cloud}] [i/{installer}] [o/{org}] [m/{machine}]`
///
/// Only appropriate to send to Anaconda-operated domains where the
/// consumer has opted in to telemetry. For non-Anaconda domains, use
/// [`platform_ua_string`] alone.
pub fn identity_tokens(config: &Config) -> String {
    match tokens::identity_tokens(config) {
        Ok(s) => s,
        Err(e) => {
            tracing::error!("Failed to generate AAU tokens: {}", e);
            format!("aau/{}", VERSION)
        }
    }
}

/// Build the full token string (platform UA + identity tokens).
///
/// Format: `[prefix...] [reqwest/{ver}] [platform...] [rattler/{ver}] aau/{version} c/{client} s/{session} e/{env} [a/{cloud}] [o/{org}] [m/{machine}] [i/{installer}]`
///
/// This is the full User-Agent for requests to Anaconda-operated domains.
/// For requests to non-Anaconda domains, use [`platform_ua_string`] alone
/// to avoid sending identity tokens off-platform.
pub fn token_string(config: &Config) -> String {
    let platform = platform_ua_string(&config.into());
    let identity = identity_tokens(config);
    if platform.is_empty() {
        identity
    } else if identity.is_empty() {
        platform
    } else {
        format!("{} {}", platform, identity)
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
///
/// # Panics
///
/// Panics if the OS random number generator is unavailable. OS entropy
/// failures are catastrophic and essentially never recoverable; returning
/// an empty string here would silently produce an invalid token downstream.
#[must_use]
pub fn random_token() -> String {
    utils::random_token("cli").expect("OS random number generator is unavailable")
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
///
/// The `#[must_use]` attribute ensures the compiler warns if the guard is
/// dropped immediately (e.g. `anaconda_anon_usage::init();` with no binding),
/// which would defeat the entire purpose of the guard.
#[must_use = "dropping the FlushGuard immediately flushes deferred writes \
              and ends AAU lifetime; bind it to a local (e.g. `let _aau = init();`)"]
pub struct FlushGuard;

impl Drop for FlushGuard {
    fn drop(&mut self) {
        let _ = finalize_deferred_writes();
    }
}

/// Initialize AAU and return a guard that flushes deferred writes on drop.
#[must_use = "the returned FlushGuard flushes deferred writes when dropped; \
              bind it for the lifetime of the process (e.g. `let _aau = init();`)"]
pub fn init() -> FlushGuard {
    FlushGuard
}
