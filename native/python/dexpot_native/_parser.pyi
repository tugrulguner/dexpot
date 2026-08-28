def parse_head(
    head: bytes,
    request_line_limit: int,
    header_bytes_limit: int,
    header_count_limit: int,
    body_limit: int,
) -> tuple[str, bytes, str, dict[str, str], int, bool]: ...
