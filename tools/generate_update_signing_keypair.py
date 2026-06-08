from __future__ import annotations

import argparse
import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text.rstrip() + "\n")


def _parse_args():
    parser = argparse.ArgumentParser(description="Generate a local Ed25519 update-signing keypair")
    parser.add_argument("--out-dir", default="local_keys", help="Directory for the generated keypair")
    parser.add_argument(
        "--repo-public-key",
        default="update_public_key.pem",
        help="Optional public key copy used by local release packaging",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing key files")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    out_dir = os.path.abspath(str(args.out_dir or "local_keys"))
    private_key_path = os.path.join(out_dir, "update_signing_private_key.pem")
    public_key_path = os.path.join(out_dir, "update_signing_public_key.pem")
    repo_public_key_path = os.path.abspath(str(args.repo_public_key or "").strip()) if args.repo_public_key else ""

    existing = [p for p in (private_key_path, public_key_path, repo_public_key_path) if p and os.path.exists(p)]
    if existing and not args.force:
        joined = "\n".join(existing)
        raise SystemExit(f"Refusing to overwrite existing key files without --force:\n{joined}")

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    _write_text(private_key_path, private_pem)
    _write_text(public_key_path, public_pem)
    if repo_public_key_path:
        _write_text(repo_public_key_path, public_pem)

    print("Generated update signing keypair:")
    print(f"- private: {private_key_path}")
    print(f"- public:  {public_key_path}")
    if repo_public_key_path:
        print(f"- repo public copy: {repo_public_key_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
