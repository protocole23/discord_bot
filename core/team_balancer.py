"""
팀 편성 로직 (랭크 점수 기준 스네이크 드래프트 / 랜덤 배분).
"""
import random
from dataclasses import dataclass
from typing import Dict, List


@dataclass
class Applicant:
    discord_id: int
    display_name: str
    nickname: str
    tier: str
    rp: int


@dataclass
class Team:
    index: int
    members: List[Applicant]

    @property
    def total_rp(self) -> int:
        return sum(m.rp for m in self.members)

    @property
    def avg_rp(self) -> float:
        return self.total_rp / len(self.members) if self.members else 0


def snake_draft(applicants: List[Applicant], team_count: int) -> List[Team]:
    """RP 내림차순 정렬 후 스네이크 순서로 팀에 배분 (원리: 1→N→N→1 반복 배분 → 팀별 RP 합산이 최대한 비슷해짐)"""
    sorted_applicants = sorted(applicants, key=lambda a: a.rp, reverse=True)
    teams = [Team(index=i, members=[]) for i in range(team_count)]

    order = list(range(team_count))
    idx = 0
    for applicant in sorted_applicants:
        team_i = order[idx]
        teams[team_i].members.append(applicant)

        idx += 1
        if idx == team_count:
            idx = 0
            order.reverse()  # 스네이크: 방향 반전

    return teams


def random_draft(applicants: List[Applicant], team_count: int) -> List[Team]:
    """랭크 점수 무시하고 랜덤으로 섞어서 균등하게 배분 (인원수만 최대한 고르게 맞춤)"""
    shuffled = list(applicants)
    random.shuffle(shuffled)
    teams = [Team(index=i, members=[]) for i in range(team_count)]

    for i, applicant in enumerate(shuffled):
        teams[i % team_count].members.append(applicant)

    return teams


def teams_to_assignment(teams: List[Team]) -> Dict[int, int]:
    """Team 리스트 -> {discord_id: team_index} 매핑으로 변환 (수동 편집/저장용)"""
    assignment: Dict[int, int] = {}
    for team in teams:
        for member in team.members:
            assignment[member.discord_id] = team.index
    return assignment


def assignment_to_teams(
    assignment: Dict[int, int], applicants: Dict[int, Applicant], team_count: int
) -> List[Team]:
    """{discord_id: team_index} 매핑 -> Team 리스트로 변환 (렌더링용)"""
    teams = [Team(index=i, members=[]) for i in range(team_count)]
    for discord_id, team_idx in assignment.items():
        applicant = applicants.get(discord_id)
        if applicant is not None and 0 <= team_idx < team_count:
            teams[team_idx].members.append(applicant)
    return teams
