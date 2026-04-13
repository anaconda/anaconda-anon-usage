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
    eprintln!("  --prefix PATH      Use PATH as the environment prefix");
    eprintln!("  --jwt TOKEN        Use TOKEN as the Anaconda auth JWT");
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
    let mut prefix: Option<String> = None;
    let mut jwt: Option<String> = None;
    let mut detail = false;

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
            "--prefix" => {
                i += 1;
                prefix = Some(args.get(i).unwrap_or_else(|| usage()).clone());
            }
            "--jwt" => {
                i += 1;
                jwt = Some(args.get(i).unwrap_or_else(|| usage()).clone());
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
        env_prefix: prefix,
        anaconda_jwt: jwt,
    };

    println!("{}", anaconda_anon_usage::token_string(&config));
    if detail {
        let entries = anaconda_anon_usage::token_details(&config);
        for t in &entries {
            println!("  {}/{} ({}) <- {}", t.prefix, t.value, t.label, t.source);
        }
    }

    if let Err(e) = anaconda_anon_usage::finalize_deferred_writes() {
        eprintln!("Warning: failed to flush deferred writes: {}", e);
    }
}
