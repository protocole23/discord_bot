"""
서버(길드)별 내전 세션 상태를 메모리에서 관리한다.
봇 재시작 시 초기화됨 (필요하면 나중에 SQLite로 영속화 가능).
"""
import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .team_balancer import Applicant

import config


@dataclass
class MatchSession:
    guild_id: int
    map_name: str          # "루미아섬" or "코발트"
    team_size: int
    team_count: int
    applicants: Dict[int, Applicant] = field(default_factory=dict)  # discord_id -> Applicant
    closed: bool = False
    announce_channel_id: Optional[int] = None  # /내전개설 안내 메시지가 올라간 채널
    announce_message_id: Optional[int] = None  # /내전개설 안내 메시지 ID (인원수 갱신용으로 수정함)

    team_assignment: Optional[Dict[int, int]] = None  # discord_id -> team_index (팀편성 후 저장, 수동이동에 사용)
    balance_method: Optional[str] = None              # "random" 또는 "rank" (다시 편성할 때 같은 방식 재사용)
    team_channel_id: Optional[int] = None             # 팀편성 결과 메시지 채널
    team_message_id: Optional[int] = None             # 팀편성 결과 메시지 ID (재편성/수동이동 시 수정용)

    effective_team_size: Optional[int] = None   # 루미아섬 솔로(1)/듀오(2)/스쿼드(3) 선택값. None이면 team_size 기본값 사용
    formed_team_count: Optional[int] = None     # 마지막으로 편성했을 때 실제 사용된 팀 개수 (수동이동 범위 검증 등에 사용)

    scheduled_time: Optional[datetime.datetime] = None  # 내전 시작 예정 시각 (KST, tz-aware)
    reminder_minutes: Optional[int] = None              # 시작 몇 분 전에 알림 보낼지
    reminder_sent: bool = False                          # 알림 중복 발송 방지
    discord_event_id: Optional[int] = None               # 디스코드 자체 일정(이벤트) ID
    reminder_channel_id: Optional[int] = None             # 알림 메시지가 올라간 채널 (취소/종료 시 삭제용)
    reminder_message_id: Optional[int] = None             # 알림 메시지 ID (취소/종료 시 삭제용)
    start_notified: bool = False                           # 내전 시작 시각 알림 중복 발송 방지
    start_channel_id: Optional[int] = None                 # 내전 시작 알림 메시지 채널 (취소/종료 시 삭제용)
    start_message_id: Optional[int] = None                 # 내전 시작 알림 메시지 ID (취소/종료 시 삭제용)

    @property
    def capacity(self) -> int:
        return self.team_size * self.team_count

    @property
    def current_count(self) -> int:
        return len(self.applicants)

    @property
    def is_full(self) -> bool:
        return self.current_count >= self.capacity


class MatchSessionManager:
    def __init__(self):
        self._sessions: Dict[int, MatchSession] = {}

    def get(self, guild_id: int) -> Optional[MatchSession]:
        return self._sessions.get(guild_id)

    def create(self, guild_id: int, map_name: str) -> MatchSession:
        if map_name not in config.MAP_CONFIG:
            raise ValueError(f"알 수 없는 맵입니다: {map_name}")
        cfg = config.MAP_CONFIG[map_name]
        session = MatchSession(
            guild_id=guild_id,
            map_name=map_name,
            team_size=cfg["team_size"],
            team_count=cfg["team_count"],
        )
        self._sessions[guild_id] = session
        return session

    def cancel(self, guild_id: int):
        self._sessions.pop(guild_id, None)

    def all_sessions(self) -> List[MatchSession]:
        return list(self._sessions.values())


# 전역 세션 매니저 (봇 프로세스 내에서 공유)
session_manager = MatchSessionManager()
