# -*- coding: utf-8 -*-
from urllib.parse import urlparse
import urllib.request
import json
import logging
import sys

# Flask/플러그인 베이스는 BookOasis 앱 안에서만 존재합니다.
# 이 파일을 `python pixiv_ranking.py --mode daily --content all` 처럼
# 단독 CLI로도 실행/테스트할 수 있도록 없으면 더미로 대체합니다.
try:
    from plugins.metadata.base import BaseMetadataProvider
    from flask import Response, request, jsonify
    _FLASK_AVAILABLE = True
except ImportError:
    _FLASK_AVAILABLE = False

    class BaseMetadataProvider:  # CLI 단독 실행용 더미 베이스
        pass

# 로그 설정 (중복 핸들러 방지: 리로드 시 로그가 중복 출력되는 것을 막음)
logger = logging.getLogger("PixivPlugin")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s"))
    logger.addHandler(_handler)
    logger.propagate = False

# 이미지 프록시가 허용할 호스트 화이트리스트 (오픈 프록시로 악용되는 것을 방지)
ALLOWED_PROXY_HOSTS = ("i.pximg.net", "pixiv.net", "www.pixiv.net")

# Pixiv용 User-Agent (없으면 요청이 차단됨)
PIXIV_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
)


def fetch_pixiv_ranking(mode, content):
    """
    Pixiv 랭킹 JSON을 가져와 contents 리스트를 반환하는 공통 함수.
    - 플러그인의 pixiv_get() (Flask 라우트)
    - 단독 CLI 실행 (아래 __main__ 블록)
    양쪽에서 공통으로 사용합니다.
    """
    url = f"https://www.pixiv.net/ranking.php?mode={mode}&content={content}&format=json"
    headers = {"User-Agent": PIXIV_USER_AGENT, "Referer": "https://www.pixiv.net/"}

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as response:
        raw_data = response.read().decode('utf-8')
        data = json.loads(raw_data)
        return data.get('contents', [])


class PixivRankingPlugin(BaseMetadataProvider):
    """
    Pixiv 랭킹을 카테고리 레벨 풀페이지로 보여주는 플러그인.

    확인 완료 (서버 소스 대조 결과):
    - `category_tab`은 실제 코어 계약입니다. services/metadata_factory.py가
      getattr(target_class, 'category_tab', None)로 읽고, api/library.py의
      /api/media/category-plugins가 사이드바 메뉴를 만들 때 사용합니다.
      풀페이지 UI(index.html/style.css/script.js)는 /api/media/plugins/<id>/ui
      가 JSON 번들로 내려줍니다. → 이 부분은 그대로 두면 정상 동작합니다.
    - /api/media/dashboard/widgets/<id>/data 는 오직 get_dashboard_data(db_type, limit)
      만 호출하며 type/limit 외 파라미터는 넘겨주지 않습니다. mode/content 같은
      커스텀 파라미터가 필요하면 이 공용 엔드포인트로는 처리할 수 없습니다.
    - 그래서 mode/content를 받는 실시간 조회, 이미지 프록시는
      plugins/metadata/aladin_bestseller/aladin_bestseller.py 가 쓰는 것과
      동일한 방식으로, 클래스 메서드가 아니라 **모듈 최상단에서 @app.route(...)**
      로 직접 등록합니다 (아래 참고). `app`은 플러그인 로더가 모듈 네임스페이스에
      미리 주입해두므로 import 없이 그대로 사용합니다.
    """

    id = "pixiv_ranking"
    name = "Pixiv 랭킹 뷰어"
    is_searchable = False
    config_schema = []

    category_tab = {"title": "Pixiv 랭킹", "icon": "fa-solid fa-palette", "order": 90}

    update_manifest = {
        "enabled": True,
        "provider": "github-raw",
        "raw_base_url": "https://raw.githubusercontent.com/yume-script/pixiv_ranking/main",
        "files": ["pixiv_ranking.py", "__init__.py", "index.html", "style.css", "script.js", "VERSION"],
        "version_file": "VERSION",
        "version_key": "plugin version",
        "show_sample_update_button": True,
    }

    # ---------------------------------------------------------------
    # 필수 계약 (guide_plugins.md 3장) — 이전 코드에 누락되어 있었음
    # ---------------------------------------------------------------
    def search(self, db_type, query):
        # 검색형(is_searchable) 플러그인이 아니므로 빈 결과만 반환
        return {'success': True, 'items': []}

    def apply(self, db_type, book_id, item_data):
        return False, "이 플러그인은 카테고리 전용이며 메타데이터 적용 대상이 아닙니다."

    # ---------------------------------------------------------------
    # (선택) 공통 데스크 위젯 계약 — /api/media/dashboard/widgets/<id>/data 가
    # 호출합니다. category_tab 풀페이지는 아래의 커스텀 @app.route를 쓰므로
    # 이 메서드는 "일반 대시보드 카드"로도 노출하고 싶을 때만 필요합니다.
    # (원치 않으면 dashboard_widget 속성 자체를 지우면 됩니다.)
    # ---------------------------------------------------------------
    def get_dashboard_data(self, db_type, limit=10):
        try:
            contents = fetch_pixiv_ranking('daily', 'all')[:limit]
            items = [
                {
                    'title': c.get('title'),
                    'author': c.get('user_name', ''),
                    'publisher': '',
                    'cover': c.get('url'),
                    'link': c.get('url'),
                }
                for c in contents
            ]
            return {'success': True, 'items': items}
        except Exception as e:
            return {'success': False, 'error': str(e)}


# ---------------------------------------------------------------------
# 커스텀 백엔드 엔드포인트 (plugins/metadata/aladin_bestseller/aladin_bestseller.py
# 와 동일한 방식: 클래스 메서드가 아니라 모듈 최상단에서 @app.route(...)로 직접
# 등록합니다. `app`은 플러그인 로더가 이 모듈을 로드할 때 네임스페이스에 미리
# 주입해두므로 import 없이 그대로 사용합니다.
#
# script.js는 이 절대경로들을 그대로 fetch() 합니다:
#   GET /api/dashboard/pixiv-ranking?mode=daily&content=all
#   GET /api/dashboard/pixiv-ranking/image-proxy?url=<encoded>
# ---------------------------------------------------------------------
if _FLASK_AVAILABLE:

    @app.route('/api/dashboard/pixiv-ranking', methods=['GET'])
    def get_pixiv_ranking_api():
        mode = request.args.get('mode', 'daily')
        content = request.args.get('content', 'all')
        logger.info(f"[Pixiv] 요청 수신: mode={mode}, content={content}")

        try:
            contents = fetch_pixiv_ranking(mode, content)
            logger.info(f"[Pixiv] 총 {len(contents)}개 항목 추출 완료")
            return jsonify({'success': True, 'items': contents})
        except Exception as e:
            logger.error(f"[Pixiv] 데이터 수신 중 오류 발생: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/dashboard/pixiv-ranking/image-proxy', methods=['GET'])
    def proxy_pixiv_image_api():
        image_url = request.args.get('url')
        if not image_url:
            logger.warning("[Proxy] 이미지 URL이 비어있음")
            return Response("No URL", status=400)

        # 오픈 프록시 악용 방지: 화이트리스트에 없는 호스트는 차단
        try:
            host = urlparse(image_url).hostname or ""
        except Exception:
            host = ""
        if not any(host == h or host.endswith("." + h) for h in ALLOWED_PROXY_HOSTS):
            logger.warning(f"[Proxy] 허용되지 않은 호스트 요청 차단: {host}")
            return Response("Forbidden host", status=403)

        logger.info(f"[Proxy] 이미지 요청: {image_url}")
        headers = {"User-Agent": PIXIV_USER_AGENT, "Referer": "https://www.pixiv.net/"}
        try:
            req = urllib.request.Request(image_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as res:
                content = res.read()
                content_type = res.headers.get('Content-Type', 'image/jpeg')
                logger.debug(f"[Proxy] 이미지 수신 완료, 크기: {len(content)} bytes")
                return Response(content, mimetype=content_type)
        except Exception as e:
            logger.error(f"[Proxy] 이미지 다운로드 실패: {str(e)}")
            return Response(str(e), status=500)


# ---------------------------------------------------------------------
# CLI 단독 실행 (디버깅/테스트용)
#
# BookOasis 앱 없이도 이 파일 하나로 pixiv 랭킹을 직접 조회해볼 수 있습니다.
# 사용법:
#   python pixiv_ranking.py --mode daily --content all
#   python pixiv_ranking.py --mode weekly --content illust
#   python pixiv_ranking.py --mode monthly --content manga
#
# ⚠️ 참고: script.js가 브라우저에서 fetch()로 호출하는 건 위에서 @app.route로
# 등록한 /api/dashboard/pixiv-ranking (Flask 라우트)입니다. 이 CLI 블록을
# 서버가 실행하는 게 아니라, 순수하게 터미널에서 수동으로 pixiv 크롤링
# 로직만 테스트하고 싶을 때 쓰는 용도입니다.
# ---------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Pixiv 랭킹 크롤러 (urllib 버전)")
    parser.add_argument("--mode", required=True, help="daily, weekly, monthly, rookie 등")
    parser.add_argument("--content", required=True, help="all, illust, manga, ugoira 등")
    args = parser.parse_args()

    try:
        contents = fetch_pixiv_ranking(args.mode, args.content)
        if not contents:
            print("데이터를 찾을 수 없습니다. mode/content 값을 확인하세요.")
            sys.exit(0)
        print(f"[{args.mode.upper()} / {args.content.upper()}] 랭킹 목록:")
        for item in contents:
            print(f"- {item.get('title')} | {item.get('url')}")
    except Exception as e:
        print(f"오류 발생: {e}")
