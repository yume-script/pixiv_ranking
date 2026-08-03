# -*- coding: utf-8 -*-
from plugins.metadata.base import BaseMetadataProvider
import urllib.request
import json
from flask import Response, request

class PixivRankingPlugin(BaseMetadataProvider):
    id = "pixiv_ranking"
    name = "Pixiv 랭킹 뷰어"
    is_searchable = False
    
    category_tab = {
        "title": "Pixiv 랭킹",
        "icon": "fa-solid fa-palette",
        "order": 90
    }

    def search(self, db_type, query):
        return {'success': True, 'items': []}

    def apply(self, db_type, book_id, item_data):
        return False, "이 플러그인은 랭킹 뷰어 전용입니다."

    # 1. 랭킹 데이터 가져오기
    def get_pixiv_data(self, mode, content):
        url = f"https://www.pixiv.net/ranking.php?mode={mode}&content={content}&format=json"
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.pixiv.net/"}
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as res:
                return json.loads(res.read().decode('utf-8')).get('contents', [])
        except: return []

    # 2. 이미지 프록시 (Pixiv 차단 우회)
    def proxy_image(self):
        image_url = request.args.get('url')
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.pixiv.net/"}
        try:
            req = urllib.request.Request(image_url, headers=headers)
            with urllib.request.urlopen(req) as res:
                return Response(res.read(), mimetype='image/jpeg')
        except:
            return Response("이미지 로드 실패", status=404)
