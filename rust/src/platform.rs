//! Platform identification for the user-agent string.
//!
//! Format aligns with conda's user-agent conventions where possible:
//!   `{kernel}/{release} [{os}/{version}] [glibc/{version}]`
//!
//! All platform detection uses direct syscalls or file reads — no subprocesses.

use std::sync::LazyLock;

/// A single platform token (e.g., `("Darwin", "25.2.0")` or `("OSX", "26.2")`).
#[derive(Debug, Clone)]
pub struct PlatformToken {
    /// Token name (e.g., `"Darwin"`, `"OSX"`, `"glibc"`).
    pub name: String,
    /// Token value (e.g., `"25.2.0"`, `"26.2"`).
    pub value: String,
}

/// Cached platform tokens (computed once per process).
static PLATFORM_TOKENS: LazyLock<Vec<PlatformToken>> = LazyLock::new(build_platform_tokens);

/// Return the cached platform tokens.
///
/// Examples:
///   macOS:   `[Darwin/25.2.0, OSX/26.2]`
///   Linux:   `[Linux/6.5.0, ubuntu/22.04, glibc/2.35]`
///   Windows: `[Windows/10.0.22631]`
pub fn platform_tokens() -> &'static [PlatformToken] {
    &PLATFORM_TOKENS
}

fn build_platform_tokens() -> Vec<PlatformToken> {
    let mut tokens = Vec::new();

    let (system, release) = system_release();
    tokens.push(PlatformToken {
        name: system,
        value: release,
    });

    if let Some((name, version)) = os_distribution() {
        tokens.push(PlatformToken {
            name,
            value: version,
        });
    }

    if let Some((family, version)) = libc_version() {
        tokens.push(PlatformToken {
            name: family,
            value: version,
        });
    }

    let rustc = crate::RUSTC_VERSION;
    if !rustc.is_empty() {
        tokens.push(PlatformToken {
            name: "rustc".to_string(),
            value: rustc.to_string(),
        });
    }

    tokens
}

/// Get the kernel name and release version via libc::uname.
#[cfg(unix)]
fn system_release() -> (String, String) {
    unsafe {
        let mut info: libc::utsname = std::mem::zeroed();
        if libc::uname(&mut info) == 0 {
            let system = std::ffi::CStr::from_ptr(info.sysname.as_ptr())
                .to_string_lossy()
                .into_owned();
            let release = std::ffi::CStr::from_ptr(info.release.as_ptr())
                .to_string_lossy()
                .into_owned();
            return (system, release);
        }
    }
    (std::env::consts::OS.to_string(), String::from("unknown"))
}

/// Get the Windows version via RtlGetVersion (ntdll.dll FFI).
///
/// Unlike GetVersionEx, RtlGetVersion is not subject to the compatibility
/// shim that lies about the version on Windows 8.1+.
#[cfg(not(unix))]
fn system_release() -> (String, String) {
    #[repr(C)]
    struct OsVersionInfoExW {
        os_version_info_size: u32,
        major_version: u32,
        minor_version: u32,
        build_number: u32,
        platform_id: u32,
        csd_version: [u16; 128],
        service_pack_major: u16,
        service_pack_minor: u16,
        suite_mask: u16,
        product_type: u8,
        reserved: u8,
    }

    unsafe {
        #[link(name = "ntdll")]
        unsafe extern "system" {
            fn RtlGetVersion(lp_version_information: *mut OsVersionInfoExW) -> i32;
        }

        let mut info: OsVersionInfoExW = std::mem::zeroed();
        info.os_version_info_size = std::mem::size_of::<OsVersionInfoExW>() as u32;

        if RtlGetVersion(&mut info) == 0 {
            let release = format!(
                "{}.{}.{}",
                info.major_version, info.minor_version, info.build_number
            );
            return ("Windows".to_string(), release);
        }
    }

    ("Windows".to_string(), "unknown".to_string())
}

/// Get the OS distribution name and version.
///
/// On macOS: returns ("OSX", version) via SystemVersion.plist
/// On Linux: returns distro info via /etc/os-release
/// On Windows: returns None (system_release already covers it)
fn os_distribution() -> Option<(String, String)> {
    #[cfg(target_os = "macos")]
    {
        macos_version()
    }

    #[cfg(target_os = "linux")]
    {
        linux_distribution()
    }

    #[cfg(not(any(target_os = "macos", target_os = "linux")))]
    {
        None
    }
}

#[cfg(target_os = "macos")]
fn macos_version() -> Option<(String, String)> {
    // Read SystemVersion.plist directly rather than shelling out to sw_vers.
    // Note: processes linked against SDK <= 10.15 see a shimmed "10.16" here
    // instead of the real version (11+). This doesn't affect us because we
    // compile against a modern SDK, but conda's Python-based approach needs
    // a sw_vers fallback for that reason.
    let content =
        std::fs::read_to_string("/System/Library/CoreServices/SystemVersion.plist").ok()?;
    let version = parse_plist_key(&content, "ProductVersion")?;
    Some(("OSX".to_string(), version))
}

/// Extract a string value for `key` from a simple XML plist.
#[cfg(target_os = "macos")]
fn parse_plist_key(xml: &str, key: &str) -> Option<String> {
    let mut lines = xml.lines();
    while let Some(line) = lines.next() {
        if line.trim() == format!("<key>{}</key>", key) {
            let val_line = lines.next()?.trim().to_string();
            return val_line
                .strip_prefix("<string>")
                .and_then(|s| s.strip_suffix("</string>"))
                .map(|s| s.to_string());
        }
    }
    None
}

#[cfg(target_os = "linux")]
fn linux_distribution() -> Option<(String, String)> {
    // Reads /etc/os-release directly. conda uses the `distro` Python package
    // which has additional fallbacks (/etc/lsb-release, distro-specific files),
    // but /etc/os-release is standard on all modern distros.
    let content = std::fs::read_to_string("/etc/os-release").ok()?;
    let mut name = None;
    let mut version = None;
    for line in content.lines() {
        if let Some(val) = line.strip_prefix("NAME=") {
            name = Some(val.trim_matches('"').to_string());
        } else if let Some(val) = line.strip_prefix("VERSION_ID=") {
            version = Some(val.trim_matches('"').to_string());
        }
    }
    // Lowercase to match conda's distro.id() convention (e.g. "ubuntu" not "Ubuntu").
    Some((name?.to_lowercase(), version.unwrap_or_default()))
}

/// Get the C library family and version.
///
/// On Linux (glibc): returns ("glibc", version) via gnu_get_libc_version().
/// On other platforms (including musl-based Linux): returns None.
fn libc_version() -> Option<(String, String)> {
    #[cfg(all(target_os = "linux", target_env = "gnu"))]
    {
        linux_libc_version()
    }

    #[cfg(not(all(target_os = "linux", target_env = "gnu")))]
    {
        None
    }
}

#[cfg(all(target_os = "linux", target_env = "gnu"))]
fn linux_libc_version() -> Option<(String, String)> {
    unsafe {
        let ver = std::ffi::CStr::from_ptr(libc::gnu_get_libc_version())
            .to_string_lossy()
            .into_owned();
        if ver.is_empty() {
            return None;
        }
        Some(("glibc".to_string(), ver))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_platform_tokens_not_empty() {
        let tokens = platform_tokens();
        assert!(!tokens.is_empty());
    }

    #[test]
    fn test_system_release_reasonable() {
        let (system, release) = system_release();
        assert!(!system.is_empty());
        assert!(!release.is_empty());
        assert_ne!(release, "unknown");
    }

    #[test]
    fn test_first_token_is_kernel() {
        let tokens = platform_tokens();
        let first = &tokens[0];
        if cfg!(target_os = "macos") {
            assert_eq!(first.name, "Darwin");
        } else if cfg!(target_os = "linux") {
            assert_eq!(first.name, "Linux");
        } else if cfg!(target_os = "windows") {
            assert_eq!(first.name, "Windows");
        }
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn test_macos_includes_osx() {
        let tokens = platform_tokens();
        assert!(
            tokens.iter().any(|t| t.name == "OSX"),
            "expected OSX token, got: {:?}",
            tokens
        );
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn test_linux_includes_distro() {
        let tokens = platform_tokens();
        // Should have at least kernel + distro
        assert!(tokens.len() >= 2, "expected distro token on Linux");
    }

    #[cfg(all(target_os = "linux", target_env = "gnu"))]
    #[test]
    fn test_linux_includes_glibc() {
        let tokens = platform_tokens();
        assert!(
            tokens.iter().any(|t| t.name == "glibc"),
            "expected glibc token, got: {:?}",
            tokens
        );
    }
}
