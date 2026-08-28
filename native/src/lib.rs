use std::net::Ipv6Addr;
use std::str::FromStr;

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyBytesMethods, PyDict};

fn error<T>(status: u16, detail: &'static str, version: Option<&str>) -> PyResult<T> {
    Err(PyValueError::new_err((
        status,
        detail,
        version.map(str::to_owned),
    )))
}

fn is_token_byte(byte: u8) -> bool {
    byte.is_ascii_alphanumeric() || b"!#$%&'*+-.^_`|~".contains(&byte)
}

fn is_unreserved(byte: u8) -> bool {
    byte.is_ascii_alphanumeric() || b"-._~".contains(&byte)
}

fn is_sub_delim(byte: u8) -> bool {
    b"!$&'()*+,;=".contains(&byte)
}

fn valid_reg_name(raw: &[u8]) -> bool {
    if raw.is_empty() {
        return false;
    }
    let mut index = 0;
    while index < raw.len() {
        let byte = raw[index];
        if is_unreserved(byte) || is_sub_delim(byte) {
            index += 1;
        } else if byte == b'%'
            && index + 2 < raw.len()
            && raw[index + 1].is_ascii_hexdigit()
            && raw[index + 2].is_ascii_hexdigit()
        {
            index += 3;
        } else {
            return false;
        }
    }
    true
}

fn valid_port(raw: &[u8]) -> bool {
    !raw.is_empty()
        && raw.len() <= 5
        && raw.iter().all(u8::is_ascii_digit)
        && std::str::from_utf8(raw)
            .ok()
            .and_then(|value| value.parse::<u32>().ok())
            .is_some_and(|value| value <= 65_535)
}

fn valid_ipv_future(raw: &[u8]) -> bool {
    if raw.len() < 4 || !matches!(raw[0], b'v' | b'V') {
        return false;
    }
    let Some(dot) = raw.iter().position(|byte| *byte == b'.') else {
        return false;
    };
    dot > 1
        && raw[1..dot].iter().all(u8::is_ascii_hexdigit)
        && dot + 1 < raw.len()
        && raw[dot + 1..]
            .iter()
            .all(|byte| is_unreserved(*byte) || is_sub_delim(*byte) || b":-".contains(byte))
}

fn validate_host(raw: &[u8]) -> bool {
    if raw.is_empty()
        || raw.contains(&b',')
        || raw.contains(&b'@')
        || raw.iter().any(|byte| !byte.is_ascii())
    {
        return false;
    }
    if raw[0] == b'[' {
        let Some(close) = raw.iter().position(|byte| *byte == b']') else {
            return false;
        };
        if close <= 1 {
            return false;
        }
        let literal = &raw[1..close];
        let suffix = &raw[close + 1..];
        if !suffix.is_empty() && (suffix[0] != b':' || !valid_port(&suffix[1..])) {
            return false;
        }
        return valid_ipv_future(literal)
            || std::str::from_utf8(literal)
                .ok()
                .is_some_and(|value| Ipv6Addr::from_str(value).is_ok());
    }
    if raw.iter().filter(|byte| **byte == b':').count() > 1 {
        return false;
    }
    if let Some(colon) = raw.iter().rposition(|byte| *byte == b':') {
        valid_reg_name(&raw[..colon]) && valid_port(&raw[colon + 1..])
    } else {
        valid_reg_name(raw)
    }
}

fn trim_ows(mut value: &[u8]) -> &[u8] {
    while value
        .first()
        .is_some_and(|byte| matches!(byte, b' ' | b'\t'))
    {
        value = &value[1..];
    }
    while value
        .last()
        .is_some_and(|byte| matches!(byte, b' ' | b'\t'))
    {
        value = &value[..value.len() - 1];
    }
    value
}

fn canonical_decimal(raw: &[u8]) -> Option<&[u8]> {
    if raw.is_empty() || !raw.iter().all(u8::is_ascii_digit) {
        return None;
    }
    let first_nonzero = raw.iter().position(|byte| *byte != b'0');
    Some(first_nonzero.map_or(&raw[raw.len() - 1..], |index| &raw[index..]))
}

fn decimal_exceeds(raw: &[u8], limit: usize) -> bool {
    let limit = limit.to_string();
    raw.len() > limit.len() || (raw.len() == limit.len() && raw > limit.as_bytes())
}

fn header_name_eq(name: &[u8], expected: &[u8]) -> bool {
    name.eq_ignore_ascii_case(expected)
}

fn latin1(raw: &[u8]) -> String {
    raw.iter().map(|byte| char::from(*byte)).collect()
}

fn has_connection_token(value: &[u8], expected: &[u8]) -> bool {
    value
        .split(|byte| *byte == b',')
        .map(trim_ows)
        .any(|token| token.eq_ignore_ascii_case(expected))
}

fn split_crlf(head: &[u8]) -> Vec<&[u8]> {
    let mut lines = Vec::new();
    let mut start = 0;
    while let Some(relative) = head[start..]
        .windows(2)
        .position(|window| window == b"\r\n")
    {
        let end = start + relative;
        lines.push(&head[start..end]);
        start = end + 2;
    }
    lines.push(&head[start..]);
    lines
}

type ParsedHeadResult = (String, Py<PyBytes>, String, Py<PyDict>, usize, bool);

#[pyfunction]
fn parse_head(
    py: Python<'_>,
    input: &Bound<'_, PyBytes>,
    request_line_limit: usize,
    header_bytes_limit: usize,
    header_count_limit: usize,
    body_limit: usize,
) -> PyResult<ParsedHeadResult> {
    let data = input.as_bytes();
    if data.len() > header_bytes_limit {
        return error(431, "request headers too large", None);
    }
    let all_lines = split_crlf(data);
    let mut lines = all_lines.into_iter();
    let Some(request_line) = lines.next() else {
        return error(400, "malformed request line", None);
    };
    if request_line.len() > request_line_limit {
        return error(414, "request target too long", None);
    }
    let parts: Vec<&[u8]> = request_line.split(|byte| *byte == b' ').collect();
    if parts.len() != 3 || parts.iter().any(|part| part.is_empty()) {
        return error(400, "malformed request line", None);
    }
    let version = match parts[2] {
        b"HTTP/1.0" => "HTTP/1.0",
        b"HTTP/1.1" => "HTTP/1.1",
        _ => return error(505, "HTTP version not supported", None),
    };
    if !parts[0].iter().all(|byte| is_token_byte(*byte)) {
        return error(400, "invalid method", Some(version));
    }
    let target = parts[1];
    if !target.starts_with(b"/") {
        return error(400, "invalid request target", Some(version));
    }

    let header_lines: Vec<&[u8]> = lines.collect();
    if header_lines.len() > header_count_limit {
        return error(431, "too many headers", Some(version));
    }
    let mut host_seen = false;
    let mut content_lengths: Vec<&[u8]> = Vec::new();
    let mut headers: Vec<(String, String)> = Vec::with_capacity(header_lines.len());
    let mut transfer_encoding = false;
    let mut connection_close = false;
    let mut connection_keep_alive = false;

    for line in header_lines {
        if line.is_empty() || matches!(line.first(), Some(b' ' | b'\t')) {
            return error(400, "malformed header", Some(version));
        }
        let Some(colon) = line.iter().position(|byte| *byte == b':') else {
            return error(400, "malformed header", Some(version));
        };
        let name = &line[..colon];
        let value = trim_ows(&line[colon + 1..]);
        if name.is_empty() || !name.iter().all(|byte| is_token_byte(*byte)) {
            return error(400, "malformed header name", Some(version));
        }
        if value
            .iter()
            .any(|byte| (*byte < 0x20 && *byte != b'\t') || *byte == 0x7f)
        {
            return error(400, "malformed header value", Some(version));
        }
        let lowered_name = String::from_utf8_lossy(name).to_ascii_lowercase();
        let decoded_value = latin1(value);
        if header_name_eq(name, b"host") {
            if host_seen {
                return error(400, "multiple host headers", Some(version));
            }
            host_seen = true;
            if !validate_host(value) {
                return error(400, "invalid host header", Some(version));
            }
        } else if header_name_eq(name, b"content-length") {
            let Some(canonical) = canonical_decimal(value) else {
                return error(400, "invalid content-length", Some(version));
            };
            content_lengths.push(canonical);
        } else if header_name_eq(name, b"transfer-encoding") {
            transfer_encoding = true;
        } else if header_name_eq(name, b"connection") {
            connection_close |= has_connection_token(value, b"close");
            connection_keep_alive |= has_connection_token(value, b"keep-alive");
        }
        if let Some((_, existing)) = headers
            .iter_mut()
            .find(|(existing_name, _)| *existing_name == lowered_name)
        {
            if lowered_name == "cookie" {
                existing.push_str("; ");
                existing.push_str(&decoded_value);
            } else if lowered_name != "content-length" {
                existing.push_str(", ");
                existing.push_str(&decoded_value);
            } else {
                *existing = decoded_value;
            }
        } else {
            headers.push((lowered_name, decoded_value));
        }
    }
    if transfer_encoding {
        return error(400, "transfer-encoding is not supported", Some(version));
    }
    if content_lengths
        .iter()
        .skip(1)
        .any(|length| *length != content_lengths[0])
    {
        return error(400, "conflicting content-length headers", Some(version));
    }
    let content_length = if let Some(raw) = content_lengths.first() {
        if decimal_exceeds(raw, body_limit) {
            return error(413, "request body too large", Some(version));
        }
        std::str::from_utf8(raw)
            .ok()
            .and_then(|value| value.parse::<usize>().ok())
            .unwrap_or(0)
    } else {
        0
    };
    if version == "HTTP/1.1" && !host_seen {
        return error(400, "missing host header", Some(version));
    }
    let keep_alive = !connection_close && (version == "HTTP/1.1" || connection_keep_alive);
    let headers_dict = PyDict::new(py);
    for (name, value) in headers {
        headers_dict.set_item(name, value)?;
    }
    Ok((
        String::from_utf8_lossy(parts[0]).into_owned(),
        PyBytes::new(py, target).unbind(),
        version.to_owned(),
        headers_dict.unbind(),
        content_length,
        keep_alive,
    ))
}

#[pymodule(gil_used = false)]
mod _parser {
    #[pymodule_export]
    use super::parse_head;
}
