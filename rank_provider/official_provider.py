"""
이터널리턴 공식 오픈 API (developer.eternalreturn.io) Provider

주의: developer.eternalreturn.io 에서 API 키를 발급받은 뒤,
     .env 의 OFFICIAL_API_KEY 와 RANK_SOURCE=official 을 설정하면 이 Provider가 쓰인다.

     API 키 발급 전에는 실제 응답 필드명을 100% 확정할 수 없어서,
     아래 코드는 공식 문서에 나온 모델 구조(사용자번호 조회 -> 시즌 랭크 조회)를 기준으로
     최대한 유연하게 파싱하도록 만들었다. 만약 필드명이 다르면 _pick() 함수에
     실제 필드명만 추가해주면 된다. (developer.eternalreturn.io 문서의
     "Get User Number" / "Get User Rank" 모델 참고)
"""
import aiohttp

from .base import RankProvider, RankResult, RankProviderError

BASE_URL = "https://open-api.bser.io/v1"


def _pick(data: dict, *keys, default=None):
    """응답 JSON에서 여러 후보 키 중 존재하는 첫 값을 반환 (필드명 표기 차이 대비)"""
    for k in keys:
        if k in data and data[k] is not None:
            return data[k]
    return default


class OfficialApiProvider(RankProvider):
    def __init__(self, api_key: str, season_id: int = None):
        self.api_key = api_key
        self.season_id = season_id  # None이면 최신 시즌으로 조회 시도
        self._session: aiohttp.ClientSession = None

    def _headers(self):
        return {"x-api-key": self.api_key}

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

    async def get_rank(self, nickname: str) -> RankResult:
        await self._ensure_session()

        # 1. 닉네임 -> 유저 번호(user_num) 조회
        async with self._session.get(
            f"{BASE_URL}/user/nickname",
            params={"query": nickname},
            headers=self._headers(),
        ) as resp:
            body = await resp.json()
            if resp.status != 200 or body.get("code") != 200:
                raise RankProviderError(f"닉네임 '{nickname}' 조회 실패: {body}")
            user_num = _pick(body.get("user", {}) or body, "userNum", "user_num")
            if user_num is None:
                raise RankProviderError(f"'{nickname}' 의 유저 번호를 찾을 수 없습니다.")

        # 2. 유저 번호 -> 시즌 랭크 조회 (스쿼드 랭크 기준, teamMode 값은 문서 확인 후 조정)
        params = {"userNum": user_num}
        if self.season_id is not None:
            params["seasonID"] = self.season_id

        async with self._session.get(
            f"{BASE_URL}/user/rank",
            params=params,
            headers=self._headers(),
        ) as resp:
            body = await resp.json()
            if resp.status != 200 or body.get("code") != 200:
                # 랭크 기록이 없는 경우 (언랭크) - API가 404/빈 데이터로 응답하는 경우 처리
                return RankResult(nickname=nickname, tier="언랭크", rp=0, is_unranked=True)

            user_rank = body.get("userRank", body)
            rp = _pick(user_rank, "rankPoint", "rp", "mmr", default=None)
            tier = _pick(user_rank, "tierGrade", "tier", default="알수없음")

            if rp is None:
                return RankResult(nickname=nickname, tier="언랭크", rp=0, is_unranked=True)

            return RankResult(nickname=nickname, tier=str(tier), rp=int(rp), is_unranked=False)

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
