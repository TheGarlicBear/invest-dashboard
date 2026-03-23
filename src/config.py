DEFAULT_TICKERS = [
    "SOXL",
    "QQQ",
    "SCHD",
    "MSFT",
    "NVDA",
    "005930.KS",
    "000660.KS",
]

DEFAULT_PERIOD = "1y"
DEFAULT_INTERVAL = "1d"

PERIOD_OPTIONS = ["6mo", "1y", "2y", "5y"]
INTERVAL_OPTIONS = ["1d", "1wk"]


PROFILE_RULES = {
    "leveraged": {
        "label": "레버리지/고변동",
        "description": "낙폭과 RSI를 더 크게 보며, ATR 패널티는 완화합니다.",
        "keywords": ["SOXL", "TQQQ", "UPRO", "SOXS", "SQQQ"],
        "weights": {
            "RSI14": 1.3,
            "고점 대비 낙폭": 1.5,
            "20일선 대비": 1.1,
            "60일선 대비": 0.8,
            "MACD 히스토그램": 1.0,
            "52주 위치": 1.1,
            "ATR14 변동성": 0.5,
            "거래량 배수": 0.8,
        },
    },
    "dividend": {
        "label": "배당/방어형",
        "description": "중기 추세와 안정성을 더 크게 보며, 과매도 신호는 보조적으로 사용합니다.",
        "keywords": ["SCHD", "VYM", "HDV", "JEPI", "SPYD"],
        "weights": {
            "RSI14": 0.8,
            "고점 대비 낙폭": 1.0,
            "20일선 대비": 0.8,
            "60일선 대비": 1.5,
            "MACD 히스토그램": 0.9,
            "52주 위치": 0.9,
            "ATR14 변동성": 1.4,
            "거래량 배수": 0.6,
        },
    },
    "growth": {
        "label": "대형 성장주",
        "description": "추세와 모멘텀, 거래량을 함께 보며 낙폭도 적절히 반영합니다.",
        "keywords": ["MSFT", "NVDA", "AAPL", "AMZN", "META", "GOOGL", "TSLA"],
        "weights": {
            "RSI14": 1.0,
            "고점 대비 낙폭": 1.1,
            "20일선 대비": 1.0,
            "60일선 대비": 1.3,
            "MACD 히스토그램": 1.2,
            "52주 위치": 1.0,
            "ATR14 변동성": 0.9,
            "거래량 배수": 1.1,
        },
    },
    "korea_semiconductor": {
        "label": "국내 반도체주",
        "description": "낙폭, 거래량, 중기 추세를 같이 보며 과도한 고점 추격을 피하도록 설계합니다.",
        "keywords": ["005930.KS", "000660.KS", "042700.KS"],
        "weights": {
            "RSI14": 1.0,
            "고점 대비 낙폭": 1.3,
            "20일선 대비": 1.0,
            "60일선 대비": 1.2,
            "MACD 히스토그램": 1.0,
            "52주 위치": 1.0,
            "ATR14 변동성": 0.8,
            "거래량 배수": 1.3,
        },
    },
    "default": {
        "label": "기본형",
        "description": "가격 메리트, 추세, 변동성을 균형 있게 반영하는 기본 점수 체계입니다.",
        "keywords": [],
        "weights": {
            "RSI14": 1.0,
            "고점 대비 낙폭": 1.0,
            "20일선 대비": 1.0,
            "60일선 대비": 1.0,
            "MACD 히스토그램": 1.0,
            "52주 위치": 1.0,
            "ATR14 변동성": 1.0,
            "거래량 배수": 1.0,
        },
    },
}

SUMMARY_COLUMNS = [
    "종목",
    "Ticker",
    "프로필",
    "현재가",
    "RSI14",
    "20일선 대비(%)",
    "60일선 대비(%)",
    "고점 대비(%)",
    "52주 위치(%)",
    "MACD 히스토그램",
    "ATR14(%)",
    "거래량 배수",
    "판정",
    "점수",
    "코멘트",
]
