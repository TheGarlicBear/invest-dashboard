# 개인 투자 판단 보조기 v9

이번 버전 추가 사항:
- 사용자별 관심종목 저장 유지
- 전체 KRX 종목 CSV 포함
- 보유 종목 탭 추가
- `data/holdings/master.csv`에 업로드한 보유 종목 기본 반영
- 관심 종목 표에 `보유`, `평균단가 대비(%)` 표시
- 보유 종목 탭에서 `추매점수`, `추매판정` 확인

## 폴더 구조
- `data/krx_tickers.csv`: 전체 KRX 종목 검색용
- `data/watchlists/<user>.json`: 사용자별 관심종목
- `data/holdings/<user>.csv`: 사용자별 보유 종목

## 보유 종목 파일 형식
```csv
ticker,name,avg_price,qty,currency,market,memo
005930.KS,삼성전자,59635,20,KRW,KOSPI,
SOXL,SOXL,32.24,86,USD,US,
```

## 사용자별 보유 종목 반영
- `master`는 현재 업로드된 보유 종목 CSV를 기본 반영
- `wife`는 빈 파일로 시작
- 필요하면 `data/holdings/wife.csv`를 같은 형식으로 채우면 됨


## v11 profile fix
- 화면에 `프로파일키`, `프로파일유형`, 앱 버전이 표시됩니다.
- 개별 종목 카드에 실제 적용된 프로파일 키가 직접 표시됩니다.
