use std::process::Command;

fn main() {
    // Re-run when git state changes (new tags, new commits).
    println!("cargo:rerun-if-changed=../.git/HEAD");
    println!("cargo:rerun-if-changed=../.git/refs/tags");
    println!("cargo:rerun-if-changed=../.git/index");

    // Derive AAU_VERSION using PEP 440 / semver convention:
    //   On tag:       "0.7.6"
    //   Past tag:     "0.7.6+3.gabcdef0"
    let version = git_version().unwrap_or_else(|| env!("CARGO_PKG_VERSION").to_string());
    println!("cargo:rustc-env=AAU_VERSION={}", version);

    // Rustc version for platform tokens (e.g., "1.82.0").
    let rustc_version = rustc_version().unwrap_or_default();
    println!("cargo:rustc-env=RUSTC_VERSION={}", rustc_version);

    // Feature-gated version extraction from the consumer's Cargo.lock.
    // These features carry no dependencies — they just signal build.rs to
    // look for the named crate in Cargo.lock and expose its version.
    if cfg!(feature = "rattler") {
        let ver = extract_lock_version("rattler").unwrap_or_default();
        println!("cargo:rustc-env=RATTLER_VERSION={}", ver);
    }
    if cfg!(feature = "reqwest") {
        let ver = extract_lock_version("reqwest").unwrap_or_default();
        println!("cargo:rustc-env=REQWEST_VERSION={}", ver);
    }
}

/// Derive version from `git describe --tags --long`.
///
/// Format: `{tag}-{distance}-g{hash}` → `{tag}` or `{tag}+{distance}.g{hash}`
fn git_version() -> Option<String> {
    let output = Command::new("git")
        .args(["describe", "--tags", "--long"])
        .current_dir(concat!(env!("CARGO_MANIFEST_DIR"), "/.."))
        .output()
        .ok()?;

    if !output.status.success() {
        return None;
    }

    let raw = String::from_utf8(output.stdout).ok()?.trim().to_string();

    // Split from the right: last segment is "g{hash}", second-to-last is distance.
    let mut parts: Vec<&str> = raw.rsplitn(3, '-').collect();
    parts.reverse();

    if parts.len() != 3 {
        return None;
    }

    let tag = parts[0];
    let distance: u32 = parts[1].parse().ok()?;
    let g_hash = parts[2]; // "gabcdef0"

    if distance == 0 {
        // Exactly on a tag.
        Some(tag.to_string())
    } else {
        // Past the tag: semver/PEP 440 local version.
        Some(format!("{}+{}.{}", tag, distance, g_hash))
    }
}

/// Extract the rustc version (e.g., "1.82.0").
///
/// Uses the $RUSTC env var that Cargo sets during builds, falling back to "rustc".
fn rustc_version() -> Option<String> {
    let rustc = std::env::var("RUSTC").unwrap_or_else(|_| "rustc".to_string());
    let output = Command::new(rustc).arg("--version").output().ok()?;
    if !output.status.success() {
        return None;
    }
    let stdout = String::from_utf8(output.stdout).ok()?;
    // "rustc 1.82.0 (f6e511eec 2024-10-15)" → "1.82.0"
    stdout.split_whitespace().nth(1).map(|s| s.to_string())
}

/// Extract a dependency's resolved version from the consumer's Cargo.lock.
///
/// Walks up from OUT_DIR — which cargo places inside the consumer's `target/`
/// directory regardless of whether this crate is a local path dep, a workspace
/// member, or a registry dep — to find the nearest Cargo.lock. CARGO_MANIFEST_DIR
/// is unsuitable because for a registry dep it points into the cargo cache
/// (~/.cargo/registry/...) which has no Cargo.lock above it.
///
/// If multiple versions of the same crate exist (e.g., reqwest 0.11 and 0.12
/// via transitive deps), returns the highest version. Consumers that need to
/// pin the reported version to their direct dep can set `Config::rattler_version`
/// or `Config::reqwest_version` explicitly at runtime.
fn extract_lock_version(dep_name: &str) -> Option<String> {
    let out_dir = std::path::PathBuf::from(std::env::var_os("OUT_DIR")?);
    let lock_path = find_cargo_lock(&out_dir)?;
    println!("cargo:rerun-if-changed={}", lock_path.display());
    let lockfile = cargo_lock::Lockfile::load(&lock_path).ok()?;
    lockfile
        .packages
        .iter()
        .filter(|p| p.name.as_str() == dep_name)
        .max_by(|a, b| a.version.cmp(&b.version))
        .map(|p| p.version.to_string())
}

/// Walk up from `start` to find the nearest Cargo.lock.
fn find_cargo_lock(start: &std::path::Path) -> Option<std::path::PathBuf> {
    let mut dir = start.to_path_buf();
    loop {
        let candidate = dir.join("Cargo.lock");
        if candidate.is_file() {
            return Some(candidate);
        }
        if !dir.pop() {
            return None;
        }
    }
}
