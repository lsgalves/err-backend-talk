import re
import sys
import json
import logging
import threading
import time

from errbot.backends.base import (
    Message,
    Person,
    Room,
    RoomOccupant,
    RoomError,
    ONLINE
)
from errbot.rendering import text
from errbot.core import ErrBot


log = logging.getLogger(__name__)

try:
    import requests
except ImportError:
    log.exception('Could not start the Talk back-end')
    log.fatal(
        'You need to install the requests library in order to use the Talk backend.\n'
        'You can do `pip install -r requirements.txt` to install it'
    )
    sys.exit(1)


class TalkPerson(Person):
    def __init__(self, id=None, name=None, email=None) -> None:
        self._id = id
        self._name = name
        self._email = email

    @property
    def id(self):
        return self._id

    @property
    def name(self):
        return self._name

    @property
    def email(self):
        return self._email

    @property
    def person(self):
        return self._id

    @property
    def nick(self):
        return self._id

    @property
    def fullname(self):
        return f'{self.id}#{self.name}'

    @property
    def aclattr(self) -> str:
        return self.fullname

    @property
    def client(self) -> None:
        return None

    def __eq__(self, other):
        return isinstance(other, TalkPerson) and other.id == self.id

    def __str__(self):
        return self.nick


class TalkRoomOccupant(TalkPerson, RoomOccupant):
    def __init__(self, room: str, id: str, name: str=None, email: str=None) -> None:
        super().__init__(id, name, email)
        self._room = room

    @property
    def room(self):
        return self._room

    def __eq__(self, other):
        return (
            isinstance(other, TalkRoomOccupant)
            and other.id == self.id
            and other.room == self.room
        )

    def __str__(self):
        return f'{super().__str__()}@{self.room.name}'


class TalkRoom(Room):
    def __init__(self, backend, id: str, name: str, display_name: str, type: int, last_read_message: int, can_delete: bool=None, can_leave: bool=None) -> None:
        self._backend = backend
        self._id = id
        self._name = name
        self._display_name = display_name
        self._type = type
        self._last_read_message = last_read_message
        self._can_delete = can_delete
        self._can_leave = can_leave
        self._joined = False

    @property
    def id(self):
        return self._id

    @property
    def name(self):
        return self._name

    @property
    def display_name(self):
        return self._display_name

    @property
    def type(self):
        return self._type

    @property
    def last_read_message(self):
        return self._last_read_message

    @last_read_message.setter
    def last_read_message(self, value):
        self._last_read_message = value

    @property
    def joined(self) -> bool:
        return self._joined

    @property
    def topic(self) -> str:
        return self._display_name if self.exists else ''

    @property
    def occupants(self):
        if not self.exists:
            return []

        r = self._backend.api_get(f'/apps/spreed/api/v4/room{self.id}/participants')
        return [
            TalkRoomOccupant(id=occupant['actorId'], name=occupant['displayName'], room=self.id)
            for occupant in r['ocs']['data']
        ]

    @property
    def exists(self) -> bool:
        r = self._backend.api_get('/apps/spreed/api/v4/room')
        rooms = r['ocs']['data']
        return len([room for room in rooms if room['token'] == self.id]) > 0

    def invite(self, *args):
        for identifier in args:
            self._backend.api_post(f'/apps/spreed/api/v4/room/{self.id}/participants', {
                'newParticipant': identifier
            })

    def create(self):
        if self.exists:
            log.warning(f'Tried to create {self.name} which already exists.')
            raise RoomError('Room exists')

        self._backend.api_post(f'/apps/spreed/api/v4/room', {
            'roomType': self.type,
            'roomName': self.name
        })

    def destroy(self):
        if not self.exists:
            log.warning(f'Tried to destory {self.name} which doesn\'t exist.')
            raise RoomError('Room doesn\'t exist')
        elif not self._can_delete:
            log.warning(f'Tried to destory {self.name} which doesn\'t permission.')
            raise RoomError('Room can\'t be destroyed')

        self._backend.api_delete(f'/apps/spreed/api/v4/room/{self.id}')

    def join(self):
        log.warning(
            'Can\'t join channels.  Public channels are automatically joined'
            ' and private channels are invite only.'
        )

    def leave(self):
        if not self.exists:
            log.warning(f'Tried to leave {self.name} which doesn\'t exist.')
            raise RoomError('Room doesn\'t exist')
        elif not self._can_leave:
            log.warning(f'Tried to leave {self.name} which doesn\'t permission.')
            raise RoomError('Room can\'t be leave')

        self._backend.api_delete(f'/apps/spreed/api/v4/room/{self.id}/participants/active')

    def __eq__(self, other):
        return str(self) == str(other)

    def __unicode__(self):
        return self.name

    __str__ = __unicode__


class TalkRoomThread(threading.Thread):
    def __init__(self, room: TalkRoom, backend):
        super().__init__()
        self.room = room
        self.backend = backend

    def run(self):
        self.room._joined = True
        log.debug(f'Thread for {self.room.id} started')
        while True:
            if self.room.last_read_message == None:
                self.room.last_read_message = self.get_last_read_message()
            self.fetch_messages()

    def get_last_read_message(self) -> None:
        r = self.backend.api_get(f'/apps/spreed/api/v4/room/{self.room.id}')
        return r['ocs']['data']['lastReadMessage']

    def fetch_messages(self, timeout: int=60):
        params = {
            'setReadMarker': 0,
            'lookIntoFuture': 1,
            'lastKnownMessageId': self.room.last_read_message,
            'includeLastKnown': 0,
            'timeout': timeout
        }

        try:
            log.debug(f'Waiting messages from {self.room.name}')
            r = self.backend.api_get(f'/apps/spreed/api/v1/chat/{self.room.id}', params=params)

            if r == None:
                return

            msgs = r['ocs']['data']
            self.room.last_read_message = msgs[-1]['id']

            for msg in msgs:
                raw_msg = msg['message']
                log.debug(f'Raw message from room {self.room.name}: {raw_msg}')
                m = Message(raw_msg)

                #if self.room.type == 1: # One to one
                #    m.frm = TalkPerson(id=msg['actorId'], name=msg['actorDisplayName'])
                #    m.to = self.backend.bot_identifier
                #else:
                m.frm = TalkRoomOccupant(self.room, id=msg['actorId'], name=msg['actorDisplayName'])
                m.to = self.room

                mentions = re.findall(r'{(mention-user[1-9]+)}', raw_msg)
                for mention in mentions:
                    mention_data = msg['messageParameters'][mention]

                    if mention_data['id'] == self.backend.bot_identifier.id:
                        m.to = self.backend.bot_identifier
                        clean_msg = re.sub(r'{mention-user[1-9]+}', '', raw_msg).strip()
                        self.backend.callback_mention(clean_msg,
                            [TalkRoomOccupant(self.room, id=mention_data['id'], name=mention_data['name'])]
                        )

                self.backend.callback_message(m)
        except:
            log.exception(f'An exception occured while read message from room: {self.room.name}')

class TalkBackend(ErrBot):
    """
    This is the Talk backend for Errbot.
    """
    def __init__(self, config):
        super().__init__(config)
        identity = config.BOT_IDENTITY
        self._domain = identity.get('domain', None)
        self._base_url = self._domain + '/ocs/v2.php'
        self._refresh_token = identity.get('oauth_token', None)
        self._client_id = identity.get('oauth_key', None)
        self._client_secret = identity.get('oauth_secret', None)
        self._access_token = None
        if not self._refresh_token or not self._client_id or not self._client_secret:
            log.fatal(
                'You need to set credentials in the BOT_IDENTITY setting of '
                'your configuration. To obtain it, execute the included oauth.py script'
            )
            sys.exit(1)

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Errbot',
            'Accept': 'application/json',
        })
        self.session.hooks['response'].append(self.refresh_token_hook)
        self._api_refresh_token()
        self.bot_identifier = self._get_bot_identifier()

        self._joined_rooms_lock = threading.Lock()
        self._joined_rooms = []

    def refresh_token_hook(self, r, *args, **kwargs):
        if r.status_code >= 400:
            log.info('Refreshing tokens')
            self._api_refresh_token()
            r.request.headers["Authorization"] = self.session.headers["Authorization"]
            return self.session.send(r.request, verify=False)

    def set_refresh_token(self, refresh_token: str):
        self._refresh_token = refresh_token
        with open('./config.py', "r+") as file:
            content = file.read()
            content = re.sub(r'oauth_token.+', f'oauth_token": "{refresh_token}",', content)
            file.seek(0)
            file.truncate()
            file.write(content)

    def _get_bot_identifier(self):
        log.debug('Fetching and building identifier for the bot itself.')
        r = self.api_get('/cloud/user')
        data = r['ocs']['data']
        bot_identifier = TalkPerson(id=data['id'], name=data['display-name'], email=data['email'])
        log.debug(f'Done! I\'m connected as {bot_identifier}')
        return bot_identifier

    def _api_refresh_token(self):
        headers = {
            'User-Agent': 'Errbot',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        data = {
            'client_id': self._client_id,
            'client_secret': self._client_secret,
            'grant_type': 'refresh_token',
            'refresh_token': self._refresh_token
        }

        r = requests.post(self._domain + '/apps/oauth2/api/v1/token', headers=headers, data=json.dumps(data))
        if r.status_code != requests.codes.ok:
            raise Exception(f'Server returned an error {r.status_code}:{r.text}')
        data = r.json()
        self._access_token = data['access_token']
        self.set_refresh_token(data['refresh_token'])
        self.session.headers.update({
            'Authorization': f'Bearer {self._access_token}',
        })
        print(self._access_token)

    def api_get(self, endpoint, params=None):
        r = self.session.get(self._base_url + endpoint, params=params)
        if r.status_code >= 400:
            raise Exception(f'Server returned an error {r.status_code}:{r.text}')
        if r.status_code >= 300:
            return
        return r.json()

    def api_post(self, endpoint, content):
        r = self.session.post(self._base_url + endpoint, headers={'Content-Type': 'application/json'}, data=json.dumps(content))
        if r.status_code >= 500:
            raise Exception(f'Server returned an error {r.status_code}:{r.text}')
        return r.json()

    def api_put(self, endpoint, content):
        r = self.session.put(self._base_url + endpoint, headers={'Content-Type': 'application/json'}, data=json.dumps(content))
        if r.status_code >= 500:
            raise Exception(f'Server returned an error {r.status_code}:{r.text}')
        return r.json()

    def api_delete(self, endpoint):
        r = self.session.delete(self._base_url + endpoint)
        if r.status_code != requests.codes.ok:
            raise Exception(f'Server returned an error {r.status_code}:{r.text}')
        return r.json()

    def rooms(self):
        r = self.api_get('/apps/spreed/api/v4/room')
        return [
            TalkRoom(self,
                id=room['token'], name=room['name'], display_name=room['displayName'],
                type=room['type'], last_read_message=room['lastReadMessage'],
                can_delete=room['canDeleteConversation'],
                can_leave=room['canLeaveConversation']
            ) for room in r['ocs']['data']
        ]

    def follow_room(self, room: Room):
        log.debug(f'Following room {room.id}')
        if room.id not in self._joined_rooms:
            thread = TalkRoomThread(room, self)
            thread.daemon = True
            thread.start()
            with self._joined_rooms_lock:
                self._joined_rooms.append(room.id)
        else:
            log.info(f'Already joined {room.name}')

    def build_identifier(self, text_representation: str):
        if text_representation == str(self.bot_identifier):
            return self.bot_identifier

        raise Exception(f'Couldn\'t build an identifier from {text_representation}.')

    def query_room(self, room: str):
        for room in self.rooms():
            if room.id == room:
                log.debug(f'Found room {room}')
                return room
        return None

    def is_from_self(self, msg: Message) -> bool:
        return msg.frm.id == self.bot_identifier.id

    def send_message(self, msg: Message):
        super().send_message(msg)
        log.info(f'Send message to {msg.to.room.id}')
        log.debug(f'bf body = {msg.body}')
        body = text().convert(msg.body)
        log.debug(f'af body = {body}')
        if hasattr(msg.to, 'room'):
            self.api_post(f'/apps/spreed/api/v1/chat/{msg.to.room.id}', {
                'actorDisplayName': self.bot_identifier.name,
                'message': body,
                'referenceId': ''
            })

    def build_reply(self, msg: Message, text: str=None, private: bool=False, threaded: bool=False):
        response = self.build_message(text)
        response.frm = msg.to
        response.to = msg.frm
        if private:
            response.to = self.build_identifier(msg.frm.nick)
        return response

    def connect_callback(self):
        super().connect_callback()
        for room in self.rooms():
            self.follow_room(room)

    def disconnect_callback(self):
        super().disconnect_callback()
        self.session.close()

    def serve_once(self):
        log.info('Initializing connection')
        self.connect_callback()
        try:
            while True:
                for room in self.rooms():
                    self.follow_room(room)
                time.sleep(10)
        except KeyboardInterrupt:
            log.info('Interrupt received, shutting down...')
            return True
        finally:
            self.disconnect_callback()

    def change_presence(self, status: str=ONLINE, message: str=''):
        log.debug(f'Presence changed to {status} and activity "{message}".')
        self.api_put('/apps/user_status/api/v1/user_status/status', {
            'statusType': status
        })
        self.api_put('/apps/user_status/api/v1/user_status/message/custom', {
            'message': message
        })

    def prefix_groupchat_reply(self, message, identifier: Person):
        message.body = f'@{identifier.nick} {message.body}'

    @property
    def mode(self):
        return 'talk'
