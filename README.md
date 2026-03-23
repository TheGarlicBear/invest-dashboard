# invest_dashboard_v5_krx_lookup

개인 투자 판단 보조기 v5

추가된 기능
- KRX 종목명 검색: 국장 종목을 이름 또는 코드로 검색해서 관심 종목에 추가
- CSV 기반 KRX 사전: `data/krx_tickers.csv` 사용
- 선택형 외부 갱신: 사이드바의 `KRX 목록 업데이트` 버튼으로 `pykrx` 기반 갱신 시도
- 종목별 프로필/가중치/점수 기여도 시각화 유지

실행
```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -m streamlit run app.py
```

참고
- 기본 CSV는 자주 보는 국장 종목 중심의 시드 파일이다.
- `KRX 목록 업데이트`를 누르면 가능한 경우 전체 KRX 목록으로 교체된다.
- 업데이트 실패 시 기존 CSV는 그대로 유지된다.


## v6 변경점
- 상단 지표 카드를 기본 `st.metric` 대신 커스텀 카드로 교체해 대비를 높였습니다.
- `.streamlit/config.toml`를 추가해 라이트 테마와 기본 색상을 고정했습니다.
- `.gitignore`를 추가해 `.venv`와 캐시 파일이 GitHub에 올라가지 않도록 정리했습니다.

## GitHub 업로드
```bash
cd invest_dashboard_v5_krx_lookup
git init
git add .
git commit -m "Initial deploy-ready version"
git branch -M main
git remote add origin <YOUR_GITHUB_REPO_URL>
git push -u origin main
```

## Streamlit Community Cloud 배포
1. GitHub에 이 폴더를 올립니다.
2. Streamlit Community Cloud에서 `New app`을 선택합니다.
3. Repository / Branch / Main file path를 각각 선택합니다.
4. Main file path는 `app.py`로 지정합니다.
5. Deploy를 누르면 공개 URL이 생성됩니다.

## 주의
- `data/krx_tickers.csv`는 저장소에 포함되어야 합니다.
- `requirements.txt`는 루트에 있어야 합니다.
- 공개 주소를 알면 다른 사람도 사용할 수 있으므로, 나중에 필요하면 비밀번호 보호를 추가하는 편이 안전합니다.


## 사용자별 관심종목 저장 기능
- 사이드바에서 `사용자 선택` 후 관심종목을 입력합니다.
- `관심종목 저장`을 누르면 `data/watchlists/<사용자>.json`에 저장됩니다.
- 다음 접속 시 같은 사용자를 선택하면 자동으로 불러옵니다.
- `초기화`를 누르면 기본 관심종목으로 되돌린 뒤 즉시 저장합니다.

## 전체 KRX CSV
- `data/krx_tickers.csv`는 전체 KRX 종목 기준 포맷(`name, code, ticker_yf, market`)으로 교체되어 있습니다.
- 국장 종목 검색은 기본적으로 이 CSV를 사용합니다.
- `최신 KRX 목록 갱신(선택)`은 보조 기능입니다. 실패해도 기존 CSV를 계속 사용합니다.
