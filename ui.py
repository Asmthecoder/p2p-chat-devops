"""
ui.py — Professional Academic Node Interface (NiceGUI)
======================================================
Features: Slack/Discord style flat layouts, technical header, robust flexbox rows,
          emoji picker, typing indicators, peer status, and no mock UI components.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from nicegui import ui

if TYPE_CHECKING:
    from peer import PeerManager

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# State
# ═══════════════════════════════════════════════════════════════════════════════

class ChatState:
    def __init__(self):
        self.selected_peer_id: str        = "broadcast"
        self.dark_mode: bool              = True
        self.peers: dict                  = {}   # peer_id → {username, online, unread, typing_until}
        self.peer_manager: "PeerManager"  = None
        self.my_username: str             = "Me"
        self.my_port: int                 = 9001

_state = ChatState()


def _fmt_time(iso_str: str) -> str:
    try:
        return datetime.fromisoformat(iso_str).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _esc_js(s: str) -> str:
    return (str(s).replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
                  .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t"))


def _get_display_name(peer_id: str) -> str:
    if peer_id in _state.peers:
        return _state.peers[peer_id].get("username", peer_id)
    return peer_id


def _get_color_for_name(name: str) -> str:
    colors = ["#4f46e5", "#e11d48", "#ea580c", "#16a34a", "#9333ea", "#0284c7", "#ca8a04", "#0f766e"]
    idx = sum(ord(c) for c in name) % len(colors)
    return colors[idx]


# ═══════════════════════════════════════════════════════════════════════════════
# SVG Icons
# ═══════════════════════════════════════════════════════════════════════════════

_SVG_SUN    = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>'
_SVG_MOON   = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>'
_SVG_GEAR   = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1Z"/></svg>'
_SVG_SEND   = '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21 23 12 2.01 3 2 10l15 2-15 2z"/></svg>'
_SVG_EMOJI  = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/></svg>'
_SVG_HASH   = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="4" y1="9" x2="20" y2="9"/><line x1="4" y1="15" x2="20" y2="15"/><line x1="10" y1="3" x2="8" y2="21"/><line x1="16" y1="3" x2="14" y2="21"/></svg>'
_SVG_PLUS   = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>'
_SVG_SRCH   = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>'
_SVG_NODE   = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242M12 12v9"/><path d="m8 17 4 4 4-4"/></svg>'

QUICK_EMOJIS = ["😀","😂","❤️","👍","👋","🔥","✅","😎","🤔","😢","🎉","🚀", "👀", "💯", "✨"]


# ═══════════════════════════════════════════════════════════════════════════════
# Global CSS (Professional / Discord / Slack Style)
# ═══════════════════════════════════════════════════════════════════════════════

CSS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {
        --bg-app:         #0d1117;
        --bg-sidebar:     rgba(13, 17, 23, 0.86);
        --bg-sidebar-hov: rgba(255, 255, 255, 0.07);
        --bg-sidebar-act: rgba(193, 157, 77, 0.2);
        --bg-chat:        rgba(10, 14, 20, 0.82);
        --bg-topbar:      #111720;
        --bg-input:       rgba(18, 24, 34, 0.95);
        --bg-header:      rgba(7, 10, 15, 0.9);
        --border:         rgba(255, 255, 255, 0.12);
        --border-sb:      rgba(255, 255, 255, 0.1);
        --text-primary:   #e9eef8;
        --text-secondary: #a8b2c4;
        --text-dim:       #7f8aa0;
        --accent:         #c19d4d;
        --accent-hover:   #e2bf6e;
        --accent-soft:    rgba(193, 157, 77, 0.18);
        --divider:        rgba(255,255,255,0.1);
        --msg-hover:      rgba(193, 157, 77, 0.08);
        --code-bg:        #0b1018;
        --sidebar-w:      300px;
  }
  body.light-mode {
        --bg-app:         #ece7de;
        --bg-sidebar:     rgba(255, 255, 255, 0.82);
        --bg-sidebar-hov: rgba(36, 41, 47, 0.07);
        --bg-sidebar-act: rgba(193, 157, 77, 0.2);
        --bg-chat:        rgba(255, 255, 255, 0.76);
        --bg-topbar:      #ffffff;
        --bg-input:       rgba(247, 243, 235, 0.95);
        --bg-header:      rgba(255, 255, 255, 0.92);
        --border:         rgba(36, 41, 47, 0.14);
        --border-sb:      rgba(36, 41, 47, 0.1);
        --text-primary:   #18202c;
        --text-secondary: #546072;
        --text-dim:       #707d91;
        --accent:         #9f7834;
        --accent-hover:   #7f5e27;
        --accent-soft:    rgba(159, 120, 52, 0.14);
        --divider:        rgba(0,0,0,0.08);
        --msg-hover:      rgba(159, 120, 52, 0.07);
        --code-bg:        #f6f8fb;
  }

    body {
        font-family: 'Plus Jakarta Sans', sans-serif!important;
        margin:0;
        padding:0;
        background: var(--bg-app);
        color:var(--text-primary);
    }
  * { box-sizing:border-box; }
  .q-page-container, .q-page { padding:0!important; min-height:100vh!important; display:flex; flex-direction:column; }

  /* ── Layout ── */
  #main-grid {
        display:flex; width:100vw; height:100vh; overflow:hidden;
        backdrop-filter: blur(8px);
        animation: ui-fade-in .45s ease-out;
  }
    @keyframes ui-fade-in {
        from { opacity:0; transform: translateY(8px); }
        to { opacity:1; transform: translateY(0); }
    }
  
  /* ── Sidebar ── */
  #sidebar {
    width:var(--sidebar-w); background:var(--bg-sidebar); border-right:1px solid var(--border-sb);
        display:flex; flex-direction:column; flex-shrink:0; z-index:10;
        box-shadow: inset -1px 0 0 rgba(255,255,255,0.04);
        backdrop-filter: blur(10px);
  }
  
  /* Dashboard Header */
  #dash-header {
    height:64px; padding:0 16px; display:flex; align-items:center; justify-content:space-between;
        border-bottom:1px solid var(--border-sb); background:var(--bg-header); box-shadow:0 8px 20px rgba(0,0,0,0.16);
  }
  .dash-info { display:flex; align-items:center; gap:10px; min-width:0; }
  .dash-col { display:flex; flex-direction:column; }
    .dash-name {
        font-family:'Space Grotesk', sans-serif;
        letter-spacing:0.01em;
        font-weight:700;
        font-size:1rem;
        color:var(--text-primary);
        overflow:hidden;
        text-overflow:ellipsis;
        white-space:nowrap;
    }
    .dash-sub { font-size:0.7rem; color:var(--accent); font-weight:600; font-family:'JetBrains Mono', monospace; }
    .btn-icon {
        color:var(--text-secondary);
        cursor:pointer;
        padding:6px;
        border-radius:10px;
        border:1px solid transparent;
        display:inline-flex;
        transition:0.2s;
    }
    .btn-icon:hover {
        color:var(--text-primary);
        background:var(--bg-sidebar-hov);
        border-color:var(--accent-soft);
        transform:translateY(-1px);
    }

  /* Peers section */
  .section-title {
    font-size:0.75rem; font-weight:700; text-transform:uppercase; color:var(--text-secondary);
        padding:16px 16px 8px 16px; display:flex; justify-content:space-between; align-items:center;
        letter-spacing:0.08em;
  }
  #peer-scroll { flex:1; overflow-y:auto; padding:0 8px; }
  #peer-scroll::-webkit-scrollbar { width:6px; }
  #peer-scroll::-webkit-scrollbar-thumb { background:rgba(0,0,0,0.15); border-radius:3px; }

  /* List Items */
  .chan-item {
    display:flex; align-items:center; gap:10px; padding:6px 8px; margin:2px 0; border-radius:6px;
        cursor:pointer; color:var(--text-secondary); font-size:0.95rem; font-weight:500; transition:0.16s;
  }
    .chan-item:hover { background:var(--bg-sidebar-hov); color:var(--text-primary); transform:translateX(2px); }
    .chan-item.active {
        background:
            linear-gradient(110deg, var(--bg-sidebar-act), rgba(255,255,255,0.02));
        color:var(--text-primary);
        box-shadow:0 4px 10px rgba(0,0,0,0.14);
    }
  
  .chan-icon { color:var(--text-dim); display:flex; align-items:center; }
  .chan-item:hover .chan-icon, .chan-item.active .chan-icon { color:var(--text-secondary); }
  
  /* Peer item avatars */
  .peer-avatar {
    width:28px; height:28px; border-radius:50%; display:flex; align-items:center; justify-content:center;
        color:#fff; font-size:0.8rem; font-weight:700; flex-shrink:0; position:relative;
        box-shadow:0 4px 14px rgba(0,0,0,0.25);
  }
  .status-indicator {
    width:10px; height:10px; border-radius:50%; position:absolute; bottom:-2px; right:-2px;
    border:2px solid var(--bg-sidebar); background:#23a559;
  }
  .status-indicator.offline { background:#80848e; }
  .chan-item:hover .status-indicator { border-color:var(--bg-sidebar-hov); }
  .chan-item.active .status-indicator { border-color:var(--bg-sidebar-act); }
  
  .chan-name { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; flex:1; }
  .unread-pill {
    background:#da373c; color:#fff; font-size:0.7rem; font-weight:700; height:16px; min-width:16px;
        border-radius:8px; display:flex; align-items:center; justify-content:center; padding:0 4px;
        box-shadow:0 4px 10px rgba(218,55,60,0.35);
  }

  /* ── Chat Window ── */
  #main-chat {
        flex:1; display:flex; flex-direction:column; background:var(--bg-chat); min-width:0;
        backdrop-filter: blur(10px);
  }

  /* Chat Topbar */
  #chat-header {
    height:64px; border-bottom:1px solid var(--border); padding:0 16px; display:flex; align-items:center; gap:12px;
        box-shadow:0 8px 20px rgba(0,0,0,0.12); z-index:5;
  }
  .ch-icon { color:var(--text-dim); }
    .ch-name { font-family:'Space Grotesk', sans-serif; font-weight:700; font-size:1.14rem; color:var(--text-primary); }
  .ch-status { font-size:0.85rem; color:var(--text-secondary); padding-left:10px; border-left:1px solid var(--divider); }
  
  /* Messages Box */
  #messages-area {
    flex:1; overflow-y:auto; padding:20px 0; display:flex; flex-direction:column; scroll-behavior:smooth;
  }
  #messages-area::-webkit-scrollbar { width:8px; }
  #messages-area::-webkit-scrollbar-thumb { background:rgba(0,0,0,0.2); border-radius:4px; }
  /* Width fix for flex wrappers */
  #messages-area > div { width:100%; display:block; }

  /* Message Rows (Slack/Discord Flat Style) */
    .msg-row {
        display:flex; gap:16px; padding:8px 20px; transition:background 0.1s;
        animation: msg-rise .22s ease-out;
        align-items:flex-start;
    }
    .msg-row-in { justify-content:flex-start; }
    .msg-row-out { justify-content:flex-end; }
    .msg-row-out .msg-avatar { order:2; }
    .msg-row-out .msg-content-wrapper { align-items:flex-end; }
    .msg-row-out .msg-meta { justify-content:flex-end; }
  .msg-row:hover { background:var(--msg-hover); }
    @keyframes msg-rise {
        from { opacity:0; transform:translateY(6px); }
        to { opacity:1; transform:translateY(0); }
    }
  
  .msg-avatar {
    width:40px; height:40px; border-radius:50%; flex-shrink:0; display:flex; align-items:center; justify-content:center;
        color:#fff; font-weight:700; font-size:1.1rem; user-select:none; cursor:default; margin-top:2px;
        box-shadow:0 8px 18px rgba(0,0,0,0.22);
  }
    .msg-content-wrapper { flex:0 1 min(78%, 760px); min-width:0; display:flex; flex-direction:column; }
  .msg-meta { display:flex; align-items:baseline; gap:8px; margin-bottom:4px; }
  .msg-author { font-weight:600; font-size:1rem; color:var(--text-primary); }
    .msg-time {
        font-size:0.72rem;
        color:var(--text-secondary);
        font-weight:600;
        letter-spacing:0.02em;
        padding:2px 8px;
        border-radius:999px;
        background:var(--accent-soft);
        border:1px solid var(--border);
    }

    .msg-body {
        padding:10px 12px;
        border-radius:14px;
        border:1px solid var(--border);
        background:linear-gradient(140deg, rgba(255,255,255,0.06), rgba(255,255,255,0.02));
        box-shadow:0 8px 20px rgba(0,0,0,0.16);
    }
    .msg-row-in .msg-body {
        border-top-left-radius:6px;
    }
    .msg-row-out .msg-body {
        border-top-right-radius:6px;
        background:linear-gradient(145deg, rgba(193,157,77,0.24), rgba(193,157,77,0.12));
        box-shadow:0 6px 14px rgba(0,0,0,0.12);
    }
  
  .msg-text {
    font-size:0.95rem; color:var(--text-primary); line-height:1.45; word-wrap:break-word;
    white-space:pre-wrap;
  }

  /* System/Server messages */
  .msg-sys {
    display:flex; justify-content:center; padding:10px 0; margin:10px 0; color:var(--text-secondary);
  }
  .msg-sys span {
        font-size:0.8rem; font-weight:600; background:var(--border); padding:4px 12px; border-radius:999px; font-family:'JetBrains Mono', monospace;
  }

  /* Chat Input */
  #input-container { padding:0 20px 24px 20px; }
  .input-box {
        background:var(--bg-input); border-radius:14px; display:flex; align-items:center; gap:12px; padding:8px 12px;
        border:1px solid var(--border);
        box-shadow:0 12px 30px rgba(0,0,0,0.2);
  }
  .input-field {
    flex:1; background:transparent; border:none; outline:none; color:var(--text-primary); font-size:0.95rem;
    font-family:inherit; min-height:36px;
  }
  .emoji-btn { color:var(--text-secondary); cursor:pointer; transition:0.2s; display:flex; }
  .emoji-btn:hover { color:var(--text-primary); }
  
  /* Button for emojis inside popup */
  #emoji-popup {
    position:absolute; bottom:80px; right:30px; background:var(--bg-input); border-radius:8px; padding:12px;
    display:none; flex-wrap:wrap; gap:8px; width:260px; z-index:100; box-shadow:0 8px 24px rgba(0,0,0,0.25);
    border:1px solid var(--border);
        backdrop-filter: blur(10px);
  }
  #emoji-popup.open { display:flex; }
  .emo-itm { cursor:pointer; font-size:1.4rem; padding:4px; border-radius:4px; background:none; border:none; transition:0.1s; }
  .emo-itm:hover { background:var(--bg-sidebar-act); }

  /* Typing Indicator */
  .typing-ind {
    font-size:0.8rem; font-weight:600; color:var(--text-primary); height:24px; padding:0 20px;
    display:flex; align-items:center; gap:6px; opacity:0; transition:opacity 0.2s; pointer-events:none;
  }
  .typing-ind.active { opacity:1; }
  .dot { width:4px; height:4px; background:var(--text-primary); border-radius:50%; animation:tp 1.4s infinite ease-in-out; }
  .dot:nth-child(2) { animation-delay:0.2s; }
  .dot:nth-child(3) { animation-delay:0.4s; }
  @keyframes tp { 0%,80%,100%{transform:scale(0); opacity:0;} 40%{transform:scale(1); opacity:1;} }
  
  /* Common UI Elements */
  input, textarea { font-family:inherit; }

    @media (max-width: 980px) {
        :root { --sidebar-w: 88px; }
        .dash-col, .section-title span, .chan-name, .ch-status { display:none; }
        .section-title { justify-content:center; padding:14px 4px 8px; }
        .chan-item { justify-content:center; padding:8px 6px; }
        #chat-header { padding:0 12px; }
        .msg-row { padding:8px 12px; gap:10px; }
        .msg-content-wrapper { flex-basis:min(86%, 760px); }
        #input-container { padding:0 12px 16px; }
        #emoji-popup { right:12px; bottom:68px; width:220px; }
    }

    @media (max-width: 640px) {
        #main-grid { position:relative; }
        #sidebar {
            position:absolute;
            left:0;
            top:0;
            bottom:0;
            width:76px;
            z-index:20;
        }
        #main-chat { margin-left:76px; }
        .msg-avatar { width:34px; height:34px; font-size:0.95rem; }
        .msg-content-wrapper { flex-basis:min(92%, 760px); }
        .msg-author { font-size:0.92rem; }
        .msg-text { font-size:0.9rem; }
    }
</style>
"""


# ═══════════════════════════════════════════════════════════════════════════════
# Build UI
# ═══════════════════════════════════════════════════════════════════════════════

def build_ui(peer_manager, config: dict):
    _state.peer_manager = peer_manager
    _state.my_username  = config.get("username", "Me")
    _state.my_port      = config.get("port", 9001)
    _state.dark_mode    = config.get("theme", "dark") == "dark"

    ui.add_head_html(CSS)
    if not _state.dark_mode:
        ui.run_javascript("document.body.classList.add('light-mode')")

    add_dialog = _build_add_peer_dialog()
    settings_dialog = _build_settings_dialog(config)

    with ui.element("div").props('id="main-grid"'):
        
        # ── SIDEBAR ──
        with ui.element("div").props('id="sidebar"'):
            
            # Application / Node Header
            with ui.element("div").props('id="dash-header"'):
                with ui.element("div").classes("dash-info"):
                    ui.html(f'<span style="color:var(--accent); display:flex;">{_SVG_NODE}</span>')
                    with ui.element("div").classes("dash-col"):
                        ui.html(f'<div class="dash-name">Node: {_esc(_state.my_username)}</div>')
                        ui.html(f'<div class="dash-sub">TCP: {_state.my_port}</div>')
                with ui.element("div").classes("dash-actions"):
                    ui.html(f'<div class="btn-icon" title="Toggle Theme" id="thm-btn">{_SVG_SUN if _state.dark_mode else _SVG_MOON}</div>').on("click", _toggle_theme)
                    ui.html(f'<div class="btn-icon" title="Settings">{_SVG_GEAR}</div>').on("click", settings_dialog.open)
            
            # Channels / Broadcast
            ui.html('<div class="section-title"><span>Channels</span></div>')
            bc_row = ui.html(
                f'<div class="chan-item active" id="ch-broadcast" onclick="p2pSelect(\'broadcast\')">'
                f'<div class="chan-icon">{_SVG_HASH}</div><div class="chan-name">global-broadcast</div>'
                f'</div>'
            )
            
            # Direct Connections
            ui.html(f'<div class="section-title"><span>Direct Peers</span><div class="btn-icon" onclick="document.getElementById(\'hid-add\').click()" title="Add Peer" style="padding:2px;">{_SVG_PLUS}</div></div>')
            
            peer_list = ui.element("div").props('id="peer-scroll"')

            # Hidden mechanics
            ui.button(on_click=add_dialog.open).style("display:none;").props('id="hid-add"')

        # ── MAIN CHAT VIEW ──
        with ui.element("div").props('id="main-chat"'):
            
            # Header
            with ui.element("div").props('id="chat-header"'):
                ui.html(f'<div class="ch-icon" id="ch-head-icon">{_SVG_HASH}</div>')
                ui.html('<div class="ch-name" id="ch-head-name">global-broadcast</div>')
                ui.html('<div class="ch-status" id="ch-head-status">Public P2P Lounge</div>')

            # Chat History Map
            messages_area = ui.element("div").props('id="messages-area"')

            # Typing indicator (above input)
            ui.html(
                '<div class="typing-ind" id="typ-box">'
                '<div class="dot"></div><div class="dot"></div><div class="dot"></div>'
                '<span id="typ-name" style="margin-left:6px;">Several people are typing...</span>'
                '</div>'
            )

            # Input area
            with ui.element("div").props('id="input-container" style="position:relative;"'):
                # Emoji picker
                emo_html = "".join(f'<button class="emo-itm" onclick="document.getElementById(\'msg-input\').value += \'{e}\'; document.getElementById(\'msg-input\').focus();">{e}</button>' for e in QUICK_EMOJIS)
                ui.html(f'<div id="emoji-popup">{emo_html}</div>')

                with ui.element("div").classes("input-box"):
                    # Using raw input for clean key capture without WebSocket round-trips for every stroke
                    ui.html('<input type="text" id="msg-input" class="input-field" placeholder="Write to #global-broadcast" autocomplete="off" onkeydown="p2pKey(event)">')
                    ui.html(f'<div class="emoji-btn" onclick="document.getElementById(\'emoji-popup\').classList.toggle(\'open\')">{_SVG_EMOJI}</div>')
            
            # Backend action bridges
            ui.button(on_click=lambda: _on_send(messages_area)).style("display:none;").props('id="hid-send"')
            ui.button(on_click=lambda: _on_typing()).style("display:none;").props('id="hid-typ"')
            ui.button(on_click=lambda e: _handle_selection(e.sender.text)).style("display:none;").props('id="hid-sel"')

    # Injecting Javascript for Client Side UX
    ui.run_javascript("""
        window.p2pKey = function(e) {
            if (e.key === 'Enter') {
                document.getElementById('hid-send').click();
            } else {
                if(!window.typTmr) {
                    document.getElementById('hid-typ').click();
                    window.typTmr = setTimeout(() => { window.typTmr = null; }, 2000);
                }
            }
        };
        window.p2pSelect = function(pid) {
            document.querySelectorAll('.chan-item').forEach(e => e.classList.remove('active'));
            var target = document.querySelector(`.chan-item[data-pid="${pid}"]`);
            if(target) target.classList.add('active');
            else if(pid==='broadcast') document.getElementById('ch-broadcast').classList.add('active');
            
            // Bridge parameter hack into NiceGUI button text property to send data
            var b = document.getElementById('hid-sel');
            b.innerText = pid;
            b.click();
        };
        document.addEventListener('click', function(e) {
            var ep = document.getElementById('emoji-popup');
            if(ep && !e.target.closest('#emoji-popup') && !e.target.closest('.emoji-btn')) {
                ep.classList.remove('open');
            }
        });
    """)

    # ── Logic Bridges ──
    async def _on_send(container):
        val = await ui.run_javascript('var i=document.getElementById("msg-input"); var v=i.value; i.value=""; v;')
        if not val or not val.strip(): return
        text = val.strip()
        
        target = None if _state.selected_peer_id == "broadcast" else _state.selected_peer_id
        await _state.peer_manager.send_message(text, target)
        
        _append_message(container, "out", _state.my_username, text, datetime.now(timezone.utc).isoformat())
        _scroll_bottom()

    def _on_typing():
        if _state.selected_peer_id != "broadcast":
            asyncio.ensure_future(_state.peer_manager.send_typing(_state.selected_peer_id))

    def _handle_selection(pid: str):
        _state.selected_peer_id = pid
        if pid in _state.peers: _state.peers[pid]["unread"] = 0
        
        # Update styling
        is_bc = pid == "broadcast"
        name = "global-broadcast" if is_bc else _get_display_name(pid)
        status = "Public P2P Lounge" if is_bc else ("Online Node" if _state.peers.get(pid,{}).get("online") else "Offline Node")
        icon = _SVG_HASH if is_bc else _SVG_NODE
        placeholder = f"Write to #{name}" if is_bc else f"Write to @{name}"
        
        ui.run_javascript(f"""
            document.getElementById('ch-head-name').innerText = '{_esc_js(name)}';
            document.getElementById('ch-head-status').innerText = '{_esc_js(status)}';
            document.getElementById('ch-head-icon').innerHTML = `{icon}`;
            document.getElementById('msg-input').placeholder = '{_esc_js(placeholder)}';
            document.getElementById('msg-input').focus();
        """)
        asyncio.ensure_future(_load_history(force=True))
        _rebuild_peers(peer_list) # Update unread badges visually


    _view_state = {"peer_id": None}
    async def _load_history(force=False):
        if not force and _view_state["peer_id"] == _state.selected_peer_id: return
        _view_state["peer_id"] = _state.selected_peer_id
        
        if _state.selected_peer_id == "broadcast":
            msgs = await _state.peer_manager.store.get_all_messages(150)
        else:
            msgs = await _state.peer_manager.store.get_history(_state.selected_peer_id, 150)
        
        messages_area.clear()
        with messages_area:
            ui.html('<div class="msg-sys"><span>// Message History Start</span></div>')
            for m in msgs:
                d = m.get("direction", "in")
                s = _state.my_username if d == "out" else _get_display_name(m.get("peer_id", ""))
                if m.get("type") == "SYSTEM":
                    text = _esc(m.get("content", ""))
                    ui.html(f'<div class="msg-sys"><span>{text}</span></div>')
                else:
                    _append_message(messages_area, d, s, m.get("content", ""), m.get("timestamp", ""))
        _scroll_bottom()

    ui.timer(0.4, _load_history)

    async def _poll_inbound():
        try:
            while True:
                msg = _state.peer_manager.inbound_queue.get_nowait()
                _process_inbound(msg, messages_area)
        except asyncio.QueueEmpty:
            pass

    ui.timer(0.2, _poll_inbound)

    async def _refresh_state():
        peers = await _state.peer_manager.store.get_all_peers()
        for p in peers:
            pid = p["id"]
            if pid not in _state.peers:
                _state.peers[pid] = {**p, "unread": 0, "typing_until": 0}
            else:
                _state.peers[pid].update({k: v for k, v in p.items() if k not in ["unread", "typing_until"]})
        
        async with _state.peer_manager._lock:
            for pid, info in _state.peer_manager._peers.items():
                if pid in _state.peers:
                    _state.peers[pid]["online"] = info.get("online", 0)
                else:
                    _state.peers[pid] = {"id":pid, "username":info.get("username", pid), "online":info.get("online",0), "unread":0,"typing_until":0}
        
        _update_typing_ui()
        _rebuild_peers(peer_list)

    ui.timer(2.0, _refresh_state)


def _append_message(container, direction: str, sender: str, text: str, ts_iso: str):
    ts = _fmt_time(ts_iso)
    color = _get_color_for_name(sender)
    ini = sender[:1].upper() if sender else "?"
    content = _esc(text)
    safe_name = _esc(sender)
    row_class = "msg-row msg-row-out" if direction == "out" else "msg-row msg-row-in"
    
    with container:
        ui.html(
            f'<div class="{row_class}">'
            f'<div class="msg-avatar" style="background:{color}">{ini}</div>'
            f'<div class="msg-content-wrapper">'
            f'<div class="msg-meta"><span class="msg-author">{safe_name}</span><span class="msg-time">{ts}</span></div>'
            f'<div class="msg-body"><div class="msg-text">{content}</div></div>'
            f'</div></div>'
        )

def _process_inbound(msg: dict, area):
    mtype  = msg.get("type", "MESSAGE")
    pid    = msg.get("peer_id", "")
    sender = msg.get("sender", "Unknown")

    if pid not in _state.peers and pid != "broadcast":
        _state.peers[pid] = {"id":pid, "username":sender, "online":1, "unread":0, "typing_until":0}

    if mtype == "TYPING":
        _state.peers[pid]["typing_until"] = time.time() + 3.0
        _update_typing_ui()
        return

    if mtype == "SYSTEM":
        evt = msg.get("event", "joined")
        _state.peers[pid]["online"] = 1 if evt == "joined" else 0
        _state.peers[pid]["username"] = sender
        if _state.selected_peer_id == "broadcast":
            with area: ui.html(f'<div class="msg-sys"><span>{_esc(msg.get("content",""))}</span></div>')
            _scroll_bottom()
        return

    if mtype == "MESSAGE":
        _state.peers[pid]["typing_until"] = 0
        if _state.selected_peer_id != pid and not msg.get("is_broadcast"):
            _state.peers[pid]["unread"] = _state.peers[pid].get("unread", 0) + 1
        
        is_bc = bool(msg.get("is_broadcast", False))
        if (_state.selected_peer_id == "broadcast" and is_bc) or (_state.selected_peer_id == pid and not is_bc):
            _append_message(area, "in", _get_display_name(pid), msg.get("content", ""), msg.get("timestamp", ""))
            _scroll_bottom()

def _update_typing_ui():
    now = time.time()
    active_typers = [p["username"] for p in _state.peers.values() if p.get("typing_until", 0) > now]
    txt = ""
    is_active = False
    if active_typers:
        is_active = True
        if len(active_typers) == 1: txt = f"{active_typers[0]} is typing..."
        else: txt = "Several people are typing..."
    
    ui.run_javascript(f"""
        var ind = document.getElementById('typ-box');
        if(ind) {{
            if({'true' if is_active else 'false'}) ind.classList.add('active');
            else ind.classList.remove('active');
            document.getElementById('typ-name').innerText = '{_esc_js(txt)}';
        }}
    """)

def _rebuild_peers(container):
    container.clear()
    with container:
        sorted_peers = sorted(_state.peers.items(), key=lambda x: (not x[1].get("online",0), x[1].get("username","").lower()))
        for pid, info in sorted_peers:
            uname = info.get("username", pid)
            online = int(info.get("online", 0))
            unread = int(info.get("unread", 0))
            
            is_active = _state.selected_peer_id == pid
            row_cls = "chan-item active" if is_active else "chan-item"
            badge = f'<div class="unread-pill">{unread}</div>' if unread > 0 else ''
            
            ini = uname[:1].upper()
            col = _get_color_for_name(uname)
            st_cls = "status-indicator" if online else "status-indicator offline"
            
            ui.html(
                f'<div class="{row_cls}" data-pid="{_esc(pid)}" onclick="p2pSelect(\'{_esc_js(pid)}\')">'
                f'<div class="peer-avatar" style="background:{col}">{ini}<div class="{st_cls}"></div></div>'
                f'<div class="chan-name">{_esc(uname)}</div>{badge}'
                f'</div>'
            )

def _scroll_bottom():
    ui.run_javascript("var e=document.getElementById('messages-area'); if(e) e.scrollTop=e.scrollHeight;")

def _toggle_theme():
    _state.dark_mode = not _state.dark_mode
    body_cls = "" if _state.dark_mode else "light-mode"
    icon = _SVG_SUN if _state.dark_mode else _SVG_MOON
    ui.run_javascript(f"""
        if('{body_cls}'==='') document.body.classList.remove('light-mode');
        else document.body.classList.add('light-mode');
        var btn = document.getElementById('thm-btn');
        if(btn) btn.innerHTML = '{icon}';
    """)

# ═══════════════════════════════════════════════════════════════════════════════
# Dialog Settings
# ═══════════════════════════════════════════════════════════════════════════════
def _build_add_peer_dialog():
    with ui.dialog() as dialog, ui.card().style("min-width:350px; background:var(--bg-topbar); color:var(--text-primary); border:1px solid var(--border);"):
        ui.label("Add Direct Peer Node").style("font-size:1.1rem; font-weight:700; margin-bottom:10px;")
        ip = ui.input("IP Address", value="127.0.0.1").props("outlined dense").style("width:100%; margin-bottom:10px;")
        pt = ui.input("TCP Port", value="9002").props("outlined dense").style("width:100%; margin-bottom:20px;")
        ui.label("Connect directly to another node's IP and networking port to bypass UDP LAN discovery.").style("font-size:0.8rem; color:var(--text-secondary); margin-bottom:15px;")
        async def do_add():
            try:
                await _state.peer_manager.connect_to_peer(ip.value.strip(), int(pt.value.strip()))
                ui.notify(f"Dispatched connection to {ip.value}:{pt.value}", type="positive")
                dialog.close()
            except Exception as e: ui.notify(str(e), type="negative")
        with ui.row().style("width:100%; justify-content:flex-end; gap:8px;"):
            ui.button("Cancel", on_click=dialog.close).props('flat text-color="grey-5"')
            ui.button("Establish Link", on_click=do_add).props('color="amber-8"')
    return dialog

def _build_settings_dialog(config):
    with ui.dialog() as dialog, ui.card().style("min-width:350px; background:var(--bg-topbar); color:var(--text-primary); border:1px solid var(--border);"):
        ui.label("Node Configuration").style("font-size:1.1rem; font-weight:700; margin-bottom:10px;")
        uname = ui.input("Node Display Name", value=config.get("username")).props("outlined dense").style("width:100%; margin-bottom:10px;")
        pt = ui.input("TCP Networking Listen Port", value=str(config.get("port"))).props("outlined dense").style("width:100%; margin-bottom:6px;")
        enc = ui.switch("Enable Encryption", value=bool(config.get("encryption_enabled", True))).style("margin-bottom:10px;")
        ui.label("Note: Port changes require an application restart.").style("font-size:0.8rem; color:var(--text-secondary); margin-bottom:20px;")
        
        def save():
            import json, os
            config["username"] = uname.value.strip()
            config["port"] = int(pt.value.strip())
            config["encryption_enabled"] = bool(enc.value)
            with open(os.path.join(os.path.dirname(__file__), "config.json"), "w") as f:
                json.dump(config, f, indent=2)
            ui.notify("Configuration saved locally. Restart node script to bind.", type="positive")
            dialog.close()
        with ui.row().style("width:100%; justify-content:flex-end; gap:8px;"):
            ui.button("Close", on_click=dialog.close).props('flat text-color="grey-5"')
            ui.button("Commit Save", on_click=save).props('color="amber-8"')
    return dialog
