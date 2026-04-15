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
