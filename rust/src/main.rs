//! CLI for testing anaconda-anon-usage token generation.

use anaconda_anon_usage::{Config, VERSION};

fn usage() -> ! {
    eprintln!("anaconda-anon-usage {} (Rust crate)", VERSION);
    eprintln!();
    eprintln!("Usage: anaconda-anon-usage [options]");
    eprintln!();
    eprintln!("Options:");
    eprintln!("  --verbose          Enable debug logging");
    eprintln!("  --detail           Print per-token provenance");
    eprintln!("  --env-prefix PATH  Use PATH as the environment prefix");
    eprintln!("  --jwt TOKEN        Use TOKEN as the Anaconda auth JWT");
    eprintln!("  --platform         Include platform tokens (e.g., Darwin/25.2.0 OSX/26.2)");
    eprintln!("  --ua-prefix STR    Prepend STR to the token string (e.g., \"ana/0.1.0\")");
    eprintln!("  --rattler VER      Include rattler/VER token");
    eprintln!("  --reqwest VER      Include reqwest/VER token");
    eprintln!("  --no-keyring       Disable keyring lookups (no-op for Rust)");
    eprintln!("  --paths            Print the system token search path");
    eprintln!("  --random           Generate and print a random token");
    eprintln!("  --version          Print the crate version");
    std::process::exit(1);
}

fn init_tracing(verbosity: u8) {
    use tracing_subscriber::EnvFilter;

    let level = match verbosity {
        0 => "error",
        1 => "debug",
        _ => "trace",
    };

    let filter = EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new(level));

    tracing_subscriber::fmt()
        .with_env_filter(filter)
        .with_writer(std::io::stderr)
        .without_time()
        .init();
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();

    let mut verbosity: u8 = 0;
    let mut env_prefix: Option<String> = None;
    let mut jwt: Option<String> = None;
    let mut detail = false;
    let mut platform = false;
    let mut ua_prefix: Option<String> = None;
    let mut rattler_version: Option<String> = None;
    let mut reqwest_version: Option<String> = None;

    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--verbose" => {
                verbosity += 1;
            }
            "--help" => usage(),
            "--version" => {
                println!("{}", VERSION);
                return;
            }
            "--paths" => {
                for p in anaconda_anon_usage::search_path() {
                    println!("{}", p.display());
                }
                return;
            }
            "--random" => {
                println!("{}", anaconda_anon_usage::random_token());
                return;
            }
            "--prefix" | "--env-prefix" => {
                i += 1;
                env_prefix = Some(args.get(i).unwrap_or_else(|| usage()).clone());
            }
            "--jwt" => {
                i += 1;
                jwt = Some(args.get(i).unwrap_or_else(|| usage()).clone());
            }
            "--platform" => {
                platform = true;
            }
            "--ua-prefix" => {
                i += 1;
                ua_prefix = Some(args.get(i).unwrap_or_else(|| usage()).clone());
            }
            "--rattler" => {
                i += 1;
                rattler_version = Some(args.get(i).unwrap_or_else(|| usage()).clone());
            }
            "--reqwest" => {
                i += 1;
                reqwest_version = Some(args.get(i).unwrap_or_else(|| usage()).clone());
            }
            "--detail" => {
                detail = true;
            }
            "--no-keyring" => {
                // Accepted for CLI parity with the Python package, but
                // the Rust crate never reads keyrings directly.
            }
            _ => {
                eprintln!("Unknown option: {}", args[i]);
                usage();
            }
        }
        i += 1;
    }

    init_tracing(verbosity);

    let config = Config {
        env_prefix,
        anaconda_jwt: jwt,
        platform,
        prefix: ua_prefix,
        rattler_version,
        reqwest_version,
    };

    println!("{}", anaconda_anon_usage::token_string(&config));
    if detail {
        let entries = anaconda_anon_usage::token_details(&config);
        for t in &entries {
            println!("  {}/{} ({}) <- {}", t.prefix, t.value, t.label, t.source);
        }
    }
}
