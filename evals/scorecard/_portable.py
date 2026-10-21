"""Remove local path tokens without altering ordinary slash-separated text."""
import re


def scrub_paths(text):
    return re.sub(r"""(?<![^\s(\["'=:])(?:~/\S+|/[^/\s]+/\S+|[A-Za-z]:[\\/]\S+)""",
                  "[path omitted]", text)


def portable(value):
    """Keep local paths out of JSON string values as well as Markdown."""
    if isinstance(value, str):
        return scrub_paths(value)
    if isinstance(value, list):
        return [portable(item) for item in value]
    if isinstance(value, dict):
        return {key: portable(item) for key, item in value.items()}
    return value
