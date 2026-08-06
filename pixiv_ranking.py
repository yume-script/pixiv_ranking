# -*- coding: utf-8 -*-
"""
Pixiv 랭킹 대시보드 위젯 플러그인 (BookOasis metadata plugin)

- search / apply: 검색형 메타데이터 기능은 사용하지 않음 (대시보드 전용)
- dashboard_widget + get_dashboard_data: 픽시브 랭킹 TOP N을 카드로 노출
- 이미지: [개선] base64로 인라이닝하지 않고, /plugins/pixiv_ranking/thumb
  프록시 라우트의 URL만 내려준다. 브라우저가 <img src="...">로 각 썸네일을
  병렬 + lazy-load 방식으로 직접 요청하므로, get_dashboard_data 응답 자체는
  이미지 다운로드를 기다리지 않고 즉시 반환된다.
  (i.pximg.net은 Referer 헤더가 없으면 403을 반환하므로, 프록시 라우트에서
   서버 사이드로 Referer를 붙여 중계하는 구조는 그대로 유지한다.)

주의:
- 코어 대시보드 카드 렌더러(공통 데스크 그리드)가 실제로 읽는 필드는
  cover / title / author / publisher / link 입니다.
  (random_gallery 예제 플러그인 소스로 확인됨: https://github.com/yume-script/random_gallery)
  다른 렌더러가 다른 키를 참조할 경우를 대비해 image/image_url/url 등의
  별칭 필드도 함께 채워서 반환합니다.

[개선사항 적용 내역]
1. 이미지 base64 인라이닝 제거 -> 프록시 URL 방식으로 전환 (가장 큰 속도 개선)
2. 랭킹 API 응답에 대한 TTL 캐시 추가 (기본 5분)
3. urllib 대신 requests.Session()으로 커넥션(TCP/TLS) 재사용
4. 상세 로그를 warning -> debug로 낮춤 (운영 환경에서 I/O 비용 절감)

[통합 시 확인 필요 — 프레임워크 의존적인 부분]
- 이 플러그인 시스템의 실제 라우트 등록 방식(Blueprint 등록 지점, URL prefix)을
  모르기 때문에, 아래 `bp` Blueprint는 하나의 예시입니다.
  random_gallery 같은 다른 플러그인이 이미 Flask 라우트를 어떻게 등록하는지
  확인한 뒤, 그 방식에 맞춰 `register_routes()` 호출 지점을 연결해야 합니다.
"""

import json
import logging
import re
import time
from urllib.parse import quote, unquote

import requests
from concurrent.futures import ThreadPoolExecutor

from plugins.metadata.base import BaseMetadataProvider

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
)
PIXIV_REFERER = "https://www.pixiv.net/"

# 동시에 받아올 썸네일 최대 개수 (네트워크 부하 제한) - 랭킹 프리페치용
MAX_CONCURRENT_THUMBS = 5
# 개별 요청 타임아웃(초)
REQUEST_TIMEOUT = 8

# 랭킹 API 응답 캐시 TTL(초). 랭킹은 자주 바뀌지 않으므로 5분 정도로 설정.
RANKING_CACHE_TTL = 300

# 프로세스 전역에서 커넥션을 재사용하기 위한 공용 세션
_session = requests.Session()
_session.headers.update({
    "User-Agent": USER_AGENT,
    "Referer": PIXIV_REFERER,
})

# 랭킹 캐시: {(mode, content, limit): (timestamp, contents)}
_ranking_cache = {}


def _thumb_to_original(thumb_url):
    """
    https://i.pximg.net/c/480x960/img-master/img/2026/08/02/14/53/33/147926455_p0_master1200.jpg
    ==> https://i.pximg.net/img-original/img/2026/08/02/14/53/33/147926455_p0.jpg
    (원본이 png인 작품은 이 변환만으로 404가 날 수 있음 - 참고용으로만 사용)
    """
    if not thumb_url:
        return thumb_url
    original = re.sub(r"/c/\d+x\d+/img-master/", "/img-original/", thumb_url)
    original = original.replace("_master1200", "")
    return original


class PixivRankingMetadataProvider(BaseMetadataProvider):
    id = "pixiv_ranking"
    name = "Pixiv 랭킹"
    is_searchable = False

    config_schema = [
        {
            "key": "PHPSESSID",
            "label": "Pixiv 로그인 세션 (PHPSESSID)",
            "type": "password",
            "required": True,
        },
        {
            "key": "MODE",
            "label": "랭킹 모드",
            "type": "select",
            "default": "daily",
            "options": [
                {"value": "daily", "label": "일간 (daily)"},
                {"value": "weekly", "label": "주간 (weekly)"},
                {"value": "monthly", "label": "월간 (monthly)"},
                {"value": "rookie", "label": "신인 (rookie)"},
                {"value": "original", "label": "오리지널 (original)"},
                {"value": "daily_ai", "label": "AI생성 (daily_ai)"},
                {"value": "male", "label": "남자에게 인기 (male)"},
                {"value": "female", "label": "여자에게 인기 (female)"},
            ],
        },
        {
            "key": "CONTENT",
            "label": "콘텐츠 타입",
            "type": "select",
            "default": "all",
            "options": [
                {"value": "all", "label": "종합 (all)"},
                {"value": "illust", "label": "일러스트 (illust)"},
                {"value": "ugoira", "label": "우고이라 (ugoira)"},
                {"value": "manga", "label": "만화 (manga)"},
            ],
        },
        {
            "key": "LIMIT",
            "label": "표시 개수",
            "type": "select",
            "default": "50",
            "options": [
                {"value": "10", "label": "10개"},
                {"value": "20", "label": "20개"},
                {"value": "30", "label": "30개"},
                {"value": "50", "label": "50개 (최대)"},
            ],
        },
    ]

    # 자동 업데이트를 지원하려면 raw_base_url을 실제 호스팅 리포지토리로 바꿔서 사용
    update_manifest = {
        "enabled": False,
        "provider": "github-raw",
        "raw_base_url": "https://raw.githubusercontent.com/<org>/<repo>/<branch>/plugins/metadata/pixiv_ranking",
        "files": ["pixiv_ranking.py", "__init__.py", "VERSION"],
        "version_file": "VERSION",
        "version_key": "plugin version",
        "show_sample_update_button": False,
    }
    # 대쉬보드에 보여주고 싶을때..
    #dashboard_widget = {
    #    "title": "Pixiv 랭킹",
    #    "subtitle": "픽시브 실시간 랭킹",
    #    "provider": "Pixiv",
    #    "icon": "fa-solid fa-image",
    #    "limit": 10,
    #    "supported_types": ["general"],
    #}

    # 코어 좌측/상단 "카테고리" 내비게이션에 별도 메뉴로 노출되는 풀페이지 탭 계약.
    # (guide_plugins.md에는 없지만 random_gallery 실제 소스로 확인된 계약:
    #  title/icon/order 만 선언하면 되고, 카드 데이터는 get_dashboard_data()를
    #  그대로 재사용함 — 별도 index.html/script.js 불필요)
    category_tab = {
        "title": "Pixiv 랭킹",
        "icon": "fa-solid fa-image",
        "order": 92,
    }

    # ---- 필수 계약 (대시보드 전용이라 실질 동작 없음) ----
    def search(self, db_type, query):
        return []

    def apply(self, db_type, book_id, item_data):
        return False, "대시보드 전용 플러그인입니다."

    # ---- 내부 헬퍼 ----
    def _fetch_ranking(self, session_id, mode, content, limit):
        cache_key = (mode, content, limit)
        cached = _ranking_cache.get(cache_key)
        now = time.time()
        if cached and (now - cached[0]) < RANKING_CACHE_TTL:
            logger.debug(
                "[pixiv_ranking] 1/3 캐시 히트: mode=%s, content=%s, limit=%s (남은 TTL %.0fs)",
                mode, content, limit, RANKING_CACHE_TTL - (now - cached[0]),
            )
            return cached[1]

        url = (
            f"https://www.pixiv.net/ranking.php"
            f"?mode={mode}&content={content}&format=json"
        )
        logger.debug(
            "[pixiv_ranking] 1/3 랭킹 조회 시작(캐시 미스): mode=%s, content=%s, limit=%s, url=%s",
            mode, content, limit, url,
        )
        t0 = time.time()
        resp = _session.get(
            url,
            cookies={"PHPSESSID": session_id} if session_id else None,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        elapsed = time.time() - t0
        logger.debug(
            "[pixiv_ranking] 1/3 랭킹 응답 수신: status=%s, %.2fs 소요, body(앞 300자)=%s",
            resp.status_code, elapsed, resp.text[:300],
        )
        data = resp.json()
        contents = data.get("contents", [])
        logger.debug(
            "[pixiv_ranking] 1/3 랭킹 파싱 완료: 전체 %d개 중 %d개 사용 예정",
            len(contents), min(limit, len(contents)),
        )
        trimmed = contents[:limit]
        _ranking_cache[cache_key] = (now, trimmed)
        return trimmed

    def _get_request_override(self, key):
        """Flask 요청 컨텍스트에서 쿼리 파라미터를 읽음 (프론트엔드 드롭다운 값).
        요청 컨텍스트 밖에서 호출되면(예: 배치 작업) 조용히 None을 반환하고
        설정값(config)으로 폴백함."""
        try:
            from flask import request
            val = request.args.get(key)
            return val if val else None
        except Exception:
            return None

    def _build_items(self, contents, session_id):
        """
        [개선] 더 이상 서버에서 썸네일을 다운로드해 base64로 인라이닝하지 않는다.
        대신 프록시 라우트(/plugins/pixiv_ranking/thumb?url=...)의 URL만 채워서
        반환한다 -> get_dashboard_data가 이미지 다운로드를 기다리지 않고 즉시
        응답하며, 실제 이미지 로딩은 브라우저가 <img> 태그로 병렬/lazy 처리한다.
        """
        items = []
        for entry in contents:
            work_id = entry.get("illust_id") or entry.get("id")
            page_url = f"https://www.pixiv.net/artworks/{work_id}"
            thumb_url = entry.get("url")
            proxy_url = (
                f"/plugins/pixiv_ranking/thumb?url={quote(thumb_url, safe='')}"
                if thumb_url else None
            )
            title = entry.get("title")
            rank = entry.get("rank")
            display_title = f"#{rank} {title}" if rank else title
            # 코어 대시보드 카드 렌더러가 실제로 읽는 필드: cover/title/author/publisher/link
            # (random_gallery 플러그인 소스로 확인됨)
            items.append({
                "cover": proxy_url,
                "title": display_title,
                "author": entry.get("user_name"),
                "publisher": "Pixiv",
                "link": page_url,
                # 다른 렌더러 대응용 별칭 (혹시 다른 키를 참조하는 경우 대비)
                "image": proxy_url,
                "image_url": proxy_url,
                "url": page_url,
                "link_url": page_url,
                "rank": rank,
                # 참고용 원본 이미지 URL 추정치 (png 원본이면 실패할 수 있음)
                "original_url_guess": _thumb_to_original(thumb_url),
            })
        logger.debug("[pixiv_ranking] 2/3 아이템 %d개 구성 완료 (이미지는 프록시 URL만 채움)", len(items))
        return items

    # ---- 대시보드 계약 ----
    def get_dashboard_data(self, db_type, limit=10):
        logger.debug(
            "[pixiv_ranking] 0/3 get_dashboard_data 호출: db_type=%s, limit=%s",
            db_type, limit,
        )
        cfg = self.get_plugin_config(db_type, default={})
        session_id = cfg.get("PHPSESSID")
        mode = self._get_request_override("mode") or cfg.get("MODE", "daily")
        content = self._get_request_override("content") or cfg.get("CONTENT", "all")

        # 설정에 저장된 "표시 개수"가 있으면, 프론트엔드가 요청한 limit보다
        # 우선 적용한다 (화면 상단/카드 위젯 어느 쪽에서 오든 동일하게 적용).
        try:
            configured_limit = int(cfg.get("LIMIT", 50))
        except (TypeError, ValueError):
            configured_limit = 50
        configured_limit = max(1, min(configured_limit, 50))
        effective_limit = min(limit, configured_limit) if limit else configured_limit

        logger.debug(
            "[pixiv_ranking] 0/3 설정 로드 완료: mode=%s, content=%s, session=%s,"
            " 요청 limit=%s, 설정 표시개수=%s, 최종 limit=%s"
            " (드롭다운으로 요청된 값이 있으면 그 값을 우선 사용)",
            mode, content, "설정됨" if session_id else "없음",
            limit, configured_limit, effective_limit,
        )

        if not session_id:
            logger.warning("[pixiv_ranking] 중단: PHPSESSID 미설정")
            return {
                "success": False,
                "error": "Pixiv 로그인 세션(PHPSESSID)이 설정되지 않았습니다.",
            }

        try:
            contents = self._fetch_ranking(session_id, mode, content, effective_limit)
        except (requests.RequestException, json.JSONDecodeError) as e:
            logger.warning("[pixiv_ranking] 중단: 랭킹 조회 실패: %s", e)
            return {"success": False, "error": f"랭킹 조회 실패: {e}"}

        if not contents:
            logger.warning("[pixiv_ranking] 랭킹 결과 0건, 빈 목록 반환")
            return {"success": True, "items": []}

        # [개선] 더 이상 여기서 썸네일을 미리 받지 않으므로 즉시 반환된다.
        items = self._build_items(contents, session_id)
        logger.debug(
            "[pixiv_ranking] 3/3 완료: 최종 %d개 항목 반환 (이미지는 프록시가 지연 처리)", len(items),
        )
        return {"success": True, "items": items}

    # ---- [신규] 이미지 프록시 라우트 ----
    def register_routes(self, blueprint):
        """
        플러그인 프레임워크가 라우트 등록을 지원하는 경우 이 메서드를 호출해
        blueprint(Flask Blueprint 등)에 프록시 엔드포인트를 추가한다.

        !! 통합 주의 !!
        이 플러그인 시스템에서 실제로 라우트를 등록하는 방식(메서드명, 호출
        시점, Blueprint 인스턴스 전달 여부)을 확인하지 못했습니다. 아래는
        Flask 기준 예시 구현이며, 프레임워크가 다른 방식(예: 별도
        routes.py, app.add_url_rule 직접 호출 등)을 요구한다면 그에 맞게
        연결부만 수정하면 됩니다. 핵심 로직(_proxy_thumb)은 그대로 재사용
        가능합니다.
        """
        blueprint.add_url_rule(
            "/plugins/pixiv_ranking/thumb",
            "pixiv_ranking_thumb",
            self._proxy_thumb,
            methods=["GET"],
        )

    def _proxy_thumb(self):
        from flask import request, Response, abort

        thumb_url = request.args.get("url")
        if not thumb_url:
            abort(400, "url 파라미터가 필요합니다.")
        thumb_url = unquote(thumb_url)

        # 픽시브 도메인만 허용 (오픈 프록시로 악용되는 것을 방지)
        if not re.match(r"^https://i\.pximg\.net/", thumb_url):
            abort(400, "허용되지 않은 이미지 호스트입니다.")

        t0 = time.time()
        try:
            resp = _session.get(thumb_url, timeout=REQUEST_TIMEOUT, stream=True)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.debug(
                "[pixiv_ranking] 썸네일 프록시 실패(%.2fs): %s | %s",
                time.time() - t0, e, thumb_url,
            )
            abort(502, "이미지를 가져오지 못했습니다.")

        content_type = resp.headers.get("Content-Type", "image/jpeg")
        logger.debug(
            "[pixiv_ranking] 썸네일 프록시 성공(%.2fs): %s | %s",
            time.time() - t0, content_type, thumb_url,
        )
        # 브라우저/CDN 캐시를 활용해 재요청 부담을 줄인다.
        return Response(
            resp.content,
            mimetype=content_type,
            headers={"Cache-Control": "public, max-age=3600"},
        )
