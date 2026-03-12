"""
Physics Wallah API Wrapper
Handles authentication, batch/content extraction, and video URL resolution.
"""

import aiohttp
import asyncio
import uuid
from typing import Optional, Callable

BASE_URL = "https://api.penpencil.co"
BRIGHTCOVE_BASE = "https://edge.api.brightcove.com/playback/v1"

CLIENT_ID = "5eb393ee95fab7468a79d189"
CLIENT_SECRET = "9ae3c8a7-d2cf-4e63-aa28-c5c73e5e8ae7"
BRIGHTCOVE_ACCOUNT_ID = "5107479782001"
BRIGHTCOVE_POLICY_KEY = (
    "BCpkADawqM1W-vUOMe6RSA3pA6Vw-VR1Ms34pODUl2rQI09G-aUrEIk4VMxKtbG3dISNjE4"
    "Q_eLnkMhigMwPCbY3jqQKPkwJN_l0mMwD7yqp8WMY1d_QLGC9EkeTUEDdHzrG7Uy0WVE"
)


def _default_headers(token: Optional[str] = None) -> dict:
    headers = {
        "client-id": CLIENT_ID,
        "client-secret": CLIENT_SECRET,
        "client-type": "WEB",
        "randomid": str(uuid.uuid4()),
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 11; Pixel 4) "
            "AppleWebKit/537.36 Chrome/88.0.4324.93 Mobile Safari/537.36"
        ),
    }
    if token:
        headers["authorization"] = f"Bearer {token}"
    return headers


class PWApi:
    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Auth ──────────────────────────────────────────────────────────────

    async def send_otp(self, mobile: str) -> dict:
        session = await self._get_session()
        url = f"{BASE_URL}/v3/users/get-otp"
        payload = {
            "mobile": mobile,
            "countryCode": "+91",
            "organizationId": CLIENT_ID,
        }
        async with session.post(url, json=payload, headers=_default_headers()) as r:
            return await r.json()

    async def verify_otp(self, mobile: str, otp: str) -> dict:
        session = await self._get_session()
        url = f"{BASE_URL}/v3/users/login"
        payload = {
            "mobile": mobile,
            "otp": otp,
            "countryCode": "+91",
            "organizationId": CLIENT_ID,
        }
        async with session.post(url, json=payload, headers=_default_headers()) as r:
            return await r.json()

    # ── Batches ───────────────────────────────────────────────────────────

    async def get_all_batches(self, token: str) -> list:
        session = await self._get_session()
        all_batches = []
        page = 1
        while True:
            url = f"{BASE_URL}/v3/batches/my-batches"
            params = {"page": page, "limit": 100}
            async with session.get(url, params=params, headers=_default_headers(token)) as r:
                resp = await r.json()
            items = resp.get("data", []) or []
            if not items:
                break
            all_batches.extend(items)
            if len(items) < 100:
                break
            page += 1
        return all_batches

    # ── Subjects ──────────────────────────────────────────────────────────

    async def get_subjects(self, token: str, batch_id: str) -> list:
        session = await self._get_session()
        url = f"{BASE_URL}/v3/batches/{batch_id}/subject"
        async with session.get(url, headers=_default_headers(token)) as r:
            resp = await r.json()
        return resp.get("data", []) or []

    # ── Topics ────────────────────────────────────────────────────────────

    async def get_all_topics(self, token: str, batch_id: str, subject_slug: str) -> list:
        session = await self._get_session()
        all_topics = []
        page = 1
        while True:
            url = f"{BASE_URL}/v3/batches/{batch_id}/subject/{subject_slug}/topics"
            params = {"page": page, "limit": 100}
            async with session.get(url, params=params, headers=_default_headers(token)) as r:
                resp = await r.json()
            items = resp.get("data", []) or []
            if not items:
                break
            all_topics.extend(items)
            if len(items) < 100:
                break
            page += 1
        return all_topics

    # ── Contents ──────────────────────────────────────────────────────────

    async def get_topic_contents(
        self, token: str, batch_id: str, subject_slug: str,
        topic_slug: str, content_type: str = "videos"
    ) -> list:
        session = await self._get_session()
        all_items = []
        page = 1
        while True:
            url = (
                f"{BASE_URL}/v3/batches/{batch_id}/subject"
                f"/{subject_slug}/topics/{topic_slug}/contents"
            )
            params = {"page": page, "contentType": content_type, "limit": 100}
            async with session.get(url, params=params, headers=_default_headers(token)) as r:
                resp = await r.json()
            items = resp.get("data", []) or []
            if not items:
                break
            all_items.extend(items)
            if len(items) < 100:
                break
            page += 1
            await asyncio.sleep(0.15)
        return all_items

    # ── Video URL Resolution ───────────────────────────────────────────────

    async def resolve_video_url(self, token: str, content_item: dict) -> Optional[str]:
        """
        Attempt to resolve a playable URL for a content item.
        Priority: YouTube > Brightcove HLS > direct URL
        """
        vd = content_item.get("videoDetails") or {}

        # YouTube embed
        yt_id = vd.get("ytId") or content_item.get("ytId")
        if yt_id:
            return f"https://www.youtube.com/watch?v={yt_id}"

        # Direct URL in content
        direct = (
            content_item.get("url")
            or vd.get("videoUrl")
            or content_item.get("homeworkPdfLink")
        )
        if direct and ("youtube.com" in direct or "youtu.be" in direct):
            return direct

        # Brightcove
        bc_id = vd.get("bcVideoId") or content_item.get("bcVideoId")
        if bc_id:
            url = await self._brightcove_hls(token, bc_id)
            if url:
                return url

        # Fallback direct URL
        if direct:
            return direct

        return None

    async def _brightcove_hls(self, token: str, video_id: str) -> Optional[str]:
        session = await self._get_session()
        # Try PW signed-URL endpoint first
        signed_jwt = None
        try:
            url = f"{BASE_URL}/v1/videos/brightcove/signed-url"
            async with session.get(
                url, params={"videoId": video_id}, headers=_default_headers(token)
            ) as r:
                r_data = await r.json()
                signed_jwt = (
                    r_data.get("data", {}).get("signedUrl")
                    or r_data.get("signedUrl")
                )
        except Exception:
            pass

        bc_url = f"{BRIGHTCOVE_BASE}/accounts/{BRIGHTCOVE_ACCOUNT_ID}/videos/{video_id}"
        bc_headers = {"Accept": f"application/json;pk={BRIGHTCOVE_POLICY_KEY}"}
        if signed_jwt:
            bc_headers["Authorization"] = f"Bearer {signed_jwt}"

        try:
            async with session.get(bc_url, headers=bc_headers) as r:
                bc_data = await r.json()
                sources = bc_data.get("sources", [])
                for src in sources:
                    if src.get("type") == "application/x-mpegURL" and src.get("src"):
                        return src["src"]
                for src in sources:
                    if src.get("src"):
                        return src["src"]
        except Exception:
            pass
        return None

    # ── Full Deep Extraction ───────────────────────────────────────────────

    async def extract_batch_json(
        self, token: str, batch: dict, progress_cb: Optional[Callable] = None
    ) -> dict:
        batch_id = batch.get("_id") or batch.get("id", "")
        batch_name = batch.get("name", "Unknown Batch")

        result = {
            "batch_id": batch_id,
            "batch_name": batch_name,
            "batch_slug": batch.get("slug", ""),
            "language": batch.get("language", ""),
            "subjects": [],
        }

        if progress_cb:
            await progress_cb(f"📦 Processing *{batch_name}*...")

        subjects = await self.get_subjects(token, batch_id)

        for subj in subjects:
            subj_slug = subj.get("slug") or subj.get("_id", "")
            subj_name = subj.get("subject", subj.get("name", "Unknown"))

            if progress_cb:
                await progress_cb(f"  📚 Subject: {subj_name}")

            subj_data = {
                "subject_id": subj.get("_id", ""),
                "subject_name": subj_name,
                "subject_slug": subj_slug,
                "topics": [],
            }

            topics = await self.get_all_topics(token, batch_id, subj_slug)

            for topic in topics:
                topic_slug = topic.get("slug") or topic.get("_id", "")
                topic_name = topic.get("name", "Unknown Topic")

                topic_data = {
                    "topic_id": topic.get("_id", ""),
                    "topic_name": topic_name,
                    "topic_slug": topic_slug,
                    "videos": [],
                    "notes": [],
                    "dpp": [],
                }

                for ctype, key in [("videos", "videos"), ("notes", "notes"), ("DppNotes", "dpp")]:
                    items = await self.get_topic_contents(
                        token, batch_id, subj_slug, topic_slug, ctype
                    )
                    for item in items:
                        vd = item.get("videoDetails") or {}
                        topic_data[key].append({
                            "id": item.get("_id", ""),
                            "title": item.get("topic") or item.get("name", "Untitled"),
                            "duration_sec": vd.get("duration", 0),
                            "brightcove_id": vd.get("bcVideoId", ""),
                            "youtube_id": vd.get("ytId", ""),
                            "direct_url": item.get("url") or vd.get("videoUrl") or item.get("homeworkPdfLink", ""),
                            "is_drm": item.get("isDrmProtected", False),
                            "created_at": item.get("createdAt", ""),
                        })

                subj_data["topics"].append(topic_data)
                await asyncio.sleep(0.1)

            result["subjects"].append(subj_data)

        return result
