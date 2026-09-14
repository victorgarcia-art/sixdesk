"""Ciclo horario. Corre en GitHub Actions (o donde sea) a los 5 minutos de cada hora.

1. Baja las últimas 500 velas 1h de todos los pares USDT de MEXC (velas cerradas).
2. Detecta: triple divergencia alcista reciente (vigilancia) y ruptura por compresión en la última vela cerrada (setup).
3. Actualiza posiciones paper abiertas (objetivo +15%, stop -7%, 72h).
4. Pasa cada setup por los seis agentes; si EINSTEIN aprueba, abre posición paper y avisa.
5. Guarda estado en data/ (el workflow lo commitea).
"""
import json, os, sys, time, threading
from concurrent.futures import ThreadPoolExecutor
import numpy as np, requests

from desk import signals as S
from desk.config import CFG
from desk import agents
from notify import notify

BASE = "https://api.mexc.com"
MIN_VOL24 = float(os.getenv("MIN_VOL24", 50_000))
TP, SL, MAX_HOURS = 0.15, 0.07, 72
EXCL = {"USDC","USDT","USDE","DAI","TUSD","FDUSD","USD1","PYUSD","USDD","USDP","EURT","BUSD","XAUT","PAXG","WBTC","WETH","STETH","USDQ","USDS","RLUSD","USDY","EUR"}
STATE = "data/state.json"; SETUPS = "data/setups.jsonl"; WATCH = "data/vigilancia.json"; LAST = "data/ultimo_ciclo.md"

sess = requests.Session(); _lock = threading.Lock(); _last = [0.0]
def _limiter(rps=15):
    with _lock:
        w = _last[0] + 1 / rps - time.time()
        if w > 0: time.sleep(w)
        _last[0] = time.time()

def get(path, params, tries=3):
    for t in range(tries):
        _limiter()
        try:
            r = sess.get(BASE + path, params=params, timeout=15)
            if r.status_code == 429: time.sleep(3 + 3 * t); continue
            r.raise_for_status(); return r.json()
        except Exception:
            if t == tries - 1: raise
            time.sleep(1 + t)

def universe():
    info = get("/api/v3/exchangeInfo", {})
    return [s["symbol"] for s in info["symbols"] if s.get("quoteAsset") == "USDT" and s.get("status") in ("1", "ENABLED")
            and s.get("isSpotTradingAllowed", True) and s["baseAsset"] not in EXCL
            and not s["baseAsset"].endswith(("3L","3S","5L","5S","2L","2S","4L","4S"))]

def candles(sym):
    try:
        o = get("/api/v3/klines", {"symbol": sym, "interval": "60m", "limit": 500})
    except Exception:
        return sym, None
    if not o or len(o) < 300: return sym, None
    arr = np.array([[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])] for k in o[:-1]])  # última vela abierta fuera
    return sym, arr

def load_state():
    if os.path.exists(STATE):
        return json.load(open(STATE))
    return {"equity_eur": CFG.paper_equity, "cash_eur": CFG.paper_equity, "positions": {}, "closed": [], "lessons": [], "cycles": 0}

def manage_positions(state, data):
    closed = []
    for sym in list(state["positions"]):
        p = state["positions"][sym]; arr = data.get(sym)
        if arr is None: continue
        last = arr[-1]; e = p["entry_price"]; reason = None; exit_px = None
        if last[3] <= e * (1 - SL): reason, exit_px = "stop", e * (1 - SL)
        elif last[2] >= e * (1 + TP): reason, exit_px = "objetivo", e * (1 + TP)
        elif time.time() * 1000 - p["opened_ts"] >= MAX_HOURS * 3600e3: reason, exit_px = "caducidad", last[4]
        if not reason: continue
        gross = p["qty"] * exit_px * (1 - CFG.fee_pct / 100)
        pnl = gross - p["cost_eur"]
        rec = {"symbol": sym, "reason": reason, "entry_price": e, "exit_price": exit_px, "pnl_eur": round(pnl, 2),
               "pnl_pct": round(100 * pnl / p["cost_eur"], 2), "opened_ts": p["opened_ts"], "closed_ts": int(time.time() * 1000), "thesis": p.get("thesis", "")}
        state["cash_eur"] = round(state["cash_eur"] + gross, 2)
        del state["positions"][sym]; state["closed"].append(rec); state["closed"] = state["closed"][-300:]; closed.append(rec)
    return closed

def equity(state, data):
    eq = state["cash_eur"]
    for sym, p in state["positions"].items():
        px = data[sym][-1][4] if data.get(sym) is not None else p["entry_price"]
        eq += p["qty"] * px
    state["equity_eur"] = round(eq, 2); return state["equity_eur"]

def main():
    t0 = time.time(); syms = universe()
    data = {}
    with ThreadPoolExecutor(max_workers=12) as pool:
        for sym, arr in pool.map(candles, syms):
            if arr is not None: data[sym] = arr
    print(f"velas: {len(data)}/{len(syms)} pares en {time.time()-t0:.0f}s", flush=True)

    state = load_state(); state["cycles"] += 1
    closed = manage_positions(state, data)

    watch, setups = [], []
    for sym, arr in data.items():
        c, low, v = arr[:, 4], arr[:, 3], arr[:, 5]
        n = len(c)
        vol24 = float((c[-24:] * v[-24:]).sum())
        if vol24 < MIN_VOL24: continue
        r = S.rsi(c)
        divs = [d for d in S.bullish_divergences(low, r, S.pivot_lows(low)) if d[1] == 3 and n - 48 <= d[0] < n]
        if not divs: continue
        latest = max(divs, key=lambda d: d[0])
        watch.append({"symbol": sym, "div3_hours_ago": n - 1 - latest[0], "rsi_pivot": round(latest[2], 1), "vol24": round(vol24), "price": float(c[-1])})
        div_in_24h = any(n - 25 <= d[0] <= n - 1 for d in divs)
        if div_in_24h and S.squeeze_breakout_long(c, v, n - 1):
            setups.append({"symbol": sym, "vol24": round(vol24), "features": S.features(sym, arr, r), "div3_hours_ago": n - 1 - latest[0]})
    watch.sort(key=lambda w: -w["vol24"])
    json.dump({"ts": int(time.time() * 1000), "watch": watch}, open(WATCH, "w"), indent=1)

    eq = equity(state, data); positions = [{"symbol": s, **p} for s, p in state["positions"].items()]
    approved, rejected = [], []
    use_llm = bool(CFG.llm_api_key) or CFG.llm_provider == "mock"
    if setups:
        lessons = state.get("lessons", [])
        if use_llm:
            try:
                lessons = agents.archive(state["closed"], [x for x in _read_setups()[-40:] if x.get("decision") == "reject"]) or lessons
            except Exception as e:
                print("ARCHIVE error", e)
            state["lessons"] = lessons
        for su in setups[:6]:
            sym, f = su["symbol"], su["features"]
            if sym in state["positions"]: continue
            price = f["price"]; stop = price * (1 - SL); target = price * (1 + TP)
            risk_eur = eq * CFG.risk_per_trade_pct / 100
            size = min(risk_eur / SL, eq * CFG.max_position_pct / 100, state["cash_eur"])
            pkg = {"symbol": sym, "probe": {"thesis": f"triple divergencia alcista hace {su['div3_hours_ago']}h + ruptura por compresión con volumen {f['vol_z_1h']}σ", "score": 0.7},
                   "levels": {"entry_type": "market", "stop_price": round(stop, 8), "target_price": round(target, 8), "stop_dist_pct": SL * 100, "rr": round(TP / SL, 2), "max_hold_hours": MAX_HOURS},
                   "features": {k: f[k] for k in f if k != "m15_last8"}, "lessons": lessons,
                   "portfolio": {"equity_eur": eq, "open_positions": positions}, "utc_hour": time.gmtime().tm_hour}
            decision = {"decision": "approve", "conviction": None, "reason": "sin LLM: regla pura"}
            if use_llm:
                try:
                    pr = agents.prism(pkg["probe"], f, lessons); pkg["prism"] = pr
                    if pr["verdict"] != "keep":
                        decision = {"decision": "reject", "conviction": pr["confidence"], "reason": "PRISM: " + pr["reason"]}
                    else:
                        lv = agents.limit(pkg["probe"], f); pkg["limit_note"] = lv["invalidation"]
                        sc = agents.scale(f, eq, positions, SL * 100); size = min(size, sc["position_eur"]) if sc["position_eur"] > 0 else size; pkg["scale"] = sc
                        decision = agents.einstein(pkg)
                except Exception as e:
                    decision = {"decision": "reject", "conviction": 0, "reason": f"error LLM: {str(e)[:120]}"}
            rec = {"ts": int(time.time() * 1000), "symbol": sym, "price": price, "vol24": su["vol24"], "size_eur": round(size, 2),
                   "stop": round(stop, 8), "target": round(target, 8), **decision, "mode": "paper"}
            if decision["decision"] == "approve" and size >= CFG.min_order_eur and len(state["positions"]) < CFG.max_open_positions:
                fee = size * CFG.fee_pct / 100
                state["positions"][sym] = {"qty": (size - fee) / price, "entry_price": price, "cost_eur": round(size, 2), "stop_price": stop, "target_price": target,
                                           "opened_ts": int(time.time() * 1000), "thesis": pkg["probe"]["thesis"], "einstein": decision["reason"]}
                state["cash_eur"] = round(state["cash_eur"] - size, 2); approved.append(rec)
            else:
                if decision["decision"] == "approve":
                    rec["reason"] = "aprobado por EINSTEIN pero sin hueco: " + ("máximo de posiciones" if len(state["positions"]) >= CFG.max_open_positions else "tamaño bajo el mínimo")
                rejected.append(rec)
            with open(SETUPS, "a") as fh: fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    equity(state, data); json.dump(state, open(STATE, "w"), indent=1, ensure_ascii=False)

    # resumen y aviso
    lines = [f"Ciclo {state['cycles']} · {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())} · {len(data)} pares · {time.time()-t0:.0f}s",
             f"Equity paper: {state['equity_eur']:.2f} € · caja {state['cash_eur']:.2f} € · abiertas {len(state['positions'])}",
             f"Vigilancia (DIV3 <48h): {len(watch)} · Setups DIV3→ruptura: {len(setups)} · aprobados {len(approved)} · rechazados {len(rejected)}"]
    for r in approved: lines.append(f"✅ {r['symbol']} @ {r['price']} · {r['size_eur']} € · stop {r['stop']} · obj {r['target']} · {r['reason'][:120]}")
    for r in rejected: lines.append(f"✖ {r['symbol']} @ {r['price']} · {r['reason'][:120]}")
    for c in closed: lines.append(f"⏹ {c['symbol']} cerrada por {c['reason']} {c['pnl_pct']:+.2f}% ({c['pnl_eur']:+.2f} €)")
    lines.append("Vigilancia: " + ", ".join(f"{w['symbol'][:-4]}({w['div3_hours_ago']}h)" for w in watch[:15]))
    text = "\n".join(lines); print(text)
    open(LAST, "w").write("```\n" + text + "\n```\n")
    if approved or closed or os.getenv("NOTIFY_ALWAYS") == "1":
        notify(text)

def _read_setups():
    if not os.path.exists(SETUPS): return []
    return [json.loads(l) for l in open(SETUPS) if l.strip()]

if __name__ == "__main__":
    main()
