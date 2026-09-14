# sixdesk — escáner horario + mesa de seis agentes (MEXC spot, paper)

Cada hora, en la nube de GitHub (gratis, sin servidor tuyo):

1. Baja las últimas 500 velas 1h de todos los pares USDT de MEXC (~1.450 pares, ~100 s).
2. Detecta el setup validado en 56 días: **triple divergencia alcista RSI 1h + ruptura por compresión de volumen** (50% toca +10% antes de -7%, 26% toca +20%).
3. Actualiza posiciones paper abiertas: objetivo +15 %, stop -7 %, máximo 72 h.
4. Pasa cada setup por PRISM → LIMIT → SCALE → EINSTEIN (Qwen por API); ARCHIVE resume lecciones. Si EINSTEIN aprueba, abre posición paper (1 % de riesgo, máx. 25 % del equity, máx. 3 abiertas).
5. Te avisa por Telegram y guarda todo en `data/` (estado, setups, vigilancia, último ciclo).

## Puesta en marcha (desde el navegador, 10 minutos)

**1. Repositorio.** En github.com → New repository → nombre `sixdesk`, **Public** (minutos ilimitados; privado tiene 2.000 min/mes y este job gasta ~2.200). Sube todos los archivos de este zip (Add file → Upload files), incluida la carpeta `.github`.

**2. Secretos.** Settings → Secrets and variables → Actions → New repository secret:
- `DASHSCOPE_API_KEY` — tu clave de Alibaba Cloud Model Studio (Qwen).
- `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` — opcionales (ver abajo).
- `WEBHOOK_URL` — opcional, webhook de Make.com para volcar a Sheets.

Variables opcionales (pestaña Variables): `MODEL_WORKERS`, `MODEL_GATE`, `PAPER_EQUITY`, `MIN_VOL24`, `NOTIFY_ALWAYS=1` para recibir aviso cada hora aunque no haya nada.

**3. Activar.** Pestaña Actions → "sixdesk hourly" → Run workflow. La primera ejecución tarda ~3 min. A partir de ahí corre solo a los 5 minutos de cada hora (UTC). Cada ciclo commitea `data/`; ahí ves el historial completo.

**4. Telegram (2 minutos).** Habla con @BotFather → `/newbot` → copia el token. Escribe cualquier cosa a tu bot, luego abre `https://api.telegram.org/bot<TOKEN>/getUpdates` y copia el `chat.id`.

## Qué verás

- `data/ultimo_ciclo.md`: resumen del último ciclo (equity paper, setups, aprobados, rechazados, lista de vigilancia).
- `data/vigilancia.json`: pares con triple divergencia en las últimas 48 h esperando ruptura.
- `data/setups.jsonl`: cada setup con la decisión de los agentes y el motivo.
- `data/state.json`: posiciones abiertas, cerradas con PnL, caja y lecciones de ARCHIVE.

## Sin clave de Qwen

Si `DASHSCOPE_API_KEY` no está, el sistema funciona en modo regla pura: todo setup se aprueba y se registra en paper. Sirve para acumular track record del setup sin agentes y compararlo después con los agentes.

## Reglas duras (código, no negociables por el modelo)

| | |
|---|---|
| Riesgo por trade | 1 % del equity (`RISK_PER_TRADE_PCT`) |
| Tamaño máximo | 25 % del equity (`MAX_POSITION_PCT`) |
| Posiciones abiertas | 3 (`MAX_OPEN_POSITIONS`) |
| Salida | +15 % / -7 % / 72 h (fijo en `hourly.py`) |
| Convicción mínima EINSTEIN | 0,75 (`MIN_CONVICTION`) |
| Volumen mínimo 24 h | 50.000 $ (`MIN_VOL24`) |

## Pasar a real

No está conectado a ninguna cuenta. Cuando el paper lo justifique, la ejecución real se añade en `hourly.py` donde se abre la posición (orden + stop en el exchange vía API). Primero 30 días de paper.

## Si MEXC bloquea las IPs de GitHub

Verás errores 403 en el log del workflow. Alternativas: apuntar `BASE` a otro exchange con API pública equivalente (OKX: `/api/v5/market/candles`) o ejecutar el job desde otro runner. Avísame y lo adapto.
