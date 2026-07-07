"""
전역 설정값을 .env 에서 읽어온다.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# 디스코드 봇 토큰
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")

# 랭크 데이터 소스: "dakgg"(크롤링) 또는 "official"(공식 오픈 API)
# 나중에 API 키 발급받으면 이 값만 "official" 로 바꾸면 됨.
RANK_SOURCE = os.getenv("RANK_SOURCE", "dakgg").lower()

# 이터널리턴 공식 오픈 API 키 (developer.eternalreturn.io 에서 발급)
OFFICIAL_API_KEY = os.getenv("OFFICIAL_API_KEY", "")

# 관리자 전용 명령을 쓸 수 있는 역할 이름 (없으면 서버 관리자 권한자만 허용)
ADMIN_ROLE_NAME = os.getenv("ADMIN_ROLE_NAME", "")

# 개발/테스트용 서버(길드) ID. 설정하면 그 서버에만 즉시 슬래시 커맨드가 동기화됨
# (전역 동기화는 디스코드 반영까지 최대 1시간 걸릴 수 있어서, 개발 중엔 이 값을 쓰는 걸 추천)
_test_guild_id = os.getenv("TEST_GUILD_ID", "")
TEST_GUILD_ID = int(_test_guild_id) if _test_guild_id.strip() else None

# 맵별 팀 구성 (팀당 인원수, 팀 개수)
MAP_CONFIG = {
    "루미아섬": {"team_size": 3, "team_count": 8},   # 3인 x 8팀 = 24명
    "코발트": {"team_size": 4, "team_count": 2},      # 4인 x 2팀 = 8명
}

# 언랭크(시즌 랭크 기록 없음) 유저에게 부여할 고정 점수
# 아이언 최저 구간보다 낮은 값으로 설정 (실제 최저 RP 값은 시즌마다 다르므로 넉넉히 음수로 설정)
UNRANKED_SCORE = -1000
