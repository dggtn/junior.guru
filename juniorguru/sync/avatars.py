from pathlib import Path
from urllib.parse import urlparse
from io import BytesIO
import asyncio

from PIL import Image

from juniorguru.lib.timer import measure
from juniorguru.lib import loggers
from juniorguru.lib.club import discord_task
from juniorguru.models import ClubUser, with_db


logger = loggers.get('avatars')


IMAGES_PATH = Path(__file__).parent.parent / 'images'
AVATARS_PATH = IMAGES_PATH / 'avatars'
AVATAR_SIZE_PX = 60


@measure('avatars')
@with_db
@discord_task
async def main(client):
    AVATARS_PATH.mkdir(exist_ok=True, parents=True)
    for path in AVATARS_PATH.glob('*.png'):
        path.unlink()

    await asyncio.gather(*[
        process_member(client, member)
        for member in ClubUser.members_listing()
    ])


async def process_member(client, member):
    logger_m = logger.getChild(str(member.id))
    logger_m.info('Checking avatar')
    logger_m.debug(f"Name: {member.display_name}")
    try:
        discord_member = await client.juniorguru_guild.fetch_member(member.id)
        if discord_member.avatar:
            logger_m.info("Has avatar, downloading")
            member.avatar_path = await download_avatar(discord_member.avatar)
        if member.avatar_path:
            logger_m.info(f"Has avatar, downloaded as '{member.avatar_path}'")
        else:
            logger_m.info("Has no avatar")
    except:
        logger_m.exception("Unable to get avatar")
        raise
    member.save()


async def download_avatar(avatar):
    buffer = BytesIO()
    await avatar.save(buffer)
    image = Image.open(buffer)
    image = image.resize((AVATAR_SIZE_PX, AVATAR_SIZE_PX))
    image_path = AVATARS_PATH / f'{Path(urlparse(avatar.url).path).stem}.png'
    image.save(image_path, 'PNG')
    return f'images/avatars/{image_path.name}'


if __name__ == '__main__':
    main()
