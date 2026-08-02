# -*- coding: utf-8 -*-
"""
Pixiv 랭킹 이미지 위젯 플러그인 (BookOasis metadata plugin)

- 대시보드에 pixiv 일간/주간/월간 랭킹 이미지를 카드 형태로 노출합니다.
- PHPSESSID(pixiv 로그인 세션 쿠키)를 플러그인 설정에서 입력해야 동작합니다.
- 외부 패키지(requests) 의존성 없이 파이썬 표준 라이브러리(urllib)만 사용합니다.
- logging 모듈로 각 단계 진행상황을 서버 로그에 남겨 문제 진단이 쉽도록 했습니다.

주의:
- pixiv 이용약관상 대량 크롤링/재배포는 금지되어 있으니 개인 열람용으로만 사용하십시오.
- 이 플러그인은 코어 계약(search/apply/get_dashboard_data)만 사용하며,
  코어 수정 없이 plugins/metadata/pixiv_ranking/ 아래 코드만으로 동작합니다.
"""

import json
import logging
import re
import urllib.request
import urllib.error
import urllib.parse

from plugins.metadata.base import BaseMetadataProvider

logger = logging.getLogger("plugin.pixiv_ranking")


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

    _USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    _REFERER = "https://www.pixiv.net/"
    _TIMEOUT = 10

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
    # 내부 구현 (urllib 기반, 외부 패키지 불필요)
    # ---------------------------------------------------------------
    def _http_get(self, url, cookies=None):
        req = urllib.request.Request(url)
        req.add_header("User-Agent", self._USER_AGENT)
        req.add_header("Referer", self._REFERER)
        if cookies:
            cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())
            req.add_header("Cookie", cookie_header)

        with urllib.request.urlopen(req, timeout=self._TIMEOUT) as res:
            charset = res.headers.get_content_charset() or "utf-8"
            body = res.read().decode(charset, errors="replace")
            return res.status, body, dict(res.headers)

    def _fetch_items(self, db_type, limit=10):
        cfg = self.get_plugin_config(db_type, default={})
        phpsessid = cfg.get("PHPSESSID")
        mode = cfg.get("RANKING_MODE", "daily")
        image_size = cfg.get("IMAGE_SIZE", "regular")

        logger.info(
            "[pixiv_ranking] 설정 로드: mode=%s, image_size=%s, PHPSESSID 설정됨=%s",
            mode, image_size, bool(phpsessid),
        )

        try:
            fetch_limit = int(cfg.get("FETCH_LIMIT", limit) or limit)
        except (TypeError, ValueError):
            fetch_limit = limit
        fetch_limit = max(1, min(fetch_limit, 50))

        if not phpsessid:
            logger.warning("[pixiv_ranking] PHPSESSID가 비어있음 - 플러그인 설정을 저장했는지 확인 필요")
            return {
                "success": False,
                "error": "PHPSESSID가 설정되지 않았습니다. 플러그인 설정에서 pixiv 로그인 세션 쿠키를 입력하고 저장하십시오.",
            }

        cookies = {"PHPSESSID": phpsessid}

        illust_ids = self._get_ranking_illust_ids(mode, cookies, fetch_limit)
        logger.info("[pixiv_ranking] 랭킹 페이지에서 작품 ID %d개 추출", len(illust_ids))

        if not illust_ids:
            # 요청은 성공했지만(200) 작품 ID가 하나도 안 잡힌 경우
            # -> 대부분 PHPSESSID 만료/무효 또는 로그인 페이지로 리다이렉트된 경우입니다.
            return {
                "success": False,
                "error": (
                    "랭킹 페이지에서 작품을 하나도 찾지 못했습니다. "
                    "PHPSESSID가 만료되었거나 잘못됐을 가능성이 높습니다. "
                    "브라우저에서 pixiv에 다시 로그인한 뒤 새 PHPSESSID 값으로 갱신해 저장해 보십시오."
                ),
            }

        items = []
        for illust_id in illust_ids[:fetch_limit]:
            detail = self._get_illust_detail(illust_id, cookies)
            if not detail:
                logger.warning("[pixiv_ranking] illust_id=%s 상세 조회 실패, 건너뜀", illust_id)
                continue
            items.append(detail_to_item(detail, illust_id, image_size))

        logger.info("[pixiv_ranking] 최종 아이템 %d개 구성 완료", len(items))

        if not items:
            return {
                "success": False,
                "error": "작품 ID는 찾았지만 상세 이미지 정보를 하나도 가져오지 못했습니다. PHPSESSID 유효성을 확인해 주세요.",
            }

        return {"success": True, "items": items}

    def _get_ranking_illust_ids(self, mode, cookies, limit):
        params = urllib.parse.urlencode({"mode": mode})
        url = f"https://www.pixiv.net/ranking.php?{params}"
        logger.info("[pixiv_ranking] 랭킹 페이지 요청: %s", url)

        try:
            status, body, resp_headers = self._http_get(url, cookies=cookies)
        except urllib.error.HTTPError as e:
            logger.error("[pixiv_ranking] 랭킹 페이지 HTTP 에러: %s %s", e.code, e.reason)
            raise RuntimeError(f"랭킹 페이지 요청 실패 (HTTP {e.code}): {e.reason}")
        except urllib.error.URLError as e:
            logger.error("[pixiv_ranking] 랭킹 페이지 접속 실패: %s", e.reason)
            raise RuntimeError(
                f"랭킹 페이지 접속 실패: {e.reason} "
                "(서버의 외부 인터넷/DNS 접근이 막혀있는지 확인해 보십시오.)"
            )

        logger.info("[pixiv_ranking] 랭킹 페이지 응답 status=%s, 길이=%d bytes", status, len(body))

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
            status, body, _ = self._http_get(url, cookies=cookies)
        except urllib.error.URLError as e:
            logger.warning("[pixiv_ranking] illust_id=%s 요청 실패: %s", illust_id, e)
            return None

        try:
            data = json.loads(body)
        except (ValueError, TypeError):
            logger.warning("[pixiv_ranking] illust_id=%s 응답 JSON 파싱 실패", illust_id)
            return None

        if data.get("error"):
            logger.warning(
                "[pixiv_ranking] illust_id=%s API 에러 응답: %s", illust_id, data.get("message")
            )
            return None

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
