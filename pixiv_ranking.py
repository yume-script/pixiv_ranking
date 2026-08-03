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

    ⚠️ 확인 필요:
    - `category_tab` 필드는 guide_plugins.md에 문서화된 공식 계약이 아닙니다.
      (문서 5장 기준 풀페이지 탭의 공식 계약은
       dashboard_widget = {..., 'all_desk_tab': True} + get_dashboard_data() 입니다.)
      코어가 실제로 category_tab을 인식하지 못한다면 탭이 노출되지 않을 수 있으니,
      실제 BookOasis 코어 버전에서 지원 여부를 확인하세요.
    - pixiv_get / proxy_image 를 실제로 어떤 URL로 호출할 수 있는지도
      코어의 라우팅 규칙에 맞춰 확인이 필요합니다. (guide 1장: "코어는 플러그인
      고유 라우트/내부 함수명을 알지 않는다"는 원칙과 상충될 수 있습니다.)
      아래 코드와 script.js는 상대경로(같은 플러그인 네임스페이스 하위)를
      호출한다고 가정한 것이므로, 실제 라우트가 다르면 script.js의
      API_BASE / PROXY_BASE 값만 바꿔주면 됩니다.
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
    # 커스텀 백엔드 엔드포인트
    # ---------------------------------------------------------------
    def pixiv_get(self):
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

    def proxy_image(self):
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
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.pixiv.net/"}
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
# ⚠️ 참고: script.js가 브라우저에서 fetch()로 호출하는 "pixiv_get"은
# 이 CLI 스크립트를 서버에서 직접 실행하는 것이 아니라, 위 클래스의
# pixiv_get() 메서드가 Flask 라우트로 노출된 것을 호출하는 것입니다.
# (브라우저가 서버의 .py 파일을 직접 실행시킬 수는 없습니다.)
# 이 __main__ 블록은 순수하게 터미널에서 수동으로 테스트할 때만 쓰입니다.
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
