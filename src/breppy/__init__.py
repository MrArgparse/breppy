from bs4 import BeautifulSoup, element
from pathlib import Path
from rich.logging import RichHandler
from urllib.parse import urljoin
import logging
import msgspec
import os
import platformdirs
import requests
import tomlkit
import urllib

logging.basicConfig(
	level=logging.INFO, format='%(message)s', datefmt='[%X]', handlers=[RichHandler()]
)
PLATFORMDIRS = platformdirs.PlatformDirs(appname='breppy', appauthor=False)
CONFIG_FOLDER = PLATFORMDIRS.user_config_path
DEFAULT_CONFIGURATION_PATH = CONFIG_FOLDER / 'breppy_config.toml'
DEFAULT_ENCODING = 'utf-8'


class NewLuminanceCookies(msgspec.Struct, tag='new_luminance', kw_only=True):
	cid: str = ''
	sid: str = ''


class OldLuminanceCookies(msgspec.Struct, tag='old_luminance', kw_only=True):
	session: str = ''


class Payload(msgspec.Struct, kw_only=True):
	auth: str = ''
	checkonly: str = 'check for dupes'
	submit: str = 'true'
	genre_tags: str = '---'
	fontfont: int = -1
	fontsize: int = -1
	MAX_FILE_SIZE: int = 2097152
	anonymous: int = 1


class TrackerConfig(msgspec.Struct, kw_only=True):
	url: str
	cookies: NewLuminanceCookies | OldLuminanceCookies
	payload: Payload


def guess_tracker(url: str) -> TrackerConfig:
	cookies: OldLuminanceCookies | NewLuminanceCookies

	if url == 'https://www.pornbay.org':
		cookies = OldLuminanceCookies()

	else:
		cookies = NewLuminanceCookies()

	return TrackerConfig(url=url, cookies=cookies, payload=Payload())


class DefaultConfig(msgspec.Struct, kw_only=True):
	Emp: TrackerConfig = msgspec.field(
		default_factory=lambda: guess_tracker('https://www.empornium.sx')
	)
	Ent: TrackerConfig = msgspec.field(
		default_factory=lambda: guess_tracker('https://www.enthralled.me')
	)
	Pbay: TrackerConfig = msgspec.field(
		default_factory=lambda: guess_tracker('https://www.pornbay.org')
	)


def get_config_path(path: Path | None = None) -> Path:
	if path is None:
		return DEFAULT_CONFIGURATION_PATH

	return Path(path).resolve()


def load_config(path: Path | None = None) -> DefaultConfig:
	path = get_config_path(path)

	with open(path, 'r', encoding=DEFAULT_ENCODING) as fp:
		data = fp.read()

	return msgspec.toml.decode(data, type=DefaultConfig)


def save_config(configuration: DefaultConfig, path: Path | None = None) -> None:
	path = get_config_path(path)
	data = tomlkit.dumps(msgspec.to_builtins(configuration))
	path.parent.mkdir(parents=True, exist_ok=True)

	with open(path, 'w', encoding=DEFAULT_ENCODING) as fp:
		fp.write(data)

	logging.info(f'New default config saved in: {DEFAULT_CONFIGURATION_PATH}')


def load_or_create_config(path: Path | None = None) -> DefaultConfig:
	path = get_config_path(path)

	if path.exists():
		logging.info(f'Previous config found in: {DEFAULT_CONFIGURATION_PATH}')

	try:
		return load_config(path)

	except FileNotFoundError:
		pass

	configuration = DefaultConfig()
	save_config(configuration, path)

	return configuration


CONFIG = msgspec.to_builtins(load_or_create_config())


def find_empty_keys(d: object, current_key: str = '') -> list[str]:
	empty_keys: list[str] = []

	if not isinstance(d, dict):
		if d == '':
			return [current_key]

		else:
			return empty_keys

	for key, value in d.items():
		new_key = f'{current_key}.{key}' if current_key else key
		empty_keys.extend(find_empty_keys(value, new_key))

	return empty_keys


EMPTY_KEYS = find_empty_keys(CONFIG)

if EMPTY_KEYS:
	logging.warning(
		f'Values missing for the following keys:{os.linesep}{", ".join(EMPTY_KEYS)}'
	)


def stringify_ints(my_dict: dict[str, str | int]) -> dict[str, str]:
	return {key: str(value) for key, value in my_dict.items()}


def prepare_upload(
	bbcode: str, category: int, cover: str, taglist: str, title: str, tracker: str
) -> dict[str, str]:
	payload = stringify_ints(CONFIG[tracker]['payload'])
	payload.pop('checkonly')
	payload['ignoredupes'] = '1'
	payload['category'] = str(category)
	payload['title'] = title
	payload['image'] = cover

	match tracker:
		case 'Emp' | 'Ent':
			payload['taglist'] = taglist
			payload['desc'] = bbcode

		case 'PBay':
			payload['tags'] = taglist
			payload['desc'] = bbcode.replace(
				'[font=Aleo]', '[font=Palatino Linotype]'
			).replace('[font=Quantico]', '[font=Microsoft Sans Serif]')

	return payload


def build(
	fname: Path, tracker: str, payload: dict[str, str] | None = None
) -> requests.models.Response:
	url = CONFIG[tracker]['url']
	cookies = CONFIG[tracker]['cookies']

	if not payload:
		payload = stringify_ints(CONFIG[tracker]['payload'])

	name = fname.name
	seg = '/upload.php'

	with open(fname, 'rb') as torrent:
		files = {'file_input': (name, torrent, 'application/x-bittorrent')}
		return requests.post(urljoin(url, seg), cookies=cookies, data=payload, files=files)


def grab_collage_token(collage_url: str, tracker: str) -> str | None:
	cookies = CONFIG[tracker]['cookies']
	r = requests.get(collage_url, cookies=cookies)
	soup = BeautifulSoup(r.content, 'html.parser')
	add_torrent = soup.find(id='addtorrent')

	if isinstance(add_torrent, element.Tag):
		input_field = add_torrent.find('input')

		if isinstance(input_field, element.Tag):
			token = input_field.get('value')

			if token:
				return str(token)

	return None


def collage(
	collage_id: int, torrent_url: str, tracker: str
) -> requests.models.Response:
	url = CONFIG[tracker]['url']
	collage_path = f'/collage/{collage_id}'
	collage_url = urllib.parse.urljoin(url, collage_path)
	req_url = urllib.parse.urljoin(collage_url, f'{collage_path}/add')
	cookies = CONFIG[tracker]['cookies']

	form = {'token': grab_collage_token(collage_url, tracker), 'url': torrent_url}

	return requests.post(req_url, cookies=cookies, data=form)


def legacy_collage(
	collage_id: int, torrent_url: str, tracker: str
) -> requests.models.Response:
	collage_url = urllib.parse.urljoin(
		CONFIG[tracker]['url'], f'collages.php?id={collage_id}'
	)
	cookies = CONFIG[tracker]['cookies']
	auth = CONFIG[tracker]['auth']

	cl_payload = {
		'action': 'add_torrent',
		'auth': auth,
		'collageid': collage_id,
		'url': torrent_url,
	}

	return requests.post(collage_url, cookies=cookies, data=cl_payload)
