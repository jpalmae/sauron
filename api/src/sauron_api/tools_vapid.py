#!/usr/bin/env python3
"""Generate a VAPID keypair for Web Push. Put the values in .env:

    SAURON_VAPID_PRIVATE_KEY=...
    SAURON_VAPID_PUBLIC_KEY=...
"""

from __future__ import annotations

from pywebpush import Vapid


def main() -> None:
    from cryptography.hazmat.primitives import serialization

    vapid = Vapid()
    vapid.generate_keys()
    print("SAURON_VAPID_PRIVATE_KEY=" + vapid.private_pem().decode().replace("\n", "\\n"))
    pub = vapid.public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    import base64

    print("SAURON_VAPID_PUBLIC_KEY=" + base64.urlsafe_b64encode(pub).decode().rstrip("="))


if __name__ == "__main__":
    main()
