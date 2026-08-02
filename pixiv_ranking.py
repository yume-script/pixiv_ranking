# -*- coding: utf-8 -*-
"""
Pixiv 랭킹 이미지 위젯 플러그인 (BookOasis metadata plugin)

- 대시보드에 pixiv 일간/주간/월간 랭킹 이미지를 카드 형태로 노출합니다.
- PHPSESSID(pixiv 로그인 세션 쿠키)를 플러그인 설정에서 입력해야 동작합니다.

주의:
- pixiv 이용약관상 대량 크롤링/재배포는 금지되어 있으니 개인 열람용으로만 사용하십시오.
- 이 플러그인은 코어 계약(search/apply/get_dashboard_data)만 사용하며,
  코어 수정 없이 plugins/metadata/pixiv_ranking/ 아래 코드만으로 동작합니다.
"""

import re
import requests

from plugins.metadata.base import BaseMetadataProvider


class PixivRankingMetadataProvider(BaseMetadataProvider):
    id = "pixiv_ranking"
    name = "Pixiv 랭킹"
    is_searchable = False

    config_schema = [
        {
            "key": "PHPSESSID",
            "label": "PHPSESSID (pixiv 로그인 세션 쿠키)",
            "type": "password",
            "required": True,
        },
        {
            "key": "RANKING_MODE",
            "label": "랭킹 종류",
            "type": "select",
            "default": "daily",
            "options": [
                {"value": "daily", "label": "일간"},
                {"value": "weekly", "label": "주간"},
                {"value": "monthly", "label": "월간"},
                {"value": "rookie", "label": "신인"},
                {"value": "original", "label": "오리지널"},
                {"value": "male", "label": "남자에게 인기"},
                {"value": "female", "label": "여자에게 인기"},
            ],
        },
        {
            "key": "IMAGE_SIZE",
            "label": "이미지 크기",
            "type": "select",
            "default": "regular",
            "options": [
                {"value": "regular", "label": "적당한 크기 (권장)"},
                {"value": "original", "label": "원본 (용량 큼)"},
                {"value": "small", "label": "작게 (썸네일)"},
            ],
        },
        {
            "key": "FETCH_LIMIT",
            "label": "가져올 이미지 개수",
            "type": "number",
            "default": 10,
        },
    ]

    dashboard_widget = {
        "title": "Pixiv 랭킹",
        "subtitle": "pixiv 랭킹 이미지",
        "provider": "pixiv",
        "icon": "fa-solid fa-image",
        "limit": 10,
        "supported_types": ["general"],
    }

    update_manifest = {
        "enabled": True,
        "provider": "github-raw",
        # 실제 배포 리포지토리 경로로 수정해서 사용하십시오.
        "raw_base_url": "https://raw.githubusercontent.com/<org>/<repo>/main/plugins/metadata/pixiv_ranking",
        "files": ["pixiv_ranking.py", "__init__.py", "VERSION"],
        "version_file": "VERSION",
        "version_key": "plugin version",
        "show_sample_update_button": True,
    }

    _headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.pixiv.net/",
    }

    # ---------------------------------------------------------------
    # 코어 필수 계약
    # ---------------------------------------------------------------
    def search(self, db_type, query):
        # 이 플러그인은 메타데이터 검색용이 아닌 대시보드 전용이므로 빈 결과를 반환합니다.
        return {"success": True, "items": []}

    def apply(self, db_type, book_id, item_data):
        return False, "Pixiv 랭킹 플러그인은 대시보드 전용이며 apply를 지원하지 않습니다."

    # ---------------------------------------------------------------
    # 대시보드 계약
    # ---------------------------------------------------------------
    def get_dashboard_data(self, db_type, limit=10):
        try:
            return self._fetch_items(db_type, limit=limit)
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ---------------------------------------------------------------
    # 내부 구현
    # ---------------------------------------------------------------
    def _fetch_items(self, db_type, limit=10):
        cfg = self.get_plugin_config(db_type, default={})
        phpsessid = cfg.get("PHPSESSID")
        mode = cfg.get("RANKING_MODE", "daily")
        image_size = cfg.get("IMAGE_SIZE", "regular")

        try:
            fetch_limit = int(cfg.get("FETCH_LIMIT", limit) or limit)
        except (TypeError, ValueError):
            fetch_limit = limit
        fetch_limit = max(1, min(fetch_limit, 50))

        if not phpsessid:
            return {
                "success": False,
                "error": "PHPSESSID가 설정되지 않았습니다. 플러그인 설정에서 pixiv 로그인 세션 쿠키를 입력하십시오.",
            }

        cookies = {"PHPSESSID": phpsessid}

        illust_ids = self._get_ranking_illust_ids(mode, cookies, fetch_limit)
        if not illust_ids:
            return {"success": True, "items": []}

        items = []
        for illust_id in illust_ids[:fetch_limit]:
            detail = self._get_illust_detail(illust_id, cookies)
            if not detail:
                continue
            items.append(detail_to_item(detail, illust_id, image_size))

        return {"success": True, "items": items}

    def _get_ranking_illust_ids(self, mode, cookies, limit):
        url = "https://www.pixiv.net/ranking.php"
        params = {"mode": mode}

        res = requests.get(
            url, params=params, headers=self._headers, cookies=cookies, timeout=10
        )
        res.raise_for_status()

        ids = re.findall(r"/artworks/(\d+)", res.text)
        seen = set()
        ordered_ids = []
        for x in ids:
            if x not in seen:
                seen.add(x)
                ordered_ids.append(x)
            if len(ordered_ids) >= limit:
                break
        return ordered_ids

    def _get_illust_detail(self, illust_id, cookies):
        url = f"https://www.pixiv.net/ajax/illust/{illust_id}"
        res = requests.get(url, headers=self._headers, cookies=cookies, timeout=10)
        if res.status_code != 200:
            return None
        data = res.json()
        return data.get("body")


def detail_to_item(body, illust_id, image_size):
    urls = body.get("urls", {}) or {}
    image_url = urls.get(image_size) or urls.get("regular") or urls.get("original")

    return {
        "title": body.get("illustTitle") or f"작품 {illust_id}",
        "author": body.get("userName"),
        "image_url": image_url,
        "url": f"https://www.pixiv.net/artworks/{illust_id}",
        "illust_id": illust_id,
    }
