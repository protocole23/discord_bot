import asyncio
import logging
import os

import discord
from discord.ext import commands
from aiohttp import web

import config
from rank_provider import get_provider

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("er_team_bot")

INTENTS = discord.Intents.default()
INTENTS.members = True  # display_name, roles 접근을 위해 필요 (개발자 포털에서도 켜줘야 함)


class ERTeamBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=INTENTS)
        self.rank_provider = get_provider()

    async def setup_hook(self):
        await self.load_extension("cogs.match_cog")

        if config.TEST_GUILD_ID:
            guild = discord.Object(id=config.TEST_GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info(f"[테스트 서버 즉시 동기화] 슬래시 커맨드 {len(synced)}개 동기화 완료")
        else:
            synced = await self.tree.sync()
            log.info(f"[전역 동기화 - 반영까지 최대 1시간] 슬래시 커맨드 {len(synced)}개 동기화 완료")

    async def close(self):
        await self.rank_provider.close()
        await super().close()


bot = ERTeamBot()


@bot.event
async def on_ready():
    log.info(f"로그인 완료: {bot.user} (데이터 소스: {config.RANK_SOURCE})")


async def start_healthcheck_server():
    """Render 같은 PaaS의 무료 'Web Service'는 일정 시간 HTTP 요청이 없으면 잠들어버림.
    /healthz 하나 열어두고 외부 핑(UptimeRobot 등)으로 깨어있게 유지하기 위한 최소 웹서버.
    PORT 환경변수가 없으면(로컬/VPS/Docker 단독 실행) 그냥 건너뜀."""
    port = os.getenv("PORT")
    if not port:
        return

    app = web.Application()
    app.router.add_get("/healthz", lambda request: web.Response(text="OK"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(port))
    await site.start()
    log.info(f"헬스체크 웹서버 시작됨 (포트 {port}) - Render 등에서 잠들지 않도록 /healthz 로 핑 걸어두세요")


def main():
    if not config.DISCORD_TOKEN:
        raise RuntimeError(".env 에 DISCORD_TOKEN이 설정되어 있지 않습니다.")

    async def runner():
        await start_healthcheck_server()
        async with bot:
            await bot.start(config.DISCORD_TOKEN)

    asyncio.run(runner())


if __name__ == "__main__":
    main()
