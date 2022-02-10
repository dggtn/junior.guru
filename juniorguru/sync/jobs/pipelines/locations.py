import re
from functools import lru_cache, wraps

import requests
from lxml import etree

from juniorguru.lib import loggers
from juniorguru.jobs.settings import USER_AGENT


logger = loggers.get('juniorguru.jobs.pipelines.locations')


# https://docs.python-requests.org/en/master/user/advanced/#timeouts
MAPYCZ_REQUEST_TIMEOUT = (3.05, 27)


OPTIMIZATIONS = [
    (re.compile(pattern), value) for pattern, value in [
        (r'\bPraha\b', {'place': 'Praha', 'region': 'Praha', 'country': 'Česko'}),
        (r'\bPrague\b', {'place': 'Praha', 'region': 'Praha', 'country': 'Česko'}),
        (r'\bBrno\b', {'place': 'Brno', 'region': 'Brno', 'country': 'Česko'}),
        (r'\bOstrava\b', {'place': 'Ostrava', 'region': 'Ostrava', 'country': 'Česko'}),
    ]
]

REGIONS_MAPPING = {
    # countries
    'Deutschland': 'Německo',
    'Polska': 'Polsko',
    'Österreich': 'Rakousko',

    # regions
    'Hlavní město Praha': 'Praha',
    'Středočeský kraj': 'Praha',
    'Jihočeský kraj': 'České Budějovice',
    'Plzeňský kraj': 'Plzeň',
    'Karlovarský kraj': 'Karlovy Vary',
    'Ústecký kraj': 'Ústí nad Labem',
    'Liberecký kraj': 'Liberec',
    'Královéhradecký kraj': 'Hradec Králové',
    'Pardubický kraj': 'Pardubice',
    'Olomoucký kraj': 'Olomouc',
    'Moravskoslezský kraj': 'Ostrava',
    'Jihomoravský kraj': 'Brno',
    'Zlínský kraj': 'Zlín',
    'Kraj Vysočina': 'Jihlava',
}

ADDRESS_TYPES_MAPPING = {
    # Mapy.cz
    'muni': 'place',
    'regi': 'region',
    'coun': 'country',

    # OpenStreetMaps
    'osmm': 'place',
    'osmr': 'region',
    'osmc': 'country',
}


class GeocodeError(Exception):
    pass


def process(item, geocode=None):
    location_tuples = [parse_location(loc, item, geocode)
                       for loc in item.get('locations_raw', [])]
    location_tuples = set(filter(None, location_tuples))
    item['locations'] = [dict(name=name, region=region)
                            for name, region in location_tuples]
    return item


def parse_location(location_raw, item, geocode=None):
    geocode = geocode or geocode_mapycz
    try:
        logger.debug(f"Geocoding '{location_raw}'")
        address = geocode(location_raw)
        if address:
            try:
                return (address['place'], get_region(address))
            except KeyError as e:
                raise KeyError(f"{address!r} doesn't have key {e}") from e
    except Exception:
        info = dict(title=item.get('title'),
                    company=item.get('company_name'))
        logger.exception(f"Geocoding '{location_raw}' failed, {info!r}")


def optimize_geocoding(geocode):
    @wraps(geocode)
    def wrapper(location_raw):
        for location_re, value in OPTIMIZATIONS:
            if location_re.search(location_raw):
                return value
        return lru_cache(geocode)(location_raw)
    return wrapper


@optimize_geocoding
def geocode_mapycz(location_raw):
    try:
        logger.debug(f"Geocoding '{location_raw}' using api.mapy.cz/geocode")
        response = requests.get('https://api.mapy.cz/geocode',
                                params={'query': location_raw},
                                headers={'User-Agent': USER_AGENT},
                                timeout=MAPYCZ_REQUEST_TIMEOUT)
        response.raise_for_status()

        xml = etree.fromstring(response.content)
        items = xml.xpath('//item')
        if not items:
            return None

        item = items[0]
        title, lat, lng = item.get('title'), item.get('y'), item.get('x')
    except requests.RequestException as e:
        raise GeocodeError(f"Unable to geocode '{location_raw}'") from e

    try:
        logger.debug(f"Reverse geocoding '{location_raw}' lat: {lat} lng: {lng} using api.mapy.cz/rgeocode")
        response = requests.get('https://api.mapy.cz/rgeocode',
                                params={'lat': lat, 'lon': lng},
                                headers={'User-Agent': USER_AGENT},
                                timeout=MAPYCZ_REQUEST_TIMEOUT)
        response.raise_for_status()

        xml = etree.fromstring(response.content)
        items = xml.xpath('//item')
        if not items:
            raise ValueError('No items in the reverse geocode response')

        address = {ADDRESS_TYPES_MAPPING[item.attrib['type']]: item.attrib['name']
                   for item in items if item.attrib['type'] in ADDRESS_TYPES_MAPPING}
        return address
    except requests.RequestException as e:
        raise GeocodeError(f"Unable to geocode '{location_raw}' (unable to reverse geocode '{title}' lat: {lat} lng: {lng})") from e


def get_region(address):
    if address['country'].lower().startswith('česk'):
        region = address['region']
    else:
        region = address['country']
    return REGIONS_MAPPING.get(region, region)


if __name__ == '__main__':
    """
    Usage:

        poetry run python -m juniorguru.sync.jobs.pipelines.locations 'Brno, South Moravia'
    """
    import sys
    from pprint import pprint

    location_raw = sys.argv[1]
    print('geocode()')
    pprint(geocode_mapycz(location_raw))
    print('---\nprocess()')
    pprint(process({'locations_raw': [location_raw]}))
