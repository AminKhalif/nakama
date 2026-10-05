"""Human operator console at /console (mobile-friendly HTML).

Separate auth domain from agents, enforced server-side: the console only
accepts the operator token (via login cookie). Agent keypairs and signed
envelopes are never consulted here, and console endpoints never accept
them -- so an agent key cannot approve friendships, touch grants, rotate
keys, or revoke anything, no matter what it sends.

What the human gets: per-agent invite codes (minted here, single-use,
24h), pending friend-request cards with a scope sheet on accept, per-grant
expiry controls, live games with spectator links, one-tap revoke/unfriend
(freezes live sessions immediately), key rotation, the revocation list,
and an activity feed.
"""

import hashlib
import hmac
import os
import secrets
import time
from datetime import datetime, timezone

from . import friends, identity

SESSION_TTL = 12 * 3600
_sessions = {}  # sid -> expiry unix ts (in-memory; single process)

SCOPE_WORDS = {
    "game.ttt:play": "Play tic-tac-toe with this friend",
    "game.ttt:spectate": "See this friend's game results",
}


def ensure_console_token(store):
    """Return the plaintext token only when it is newly created (print once).
    Otherwise return None: the token is stored hashed and never recoverable.
    GW_CONSOLE_TOKEN env presets it without printing."""
    existing = store.get_config("console_token_hash")
    env_token = os.environ.get("GW_CONSOLE_TOKEN", "").strip()
    if env_token:
        store.set_config("console_token_hash", _hash(env_token))
        return None
    if existing:
        return None
    token = "gwop_" + secrets.token_urlsafe(24)
    store.set_config("console_token_hash", _hash(token))
    return token


def _hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _authed(cookies):
    sid = cookies.get("gw_console", "")
    exp = _sessions.get(sid)
    if exp and exp > time.time():
        _sessions[sid] = time.time() + SESSION_TTL
        return True
    _sessions.pop(sid, None)
    return False


def esc(s):
    return str(s if s is not None else "").replace("&", "&amp;").replace(
        "<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _ts(ts):
    if not ts:
        return "--"
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _ago(ts):
    if not ts:
        return "never"
    mins = int((time.time() - ts) / 60)
    if mins < 1:
        return "just now"
    if mins < 60:
        return "%dm ago" % mins
    hours = mins // 60
    if hours < 48:
        return "%dh ago" % hours
    return "%dd ago" % (hours // 24)


# ---------------------------------------------------------------------------
# html
# ---------------------------------------------------------------------------

STYLE = """<style>
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,sans-serif;margin:0;padding:14px;
color:#1a1a1a;background:#fafafa}
.wrap{max-width:680px;margin:0 auto}
h1{font-size:22px}h2{font-size:17px;margin:22px 0 8px}
.card{background:#fff;border:1px solid #ddd;border-radius:12px;padding:14px;
margin:10px 0}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
code{background:#f0f0f0;padding:2px 6px;border-radius:4px;font-size:13px;
word-break:break-all}
button{padding:9px 14px;font-size:14px;border-radius:8px;border:1px solid #ccc;
background:#fff;cursor:pointer}
button.primary{background:#0b5fff;color:#fff;border-color:#0b5fff}
button.danger{color:#b00020;border-color:#e88}
input,select{padding:9px;font-size:14px;border-radius:8px;border:1px solid #ccc;
max-width:100%}
.muted{color:#666;font-size:13px}
.pill{display:inline-block;padding:2px 8px;border-radius:20px;font-size:12px;
background:#eef;font-weight:600}
.pill.ok{background:#e2f5e9}.pill.bad{background:#ffe9e9}.pill.warn{background:#fff4d6}
table{width:100%;border-collapse:collapse;font-size:14px}
td,th{padding:6px 4px;border-bottom:1px solid #eee;text-align:left}
.feed{font-size:13px}.feed div{padding:5px 0;border-bottom:1px solid #f0f0f0}
form.inline{display:inline}
label.scope{display:block;padding:6px 0}
</style>"""


def login_page(error=""):
    return ("<!doctype html><html><head><meta charset=utf-8>"
            '<meta name=viewport content="width=device-width,initial-scale=1">'
            "<title>Gateway console</title>" + STYLE + "</head><body><div class=wrap>"
            "<h1>&#129302; Gateway console</h1>"
            "<div class=card><p>Operator sign-in. This token was printed once "
            "when the gateway first started.</p>"
            + (("<p><b>%s</b></p>" % esc(error)) if error else "") +
            '<form method=post action="/console/login">'
            '<input type=password name=token placeholder="operator token" '
            'style="width:100%;margin-bottom:10px" autocomplete=off>'
            '<br><button class=primary type=submit>Sign in</button></form></div>'
            "</div></body></html>")


def dashboard(store):
    agents = store.list_agents()
    friendships = store.list_friendships()
    sess_list = store.all_sessions()
    events = store.recent_events(60)
    revoked = store.revoked_keys()
    names = {a["id"]: a["name"] for a in agents}
    last_active = {}
    for e in events:
        if e["agent_id"] and e["agent_id"] not in last_active:
            last_active[e["agent_id"]] = e["ts"]

    h = ["<!doctype html><html><head><meta charset=utf-8>",
         '<meta name=viewport content="width=device-width,initial-scale=1">',
         "<title>Gateway console</title>", STYLE, "</head><body><div class=wrap>",
         "<h1>&#129302; Gateway console</h1>",
         '<p><form class=inline method=post action="/console/logout">'
         '<button type=submit>Sign out</button></form></p>']

    # -- agents & invite codes --
    h.append("<h2>Agents</h2>")
    if not agents:
        h.append("<p class=muted>No agents registered yet.</p>")
    for a in agents:
        code = store.active_invite_code(a["id"])
        h.append('<div class=card><div class=row><b>%s</b>'
                 '<span class=pill>%s</span></div>'
                 % (esc(a["name"]), esc(a["vendor"] or "agent")))
        h.append('<p class=muted>Owner: %s &middot; last active %s</p>'
                 % (esc(a["owner_display_name"]),
                    _ago(last_active.get(a["id"]))))
        h.append("<p>Invite code: ")
        if code:
            h.append("<code>%s</code> <span class=muted>single-use, expires %s</span>"
                     % (esc(code["code"]), _ts(code["expires_at"])))
        else:
            h.append('<span class=muted>none active</span>')
        h.append(' <form class=inline method=post action="/console/invite/%s/mint">'
                 "<button type=submit>Mint new code</button></form></p>" % a["id"])
        h.append('<p class=muted>Share the code with the other human so their '
                 "agent can send a friend request.</p>")
        h.append('<form method=post action="/console/keys/rotate">'
                 '<input type=hidden name=agent_id value="' + a["id"] + '">'
                 '<input name=new_pubkey placeholder="new ed25519:&lt;64 hex&gt; key" '
                 'style="width:100%;margin-bottom:8px">'
                 '<button type=submit>Rotate key</button></form>')
        # pending requests where this agent is the recipient
        for r in store.pending_requests_for(a["id"]):
            if r["b_id"] != a["id"]:
                continue
            frm = names.get(r["a_id"], "?")
            h.append('<div class=card><b>Friend request</b> from %s<br>'
                     '<span class=muted>Accepting opens a scope sheet.</span>'
                     '<form method=post action="/console/requests/%s/accept">'
                     % (esc(frm), r["id"]))
            for scope in friends.DEFAULT_SCOPES:
                h.append('<label class=scope><input type=checkbox name=scope '
                         'value="%s" checked> %s <code>%s</code></label>'
                         % (esc(scope), esc(SCOPE_WORDS.get(scope, scope)),
                            esc(scope)))
            h.append('<label class=scope>Grant lasts '
                     '<input type=number name=days min=1 max=3650 value=365 '
                     'style="width:80px"> days</label>'
                     '<button class=primary type=submit>Accept</button></form> '
                     '<form class=inline method=post '
                     'action="/console/requests/%s/decline">'
                     "<button type=submit>Decline</button></form></div>" % r["id"])
        h.append("</div>")

    # -- friendships & grants --
    h.append("<h2>Friendships &amp; scopes</h2>")
    if not friendships:
        h.append("<p class=muted>None yet.</p>")
    for fr in friendships:
        an, bn = names.get(fr["a_id"], "?"), names.get(fr["b_id"], "?")
        pill = {"accepted": "ok", "pending": "warn", "declined": "bad",
                "revoked": "bad"}.get(fr["status"], "")
        h.append('<div class=card><div class=row><b>%s &harr; %s</b>'
                 '<span class="pill %s">%s</span></div>'
                 % (esc(an), esc(bn), pill, esc(fr["status"])))
        for g in store.grants_for_friendship(fr["id"]):
            who = names.get(g["agent_id"], "?")
            desc = SCOPE_WORDS.get(g["scope"], g["scope"])
            state = "revoked" if g["revoked"] else (
                "expired" if g["expires_at"] <= time.time() else "live")
            gpill = "ok" if state == "live" else "bad"
            h.append('<p><span class="pill %s">%s</span> <code>%s</code> '
                     '<span class=muted>for %s</span><br>'
                     '<span class=muted>%s &middot; expires %s</span><br>'
                     % (gpill, state, esc(g["scope"]), esc(who), esc(desc),
                        _ts(g["expires_at"])))
            h.append('<form class=inline method=post action="/console/grants/%s/%s">'
                     '<button type=submit>%s</button></form> '
                     % (g["id"], "restore" if g["revoked"] else "revoke",
                        "Restore" if g["revoked"] else "Revoke"))
            h.append('<form class=inline method=post action="/console/grants/%s/expiry">'
                     '<input type=number name=days min=1 max=3650 value=365 '
                     'style="width:80px" title="days from now">'
                     '<button type=submit>Set expiry</button></form></p>' % g["id"])
        if fr["status"] == "accepted":
            h.append('<form method=post action="/console/friendships/%s/unfriend">'
                     '<button class=danger type=submit>Unfriend &amp; freeze sessions'
                     "</button></form>" % fr["id"])
        h.append("</div>")

    # -- sessions --
    h.append("<h2>Sessions</h2>")
    live = [s for s in sess_list if s["status"] == "active"]
    if not live:
        h.append("<p class=muted>No live sessions.</p>")
    for s in live:
        h.append('<div class=card><div class=row><b><a href="/g/%s">%s</a></b>'
                 '<span class="pill ok">%s</span></div>'
                 '<p class=muted>%s (a/X) vs %s (b/O) &middot; auditor %s '
                 "&middot; round %d &middot; phase %s</p>"
                 % (s["id"], esc(s["id"][:14]), esc(s["status"]),
                    esc(names.get(s["a_id"], "?")), esc(names.get(s["b_id"], "?")),
                    esc(names.get(s["auditor_id"], "?")),
                    s["round"], esc(s["phase"])))
        h.append('<form method=post action="/console/sessions/%s/freeze">'
                 '<button class=danger type=submit>Freeze</button></form>'
                 % s["id"])
        h.append("</div>")

    # -- revoked keys --
    h.append("<h2>Revoked keys</h2>")
    h.append('<div class=card><form method=post action="/console/keys/revoke">'
             '<input name=pubkey placeholder="ed25519:<64 hex> public key" '
             'style="width:100%;margin-bottom:8px">'
             '<input name=reason placeholder="reason" '
             'style="width:100%;margin-bottom:8px">'
             '<button class=danger type=submit>Revoke key</button></form>')
    for k in revoked:
        h.append("<p><code>%s</code><br><span class=muted>%s &middot; %s</span></p>"
                 % (esc(k["pubkey"][:32] + "..."),
                    esc(k["reason"]), _ts(k["revoked_at"])))
    h.append("</div>")

    # -- activity --
    h.append("<h2>Activity</h2><div class=card feed>")
    for e in events:
        when = datetime.fromtimestamp(e["ts"], timezone.utc).strftime("%m-%d %H:%M")
        h.append("<div><span class=muted>%s</span> <b>%s</b> %s</div>"
                 % (when, esc(e["kind"]), esc(e["summary"])))
    h.append("</div></div></body></html>")
    return "".join(h)


# ---------------------------------------------------------------------------
# request handling. `res` is a small responder provided by server.py with
# send_html(str), see_other(url), and read_form() -> dict.
# ---------------------------------------------------------------------------

class ConsoleApp:
    def __init__(self, store, gw_keys):
        self.store = store
        self.gw_keys = gw_keys

    def authed(self, cookies):
        """Public so server.py can gate gw.friend_decide on console auth."""
        return _authed(cookies)

    def handle(self, method, path, cookies, res):
        """Return True if this was a console path (handled), else False."""
        if not path.startswith("/console"):
            return False
        if path == "/console/login" and method == "POST":
            return self._login(res)
        if path == "/console/logout" and method == "POST":
            return self._logout(cookies, res)
        if not _authed(cookies):
            res.send_html(login_page())
            return True
        if method == "GET" and path in ("/console", "/console/"):
            res.send_html(dashboard(self.store))
            return True
        if method == "POST":
            return self._action(path, res)
        res.send_html(dashboard(self.store))
        return True

    # -- auth ------------------------------------------------------------
    def _login(self, res):
        form = res.read_form()
        token = form.get("token", [""])[0]
        want = self.store.get_config("console_token_hash")
        if want and hmac.compare_digest(_hash(token), want):
            sid = secrets.token_urlsafe(24)
            _sessions[sid] = time.time() + SESSION_TTL
            res.see_other("/console", cookie=("gw_console", sid))
        else:
            res.send_html(login_page("Wrong token."))
        return True

    def _logout(self, cookies, res):
        _sessions.pop(cookies.get("gw_console", ""), None)
        res.see_other("/console", cookie=("gw_console", "expired; Max-Age=0"))
        return True

    # -- actions -----------------------------------------------------------
    def _action(self, path, res):
        store = self.store
        parts = path.split("/")

        def done():
            res.see_other("/console")
            return True

        if len(parts) == 5 and parts[2] == "requests" and parts[4] == "accept":
            form = res.read_form()
            scopes = [s for s in form.get("scope", [])
                      if s in friends.DEFAULT_SCOPES]
            try:
                days = max(1, min(3650, int(form.get("days", ["365"])[0])))
            except ValueError:
                days = 365
            friends.human_decide(store, self.gw_keys, parts[3], True,
                                 scopes=scopes or None,
                                 expires_at=time.time() + days * 86400)
            return done()
        if len(parts) == 5 and parts[2] == "requests" and parts[4] == "decline":
            friends.human_decide(store, self.gw_keys, parts[3], False)
            return done()
        if len(parts) == 5 and parts[2] == "invite" and parts[4] == "mint":
            friends.mint_invite_code(store, parts[3])
            return done()
        if len(parts) == 5 and parts[2] == "grants" and parts[4] in ("revoke", "restore"):
            friends.set_grant_revoked(store, self.gw_keys, parts[3],
                                      parts[4] == "revoke")
            return done()
        if len(parts) == 5 and parts[2] == "grants" and parts[4] == "expiry":
            form = res.read_form()
            try:
                days = max(1, min(3650, int(form.get("days", ["365"])[0])))
            except ValueError:
                days = 365
            friends.set_grant_expiry(store, parts[3], time.time() + days * 86400)
            return done()
        if len(parts) == 5 and parts[2] == "friendships" and parts[4] == "unfriend":
            friends.revoke_friendship(store, self.gw_keys, parts[3])
            return done()
        if len(parts) == 5 and parts[2] == "sessions" and parts[4] == "freeze":
            ttt_freeze(store, parts[3])
            return done()
        if path == "/console/keys/revoke":
            form = res.read_form()
            pubkey = form.get("pubkey", [""])[0].strip()
            reason = form.get("reason", [""])[0].strip()
            identity.revoke_key(store, pubkey, reason)
            return done()
        if path == "/console/keys/rotate":
            form = res.read_form()
            agent_id = form.get("agent_id", [""])[0]
            new_pubkey = form.get("new_pubkey", [""])[0].strip()
            identity.rotate_key(store, self.gw_keys, agent_id, new_pubkey)
            return done()
        res.see_other("/console")
        return True


def ttt_freeze(store, session_id):
    from . import sessions as ttt
    ttt.freeze_session(store, session_id, "frozen by human in console")
