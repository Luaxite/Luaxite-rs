use std::fmt;

use console::{Color, style};


#[derive(Debug, Clone, Copy)]
pub enum Label {
    Info,
    Warn,
    Error,
}

impl Label {
    
    #[must_use]
    pub fn name(&self) -> &str {
        match self {
            Self::Info => "INFO",
            Self::Warn => "WARN",
            Self::Error => "ERROR",
        }
    }

    
    #[must_use]
    pub fn color(&self) -> Color {
        match self {
            Self::Info => Color::Blue,
            Self::Warn => Color::Yellow,
            Self::Error => Color::Red,
        }
    }
}

impl fmt::Display for Label {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "{}{}{}",
            style("[").dim(),
            style(self.name()).fg(self.color()),
            style("]").dim()
        )
    }
}
