from collections import namedtuple
from datetime import datetime, timedelta, date

from juniorguru.lib.club import JUNIORGURU_BOT
from juniorguru.models.club import ClubMessage, ClubUser
from juniorguru.sync.onboarding import prepare_messages, prepare_channels_operations


SCHEDULED_MESSAGES = {
    '👋': lambda context: 'First message',
    '🌯': lambda context: 'Second message',
    '💤': lambda context: 'Third message',
    '🆗': lambda context: 'Fourth message',
    '🟡': lambda context: 'Fifth message',
    '🟥': lambda context: 'Sixth message',
    '🤡': lambda context: 'Seventh message',
}

TODAY = date.today()


StubTextChannel = namedtuple('StubTextChannel', ['name', 'topic'])


def create_member(id):
    return ClubUser(id=id, display_name='Alice Foo', mention='...', tag='...')


def create_message(id, author_id, content, created_at=None, reactions=None):
    return ClubMessage(id=id,
                       url='https://example.com',
                       content=content,
                       reactions=reactions or {'❤️': 42},
                       created_at=created_at or datetime(2022, 1, 1),
                       author=create_member(author_id),
                       channel_id=123,
                       channel_name='dan-srb-tipy',
                       channel_mention='...')


def create_bot_message(id, content, created_at=None, unread=False):
    return create_message(id, JUNIORGURU_BOT, content, created_at=created_at,
                          reactions={'✅': 1} if unread else {'✅': 2})


def test_prepare_channels_operations_declutter():
    channel1 = StubTextChannel('honza-tipy', 'Tipy a soukromý kanál jen pro tebe! #abcd')
    channel2 = StubTextChannel('foo-moo-boo', '')

    assert prepare_channels_operations([channel1, channel2], []) == [
        ('delete', (channel1,)),
        ('delete', (channel2,)),
    ]


def test_prepare_channels_operations_empty_category():
    member1 = create_member(1)
    member2 = create_member(2)
    member3 = create_member(3)

    assert prepare_channels_operations([], [member1, member2, member3]) == [
        ('create', (member1,)),
        ('create', (member2,)),
        ('create', (member3,)),
    ]


def test_prepare_channels_operations_close_channels_for_missing_members():
    channel1 = StubTextChannel('alice-foo-tipy', 'Tipy a soukromý kanál jen pro tebe! 🦸 Alice Foo #1')
    channel2 = StubTextChannel('alice-foo-tipy', 'Tipy a soukromý kanál jen pro tebe! 🦸 Alice Foo #2')
    channel3 = StubTextChannel('alice-foo-tipy', 'Tipy a soukromý kanál jen pro tebe! 🦸 Alice Foo #3')
    channels = [channel1, channel2, channel3]

    member1 = create_member(1)
    member3 = create_member(3)
    members = [member1, member3]

    assert prepare_channels_operations(channels, members) == [
        ('update', (member1, channel1)),
        ('update', (member3, channel3)),
        ('close', (channel2,)),
    ]


def test_prepare_messages_empty_history():
    history = []

    assert prepare_messages(history, SCHEDULED_MESSAGES, TODAY) == [(None, '👋 First message')]


def test_prepare_messages_history_with_no_bot_messages():
    history = [create_message(1, 123, 'Non-relevant message'),
               create_message(2, 345, 'Another non-relevant message')]

    assert prepare_messages(history, SCHEDULED_MESSAGES, TODAY) == [(None, '👋 First message')]


def test_prepare_messages_history_with_non_relevant_bot_messages():
    history = [create_bot_message(1, 'Non-relevant message', unread=True),
               create_bot_message(2, 'Another non-relevant message')]

    assert prepare_messages(history, SCHEDULED_MESSAGES, TODAY) == [(None, '👋 First message')]


def test_prepare_messages_history_with_the_first_message():
    history = [create_bot_message(1, '👋 First message')]

    assert prepare_messages(history, SCHEDULED_MESSAGES, TODAY) == [(None, '🌯 Second message')]


def test_prepare_messages_history_unread():
    history = [create_bot_message(1, '👋 First message', unread=True)]

    assert prepare_messages(history, SCHEDULED_MESSAGES, TODAY) == []


def test_prepare_messages_history_unread_last_message():
    history = [create_bot_message(1, '👋 First message', created_at=datetime.utcnow() - timedelta(days=2)),
               create_bot_message(2, '🌯 Second message', created_at=datetime.utcnow() - timedelta(days=1), unread=True)]

    assert prepare_messages(history, SCHEDULED_MESSAGES, TODAY) == []


def test_prepare_messages_history_unread_past_but_not_last_message():
    history = [create_bot_message(1, '👋 First message', created_at=datetime.utcnow() - timedelta(days=2), unread=True),
               create_bot_message(2, '🌯 Second message', created_at=datetime.utcnow() - timedelta(days=1))]

    assert prepare_messages(history, SCHEDULED_MESSAGES, TODAY) == [(None, '💤 Third message')]


def test_prepare_messages_history_with_missing_messages():
    history = [create_bot_message(1, '👋 First message'),
               create_bot_message(2, '🟥 Sixth message')]

    assert prepare_messages(history, SCHEDULED_MESSAGES, TODAY) == [(None, '🌯 Second message')]


def test_prepare_messages_history_with_edits():
    history = [create_bot_message(1, '👋 Outdated message'),
               create_bot_message(2, '🌯 Second message'),
               create_bot_message(3, '💤 Third message'),
               create_bot_message(4, '🆗 Outdated message')]

    assert prepare_messages(history, SCHEDULED_MESSAGES, TODAY) == [(1, '👋 First message'),
                                                                    (4, '🆗 Fourth message'),
                                                                    (None, '🟡 Fifth message')]


def test_prepare_messages_post_for_the_first_time_that_day():
    history = [create_bot_message(1, '👋 First message', created_at=datetime.utcnow() - timedelta(days=3)),
               create_bot_message(2, '🌯 Second message', created_at=datetime.utcnow() - timedelta(days=2)),
               create_bot_message(3, '💤 Third message', created_at=datetime.utcnow() - timedelta(days=1))]

    assert prepare_messages(history, SCHEDULED_MESSAGES, TODAY) == [(None, '🆗 Fourth message')]



def test_prepare_messages_dont_post_twice_the_same_day():
    history = [create_bot_message(1, '👋 First message', created_at=datetime.utcnow() - timedelta(days=2)),
               create_bot_message(2, '🌯 Second message', created_at=datetime.utcnow() - timedelta(days=1)),
               create_bot_message(3, '💤 Third message', created_at=datetime.utcnow())]

    assert prepare_messages(history, SCHEDULED_MESSAGES, TODAY) == []


def test_prepare_messages_edit_messages_regardless_of_dates():
    history = [create_bot_message(1, '👋 Outdated message', created_at=datetime.utcnow() - timedelta(days=3)),
               create_bot_message(2, '🌯 Second message', created_at=datetime.utcnow() - timedelta(days=2)),
               create_bot_message(3, '💤 Third message', created_at=datetime.utcnow() - timedelta(days=1)),
               create_bot_message(4, '🆗 Outdated message', created_at=datetime.utcnow())]

    assert prepare_messages(history, SCHEDULED_MESSAGES, TODAY) == [(1, '👋 First message'),
                                                                    (4, '🆗 Fourth message')]


def test_prepare_messages_passes_context():
    context = dict(name='Honza')
    scheduled_messages = {'🔥': lambda context: f"Hello {context['name']}"}

    assert prepare_messages([], scheduled_messages, TODAY, context=context) == [(None, '🔥 Hello Honza')]
