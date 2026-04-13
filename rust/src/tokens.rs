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
/// - Strips `/.condarc` suffixes to get parent directories
/// - Excludes the home directory itself (from `~/.condarc`)
/// - Only returns directories that exist on disk, deduplicated
///
/// Cached in a `LazyLock` — filesystem checks happen once per process.
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

    #[cfg(windows)]
    dirs.push("C:/ProgramData/conda".into());

    #[cfg(not(windows))]
    {
        dirs.push("/etc/conda".into());
        dirs.push("/var/lib/conda".into());
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

/// Parse a token value string into (token, source) pairs, deduplicating.
///
/// Token files may contain slash-separated multiple tokens (for org/machine tokens
/// set by administrators). Each token is validated against the AAU format before
/// inclusion.
fn parse_token_values(content: &str, source: &str, results: &mut Vec<(String, String)>) {
    for token in content.split('/') {
        let token = token.trim();
        if token.is_empty() {
            continue;
        }
        if !is_valid_token(token) {
            tracing::debug!("Invalid token discarded: {}", token);
            continue;
        }
        if !results.iter().any(|(t, _)| t == token) {
            results.push((token.to_string(), source.to_string()));
        }
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
            parse_token_values(&val, &format!("${}", env_var), &mut results);
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
                    parse_token_values(&content, &fpath.display().to_string(), &mut results);
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

/// Resolve the environment prefix: explicit arg > CONDA_PREFIX > None.
fn resolve_prefix(prefix: Option<&str>) -> Option<String> {
    if let Some(p) = prefix {
        return Some(p.to_string());
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

/// Collect all AAU tokens with provenance information.
///
/// This is the single source of truth for token assembly. The `aau/` version
/// entry is included as the first element. The token string can be exactly
/// reproduced by joining entries as `"{prefix}/{value}"`.
fn collect_tokens(config: &Config) -> Result<Vec<TokenEntry>> {
    let mut entries = Vec::new();

    // Version (always first)
    entries.push(TokenEntry {
        prefix: "aau",
        label: "version",
        value: VERSION.to_string(),
        source: "build".to_string(),
    });

    // Client token
    let client = client_token()?;
    if !client.is_empty() {
        let source = dirs::home_dir()
            .map(|h| h.join(".conda/aau_token").display().to_string())
            .unwrap_or_default();
        entries.push(TokenEntry {
            prefix: "c",
            label: "client",
            value: client,
            source,
        });
    }

    // Session token
    let session = session_token()?;
    if !session.is_empty() {
        entries.push(TokenEntry {
            prefix: "s",
            label: "session",
            value: session,
            source: "random (per-process)".to_string(),
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
            prefix: "e",
            label: "environment",
            value: environment,
            source: env_path,
        });
    }

    // Anaconda Cloud token (extracted from caller-provided JWT)
    let jwt = config.anaconda_jwt.clone();
    let jwt_key = format!("anaconda_cloud_token_{}", jwt.as_deref().unwrap_or(""));
    if let Some(cloud) = cached_option(&jwt_key, || anaconda_cloud_token(jwt.as_deref())) {
        entries.push(TokenEntry {
            prefix: "a",
            label: "anaconda",
            value: cloud,
            source: "JWT".to_string(),
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
                prefix: prefix_char,
                label,
                value: token,
                source,
            });
        }
    }

    Ok(entries)
}

/// Build the full AAU token string.
///
/// Format: `aau/0.7.6 c/{client} s/{session} e/{env} a/{cloud} i/{installer} o/{org} m/{machine}`
///
/// Equivalent to joining the entries from [`token_details`] as `"{prefix}/{value}"`.
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
fn entries_to_string(entries: &[TokenEntry]) -> String {
    entries
        .iter()
        .map(|e| format!("{}/{}", e.prefix, e.value))
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

    // ---- parse_token_values ----

    #[test]
    fn parse_single_token() {
        let mut results = Vec::new();
        parse_token_values("mytoken", "test", &mut results);
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].0, "mytoken");
    }

    #[test]
    fn parse_slash_separated_tokens() {
        let mut results = Vec::new();
        parse_token_values("token1/token2/token3", "test", &mut results);
        let tokens: Vec<&str> = results.iter().map(|(t, _)| t.as_str()).collect();
        assert_eq!(tokens, vec!["token1", "token2", "token3"]);
    }

    #[test]
    fn parse_deduplicates() {
        let mut results = Vec::new();
        parse_token_values("dup/dup/dup", "test", &mut results);
        assert_eq!(results.len(), 1);
    }

    #[test]
    fn parse_skips_empty_segments() {
        let mut results = Vec::new();
        parse_token_values("a//b/", "test", &mut results);
        let tokens: Vec<&str> = results.iter().map(|(t, _)| t.as_str()).collect();
        assert_eq!(tokens, vec!["a", "b"]);
    }

    #[test]
    fn parse_trims_whitespace() {
        let mut results = Vec::new();
        parse_token_values("  tok1 / tok2 ", "test", &mut results);
        let tokens: Vec<&str> = results.iter().map(|(t, _)| t.as_str()).collect();
        assert_eq!(tokens, vec!["tok1", "tok2"]);
    }

    #[test]
    fn parse_skips_invalid_tokens() {
        let mut results = Vec::new();
        parse_token_values("good/b@d!/also-good", "test", &mut results);
        let tokens: Vec<&str> = results.iter().map(|(t, _)| t.as_str()).collect();
        assert_eq!(tokens, vec!["good", "also-good"]);
    }

    #[test]
    fn parse_empty_string() {
        let mut results = Vec::new();
        parse_token_values("", "test", &mut results);
        assert!(results.is_empty());
    }

    #[test]
    fn parse_appends_to_existing() {
        let mut results = vec![("existing".to_string(), "prior".to_string())];
        parse_token_values("new", "test", &mut results);
        let tokens: Vec<&str> = results.iter().map(|(t, _)| t.as_str()).collect();
        assert_eq!(tokens, vec!["existing", "new"]);
    }

    #[test]
    fn parse_dedup_across_existing() {
        let mut results = vec![("existing".to_string(), "prior".to_string())];
        parse_token_values("existing/brand-new", "test", &mut results);
        let tokens: Vec<&str> = results.iter().map(|(t, _)| t.as_str()).collect();
        assert_eq!(tokens, vec!["existing", "brand-new"]);
    }

    // ---- system_tokens_with_source (via env vars) ----

    #[test]
    fn system_tokens_from_env_var() {
        let env_key = "AAU_TEST_SYSTEM_TOKEN_ENV_7382";
        unsafe { std::env::set_var(env_key, "envtoken1/envtoken2") };
        let result = system_tokens_with_source("nonexistent_file", "test", env_key);
        unsafe { std::env::remove_var(env_key) };
        let tokens: Vec<&str> = result.iter().map(|(t, _)| t.as_str()).collect();
        assert_eq!(tokens, vec!["envtoken1", "envtoken2"]);
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

    // ---- token_string / token_details ----

    #[test]
    fn token_string_starts_with_version() {
        let result = token_string(&default_config()).unwrap();
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
        let entries = token_details(&default_config()).unwrap();
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
        let rebuilt: String = entries
            .iter()
            .map(|e| format!("{}/{}", e.prefix, e.value))
            .collect::<Vec<_>>()
            .join(" ");
        assert_eq!(string, rebuilt);
    }
}
