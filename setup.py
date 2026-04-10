"""
setup.py — One-command project setup
=====================================
Run: python setup.py
Installs all dependencies, generates config.json if missing,
and prints a quick-start guide.
"""

import subprocess
import sys
import json
import os

from pathlib import Path

ROOT = Path(__file__).parent


def pip_install():
    print("[*] Installing dependencies...")
    req = ROOT / "requirements.txt"
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(req)],
        capture_output=False,
    )
    if result.returncode != 0:
        print("[FAIL] pip install failed. Please run manually:")
        print(f"   pip install -r {req}")
        sys.exit(1)
    print("[OK] Dependencies installed.\n")


def generate_config():
    cfg_path = ROOT / "config.json"
    if cfg_path.exists():
        print(f"[INFO] config.json already exists at {cfg_path}\n")
        return

    try:
        from cryptography.fernet import Fernet
        key = Fernet.generate_key().decode()
    except ImportError:
        key = ""

    config = {
        "username":           "Peer1",
        "port":               9001,
        "known_peers":        [],
        "encryption_key":     key,
        "encryption_enabled": True,
        "theme":              "dark",
    }
    with open(cfg_path, "w") as f:
        json.dump(config, f, indent=2)
    print(f"[OK] config.json generated at {cfg_path}\n")


def print_guide():
    print("=" * 60)
    print("  P2P Chat -- Quick Start Guide")
    print("=" * 60)
    print()
    print("Run Peer 1 (terminal 1):")
    print("  python main.py --port 9001 --username Alice")
    print("  → Open: http://localhost:17001")
    print()
    print("Run Peer 2 (terminal 2):")
    print("  python main.py --port 9002 --username Bob")
    print("  → Open: http://localhost:17002")
    print()
    print("Run Peer 3 (terminal 3):")
    print("  python main.py --port 9003 --username Charlie")
    print("  → Open: http://localhost:17003")
    print()
    print("Peers on the same LAN auto-discover via UDP broadcast.")
    print("To connect manually: click '+ Add Peer' in the sidebar.")
    print()
    print("Run latency benchmark:")
    print("  python eval/latency_test.py")
    print("=" * 60)


if __name__ == "__main__":
    pip_install()
    generate_config()
    print_guide()
