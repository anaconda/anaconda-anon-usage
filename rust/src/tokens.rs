//! Token generation and caching for all AAU token types.

use super::utils::{random_token, read_file, saved_token};
use super::{Config, Error, Result, TokenEntry, VERSION};
use base64::prelude::*;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::{LazyLock, Mutex};
use uuid::Uuid;

const INSTALLER_TOKEN_NAME: &str = "installer_token";
const ORG_TOKEN_NAME: &str = "org_token";
const MACHINE_TOKEN_NAME: &str = "machine_token";

// Environment variable overrides (matching Python anaconda-anon-usage)
const INSTALLER_TOKEN_ENV: &str = "ANACONDA_ANON_USAGE_INSTALLER_TOKEN";
const ORG_TOKEN_ENV: &str = "ANACONDA_ANON_USAGE_ORG_TOKEN";
const MACHINE_TOKEN_ENV: &str = "ANACONDA_ANON_USAGE_MACHINE_TOKEN";

// Cache for computed tokens (thread-safe, process-lifetime).
static TOKEN_CACHE: LazyLock<Mutex<HashMap<String, String>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

// Cache for multi-valued system tokens (installer, org, machine).
type SystemTokenMap = HashMap<String, Vec<(String, String)>>;
static SYSTEM_TOKEN_CACHE: LazyLock<Mutex<SystemTokenMap>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

/// Cached search paths — filesystem checks done once per process.
static SEARCH_PATH: LazyLock<Vec<PathBuf>> = LazyLock::new(compute_search_path);

fn cached_string<F>(key: &str, f: F) -> Result<String>
where
    F: FnOnce() -> Result<String>,
{
    let mut cache = TOKEN_CACHE.lock().unwrap_or_else(|e| e.into_inner());
    if let Some(value) = cache.get(key) {
        return Ok(value.clone());
    }
    let value = f()?;
    cache.insert(key.to_string(), value.clone());
    Ok(value)
}

fn cached_option<F>(key: &str, f: F) -> Option<String>
where
    F: FnOnce() -> Option<String>,
{
    let mut cache = TOKEN_CACHE.lock().unwrap_or_else(|e| e.into_inner());
    if let Some(value) = cache.get(key) {
        return if value.is_empty() {
            None
        } else {
            Some(value.clone())
        };
    }
    let value = f();
    cache.insert(key.to_string(), value.clone().unwrap_or_default());
    value
}

fn cached_system_tokens<F>(key: &str, f: F) -> Vec<(String, String)>
where
    F: FnOnce() -> Vec<(String, String)>,
{
    let mut cache = SYSTEM_TOKEN_CACHE.lock().unwrap_or_else(|e| e.into_inner());
    if let Some(value) = cache.get(key) {
        return value.clone();
    }
    let value = f();
    cache.insert(key.to_string(), value.clone());
    value
}

/// Conda configuration search paths (same locations conda checks for .condarc).
///
/// Mirrors conda's `SEARCH_PATH` constant from `conda.base.constants`:
/// - Platform-specific system directories (`/etc/conda`, `C:/ProgramData/conda`)
/// - `$CONDA_ROOT` (derived from `$CONDA_EXE` — the base/root environment)
/// - `$XDG_CONFIG_HOME/conda`, `~/.config/conda`, `~/.conda`
/// - `$CONDA_PREFIX` (the currently active environment)
///
/// May include directories that do not exist on disk. Callers handle
/// missing files/directories gracefully. Token deduplication happens
/// in `parse_token_values`, so duplicate paths are harmless.
///
/// Cached in a `LazyLock` — computed once per process.
pub fn search_path() -> &'static [PathBuf] {
    &SEARCH_PATH
}

/// Resolve the conda root/base environment prefix.
///
/// Tries these sources in order, returning the first that succeeds:
/// 1. `$CONDA_ROOT` — set by activation scripts or `sys.prefix`
/// 2. `$CONDA_EXE` — grandparent of the conda executable path
///    - Unix: `.../bin/conda` → `...`
///    - Windows: `...\Scripts\conda.exe` → `...`
/// 3. `$CONDA_PYTHON_EXE` — the Python interpreter in the base env
///    - Unix: `.../bin/python` → grandparent
///    - Windows: `...\python.exe` → parent
/// 4. Walk `$PATH` for a `condabin` entry → its parent directory
fn conda_root() -> Option<PathBuf> {
    // 1. CONDA_ROOT — direct
    if let Ok(root) = std::env::var("CONDA_ROOT") {
        if !root.is_empty() {
            return Some(PathBuf::from(root));
        }
    }

    // 2. CONDA_EXE — grandparent (strip filename + bin/Scripts)
    if let Some(root) = env_path_grandparent("CONDA_EXE") {
        return Some(root);
    }

    // 3. CONDA_PYTHON_EXE — platform-dependent
    if let Ok(val) = std::env::var("CONDA_PYTHON_EXE") {
        if !val.is_empty() {
            let path = PathBuf::from(&val);
            // On Unix, python is at .../bin/python → grandparent
            // On Windows, python is at ...\python.exe → parent
            let root = if cfg!(windows) {
                path.parent().map(|p| p.to_path_buf())
            } else {
                path.parent()
                    .and_then(|p| p.parent())
                    .map(|p| p.to_path_buf())
            };
            if let Some(r) = root {
                return Some(r);
            }
        }
    }

    // 4. Walk PATH for a condabin directory
    if let Ok(path_var) = std::env::var("PATH") {
        let sep = if cfg!(windows) { ';' } else { ':' };
        for entry in path_var.split(sep) {
            let p = Path::new(entry);
            if p.file_name().and_then(|n| n.to_str()) == Some("condabin") {
                if let Some(parent) = p.parent() {
                    return Some(parent.to_path_buf());
                }
            }
        }
    }

    None
}

/// Extract the grandparent directory from an environment variable path.
fn env_path_grandparent(var: &str) -> Option<PathBuf> {
    let val = std::env::var(var).ok()?;
    if val.is_empty() {
        return None;
    }
    let path = PathBuf::from(val);
    path.parent()?.parent().map(|p| p.to_path_buf())
}

fn compute_search_path() -> Vec<PathBuf> {
    let mut dirs: Vec<PathBuf> = Vec::new();

    // Test-only override, gated at compile time by the `test-support` feature.
    // Released binaries never see this code path.
    #[cfg(feature = "test-support")]
    let test_root = std::env::var("ANACONDA_ANON_USAGE_TEST_SYSTEM_ROOT")
        .ok()
        .filter(|v| !v.is_empty());
    #[cfg(not(feature = "test-support"))]
    let test_root: Option<String> = None;

    if let Some(test_root) = test_root {
        dirs.push(PathBuf::from(test_root));
    } else {
        #[cfg(windows)]
        dirs.push("C:/ProgramData/conda".into());

        #[cfg(not(windows))]
        {
            dirs.push("/etc/conda".into());
            dirs.push("/var/lib/conda".into());
        }
    }

    let conda_root = conda_root();
    if let Some(ref root) = conda_root {
        dirs.push(root.clone());
    }

    if let Ok(xdg) = std::env::var("XDG_CONFIG_HOME") {
        if !xdg.is_empty() {
            dirs.push(PathBuf::from(xdg).join("conda"));
        }
    }

    if let Some(home) = dirs::home_dir() {
        dirs.push(home.join(".config/conda"));
        dirs.push(home.join(".conda"));
    }

    if let Ok(prefix) = std::env::var("CONDA_PREFIX") {
        if !prefix.is_empty() && conda_root.as_deref() != Some(Path::new(&prefix)) {
            dirs.push(PathBuf::from(prefix));
        }
    }

    dirs
}

/// Validate a token against the AAU token format.
///
/// Matches Python anaconda-anon-usage's `VALID_TOKEN_RE = r"^(?:[A-Za-z0-9]|_|-){1,36}$"`.
fn is_valid_token(token: &str) -> bool {
    !token.is_empty()
        && token.len() <= 36
        && token
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
}

/// Parse a single token value, validating and deduplicating.
///
/// The entire trimmed input is treated as one opaque token (no splitting).
/// This matches Python anaconda-anon-usage behavior where each env var or
/// file value is validated as a whole against VALID_TOKEN_RE.
fn parse_token_value(content: &str, source: &str, results: &mut Vec<(String, String)>) {
    let token = content.trim();
    if token.is_empty() {
        return;
    }
    if !is_valid_token(token) {
        tracing::debug!("Invalid token discarded: {}", token);
        return;
    }
    if !results.iter().any(|(t, _)| t == token) {
        results.push((token.to_string(), source.to_string()));
    }
}

/// Read system-level tokens from conda config directories and environment variables.
///
/// Returns (token, source) pairs with provenance. Environment variables are additive:
/// tokens from `$ANACONDA_ANON_USAGE_{NAME}` are collected first, then tokens from
/// config directory files are appended. Duplicates are suppressed. This matches the
/// Python anaconda-anon-usage behavior where env vars supplement (not replace)
/// file-based tokens.
///
/// Searches for both the plain filename and dotfile variant (e.g.
/// `org_token` and `.org_token`) in each config directory.
fn system_tokens_with_source(fname: &str, label: &str, env_var: &str) -> Vec<(String, String)> {
    let mut results: Vec<(String, String)> = Vec::new();

    // Check environment variable (additive, same as Python anaconda-anon-usage)
    if let Ok(val) = std::env::var(env_var) {
        let val = val.trim().to_string();
        if !val.is_empty() {
            tracing::debug!("Found {} token in environment: {}", label, val);
            parse_token_value(&val, &format!("${}", env_var), &mut results);
        }
    }

    let dotname = format!(".{}", fname);

    for path in search_path() {
        // Check both plain and dotfile variants
        for name in &[fname, dotname.as_str()] {
            let fpath = path.join(name);
            if !fpath.exists() {
                continue;
            }

            if let Ok(content) = read_file(&fpath, label, true) {
                if !content.is_empty() {
                    parse_token_value(&content, &fpath.display().to_string(), &mut results);
                }
            }
        }
    }

    if results.is_empty() {
        tracing::debug!("No {} tokens found", label);
    }

    results
}

fn client_token() -> Result<String> {
    cached_string("client_token", || {
        let config_dir = dirs::home_dir()
            .ok_or_else(|| Error::Other("No home directory".to_string()))?
            .join(".conda");
        let fpath = config_dir.join("aau_token");
        saved_token(&fpath, "client", None, false, true)
    })
}

fn session_token() -> Result<String> {
    cached_string("session_token", || random_token("session"))
}

/// Resolve the environment prefix: explicit arg > global > CONDA_PREFIX > None.
fn resolve_prefix(prefix: Option<&str>) -> Option<String> {
    if let Some(p) = prefix {
        return Some(p.to_string());
    }
    if let Some(p) = crate::get_env_prefix() {
        return Some(p);
    }
    std::env::var("CONDA_PREFIX").ok().filter(|s| !s.is_empty())
}

fn environment_token(prefix: Option<&str>) -> Result<String> {
    let prefix_str = match resolve_prefix(prefix) {
        Some(p) => p,
        None => return Ok(String::new()),
    };

    let cache_key = format!("environment_token_{}", prefix_str);
    cached_string(&cache_key, || {
        let fpath = PathBuf::from(&prefix_str).join("etc").join("aau_token");
        saved_token(
            &fpath,
            "environment",
            Some(PathBuf::from(&prefix_str)),
            false,
            false,
        )
    })
}

/// Extract a compact identity token from a JWT-format API key.
///
/// Mirrors Python anaconda-anon-usage `_jwt_to_token()`:
/// 1. Split into 3 dot-separated base64url parts
/// 2. Decode header — must have `"typ": "JWT"`
/// 3. Decode payload — must have positive integer `exp` (not expired) and UUID `sub`
/// 4. Convert UUID to 16 raw bytes -> base64url -> strip trailing `=`
///
/// Returns `None` (not an error) for any invalid/expired/missing token.
fn jwt_to_token(api_key: &str) -> Option<String> {
    let parts: Vec<&str> = api_key.split('.').collect();
    if parts.len() != 3 || parts.iter().any(|p| p.is_empty()) {
        tracing::debug!("API key is not a 3-part JWT");
        return None;
    }

    // All three parts must be valid base64url (structural check, no crypto verification).
    // Python does: list(map(lambda x: base64.urlsafe_b64decode(x + "==="), parts))
    let header_bytes = BASE64_URL_SAFE_NO_PAD.decode(parts[0]).ok()?;
    let payload_bytes = BASE64_URL_SAFE_NO_PAD.decode(parts[1]).ok()?;
    if BASE64_URL_SAFE_NO_PAD.decode(parts[2]).is_err() {
        tracing::debug!("JWT signature is not valid base64url");
        return None;
    }

    // Header must be a JSON object with typ: "JWT"
    let header: serde_json::Value = serde_json::from_slice(&header_bytes).ok()?;
    if header.get("typ").and_then(|v| v.as_str()) != Some("JWT") {
        tracing::debug!("JWT header typ is not 'JWT'");
        return None;
    }

    // Payload must be a JSON object
    let payload: serde_json::Value = serde_json::from_slice(&payload_bytes).ok()?;

    // Check expiration
    let exp = payload.get("exp").and_then(|v| v.as_i64())?;
    if exp <= 0 {
        tracing::debug!("JWT exp is not a positive integer");
        return None;
    }
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    if exp < now {
        tracing::debug!("API key expired {}s ago", now - exp);
        return None;
    }

    // Extract subscriber UUID
    let sub = payload.get("sub").and_then(|v| v.as_str())?;
    let user_uuid = Uuid::parse_str(sub).ok()?;

    // Encode as compact base64url token (16 bytes, no padding)
    let token = BASE64_URL_SAFE_NO_PAD.encode(user_uuid.as_bytes());
    tracing::debug!("Extracted Anaconda auth token from JWT");
    Some(token)
}

/// Anaconda Cloud auth token (a/ prefix).
///
/// Extracts the user UUID from the provided JWT. If no JWT is provided,
/// the `a/` token is omitted.
fn anaconda_cloud_token(jwt: Option<&str>) -> Option<String> {
    let jwt = jwt.filter(|s| !s.is_empty())?;
    jwt_to_token(jwt)
}

/// Parse a prefix string into TokenEntry values.
///
/// Each whitespace-delimited word becomes its own entry. Words containing
/// `/` are split into `prefix/value`; words without `/` use the whole
/// word as the prefix with an empty value.
fn parse_prefix(prefix: &str) -> Vec<TokenEntry> {
    prefix
        .split_whitespace()
        .map(|word| {
            let (name, value) = match word.split_once('/') {
                Some((n, v)) => (n.to_string(), v.to_string()),
                None => (word.to_string(), String::new()),
            };
            TokenEntry {
                prefix: name,
                label: "prefix".into(),
                value,
                source: "config".into(),
            }
        })
        .collect()
}

/// Collect all AAU tokens with provenance information.
///
/// This is the single source of truth for token assembly. The ordering is:
/// 1. Prefix entries (from `config.prefix`)
/// 2. Reqwest version (if `reqwest` feature is enabled)
/// 3. Platform tokens (if `config.platform` is true)
/// 4. Rattler version (if `rattler` feature is enabled)
/// 5. AAU tokens (`aau/`, `c/`, `s/`, `e/`, `a/`, `i/`, `o/`, `m/`)
///
/// The token string can be exactly reproduced by joining entries as
/// `"{prefix}/{value}"` (or just `"{prefix}"` when value is empty).
fn collect_tokens(config: &Config) -> Result<Vec<TokenEntry>> {
    let mut entries = Vec::new();

    // 1. Prefix entries
    if let Some(ref prefix) = config.prefix {
        entries.extend(parse_prefix(prefix));
    }

    // 2. Reqwest version (before platform tokens)
    {
        let ver: Option<&str> = config.reqwest_version.as_deref().or({
            #[cfg(feature = "reqwest")]
            {
                Some(crate::REQWEST_VERSION)
            }
            #[cfg(not(feature = "reqwest"))]
            {
                None
            }
        });
        if let Some(v) = ver.filter(|s| !s.is_empty()) {
            entries.push(TokenEntry {
                prefix: "reqwest".into(),
                label: "http".into(),
                value: v.to_string(),
                source: if config.reqwest_version.is_some() {
                    "config"
                } else {
                    "build (Cargo.lock)"
                }
                .into(),
            });
        }
    }

    // 3. Platform tokens
    if config.platform {
        for pt in crate::platform::platform_tokens() {
            entries.push(TokenEntry {
                prefix: pt.name.clone(),
                label: "platform".into(),
                value: pt.value.clone(),
                source: "system".into(),
            });
        }
    }

    // 4. Rattler version (after platform, before aau)
    {
        let ver: Option<&str> = config.rattler_version.as_deref().or({
            #[cfg(feature = "rattler")]
            {
                Some(crate::RATTLER_VERSION)
            }
            #[cfg(not(feature = "rattler"))]
            {
                None
            }
        });
        if let Some(v) = ver.filter(|s| !s.is_empty()) {
            entries.push(TokenEntry {
                prefix: "rattler".into(),
                label: "solver".into(),
                value: v.to_string(),
                source: if config.rattler_version.is_some() {
                    "config"
                } else {
                    "build (Cargo.lock)"
                }
                .into(),
            });
        }
    }

    // 5. AAU version (always first of the AAU tokens)
    entries.push(TokenEntry {
        prefix: "aau".into(),
        label: "version".into(),
        value: VERSION.to_string(),
        source: "build".into(),
    });

    // Client token
    let client = client_token()?;
    if !client.is_empty() {
        let source = dirs::home_dir()
            .map(|h| h.join(".conda/aau_token").display().to_string())
            .unwrap_or_default();
        entries.push(TokenEntry {
            prefix: "c".into(),
            label: "client".into(),
            value: client,
            source,
        });
    }

    // Session token
    let session = session_token()?;
    if !session.is_empty() {
        entries.push(TokenEntry {
            prefix: "s".into(),
            label: "session".into(),
            value: session,
            source: "random (per-process)".into(),
        });
    }

    // Environment token
    let prefix_str = resolve_prefix(config.env_prefix.as_deref());
    let environment = environment_token(config.env_prefix.as_deref())?;
    if !environment.is_empty() {
        let env_path = prefix_str
            .as_deref()
            .map(|p| format!("{}/etc/aau_token", p))
            .unwrap_or_default();
        entries.push(TokenEntry {
            prefix: "e".into(),
            label: "environment".into(),
            value: environment,
            source: env_path,
        });
    }

    // Anaconda Cloud token (extracted from caller-provided JWT)
    let jwt = config.anaconda_jwt.clone();
    let jwt_key = format!("anaconda_cloud_token_{}", jwt.as_deref().unwrap_or(""));
    if let Some(cloud) = cached_option(&jwt_key, || anaconda_cloud_token(jwt.as_deref())) {
        entries.push(TokenEntry {
            prefix: "a".into(),
            label: "anaconda".into(),
            value: cloud,
            source: "JWT".into(),
        });
    }

    // System tokens (installer, org, machine) with provenance
    for (fname, env_var, prefix_char, label) in [
        (INSTALLER_TOKEN_NAME, INSTALLER_TOKEN_ENV, "i", "installer"),
        (ORG_TOKEN_NAME, ORG_TOKEN_ENV, "o", "org"),
        (MACHINE_TOKEN_NAME, MACHINE_TOKEN_ENV, "m", "machine"),
    ] {
        for (token, source) in
            cached_system_tokens(fname, || system_tokens_with_source(fname, label, env_var))
        {
            entries.push(TokenEntry {
                prefix: prefix_char.into(),
                label: label.into(),
                value: token,
                source,
            });
        }
    }

    Ok(entries)
}

/// Build the full token string.
///
/// Format: `[prefix...] [reqwest/{ver}] [platform...] [rattler/{ver}] aau/{ver} c/{client} s/{session} e/{env} [a/{cloud}] [i/{installer}] [o/{org}] [m/{machine}]`
pub fn token_string(config: &Config) -> Result<String> {
    let entries = collect_tokens(config)?;
    let result = entries_to_string(&entries);
    tracing::debug!("Full aau token string: {}", result);
    Ok(result)
}

/// Collect all AAU tokens with per-token provenance information.
///
/// Returns individual token entries including the `aau/` version entry.
/// The token string can be exactly reproduced by joining entries:
/// ```ignore
/// entries.iter().map(|e| format!("{}/{}", e.prefix, e.value)).collect::<Vec<_>>().join(" ")
/// ```
pub fn token_details(config: &Config) -> Result<Vec<TokenEntry>> {
    collect_tokens(config)
}

/// Join token entries into a space-separated token string.
///
/// Entries with a non-empty value are formatted as `prefix/value`.
/// Entries with an empty value are formatted as just `prefix`.
fn entries_to_string(entries: &[TokenEntry]) -> String {
    entries
        .iter()
        .map(|e| {
            if e.value.is_empty() {
                e.prefix.clone()
            } else {
                format!("{}/{}", e.prefix, e.value)
            }
        })
        .collect::<Vec<_>>()
        .join(" ")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn default_config() -> Config {
        Config {
            env_prefix: Some("/nonexistent/prefix".to_string()),
            ..Default::default()
        }
    }

    // ---- is_valid_token ----

    #[test]
    fn valid_token_alphanumeric() {
        assert!(is_valid_token("abc123XYZ"));
    }

    #[test]
    fn valid_token_with_underscores_and_dashes() {
        assert!(is_valid_token("my_token-v2"));
    }

    #[test]
    fn valid_token_max_length_36() {
        let token = "a".repeat(36);
        assert!(is_valid_token(&token));
    }

    #[test]
    fn invalid_token_too_long() {
        let token = "a".repeat(37);
        assert!(!is_valid_token(&token));
    }

    #[test]
    fn invalid_token_empty() {
        assert!(!is_valid_token(""));
    }

    #[test]
    fn invalid_token_special_chars() {
        assert!(!is_valid_token("token!@#$"));
    }

    #[test]
    fn invalid_token_spaces() {
        assert!(!is_valid_token("has space"));
    }

    #[test]
    fn invalid_token_slash() {
        assert!(!is_valid_token("a/b"));
    }

    #[test]
    fn valid_token_single_char() {
        assert!(is_valid_token("x"));
    }

    // ---- parse_token_value ----

    #[test]
    fn parse_single_token() {
        let mut results = Vec::new();
        parse_token_value("mytoken", "test", &mut results);
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].0, "mytoken");
    }

    #[test]
    fn parse_slash_containing_value_rejected() {
        let mut results = Vec::new();
        parse_token_value("token1/token2", "test", &mut results);
        assert!(
            results.is_empty(),
            "Slash-containing value should be rejected"
        );
    }

    #[test]
    fn parse_deduplicates() {
        let mut results = Vec::new();
        parse_token_value("dup", "test1", &mut results);
        parse_token_value("dup", "test2", &mut results);
        parse_token_value("dup", "test3", &mut results);
        assert_eq!(results.len(), 1);
    }

    #[test]
    fn parse_trims_whitespace() {
        let mut results = Vec::new();
        parse_token_value("  plain-token  ", "test", &mut results);
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].0, "plain-token");
    }

    #[test]
    fn parse_rejects_invalid_token() {
        let mut results = Vec::new();
        parse_token_value("b@d!", "test", &mut results);
        assert!(results.is_empty(), "Invalid token should be rejected");

        parse_token_value("good", "test", &mut results);
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].0, "good");
    }

    #[test]
    fn parse_empty_string() {
        let mut results = Vec::new();
        parse_token_value("", "test", &mut results);
        assert!(results.is_empty());
    }

    #[test]
    fn parse_appends_to_existing() {
        let mut results = vec![("existing".to_string(), "prior".to_string())];
        parse_token_value("new", "test", &mut results);
        let tokens: Vec<&str> = results.iter().map(|(t, _)| t.as_str()).collect();
        assert_eq!(tokens, vec!["existing", "new"]);
    }

    #[test]
    fn parse_dedup_across_existing() {
        let mut results = vec![("existing".to_string(), "prior".to_string())];
        parse_token_value("existing", "test", &mut results);
        parse_token_value("brand-new", "test", &mut results);
        let tokens: Vec<&str> = results.iter().map(|(t, _)| t.as_str()).collect();
        assert_eq!(tokens, vec!["existing", "brand-new"]);
    }

    // ---- system_tokens_with_source (via env vars) ----

    #[test]
    fn system_tokens_from_env_var() {
        let env_key = "AAU_TEST_SYSTEM_TOKEN_ENV_7382";
        // Slash-containing value is now rejected (matches Python behavior)
        unsafe { std::env::set_var(env_key, "envtoken1/envtoken2") };
        let result = system_tokens_with_source("nonexistent_file", "test", env_key);
        unsafe { std::env::remove_var(env_key) };
        assert!(
            result.is_empty(),
            "Slash-containing token should be rejected"
        );
    }

    #[test]
    fn system_tokens_empty_env_ignored() {
        let env_key = "AAU_TEST_SYSTEM_TOKEN_EMPTY_9281";
        unsafe { std::env::set_var(env_key, "   ") };
        let result = system_tokens_with_source("nonexistent_file", "test", env_key);
        unsafe { std::env::remove_var(env_key) };
        assert!(result.is_empty());
    }

    #[test]
    fn system_tokens_no_env_no_files_empty() {
        let env_key = "AAU_TEST_SYSTEM_TOKEN_NONE_4839";
        unsafe { std::env::remove_var(env_key) };
        let result = system_tokens_with_source("nonexistent_file", "test", env_key);
        assert!(result.is_empty());
    }

    // ---- jwt_to_token ----

    /// Build a minimal JWT for testing (no real signature).
    fn make_test_jwt(header: &serde_json::Value, payload: &serde_json::Value) -> String {
        let h = BASE64_URL_SAFE_NO_PAD.encode(serde_json::to_vec(header).unwrap());
        let p = BASE64_URL_SAFE_NO_PAD.encode(serde_json::to_vec(payload).unwrap());
        let sig = BASE64_URL_SAFE_NO_PAD.encode(b"fakesignature");
        format!("{}.{}.{}", h, p, sig)
    }

    #[test]
    fn jwt_valid_token_extracts_uuid() {
        let test_uuid = "d04c356b-afd2-4b3e-80f2-403113e0974b";
        let jwt = make_test_jwt(
            &serde_json::json!({"typ": "JWT", "alg": "RS256"}),
            &serde_json::json!({"sub": test_uuid, "exp": 4102444800_i64}),
        );
        let token = jwt_to_token(&jwt).unwrap();
        let decoded = BASE64_URL_SAFE_NO_PAD.decode(&token).unwrap();
        assert_eq!(decoded.len(), 16);
        let recovered = Uuid::from_bytes(decoded.try_into().unwrap());
        assert_eq!(recovered.to_string(), test_uuid);
    }

    #[test]
    fn jwt_expired_returns_none() {
        let jwt = make_test_jwt(
            &serde_json::json!({"typ": "JWT", "alg": "RS256"}),
            &serde_json::json!({"sub": "d04c356b-afd2-4b3e-80f2-403113e0974b", "exp": 1}),
        );
        assert!(jwt_to_token(&jwt).is_none());
    }

    #[test]
    fn jwt_missing_typ_returns_none() {
        let jwt = make_test_jwt(
            &serde_json::json!({"alg": "RS256"}),
            &serde_json::json!({"sub": "d04c356b-afd2-4b3e-80f2-403113e0974b", "exp": 4102444800_i64}),
        );
        assert!(jwt_to_token(&jwt).is_none());
    }

    #[test]
    fn jwt_missing_sub_returns_none() {
        let jwt = make_test_jwt(
            &serde_json::json!({"typ": "JWT", "alg": "RS256"}),
            &serde_json::json!({"exp": 4102444800_i64}),
        );
        assert!(jwt_to_token(&jwt).is_none());
    }

    #[test]
    fn jwt_invalid_uuid_sub_returns_none() {
        let jwt = make_test_jwt(
            &serde_json::json!({"typ": "JWT", "alg": "RS256"}),
            &serde_json::json!({"sub": "not-a-uuid", "exp": 4102444800_i64}),
        );
        assert!(jwt_to_token(&jwt).is_none());
    }

    #[test]
    fn jwt_not_a_jwt_returns_none() {
        assert!(jwt_to_token("just-a-plain-api-key").is_none());
        assert!(jwt_to_token("").is_none());
        assert!(jwt_to_token("a.b").is_none());
    }

    #[test]
    fn jwt_negative_exp_returns_none() {
        let jwt = make_test_jwt(
            &serde_json::json!({"typ": "JWT", "alg": "RS256"}),
            &serde_json::json!({"sub": "d04c356b-afd2-4b3e-80f2-403113e0974b", "exp": -1}),
        );
        assert!(jwt_to_token(&jwt).is_none());
    }

    // ---- anaconda_cloud_token ----

    #[test]
    fn anaconda_cloud_token_none_returns_none() {
        assert!(anaconda_cloud_token(None).is_none());
    }

    #[test]
    fn anaconda_cloud_token_empty_returns_none() {
        assert!(anaconda_cloud_token(Some("")).is_none());
    }

    #[test]
    fn anaconda_cloud_token_valid_jwt_extracts() {
        let test_uuid = "d04c356b-afd2-4b3e-80f2-403113e0974b";
        let jwt = make_test_jwt(
            &serde_json::json!({"typ": "JWT", "alg": "RS256"}),
            &serde_json::json!({"sub": test_uuid, "exp": 4102444800_i64}),
        );
        let result = anaconda_cloud_token(Some(&jwt));
        assert!(result.is_some());
    }

    #[test]
    fn anaconda_cloud_token_invalid_jwt_returns_none() {
        assert!(anaconda_cloud_token(Some("not-a-jwt")).is_none());
    }

    // ---- resolve_prefix / set_env_prefix ----

    #[test]
    fn resolve_prefix_explicit_wins_over_global() {
        crate::set_env_prefix("/global/prefix");
        let result = resolve_prefix(Some("/explicit/prefix"));
        assert_eq!(result.as_deref(), Some("/explicit/prefix"));
    }

    #[test]
    fn resolve_prefix_falls_back_to_global() {
        crate::set_env_prefix("/global/fallback");
        let result = resolve_prefix(None);
        assert_eq!(result.as_deref(), Some("/global/fallback"));
    }

    // ---- token_string / token_details ----

    #[test]
    fn token_string_starts_with_version() {
        let config = Config {
            env_prefix: Some("/nonexistent/prefix".into()),
            platform: false,
            ..Default::default()
        };
        let result = token_string(&config).unwrap();
        assert!(result.starts_with(&format!("aau/{}", VERSION)));
    }

    #[test]
    fn token_string_contains_client_and_session() {
        let result = token_string(&default_config()).unwrap();
        assert!(
            result.contains(" c/"),
            "expected client token in: {}",
            result
        );
        assert!(
            result.contains(" s/"),
            "expected session token in: {}",
            result
        );
    }

    #[test]
    fn token_details_first_entry_is_version() {
        let config = Config {
            env_prefix: Some("/nonexistent/prefix".into()),
            platform: false,
            ..Default::default()
        };
        let entries = token_details(&config).unwrap();
        assert!(!entries.is_empty());
        assert_eq!(entries[0].prefix, "aau");
        assert_eq!(entries[0].label, "version");
        assert_eq!(entries[0].value, VERSION);
    }

    #[test]
    fn token_string_equals_joined_details() {
        let config = default_config();
        let string = token_string(&config).unwrap();
        let entries = token_details(&config).unwrap();
        let rebuilt = entries_to_string(&entries);
        assert_eq!(string, rebuilt);
    }

    // ---- parse_prefix ----

    #[test]
    fn parse_prefix_single_token() {
        let entries = parse_prefix("ana/0.1.0");
        assert_eq!(entries.len(), 1);
        assert_eq!(entries[0].prefix, "ana");
        assert_eq!(entries[0].value, "0.1.0");
        assert_eq!(entries[0].label, "prefix");
    }

    #[test]
    fn parse_prefix_multiple_tokens() {
        let entries = parse_prefix("ana/0.1.0 rattler/0.40.5");
        assert_eq!(entries.len(), 2);
        assert_eq!(entries[0].prefix, "ana");
        assert_eq!(entries[0].value, "0.1.0");
        assert_eq!(entries[1].prefix, "rattler");
        assert_eq!(entries[1].value, "0.40.5");
    }

    #[test]
    fn parse_prefix_bare_word() {
        let entries = parse_prefix("myapp");
        assert_eq!(entries.len(), 1);
        assert_eq!(entries[0].prefix, "myapp");
        assert_eq!(entries[0].value, "");
    }

    #[test]
    fn parse_prefix_empty_string() {
        let entries = parse_prefix("");
        assert!(entries.is_empty());
    }

    #[test]
    fn parse_prefix_extra_whitespace() {
        let entries = parse_prefix("  ana/0.1.0   rattler/0.40.5  ");
        assert_eq!(entries.len(), 2);
    }

    // ---- entries_to_string with empty values ----

    #[test]
    fn entries_to_string_with_empty_value() {
        let entries = vec![
            TokenEntry {
                prefix: "myapp".into(),
                label: "prefix".into(),
                value: "".into(),
                source: "config".into(),
            },
            TokenEntry {
                prefix: "aau".into(),
                label: "version".into(),
                value: "0.7.6".into(),
                source: "build".into(),
            },
        ];
        assert_eq!(entries_to_string(&entries), "myapp aau/0.7.6");
    }

    // ---- prefix + platform ordering ----

    #[test]
    fn token_string_with_prefix_prepends() {
        let config = Config {
            env_prefix: Some("/nonexistent/prefix".into()),
            prefix: Some("ana/0.1.0".into()),
            platform: false,
            ..Default::default()
        };
        let result = token_string(&config).unwrap();
        assert!(
            result.starts_with("ana/0.1.0 aau/"),
            "expected prefix first, got: {}",
            result
        );
    }

    #[test]
    fn token_string_with_platform_prepends() {
        let config = Config {
            env_prefix: Some("/nonexistent/prefix".into()),
            platform: true,
            ..Default::default()
        };
        let result = token_string(&config).unwrap();
        // Platform tokens come before aau/
        let aau_pos = result.find("aau/").expect("should contain aau/");
        assert!(
            aau_pos > 0,
            "expected platform tokens before aau/, got: {}",
            result
        );
    }

    #[test]
    fn token_string_prefix_before_platform_before_aau() {
        let config = Config {
            env_prefix: Some("/nonexistent/prefix".into()),
            prefix: Some("ana/0.1.0".into()),
            platform: true,
            ..Default::default()
        };
        let result = token_string(&config).unwrap();
        let ana_pos = result.find("ana/0.1.0").expect("should contain prefix");
        let aau_pos = result.find("aau/").expect("should contain aau/");
        assert!(
            ana_pos < aau_pos,
            "prefix should come before aau tokens, got: {}",
            result
        );
        assert!(
            result.starts_with("ana/0.1.0"),
            "prefix should be first, got: {}",
            result
        );
    }

    #[test]
    fn token_details_with_prefix_has_prefix_label() {
        let config = Config {
            env_prefix: Some("/nonexistent/prefix".into()),
            prefix: Some("ana/0.1.0 rattler/0.40.5".into()),
            platform: false,
            ..Default::default()
        };
        let entries = token_details(&config).unwrap();
        assert_eq!(entries[0].label, "prefix");
        assert_eq!(entries[0].prefix, "ana");
        assert_eq!(entries[1].label, "prefix");
        assert_eq!(entries[1].prefix, "rattler");
        assert_eq!(entries[2].label, "version");
        assert_eq!(entries[2].prefix, "aau");
    }

    #[test]
    fn token_details_with_platform_has_platform_label() {
        let config = Config {
            env_prefix: Some("/nonexistent/prefix".into()),
            platform: true,
            ..Default::default()
        };
        let entries = token_details(&config).unwrap();
        // First entry should be platform
        assert_eq!(entries[0].label, "platform");
        // Find the aau entry
        let aau_idx = entries.iter().position(|e| e.prefix == "aau").unwrap();
        // All entries before aau should be platform
        for e in &entries[..aau_idx] {
            assert_eq!(e.label, "platform");
        }
    }

    // ---- test-support feature gating ----
    // The `test-support` feature must never be enabled in released binaries.
    // These tests lock in the observable behavior of the gating in both directions.

    #[cfg(feature = "test-support")]
    #[test]
    fn system_root_override_honored_with_test_support() {
        let tmp = tempfile::tempdir().unwrap();
        let override_path = tmp.path().to_path_buf();
        unsafe {
            std::env::set_var("ANACONDA_ANON_USAGE_TEST_SYSTEM_ROOT", &override_path);
        }
        let search_path = compute_search_path();
        unsafe {
            std::env::remove_var("ANACONDA_ANON_USAGE_TEST_SYSTEM_ROOT");
        }
        assert!(
            search_path.contains(&override_path),
            "with test-support, override path should appear in search path"
        );
        // And the real system dirs should NOT be included when the override is active
        assert!(
            !search_path.iter().any(|p| p == &PathBuf::from("/etc/conda")
                || p == &PathBuf::from("/var/lib/conda")
                || p == &PathBuf::from("C:/ProgramData/conda")),
            "override should replace system dirs, not append to them"
        );
    }

    #[cfg(not(feature = "test-support"))]
    #[test]
    fn system_root_override_ignored_without_test_support() {
        let tmp = tempfile::tempdir().unwrap();
        let override_path = tmp.path().to_path_buf();
        unsafe {
            std::env::set_var("ANACONDA_ANON_USAGE_TEST_SYSTEM_ROOT", &override_path);
        }
        let search_path = compute_search_path();
        unsafe {
            std::env::remove_var("ANACONDA_ANON_USAGE_TEST_SYSTEM_ROOT");
        }
        assert!(
            !search_path.contains(&override_path),
            "without test-support, override path MUST NOT appear in search path"
        );
    }
}
