//! File I/O, token persistence, and MAC-based node-tying utilities.

use super::{DeferredWrite, Result, DEFERRED};
use base64::Engine;
use mac_address::get_mac_address;
use std::fs;
use std::path::{Path, PathBuf};
use tracing::{debug, error};

/// 16 bytes of entropy, base64url-encoded (⌈16×4/3⌉ = 22).
const TOKEN_LENGTH: usize = 22;

/// Result of attempting to write a token file to disk.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum WriteStatus {
    /// Token was written successfully.
    Success,
    /// Target directory doesn't exist yet; write queued for later.
    Defer,
    /// Write failed (permissions, I/O error, etc.).
    Fail,
}

/// Generate a random 22-character URL-safe base64 token.
pub fn random_token(what: &str) -> Result<String> {
    let num_bytes = (TOKEN_LENGTH * 6 - 1) / 8 + 1;
    let mut bytes = vec![0u8; num_bytes];
    getrandom::fill(&mut bytes).map_err(|e| super::Error::Other(e.to_string()))?;

    let result = base64::engine::general_purpose::URL_SAFE_NO_PAD
        .encode(&bytes)
        .chars()
        .take(TOKEN_LENGTH)
        .collect::<String>();

    debug!("Generated {} token: {}", what, result);
    Ok(result)
}

/// Get the system's MAC address as a URL-safe base64 string (for VM cloning detection).
///
/// Matches the Python implementation exactly:
///   `val.to_bytes(6, byteorder=sys.byteorder)` followed by `urlsafe_b64encode`.
///
/// Python uses `uuid._unix_getnode()` which returns a 48-bit integer, then converts
/// it to bytes using the **system's native byte order**. `mac_address::get_mac_address()`
/// returns bytes in network order (big-endian), so on little-endian systems we must
/// reverse the bytes before encoding.
pub fn get_node_str() -> String {
    match get_mac_address() {
        Ok(Some(mac)) => {
            let mut bytes = mac.bytes();
            // Python: int.to_bytes(6, byteorder=sys.byteorder)
            // MAC bytes from the crate are in network (big-endian) order.
            // On little-endian systems, reverse to match Python's encoding.
            if cfg!(target_endian = "little") {
                bytes.reverse();
            }
            base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(bytes)
        }
        Ok(None) => {
            debug!("No MAC address found");
            String::new()
        }
        Err(e) => {
            debug!("Error getting MAC address: {}", e);
            String::new()
        }
    }
}

/// Flush all deferred token writes to disk.
pub fn final_attempt() -> Result<()> {
    let deferred = {
        let mut d = DEFERRED.lock().unwrap_or_else(|e| e.into_inner());
        std::mem::take(&mut *d)
    };

    for write in deferred {
        if let WriteStatus::Fail =
            write_attempt(write.must_exist.as_deref(), &write.filepath, &write.token)
        {
            tracing::warn!("Deferred write failed for {:?}", write.filepath);
        }
    }

    Ok(())
}

/// Attempt to write a token to disk.
fn write_attempt(must_exist: Option<&Path>, fpath: &Path, token: &str) -> WriteStatus {
    if let Some(dir) = must_exist {
        if !dir.is_dir() {
            debug!("Directory not ready: {:?}", dir);
            return WriteStatus::Defer;
        }
    }

    if let Some(parent) = fpath.parent() {
        if let Err(e) = fs::create_dir_all(parent) {
            error!("Failed to create directory {:?}: {}", parent, e);
            return WriteStatus::Fail;
        }
    }

    match fs::write(fpath, token) {
        Ok(_) => {
            debug!("Token saved: {:?}", fpath);
            WriteStatus::Success
        }
        Err(e) => {
            if e.kind() == std::io::ErrorKind::PermissionDenied {
                debug!("No write permissions; cannot write token");
            } else {
                error!(
                    "Unexpected error writing token file:\n  path: {:?}\n  exception: {}",
                    fpath, e
                );
            }
            WriteStatus::Fail
        }
    }
}

fn deferred_exists(fpath: &Path, label: &str) -> Option<String> {
    let deferred = DEFERRED.lock().unwrap_or_else(|e| e.into_inner());
    for write in deferred.iter() {
        if write.filepath == fpath && write.label == label {
            return Some(write.token.clone());
        }
    }
    None
}

/// Read a token file, checking the deferred write queue first.
pub fn read_file(fpath: &Path, label: &str, single_line: bool) -> Result<String> {
    // Check deferred writes first
    if let Some(token) = deferred_exists(fpath, label) {
        debug!("Returning deferred {}: {}", label, token);
        return Ok(token);
    }

    debug!("{} path: {:?}", label, fpath);

    if !fpath.exists() {
        debug!("{} file is not present", label);
        return Ok(String::new());
    }

    match fs::read_to_string(fpath) {
        Ok(mut data) => {
            if single_line {
                data = data.trim().to_string();
                if let Some(line) = data.lines().next() {
                    data = line.to_string();
                }
            }
            debug!("Retrieved {}: {}", label, data);
            Ok(data)
        }
        Err(e) => {
            error!("Unexpected error reading: {:?}\n  {}", fpath, e);
            Err(e.into())
        }
    }
}

/// Read or generate a persistent token with optional MAC-based node-tying.
///
/// If the token file doesn't exist or the MAC address has changed (VM cloning),
/// generates a new token and persists it. Defers the write if the target directory
/// doesn't exist yet.
///
/// Unlike the Python implementation, this does not handle the legacy format where
/// the host ID was appended to the token file with a space separator. Rust consumers
/// always use the current format: separate `aau_token` and `aau_token_host` files.
pub fn saved_token(
    fpath: &Path,
    label: &str,
    must_exist: Option<PathBuf>,
    read_only: bool,
    node_tie: bool,
) -> Result<String> {
    let label = format!("{} token", label);
    let mut regenerate = false;

    let client_token = read_file(fpath, &label, true)?;

    if client_token.len() < TOKEN_LENGTH {
        if !client_token.is_empty() {
            debug!("Regenerating {} due to short length", label);
        }
        regenerate = true;
    }

    if node_tie {
        let current_node = get_node_str();
        let npath = PathBuf::from(format!("{}_host", fpath.display()));
        let saved_node = read_file(&npath, "Host id", true)?;

        if !regenerate && !saved_node.is_empty() {
            if saved_node != current_node {
                debug!("Regenerating {} due to hostID change", label);
                regenerate = true;
            } else {
                debug!("Host ID match confirmed for {}", label);
            }
        }

        if saved_node != current_node {
            let action = if saved_node.is_empty() {
                "Saving"
            } else {
                "Updating"
            };
            debug!("{} host ID: {}", action, current_node);

            if write_attempt(None, &npath, &current_node) == WriteStatus::Defer {
                DEFERRED
                    .lock()
                    .unwrap_or_else(|e| e.into_inner())
                    .push(DeferredWrite {
                        must_exist: None,
                        filepath: npath,
                        token: current_node,
                        label: "Host ID".to_string(),
                    });
            }
        }
    }

    if regenerate {
        if read_only {
            return Ok(String::new());
        }

        let final_token = random_token("client")?;

        let status = write_attempt(must_exist.as_deref(), fpath, &final_token);
        match status {
            WriteStatus::Fail => {
                debug!("Returning blank {}", label);
                return Ok(String::new());
            }
            WriteStatus::Defer => {
                debug!("Deferring {} write", label);
                DEFERRED
                    .lock()
                    .unwrap_or_else(|e| e.into_inner())
                    .push(DeferredWrite {
                        must_exist,
                        filepath: fpath.to_path_buf(),
                        token: final_token.clone(),
                        label,
                    });
            }
            WriteStatus::Success => {}
        }

        return Ok(final_token);
    }

    Ok(client_token)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    // ---- random_token ----

    #[test]
    fn random_token_length() {
        let token = random_token("test").unwrap();
        assert_eq!(token.len(), TOKEN_LENGTH);
    }

    #[test]
    fn random_token_url_safe_chars() {
        let token = random_token("test").unwrap();
        assert!(
            token
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-'),
            "token contains non-URL-safe chars: {}",
            token
        );
    }

    #[test]
    fn random_token_unique() {
        let t1 = random_token("test").unwrap();
        let t2 = random_token("test").unwrap();
        assert_ne!(t1, t2, "two random tokens should differ");
    }

    // ---- get_node_str ----

    #[test]
    fn get_node_str_returns_string() {
        // May be empty on systems without a MAC, but should not panic
        let node = get_node_str();
        if !node.is_empty() {
            assert!(!node.is_empty());
        }
    }

    // ---- write_attempt ----

    #[test]
    fn write_attempt_success() {
        let dir = tempfile::tempdir().unwrap();
        let fpath = dir.path().join("test_token");
        let status = write_attempt(None, &fpath, "hello");
        assert_eq!(status, WriteStatus::Success);
        assert_eq!(fs::read_to_string(&fpath).unwrap(), "hello");
    }

    #[test]
    fn write_attempt_creates_parent_dirs() {
        let dir = tempfile::tempdir().unwrap();
        let fpath = dir.path().join("deep").join("nested").join("token");
        let status = write_attempt(None, &fpath, "nested-tok");
        assert_eq!(status, WriteStatus::Success);
        assert_eq!(fs::read_to_string(&fpath).unwrap(), "nested-tok");
    }

    #[test]
    fn write_attempt_defer_when_must_exist_missing() {
        let fpath = Path::new("/tmp/aau_test_write_defer_token");
        let status = write_attempt(Some(Path::new("/nonexistent/dir")), fpath, "tok");
        assert_eq!(status, WriteStatus::Defer);
    }

    #[test]
    fn write_attempt_proceeds_when_must_exist_present() {
        let dir = tempfile::tempdir().unwrap();
        let fpath = dir.path().join("token_file");
        let status = write_attempt(Some(dir.path()), &fpath, "tok2");
        assert_eq!(status, WriteStatus::Success);
        assert_eq!(fs::read_to_string(&fpath).unwrap(), "tok2");
    }

    // ---- read_file ----

    #[test]
    fn read_file_nonexistent_returns_empty() {
        let result = read_file(Path::new("/nonexistent/file"), "test", true).unwrap();
        assert_eq!(result, "");
    }

    #[test]
    fn read_file_single_line_takes_first() {
        let dir = tempfile::tempdir().unwrap();
        let fpath = dir.path().join("tok");
        fs::write(&fpath, "my-token\nsecondline\n").unwrap();
        let result = read_file(&fpath, "test", true).unwrap();
        assert_eq!(result, "my-token");
    }

    #[test]
    fn read_file_single_line_trims_surrounding_whitespace() {
        let dir = tempfile::tempdir().unwrap();
        let fpath = dir.path().join("tok");
        fs::write(&fpath, "\n  my-token  \n").unwrap();
        let result = read_file(&fpath, "test", true).unwrap();
        assert_eq!(result, "my-token");
    }

    #[test]
    fn read_file_multi_line() {
        let dir = tempfile::tempdir().unwrap();
        let fpath = dir.path().join("tok");
        fs::write(&fpath, "line1\nline2\n").unwrap();
        let result = read_file(&fpath, "test", false).unwrap();
        assert_eq!(result, "line1\nline2\n");
    }

    // ---- saved_token ----

    #[test]
    fn saved_token_creates_new_when_missing() {
        let dir = tempfile::tempdir().unwrap();
        let fpath = dir.path().join("aau_token");
        let token = saved_token(&fpath, "test", None, false, false).unwrap();
        assert_eq!(token.len(), TOKEN_LENGTH);
        // Should be persisted
        assert_eq!(fs::read_to_string(&fpath).unwrap(), token);
    }

    #[test]
    fn saved_token_returns_existing() {
        let dir = tempfile::tempdir().unwrap();
        let fpath = dir.path().join("aau_token");
        let existing = "abcdefghijklmnopqrstuv"; // 22 chars
        fs::write(&fpath, existing).unwrap();
        let token = saved_token(&fpath, "test", None, false, false).unwrap();
        assert_eq!(token, existing);
    }

    #[test]
    fn saved_token_regenerates_short_token() {
        let dir = tempfile::tempdir().unwrap();
        let fpath = dir.path().join("aau_token");
        fs::write(&fpath, "short").unwrap();
        let token = saved_token(&fpath, "test", None, false, false).unwrap();
        assert_eq!(token.len(), TOKEN_LENGTH);
        assert_ne!(token, "short");
    }

    #[test]
    fn saved_token_read_only_returns_empty_for_missing() {
        let dir = tempfile::tempdir().unwrap();
        let fpath = dir.path().join("aau_token");
        let token = saved_token(&fpath, "test", None, true, false).unwrap();
        assert_eq!(token, "");
    }

    // ---- final_attempt (deferred writes) ----

    #[test]
    fn final_attempt_flushes_deferred() {
        let dir = tempfile::tempdir().unwrap();
        let fpath = dir.path().join("deferred_tok");
        {
            let mut d = DEFERRED.lock().unwrap();
            d.push(DeferredWrite {
                must_exist: None,
                filepath: fpath.clone(),
                token: "deferred-value".to_string(),
                label: "test".to_string(),
            });
        }
        final_attempt().unwrap();
        assert_eq!(fs::read_to_string(&fpath).unwrap(), "deferred-value");
    }
}
