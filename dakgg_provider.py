"""
dak.gg 크롤링 Provider (임시용)

주의:
- dak.gg 이터널리턴 페이지는 Next.js 기반이라 순수 requests+HTML 파싱으로는
  RP/티어 값이 안 보인다 (자바스크립트로 클라이언트에서 렌더링됨).
  그래서 Playwright로 실제 브라우저 렌더링 후 텍스트를 읽는 방식으로 만들었다.
- dak.gg 페이지 구조가 바뀌면 파싱이 깨질 수 있음. 그럴 땐 아래 _extract_rank_from_text()
  의 정규식만 손보면 된다. (전체 로직을 바꿀 필요는 없음)
- 이후 공식 API 키를 받으면 official_provider.py 로 교체 (config.py 의 RANK_SOURCE만 변경)
"""
import re
import asyncio
from playwright.async_api import async_playwright, TimeoutError as PWTimeoutError

import config
from .base import RankProvider, RankResult, RankProviderError

DAKGG_URL = "https://dak.gg/er/players/{nickname}?hl=ko&gameMode=RANK"

# dak.gg 상에서 쓰이는 티어 명칭 (한글/영문 둘 다 대비)
TIER_KEYWORDS = [
    "이터니티", "데미갓", "미스릴", "메테오라이트", "다이아몬드", "플래티넘",
    "골드", "실버", "브론즈", "아이언",
    "Eternity", "Demigod", "Mithril", "Meteorite", "Diamond", "Platinum",
    "Gold", "Silver", "Bronze", "Iron",
]

# dak.gg 페이지의 "새로고침" 버튼 후보 텍스트 (실제 확인된 문구를 우선순위로 둠)
REFRESH_BUTTON_TEXTS = ["전적 갱신", "새로고침", "갱신", "Refresh", "Update"]


class DakggProvider(RankProvider):
    def __init__(self):
        self._playwright = None
        self._browser = None
        self._lock = asyncio.Lock()  # 브라우저 인스턴스 동시 접근 방지

    async def _ensure_browser(self):
        if self._browser is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)

    async def get_rank(self, nickname: str) -> RankResult:
        async with self._lock:
            await self._ensure_browser()
            page = await self._browser.new_page()
            try:
                url = DAKGG_URL.format(nickname=nickname)
                # networkidle은 dak.gg의 백그라운드 폴링(광고/분석) 때문에 거의 항상 타임아웃까지
                # 다 채워서 느림. 대신 domcontentloaded만 기다리고, 실제 데이터(RP 텍스트나
                # "찾을 수 없음" 문구)가 화면에 나타날 때까지 짧게 폴링하는 방식으로 바꿈.
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=10000)
                except PWTimeoutError:
                    raise RankProviderError(
                        f"dak.gg 페이지 로딩이 너무 느려서 실패했어요. 잠시 후 다시 시도해주세요. (닉네임: {nickname})"
                    )

                body_text = ""
                for _ in range(20):  # 최대 약 6초 (0.3초 x 20) 폴링
                    body_text = await page.inner_text("body")
                    if re.search(r"[\d,]{2,7}\s*RP", body_text):
                        break
                    if "찾을 수 없" in body_text or "No results" in body_text or "not found" in body_text.lower():
                        break
                    await asyncio.sleep(0.3)

                if "찾을 수 없" in body_text or "No results" in body_text or "not found" in body_text.lower():
                    raise RankProviderError(f"닉네임 '{nickname}' 을(를) dak.gg에서 찾을 수 없습니다.")

                # dak.gg가 캐시해둔 전적이 오래됐을 수 있으므로, 설정이 켜져있으면 "전적 갱신" 버튼을
                # 눌러서 최신화를 시도한다 (최대 몇 초 더 걸림). 꺼져있으면 그냥 현재 텍스트로 진행.
                if config.DAKGG_AUTO_REFRESH:
                    body_text = await self._try_refresh(page, body_text)

                return self._extract_rank_from_text(nickname, body_text)
            finally:
                await page.close()

    async def _try_refresh(self, page, current_text: str) -> str:
        """dak.gg의 '전적 갱신' 버튼을 찾아 눌러서 최신 전적을 다시 가져오도록 시도한다.
        버튼이 없거나, 쿨다운(너무 자주 요청함) 상태거나, 실패하면 원래 텍스트를 그대로 반환.
        """
        cooldown_hints = ["잠시 후", "너무 자주", "이미 최신", "잠시만 기다", "요청 제한"]
        try:
            for label in REFRESH_BUTTON_TEXTS:
                # 1순위: <button> 요소 중 해당 텍스트를 가진 것 (실제 구조: <button class="...">전적 갱신</button>)
                btn = page.get_by_role("button", name=label, exact=False).first
                if await btn.count() == 0:
                    # 2순위: role 매칭 실패 시 일반 텍스트 매칭으로 폴백
                    btn = page.get_by_text(label, exact=False).first
                    if await btn.count() == 0:
                        continue

                try:
                    await btn.click(timeout=2000)
                except Exception:
                    # 버튼이 비활성화(쿨다운)되어 클릭 자체가 안 되는 경우 -> 기존 값 사용
                    continue

                # 갱신은 dak.gg가 실제로 게임 서버에 재조회하는 작업이라 몇 초 걸릴 수 있음.
                # 최대 약 5초간 텍스트 변화(=갱신 완료)를 기다리고, 쿨다운 안내가 뜨면 바로 포기.
                for _ in range(10):  # 최대 약 5초 (0.5초 x 10)
                    await asyncio.sleep(0.5)
                    new_text = await page.inner_text("body")
                    if any(hint in new_text for hint in cooldown_hints):
                        return current_text  # 쿨다운이면 갱신 불가, 기존 값 사용
                    if new_text != current_text:
                        return new_text
                return current_text
        except Exception:
            # 새로고침은 어디까지나 보너스 기능이므로, 실패해도 기존 값으로 계속 진행
            pass
        return current_text

    def _extract_rank_from_text(self, nickname: str, text: str) -> RankResult:
        """
        페이지 전체 텍스트에서 티어명 + RP 숫자를 뽑아낸다.
        예상 형태: "Diamond 3" 근처에 "1,234 RP" 같은 문자열이 존재.
        구조가 바뀌면 이 함수의 정규식만 수정하면 됨.
        """
        # 언랭크 판정
        if re.search(r"Unranked|언랭크|배치\s*미완료", text, re.IGNORECASE):
            return RankResult(nickname=nickname, tier="언랭크", rp=0, is_unranked=True)

        tier_match = None
        for tier in TIER_KEYWORDS:
            m = re.search(rf"{tier}\s*(\d)?", text)
            if m:
                tier_match = m.group(0)
                break

        rp_match = re.search(r"([\d,]{2,7})\s*RP", text)

        if not tier_match or not rp_match:
            raise RankProviderError(
                f"'{nickname}' 의 랭크 정보를 파싱하지 못했습니다. "
                f"dak.gg 페이지 구조가 변경되었을 수 있습니다 (DakggProvider._extract_rank_from_text 확인 필요)."
            )

        rp_value = int(rp_match.group(1).replace(",", ""))
        return RankResult(nickname=nickname, tier=tier_match, rp=rp_value, is_unranked=False)

    async def close(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
