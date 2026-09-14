"""Configuración central. Todo se lee de variables de entorno (.env)."""
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


def _b(key: str, default: bool) -> bool:
    v = os.getenv(key)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "si", "sí")


def _f(key: str, default: float) -> float:
    return float(os.getenv(key, default))


def _i(key: str, default: int) -> int:
    return int(os.getenv(key, default))


@dataclass
class Config:
    # --- Modo ---
    paper: bool = _b("PAPER", True)                       # True = simulación, no toca Kraken privado
    kraken_validate: bool = _b("KRAKEN_VALIDATE", True)   # en real: validate=True hace que Kraken compruebe la orden sin ejecutarla
    interval_min: int = _i("INTERVAL_MIN", 30)

    # --- LLM (OpenAI-compatible: DashScope/Qwen, Moonshot/Kimi, OpenAI...) ---
    llm_provider: str = os.getenv("LLM_PROVIDER", "openai_compatible")  # "mock" para pruebas sin clave
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
    llm_api_key: str = os.getenv("LLM_API_KEY", os.getenv("DASHSCOPE_API_KEY", ""))
    model_workers: str = os.getenv("MODEL_WORKERS", "qwen3.7-plus")   # PROBE, PRISM, SCALE, LIMIT, ARCHIVE
    model_gate: str = os.getenv("MODEL_GATE", "qwen3.7-max")          # EINSTEIN
    llm_temperature: float = _f("LLM_TEMPERATURE", 0.2)

    # --- Kraken ---
    kraken_key: str = os.getenv("KRAKEN_API_KEY", "")
    kraken_secret: str = os.getenv("KRAKEN_API_SECRET", "")
    quote: str = os.getenv("QUOTE", "EUR")
    universe_size: int = _i("UNIVERSE_SIZE", 40)
    exclude: list = field(default_factory=lambda: [
        s.strip().upper() for s in os.getenv(
            "EXCLUDE_BASES", "USDC,USDT,EURT,DAI,PYUSD,USDG,USDQ,TUSD,EURQ,EURR,RLUSD,USDS,FDUSD,USDD"
        ).split(",") if s.strip()
    ])

    # --- Riesgo (límites duros aplicados en código, el LLM no puede saltárselos) ---
    paper_equity: float = _f("PAPER_EQUITY", 500.0)
    risk_per_trade_pct: float = _f("RISK_PER_TRADE_PCT", 1.0)     # % del equity que se puede perder si salta el stop
    max_position_pct: float = _f("MAX_POSITION_PCT", 25.0)       # % del equity por posición
    max_open_positions: int = _i("MAX_OPEN_POSITIONS", 3)
    max_stop_atr_mult: float = _f("MAX_STOP_ATR_MULT", 2.5)      # el stop no puede estar a más de N·ATR
    min_conviction: float = _f("MIN_CONVICTION", 0.75)           # EINSTEIN debe superar esto
    fee_pct: float = _f("FEE_PCT", 0.26)                         # taker Kraken spot
    min_order_eur: float = _f("MIN_ORDER_EUR", 10.0)

    # --- Embudo ---
    probe_max: int = _i("PROBE_MAX", 8)

    # --- Persistencia ---
    data_dir: str = os.getenv("DATA_DIR", "./data")
    webhook_url: str = os.getenv("WEBHOOK_URL", "")   # opcional: Make.com → Google Sheets
    requests_trust_env: bool = _b("REQUESTS_TRUST_ENV", False)  # True si hay proxy/CA corporativo


CFG = Config()
