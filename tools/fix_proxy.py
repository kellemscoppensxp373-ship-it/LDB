#!/usr/bin/env python3
"""Emit ``set "VAR=..."`` lines that make old pip work behind the Windows proxy.

pip < 22 crashes with ``ValueError: check_hostname requires server_hostname``
whenever the *proxy URL* carries an ``https://`` scheme.  On Windows the proxy
very often comes **not** from environment variables but from the registry
(Internet Options): CPython's ``urllib.request.getproxies_registry`` maps a
plain ``host:port`` entry to ``https://host:port`` for HTTPS traffic, which is
exactly what old vendored urllib3 cannot do.

Running this with the interpreter that pip will use and ``call``-ing the
printed lines overrides the registry value with a plain ``http://`` scheme.
The CONNECT tunnel is unchanged and TLS to PyPI stays end-to-end.

Only ``set`` commands are written to stdout so the batch script can redirect
the output to a temp ``.cmd`` and execute it.
"""

from __future__ import annotations

import sys
import urllib.request


def main() -> int:
    try:
        proxies = urllib.request.getproxies()
    except Exception:
        return 0
    for key, var in (("http", "HTTP_PROXY"), ("https", "HTTPS_PROXY")):
        value = (proxies.get(key) or "").strip()
        if value.lower().startswith("https://"):
            print(f'set "{var}=http://{value[8:]}"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
