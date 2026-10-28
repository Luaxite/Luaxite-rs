

use std::{
    ffi::OsStr,
    fmt,
    path::{Path, PathBuf},
};

use mlua::prelude::*;

use super::constants::{FILE_EXTENSIONS, FILE_NAME_INIT};
use super::std::append_extension;


#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LuauFilePath {
    
    File(PathBuf),
    
    Directory(PathBuf),
}

impl LuauFilePath {
    fn resolve(module: impl AsRef<Path>) -> Result<Self, LuaNavigateError> {
        let module = module.as_ref();

        
        if module
            .file_name()
            .is_some_and(|n| n == OsStr::new(FILE_NAME_INIT))
        {
            return Err(LuaNavigateError::Ambiguous);
        }

        let mut found = None;

        
        for ext in FILE_EXTENSIONS {
            let candidate = append_extension(module, ext);
            if candidate.is_file() && found.replace(candidate).is_some() {
                return Err(LuaNavigateError::Ambiguous);
            }
        }

        
        if module.is_dir() {
            let init = Path::new(FILE_NAME_INIT);
            for ext in FILE_EXTENSIONS {
                let candidate = module.join(append_extension(init, ext));
                if candidate.is_file() && found.replace(candidate).is_some() {
                    return Err(LuaNavigateError::Ambiguous);
                }
            }

            
            
            if found.is_none() {
                return Ok(Self::Directory(module.to_path_buf()));
            }
        }

        
        
        found.map(Self::File).ok_or(LuaNavigateError::NotFound)
    }

    #[must_use]
    pub const fn is_file(&self) -> bool {
        matches!(self, Self::File(_))
    }

    #[must_use]
    pub const fn is_dir(&self) -> bool {
        matches!(self, Self::Directory(_))
    }

    #[must_use]
    pub fn as_file(&self) -> Option<&Path> {
        match self {
            Self::File(path) => Some(path),
            Self::Directory(_) => None,
        }
    }

    #[must_use]
    pub fn as_dir(&self) -> Option<&Path> {
        match self {
            Self::File(_) => None,
            Self::Directory(path) => Some(path),
        }
    }
}

impl AsRef<Path> for LuauFilePath {
    fn as_ref(&self) -> &Path {
        match self {
            Self::File(path) | Self::Directory(path) => path.as_ref(),
        }
    }
}

impl fmt::Display for LuauFilePath {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Directory(path) | Self::File(path) => path.display().fmt(f),
        }
    }
}


#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LuauModulePath {
    
    source: PathBuf,
    
    target: LuauFilePath,
}

impl LuauModulePath {
    
    #[must_use]
    pub fn strip(path: impl Into<PathBuf>) -> PathBuf {
        let mut path: PathBuf = path.into();

        if path
            .extension()
            .and_then(|e| e.to_str())
            .is_some_and(|e| FILE_EXTENSIONS.contains(&e))
        {
            path = path.with_extension("");
        }

        if path
            .file_name()
            .and_then(|e| e.to_str())
            .is_some_and(|f| f == FILE_NAME_INIT)
        {
            path.pop();
        }

        path
    }

    
    pub fn resolve(module: impl Into<PathBuf>) -> Result<Self, LuaNavigateError> {
        let source = module.into();
        let target = LuauFilePath::resolve(&source)?;
        Ok(Self { source, target })
    }

    
    #[must_use]
    pub fn source(&self) -> &Path {
        &self.source
    }

    
    #[must_use]
    pub fn target(&self) -> &LuauFilePath {
        &self.target
    }
}

impl fmt::Display for LuauModulePath {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.source().display().fmt(f)
    }
}
