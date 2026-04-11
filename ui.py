"""
ui.py — Premium P2P Chat Interface (NiceGUI)
==============================================
Design: Discord × Instagram — dark glassmorphism, blurple accents,
        smooth micro-animations, clean typography.

Bug fixes in this version
--------------------------
1. Module-level singleton fixed: ChatState is instantiated inside build_ui()
   so each browser tab/client gets its own isolated state.
2. innerText message mangling fixed: send now uses
   `await ui.run_javascript("return ...")` to read the textarea value
   directly without the collapsing whitespace that innerText causes.
3. Delivery ACK indicator: outgoing messages show ✓ (sent) and flip to
   ✓✓ (delivered) when an ACK comes back from the recipient.
4. Visual decrypt-fail indicator: bubbles containing a decryption error
   string get a red border + lock emoji prefix.
5. USERNAME_UPDATE messages handled in process_inbound.
6. Typing indicator polls peer_manager.typing_peers dict directly
   (TYPING events no longer go through the inbound queue).
7. Message search bar added to topbar.
8. Username change in Settings now calls peer_manager.broadcast_username_update.
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
# State (instantiated per build_ui call — NOT module-level singleton)
# ═══════════════════════════════════════════════════════════════════════════════

class ChatState:
    def __init__(self):
        self.selected_peer_id: str       = "broadcast"
        self.dark_mode: bool             = True
        self.peers: dict                 = {}   # peer_id → {username, online, unread}
        self.peer_manager: "PeerManager" = None
        self.my_username: str            = "Me"
        self.my_port: int                = 9001
        self.is_searching: bool          = False


# ═══════════════════════════════════════════════════════════════════════════════
# Pure utility functions (no state — safe as module-level)
# ═══════════════════════════════════════════════════════════════════════════════

def _fmt_time(iso_str: str) -> str:
    try:
        return datetime.fromisoformat(iso_str).astimezone().strftime("%H:%M")
    except Exception:
        return ""


def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _esc_js(s: str) -> str:
    return (
        str(s)
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def _get_color_for_name(name: str) -> str:
    colors = [
        "#5865F2",  # Discord blurple
        "#EB459E",  # Instagram pink
        "#57F287",  # green
        "#FEE75C",  # yellow
        "#ED4245",  # red
        "#9B59B6",  # purple
        "#E67E22",  # orange
        "#1ABC9C",  # teal
    ]
    idx = sum(ord(c) for c in name) % len(colors)
    return colors[idx]


def _is_decrypt_error(text: str) -> bool:
    return "[encrypted message" in text or "[Message decryption" in text


# ═══════════════════════════════════════════════════════════════════════════════
# SVG Icons
# ═══════════════════════════════════════════════════════════════════════════════

_SVG_SUN    = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>'
_SVG_MOON   = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>'
_SVG_GEAR   = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1Z"/></svg>'
_SVG_SEND   = '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21 23 12 2.01 3 2 10l15 2-15 2z"/></svg>'
_SVG_HASH   = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="4" y1="9" x2="20" y2="9"/><line x1="4" y1="15" x2="20" y2="15"/><line x1="10" y1="3" x2="8" y2="21"/><line x1="16" y1="3" x2="14" y2="21"/></svg>'
_SVG_PLUS   = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>'
_SVG_NODE   = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="5" r="3"/><circle cx="5" cy="19" r="3"/><circle cx="19" cy="19" r="3"/><line x1="12" y1="8" x2="5" y2="16"/><line x1="12" y1="8" x2="19" y2="16"/></svg>'
_SVG_SEARCH = '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>'
_SVG_CLOSE  = '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>'

QUICK_EMOJIS = ["😀","😂","❤️","👍","🔥","✅","😎","🤔","🎉","🚀","👀","💯","✨","😢","🤣","💀","😍","🥳","👋","🫡"]


# ═══════════════════════════════════════════════════════════════════════════════
# Design System CSS
# ═══════════════════════════════════════════════════════════════════════════════

CSS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
/* ── Tokens ─────────────────────────────────────────── */
:root {
  --app:         #0e1015;
  --sidebar:     #111318;
  --sidebar-hov: rgba(255,255,255,0.06);
  --sidebar-act: rgba(88,101,242,0.25);
  --chat-bg:     #16181e;
  --topbar:      #111318;
  --input-bg:    #1e2028;
  --border:      rgba(255,255,255,0.07);
  --border2:     rgba(255,255,255,0.12);
  --t1:          #e3e5ea;
  --t2:          #9da3b4;
  --t3:          #5c6273;
  --accent:      #5865F2;
  --accent-h:    #7289da;
  --accent-soft: rgba(88,101,242,0.18);
  --pink:        #EB459E;
  --green:       #23d160;
  --red:         #ed4245;
  --sidebar-w:   260px;
  --header-h:    56px;
  --radius:      12px;
  --radius-sm:   8px;
}

/* ── Reset + Base ────────────────────────────────────── */
*,*::before,*::after { box-sizing:border-box; margin:0; padding:0; }
html,body { height:100%; overflow:hidden; }
body {
  font-family:'Inter',system-ui,sans-serif;
  background:var(--app); color:var(--t1);
  font-size:15px; line-height:1.5;
}
.q-page-container,.q-page {
  padding:0!important; height:100vh!important; min-height:100vh!important;
  display:flex!important; flex-direction:column!important; overflow:hidden!important;
}

/* ── App Shell ───────────────────────────────────────── */
#app-shell {
  display:flex; width:100vw; height:100vh; overflow:hidden;
  animation: app-in 0.4s ease-out;
}
@keyframes app-in {
  from { opacity:0; transform:scale(0.98); }
  to   { opacity:1; transform:scale(1); }
}

/* ── Sidebar ─────────────────────────────────────────── */
#sidebar {
  width:var(--sidebar-w); min-width:var(--sidebar-w); max-width:var(--sidebar-w);
  background:var(--sidebar); border-right:1px solid var(--border);
  display:flex; flex-direction:column; overflow:hidden;
  flex-shrink:0; z-index:10;
}
#node-header {
  height:var(--header-h); padding:0 14px;
  display:flex; align-items:center; justify-content:space-between;
  border-bottom:1px solid var(--border); flex-shrink:0;
  background:linear-gradient(135deg,rgba(88,101,242,.12),rgba(235,69,158,.08));
}
.node-info { display:flex; align-items:center; gap:10px; min-width:0; }
.node-avatar {
  width:36px; height:36px; border-radius:50%;
  background:linear-gradient(135deg,var(--accent),var(--pink));
  display:flex; align-items:center; justify-content:center;
  font-size:.9rem; font-weight:800; color:#fff; flex-shrink:0;
  box-shadow:0 0 0 2px rgba(88,101,242,.4),0 4px 12px rgba(88,101,242,.25);
  position:relative;
}
.node-avatar::after {
  content:''; position:absolute; bottom:-1px; right:-1px;
  width:11px; height:11px; background:var(--green);
  border-radius:50%; border:2px solid var(--sidebar);
}
.node-name-col { min-width:0; }
.node-name {
  font-weight:700; font-size:.9rem; color:var(--t1);
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis; letter-spacing:-.01em;
}
.node-port {
  font-size:.7rem; color:var(--accent);
  font-family:'JetBrains Mono',monospace; font-weight:500; letter-spacing:.03em;
}
.hdr-actions { display:flex; gap:4px; }
.icon-btn {
  width:32px; height:32px; border-radius:var(--radius-sm);
  border:none; background:transparent; cursor:pointer;
  display:flex; align-items:center; justify-content:center;
  color:var(--t3); transition:all .15s;
}
.icon-btn:hover { background:var(--sidebar-hov); color:var(--t1); transform:scale(1.05); }
.sb-section {
  padding:14px 12px 6px 12px;
  font-size:.7rem; font-weight:700; text-transform:uppercase;
  letter-spacing:.1em; color:var(--t3);
  display:flex; align-items:center; justify-content:space-between; flex-shrink:0;
}
.sb-add-btn {
  width:20px; height:20px; border-radius:4px;
  background:transparent; border:none; cursor:pointer;
  display:flex; align-items:center; justify-content:center;
  color:var(--t3); transition:all .15s;
}
.sb-add-btn:hover { background:var(--sidebar-hov); color:var(--t1); }
#peer-list { flex:1; overflow-y:auto; padding:4px 8px 8px; }
#peer-list::-webkit-scrollbar { width:4px; }
#peer-list::-webkit-scrollbar-thumb { background:rgba(255,255,255,.08); border-radius:2px; }
.sb-item {
  display:flex; align-items:center; gap:10px;
  padding:7px 8px; border-radius:var(--radius-sm);
  cursor:pointer; transition:all .15s;
  color:var(--t2); font-size:.9rem; font-weight:500;
  margin-bottom:2px; position:relative;
}
.sb-item:hover { background:var(--sidebar-hov); color:var(--t1); }
.sb-item.active { background:var(--sidebar-act); color:var(--t1); font-weight:600; }
.sb-item.active::before {
  content:''; position:absolute; left:-8px; top:50%; transform:translateY(-50%);
  width:3px; height:60%; background:var(--accent); border-radius:0 3px 3px 0;
}
.sb-avatar {
  width:30px; height:30px; border-radius:50%;
  display:flex; align-items:center; justify-content:center;
  font-size:.78rem; font-weight:700; color:#fff; flex-shrink:0; position:relative;
}
.sb-status {
  width:9px; height:9px; border-radius:50%;
  position:absolute; bottom:-1px; right:-1px;
  border:2px solid var(--sidebar); background:var(--t3);
}
.sb-status.online  { background:var(--green); }
.sb-status.offline { background:var(--t3); }
.sb-label { flex:1; min-width:0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.unread-badge {
  background:var(--red); color:#fff;
  font-size:.68rem; font-weight:700;
  min-width:18px; height:18px; border-radius:9px; padding:0 5px;
  display:flex; align-items:center; justify-content:center; flex-shrink:0;
  box-shadow:0 2px 8px rgba(237,66,69,.4);
}
.sb-hash { color:var(--t3); display:flex; align-items:center; flex-shrink:0; }
.sb-item:hover .sb-hash, .sb-item.active .sb-hash { color:var(--accent); }

/* ── Main Chat Panel ─────────────────────────────────── */
#chat-panel {
  flex:1; display:flex; flex-direction:column;
  background:var(--chat-bg); overflow:hidden; min-width:0;
}
#chat-topbar {
  height:var(--header-h); border-bottom:1px solid var(--border);
  padding:0 16px; display:flex; align-items:center; gap:10px;
  flex-shrink:0; background:var(--topbar); backdrop-filter:blur(8px);
}
#ch-icon  { color:var(--t3); display:flex; align-items:center; }
#ch-name  { font-weight:700; font-size:1rem; color:var(--t1); letter-spacing:-.01em; flex:1; }
.ch-sep   { display:inline-block; width:1px; height:20px; background:var(--border2); margin:0 2px; }
#ch-sub   { font-size:.82rem; color:var(--t2); }

/* Search Bar */
#search-bar {
  display:none; padding:8px 16px; background:var(--input-bg);
  border-bottom:1px solid var(--border); align-items:center; gap:8px;
  flex-shrink:0;
}
#search-bar.open { display:flex; }
#search-input {
  flex:1; background:transparent; border:none; outline:none;
  color:var(--t1); font-family:'Inter',sans-serif; font-size:.9rem;
}
#search-input::placeholder { color:var(--t3); }
.search-count { font-size:.78rem; color:var(--t3); white-space:nowrap; }

/* Messages */
#msgs {
  flex:1; overflow-y:auto; overflow-x:hidden;
  padding:16px 0 8px; display:flex; flex-direction:column; min-height:0;
}
#msgs::-webkit-scrollbar { width:6px; }
#msgs::-webkit-scrollbar-thumb { background:rgba(255,255,255,.1); border-radius:3px; }
#msgs > * { width:100%; }

/* Message rows */
.msg-row {
  display:flex; gap:14px; padding:5px 20px;
  align-items:flex-start; transition:background .1s;
  animation:msg-in .2s ease-out;
}
.msg-row:hover { background:rgba(255,255,255,.02); }
@keyframes msg-in {
  from { opacity:0; transform:translateY(4px); }
  to   { opacity:1; transform:translateY(0); }
}
.msg-row-out { flex-direction:row-reverse; }
.msg-ava {
  width:38px; height:38px; border-radius:50%;
  display:flex; align-items:center; justify-content:center;
  font-size:1rem; font-weight:700; color:#fff; flex-shrink:0; margin-top:2px;
  box-shadow:0 4px 12px rgba(0,0,0,.3); transition:transform .15s;
}
.msg-row:hover .msg-ava { transform:scale(1.04); }
.msg-wrap { max-width:min(72%,700px); display:flex; flex-direction:column; }
.msg-row-out .msg-wrap { align-items:flex-end; }
.msg-meta { display:flex; align-items:baseline; gap:8px; margin-bottom:4px; }
.msg-row-out .msg-meta { flex-direction:row-reverse; }
.msg-author { font-weight:600; font-size:.88rem; }
.msg-time   { font-size:.7rem; color:var(--t3); font-family:'JetBrains Mono',monospace; }
.msg-ack    { font-size:.72rem; color:var(--t3); margin-left:4px; transition:color .3s; }
.msg-ack-done { color:var(--accent)!important; }

/* Bubbles */
.msg-bubble {
  padding:9px 14px; border-radius:16px;
  font-size:.91rem; line-height:1.5;
  word-break:break-word; white-space:pre-wrap; max-width:100%;
}
.msg-row-in .msg-bubble {
  background:#1e2028; border:1px solid rgba(255,255,255,.07);
  border-top-left-radius:4px; color:var(--t1);
  box-shadow:0 2px 8px rgba(0,0,0,.2);
}
.msg-row-out .msg-bubble {
  background:linear-gradient(135deg,#5865F2,#4752c4);
  border-top-right-radius:4px; color:#fff;
  box-shadow:0 4px 14px rgba(88,101,242,.35);
}
/* Decrypt-fail indicator */
.msg-bubble-error.msg-row-in .msg-bubble {
  border:1px solid rgba(237,66,69,.5)!important;
  background:rgba(237,66,69,.08)!important;
  color:#f87171!important;
}
.msg-bubble-error.msg-row-out .msg-bubble {
  background:rgba(237,66,69,.3)!important;
  box-shadow:0 4px 14px rgba(237,66,69,.25)!important;
}

/* System messages */
.msg-sys { display:flex; justify-content:center; padding:10px 20px; margin:6px 0; }
.msg-sys-pill {
  font-size:.75rem; font-weight:500; color:var(--t3);
  background:rgba(255,255,255,.04); border:1px solid var(--border);
  padding:3px 12px; border-radius:99px;
  font-family:'JetBrains Mono',monospace;
}

/* Typing indicator */
#typing-bar {
  height:24px; padding:0 20px;
  display:flex; align-items:center; gap:6px; flex-shrink:0;
  opacity:0; transition:opacity .2s; pointer-events:none;
}
#typing-bar.visible { opacity:1; }
.dot {
  width:5px; height:5px; border-radius:50%; background:var(--t2);
  animation:dotpulse 1.4s infinite ease-in-out;
}
.dot:nth-child(2) { animation-delay:.2s; }
.dot:nth-child(3) { animation-delay:.4s; }
@keyframes dotpulse {
  0%,80%,100% { transform:scale(.5); opacity:.4; }
  40%          { transform:scale(1);  opacity:1; }
}
#typing-label { font-size:.78rem; color:var(--t2); font-weight:500; font-style:italic; }

/* ── Input Area ──────────────────────────────────────── */
#input-area { padding:8px 16px 16px; flex-shrink:0; position:relative; }
#input-box {
  background:var(--input-bg); border:1px solid var(--border2);
  border-radius:14px; display:flex; align-items:flex-end; gap:8px; padding:8px 12px;
  transition:border-color .2s,box-shadow .2s;
}
#input-box:focus-within {
  border-color:rgba(88,101,242,.5);
  box-shadow:0 0 0 2px rgba(88,101,242,.12);
}
#chat-input {
  flex:1; background:transparent; border:none; outline:none;
  color:var(--t1); font-family:'Inter',sans-serif;
  font-size:.93rem; line-height:1.5; resize:none;
  min-height:22px; max-height:120px; overflow-y:auto; padding:2px 0;
}
#chat-input::placeholder { color:var(--t3); }
#chat-input::-webkit-scrollbar { width:3px; }
#chat-input::-webkit-scrollbar-thumb { background:rgba(255,255,255,.1); border-radius:2px; }
.inp-btn {
  width:32px; height:32px; border-radius:8px; border:none; cursor:pointer;
  display:flex; align-items:center; justify-content:center;
  color:var(--t2); background:transparent; transition:all .15s; flex-shrink:0;
}
.inp-btn:hover { color:var(--t1); background:rgba(255,255,255,.06); }
#send-btn {
  background:var(--accent); color:#fff; border-radius:10px;
}
#send-btn:hover {
  background:var(--accent-h); transform:scale(1.07);
  box-shadow:0 4px 12px rgba(88,101,242,.4);
}
#send-btn:active { transform:scale(.97); }

/* ── Emoji Picker ────────────────────────────────────── */
#emoji-picker {
  position:absolute; bottom:calc(100% + 6px); right:16px;
  background:#1e2028; border:1px solid var(--border2); border-radius:14px;
  padding:12px; display:none; flex-wrap:wrap; gap:4px;
  width:264px; z-index:999; box-shadow:0 12px 32px rgba(0,0,0,.4);
  animation:picker-in .15s ease-out;
}
#emoji-picker.open { display:flex; }
@keyframes picker-in {
  from { opacity:0; transform:translateY(8px) scale(.97); }
  to   { opacity:1; transform:translateY(0) scale(1); }
}
.emo {
  width:36px; height:36px; font-size:1.35rem;
  display:flex; align-items:center; justify-content:center;
  border-radius:8px; cursor:pointer; border:none; background:transparent;
  transition:background .12s,transform .12s;
}
.emo:hover { background:rgba(255,255,255,.1); transform:scale(1.18); }

/* ── Dialogs ─────────────────────────────────────────── */
.dlg-card {
  background:#1e2028!important; border:1px solid var(--border2)!important;
  border-radius:16px!important; min-width:360px!important;
  color:var(--t1)!important; padding:24px!important;
}
.dlg-title { font-size:1.05rem; font-weight:700; margin-bottom:16px; color:var(--t1); }
.dlg-card .q-field__control { background:#111318!important; border-radius:8px!important; }
.dlg-card .q-field__native,
.dlg-card .q-field__input { color:var(--t1)!important; }
.dlg-card .q-field__label { color:var(--t3)!important; }

/* ── Scrollbar global ────────────────────────────────── */
::-webkit-scrollbar { width:6px; height:6px; }
::-webkit-scrollbar-track { background:transparent; }
::-webkit-scrollbar-thumb { background:rgba(255,255,255,.1); border-radius:3px; }
::-webkit-scrollbar-thumb:hover { background:rgba(255,255,255,.2); }

/* ── Responsive ──────────────────────────────────────── */
@media (max-width:900px) {
  :root { --sidebar-w:72px; }
  .node-name-col,.sb-section span,.sb-label,#ch-sub,.ch-sep { display:none; }
  .sb-section { justify-content:center; }
  .sb-item { justify-content:center; padding:9px 6px; }
  .sb-item.active::before { display:none; }
  #input-area { padding:6px 10px 12px; }
  .msg-row { padding:5px 12px; gap:10px; }
}
</style>
"""


# ═══════════════════════════════════════════════════════════════════════════════
# Build UI  (per-client — creates its own ChatState)
# ═══════════════════════════════════════════════════════════════════════════════

def build_ui(peer_manager, config: dict):
    # ── Per-client state (FIX: no longer a module-level singleton) ──────────────
    state              = ChatState()
    state.peer_manager = peer_manager
    state.my_username  = config.get("username", "Me")
    state.my_port      = config.get("port", 9001)
    state.dark_mode    = config.get("theme", "dark") == "dark"

    ui.add_head_html(CSS)

    # ── JS bridge (injected before any HTML that calls it) ───────────────────────
    ui.add_head_html("""
    <script>
    /* Select a peer channel */
    function p2pSelect(pid) {
        document.querySelectorAll('.sb-item').forEach(el => el.classList.remove('active'));
        var t = document.querySelector('.sb-item[data-pid="'+pid+'"]');
        if (t) t.classList.add('active');
        var b = document.getElementById('_sel_bridge');
        if (b) { b.innerText = pid; b.click(); }
    }

    /* Send message — reads textarea value directly to avoid innerText mangling */
    function p2pSend() {
        var b = document.getElementById('_send_bridge');
        if (b) b.click();
    }

    /* Emoji picker toggle */
    function toggleEmoji() {
        var p = document.getElementById('emoji-picker');
        if (p) p.classList.toggle('open');
    }

    /* Insert emoji at cursor */
    function insertEmoji(e) {
        var ta = document.getElementById('chat-input');
        if (!ta) return;
        var s = ta.selectionStart, end = ta.selectionEnd;
        ta.value = ta.value.slice(0,s) + e + ta.value.slice(end);
        ta.selectionStart = ta.selectionEnd = s + e.length;
        ta.focus();
        document.getElementById('emoji-picker').classList.remove('open');
    }

    /* Auto-grow textarea */
    function autoGrow(el) {
        el.style.height = 'auto';
        el.style.height = Math.min(el.scrollHeight, 120) + 'px';
    }

    /* Search bar toggle */
    function p2pToggleSearch() {
        var bar = document.getElementById('search-bar');
        var inp = document.getElementById('search-input');
        if (!bar) return;
        var open = bar.classList.toggle('open');
        if (open) { inp.focus(); }
        else { inp.value = ''; document.getElementById('_srch_clear_bridge').click(); }
    }

    /* Dismiss emoji picker on outside click */
    document.addEventListener('click', function(e) {
        var picker = document.getElementById('emoji-picker');
        var btn    = document.getElementById('emoji-toggle-btn');
        if (picker && !picker.contains(e.target) && e.target !== btn)
            picker.classList.remove('open');
    });
    </script>
    """)

    # ── Dialogs ──────────────────────────────────────────────────────────────────
    add_dialog      = _build_add_peer_dialog(state)
    settings_dialog = _build_settings_dialog(state, config)

    # ── App Shell ────────────────────────────────────────────────────────────────
    with ui.element("div").props('id="app-shell"'):

        # ══════════ SIDEBAR ════════════════════════════════════════════════════
        with ui.element("div").props('id="sidebar"'):

            ini = (state.my_username[:1] or "?").upper()
            with ui.element("div").props('id="node-header"'):
                with ui.element("div").classes("node-info"):
                    ui.html(
                        f'<div class="node-avatar">{ini}</div>'
                        f'<div class="node-name-col">'
                        f'  <div class="node-name">{_esc(state.my_username)}</div>'
                        f'  <div class="node-port">:{state.my_port}</div>'
                        f'</div>'
                    )
                with ui.element("div").classes("hdr-actions"):
                    ui.html(
                        f'<button class="icon-btn" id="thm-btn" title="Toggle Theme"'
                        f' onclick="document.getElementById(\'_thm_bridge\').click()">'
                        f'{_SVG_SUN}</button>'
                    )
                    ui.html(
                        f'<button class="icon-btn" title="Settings"'
                        f' onclick="document.getElementById(\'_set_bridge\').click()">'
                        f'{_SVG_GEAR}</button>'
                    )

            ui.html('<div class="sb-section"><span>Channels</span></div>')
            ui.html(
                '<div class="sb-item active" data-pid="broadcast" onclick="p2pSelect(\'broadcast\')">'
                f'  <span class="sb-hash">{_SVG_HASH}</span>'
                '  <span class="sb-label">global-broadcast</span>'
                '</div>'
            )

            ui.html(
                '<div class="sb-section"><span>Direct Peers</span>'
                '<button class="sb-add-btn" onclick="document.getElementById(\'_add_bridge\').click()" title="Add peer">'
                f'{_SVG_PLUS}</button></div>'
            )
            peer_list = ui.element("div").props('id="peer-list"')

        # ══════════ CHAT PANEL ══════════════════════════════════════════════════
        with ui.element("div").props('id="chat-panel"'):

            # Topbar
            with ui.element("div").props('id="chat-topbar"'):
                ui.html(f'<div id="ch-icon" style="color:var(--t3);display:flex;">{_SVG_HASH}</div>')
                ui.html('<div id="ch-name" style="font-weight:700;font-size:1rem;flex:1;"># global-broadcast</div>')
                ui.html('<div class="ch-sep"></div>')
                ui.html('<div id="ch-sub" style="font-size:.82rem;color:var(--t2);">Public broadcast channel</div>')
                ui.html(
                    f'<button class="icon-btn" title="Search messages" onclick="p2pToggleSearch()">'
                    f'{_SVG_SEARCH}</button>'
                )

            # Search bar (collapsible)
            ui.html(
                '<div id="search-bar">'
                f'  <span style="color:var(--t3);display:flex;">{_SVG_SEARCH}</span>'
                '  <input id="search-input" type="text" placeholder="Search messages…"'
                '    onkeydown="if(event.key===\'Enter\'){document.getElementById(\'_srch_bridge\').click();}">'
                '  <span class="search-count" id="search-count"></span>'
                f'  <button class="icon-btn" onclick="p2pToggleSearch()" style="width:24px;height:24px;">{_SVG_CLOSE}</button>'
                '</div>'
            )

            # Messages
            messages_area = ui.element("div").props('id="msgs"')

            # Typing bar
            ui.html(
                '<div id="typing-bar">'
                '  <div class="dot"></div><div class="dot"></div><div class="dot"></div>'
                '  <span id="typing-label">Someone is typing…</span>'
                '</div>'
            )

            # Input area
            with ui.element("div").props('id="input-area"'):
                emoji_html = "".join(
                    f'<button class="emo" onclick="insertEmoji(\'{e}\')">{e}</button>'
                    for e in QUICK_EMOJIS
                )
                ui.html(f'<div id="emoji-picker">{emoji_html}</div>')
                ui.html(
                    '<div id="input-box">'
                    '  <textarea id="chat-input" rows="1"'
                    '    placeholder="Message #global-broadcast"'
                    '    oninput="autoGrow(this)"'
                    '    onkeydown="if(event.key===\'Enter\'&&!event.shiftKey){event.preventDefault();p2pSend();}">'
                    '  </textarea>'
                    f'  <button class="inp-btn" id="emoji-toggle-btn" title="Emoji" onclick="toggleEmoji()">'
                    '    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
                    '      <circle cx="12" cy="12" r="10"/>'
                    '      <path d="M8 14s1.5 2 4 2 4-2 4-2"/>'
                    '      <line x1="9" y1="9" x2="9.01" y2="9"/>'
                    '      <line x1="15" y1="9" x2="15.01" y2="9"/>'
                    '    </svg>'
                    '  </button>'
                    f'  <button class="inp-btn" id="send-btn" title="Send (Enter)" onclick="p2pSend()">'
                    f'    {_SVG_SEND}'
                    '  </button>'
                    '</div>'
                )

    # ── Hidden Python bridge buttons ─────────────────────────────────────────────
    # Placed outside the visual layout to not disturb flexbox.

    # Selection bridge
    ui.button("", on_click=lambda e: _handle_selection(e.sender.text)) \
      .props('id="_sel_bridge"').style("display:none;position:fixed;")

    # Send bridge — reads textarea via run_javascript (FIX: avoids innerText mangling)
    async def _trigger_send():
        text = await ui.run_javascript(
            "var ta=document.getElementById('chat-input');"
            "var v=ta?ta.value:'';"
            "if(ta){ta.value='';ta.style.height='auto';}"
            "return v;"
        )
        if text and text.strip():
            await _on_send(text, messages_area)

    ui.button("", on_click=_trigger_send) \
      .props('id="_send_bridge"').style("display:none;position:fixed;")

    # Search bridge
    async def _trigger_search():
        query = await ui.run_javascript(
            "return document.getElementById('search-input').value||'';"
        )
        await _do_search((query or "").strip())

    async def _trigger_search_clear():
        if not state.is_searching:
            return
        state.is_searching = False
        await _load_history(force=True)
        ui.run_javascript("document.getElementById('search-count').textContent='';")

    ui.button("", on_click=_trigger_search) \
      .props('id="_srch_bridge"').style("display:none;position:fixed;")
    ui.button("", on_click=_trigger_search_clear) \
      .props('id="_srch_clear_bridge"').style("display:none;position:fixed;")

    # Theme + Settings + Add-peer bridges
    ui.button("", on_click=lambda: _toggle_theme()) \
      .props('id="_thm_bridge"').style("display:none;position:fixed;")
    ui.button("", on_click=lambda: settings_dialog.open()) \
      .props('id="_set_bridge"').style("display:none;position:fixed;")
    ui.button("", on_click=lambda: add_dialog.open()) \
      .props('id="_add_bridge"').style("display:none;position:fixed;")

    # ── Inner helpers (all close over `state`) ───────────────────────────────────

    def _get_display_name(peer_id: str) -> str:
        if peer_id in state.peers:
            return state.peers[peer_id].get("username", peer_id)
        return peer_id

    def _handle_selection(pid: str):
        if not pid:
            return
        state.selected_peer_id = pid
        if pid in state.peers:
            state.peers[pid]["unread"] = 0
        state.is_searching = False
        ui.run_javascript(
            "document.getElementById('search-bar').classList.remove('open');"
            "var si=document.getElementById('search-input'); if(si) si.value='';"
            "document.getElementById('search-count').textContent='';"
        )

        is_bc = pid == "broadcast"
        name  = "global-broadcast" if is_bc else _get_display_name(pid)
        disp  = f"# {name}" if is_bc else f"@ {name}"
        sub   = (
            "Public broadcast channel"
            if is_bc
            else ("Online" if state.peers.get(pid, {}).get("online") else "Offline")
        )
        icon  = _SVG_HASH if is_bc else _SVG_NODE
        ph    = f"Message #{name}" if is_bc else f"Message @{name}"

        ui.run_javascript(
            f"document.getElementById('ch-name').innerText='{_esc_js(disp)}';"
            f"document.getElementById('ch-sub').innerText='{_esc_js(sub)}';"
            f"document.getElementById('ch-icon').innerHTML=`{icon}`;"
            f"var ta=document.getElementById('chat-input');"
            f"if(ta) ta.placeholder='{_esc_js(ph)}';"
        )
        asyncio.ensure_future(_load_history(force=True))
        _rebuild_peers(peer_list)

    # ── History loading ──────────────────────────────────────────────────────────

    _view = {"peer_id": None}

    async def _load_history(force: bool = False):
        if state.is_searching:
            return
        if not force and _view["peer_id"] == state.selected_peer_id:
            return
        _view["peer_id"] = state.selected_peer_id

        try:
            if state.selected_peer_id == "broadcast":
                msgs = await state.peer_manager.store.get_all_messages(150)
            else:
                msgs = await state.peer_manager.store.get_history(
                    state.selected_peer_id, 150
                )
        except Exception:
            msgs = []

        messages_area.clear()
        with messages_area:
            ui.html('<div class="msg-sys"><span class="msg-sys-pill">── History Start ──</span></div>')
            for m in msgs:
                d = m.get("direction", "in")
                s = (
                    state.my_username if d == "out"
                    else _get_display_name(m.get("peer_id", ""))
                )
                if m.get("type") == "SYSTEM":
                    ui.html(
                        f'<div class="msg-sys"><span class="msg-sys-pill">'
                        f'{_esc(m.get("content",""))}</span></div>'
                    )
                else:
                    _append_message(messages_area, d, s,
                                    m.get("content", ""), m.get("timestamp", ""))
        _scroll_bottom()

    ui.timer(0.5, _load_history)

    # ── Search ───────────────────────────────────────────────────────────────────

    async def _do_search(query: str):
        if not query:
            return
        state.is_searching = True
        pid = (
            None if state.selected_peer_id == "broadcast"
            else state.selected_peer_id
        )
        try:
            results = await state.peer_manager.store.search_messages(query, peer_id=pid)
        except Exception:
            results = []

        messages_area.clear()
        with messages_area:
            ui.html(
                f'<div class="msg-sys"><span class="msg-sys-pill">'
                f'🔍 "{_esc(query)}" — {len(results)} result(s)'
                f'</span></div>'
            )
            if not results:
                ui.html(
                    '<div class="msg-sys"><span class="msg-sys-pill" style="color:var(--t3);">'
                    'No messages found</span></div>'
                )
            for m in results:
                d = m.get("direction", "in")
                s = (
                    state.my_username if d == "out"
                    else _get_display_name(m.get("peer_id", ""))
                )
                _append_message(messages_area, d, s,
                                m.get("content", ""), m.get("timestamp", ""))
        _scroll_bottom()
        ui.run_javascript(
            f"document.getElementById('search-count').textContent="
            f"'{len(results)} result(s)';"
        )

    # ── Send ─────────────────────────────────────────────────────────────────────

    async def _on_send(text: str, container):
        text = text.strip()
        if not text:
            return
        try:
            target = (
                None if state.selected_peer_id == "broadcast"
                else state.selected_peer_id
            )
            msg_id = await state.peer_manager.send_message(text, target)
            _append_message(
                container, "out", state.my_username, text,
                datetime.now(timezone.utc).isoformat(), msg_id=msg_id
            )
            _scroll_bottom()
            # If we were searching, exit search mode after send
            if state.is_searching:
                state.is_searching = False
                await _load_history(force=True)
        except Exception as exc:
            logger.exception("Send failed")
            ui.notify(f"Send failed: {exc}", type="negative")

    def _on_typing_event():
        if state.selected_peer_id != "broadcast":
            asyncio.ensure_future(
                state.peer_manager.send_typing(state.selected_peer_id)
            )

    # ── Inbound message processing ────────────────────────────────────────────────

    async def _poll_inbound():
        try:
            while True:
                msg = state.peer_manager.inbound_queue.get_nowait()
                _process_inbound(msg, messages_area)
        except Exception:
            pass

    ui.timer(0.2, _poll_inbound)

    def _process_inbound(msg: dict, area):
        mtype  = msg.get("type", "MESSAGE")
        pid    = msg.get("peer_id", "")
        sender = msg.get("sender", "Unknown")

        # Ensure peer is tracked in UI state
        if pid and pid not in state.peers:
            state.peers[pid] = {
                "id": pid, "username": sender,
                "online": 1, "unread": 0,
            }

        # ── ACK: flip ✓ to ✓✓ on the outgoing bubble ────────────────────────
        if mtype == "ACK":
            msg_id = msg.get("message_id", "")
            if msg_id:
                safe_id = _esc_js(msg_id)
                ui.run_javascript(
                    f"var el=document.getElementById('ack-{safe_id}');"
                    f"if(el){{el.textContent='✓✓';el.classList.add('msg-ack-done');}}"
                )
            return

        # ── USERNAME_UPDATE ──────────────────────────────────────────────────
        if mtype == "USERNAME_UPDATE":
            if pid in state.peers:
                state.peers[pid]["username"] = sender
            with area:
                ui.html(
                    f'<div class="msg-sys"><span class="msg-sys-pill">'
                    f'✏️ {_esc(sender)} changed their username'
                    f'</span></div>'
                )
            _scroll_bottom()
            return

        # ── SYSTEM (joined/left) ─────────────────────────────────────────────
        if mtype == "SYSTEM":
            evt = msg.get("event", "joined")
            if pid in state.peers:
                state.peers[pid]["online"]   = 1 if evt == "joined" else 0
                state.peers[pid]["username"] = sender
            if state.selected_peer_id == "broadcast" and not state.is_searching:
                with area:
                    ui.html(
                        f'<div class="msg-sys"><span class="msg-sys-pill">'
                        f'{_esc(msg.get("content",""))}</span></div>'
                    )
                _scroll_bottom()
            return

        # ── MESSAGE ─────────────────────────────────────────────────────────
        if mtype == "MESSAGE":
            is_bc = bool(msg.get("is_broadcast", False))
            if state.selected_peer_id != pid and not is_bc:
                if pid in state.peers:
                    state.peers[pid]["unread"] = state.peers[pid].get("unread", 0) + 1

            show = (
                (state.selected_peer_id == "broadcast" and is_bc) or
                (state.selected_peer_id == pid and not is_bc)
            )
            if show and not state.is_searching:
                _append_message(
                    area, "in", _get_display_name(pid),
                    msg.get("content", ""), msg.get("timestamp", "")
                )
                _scroll_bottom()

    # ── Typing UI ────────────────────────────────────────────────────────────────

    def _update_typing_ui():
        now    = time.time()
        active = [
            state.peers.get(pid, {}).get("username", pid)
            for pid, exp in state.peer_manager.typing_peers.items()
            if exp > now
        ]
        if active:
            txt  = (
                f"{active[0]} is typing…" if len(active) == 1
                else "Several people are typing…"
            )
            show = "true"
        else:
            txt  = ""
            show = "false"

        ui.run_javascript(
            f"var bar=document.getElementById('typing-bar');"
            f"var lbl=document.getElementById('typing-label');"
            f"if(bar){{"
            f"  if({show}) bar.classList.add('visible');"
            f"  else bar.classList.remove('visible');"
            f"}}"
            f"if(lbl) lbl.innerText='{_esc_js(txt)}';"
        )

    # ── Peer list rebuild ────────────────────────────────────────────────────────

    def _rebuild_peers(container):
        container.clear()
        with container:
            sorted_peers = sorted(
                state.peers.items(),
                key=lambda x: (not x[1].get("online", 0), x[1].get("username", "").lower()),
            )
            if not sorted_peers:
                ui.html(
                    '<div style="padding:12px 10px;color:var(--t3);font-size:.8rem;'
                    'text-align:center;line-height:1.6;">'
                    'No peers connected yet.<br>Use <b>+</b> to add one.'
                    '</div>'
                )
                return

            for pid, info in sorted_peers:
                uname  = info.get("username", pid)
                online = int(info.get("online", 0))
                unread = int(info.get("unread", 0))
                active = state.selected_peer_id == pid
                cls    = "sb-item active" if active else "sb-item"
                color  = _get_color_for_name(uname)
                ini    = (uname[:1] or "?").upper()
                st_cls = "sb-status online" if online else "sb-status offline"
                badge  = (
                    f'<span class="unread-badge">{unread}</span>'
                    if unread > 0 else ""
                )
                ui.html(
                    f'<div class="{cls}" data-pid="{_esc(pid)}"'
                    f'  onclick="p2pSelect(\'{_esc_js(pid)}\')">'
                    f'  <div class="sb-avatar" style="background:{color}">'
                    f'    {ini}<div class="{st_cls}"></div>'
                    f'  </div>'
                    f'  <span class="sb-label">{_esc(uname)}</span>'
                    f'  {badge}'
                    f'</div>'
                )

    # ── State refresh timer ───────────────────────────────────────────────────────

    async def _refresh_state():
        try:
            peers = await state.peer_manager.store.get_all_peers()
            for p in peers:
                pid = p["id"]
                if pid not in state.peers:
                    state.peers[pid] = {**p, "unread": 0}
                else:
                    state.peers[pid].update(
                        {k: v for k, v in p.items() if k not in ["unread"]}
                    )

            async with state.peer_manager._lock:
                for pid, info in state.peer_manager._peers.items():
                    if pid in state.peers:
                        state.peers[pid]["online"] = info.get("online", 0)
                    else:
                        state.peers[pid] = {
                            "id":      pid,
                            "username": info.get("username", pid),
                            "online":  info.get("online", 0),
                            "unread":  0,
                        }
        except Exception:
            pass

        _update_typing_ui()
        _rebuild_peers(peer_list)

    ui.timer(2.0, _refresh_state)

    # ── Theme toggle ──────────────────────────────────────────────────────────────

    def _toggle_theme():
        state.dark_mode = not state.dark_mode
        icon = _SVG_SUN if state.dark_mode else _SVG_MOON
        if state.dark_mode:
            ui.run_javascript("""
                var r = document.documentElement.style;
                r.setProperty('--app','#0e1015');
                r.setProperty('--sidebar','#111318');
                r.setProperty('--chat-bg','#16181e');
                r.setProperty('--topbar','#111318');
                r.setProperty('--input-bg','#1e2028');
                r.setProperty('--t1','#e3e5ea');
                r.setProperty('--t2','#9da3b4');
                r.setProperty('--t3','#5c6273');
            """ + f"document.getElementById('thm-btn').innerHTML=`{icon}`;")
        else:
            ui.run_javascript("""
                var r = document.documentElement.style;
                r.setProperty('--app','#f2f3f5');
                r.setProperty('--sidebar','#e3e5e8');
                r.setProperty('--chat-bg','#ffffff');
                r.setProperty('--topbar','#f2f3f5');
                r.setProperty('--input-bg','#ebedef');
                r.setProperty('--t1','#060607');
                r.setProperty('--t2','#4e5058');
                r.setProperty('--t3','#6d6f78');
            """ + f"document.getElementById('thm-btn').innerHTML=`{icon}`;")


# ═══════════════════════════════════════════════════════════════════════════════
# Message rendering helpers (no state — safe as module-level)
# ═══════════════════════════════════════════════════════════════════════════════

def _append_message(
    container,
    direction: str,
    sender: str,
    text: str,
    ts_iso: str,
    msg_id: str = None,
):
    """
    Render a chat message bubble.

    msg_id  — if provided, adds a ✓ delivery indicator whose id is
              'ack-{msg_id}'; the UI flips it to ✓✓ when an ACK arrives.
    """
    ts        = _fmt_time(ts_iso)
    color     = _get_color_for_name(sender)
    ini       = (sender[:1] or "?").upper()
    content   = _esc(text)
    name      = _esc(sender)
    is_err    = _is_decrypt_error(text)
    err_cls   = " msg-bubble-error" if is_err else ""
    err_pfx   = "🔒 " if is_err else ""
    row_cls   = f"msg-row msg-row-out{err_cls}" if direction == "out" else f"msg-row msg-row-in{err_cls}"
    ack_html  = (
        f'<span id="ack-{_esc(msg_id)}" class="msg-ack" title="Sent">✓</span>'
        if msg_id and direction == "out"
        else ""
    )

    with container:
        ui.html(
            f'<div class="{row_cls}">'
            f'  <div class="msg-ava" style="background:{color}">{ini}</div>'
            f'  <div class="msg-wrap">'
            f'    <div class="msg-meta">'
            f'      <span class="msg-author" style="color:{color}">{name}</span>'
            f'      <span class="msg-time">{ts}</span>'
            f'      {ack_html}'
            f'    </div>'
            f'    <div class="msg-bubble">{err_pfx}{content}</div>'
            f'  </div>'
            f'</div>'
        )


def _scroll_bottom():
    ui.run_javascript(
        "var m=document.getElementById('msgs'); if(m) m.scrollTop=m.scrollHeight;"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Dialogs
# ═══════════════════════════════════════════════════════════════════════════════

def _build_add_peer_dialog(state: ChatState):
    with ui.dialog() as dlg, ui.card().classes("dlg-card"):
        ui.html('<div class="dlg-title">Connect to Peer</div>')
        ip = ui.input("IP Address", value="127.0.0.1").props("outlined dense") \
               .style("width:100%;margin-bottom:12px;")
        pt = ui.input("TCP Port", value="9002").props("outlined dense") \
               .style("width:100%;margin-bottom:8px;")
        ui.html(
            '<p style="font-size:.8rem;color:var(--t3);margin-bottom:16px;">'
            'Connect directly to a peer node by IP and port number.</p>'
        )

        async def do_add():
            try:
                await state.peer_manager.connect_to_peer(
                    ip.value.strip(), int(pt.value.strip())
                )
                ui.notify(f"Connecting to {ip.value}:{pt.value}…", type="positive")
                dlg.close()
            except Exception as e:
                ui.notify(str(e), type="negative")

        with ui.row().style("justify-content:flex-end;gap:8px;width:100%;"):
            ui.button("Cancel", on_click=dlg.close).props("flat")
            ui.button("Connect", on_click=do_add).props('color="primary"')
    return dlg


def _build_settings_dialog(state: ChatState, config: dict):
    with ui.dialog() as dlg, ui.card().classes("dlg-card"):
        ui.html('<div class="dlg-title">Node Settings</div>')
        uname = ui.input("Display Name", value=config.get("username", "")) \
                  .props("outlined dense").style("width:100%;margin-bottom:12px;")
        pt    = ui.input("TCP Port", value=str(config.get("port", 9001))) \
                  .props("outlined dense").style("width:100%;margin-bottom:12px;")
        enc   = ui.switch(
            "Enable Encryption", value=bool(config.get("encryption_enabled", True))
        ).style("margin-bottom:10px;")
        ui.html(
            '<p style="font-size:.8rem;color:var(--t3);margin-bottom:16px;">'
            'Port changes require an app restart. '
            'Username changes are broadcast to connected peers immediately.</p>'
        )

        async def save():
            import json as _json, os
            new_name = uname.value.strip()
            config["username"]           = new_name
            config["port"]               = int(pt.value.strip())
            config["encryption_enabled"] = bool(enc.value)
            with open(os.path.join(os.path.dirname(__file__), "config.json"), "w") as f:
                _json.dump(config, f, indent=2)

            # Propagate username change to all connected peers immediately
            if new_name and new_name != state.my_username:
                state.my_username = new_name
                try:
                    await state.peer_manager.broadcast_username_update(new_name)
                    ui.notify(f"Username updated to '{new_name}'", type="positive")
                except Exception as exc:
                    ui.notify(f"Saved but broadcast failed: {exc}", type="warning")
            else:
                ui.notify("Settings saved. Restart to apply port changes.", type="positive")
            dlg.close()

        with ui.row().style("justify-content:flex-end;gap:8px;width:100%;"):
            ui.button("Cancel", on_click=dlg.close).props("flat")
            ui.button("Save", on_click=save).props('color="primary"')
    return dlg
