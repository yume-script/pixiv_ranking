# -*- coding: utf-8 -*-
from plugins.metadata.base import BaseMetadataProvider
from flask import Response, request, jsonify
import urllib.request
import json
import logging

# 로그 설정
logger = logging.getLogger("PixivPlugin")
logger.setLevel(logging.DEBUG)

class PixivRankingPlugin(BaseMetadataProvider):
    id = "pixiv_ranking"
    name = "Pixiv 랭킹 뷰어"
    is_searchable = False
    category_tab = {"title": "Pixiv 랭킹", "icon": "fa-solid fa-palette", "order": 90}

    def pixiv_get(self):
        mode = request.args.get('mode', 'daily')
        content = request.args.get('content', 'all')
        logger.info(f"[Pixiv] 요청 수신: mode={mode}, content={content}")
        
        url = f"https://www.pixiv.net/ranking.php?mode={mode}&content={content}&format=json"
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.pixiv.net/"}
        
        try:
            logger.debug(f"[Pixiv] URL 연결 시도: {url}")
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as res:
                raw_data = res.read().decode('utf-8')
                logger.debug(f"[Pixiv] 데이터 수신 성공, 길이: {len(raw_data)}")
                data = json.loads(raw_data)
                contents = data.get('contents', [])
                logger.info(f"[Pixiv] 총 {len(contents)}개 항목 추출 완료")
                return jsonify(contents)
        except Exception as e:
            logger.error(f"[Pixiv] 데이터 수신 중 오류 발생: {str(e)}")
            return jsonify({'error': str(e)}), 500

    def proxy_image(self):
        image_url = request.args.get('url')
        logger.info(f"[Proxy] 이미지 요청: {image_url}")
        if not image_url: 
            logger.warning("[Proxy] 이미지 URL이 비어있음")
            return Response("No URL", status=400)
        
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.pixiv.net/"}
        try:
            req = urllib.request.Request(image_url, headers=headers)
            with urllib.request.urlopen(req) as res:
                content = res.read()
                logger.debug(f"[Proxy] 이미지 수신 완료, 크기: {len(content)} bytes")
                return Response(content, mimetype='image/jpeg')
        except Exception as e:
            logger.error(f"[Proxy] 이미지 다운로드 실패: {str(e)}")
            return Response(str(e), status=500)
