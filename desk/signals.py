"""Detección de señales sobre velas 1h (numpy). Misma lógica validada en el escáner de 56 días."""
import numpy as np

W = 5            # ventana de pivote
MAX_SPAN = 72    # barras máximas entre pivotes de una divergencia


def rsi(c, n=14):
    d = np.diff(c, prepend=c[0])
    up, dn = np.maximum(d, 0), np.maximum(-d, 0)
    au, ad = np.zeros_like(c), np.zeros_like(c)
    au[n] = up[1:n + 1].mean(); ad[n] = dn[1:n + 1].mean()
    for i in range(n + 1, len(c)):
        au[i] = (au[i - 1] * (n - 1) + up[i]) / n
        ad[i] = (ad[i - 1] * (n - 1) + dn[i]) / n
    out = np.full_like(c, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = au / ad
        out[n:] = np.where(ad[n:] == 0, 100.0, 100 - 100 / (1 + rs[n:]))
    return out


def pivot_lows(x, w=W):
    return [i for i in range(w, len(x) - w)
            if x[i] == x[i - w:i + w + 1].min() and (x[i - w:i + w + 1] == x[i]).sum() == 1]


def bullish_divergences(low, r, piv):
    """Lista de (barra_confirmacion, grado, rsi_pivote). Grado 3 = triple divergencia."""
    out, chain = [], 1
    for k in range(1, len(piv)):
        a, b = piv[k - 1], piv[k]
        if b - a > MAX_SPAN or np.isnan(r[a]) or np.isnan(r[b]):
            chain = 1; continue
        ok = low[b] < low[a] and r[b] > r[a] and r[a] < 45
        chain = chain + 1 if ok else 1
        if chain >= 2:
            out.append((b + W, min(chain, 3), float(r[b])))
    return out


def squeeze_breakout_long(c, v, i, n=20, look=240, pct=20):
    """True si en la barra i hay ruptura alcista tras compresión de Bollinger con volumen ≥2x."""
    if i < look + n:
        return False
    seg = c[i - look - n:i + 1]
    ma = np.convolve(seg, np.ones(n) / n, mode="full")[: len(seg)]
    sd = np.array([seg[max(0, k - n + 1):k + 1].std() for k in range(len(seg))])
    with np.errstate(divide="ignore", invalid="ignore"):
        bw = np.where(ma > 0, 4 * sd / np.where(ma == 0, 1, ma), np.nan)
    j = len(seg) - 1
    thr = np.nanpercentile(bw[j - look:j], pct)
    if not (np.nanmin(bw[j - 12:j]) <= thr):
        return False
    upper_prev = ma[j - 1] + 2 * sd[j - 1]
    vma_prev = v[i - n:i].mean()
    return bool(c[i] > upper_prev and vma_prev > 0 and v[i] >= 2 * vma_prev)


def atr_pct(arr, n=14):
    trs = [max(arr[k][2] - arr[k][3], abs(arr[k][2] - arr[k - 1][4]), abs(arr[k][3] - arr[k - 1][4])) for k in range(-n, 0)]
    return round(100 * (sum(trs) / n) / arr[-1][4], 3)


def features(sym, arr, r):
    """Features compactas para los agentes (mismo formato que la mesa)."""
    c, v = arr[:, 4], arr[:, 5]
    last = c[-1]
    volq = c * v
    prior = volq[-49:-1]
    mu, sd = prior.mean(), prior.std() or 1e-9
    hi24, lo24 = arr[-24:, 2].max(), arr[-24:, 3].min()
    return {
        "symbol": sym, "price": float(last),
        "chg_1h_pct": round(100 * (last / c[-2] - 1), 2),
        "chg_4h_pct": round(100 * (last / c[-5] - 1), 2),
        "chg_24h_pct": round(100 * (last / c[-25] - 1), 2),
        "vol_z_1h": round(float((volq[-1] - mu) / sd), 2),
        "vol_z_prev_1h": round(float((volq[-2] - mu) / sd), 2),
        "vol_24h_quote": round(float(volq[-24:].sum())),
        "range_pos_24h": round(float((last - lo24) / (hi24 - lo24)), 2) if hi24 > lo24 else None,
        "atr_pct_1h": atr_pct(arr), "rsi14_1h": round(float(r[-1]), 1), "spread_pct": None,
        "m15_last8": [[float(round(x[4], 10)), round(float(x[4] * x[5]))] for x in arr[-8:]],
    }
