from __future__ import annotations

from typing import Tuple

def decide_final_action(structure_label: str, profit_label: str, add_label: str) -> Tuple[str, str]:
    if structure_label == '구조 훼손':
        return 'STOP', '구조 훼손 우선. 추매보다 손절/축소 검토'
    if profit_label in {'일부축소 우선', '분할익절 검토'}:
        return 'TAKE_PROFIT', '수익 보호 우선. 분할 익절 검토'
    if structure_label in {'축소 후보', '경고'}:
        return 'WATCH', '손절선 인접 또는 구조 약화. 관찰 우선'
    if add_label in {'2차 추매 후보', '1차 추매 후보'}:
        return 'ADD', '구조 훼손은 아니며 가격 메리트 구간'
    return 'HOLD', '추가 행동보다 기존 보유 유지'
