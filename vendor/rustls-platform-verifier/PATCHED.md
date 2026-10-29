# rustls-platform-verifier 0.7.1 (patched copy)

Upstream: https://crates.io/crates/rustls-platform-verifier/0.7.1 (https://github.com/rustls/rustls-platform-verifier), MIT OR Apache-2.0.

reqwest 0.13 (used by azalea for Microsoft/Mojang auth) verifies TLS with this crate, and on Android it needs a JavaVM that a native executable run from
Termux does not have, so `reqwest::Client::new()` fails (`ndk-context` panics / "JVM not initialized").

Changes (Android only):

- `src/verification/others.rs` is used on Android too, with the bundled Mozilla roots (`webpki-root-certs`, same as its wasm32 path) instead of the system store.
- Removed the JNI code (`src/android.rs`, `src/verification/android.rs`), the `jni` / `once_cell` / `rustls-platform-verifier-android` / `android_logger`
  dependencies, the test fixtures (`src/tests`) and the examples. Added a no-op `ffi-testing` feature so existing `cfg(feature = "ffi-testing")` checks still resolve.

Other targets (Linux, macOS, Windows) are unchanged. Wired in with `[patch.crates-io]` in the root Cargo.toml. Remove both once upstream can run without a JVM.
