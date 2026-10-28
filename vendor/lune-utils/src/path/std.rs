
use std::{
    env::{current_dir, current_exe},
    ffi::OsStr,
    path::{Component, MAIN_SEPARATOR, Path, PathBuf},
    sync::{Arc, LazyLock},
};

use path_clean::PathClean;

static CWD: LazyLock<Arc<Path>> = LazyLock::new(create_cwd);
static EXE: LazyLock<Arc<Path>> = LazyLock::new(create_exe);

fn create_cwd() -> Arc<Path> {
    let mut cwd = current_dir()
        .expect("failed to find current working directory")
        .to_str()
        .expect("current working directory is not valid UTF-8")
        .to_string();
    if !cwd.ends_with(MAIN_SEPARATOR) {
        cwd.push(MAIN_SEPARATOR);
    }
    dunce::canonicalize(cwd)
        .expect("failed to canonicalize current working directory")
        .into()
}

fn create_exe() -> Arc<Path> {
    let exe = current_exe()
        .expect("failed to find current executable")
        .to_str()
        .expect("current executable path is not valid UTF-8")
        .to_string();
    dunce::canonicalize(exe)
        .expect("failed to canonicalize current executable path")
        .into()
}

#[must_use]
pub fn get_current_dir() -> Arc<Path> {
    Arc::clone(&CWD)
}

#[must_use]
pub fn get_current_exe() -> Arc<Path> {
    Arc::clone(&EXE)
}

#[must_use]
pub fn clean_path(path: impl AsRef<Path>) -> PathBuf {
    path.as_ref().clean()
}

#[must_use]
pub fn clean_path_and_make_absolute(path: impl AsRef<Path>) -> PathBuf {
    let path = path.as_ref();
    if path.is_relative() {
        CWD.join(path).clean()
    } else {
        path.clean()
    }
}

#[must_use]
pub fn append_extension(path: impl AsRef<Path>, ext: impl AsRef<OsStr>) -> PathBuf {
    let path = path.as_ref();
    match path.extension() {
        None => path.with_extension(ext),
        Some(curr_ext) => {
            let mut new_ext = curr_ext.to_os_string();
            new_ext.push(".");
            new_ext.push(ext);
            path.with_extension(new_ext)
        }
    }
}

#[must_use]
pub fn relative_path_normalize(path: impl AsRef<Path>) -> PathBuf {
    let path = clean_path(path);

    let mut it = path.components().peekable();
    if it.peek().is_none_or(|c| matches!(c, Component::Normal(..))) {
        std::iter::once(Component::CurDir).chain(it).collect()
    } else {
        path
    }
}

pub fn relative_path_parent(rel: &mut PathBuf) {
    if rel.as_os_str() == Component::CurDir.as_os_str() {
        *rel = PathBuf::from(Component::ParentDir.as_os_str());
    } else if rel.components().all(|c| c == Component::ParentDir) {
        rel.push(Component::ParentDir.as_os_str());
    } else {
        rel.pop();
    }
}
