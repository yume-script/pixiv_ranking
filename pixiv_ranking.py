# -*- coding: utf-8 -*-
from plugins.metadata.base import BaseMetadataProvider
from flask import Response, request, jsonify
import urllib.request
import json
import base64
import re
import logging
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger("PixivPlugin")
logger.setLevel(logging.DEBUG)

CACHE_TTL_SEC = 600
MAX_WORKERS = 15
FETCH_TIMEOUT = 6


def to_original_url(thumb_url):
    # https://i.pximg.net/c/480x960/img-master/img/2026/08/02/14/53/33/147926455_p0_master1200.jpg
    # ==> https://i.pximg.net/img-original/img/2026/08/02/14/53/33/147926455_p0.jpg
    if not thumb_url:
        return thumb_url
    original = re.sub(r'/c/\d+x\d+/img-master/', '/img-original/', thumb_url)
    original = original.replace('_master1200', '')
    return original


class PixivRankingPlugin(BaseMetadataProvider):
    id = "pixiv_ranking"
    name = "Pixiv 랭킹 뷰어"
    is_searchable = False
    category_tab = {"title": "Pixiv 랭킹", "icon": "fa-solid fa-palette", "order": 90}

    # 플러그인 설정 화면에서 PHPSESSID 입력받기
    config_schema = [
        {"key": "PHPSESSID", "label": "Pixiv 세션 쿠키 (PHPSESSID)", "type": "password", "required": True},
    ]

    _image_cache = {}  # {원본url: (data_uri, timestamp)}
    _cache_lock = threading.Lock()

    def _headers(self, db_type):
        cfg = self.get_plugin_config(db_type, default={})
        session_id = cfg.get("PHPSESSID", "")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Referer": "https://www.pixiv.net/",
        }
        if session_id:
            headers["Cookie"] = f"PHPSESSID={session_id}"
        return headers

    def _fetch_image_data_uri(self, image_url, headers):
        with self._cache_lock:
            cached = self._image_cache.get(image_url)
        if cached and (time.time() - cached[1] < CACHE_TTL_SEC):
            return image_url, cached[0]
        try:
            req = urllib.request.Request(image_url, headers=headers)
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as res:
                content = res.read()
            data_uri = "data:image/jpeg;base64," + base64.b64encode(content).decode('ascii')
            with self._cache_lock:
                self._image_cache[image_url] = (data_uri, time.time())
            return image_url, data_uri
        except Exception as e:
            logger.error(f"[Prefetch] 실패: {image_url} - {e}")
            return image_url, None

    def pixiv_get(self):
        db_type = request.args.get('db_type', 'general')
        mode = request.args.get('mode', 'daily')
        content = request.args.get('content', 'all')
        headers = self._headers(db_type)

        url = f"https://www.pixiv.net/ranking.php?mode={mode}&content={content}&format=json"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as res:
                data = json.loads(res.read().decode('utf-8'))
                contents = data.get('contents', [])

            if not contents:
                logger.warning("[Pixiv] 빈 응답 - PHPSESSID 쿠키가 만료되었을 수 있습니다.")

            # 목록용 썸네일(url, 이미 작은 사이즈)만 병렬 프리페치
            # 원본(img-original)은 목록 단계에선 받지 않음 -> 페이로드 절약
            thumb_urls = [item['url'] for item in contents if item.get('url')]
            results = {}
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {
                    executor.submit(self._fetch_image_data_uri, u, headers): u
                    for u in thumb_urls
                }
                for future in as_completed(futures):
                    u, data_uri = future.result()
                    if data_uri:
                        results[u] = data_uri

            for item in contents:
                thumb = item.get('url')
                item['image_data'] = results.get(thumb)  # base64 썸네일
                item['original_url'] = to_original_url(thumb)  # 원본은 URL만 (지연 로딩)
                item['illust_id'] = item.get('illust_id')
                item['page_url'] = f"https://www.pixiv.net/artworks/{item.get('illust_id')}"

            logger.info(f"[Pixiv] 총 {len(contents)}개 항목, 썸네일 {len(results)}개 프리페치 완료")
            return jsonify(contents)
        except Exception as e:
            logger.error(f"[Pixiv] 데이터 수신 중 오류 발생: {str(e)}")
            return jsonify({'error': str(e)}), 500

    def proxy_image(self):
        # 원본 이미지 확대보기 등, 필요할 때만 개별 요청
        image_url = request.args.get('url')
        db_type = request.args.get('db_type', 'general')
        if not image_url:
            return Response("No URL", status=400)
        _, data_uri = self._fetch_image_data_uri(image_url, self._headers(db_type))
        if not data_uri:
            return Response("fetch failed", status=500)
        raw = base64.b64decode(data_uri.split(",", 1)[1])
        return Response(raw, mimetype='image/jpeg')
