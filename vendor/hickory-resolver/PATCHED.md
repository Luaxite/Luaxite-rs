# hickory-resolver 0.26.3 (patched copy)

Upstream: https://crates.io/crates/hickory-resolver/0.26.3 (https://github.com/hickory-dns/hickory-dns), MIT OR Apache-2.0.

Changes (Android only):

- `src/system_conf/android.rs` no longer uses JNI. Upstream calls `ndk_context::android_context()`, which panics ("android context was not initialized") in a
  plain native executable such as one run from Termux: there is no JavaVM or Activity, and azalea's `unwrap_or_else` fallback to Google DNS never runs because
  it is a panic, not an `Err`. The copy reads the first `resolv.conf` with a `nameserver` (`$PREFIX/etc/resolv.conf`, the Termux path, `/etc/resolv.conf`,
  `/system/etc/resolv.conf`) and returns an `Err` when there is none, so callers can fall back.
- `Cargo.toml`: the Android-only `jni` and `ndk-context` dependencies (and their `dep:` entries in `system-config`) are removed, as are the `[[example]]`,
  `[[test]]` and `[[bench]]` tables (their files are not vendored).

Other targets are unchanged. Wired in with `[patch.crates-io]` in the root Cargo.toml. Remove both once upstream stops panicking without an Android context.
