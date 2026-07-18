import datetime
import logging
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from core.match_session import session_manager, MatchSession
from core.team_balancer import (
    Applicant,
    snake_draft,
    random_draft,
    teams_to_assignment,
    assignment_to_teams,
)
from rank_provider.base import RankProviderError

log = logging.getLogger("er_team_bot.match_cog")

KST = ZoneInfo("Asia/Seoul")

METHOD_LABELS = {"rank": "티어순 (RP 기준)", "random": "랜덤"}
MODE_LABELS = {1: "솔로 (1인)", 2: "듀오 (2인)", 3: "스쿼드 (3인)"}


def parse_schedule(date_str: str, time_str: str) -> datetime.datetime:
    """'07/10', '20:00' 같은 입력을 KST 기준 datetime으로 변환.
    구분자는 '/', '-', '.' 다 허용. 연도는 생략하고 월/일만 입력.
    이미 지난 날짜면 내년으로 자동 보정."""
    normalized_date = date_str.replace(".", "/").replace("-", "/").strip()
    normalized_time = time_str.replace(".", ":").strip()

    month_str, day_str = normalized_date.split("/")
    hour_str, minute_str = normalized_time.split(":")

    now = datetime.datetime.now(KST)
    dt = datetime.datetime(
        year=now.year, month=int(month_str), day=int(day_str),
        hour=int(hour_str), minute=int(minute_str), tzinfo=KST,
    )
    # 이미 1시간 이상 지난 시점이면 내년으로 간주 (연말/연초 내전 대비)
    if dt < now - datetime.timedelta(hours=1):
        dt = dt.replace(year=now.year + 1)
    return dt


def is_admin(interaction: discord.Interaction) -> bool:
    if config.ADMIN_ROLE_NAME:
        return any(r.name == config.ADMIN_ROLE_NAME for r in interaction.user.roles)
    return interaction.user.guild_permissions.manage_guild


def build_open_embed(session: MatchSession) -> discord.Embed:
    """/내전개설 안내 임베드를 세션의 현재 상태 기준으로 새로 만든다 (인원수 갱신용)"""
    embed = discord.Embed(
        title=f"🎮 내전 신청 중 - {session.map_name}",
        description=(
            f"**{session.map_name}는 {session.capacity}명 모집중**\n\n"
            f"`/내전신청 닉네임:본인 이터널리턴 닉네임` 으로 신청해주세요.\n"
            f"인원이 모이면 이 메시지의 **팀편성 버튼**을 눌러 팀을 나눌 수 있어요."
        ),
        color=discord.Color.blue() if not session.is_full else discord.Color.gold(),
    )

    if session.scheduled_time:
        ts = int(session.scheduled_time.timestamp())
        reminder_note = f" (시작 {session.reminder_minutes}분 전 신청자 전원 알림 예정)" if session.reminder_minutes else ""
        embed.add_field(
            name="🕒 시작 예정",
            value=f"<t:{ts}:F> (<t:{ts}:R>){reminder_note}",
            inline=False,
        )

    if session.applicants:
        names = ", ".join(a.nickname for a in session.applicants.values())
        embed.add_field(name="현재 신청자", value=names, inline=False)

    status = f"현재 인원: {session.current_count}/{session.capacity}"
    if session.is_full:
        status += " — 정원 도달! 아래 버튼으로 팀편성 해보세요."
    embed.set_footer(text=status)
    return embed


async def refresh_announce_message(bot: commands.Bot, session: MatchSession):
    """/내전개설 때 올라간 안내 메시지를 최신 인원수로 수정한다"""
    if not session.announce_channel_id or not session.announce_message_id:
        return
    try:
        channel = bot.get_channel(session.announce_channel_id) or await bot.fetch_channel(session.announce_channel_id)
        message = await channel.fetch_message(session.announce_message_id)
        await message.edit(embed=build_open_embed(session))
    except discord.HTTPException:
        pass  # 메시지가 지워졌거나 접근 못하면 그냥 무시 (핵심 기능 아님)


def regenerate_assignment(session: MatchSession):
    """session.balance_method 에 맞는 방식으로 팀을 다시 짜서 session.team_assignment 를 갱신한다.
    팀 개수는 신청 인원을 팀당 인원수로 나눈 올림값으로 동적 계산하되, 맵 최대 팀 수(session.team_count)를 넘지 않는다.
    예) 루미아섬 스쿼드(3인): 7명 -> ceil(7/3)=3팀, 24명 -> ceil(24/3)=8팀
    모드(솔로/듀오/스쿼드)는 팀당 인원수(team_size)와 정원(capacity)에 영향을 준다."""
    import math

    applicants = list(session.applicants.values())
    team_size = session.effective_team_size or session.team_size
    if applicants:
        team_count = min(math.ceil(len(applicants) / team_size), session.team_count)
    else:
        team_count = 1
    session.formed_team_count = team_count

    if session.balance_method == "random":
        teams = random_draft(applicants, team_count)
    else:
        teams = snake_draft(applicants, team_count)
    session.team_assignment = teams_to_assignment(teams)


def build_team_embed(session: MatchSession) -> discord.Embed:
    """session.team_assignment 기준으로 팀편성 결과 임베드를 만든다"""
    team_count = session.formed_team_count or session.team_count
    teams = assignment_to_teams(session.team_assignment, session.applicants, team_count)
    method_label = METHOD_LABELS.get(session.balance_method, session.balance_method)

    team_size = session.effective_team_size or session.team_size
    mode_label = MODE_LABELS.get(team_size, f"{team_size}인")

    embed = discord.Embed(
        title=f"🧩 팀 편성 - {session.map_name} ({session.current_count}명, {mode_label}, 방식: {method_label})",
        color=discord.Color.blue(),
    )
    for team in teams:
        member_lines = "\n".join(f"- {m.nickname} ({m.tier}, {m.rp}RP)" for m in team.members)
        embed.add_field(
            name=f"팀 {team.index + 1} (합계 {team.total_rp} RP / 평균 {team.avg_rp:.0f})",
            value=member_lines or "-",
            inline=False,
        )

    embed.set_footer(
        text="🔀 다시 편성 / ❌ 편성 취소 버튼 사용 가능 / /수동이동 으로 개별 조정 가능"
    )
    return embed


async def update_team_message(bot: commands.Bot, session: MatchSession):
    """팀편성 결과 메시지를 최신 상태로 다시 그린다 (버튼/명령어로 바뀐 뒤 호출)"""
    if not session.team_channel_id or not session.team_message_id:
        return
    try:
        channel = bot.get_channel(session.team_channel_id) or await bot.fetch_channel(session.team_channel_id)
        message = await channel.fetch_message(session.team_message_id)
        await message.edit(embed=build_team_embed(session))
    except discord.HTTPException:
        pass


async def trigger_team_formation(bot: commands.Bot, interaction: discord.Interaction, guild_id: int, method: str):
    """팀편성 버튼(랜덤/티어순)을 눌렀을 때 공통으로 실행되는 로직.
    이미 팀편성 결과 메시지가 있으면 새로 만들지 않고 그 메시지를 수정한다."""
    session = session_manager.get(guild_id)
    if session is None or session.closed:
        await interaction.response.send_message("현재 진행 중인 내전이 없어요.", ephemeral=True)
        return

    if session.current_count == 0:
        await interaction.response.send_message("신청자가 없어요.", ephemeral=True)
        return

    session.balance_method = method
    regenerate_assignment(session)

    # 기존 팀편성 메시지가 있으면 그걸 수정, 없으면 새로 생성
    if session.team_channel_id and session.team_message_id:
        try:
            channel = bot.get_channel(session.team_channel_id) or await bot.fetch_channel(session.team_channel_id)
            message = await channel.fetch_message(session.team_message_id)
            await message.edit(embed=build_team_embed(session), view=TeamFormView(guild_id))
            await interaction.response.send_message("✅ 팀편성 메시지를 갱신했어요.", ephemeral=True)
            return
        except discord.HTTPException:
            pass  # 메시지가 지워졌으면 아래에서 새로 생성

    view = TeamFormView(guild_id)
    await interaction.response.send_message(embed=build_team_embed(session), view=view)
    sent_message = await interaction.original_response()
    session.team_channel_id = sent_message.channel.id
    session.team_message_id = sent_message.id


async def delete_session_messages(bot: commands.Bot, session: MatchSession, guild: discord.Guild = None):
    """내전 취소/종료 시 개설 안내 메시지, 팀편성 결과 메시지, 디스코드 이벤트까지 정리한다"""
    targets = [
        ("announce", session.announce_channel_id, session.announce_message_id),
        ("team", session.team_channel_id, session.team_message_id),
        ("reminder", session.reminder_channel_id, session.reminder_message_id),
        ("start_notice", session.start_channel_id, session.start_message_id),
    ]
    for label, channel_id, message_id in targets:
        if not channel_id or not message_id:
            log.info(f"[내전정리] {label} 메시지 정보 없음 (channel_id={channel_id}, message_id={message_id})")
            continue
        try:
            channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
            message = await channel.fetch_message(message_id)
            await message.delete()
            log.info(f"[내전정리] {label} 메시지 삭제 완료 (message_id={message_id})")
        except Exception as e:
            log.warning(f"[내전정리] {label} 메시지 삭제 실패 (channel_id={channel_id}, message_id={message_id}): {e}")

    if guild and session.discord_event_id:
        try:
            event = await guild.fetch_scheduled_event(session.discord_event_id)
            await event.delete()
            log.info("[내전정리] 디스코드 이벤트 삭제 완료")
        except Exception as e:
            log.warning(f"[내전정리] 디스코드 이벤트 삭제 실패: {e}")


class TeamModeSelect(discord.ui.Select):
    """루미아섬 전용: 솔로(1인)/듀오(2인)/스쿼드(3인) 모드 선택 드롭다운"""

    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        options = [
            discord.SelectOption(label="솔로 (1인 x 8팀 = 8명)", value="1", description="1인 8팀"),
            discord.SelectOption(label="듀오 (2인 x 8팀 = 16명)", value="2", description="2인 8팀"),
            discord.SelectOption(label="스쿼드 (3인 x 8팀 = 24명)", value="3", description="3인 8팀 (기본)", default=True),
        ]
        super().__init__(placeholder="편성 모드 선택 (기본: 스쿼드)", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        if not is_admin(interaction):
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return

        session = session_manager.get(self.guild_id)
        if session is None or session.closed:
            await interaction.response.send_message("현재 진행 중인 내전이 없어요.", ephemeral=True)
            return

        session.effective_team_size = int(self.values[0])
        mode_label = MODE_LABELS.get(session.effective_team_size, f"{session.effective_team_size}인")
        await interaction.response.send_message(
            f"✅ 편성 모드를 **{mode_label}**로 설정했어요. 이제 팀편성 버튼을 눌러주세요.", ephemeral=True
        )
        await refresh_announce_message(interaction.client, session)


class OpenMatchView(discord.ui.View):
    """/내전개설 안내 메시지에 붙는 팀편성 버튼 (티어순/랜덤) + 루미아섬 모드선택"""

    def __init__(self, guild_id: int, bot: commands.Bot, map_name: str = None):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.bot = bot
        if map_name == "루미아섬":
            self.add_item(TeamModeSelect(guild_id))

    @discord.ui.button(label="📊 티어순 팀편성", style=discord.ButtonStyle.primary)
    async def form_rank(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction):
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return
        await trigger_team_formation(self.bot, interaction, self.guild_id, "rank")

    @discord.ui.button(label="🎲 랜덤 팀편성", style=discord.ButtonStyle.secondary)
    async def form_random(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction):
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return
        await trigger_team_formation(self.bot, interaction, self.guild_id, "random")


class TeamFormView(discord.ui.View):
    """팀편성 결과 메시지에 붙는 재편성/편성취소 버튼"""

    def __init__(self, guild_id: int):
        super().__init__(timeout=None)  # 봇이 켜져있는 동안은 계속 눌러도 되게 타임아웃 없음
        self.guild_id = guild_id

    @discord.ui.button(label="🔀 다시 편성", style=discord.ButtonStyle.secondary)
    async def reroll(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction):
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return

        session = session_manager.get(self.guild_id)
        if session is None or session.team_assignment is None:
            await interaction.response.send_message("편성 정보를 찾을 수 없어요.", ephemeral=True)
            return

        regenerate_assignment(session)
        await interaction.response.edit_message(embed=build_team_embed(session), view=self)

    @discord.ui.button(label="❌ 편성 취소", style=discord.ButtonStyle.danger)
    async def cancel_formation(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction):
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return

        session = session_manager.get(self.guild_id)
        if session is None:
            await interaction.response.send_message("세션을 찾을 수 없어요.", ephemeral=True)
            return

        # 편성 정보 초기화 -> 다시 신청/신청취소 가능해짐
        session.team_assignment = None
        session.balance_method = None
        session.formed_team_count = None
        session.team_channel_id = None
        session.team_message_id = None

        await interaction.response.edit_message(
            content="↩️ 편성이 취소됐어요. 다시 신청을 받을 수 있어요.", embed=None, view=None
        )
        await refresh_announce_message(interaction.client, session)


class MatchCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rank_provider = bot.rank_provider  # bot.py에서 주입
        self.reminder_loop.start()

    def cog_unload(self):
        self.reminder_loop.cancel()

    @tasks.loop(seconds=30)
    async def reminder_loop(self):
        """30초마다 모든 세션을 확인해서, 시작 전 알림 / 시작 시각 알림을 각각 체크해서 발송"""
        now = datetime.datetime.now(KST)
        for session in session_manager.all_sessions():
            if session.closed:
                continue
            if session.scheduled_time is None:
                continue

            # 1) 시작 몇 분 전 알림
            if not session.reminder_sent and session.reminder_minutes is not None:
                remind_at = session.scheduled_time - datetime.timedelta(minutes=session.reminder_minutes)
                if now >= remind_at:
                    await self._send_prestart_reminder(session)
                    session.reminder_sent = True

            # 2) 내전 시작 시각 알림
            if not session.start_notified and now >= session.scheduled_time:
                await self._send_start_notification(session)
                session.start_notified = True

    @reminder_loop.before_loop
    async def before_reminder_loop(self):
        await self.bot.wait_until_ready()

    def _mention_applicants(self, session: MatchSession) -> str:
        # 테스트 더미(음수 ID)는 멘션 제외, 실제 신청자만 멘션
        return " ".join(f"<@{aid}>" for aid in session.applicants.keys() if aid > 0)

    async def _send_prestart_reminder(self, session: MatchSession):
        if not session.announce_channel_id:
            return
        try:
            channel = self.bot.get_channel(session.announce_channel_id) or await self.bot.fetch_channel(session.announce_channel_id)
        except discord.HTTPException:
            return

        mentions = self._mention_applicants(session)
        ts = int(session.scheduled_time.timestamp())
        text = f"⏰ **{session.map_name} 내전 시작 {session.reminder_minutes}분 전이에요!** (<t:{ts}:t>)"
        if mentions:
            text += f"\n{mentions}"

        try:
            sent = await channel.send(text)
            session.reminder_channel_id = sent.channel.id
            session.reminder_message_id = sent.id
        except discord.HTTPException:
            pass

    async def _send_start_notification(self, session: MatchSession):
        if not session.announce_channel_id:
            return
        try:
            channel = self.bot.get_channel(session.announce_channel_id) or await self.bot.fetch_channel(session.announce_channel_id)
        except discord.HTTPException:
            return

        mentions = self._mention_applicants(session)
        text = f"🚀 **{session.map_name} 내전 시작 시간이에요!** 다들 준비해주세요."
        if mentions:
            text += f"\n{mentions}"

        try:
            sent = await channel.send(text)
            session.start_channel_id = sent.channel.id
            session.start_message_id = sent.id
        except discord.HTTPException:
            pass

    맵선택 = [
        app_commands.Choice(name="루미아섬 (24명 모집)", value="루미아섬"),
        app_commands.Choice(name="코발트 (8명 모집)", value="코발트"),
    ]

    # ---------------------------------------------------------------
    @app_commands.command(name="내전개설", description="맵을 선택해 내전 신청을 시작합니다.")
    @app_commands.choices(맵=맵선택)
    @app_commands.describe(
        날짜="내전 시작 날짜 (예: 07/10)",
        시간="내전 시작 시각, 24시 기준 (예: 20:00)",
        알림분전="시작 몇 분 전에 신청자 전원에게 알림을 보낼지 (예: 30)",
    )
    async def open_match(
        self,
        interaction: discord.Interaction,
        맵: app_commands.Choice[str],
        날짜: str,
        시간: str,
        알림분전: int,
    ):
        if not is_admin(interaction):
            await interaction.response.send_message("관리자만 내전을 개설할 수 있어요.", ephemeral=True)
            return

        existing = session_manager.get(interaction.guild_id)
        if existing and not existing.closed:
            await interaction.response.send_message(
                f"이미 진행 중인 내전이 있어요 ({existing.map_name}, {existing.current_count}/{existing.capacity}명). "
                f"먼저 `/내전취소`로 종료해주세요.",
                ephemeral=True,
            )
            return

        try:
            scheduled_time = parse_schedule(날짜, 시간)
        except Exception:
            await interaction.response.send_message(
                "날짜/시간 형식이 올바르지 않아요. 예: 날짜=07/10, 시간=20:00", ephemeral=True
            )
            return

        if scheduled_time <= datetime.datetime.now(KST):
            await interaction.response.send_message(
                "이미 지난 시간이에요. 현재 이후 시간으로 다시 입력해주세요.", ephemeral=True
            )
            return

        if 알림분전 < 0:
            await interaction.response.send_message("알림분전은 0 이상이어야 해요.", ephemeral=True)
            return

        session = session_manager.create(interaction.guild_id, 맵.value)
        session.scheduled_time = scheduled_time
        session.reminder_minutes = 알림분전

        # 디스코드 자체 일정(이벤트) 생성 (권한 없으면 실패해도 신청 자체는 계속 진행)
        try:
            event = await interaction.guild.create_scheduled_event(
                name=f"이터널리턴 내전 - {session.map_name}",
                description="봇으로 자동 생성된 내전 일정입니다. 신청은 디스코드 채널의 /내전신청 명령어로 해주세요.",
                start_time=scheduled_time,
                end_time=scheduled_time + datetime.timedelta(hours=2),
                entity_type=discord.EntityType.external,
                location="인게임 (이터널리턴)",
                privacy_level=discord.PrivacyLevel.guild_only,
            )
            session.discord_event_id = event.id
        except discord.Forbidden:
            log.warning("디스코드 이벤트 생성 실패: 봇에 '이벤트 관리' 권한이 없음")
        except Exception as e:
            log.warning(f"디스코드 이벤트 생성 실패: {e}")

        await interaction.response.send_message(embed=build_open_embed(session), view=OpenMatchView(interaction.guild_id, self.bot, session.map_name))
        sent_message = await interaction.original_response()
        session.announce_channel_id = sent_message.channel.id
        session.announce_message_id = sent_message.id

    # ---------------------------------------------------------------
    @app_commands.command(name="내전신청", description="이터널리턴 닉네임으로 내전에 신청합니다.")
    @app_commands.describe(닉네임="본인의 이터널리턴 인게임 닉네임")
    async def apply_match(self, interaction: discord.Interaction, 닉네임: str):
        session = session_manager.get(interaction.guild_id)
        if session is None or session.closed:
            await interaction.response.send_message("현재 진행 중인 내전이 없어요. `/내전개설`로 먼저 열어주세요.", ephemeral=True)
            return

        if session.team_assignment is not None:
            await interaction.response.send_message("이미 팀 편성이 진행 중이라 새로 신청할 수 없어요.", ephemeral=True)
            return

        if interaction.user.id in session.applicants:
            await interaction.response.send_message("이미 신청하셨어요. 다시 신청하려면 `/신청취소` 후 재신청해주세요.", ephemeral=True)
            return

        if session.is_full:
            await interaction.response.send_message("정원이 이미 마감되었어요.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True, ephemeral=True)

        try:
            rank = await self.rank_provider.get_rank(닉네임)
        except RankProviderError as e:
            await interaction.followup.send(f"⚠️ {e}", ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(
                f"⚠️ 랭크 조회 중 알 수 없는 오류가 발생했어요: {e}\n잠시 후 다시 시도해주세요.",
                ephemeral=True,
            )
            return

        score = config.UNRANKED_SCORE if rank.is_unranked else rank.rp

        applicant = Applicant(
            discord_id=interaction.user.id,
            display_name=interaction.user.display_name,
            nickname=rank.nickname,
            tier=rank.tier,
            rp=score,
        )
        session.applicants[interaction.user.id] = applicant

        await interaction.followup.send(
            f"✅ **{applicant.nickname}** 님 신청 완료! (티어: {rank.tier}, RP: {rank.rp})\n"
            f"현재 인원: **{session.current_count}/{session.capacity}**",
            ephemeral=True,
        )
        await refresh_announce_message(self.bot, session)

    # ---------------------------------------------------------------
    @app_commands.command(name="신청취소", description="본인의 내전 신청을 취소합니다.")
    async def cancel_application(self, interaction: discord.Interaction):
        session = session_manager.get(interaction.guild_id)
        if session is None or session.closed:
            await interaction.response.send_message("현재 진행 중인 내전이 없어요.", ephemeral=True)
            return

        if session.team_assignment is not None:
            await interaction.response.send_message("이미 팀 편성이 진행 중이라 취소할 수 없어요. 관리자에게 문의해주세요.", ephemeral=True)
            return

        if interaction.user.id not in session.applicants:
            await interaction.response.send_message("신청 내역이 없어요.", ephemeral=True)
            return

        del session.applicants[interaction.user.id]
        await interaction.response.send_message("신청이 취소됐어요.", ephemeral=True)
        await refresh_announce_message(self.bot, session)

    # ---------------------------------------------------------------
    @app_commands.command(name="수동이동", description="특정 신청자를 원하는 팀으로 수동 이동합니다. (관리자 전용, 팀편성 버튼 사용 후)")
    @app_commands.describe(닉네임="이동할 신청자의 등록된 닉네임", 팀번호="이동할 팀 번호 (1부터 시작)")
    async def manual_move(self, interaction: discord.Interaction, 닉네임: str, 팀번호: int):
        if not is_admin(interaction):
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return

        session = session_manager.get(interaction.guild_id)
        if session is None or session.team_assignment is None:
            await interaction.response.send_message("먼저 개설 메시지의 팀편성 버튼을 눌러 편성을 만들어주세요.", ephemeral=True)
            return

        if session.closed:
            await interaction.response.send_message("이미 확정된 편성이라 수정할 수 없어요.", ephemeral=True)
            return

        team_count = session.formed_team_count or session.team_count
        if not (1 <= 팀번호 <= team_count):
            await interaction.response.send_message(f"팀번호는 1~{team_count} 사이여야 해요.", ephemeral=True)
            return

        target = None
        for applicant in session.applicants.values():
            if applicant.nickname.strip().lower() == 닉네임.strip().lower():
                target = applicant
                break

        if target is None:
            await interaction.response.send_message(f"'{닉네임}' 신청자를 찾을 수 없어요.", ephemeral=True)
            return

        session.team_assignment[target.discord_id] = 팀번호 - 1
        await interaction.response.send_message(
            f"✅ **{target.nickname}** 님을 팀 {팀번호} 로 이동했어요.", ephemeral=True
        )
        await update_team_message(self.bot, session)

    # ---------------------------------------------------------------
    @app_commands.command(name="내전취소", description="진행 중인 내전을 취소합니다. (관리자 전용)")
    async def cancel_match(self, interaction: discord.Interaction):
        if not is_admin(interaction):
            await interaction.response.send_message("관리자만 내전을 취소할 수 있어요.", ephemeral=True)
            return

        session = session_manager.get(interaction.guild_id)
        if session is None:
            await interaction.response.send_message("진행 중인 내전이 없어요.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        await delete_session_messages(self.bot, session, interaction.guild)
        session_manager.cancel(interaction.guild_id)
        await interaction.followup.send("🚫 내전이 취소되었어요.")

    # ---------------------------------------------------------------
    @app_commands.command(name="내전종료", description="내전이 끝난 후 세션을 정리합니다. (관리자 전용)")
    async def end_match(self, interaction: discord.Interaction):
        if not is_admin(interaction):
            await interaction.response.send_message("관리자만 사용할 수 있어요.", ephemeral=True)
            return

        session = session_manager.get(interaction.guild_id)
        if session is None:
            await interaction.response.send_message("진행 중인 내전이 없어요.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        await delete_session_messages(self.bot, session, interaction.guild)
        session_manager.cancel(interaction.guild_id)
        await interaction.followup.send(f"🏁 {session.map_name} 내전이 종료됐어요. 수고하셨습니다!")


async def setup(bot: commands.Bot):
    await bot.add_cog(MatchCog(bot))