#!/usr/bin/env python3
"""HEAT MAP Telegram poster for @heatsfun_bot.
Usage: post_heatmap.py auto|board|alerts|preview
- auto: alerts on new coin / leader change; full board if >= board_every_minutes since last board post
- board: post the full board now
- alerts: only alerts
- preview: print the board message, post nothing
Reads ../heat0.json (caller pulls). State in tg_state.json (committed).
"""
import json, os, sys, subprocess, html, datetime, urllib.request, urllib.parse
HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "config.json")))
STATE_PATH = os.path.join(HERE, "tg_state.json")
REPO = os.path.dirname(HERE)

def load_board():
    d = json.load(open(os.path.join(REPO, "heat0.json")))
    coins = sorted(d.get("coins", []), key=lambda c: -c.get("score", 0))
    return coins

def board_msg(coins):
    e = html.escape
    lines = [f"🔥 <b>HEAT MAP · HEAT {CFG['heat_number']}</b>"]
    if coins:
        for i, c in enumerate(coins, 1):
            lines.append(f"{i}. <b>{e(c['ticker'])}</b> {c['score']}")
    else:
        lines.append("No CAs yet — be the first.")
    lines.append(f"⏳ HEAT END: {e(CFG['heat_end_label'])}")
    lines.append(f"Drop your CA under the HEAT post 👉 {e(CFG['heat_post'])}")
    lines.append("heats.fun")
    return "\n".join(lines)

def send(text):
    tok = os.environ["HEATMAP_TG_BOT_TOKEN"]
    data = urllib.parse.urlencode({"chat_id": CFG["chat_id"], "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    r = json.load(urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data, timeout=30))
    if not r.get("ok"):
        raise SystemExit(f"telegram error: {r}")
    return r["result"]["message_id"]

def screenshot():
    out = "/tmp/heatmap.png"
    try:
        if os.path.exists(out): os.remove(out)
        subprocess.run(["timeout", "90", os.environ.get("CHROME_BIN", "google-chrome"), "--headless=new", "--no-sandbox", "--disable-gpu",
                        "--hide-scrollbars", "--window-size=1280,900", "--virtual-time-budget=10000",
                        f"--screenshot={out}", "https://heats.fun/map"], capture_output=True, check=False)
        return out if os.path.exists(out) and os.path.getsize(out) > 20000 else None
    except Exception:
        return None

def send_photo(path, caption):
    import mimetypes, uuid
    tok = os.environ["HEATMAP_TG_BOT_TOKEN"]
    b = uuid.uuid4().hex
    parts = []
    for k, v in (("chat_id", str(CFG["chat_id"])), ("caption", caption), ("parse_mode", "HTML")):
        parts.append(f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    parts.append(f"--{b}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"heatmap.png\"\r\nContent-Type: image/png\r\n\r\n".encode()
                 + open(path, "rb").read() + b"\r\n")
    parts.append(f"--{b}--\r\n".encode())
    req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendPhoto", b"".join(parts),
                                 {"Content-Type": f"multipart/form-data; boundary={b}"})
    r = json.load(urllib.request.urlopen(req, timeout=60))
    if not r.get("ok"):
        raise SystemExit(f"telegram error: {r}")
    return r["result"]["message_id"]

def post_board(coins):
    shot = screenshot()
    if shot:
        try:
            return send_photo(shot, board_msg(coins))
        except BaseException as ex:
            print(json.dumps({"photo_failed": str(ex)}))
    return send(board_msg(coins))

def sig(coins):
    return [[c["ca"], c["score"]] for c in coins]

def change_summary(prev, coins):
    e = html.escape
    pm = {ca: (i, sc) for i, (ca, sc) in enumerate(prev)}
    cur = {c["ca"]: (i, c) for i, c in enumerate(coins)}
    out = []
    if coins and prev and coins[0]["ca"] != prev[0][0]:
        out.append(f"👑 New leader: <b>{e(coins[0]['ticker'])}</b>")
    for i, c in enumerate(coins):
        if c["ca"] not in pm:
            out.append(f"🆕 <b>{e(c['ticker'])}</b> joined with {c['score']} pts")
        else:
            pi, ps = pm[c["ca"]]
            if c["score"] != ps:
                d = c["score"] - ps
                out.append(f"{'📈' if d > 0 else '📉'} <b>{e(c['ticker'])}</b> {ps} → {c['score']}")
            elif pi != i:
                out.append(f"↕️ <b>{e(c['ticker'])}</b> #{pi+1} → #{i+1}")
    for ca, _ in prev:
        if ca not in cur:
            out.append("➖ a coin left the board")
    if any(x.startswith("🆕") or x.startswith("📈") or x.startswith("📉") for x in out):
        out = [x for x in out if not x.startswith("↕️")]
    return out

import re
def sanitize_comment(text):
    """Never mention who called a coin: drop @handles and Jay/jaywebski (incl. possessives)."""
    if not text: return text
    t = re.sub(r"\s*\b(?:from|by|via)\s+(?:@\w+|jaywebski|jay)(?:'s|’s)?(?:\s+(?:CA-only\s+)?(?:reply|call|post|tweet|CA))?", "", text, flags=re.I)
    t = re.sub(r"@\w+", "", t)
    t = re.sub(r"\b(?:jaywebski|jay)(?:'s|’s)?\b", "", t, flags=re.I)
    t = re.sub(r"\s+([;,.!?])", r"\1", t)
    return re.sub(r"\s{2,}", " ", t).strip()

def auto_comment(prev, coins):
    # Uses only tickers, scores and ranks; never names accounts.
    if not coins: return None
    pm = {ca: (i, sc) for i, (ca, sc) in enumerate(prev)}
    t = lambda c: c["ticker"]
    if prev and coins[0]["ca"] != prev[0][0]:
        return f"{t(coins[0])} takes the lead with {coins[0]['score']} pts!"
    new = [c for c in coins if c["ca"] not in pm]
    if new:
        return f"{t(new[0])} enters the HEAT MAP at #{coins.index(new[0])+1}."
    ups = sorted([(c["score"] - pm[c["ca"]][1], c) for c in coins if c["ca"] in pm and c["score"] > pm[c["ca"]][1]], key=lambda x: -x[0])
    if ups:
        d, c = ups[0]
        i = coins.index(c); pi = pm[c["ca"]][0]
        if i < pi:
            return f"{t(c)} climbs to #{i+1} (+{d}). {t(coins[0])} still on top."
        return f"{t(c)} heating up (+{d}). {t(coins[0])} still leads with {coins[0]['score']}."
    return f"Board shuffle. {t(coins[0])} still leads with {coins[0]['score']}."

def main():
    args = sys.argv[1:]
    comment = None
    if "--comment" in args:
        i = args.index("--comment"); comment = args[i+1] if i+1 < len(args) else None
        args = args[:i] + args[i+2:]
    mode = args[0] if args else "auto"
    coins = load_board()
    if mode == "preview":
        print(board_msg(coins), screenshot()); return
    now = datetime.datetime.now(datetime.timezone.utc)
    if now > datetime.datetime.fromisoformat(CFG["heat_end_iso"]) and mode == "auto":
        print(json.dumps({"skipped": "heat_ended"})); return
    st = json.load(open(STATE_PATH)) if os.path.exists(STATE_PATH) else {}
    if st.get("heat_number") != CFG["heat_number"]:
        st = {"heat_number": CFG["heat_number"], "last_sig": None}
    if "last_sig" not in st:
        st["last_sig"] = None
    cur = sig(coins)
    posted = None
    if mode == "board" or (mode == "auto" and cur != st["last_sig"]):
        changes = change_summary(st["last_sig"] or [], coins) if st["last_sig"] is not None and mode == "auto" else []
        cap = board_msg(coins)
        if changes:
            cap = "\n".join(changes[:8]) + "\n\n" + cap
        if not comment and changes:
            comment = auto_comment(st["last_sig"] or [], coins)
        comment = sanitize_comment(comment)
        if comment:
            cap = f"💬 <i>{html.escape(comment.strip())[:300]}</i>\n\n" + cap
        shot = screenshot()
        if shot:
            try:
                posted = send_photo(shot, cap[:1024])
            except BaseException as ex:
                print(json.dumps({"photo_failed": str(ex)}))
        if posted is None:
            posted = send(cap)
        st["last_sig"] = cur
        st["last_board"] = now.isoformat()
    json.dump(st, open(STATE_PATH, "w"), indent=2)
    print(json.dumps({"mode": mode, "posted": posted, "changed": posted is not None}))

if __name__ == "__main__":
    main()
