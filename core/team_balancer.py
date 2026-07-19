"""
팀 편성 로직 (랭크 점수 기준 순차 배분 / 랜덤 배분).
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


def rank_draft(applicants: List[Applicant], team_count: int) -> List[Team]:
    """RP 내림차순 정렬 후 1팀→2팀→...→N팀→1팀→2팀... 순서로 순차 배분.
    인원이 팀 개수의 배수가 아니어도, 남는 인원은 항상 1팀부터 순서대로 이어서 배치됨."""
    sorted_applicants = sorted(applicants, key=lambda a: a.rp, reverse=True)
    teams = [Team(index=i, members=[]) for i in range(team_count)]

    for i, applicant in enumerate(sorted_applicants):
        teams[i % team_count].members.append(applicant)

    return teams


def random_draft(applicants: List[Applicant], team_count: int) -> List[Team]:
    """랭크 점수 무시하고 랜덤으로 섞은 뒤 1팀→2팀→...→N팀 순서로 순차 배분.
    (남는 인원 처리 방식은 rank_draft와 동일하게 1팀부터 순서대로)"""
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