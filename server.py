#!/usr/bin/env python3
"""
TOKEN2049 Paydify demo — local backend.

Serves the demo HTML and:
  POST /api/pay              create a REAL Paydify order → returns its live QR (secret stays server-side)
  POST /api/callback         Paydify's payment webhook (notificationUrl) → verifies + marks the order paid
  GET  /api/status?txnId=..  the page polls this; flips to the success screen when state == PAID
  GET  /api/dev/paid?txnId=  LOCAL TEST ONLY — mark an order paid without a real payment, to see the flip

Callback reachability: Paydify calls notificationUrl from the internet, so it must be a PUBLIC https URL.
Set PUBLIC_BASE_URL to a public https base that forwards to this server, e.g. a tunnel:
    cloudflared tunnel --url http://127.0.0.1:8080     (or: ngrok http 8080)
    PUBLIC_BASE_URL=https://<your-tunnel>.trycloudflare.com python3 server.py
Without it, orders are still created (notificationUrl falls back to a placeholder) but no real
callback can arrive — use /api/dev/paid to demo the page flip locally.

Run:
    PAYDIFY_KEY=AK... PAYDIFY_SECRET=... python3 server.py     (or use paydify.secret.json)
Open http://127.0.0.1:8080/  (set PORT=... to change)

Pure Python standard library — no pip installs needed.
"""
import json, os, time, hmac, hashlib, base64, threading, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
# Page served at "/". Override with DEFAULT_PAGE=TOKEN2049-Paydify-demo.html for the multi-scenario demo.
HTML = os.environ.get("DEFAULT_PAGE", "shop-demo.html")
BASE = os.environ.get("PAYDIFY_BASE", "https://openapi.paydify.com/crypto-payment")
API_PATH = "/payin/v1/createPayment"          # what gets signed (no /crypto-payment prefix)
QUERY_PATH = "/payin/v1/getPaymentStatus"     # poll real order status by mchTxnId (no public URL needed)

# Public https base that forwards to this server (a tunnel), used for the callback URL.
PUBLIC_BASE = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
CALLBACK_PATH = "/api/callback"
CALLBACK_URL = (PUBLIC_BASE + CALLBACK_PATH) if PUBLIC_BASE.startswith("https://") else "https://example.com/callback"

# In-memory order state: txnId -> state (INIT / PAYING / PAID / FAILED / TIMEOUT), plus txnId -> mchTxnId
# so /api/status can ask Paydify for the live state. Demo-scale.
ORDERS = {}
TXN2MCH = {}
LOCK = threading.Lock()
FINAL = {"PAID", "FAILED", "TIMEOUT"}


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def load_creds():
    """Env vars first, then optional paydify.secret.json next to this file. Never hardcoded."""
    key = os.environ.get("PAYDIFY_KEY")
    secret = os.environ.get("PAYDIFY_SECRET")
    merchant_id = os.environ.get("PAYDIFY_MERCHANT_ID", "M524689056")
    app_id = os.environ.get("PAYDIFY_APP_ID", "A24689057")
    p = os.path.join(HERE, "paydify.secret.json")
    if (not key or not secret) and os.path.exists(p):
        c = json.load(open(p))
        key = key or c.get("key")
        secret = secret or c.get("secret")
        merchant_id = c.get("merchantId", merchant_id)
        app_id = c.get("appId", app_id)
    return key, secret, merchant_id, app_id


def sign(app_id, secret, api_path, body, ts):
    # HMAC-SHA256 over compact-JSON of the 4 signed fields, sorted; base64 (lowercase-hex NOT used).
    content = json.dumps(
        {"apiPath": api_path, "body": body, "x-api-key": app_id, "x-api-timestamp": str(ts)},
        separators=(",", ":"), sort_keys=True, ensure_ascii=False,
    )
    return base64.b64encode(hmac.new(secret.encode(), content.encode(), hashlib.sha256).digest()).decode()


def _post(key, secret, body):
    ts = int(time.time() * 1000)
    body_str = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
    sig = sign(key, secret, API_PATH, body_str, ts)
    req = urllib.request.Request(
        BASE + API_PATH, data=body_str.encode("utf-8"), method="POST",
        headers={"content-type": "application/json", "x-api-key": key,
                 "x-api-timestamp": str(ts), "x-api-signature": sig},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"code": "HTTP%d" % e.code, "message": "http error"}
    except Exception as e:
        return {"code": "NETWORK", "message": str(e)}


def create_payment(amount, currency, pay1, pay2, desc, title=""):
    """Create a real order carrying the exact currency / wallet (payMethod1) / chain (payMethod2)
    the shopper picked. If that specific combo isn't accepted, retry generic so the QR still works."""
    key, secret, mid, aid = load_creds()
    if not key or not secret:
        return {"ok": False, "error": "server missing PAYDIFY_KEY / PAYDIFY_SECRET"}

    # Public-exposure hardening: the browser sends the amount, so on a public URL clamp/override it
    # server-side. FIXED_AMOUNT forces every order to that value (set FIXED_AMOUNT=0.10 for a shop-only
    # booth). Otherwise MAX_AMOUNT caps it (default 100) so nobody can mint an absurd order.
    fixed = os.environ.get("FIXED_AMOUNT", "").strip()
    if fixed:
        amount = fixed
    else:
        try:
            cap = float(os.environ.get("MAX_AMOUNT", "100"))
            if float(amount) > cap:
                amount = ("%s" % cap).rstrip("0").rstrip(".")
        except (TypeError, ValueError):
            amount = "0.10"

    def build(with_methods):
        b = {
            "mchTxnId": "t2049-%d" % int(time.time() * 1000),
            "txnAmount": str(amount),
            "currency": (currency or "USDT").upper(),
            "checkoutMode": "MERCHANT",
            "merchantId": mid, "merchantAppId": aid,
            "notificationUrl": CALLBACK_URL,
            "successReturnUrl": "", "failReturnUrl": "", "pendingReturnUrl": "",
            "txnTitle": (title or "")[:120], "txnDesc": (desc or "")[:120],
        }
        if with_methods and pay1:
            b["payMethod1"] = pay1
        if with_methods and pay2:
            b["payMethod2"] = pay2
        return b

    specific = bool(pay1 or pay2)
    resp = _post(key, secret, build(specific))
    if resp.get("code") != "SYS_SUCCESS" and specific:      # combo not accepted → generic order
        resp = _post(key, secret, build(False)); specific = False
    if resp.get("code") != "SYS_SUCCESS":
        return {"ok": False, "error": resp.get("messageDetail") or resp.get("message") or resp.get("code")}
    d = resp.get("data") or {}
    txn = d.get("txnId"); mch = d.get("mchTxnId")
    if txn:
        with LOCK:
            ORDERS[txn] = (d.get("state") or "INIT").upper()
            if mch:
                TXN2MCH[txn] = mch
        log("order created  txnId=%s  amount=%s %s" % (txn, amount, (currency or "USDT")))
    return {"ok": True, "txnId": txn, "httplink": d.get("httplink"),
            "qrCode": d.get("qrCode"), "state": d.get("state"), "specific": specific}


def get_payment_status(txn):
    """Ask Paydify for the live state of an order BY txnId. Returns state (upper) or None.
    Querying by txnId (not mchTxnId) means it does NOT depend on any in-memory map, so it keeps
    working even if this process restarted between order creation and payment (e.g. Render cold start)."""
    key, secret, mid, aid = load_creds()
    if not (key and secret and txn):
        return None
    ts = int(time.time() * 1000)
    body_str = json.dumps({"txnId": txn, "merchantAppId": aid}, separators=(",", ":"), ensure_ascii=False)
    sig = sign(key, secret, QUERY_PATH, body_str, ts)
    req = urllib.request.Request(
        BASE + QUERY_PATH, data=body_str.encode("utf-8"), method="POST",
        headers={"content-type": "application/json", "x-api-key": key,
                 "x-api-timestamp": str(ts), "x-api-signature": sig},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read().decode("utf-8"))
    except Exception:
        return None
    if resp.get("code") != "SYS_SUCCESS":
        return None
    data = resp.get("data") or []
    if not data:
        return None
    return ((data[0].get("state") or "").upper()) or None


def status_of(txn):
    """Live order state for the page's poll: cached final state, else ask Paydify BY txnId
    (stateless — survives restarts)."""
    with LOCK:
        st = ORDERS.get(txn, "UNKNOWN")
    if st in FINAL:                      # already settled (via callback or a prior poll) — no re-query
        return st
    live = get_payment_status(txn)
    if live:
        with LOCK:
            ORDERS[txn] = live
        if live in FINAL:
            log("order %s -> %s (via query)" % (txn, live))
        return live
    return st


def verify_callback(headers, raw_body):
    """Recompute the Payin signature over the raw callback and compare to x-api-signature."""
    _, secret, _, _ = load_creds()
    key = headers.get("x-api-key", "")
    ts = headers.get("x-api-timestamp", "")
    got = headers.get("x-api-signature", "")
    if not (secret and key and ts and got):
        return False
    expect = sign(key, secret, CALLBACK_PATH, raw_body, ts)
    return hmac.compare_digest(expect, got)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, ctype, body):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/status":
            txn = (parse_qs(parsed.query).get("txnId") or [""])[0]
            st = status_of(txn)
            self._send(200, "application/json", json.dumps({"state": st, "paid": st == "PAID"}))
            return
        if path == "/api/dev/paid":                     # LOCAL TEST ONLY
            txn = (parse_qs(parsed.query).get("txnId") or [""])[0]
            with LOCK:
                if txn:
                    ORDERS[txn] = "PAID"
            self._send(200, "application/json", json.dumps({"ok": bool(txn), "state": "PAID"}))
            return
        if path == "/":
            path = "/" + HTML
        fp = os.path.normpath(os.path.join(HERE, path.lstrip("/")))
        if not fp.startswith(HERE) or not os.path.isfile(fp):
            self._send(404, "text/plain", "not found"); return
        ctype = "text/html; charset=utf-8" if fp.endswith(".html") else "application/octet-stream"
        with open(fp, "rb") as f:
            self._send(200, ctype, f.read())

    def do_POST(self):
        path = urlparse(self.path).path
        n = int(self.headers.get("content-length", 0) or 0)
        raw = self.rfile.read(n) if n else b""

        if path == "/api/callback":
            raw_str = raw.decode("utf-8", "replace")
            hdr = {k.lower(): v for k, v in self.headers.items()}
            ok = verify_callback(hdr, raw_str)
            try:
                p = json.loads(raw_str)
            except Exception:
                p = {}
            txn = p.get("txnId"); state = (p.get("state") or "").upper()
            log("CALLBACK IN   txnId=%s  state=%s  signature=%s" % (txn, state, "OK" if ok else "BAD/REJECTED"))
            if not ok:
                self._send(401, "text/plain", "invalid signature"); return
            if txn and state:
                with LOCK:
                    ORDERS[txn] = state          # idempotent: last write wins on (txnId,state)
            self._send(200, "text/plain", "success")     # ack so Paydify stops retrying
            return

        if path == "/api/pay":
            try:
                data = json.loads(raw or b"{}")
            except Exception:
                data = {}
            result = create_payment(data.get("amount", "1"), data.get("currency", "USDT"),
                                    data.get("payMethod1", ""), data.get("payMethod2", ""),
                                    data.get("desc", ""), data.get("title", ""))
            self._send(200, "application/json", json.dumps(result))
            return

        self._send(404, "application/json", '{"ok":false,"error":"not found"}')

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    # HOST: local default 127.0.0.1 (safe); cloud sets HOST=0.0.0.0 so the platform can reach it.
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8080"))
    key, _, mid, aid = load_creds()
    print("=" * 56)
    print(" TOKEN2049 Paydify demo")
    print(" listen   : http://%s:%d/  (default page: %s)" % (host, port, HTML))
    print(" creds    : %s   merchant=%s app=%s" % ("loaded" if key else "MISSING (set PAYDIFY_KEY/PAYDIFY_SECRET)", mid, aid))
    print(" amount   : %s" % (("fixed " + os.environ["FIXED_AMOUNT"]) if os.environ.get("FIXED_AMOUNT") else ("cap " + os.environ.get("MAX_AMOUNT", "100"))))
    print("=" * 56)
    ThreadingHTTPServer((host, port), Handler).serve_forever()
