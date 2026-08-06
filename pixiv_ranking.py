# -*- coding: utf-8 -*-
"""
Pixiv 랭킹 대시보드 위젯 플러그인 (BookOasis metadata plugin)

- search / apply: 검색형 메타데이터 기능은 사용하지 않음 (대시보드 전용)
- dashboard_widget + get_dashboard_data: 픽시브 랭킹 TOP N을 카드로 노출
- 이미지: 로컬 저장 없이, 요청 시점에 서버가 Referer 헤더를 붙여
  픽시브에서 직접 받아온 뒤 base64 데이터 URI로 응답에 포함시켜 프록시.
  (브라우저가 i.pximg.net에 직접 요청하면 Referer 누락으로 403이 나므로
   반드시 서버 사이드에서 중계해야 함)

[정정 내역 — 자체 프록시 라우트 시도 롤백]
한때 base64 대신 `/plugins/pixiv_ranking/thumb` 자체 라우트 URL을 내려주는
방식을 시도했으나, random_gallery 플러그인의 실제 소스로 확인한 결과 이
프레임워크는 `get_dashboard_data()` 단 하나만 공개 계약으로 호출하고
플러그인이 별도 Flask 라우트를 등록할 방법을 제공하지 않습니다. 그래서
base64 인라이닝 방식으로 되돌렸습니다.

주의:
- 코어 대시보드 카드 렌더러(공통 데스크 그리드)가 실제로 읽는 필드는
  cover / title / author / publisher / link 입니다.
  (random_gallery 예제 플러그인 소스로 확인됨: https://github.com/yume-script/random_gallery)
  다른 렌더러가 다른 키를 참조할 경우를 대비해 image/image_url/url 등의
  별칭 필드도 함께 채워서 반환합니다.

[성능 개선 내역]
1. 랭킹 API 응답에 대한 TTL 캐시 추가 (기본 5분)
2. 썸네일 base64 데이터 URI 자체를 URL 기준으로 캐시 (기본 30분)
3. requests.Session()으로 커넥션(TCP/TLS) 재사용
4. 상세 로그를 warning -> debug로 낮춤 (에러성 로그만 warning 유지)
5. [신규] 썸네일 다운로드 사이즈 축소
   픽시브 썸네일 URL은 `/c/{width}x{height}[_quality][_format]/img-master/...`
   형식으로, 픽시브 서버가 원본을 그 사이즈로 즉석 리사이즈해서 내려준다
   (kepstin/Fix-pixiv-thumbnails, greasyfork "Improve pixiv thumbnails"
   등 여러 픽시브 클라이언트 프로젝트에서 확인된, 픽시브가 실제로 서비스에
   사용 중인 공개된 CDN 파라미터). 랭킹 API가 기본으로 내려주는 원본 썸네일
   URL의 `/c/WxH.../` 부분을 대시보드 카드에 실제로 필요한 작은 사이즈로
   치환해서 요청하면:
     - 픽시브 → 우리 서버 다운로드량 자체가 줄어듬 (네트워크 시간 단축)
     - base64 인코딩 후 JSON payload 크기도 비례해서 줄어듬 (브라우저
       전송/렌더링도 더 빨라짐)
     - 썸네일 캐시가 메모리를 훨씬 덜 씀 (더 많은 항목을 오래 캐시 가능)
   요청한 사이즈가 어떤 이유로든 실패(404 등)하면 원래 사이즈로 자동
   폴백한다.
"""

import json
import logging
import re
import sys
import time
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from plugins.metadata.base import BaseMetadataProvider

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
)
PIXIV_REFERER = "https://www.pixiv.net/"

# 동시에 받아올 썸네일 최대 개수 (네트워크 부하 제한)
MAX_CONCURRENT_THUMBS = 5
# 개별 요청 타임아웃(초)
REQUEST_TIMEOUT = 8

# 랭킹 API 응답 캐시 TTL(초). 랭킹은 자주 바뀌지 않으므로 5분 정도로 설정.
RANKING_CACHE_TTL = 300
# 썸네일 base64 캐시 TTL(초). 작품 썸네일 자체는 거의 안 바뀌므로 더 길게.
THUMB_CACHE_TTL = 1800
# 썸네일 캐시 최대 보관 개수 (메모리 무한 증가 방지, 오래된 것부터 정리)
THUMB_CACHE_MAX_ITEMS = 500

# 대시보드 카드에 실제로 필요한 썸네일 사이즈. 카드가 보통 150~200px 폭으로
# 렌더링되므로, 그보다 약간 여유 있는 사이즈 + 낮은 JPEG 품질로 충분함.
# 형식: "{width}x{height}_{quality 1-100}" (crop 방식은 원본 파일명이
# _master1200/_square1200 중 무엇이냐에 따라 결정되며 이 값과는 무관함)
THUMB_TARGET_SIZE = "200x200_75"

# 프로세스 전역에서 커넥션을 재사용하기 위한 공용 세션
_session = requests.Session()
_session.headers.update({
    "User-Agent": USER_AGENT,
    "Referer": PIXIV_REFERER,
})

# 랭킹 캐시: {(mode, content, limit): (timestamp, contents)}
_ranking_cache = {}
# 썸네일 캐시: {thumb_url(원본 기준): (timestamp, data_uri)}
_thumb_cache = {}

_THUMB_SIZE_RE = re.compile(r"/c/\d+x\d+(?:_[^/]*)?/")


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


def _shrink_thumb_url(thumb_url, size=THUMB_TARGET_SIZE):
    """썸네일 URL의 /c/{width}x{height}.../ 부분을 더 작은 사이즈로 치환.
    해당 세그먼트가 없는 URL(예: img-original)은 그대로 반환."""
    if not thumb_url:
        return thumb_url
    shrunk, count = _THUMB_SIZE_RE.subn(f"/c/{size}/", thumb_url, count=1)
    return shrunk if count else thumb_url


def _thumb_cache_get(thumb_url):
    entry = _thumb_cache.get(thumb_url)
    if not entry:
        return None
    ts, data_uri = entry
    if time.time() - ts > THUMB_CACHE_TTL:
        _thumb_cache.pop(thumb_url, None)
        return None
    return data_uri


def _thumb_cache_set(thumb_url, data_uri):
    if len(_thumb_cache) >= THUMB_CACHE_MAX_ITEMS:
        # 가장 오래된 항목부터 정리 (간단한 방식, 별도 라이브러리 불필요)
        oldest_key = min(_thumb_cache, key=lambda k: _thumb_cache[k][0])
        _thumb_cache.pop(oldest_key, None)
    _thumb_cache[thumb_url] = (time.time(), data_uri)


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
        {
            "key": "LOG_LEVEL",
            "label": "로그 레벨",
            "type": "select",
            "default": "WARNING",
            "options": [
                {"value": "WARNING", "label": "WARNING (기본, 오류만 기록)"},
                {"value": "INFO", "label": "INFO"},
                {"value": "DEBUG", "label": "DEBUG (단계별 소요시간·요청 상세 기록)"},
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
    # 주의: 이 값은 코어가 인스턴스가 아닌 "클래스 자체"에서 읽는 것으로 보임
    # (random_gallery README에서 확인된 회귀 버그 사례). 따라서 반드시 고정된
    # dict여야 하며, @property 등으로 동적으로 바꾸면 플러그인이 목록에서
    # 통째로 사라질 수 있음.
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
                "[pixiv_ranking] 1/3 랭킹 캐시 히트: mode=%s, content=%s, limit=%s (남은 TTL %.0fs)",
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

    def _download_thumb_bytes(self, url, session_id):
        resp = _session.get(
            url,
            cookies={"PHPSESSID": session_id} if session_id else None,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "image/jpeg")
        return resp.content, content_type

    def _fetch_thumb_data_uri(self, thumb_url, session_id):
        """썸네일을 base64 data URI로 변환. URL(원본 사이즈 기준) 캐시를 먼저
        확인하고, 캐시 미스일 때만 축소된 사이즈로 픽시브에 요청한다
        (로컬 파일 저장 없음). 축소 사이즈 요청이 실패하면 원본 사이즈로
        한 번 더 시도한다."""
        if not thumb_url:
            logger.debug("[pixiv_ranking] 2/3 썸네일 URL 없음, 건너뜀")
            return None

        cached = _thumb_cache_get(thumb_url)
        if cached is not None:
            return cached

        small_url = _shrink_thumb_url(thumb_url)
        t0 = time.time()
        try:
            raw, content_type = self._download_thumb_bytes(small_url, session_id)
            logger.debug(
                "[pixiv_ranking] 2/3 축소 썸네일 수신 성공(%.2fs): %d bytes, %s | %s",
                time.time() - t0, len(raw), content_type, small_url,
            )
        except requests.RequestException as e:
            logger.debug(
                "[pixiv_ranking] 2/3 축소 썸네일 실패(%.2fs), 원본 사이즈로 재시도: %s | %s",
                time.time() - t0, e, small_url,
            )
            t1 = time.time()
            try:
                raw, content_type = self._download_thumb_bytes(thumb_url, session_id)
                logger.debug(
                    "[pixiv_ranking] 2/3 원본 사이즈 폴백 성공(%.2fs): %d bytes, %s | %s",
                    time.time() - t1, len(raw), content_type, thumb_url,
                )
            except requests.RequestException as e2:
                logger.warning(
                    "[pixiv_ranking] 2/3 썸네일 수신 완전 실패(축소 %.2fs + 원본 %.2fs): %s | %s",
                    time.time() - t0, time.time() - t1, e2, thumb_url,
                )
                return None

        b64 = b64encode(raw).decode("ascii")
        data_uri = f"data:{content_type};base64,{b64}"
        _thumb_cache_set(thumb_url, data_uri)
        return data_uri

    def _build_items(self, contents, session_id):
        logger.debug(
            "[pixiv_ranking] 2/3 썸네일 %d개 병렬 수집 시작 (동시 %d개, 사이즈=%s, 캐시 히트분은 즉시 반환)",
            len(contents), MAX_CONCURRENT_THUMBS, THUMB_TARGET_SIZE,
        )
        t0 = time.time()
        items = [None] * len(contents)

        def _work(idx, entry):
            work_id = entry.get("illust_id") or entry.get("id")
            page_url = f"https://www.pixiv.net/artworks/{work_id}"
            thumb_url = entry.get("url")
            image_data_uri = self._fetch_thumb_data_uri(thumb_url, session_id)
            title = entry.get("title")
            rank = entry.get("rank")
            display_title = f"#{rank} {title}" if rank else title
            # 코어 대시보드 카드 렌더러가 실제로 읽는 필드: cover/title/author/publisher/link
            # (random_gallery 플러그인 소스로 확인됨)
            return idx, {
                "cover": image_data_uri,
                "title": display_title,
                "author": entry.get("user_name"),
                "publisher": "Pixiv",
                "link": page_url,
                # 다른 렌더러 대응용 별칭 (혹시 다른 키를 참조하는 경우 대비)
                "image": image_data_uri,
                "image_url": image_data_uri,
                "url": page_url,
                "link_url": page_url,
                "rank": rank,
                # 참고용 원본 이미지 URL 추정치 (png 원본이면 실패할 수 있음)
                "original_url_guess": _thumb_to_original(thumb_url),
            }

        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_THUMBS) as pool:
            futures = [
                pool.submit(_work, idx, entry) for idx, entry in enumerate(contents)
            ]
            for fut in as_completed(futures):
                idx, item = fut.result()
                items[idx] = item

        elapsed = time.time() - t0
        success_count = sum(1 for it in items if it.get("cover"))
        logger.debug(
            "[pixiv_ranking] 2/3 썸네일 수집 완료: %.2fs, 성공 %d/%d개",
            elapsed, success_count, len(items),
        )
        return items

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

    # ---- 대시보드 계약 ----
    def get_dashboard_data(self, db_type, limit=10):
        logger.debug(
            "[pixiv_ranking] 0/3 get_dashboard_data 호출: db_type=%s, limit=%s",
            db_type, limit,
        )
        cfg = self.get_plugin_config(db_type, default={})

        # 설정 화면(settings.html)의 "로그 레벨" 드롭다운 값을 그대로 반영.
        # 배포 없이 UI에서 바로 DEBUG로 바꿔 병목 구간(1/3 랭킹 조회,
        # 2/3 썸네일 다운로드/캐시 히트율)을 진단할 수 있도록 하기 위함.
        log_level_name = str(cfg.get("LOG_LEVEL", "WARNING")).upper()
        log_level = getattr(logging, log_level_name, None)
        if not isinstance(log_level, int):
            log_level = logging.WARNING
        if logger.level != log_level:
            logger.setLevel(log_level)

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

        items = self._build_items(contents, session_id)
        logger.debug(
            "[pixiv_ranking] 3/3 완료: 최종 %d개 항목 반환", len(items),
        )
        return {"success": True, "items": items}
