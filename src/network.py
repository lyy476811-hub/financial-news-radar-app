import os
from contextlib import contextmanager


@contextmanager
def bypass_environment_proxies():
    """Temporarily ignore system/VPN proxy variables for direct domestic access."""
    proxy_keys = (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    )
    previous = {key: os.environ.get(key) for key in proxy_keys}
    for key in proxy_keys:
        os.environ.pop(key, None)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is not None:
                os.environ[key] = value
