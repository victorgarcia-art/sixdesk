"""Los seis agentes. Cada uno hace una sola cosa y devuelve JSON.

PROBE    → encuentra ideas (volumen que se mueve antes que el precio)
PRISM    → comprueba quién ha pagado el pico y si el movimiento ya está agotado
SCALE    → dimensiona en euros lo que queda
LIMIT    → define dónde deja de ser un trade (stop, objetivo, caducidad)
ARCHIVE  → memoria: resume lo que el resto olvidó
EINSTEIN → la puerta: veto final, solo pasan ideas de alta convicción

Las reglas de riesgo se aplican en código (clamp), nunca se delegan al modelo.
"""
from .config import CFG
from .llm import ask_json

_COMMON = (
    "Eres un agente de una mesa de trading de criptomonedas spot en Kraken (solo posiciones largas, sin apalancamiento). "
    "Actúas sobre datos numéricos que se te pasan en JSON; no inventes datos. "
    "La mesa está diseñada para rechazar casi todo: ante la duda, rechaza. "
    "Escribe los campos de texto en español, cortos."
)

PROBE_SYS = _COMMON + f"""
ROL: PROBE. Recibes una tabla de pares con precio, cambios %, z-score de volumen de la última hora (vol_z_1h) frente a las 48 horas previas, posición en el rango 24h, ATR%, RSI y spread.
Busca VOLUMEN QUE SE MUEVE ANTES QUE EL PRECIO: vol_z_1h alto (≥1.5) con cambio de precio todavía moderado, spread bajo, no en sobrecompra extrema.
Descarta pares con spread_pct > 0.5, RSI > 78 o chg_24h_pct > 15 (ya se ha ido).
Devuelve como máximo {CFG.probe_max} candidatos, ordenados por score (0-1).
Formato: {{"candidates":[{{"symbol":"XXX/EUR","score":0.0,"thesis":"..."}}]}}
Si no hay nada que cumpla, devuelve {{"candidates":[]}}.
"""

PRISM_SYS = _COMMON + """
ROL: PRISM. Recibes UN candidato con su tesis y sus features, incluidas las últimas 8 velas de 15m como [cierre, volumen_en_euros].
Comprueba QUIÉN HA PAGADO EL PICO: ¿el volumen es sostenido en varias velas o es una sola vela (posible barrido/liquidación)? ¿El precio acompaña o ya se ha extendido? ¿La vela previa (vol_z_prev_1h) también era alta (persistencia) o es ruido?
Rechaza si: el volumen es de una sola vela y el precio ya subió >4% en 1h; el RSI > 75; el rango 24h está en máximos (range_pos_24h > 0.9) sin nueva entrada de volumen; el spread es alto.
Formato: {"verdict":"keep"|"reject","confidence":0.0,"reason":"..."}
"""

SCALE_SYS = _COMMON + """
ROL: SCALE. Haces la cuenta del dinero. Recibes equity, posiciones abiertas, riesgo máximo por trade en euros y la volatilidad (ATR%).
Propón el tamaño de la posición en euros: más pequeño cuanto mayor sea el ATR% y cuanto más expuesta esté ya la cartera. Nunca propongas más de max_position_eur.
Formato: {"position_eur":0.0,"note":"..."}
"""

LIMIT_SYS = _COMMON + """
ROL: LIMIT. Marcas dónde el trade deja de ser un trade. Recibes el candidato, precio actual y ATR%.
Define: stop_price (por debajo del precio, entre 1 y 2.5 ATR), target_price (al menos 2x la distancia del stop), tipo de entrada ("market" o "limit" con limit_price ≤ precio actual), max_hold_hours (4-48) y la invalidación en una frase.
Formato: {"entry_type":"market"|"limit","limit_price":null|0.0,"stop_price":0.0,"target_price":0.0,"max_hold_hours":0,"invalidation":"..."}
"""

ARCHIVE_SYS = _COMMON + """
ROL: ARCHIVE. Eres la memoria de la mesa. Recibes los últimos trades cerrados (con resultado) y las últimas ideas rechazadas por etapa.
Extrae 3-6 lecciones operativas, concretas y verificables, que el resto de agentes deba tener en cuenta hoy (p. ej. "los picos de volumen en pares con vol_24h < 200k € han acabado en stop 4 de 5 veces").
Formato: {"lessons":["...","..."]}
"""

EINSTEIN_SYS = _COMMON + f"""
ROL: EINSTEIN. Eres la puerta. Recibes el paquete completo de un trade (tesis de PROBE, veredicto de PRISM, tamaño de SCALE, niveles de LIMIT, lecciones de ARCHIVE y estado de la cartera).
Tu trabajo es ENCONTRAR LA RAZÓN PARA NO HACERLO. Revisa: ¿la tesis y el veredicto se contradicen? ¿el ratio objetivo/stop es < 2? ¿alguna lección de ARCHIVE aplica? ¿la cartera ya está concentrada? ¿es una hora de mercado ilíquida? ¿la tesis es genérica y no numérica?
Solo apruebas con convicción ≥ {CFG.min_conviction}. Aprobar debe ser raro.
Formato: {{"decision":"approve"|"reject","conviction":0.0,"reason":"..."}}
"""


# ----------------------------------------------------------------- llamadas

def probe(universe_rows: list[dict]) -> list[dict]:
    out = ask_json("PROBE", PROBE_SYS, {"universe": universe_rows, "max_candidates": CFG.probe_max}, CFG.model_workers)
    cands = out.get("candidates", [])[: CFG.probe_max]
    valid = {r["symbol"] for r in universe_rows}
    return [c for c in cands if c.get("symbol") in valid]


def prism(candidate: dict, feats: dict, lessons: list[str]) -> dict:
    out = ask_json("PRISM", PRISM_SYS, {"candidate": candidate, "features": feats, "lessons": lessons}, CFG.model_workers)
    out["verdict"] = "keep" if str(out.get("verdict", "")).lower() == "keep" else "reject"
    out["confidence"] = float(out.get("confidence", 0) or 0)
    return out


def scale(feats: dict, equity: float, positions: list[dict], stop_dist_pct: float) -> dict:
    max_pos = equity * CFG.max_position_pct / 100
    risk_eur = equity * CFG.risk_per_trade_pct / 100
    # tamaño máximo tal que si salta el stop se pierde como mucho risk_eur
    risk_cap = risk_eur / (stop_dist_pct / 100) if stop_dist_pct > 0 else max_pos
    hard_cap = min(max_pos, risk_cap)
    out = ask_json("SCALE", SCALE_SYS, {
        "features": {k: feats[k] for k in ("symbol", "price", "atr_pct_1h", "spread_pct")},
        "equity_eur": equity, "open_positions": positions,
        "risk_per_trade_eur": round(risk_eur, 2), "stop_distance_pct": stop_dist_pct,
        "max_position_eur": round(hard_cap, 2),
    }, CFG.model_workers)
    pos = float(out.get("position_eur", 0) or 0)
    out["position_eur"] = round(max(0.0, min(pos, hard_cap)), 2)   # clamp duro
    out["hard_cap_eur"] = round(hard_cap, 2)
    return out


def limit(candidate: dict, feats: dict) -> dict:
    px, atr = feats["price"], (feats.get("atr_pct_1h") or 1.0) / 100
    out = ask_json("LIMIT", LIMIT_SYS, {"candidate": candidate, "price": px, "atr_pct_1h": feats.get("atr_pct_1h"),
                                        "m15_last8": feats.get("m15_last8")}, CFG.model_workers)
    stop = float(out.get("stop_price") or 0)
    tgt = float(out.get("target_price") or 0)
    # guardarraíles: stop dentro de [0.5, max_stop_atr_mult] ATR bajo el precio, objetivo ≥ 2R
    lo, hi = px * (1 - CFG.max_stop_atr_mult * atr), px * (1 - 0.5 * atr)
    stop = min(max(stop, lo), hi) if stop > 0 else px * (1 - 1.5 * atr)
    r = px - stop
    if tgt < px + 2 * r:
        tgt = px + 2 * r
    entry_type = "limit" if str(out.get("entry_type", "market")).lower() == "limit" and out.get("limit_price") else "market"
    lp = float(out["limit_price"]) if entry_type == "limit" else None
    if lp is not None and lp > px:
        entry_type, lp = "market", None
    hold = int(out.get("max_hold_hours") or 24)
    return {
        "entry_type": entry_type, "limit_price": lp,
        "stop_price": round(stop, 8), "target_price": round(tgt, 8),
        "stop_dist_pct": round(100 * r / px, 3), "rr": round((tgt - px) / r, 2) if r > 0 else None,
        "max_hold_hours": max(4, min(hold, 48)),
        "invalidation": str(out.get("invalidation", ""))[:200],
    }


def archive(closed_trades: list[dict], rejected: list[dict]) -> list[str]:
    if not closed_trades and not rejected:
        return []
    out = ask_json("ARCHIVE", ARCHIVE_SYS, {"closed_trades": closed_trades[-20:], "rejected_recent": rejected[-40:]}, CFG.model_workers)
    return [str(x)[:200] for x in out.get("lessons", [])][:6]


def einstein(package: dict) -> dict:
    out = ask_json("EINSTEIN", EINSTEIN_SYS, {"package": package, "min_conviction": CFG.min_conviction}, CFG.model_gate)
    conv = float(out.get("conviction", 0) or 0)
    approve = str(out.get("decision", "")).lower() == "approve" and conv >= CFG.min_conviction
    return {"decision": "approve" if approve else "reject", "conviction": conv, "reason": str(out.get("reason", ""))[:300]}
