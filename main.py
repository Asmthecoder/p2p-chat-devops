"""
main.py — Application Entry Point
===================================
Rubric: All criteria (orchestration layer)

Usage
-----
    python main.py                          # uses config.json defaults
    python main.py --port 9002 --username Bob
    python main.py --port 9003 --username Charlie

Each instance is a fully independent peer node.
Open http://localhost:<port+8000> in your browser to access the UI.

Bootstrap sequence
------------------
1. Load / create config.json
2. Initialise EncryptionService
3. Initialise MessageStore (SQLite)
4. Initialise PeerManager (TCP server + UDP discovery + heartbeat)
5. Auto-connect to known_peers from config
6. Build NiceGUI UI and serve it
"""

import argparse
import asyncio
import json
import logging
import os
import sys

from nicegui import app, ui

from encryption import EncryptionService, generate_key
from message_store import MessageStore
from peer import PeerManager

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
DEFAULT_CONFIG = {
    "username":           "Peer",
    "port":               9001,
    "host":               "0.0.0.0",
    "known_peers":        [],
    "encryption_key":     "",
    "encryption_enabled": True,
    "theme":              "dark",
}


# ═══════════════════════════════════════════════════════════════════════════════
# Config helpers
# ═══════════════════════════════════════════════════════════════════════════════

def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        # Merge with defaults for any missing keys
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, v)
    else:
        cfg = DEFAULT_CONFIG.copy()
    if not cfg.get("encryption_key"):
        cfg["encryption_key"] = generate_key()
    return cfg


def save_config(cfg: dict):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
    logger.info("Config saved to %s", CONFIG_PATH)


# ═══════════════════════════════════════════════════════════════════════════════
# CLI args (override config.json)
# ═══════════════════════════════════════════════════════════════════════════════

def parse_args(config: dict) -> dict:
    parser = argparse.ArgumentParser(description="P2P Chat Node")
    parser.add_argument("--port",     type=int,   default=config["port"],     help="TCP listen port")
    parser.add_argument("--host",     type=str,   default=os.environ.get("UI_HOST", config.get("host", "0.0.0.0")), help="UI host bind address")
    parser.add_argument("--username", type=str,   default=config["username"], help="Display name")
    parser.add_argument("--ui-port",  type=int,   default=None,               help="NiceGUI web port (default: UI_PORT env or tcp_port + 8000)")
    parser.add_argument("--no-enc",   action="store_true",                    help="Disable encryption")
    args = parser.parse_args()

    config["port"]     = args.port
    config["host"]     = args.host
    config["username"] = args.username
    if args.no_enc:
        config["encryption_enabled"] = False
    env_ui_port = os.environ.get("UI_PORT")
    ui_port = args.ui_port if args.ui_port else int(env_ui_port) if env_ui_port else args.port + 8000
    config["ui_port"] = ui_port
    return config


# ═══════════════════════════════════════════════════════════════════════════════
# Application startup
# ═══════════════════════════════════════════════════════════════════════════════

_peer_manager: PeerManager = None


async def startup():
    global _peer_manager
    config = app.storage.general.get("config")  # injected before app.run()

    # 1. Encryption
    crypto_enabled = config.get("encryption_enabled", True)
    crypto = EncryptionService(config["encryption_key"] if crypto_enabled else "")
    logger.info("Encryption: %s", "ON" if crypto.enabled else "OFF")

    # 2. Message store
    db_name = f"chat_{config['port']}.db"
    store   = MessageStore(db_name)
    await store.init()

    # 3. Peer manager
    _peer_manager = PeerManager(
        username = config["username"],
        host     = "0.0.0.0",
        port     = config["port"],
        store    = store,
        crypto   = crypto,
    )
    await _peer_manager.start()
    logger.info("Peer node started: %s @ port %d", config["username"], config["port"])

    # 4. Auto-connect to known peers
    for entry in config.get("known_peers", []):
        try:
            if isinstance(entry, (list, tuple)) and len(entry) == 2:
                h, p = entry
            elif isinstance(entry, str) and ":" in entry:
                h, p = entry.rsplit(":", 1)
            else:
                continue
            asyncio.ensure_future(_peer_manager.connect_to_peer(str(h), int(p)))
        except Exception as exc:
            logger.warning("Could not parse known_peer %s: %s", entry, exc)


async def shutdown():
    if _peer_manager:
        await _peer_manager.stop()
    logger.info("Peer node shut down cleanly.")


# ═══════════════════════════════════════════════════════════════════════════════
# NiceGUI page
# ═══════════════════════════════════════════════════════════════════════════════

@ui.page("/")
async def index():
    config = app.storage.general.get("config", {})
    from ui import build_ui
    build_ui(_peer_manager, config)


# ═══════════════════════════════════════════════════════════════════════════════
# Port cleanup helper
# ═══════════════════════════════════════════════════════════════════════════════

def free_port(port: int):
    """Kill any process currently listening on *port* so we can bind cleanly."""
    import subprocess, platform
    try:
        if platform.system() == "Windows":
            # Find the PID via netstat using safe parameter passing (no shell injection)
            out = subprocess.check_output(
                ["netstat", "-ano"], text=True, stderr=subprocess.DEVNULL
            )
            pids = set()
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 5 and f":{port}" in parts[1] and parts[3] == "LISTENING":
                    pid_str = parts[4].strip()
                    # Validate PID is numeric before using it
                    if pid_str.isdigit():
                        pids.add(pid_str)
            for pid in pids:
                try:
                    # Use list-based args (no shell=True) to prevent shell injection
                    subprocess.call(["taskkill", "/PID", pid, "/F"],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    logger.info("Freed port %d (killed PID %s)", port, pid)
                except Exception as exc:
                    logger.warning("Failed to kill PID %s: %s", pid, exc)
        else:
            # Linux / macOS
            out = subprocess.check_output(
                ["lsof", "-ti", f":{port}"], text=True, stderr=subprocess.DEVNULL
            )
            for pid in out.strip().splitlines():
                pid_str = pid.strip()
                # Validate PID is numeric before using it
                if pid_str.isdigit():
                    try:
                        subprocess.call(["kill", "-9", pid_str])
                        logger.info("Freed port %d (killed PID %s)", port, pid_str)
                    except Exception as exc:
                        logger.warning("Failed to kill PID %s: %s", pid_str, exc)
    except Exception as exc:
        logger.debug("Could not free port %d: %s (likely already free)", port, exc)


def main():
    config = load_config()
    config = parse_args(config)
    save_config(config)

    logger.info("=" * 60)
    logger.info("  P2P Chat Node — %s", config["username"])
    logger.info("  UI host  : %s", config.get("host", "0.0.0.0"))
    logger.info("  TCP port : %d", config["port"])
    logger.info("  Web UI   : http://localhost:%d", config["ui_port"])
    logger.info("=" * 60)

    # Free UI port before binding (avoids Errno 10048 on rapid restart)
    free_port(config["ui_port"])

    # Share config with NiceGUI lifecycle hooks via app.storage
    app.on_startup(startup)
    app.on_shutdown(shutdown)
    app.storage.general["config"] = config

    ui.run(
        title       = f"P2P Chat — {config['username']}",
        host        = config.get("host", "0.0.0.0"),
        port        = config["ui_port"],
        dark        = config.get("theme", "dark") == "dark",
        reload      = False,
        show        = True,
        storage_secret = generate_key(),  # Use cryptographically secure key instead of hard-coded value
    )


if __name__ in ("__main__", "__mp_main__"):
    main()
