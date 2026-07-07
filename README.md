# 이터널리턴 내전 팀편성 디스코드 봇

신청자의 이터널리턴 랭크(RP)를 조회해서, 맵에 맞는 인원수로 랭크 밸런스 팀을 자동 편성하는 봇.

## 1. 설치

```bash
cd er_team_bot
python -m venv venv
source venv/bin/activate   # Windows는 venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium   # dak.gg 크롤링용 브라우저 설치 (최초 1회)
```

## 2. 설정

`.env.example` 을 복사해서 `.env` 로 만들고 값을 채운다.

```bash
cp .env.example .env
```

- `DISCORD_TOKEN`: [Discord Developer Portal](https://discord.com/developers/applications) 에서 봇 생성 후 발급.
  - Bot 탭에서 `Server Members Intent` 를 켜야 한다 (닉네임/역할 조회용).
  - OAuth2 > URL Generator 에서 `bot`, `applications.commands` 스코프 체크 후 서버에 초대.
- `RANK_SOURCE`: 처음엔 `dakgg` 로 두고, 나중에 공식 API 키 받으면 `official` 로 변경.
- `ADMIN_ROLE_NAME`: 내전 개설/취소 권한을 줄 역할 이름. 비워두면 "서버 관리" 권한 보유자만 가능.

## 3. 실행

```bash
python bot.py
```

## 4. 명령어

| 명령어 | 권한 | 설명 |
|---|---|---|
| `/내전개설 맵:루미아섬\|코발트` | 관리자 | 내전 신청 시작 (정원 자동 계산) |
| `/내전신청 닉네임:...` | 전체 | 신청 (랭크 자동 조회). 정원 차면 자동 마감+팀편성 |
| `/신청취소` | 본인 | 내 신청 취소 |
| `/내전취소` | 관리자 | 진행 중인 내전 취소 (인원 부족할 때 등) |

## 5. 맵별 정원

- 루미아섬: 3인 x 8팀 = 24명
- 코발트: 4인 x 2팀 = 8명

## 6. 팀 편성 방식

RP(랭크 포인트) 내림차순 정렬 후 **스네이크 드래프트** 방식으로 배분한다.
(1팀→2팀→...→N팀→N팀→...→2팀→1팀 순서로 반복 배분 → 팀별 RP 합계가 최대한 균등해짐)

언랭크(시즌 기록 없음) 유저는 최저 티어보다 낮은 고정 점수(`config.py`의 `UNRANKED_SCORE`)를 받는다.

## 7. ⚠️ dak.gg 크롤링(DakggProvider)에 대한 중요 안내

dak.gg의 이터널리턴 페이지는 자바스크립트로 렌더링되는 구조라서, 단순 HTML 요청으로는
RP/티어 값을 가져올 수 없다. 그래서 Playwright로 실제 브라우저를 띄워 렌더링된 텍스트를
읽는 방식(`rank_provider/dakgg_provider.py`)으로 만들어뒀다.

**직접 확인이 필요한 부분:**
- dak.gg는 비공식 사이트라 자체 API를 안 열어주고, 페이지 구조도 예고 없이 바뀔 수 있다.
- `_extract_rank_from_text()` 의 정규식은 일반적인 "티어명 + 숫자 RP" 패턴을 가정하고 작성한 것이라,
  실제 페이지에서 안 맞을 수 있다. 봇을 처음 돌려보고 랭크 조회가 실패하면:
  1. 브라우저 개발자도구(F12) → Network 탭에서 `dak.gg/er/players/{닉네임}` 접속 후
     실제 표시되는 티어/RP 텍스트 형식을 확인
  2. `dakgg_provider.py` 의 `TIER_KEYWORDS` 나 정규식 부분만 수정하면 됨 (다른 파일은 안 건드려도 됨)
- 이 크롤링 방식은 **임시용**이다. 이터널리턴 공식 오픈 API 키를 받으면
  `.env` 의 `RANK_SOURCE=official` 로 바꾸는 것만으로 `OfficialApiProvider` 로 전환된다.

## 8. 공식 API로 전환 시 참고

`rank_provider/official_provider.py` 는 developer.eternalreturn.io 문서의
"Get User Number" / "Get User Rank" 모델 구조를 기준으로 작성했다.
실제 키 발급 후 응답 JSON의 필드명이 코드와 다르면 `_pick()` 호출 부분에
실제 필드명만 추가해주면 된다 (로직 자체는 안 건드려도 됨).

## 9. 향후 확장 아이디어

- 신청 인원/세션을 SQLite로 영속화 (봇 재시작 시에도 유지)
- 코드 관리(`tb_code`) 방식처럼 맵/정원 설정을 DB화해서 관리자가 직접 추가 가능하게
- 팀 편성 결과를 역할 지급 + 음성채널 자동 이동과 연동
