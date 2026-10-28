use std::{
    fmt,
    str::FromStr,
    sync::{Arc, LazyLock},
};

use console::style;
use mlua::prelude::*;

use super::StackTrace;

static STYLED_STACK_BEGIN: LazyLock<String> = LazyLock::new(|| {
    format!(
        "{}{}{}",
        style("[").dim(),
        style("Stack Begin").blue(),
        style("]").dim()
    )
});

static STYLED_STACK_END: LazyLock<String> = LazyLock::new(|| {
    format!(
        "{}{}{}",
        style("[").dim(),
        style("Stack End").blue(),
        style("]").dim()
    )
});

const STACK_TRACE_INDENT: &str = "    ";

#[derive(Debug, Default, Clone)]
pub struct ErrorComponents {
    messages: Vec<String>,
    trace: Option<StackTrace>,
}

impl ErrorComponents {
    #[must_use]
    pub fn messages(&self) -> &[String] {
        &self.messages
    }

    #[must_use]
    pub fn trace(&self) -> Option<&StackTrace> {
        self.trace.as_ref()
    }

    #[must_use]
    pub fn has_trace(&self) -> bool {
        self.trace
            .as_ref()
            .is_some_and(|trace| !trace.lines().is_empty())
    }
}

impl fmt::Display for ErrorComponents {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        for message in self.messages() {
            writeln!(f, "{message}")?;
        }
        if self.has_trace() {
            let trace = self.trace.as_ref().expect("trace exists and is non-empty");
            writeln!(f, "{}", *STYLED_STACK_BEGIN)?;
            for line in trace.lines() {
                writeln!(f, "{STACK_TRACE_INDENT}{line}")?;
            }
            writeln!(f, "{}", *STYLED_STACK_END)?;
        }
        Ok(())
    }
}

impl From<LuaError> for ErrorComponents {
    fn from(error: LuaError) -> Self {
        fn lua_error_message(e: &LuaError) -> String {
            if let LuaError::RuntimeError(s) = e {
                s.clone()
            } else {
                e.to_string()
            }
        }

        fn lua_stack_trace(source: &str) -> Option<StackTrace> {
            StackTrace::from_str(source).ok()
        }

        #[allow(clippy::arc_with_non_send_sync)]
        let mut error = Arc::new(error);
        let mut messages = Vec::new();
        while let LuaError::WithContext {
            ref context,
            ref cause,
        } = *error
        {
            messages.push(context.clone());
            error = cause.clone();
        }

        let mut trace = if let LuaError::CallbackError {
            ref traceback,
            ref cause,
        } = *error
        {
            messages.push(lua_error_message(cause));
            lua_stack_trace(traceback)
        } else if let LuaError::RuntimeError(ref s) = *error {
            if let Some(pos) = s.find("stack traceback:") {
                let (message, traceback) = s.split_at(pos);
                messages.push(message.trim().to_string());
                lua_stack_trace(traceback)
            } else {
                messages.push(s.clone());
                None
            }
        } else {
            messages.push(lua_error_message(&error));
            None
        };

        if let Some(trace) = &mut trace {
            let lines = trace.lines_mut();
            loop {
                let first_is_c_and_empty = lines
                    .first()
                    .is_some_and(|line| line.source().is_c() && line.is_empty());
                let second_is_c_and_nonempty = lines
                    .get(1)
                    .is_some_and(|line| line.source().is_c() && !line.is_empty());
                if first_is_c_and_empty && second_is_c_and_nonempty {
                    lines.remove(0);
                } else {
                    break;
                }
            }
        }

        if let Some(message) = messages.last_mut()
            && let Some(line) = trace
                .iter()
                .flat_map(StackTrace::lines)
                .find(|line| line.source().is_lua())
        {
            if let Some(path) = line.path() {
                let prefix = format!("[string \"{path}\"]:");
                if message.starts_with(&prefix) {
                    *message = message[prefix.len()..].trim().to_string();
                }
            }
            if let Some(line) = line.line_number() {
                let prefix = format!("{line}:");
                if message.starts_with(&prefix) {
                    *message = message[prefix.len()..].trim().to_string();
                }
            }
        }

        ErrorComponents { messages, trace }
    }
}

impl From<Box<LuaError>> for ErrorComponents {
    fn from(value: Box<LuaError>) -> Self {
        Self::from(*value)
    }
}
