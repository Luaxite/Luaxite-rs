
#[derive(Debug, Clone, Copy)]
pub struct ValueFormatConfig {
    pub(super) max_depth: usize,
    pub(super) colors_enabled: bool,
}

impl ValueFormatConfig {
    
    #[must_use]
    pub const fn new() -> Self {
        Self {
            max_depth: 3,
            colors_enabled: false,
        }
    }

    
    #[must_use]
    pub const fn with_max_depth(self, max_depth: usize) -> Self {
        Self { max_depth, ..self }
    }

    
    #[must_use]
    pub const fn with_colors_enabled(self, colors_enabled: bool) -> Self {
        Self {
            colors_enabled,
            ..self
        }
    }
}

impl Default for ValueFormatConfig {
    fn default() -> Self {
        Self::new()
    }
}
