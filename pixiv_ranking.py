# -*- coding: utf-8 -*-
"""
Pixiv 랭킹 이미지 위젯 플러그인 (BookOasis metadata plugin)

- [플러그인] 카테고리의 독립된 단독 탭(all_desk_tab)으로 렌더링됩니다.
- 설정에서 체크한 여러 랭킹 종류(일간/주간/월간 등)를 한 번에 가져와
  제목 앞에 [일간]/[주간] 라벨을 붙여 하나의 목록으로 함께 보여줍니다.
  (코어가 위젯 내부의 실시간 탭 전환 UI를 지원하지 않아, index.html/script.js는
   설정 화면에만 적용되고 실제 위젯 화면에는 반영되지 않습니다 - 가이드 4절 참고)
- PHPSESSID(pixiv 로그인 세션 쿠키)를 플러그인 설정에서 입력해야 동작합니다.
- 외부 패키지(requests) 의존성 없이 파이썬 표준 라이브러리(urllib)만 사용합니다.
- 이미지 서버(i.pximg.net)의 Referer 핫링크 차단을 우회하기 위해
  서버에서 이미지를 직접 내려받아 base64 data URI로 임베드합니다.

주의:
- pixiv 이용약관상 대량 크롤링/재배포는 금지되어 있으니 개인 열람용으로만 사용하십시오.
"""

import base64
import json
import logging
import re
import urllib.request
import urllib.error
import urllib.parse

from plugins.metadata.base import BaseMetadataProvider

logger = logging.getLogger("plugin.pixiv_ranking")

# 표시 라벨 매핑
_MODE_LABELS = {
    "daily": "일간",
    "weekly": "주간",
    "monthly": "월간",
    "rookie": "신인",
    "original": "오리지널",
    "male": "남자인기",
    "female": "여자인기",
}


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
        {"key": "SHOW_DAILY", "label": "일간 랭킹 표시", "type": "checkbox", "default": True},
        {"key": "SHOW_WEEKLY", "label": "주간 랭킹 표시", "type": "checkbox", "default": True},
        {"key": "SHOW_MONTHLY", "label": "월간 랭킹 표시", "type": "checkbox", "default": True},
        {"key": "SHOW_ROOKIE", "label": "신인 랭킹 표시", "type": "checkbox", "default": False},
        {"key": "SHOW_ORIGINAL", "label": "오리지널 랭킹 표시", "type": "checkbox", "default": False},
        {"key": "SHOW_MALE", "label": "남자에게 인기 표시", "type": "checkbox", "default": False},
        {"key": "SHOW_FEMALE", "label": "여자에게 인기 표시", "type": "checkbox", "default": False},
        {
            "key": "IMAGE_SIZE",
            "label": "이미지 크기",
            "type": "select",
            "default": "small",
            "options": [
                {"value": "small", "label": "작게 (권장, 빠름)"},
                {"value": "regular", "label": "적당한 크기"},
                {"value": "original", "label": "원본 (매우 느림/용량 큼, 비권장)"},
            ],
        },
        {
            "key": "PER_MODE_LIMIT",
            "label": "랭킹 종류별 가져올 이미지 개수",
            "type": "number",
            "default": 8,
        },
    ]

    dashboard_widget = {
        "title": "Pixiv 랭킹",
        "subtitle": "pixiv 랭킹 이미지",
        "provider": "pixiv",
        "icon": "fa-solid fa-image",
        "limit": 60,
        "all_desk_tab": True,  # 공통 데스크 카드가 아닌 [플러그인] 카테고리 단독 전체화면 탭으로 렌더링
        "supported_types": ["general"],
    }

    update_manifest = {
        "enabled": True,
        "provider": "github-raw",
        "raw_base_url": "https://raw.githubusercontent.com/<org>/<repo>/main/plugins/metadata/pixiv_ranking",
        "files": ["pixiv_ranking.py", "__init__.py", "VERSION"],
        "version_file": "VERSION",
        "version_key": "plugin version",
        "show_sample_update_button": True,
    }

    _USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    _REFERER = "https://www.pixiv.net/"
    _TIMEOUT = 10
    _MAX_IMAGE_BYTES = 3 * 1024 * 1024
    _MAX_TOTAL_ITEMS = 60

    # ---------------------------------------------------------------
    # 코어 필수 계약
    # ---------------------------------------------------------------
    def search(self, db_type, query):
        return {"success": True, "items": []}

    def apply(self, db_type, book_id, item_data):
        return False, "Pixiv 랭킹 플러그인은 대시보드 전용이며 apply를 지원하지 않습니다."

    # ---------------------------------------------------------------
    # 대시보드 계약
    # ---------------------------------------------------------------
    def get_dashboard_data(self, db_type, limit=10):
        logger.info("[pixiv_ranking] get_dashboard_data 호출 (db_type=%s, limit=%s)", db_type, limit)
        try:
            result = self._fetch_items(db_type, limit=limit)
            logger.info(
                "[pixiv_ranking] 결과: success=%s, items=%s",
                result.get("success"),
                len(result.get("items", [])) if result.get("success") else "-",
            )
            return result
        except Exception as e:
            logger.exception("[pixiv_ranking] get_dashboard_data 처리 중 예외 발생")
            return {"success": False, "error": str(e)}

    # ---------------------------------------------------------------
    # 내부 구현
    # ---------------------------------------------------------------
    def _http_get_text(self, url, cookies=None):
        req = urllib.request.Request(url)
        req.add_header("User-Agent", self._USER_AGENT)
        req.add_header("Referer", self._REFERER)
        if cookies:
            cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())
            req.add_header("Cookie", cookie_header)

        with urllib.request.urlopen(req, timeout=self._TIMEOUT) as res:
            charset = res.headers.get_content_charset() or "utf-8"
            body = res.read().decode(charset, errors="replace")
            return res.status, body

    def _http_get_bytes(self, url, cookies=None):
        req = urllib.request.Request(url)
        req.add_header("User-Agent", self._USER_AGENT)
        req.add_header("Referer", self._REFERER)
        if cookies:
            cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())
            req.add_header("Cookie", cookie_header)

        with urllib.request.urlopen(req, timeout=self._TIMEOUT) as res:
            content_type = res.headers.get_content_type() or "image/jpeg"
            raw = res.read()
            return res.status, content_type, raw

    def _fetch_items(self, db_type, limit=10):
        cfg = self.get_plugin_config(db_type, default={})
        phpsessid = cfg.get("PHPSESSID")
        image_size = cfg.get("IMAGE_SIZE", "small")

        if not phpsessid:
            logger.warning("[pixiv_ranking] PHPSESSID가 비어있음")
            return {
                "success": False,
                "error": "PHPSESSID가 설정되지 않았습니다. 플러그인 설정에서 pixiv 로그인 세션 쿠키를 입력하고 저장하십시오.",
            }

        try:
            per_mode_limit = int(cfg.get("PER_MODE_LIMIT", 8) or 8)
        except (TypeError, ValueError):
            per_mode_limit = 8
        per_mode_limit = max(1, min(per_mode_limit, 30))

        enabled_modes = []
        mode_flags = [
            ("daily", "SHOW_DAILY", True),
            ("weekly", "SHOW_WEEKLY", True),
            ("monthly", "SHOW_MONTHLY", True),
            ("rookie", "SHOW_ROOKIE", False),
            ("original", "SHOW_ORIGINAL", False),
            ("male", "SHOW_MALE", False),
            ("female", "SHOW_FEMALE", False),
        ]
        for mode, key, default in mode_flags:
            if cfg.get(key, default):
                enabled_modes.append(mode)

        if not enabled_modes:
            return {
                "success": False,
                "error": "표시할 랭킹 종류가 하나도 선택되지 않았습니다. 플러그인 설정에서 최소 1개 이상 체크해 주세요.",
            }

        cookies = {"PHPSESSID": phpsessid}

        items = []
        for mode in enabled_modes:
            if len(items) >= self._MAX_TOTAL_ITEMS:
                break
            mode_label = _MODE_LABELS.get(mode, mode)
            illust_ids = self._get_ranking_illust_ids(mode, cookies, per_mode_limit)
            logger.info("[pixiv_ranking] [%s] 작품 ID %d개 추출", mode_label, len(illust_ids))

            for illust_id in illust_ids:
                if len(items) >= self._MAX_TOTAL_ITEMS:
                    break
                detail = self._get_illust_detail(illust_id, cookies)
                if not detail:
                    logger.warning("[pixiv_ranking] [%s] illust_id=%s 상세 조회 실패, 건너뜀", mode_label, illust_id)
                    continue
                item = self._build_item(detail, illust_id, image_size, cookies, mode_label)
                items.append(item)

        logger.info("[pixiv_ranking] 최종 아이템 %d개 구성 완료 (모드: %s)", len(items), ", ".join(enabled_modes))

        if not items:
            return {
                "success": False,
                "error": "선택한 랭킹에서 이미지를 하나도 가져오지 못했습니다. PHPSESSID 유효성을 확인해 주세요.",
            }

        return {"success": True, "items": items}

    def _get_ranking_illust_ids(self, mode, cookies, limit):
        params = urllib.parse.urlencode({"mode": mode})
        url = f"https://www.pixiv.net/ranking.php?{params}"

        try:
            status, body = self._http_get_text(url, cookies=cookies)
        except urllib.error.HTTPError as e:
            logger.error("[pixiv_ranking] [%s] 랭킹 페이지 HTTP 에러: %s %s", mode, e.code, e.reason)
            return []
        except urllib.error.URLError as e:
            logger.error("[pixiv_ranking] [%s] 랭킹 페이지 접속 실패: %s", mode, e.reason)
            return []

        ids = re.findall(r"/artworks/(\d+)", body)
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
        try:
            status, body = self._http_get_text(url, cookies=cookies)
        except urllib.error.URLError as e:
            logger.warning("[pixiv_ranking] illust_id=%s 요청 실패: %s", illust_id, e)
            return None

        try:
            data = json.loads(body)
        except (ValueError, TypeError):
            logger.warning("[pixiv_ranking] illust_id=%s 응답 JSON 파싱 실패", illust_id)
            return None

        if data.get("error"):
            logger.warning("[pixiv_ranking] illust_id=%s API 에러 응답: %s", illust_id, data.get("message"))
            return None

        return data.get("body")

    def _build_item(self, body, illust_id, image_size, cookies, mode_label):
        urls = body.get("urls") or {}

        remote_url = None
        if isinstance(urls, dict):
            for key in (image_size, "regular", "small", "thumb", "mini", "original"):
                candidate = urls.get(key)
                if candidate:
                    remote_url = candidate
                    break

        image_value = remote_url

        if remote_url:
            try:
                status, content_type, raw = self._http_get_bytes(remote_url, cookies=cookies)
                if status == 200 and raw and len(raw) <= self._MAX_IMAGE_BYTES:
                    b64 = base64.b64encode(raw).decode("ascii")
                    image_value = f"data:{content_type};base64,{b64}"
            except Exception as e:
                logger.warning("[pixiv_ranking] illust_id=%s 이미지 다운로드 실패: %s", illust_id, e)

        raw_title = body.get("illustTitle") or f"작품 {illust_id}"
        title = f"[{mode_label}] {raw_title}"
        author = body.get("userName")
        artwork_url = f"https://www.pixiv.net/artworks/{illust_id}"

        return {
            "title": title,
            "author": author,
            "url": artwork_url,
            "link": artwork_url,
            "illust_id": illust_id,
            "category": mode_label,
            "cover": image_value,
            "cover_url": image_value,
            "image_url": image_value,
            "image": image_value,
            "thumbnail": image_value,
            "thumbnail_url": image_value,
            "src": image_value,
        }
