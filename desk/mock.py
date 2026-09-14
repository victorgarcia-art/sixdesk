"""Respuestas simuladas por rol. Solo para comprobar la tubería (LLM_PROVIDER=mock)."""


def mock_answer(role: str, p: dict) -> dict:
    if role == "PROBE":
        rows = sorted(p["universe"], key=lambda r: -(r.get("vol_z_1h") or 0))[: p["max_candidates"]]
        return {"candidates": [
            {"symbol": r["symbol"], "score": round(min(1.0, 0.5 + 0.1 * (r.get("vol_z_1h") or 0)), 2),
             "thesis": f"volumen z={r.get('vol_z_1h')} adelanta al precio ({r.get('chg_1h_pct')}% 1h)"}
            for r in rows]}
    if role == "PRISM":
        f = p["features"]
        keep = (f.get("vol_z_1h") or 0) > 1.0 and (f.get("chg_24h_pct") or 0) < 12
        return {"verdict": "keep" if keep else "reject", "confidence": 0.7 if keep else 0.4,
                "reason": "volumen confirma y el movimiento no está agotado" if keep else "sin confirmación de volumen o movimiento ya extendido"}
    if role == "SCALE":
        return {"position_eur": round(p["equity_eur"] * 0.2, 2), "note": "20% del equity, dentro de límites"}
    if role == "LIMIT":
        px, atr = p["price"], (p.get("atr_pct_1h") or 1.0) / 100
        return {"entry_type": "market", "limit_price": None, "stop_price": round(px * (1 - 1.5 * atr), 8),
                "target_price": round(px * (1 + 3 * atr), 8), "max_hold_hours": 24,
                "invalidation": "cierre 1h por debajo de 1.5 ATR desde la entrada"}
    if role == "ARCHIVE":
        return {"lessons": ["(mock) sin histórico suficiente"]}
    if role == "EINSTEIN":
        conf = p["package"]["prism"].get("confidence", 0)
        return {"decision": "approve" if conf >= 0.7 else "reject", "conviction": conf,
                "reason": "mock: aprueba solo si PRISM ≥ 0.7"}
    raise ValueError(role)
