from .base import RankProvider, RankResult, RankProviderError
from .dakgg_provider import DakggProvider
from .official_provider import OfficialApiProvider

import config


def get_provider() -> RankProvider:
    """config.RANK_SOURCE 값에 따라 알맞은 Provider 인스턴스를 반환"""
    if config.RANK_SOURCE == "official":
        if not config.OFFICIAL_API_KEY:
            raise RuntimeError("RANK_SOURCE=official 인데 OFFICIAL_API_KEY가 비어있습니다. .env 확인해주세요.")
        return OfficialApiProvider(api_key=config.OFFICIAL_API_KEY)
    return DakggProvider()
