"""Skånsom HTTP-klient mot Finn.no.

Designet for å unngå å belaste Finn.no unødig og for å oppdage/gi opp pent
ved tegn på blokkering, i stedet for å presse på. Se README for hvorfor
frekvens og volum er holdt lavt -- Finn.no sin robots.txt ber eksplisitt om
skriftlig samtykke for automatisert/systematisk bruk, noe dette prosjektet
er et bevisst, lavvolums avvik fra (personlig bruk, ikke videresalg av data).
"""

import logging
import random
import time
import urllib.robotparser
from urllib.parse import urlparse

import requests

from src import config

logger = logging.getLogger(__name__)


class BlockedError(RuntimeError):
    """Reist når Finn.no svarer med 403/429 etter alle retry-forsøk."""


class FinnClient:
    def __init__(self):
        self._session = requests.Session()
        self._user_agent = random.choice(config.USER_AGENTS)
        self._session.headers.update(
            {
                "User-Agent": self._user_agent,
                "Accept-Language": "nb-NO,nb;q=0.9,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )
        self._request_count = 0
        self._robots = self._load_robots()

    def _load_robots(self):
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url("https://www.finn.no/robots.txt")
        try:
            parser.read()
        except Exception:
            logger.warning("Klarte ikke å lese robots.txt, fortsetter forsiktig")
            parser = None
        return parser

    def _check_allowed(self, url):
        if self._robots is None:
            return True
        path = urlparse(url).path
        return self._robots.can_fetch(self._user_agent, path)

    def _sleep_between_requests(self):
        if self._request_count > 0 and self._request_count % config.LONG_PAUSE_EVERY_N_REQUESTS == 0:
            pause = random.uniform(config.LONG_PAUSE_MIN_S, config.LONG_PAUSE_MAX_S)
            logger.info("Lang pause (%.1fs) etter %d kall", pause, self._request_count)
            time.sleep(pause)
        else:
            time.sleep(random.uniform(config.MIN_DELAY_S, config.MAX_DELAY_S))

    def get(self, url):
        """Henter en URL med forsinkelse, backoff ved 403/429, og robots-sjekk.

        Reiser BlockedError hvis Finn.no fortsatt svarer med blokkering etter
        alle retry-forsøk -- kalleren bør da avslutte hele kjøringen, ikke
        fortsette til neste søk.
        """
        if not self._check_allowed(url):
            raise BlockedError(f"robots.txt tillater ikke henting av {url}")

        self._sleep_between_requests()
        self._request_count += 1

        last_status = None
        for attempt, backoff in enumerate([0] + config.BACKOFF_SCHEDULE_S):
            if backoff:
                logger.warning("Fikk status %s, venter %ss før nytt forsøk", last_status, backoff)
                time.sleep(backoff)
            response = self._session.get(url, timeout=config.REQUEST_TIMEOUT_S)
            if response.status_code == 200:
                return response
            if response.status_code in (403, 429):
                last_status = response.status_code
                continue
            response.raise_for_status()

        raise BlockedError(
            f"Blokkert av Finn.no (status {last_status}) etter {len(config.BACKOFF_SCHEDULE_S)} forsøk på {url}"
        )

    @property
    def request_count(self):
        return self._request_count
