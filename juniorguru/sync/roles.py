from collections import Counter
from pathlib import Path
from pprint import pformat

from discord import Color
from strictyaml import Int, Map, Seq, Str, load

from juniorguru.cli.sync import main as cli
from juniorguru.lib import discord_sync, loggers
from juniorguru.lib.discord_club import get_user_roles
from juniorguru.lib.mutations import mutating_discord
from juniorguru.models.base import db
from juniorguru.models.club import ClubDocumentedRole, ClubUser
from juniorguru.models.event import Event
from juniorguru.models.mentor import Mentor
from juniorguru.models.partner import Partnership


logger = loggers.from_path(__file__)

YAML_PATH = Path('juniorguru/data/roles.yml')

YAML_SCHEMA = Seq(
    Map({
        'id': Int(),
        'slug': Str(),
        'description': Str(),
    })
)

PARTNER_ROLE_PREFIX = 'Firma: '

STUDENT_ROLE_PREFIX = 'Student: '


@cli.sync_command(dependencies=['club-content',
                                'events',
                                'avatars',
                                'members',
                                'partners',
                                'mentoring'])
def main():
    discord_sync.run(discord_task)


@db.connection_context()
async def discord_task(client):
    logger.info('Setting up db table for documented roles')
    ClubDocumentedRole.drop_table()
    ClubDocumentedRole.create_table()

    logger.info('Fetching info about roles')
    yaml_records = {record.data['id']: record.data
                    for record in load(YAML_PATH.read_text(), YAML_SCHEMA)}

    # Why sorting and enumeration? Citing docs: "The recommended and correct way
    # to compare for roles in the hierarchy is using the comparison operators on
    # the role objects themselves."
    discord_roles = await client.club_guild.fetch_roles()
    documented_discord_roles = sorted([discord_role for discord_role
                                       in discord_roles
                                       if discord_role.id in yaml_records], reverse=True)

    for position, discord_role in enumerate(documented_discord_roles, start=1):
        logger.debug(f"#{position} {discord_role.name}")
        ClubDocumentedRole.create(id=discord_role.id,
                                  position=position,
                                  name=discord_role.name,
                                  mention=discord_role.mention,
                                  slug=yaml_records[discord_role.id]['slug'],
                                  description=yaml_records[discord_role.id]['description'].strip(),
                                  emoji=discord_role.unicode_emoji)

    logger.info('Preparing data for computing how to re-assign roles')
    members = ClubUser.members_listing()
    partners = [partnership.partner for partnership in Partnership.active_listing()]
    changes = []
    top_members_limit = ClubUser.top_members_limit()
    logger.info(f'members_count={len(members)}, top_members_limit={top_members_limit}')

    logger.info('Computing how to re-assign role: most_discussing')
    role_id = ClubDocumentedRole.get_by_slug('most_discussing').id
    messages_count_stats = calc_stats(members, lambda m: m.messages_count(), top_members_limit)
    logger.debug(f"messages_count {repr_stats(members, messages_count_stats)}")
    recent_messages_count_stats = calc_stats(members, lambda m: m.recent_messages_count(), top_members_limit)
    logger.debug(f"recent_messages_count {repr_stats(members, recent_messages_count_stats)}")
    most_discussing_members_ids = set(messages_count_stats.keys()) | set(recent_messages_count_stats.keys())
    logger.debug(f"most_discussing_members: {repr_ids(members, most_discussing_members_ids)}")
    for member in members:
        changes.extend(evaluate_changes(member.id, member.initial_roles, most_discussing_members_ids, role_id))

    logger.info('Computing how to re-assign role: most_helpful')
    role_id = ClubDocumentedRole.get_by_slug('most_helpful').id
    upvotes_count_stats = calc_stats(members, lambda m: m.upvotes_count(), top_members_limit)
    logger.debug(f"upvotes_count {repr_stats(members, upvotes_count_stats)}")
    recent_upvotes_count_stats = calc_stats(members, lambda m: m.recent_upvotes_count(), top_members_limit)
    logger.debug(f"recent_upvotes_count {repr_stats(members, recent_upvotes_count_stats)}")
    most_helpful_members_ids = set(upvotes_count_stats.keys()) | set(recent_upvotes_count_stats.keys())
    logger.debug(f"most_helpful_members: {repr_ids(members, most_helpful_members_ids)}")
    for member in members:
        changes.extend(evaluate_changes(member.id, member.initial_roles, most_helpful_members_ids, role_id))

    logger.info('Computing how to re-assign role: has_intro_and_avatar')
    role_id = ClubDocumentedRole.get_by_slug('has_intro_and_avatar').id
    intro_avatar_members_ids = [member.id for member in members if member.has_avatar and member.intro]
    logger.debug(f"intro_avatar_members: {repr_ids(members, intro_avatar_members_ids)}")
    for member in members:
        changes.extend(evaluate_changes(member.id, member.initial_roles, intro_avatar_members_ids, role_id))

    logger.info('Computing how to re-assign role: new')
    role_id = ClubDocumentedRole.get_by_slug('new').id
    new_members_ids = [member.id for member in members if member.is_new()]
    logger.debug(f"new_members_ids: {repr_ids(members, new_members_ids)}")
    for member in members:
        changes.extend(evaluate_changes(member.id, member.initial_roles, new_members_ids, role_id))

    logger.info('Computing how to re-assign role: year_old')
    role_id = ClubDocumentedRole.get_by_slug('year_old').id
    year_old_members_ids = [member.id for member in members if member.is_year_old()]
    logger.debug(f"year_old_members_ids: {repr_ids(members, year_old_members_ids)}")
    for member in members:
        changes.extend(evaluate_changes(member.id, member.initial_roles, year_old_members_ids, role_id))

    logger.info('Computing how to re-assign role: speaker')
    role_id = ClubDocumentedRole.get_by_slug('speaker').id
    speaking_members_ids = [member.id for member in Event.list_speaking_members()]
    logger.debug(f"speaking_members_ids: {repr_ids(members, speaking_members_ids)}")
    for member in members:
        changes.extend(evaluate_changes(member.id, member.initial_roles, speaking_members_ids, role_id))

    logger.info('Computing how to re-assign role: mentor')
    role_id = ClubDocumentedRole.get_by_slug('mentor').id
    mentors_members_ids = [mentor.user.id for mentor in Mentor.listing()]
    logger.debug(f"mentors_ids: {repr_ids(members, mentors_members_ids)}")
    for member in members:
        changes.extend(evaluate_changes(member.id, member.initial_roles, mentors_members_ids, role_id))

    logger.info('Computing how to re-assign role: founder')
    role_id = ClubDocumentedRole.get_by_slug('founder').id
    founders_members_ids = [member.id for member in members if member.is_founder()]
    logger.debug(f"founders_members_ids: {repr_ids(members, founders_members_ids)}")
    for member in members:
        changes.extend(evaluate_changes(member.id, member.initial_roles, founders_members_ids, role_id))

    logger.info('Computing how to re-assign role: partner')
    role_id = ClubDocumentedRole.get_by_slug('partner').id
    coupons = list(filter(None, (partner.coupon for partner in partners)))
    partners_members_ids = [member.id for member in members if member.coupon in coupons]
    logger.debug(f"partners_members_ids: {repr_ids(members, partners_members_ids)}")
    for member in members:
        changes.extend(evaluate_changes(member.id, member.initial_roles, partners_members_ids, role_id))

    # syncing with Discord
    logger.info(f'Managing roles for {len(partners)} partners')
    await manage_partner_roles(client, discord_roles, partners)

    for partner in partners:
        partner_members_ids = [member.id for member in partner.list_members]
        logger.debug(f"partner_members_ids({partner!r}): {repr_ids(members, partner_members_ids)}")
        for member in members:
            changes.extend(evaluate_changes(member.id, member.initial_roles, partner_members_ids, partner.role_id))

        student_members_ids = [member.id for member in partner.list_student_members]
        logger.debug(f"student_members_ids({partner!r}): {repr_ids(members, student_members_ids)}")
        for member in members:
            changes.extend(evaluate_changes(member.id, member.initial_roles, student_members_ids, partner.student_role_id))

    logger.info(f'Applying {len(changes)} changes to roles:\n{pformat(changes)}')
    await apply_changes(client, changes)


# TODO rewrite so it doesn't need any async/await and can be tested
async def manage_partner_roles(client, discord_roles, partners):
    partner_roles_mapping = {PARTNER_ROLE_PREFIX + partner.name: partner
                             for partner in partners}
    student_roles_mapping = {STUDENT_ROLE_PREFIX + partner.name: partner
                             for partner in partners if partner.student_coupon}
    roles_names = list(partner_roles_mapping.keys()) + list(student_roles_mapping.keys())
    logger.info(f"There should be {len(roles_names)} roles with partner or student prefixes")

    existing_roles = [role for role in discord_roles
                      if role.name.startswith((PARTNER_ROLE_PREFIX, STUDENT_ROLE_PREFIX))]
    logger.info(f"Found {len(existing_roles)} roles with partner or student prefixes")

    roles_to_remove = [role for role in existing_roles if role.name not in roles_names]
    logger.info(f"Roles [{', '.join([role.name for role in roles_to_remove])}] will be removed")
    for role in roles_to_remove:
        logger.info(f"Removing role '{role.name}'")
        with mutating_discord(role) as proxy:
            await proxy.delete()

    roles_names_to_add = set(roles_names) - {role.name for role in existing_roles}
    logger.info(f"Roles [{', '.join(roles_names_to_add)}] will be added")
    for role_name in roles_names_to_add:
        logger.info(f"Adding role '{role_name}'")
        color = Color.dark_grey() if role_name.startswith(PARTNER_ROLE_PREFIX) else Color.default()
        with mutating_discord(client.club_guild) as proxy:
            await proxy.create_role(name=role_name, color=color, mentionable=True)

    existing_roles = [role for role in discord_roles
                      if role.name.startswith((PARTNER_ROLE_PREFIX, STUDENT_ROLE_PREFIX))]
    for role in existing_roles:
        partner = partner_roles_mapping.get(role.name)
        if partner:
            logger.info(f"Setting '{role.name}' to be employee role of {partner!r}'")
            partner.role_id = role.id
            partner.save()
        else:
            partner = student_roles_mapping.get(role.name)
            if partner:
                logger.info(f"Setting '{role.name}' to be student role of {partner!r}'")
                partner.student_role_id = role.id
                partner.save()


async def apply_changes(client, changes):
    # Can't take discord_roles as an argument and use instead of fetching, because before
    # this function runs, manage_partner_roles makes changes to the list of roles. This
    # function applies all changes to members, including the partner/student ones.
    all_discord_roles = {discord_role.id: discord_role
                         for discord_role in await client.club_guild.fetch_roles()}

    changes_by_members = {}
    for member_id, op, role_id in changes:
        changes_by_members.setdefault(member_id, dict(add=[], remove=[]))
        changes_by_members[member_id][op].append(role_id)

    for member_id, changes in changes_by_members.items():
        discord_member = await client.club_guild.fetch_member(member_id)
        if changes['add']:
            discord_roles = [all_discord_roles[role_id] for role_id in changes['add']]
            logger.debug(f'{discord_member.display_name}: adding {repr_roles(discord_roles)}')
            with mutating_discord(discord_member) as proxy:
                await proxy.add_roles(*discord_roles)
        if changes['remove']:
            discord_roles = [all_discord_roles[role_id] for role_id in changes['remove']]
            logger.debug(f'{discord_member.display_name}: removing {repr_roles(discord_roles)}')
            with mutating_discord(discord_member) as proxy:
                await proxy.remove_roles(*discord_roles)

        member = ClubUser.get_by_id(member_id)
        member.updated_roles = get_user_roles(discord_member)
        member.save()


def calc_stats(members, calc_member_fn, top_members_limit):
    counter = Counter({member.id: calc_member_fn(member) for member in members})
    return dict(counter.most_common()[:top_members_limit])


def evaluate_changes(member_id, initial_roles_ids, role_members_ids, role_id):
    if member_id in role_members_ids and role_id not in initial_roles_ids:
        return [(member_id, 'add', role_id)]
    if member_id not in role_members_ids and role_id in initial_roles_ids:
        return [(member_id, 'remove', role_id)]
    return []


def repr_stats(members, stats):
    display_names = {member.id: member.display_name for member in members}
    return repr({display_names[member_id]: count for member_id, count in stats.items()})


def repr_ids(members, members_ids):
    display_names = {member.id: member.display_name for member in members}
    return repr([display_names.get(member_id, "(doesn't exist)") for member_id in members_ids])


def repr_roles(roles):
    return repr([role.name for role in roles])
