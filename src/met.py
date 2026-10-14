"""The Metropolitan Museum of Art Open Access Collection (Course 5: Visual Garnish)."""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Callable, Optional

import requests

from .config import Source

log = logging.getLogger(__name__)

USER_AGENT = "BaconsBento/1.0 (+https://t.me/baconbento)"
DEFAULT_ENDPOINT = "https://collectionapi.metmuseum.org/public/collection/v1"


@dataclass
class MetArtwork:
    object_id: int
    title: str
    artist: str
    date: str
    medium: str
    department: str
    object_url: str
    image_url: str


def fetch_met_artwork(
    source: Source,
    is_seen: Optional[Callable[[int], bool]] = None,
    session: Optional[requests.Session] = None,
    max_tries: int = 15,
) -> Optional[MetArtwork]:
    """Fetch an unseen, high-res CC0 highlight from The Met Open Access API."""
    sess = session or requests
    endpoint = source.endpoint or DEFAULT_ENDPOINT
    dept_ids = source.config.get("department_ids", [6, 9, 11, 17, 21])
    dept_id = random.choice(dept_ids)

    objects_url = f"{endpoint}/objects"
    params = {"departmentIds": str(dept_id)}

    try:
        resp = sess.get(objects_url, params=params, headers={"User-Agent": USER_AGENT}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        object_ids = data.get("objectIDs") or []
        if not object_ids:
            log.warning("No Met objects found for dept %d", dept_id)
            return None

        # Filter seen and sample candidates
        if is_seen:
            candidates = [oid for oid in object_ids if not is_seen(oid)]
        else:
            candidates = object_ids

        if not candidates:
            log.info("All Met highlights in dept %d already seen; using pool", dept_id)
            candidates = object_ids

        random.shuffle(candidates)

        for oid in candidates[:max_tries]:
            obj_url = f"{endpoint}/objects/{oid}"
            obj_resp = sess.get(obj_url, headers={"User-Agent": USER_AGENT}, timeout=15)
            if obj_resp.status_code != 200:
                continue
            item = obj_resp.json()

            # Must have public domain CC0 image
            image_url = item.get("primaryImage") or item.get("primaryImageSmall")
            if not image_url or not item.get("isPublicDomain", True):
                continue

            title = item.get("title") or "Untitled"
            artist = item.get("artistDisplayName") or "Unknown Artist"
            date = item.get("objectDate") or ""
            medium = item.get("medium") or ""
            department = item.get("department") or ""
            url = item.get("objectURL") or f"https://www.metmuseum.org/art/collection/search/{oid}"

            return MetArtwork(
                object_id=oid,
                title=title,
                artist=artist,
                date=date,
                medium=medium,
                department=department,
                object_url=url,
                image_url=image_url,
            )
        log.warning("Exhausted Met candidate attempts without finding valid image")
        return None
    except Exception as exc:
        log.warning("Met API fetch failed: %s", exc)
        return None
