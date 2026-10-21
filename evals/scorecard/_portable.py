"""Remove local path tokens without altering ordinary slash-separated text."""
import re


def scrub_paths(text):
    # Local roots anywhere (also after punctuation), home-relative and drive paths; ordinary text such as
    # /api/v1 or and/or stays readable.
    return re.sub(r"""(?<![\w.~])(?:/(?:Users|home|private|var|tmp|Volumes|opt|root|mnt|srv)/\S*|~/\S+|[A-Za-z]:[\\/]\S+)""",
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
