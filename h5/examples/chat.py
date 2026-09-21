#!/usr/bin/env python3
"""Server-side example. Set PLATFORM_BASE_URL, PLATFORM_API_KEY and PLATFORM_MODEL."""
import os
import sys
from urllib.parse import urlsplit

from openai import APIConnectionError, APIStatusError, DefaultHttpxClient, OpenAI

base = os.environ["PLATFORM_BASE_URL"].rstrip("/")
key = os.environ["PLATFORM_API_KEY"]
model = os.environ["PLATFORM_MODEL"]
url = urlsplit(base)
local_http = url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1")
if (not key or not model or not url.hostname or url.username is not None or
        url.password is not None or url.query or url.fragment or url.path != "/v1" or
        (url.scheme != "https" and not local_http)):
    raise ValueError("Use a trusted HTTPS base ending in /v1; HTTP is allowed only for loopback development.")

# No default provider URL and no automatic replay of a billable request.
with OpenAI(api_key=key, base_url=base, max_retries=0, timeout=60.0,
            http_client=DefaultHttpxClient(follow_redirects=False)) as client:
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=128,
        )
    except APIStatusError as error:
        print(f"HTTP {error.status_code}: check permissions, limits and usage before retrying.", file=sys.stderr)
        sys.exit(1)
    except APIConnectionError:
        print("Connection failed or timed out; outcome is unknown. Check usage before retrying.", file=sys.stderr)
        sys.exit(1)

if not response.choices or not isinstance(response.choices[0].message.content, str):
    raise RuntimeError("No text completion returned; inspect the model protocol and usage record.")
print(response.choices[0].message.content)
