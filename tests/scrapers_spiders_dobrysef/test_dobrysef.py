from datetime import date
from pathlib import Path

import pytest
from scrapy.http import XmlResponse, HtmlResponse

from juniorguru.scrapers.spiders import dobrysef


FIXTURES_DIR = Path(__file__).parent


def test_spider_parse():
    response = XmlResponse('https://example.com/example/',
                           body=Path(FIXTURES_DIR / 'jobposts.json').read_bytes())
    requests = list(dobrysef.Spider().parse(response))

    assert len(requests) == 7


def test_spider_parse_job():
    response = XmlResponse('https://example.com/example/',
                           body=Path(FIXTURES_DIR / 'jobposts.json').read_bytes())
    job = list(dobrysef.Spider().parse_job(response, response.json()[2]))[0]

    assert sorted(job.keys()) == sorted([
        'title', 'link', 'company_name', 'company_link', 'employment_types',
        'posted_at', 'description_html', 'company_logo_urls', 'remote',
        'locations_raw',
    ])
    assert job['title'] == 'Datový Architekt'
    assert job['link'] == 'https://dobrysef.cz/prace/datovy-architekt-eu6p/'
    assert job['locations_raw'] == ['Praha']
    assert job['employment_types'] == ['full time']
    assert job['company_name'] == 'Firma jen na oko'
    assert job['company_link'] == 'https://dobrysef.cz/firmy/firma-jen-na-oko/'
    assert job['remote'] is False
    assert job['posted_at'] == date(2021, 1, 30)
    assert job['company_logo_urls'] == ['https://dobrysef.cz/media/pub/brand/firma-jen-na-oko-logo.png']
    assert '<li>V kanceláři máme k dispozici občerstvení' in job['description_html']


def test_spider_parse_job_junior():
    response = XmlResponse('https://example.com/example/',
                           body=Path(FIXTURES_DIR / 'jobposts-junior.json').read_bytes())
    job = list(dobrysef.Spider().parse_job(response, response.json()[0]))[0]

    assert 'junior' in job['description_html']

def test_spider_parse_job_multi_cities():
    response = XmlResponse('https://example.com/example/',
                           body=Path(FIXTURES_DIR / 'jobposts-multi-cities.json').read_bytes())
    job = list(dobrysef.Spider().parse_job(response, response.json()[0]))[0]

    assert job['locations_raw'] == ['Děčín', 'Havířov']

def test_spider_parse_job_employment_types():
    response = XmlResponse('https://example.com/example/',
                           body=Path(FIXTURES_DIR / 'jobposts-employment-types.json').read_bytes())
    job = list(dobrysef.Spider().parse_job(response, response.json()[0]))[0]

    assert job['employment_types'] == ['full time', 'part time']

def test_spider_parse_job_contract():
    response = XmlResponse('https://example.com/example/',
                           body=Path(FIXTURES_DIR / 'jobposts-contract.json').read_bytes())
    job = list(dobrysef.Spider().parse_job(response, response.json()[0]))[0]

    assert job['employment_types'] == ['full time', 'part time', 'contract']
