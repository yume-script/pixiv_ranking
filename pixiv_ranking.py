# -*- coding: utf-8 -*-
from plugins.metadata.base import BaseMetadataProvider
import urllib.request
import json

class PixivRankingPlugin(BaseMetadataProvider):
    id = "pixiv_ranking"
    name = "Pixiv 랭킹 뷰어"
    is_searchable = False
    
    # 카테고리 1등 시민 메뉴 등록
    category_tab = {
        "title": "Pixiv 랭킹",
        "icon": "fa-solid fa-palette",
        "order": 90
    }

    def search(self, db_type, query):
        return {'success': True, 'items': []}

    def apply(self, db_type, book_id, item_data):
        return False, "이 플러그인은 랭킹 뷰어 전용입니다."

    # 프론트엔드에서 호출할 데이터 제공 API
    def get_pixiv_data(self, mode, content):
        url = f"https://www.pixiv.net/ranking.php?mode={mode}&content={content}&format=json"
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.pixiv.net/"}
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as res:
                return json.loads(res.read().decode('utf-8')).get('contents', [])
        except Exception as e:
            return []
