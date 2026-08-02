# -*- coding: utf-8 -*-
"""
Pixiv 랭킹 이미지 위젯 플러그인 (BookOasis metadata plugin)

- 대시보드에 pixiv 일간/주간/월간 랭킹 이미지를 카드 형태로 노출합니다.
- PHPSESSID(pixiv 로그인 세션 쿠키)를 플러그인 설정에서 입력해야 동작합니다.
- 외부 패키지(requests) 의존성 없이 파이썬 표준 라이브러리(urllib)만 사용합니다.
- logging 모듈로 각 단계 진행상황을 서버 로그에 남겨 문제 진단이 쉽도록 했습니다.

중요:
- pixiv의 이미지 서버(i.pximg.net)는 Referer 헤더가 없는 요청(브라우저의 일반 <img> 태그 포함)을
  차단합니다. 이 때문에 원본 이미지 URL을 그대로 프런트엔드에 내려주면 제목/텍스트는 보여도
  이미지만 깨지는 문제가 발생합니다.
- 이를 우회하기 위해 이 플러그인은 서버 쪽에서 Referer 헤더를 포함해 이미지를 직접 내려받은 뒤
  base64 data URI로 변환해서 응답합니다. 브라우저는 pixiv 서버에 전혀 접근하지 않으므로
  Referer 차단 문제가 발생하지 않습니다.
- 프런트엔드는 이 플러그인의 아이템을 "도서 카드"(cover/title/author/publisher)로 렌더링하므로
  이미지 필드는 'cover' 키를 최우선으로 채웁니다 (다른 후보 키도 동시에 채워 호환성 확보).

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
            "default": "small",
            "options": [
                {"value": "small", "label": "작게 (권장, 빠름)"},
                {"value": "regular", "label": "적당한 크기"},
                {"value": "original", "label": "원본 (매우 느림/용량 큼, 비권장)"},
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
        mode = cfg.get("RANKING_MODE", "daily")
        image_size = cfg.get("IMAGE_SIZE", "small")

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
            logger.warning("[pixiv_ranking] PHPSESSID가 비어있음")
            return {
                "success": False,
                "error": "PHPSESSID가 설정되지 않았습니다. 플러그인 설정에서 pixiv 로그인 세션 쿠키를 입력하고 저장하십시오.",
            }

        cookies = {"PHPSESSID": phpsessid}

        illust_ids = self._get_ranking_illust_ids(mode, cookies, fetch_limit)
        logger.info("[pixiv_ranking] 랭킹 페이지에서 작품 ID %d개 추출", len(illust_ids))

        if not illust_ids:
            return {
                "success": False,
                "error": (
                    "랭킹 페이지에서 작품을 하나도 찾지 못했습니다. "
                    "PHPSESSID가 만료되었거나 잘못됐을 가능성이 높습니다."
                ),
            }

        items = []
        for illust_id in illust_ids[:fetch_limit]:
            detail = self._get_illust_detail(illust_id, cookies)
            if not detail:
                logger.warning("[pixiv_ranking] illust_id=%s 상세 조회 실패, 건너뜀", illust_id)
                continue
            item = self._build_item(detail, illust_id, image_size, cookies)
            items.append(item)

        logger.info("[pixiv_ranking] 최종 아이템 %d개 구성 완료", len(items))

        if not items:
            return {
                "success": False,
                "error": "작품 ID는 찾았지만 상세 정보를 하나도 가져오지 못했습니다.",
            }

        return {"success": True, "items": items}

    def _get_ranking_illust_ids(self, mode, cookies, limit):
        params = urllib.parse.urlencode({"mode": mode})
        url = f"https://www.pixiv.net/ranking.php?{params}"
        logger.info("[pixiv_ranking] 랭킹 페이지 요청: %s", url)

        try:
            status, body = self._http_get_text(url, cookies=cookies)
        except urllib.error.HTTPError as e:
            logger.error("[pixiv_ranking] 랭킹 페이지 HTTP 에러: %s %s", e.code, e.reason)
            raise RuntimeError(f"랭킹 페이지 요청 실패 (HTTP {e.code}): {e.reason}")
        except urllib.error.URLError as e:
            logger.error("[pixiv_ranking] 랭킹 페이지 접속 실패: %s", e.reason)
            raise RuntimeError(f"랭킹 페이지 접속 실패: {e.reason}")

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
            logger.warning(
                "[pixiv_ranking] illust_id=%s API 에러 응답: %s", illust_id, data.get("message")
            )
            return None

        return data.get("body")

    def _build_item(self, body, illust_id, image_size, cookies):
        urls = body.get("urls") or {}

        # 진단용: 실제 urls 딕셔너리에 어떤 키가 들어있는지 항상 로그로 남김
        logger.info(
            "[pixiv_ranking] illust_id=%s urls 키 목록=%s",
            illust_id, list(urls.keys()) if isinstance(urls, dict) else type(urls),
        )

        remote_url = None
        if isinstance(urls, dict):
            for key in (image_size, "regular", "small", "thumb", "mini", "original"):
                candidate = urls.get(key)
                if candidate:
                    remote_url = candidate
                    break

        image_value = remote_url

        if not remote_url:
            logger.warning(
                "[pixiv_ranking] illust_id=%s remote_url을 찾지 못함 (urls=%s)", illust_id, urls
            )
        else:
            logger.info("[pixiv_ranking] illust_id=%s 이미지 다운로드 시도: %s", illust_id, remote_url)
            try:
                status, content_type, raw = self._http_get_bytes(remote_url, cookies=cookies)
                logger.info(
                    "[pixiv_ranking] illust_id=%s 이미지 응답 status=%s, content_type=%s, bytes=%d",
                    illust_id, status, content_type, len(raw) if raw else 0,
                )
                if status == 200 and raw:
                    if len(raw) > self._MAX_IMAGE_BYTES:
                        logger.warning(
                            "[pixiv_ranking] illust_id=%s 이미지 용량 초과(%d bytes) - base64 임베드 생략",
                            illust_id, len(raw),
                        )
                    else:
                        b64 = base64.b64encode(raw).decode("ascii")
                        image_value = f"data:{content_type};base64,{b64}"
                        logger.info(
                            "[pixiv_ranking] illust_id=%s 이미지 base64 임베드 완료 (%d bytes)",
                            illust_id, len(raw),
                        )
            except urllib.error.HTTPError as e:
                logger.warning(
                    "[pixiv_ranking] illust_id=%s 이미지 다운로드 HTTP 에러: %s %s",
                    illust_id, e.code, e.reason,
                )
            except Exception as e:
                logger.warning("[pixiv_ranking] illust_id=%s 이미지 다운로드 실패: %s", illust_id, e)

        title = body.get("illustTitle") or f"작품 {illust_id}"
        author = body.get("userName")
        artwork_url = f"https://www.pixiv.net/artworks/{illust_id}"

        return {
            "title": title,
            "author": author,
            "url": artwork_url,
            "link": artwork_url,
            "illust_id": illust_id,
            "cover": image_value,
            "cover_url": image_value,
            "image_url": image_value,
            "image": image_value,
            "thumbnail": image_value,
            "thumbnail_url": image_value,
            "src": image_value,
        }
