"""
랭크 데이터 소스를 추상화하는 인터페이스.

지금은 dak.gg 크롤링(DakggProvider)을 쓰지만,
공식 API 키를 발급받으면 OfficialApiProvider 로 교체할 수 있도록
같은 인터페이스(get_rank)를 따르게 만든다.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class RankResult:
    nickname: str          # 실제(정규화된) 닉네임
    tier: str               # 예: "다이아몬드 3", "언랭크"
    rp: int                 # 랭크 포인트 (팀 편성 점수 기준값)
    is_unranked: bool = False


class RankProviderError(Exception):
    """닉네임을 못찾거나 파싱에 실패했을 때 발생시키는 예외"""
    pass


class RankProvider:
    """모든 Provider가 구현해야 하는 인터페이스"""

    async def get_rank(self, nickname: str) -> RankResult:
        raise NotImplementedError

    async def close(self):
        """세션/브라우저 등 자원 정리. 필요 없으면 그냥 pass"""
        pass
