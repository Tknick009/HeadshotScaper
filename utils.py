import logging
import re
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

def setup_logging(debug: bool):
    """Configure logging with appropriate level and format."""
    level = logging.DEBUG if debug else logging.INFO
    format_str = '%(asctime)s - %(levelname)s - %(message)s'
    logging.basicConfig(level=level, format=format_str)

def clean_filename(name: str) -> str:
    """Convert athlete name to a safe filename."""
    # Remove invalid filename characters
    cleaned = re.sub(r'[<>:"/\\|?*]', '', name)
    # Replace spaces with underscores
    cleaned = cleaned.replace(' ', '_')
    # Remove any other problematic characters
    cleaned = re.sub(r'[^\w\-_.]', '', cleaned)
    # Keep original capitalization for proper names
    return cleaned

def remove_resize_params(url: str) -> str:
    """Remove image resizing parameters from URL."""
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)

    # Remove common resize parameters
    resize_params = ['width', 'height', 'w', 'h', 'size', 'resize']
    for param in resize_params:
        query_params.pop(param, None)

    # Remove quality parameters
    quality_params = ['quality', 'q']
    for param in quality_params:
        query_params.pop(param, None)

    # Rebuild URL without resize parameters
    clean_query = urlencode(query_params, doseq=True)
    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        clean_query,
        parsed.fragment
    ))