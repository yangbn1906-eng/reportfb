# dashboard.py - Meta System Intelligence PRO v3.3 (Cloud Compatible)

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import json
import logging
import hashlib
import tempfile
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
import numpy as np
import time

# ==================== CONFIGURATION ====================
st.set_page_config(
    page_title='Anbub.io', 
    layout='wide',
    page_icon="🚀"
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Constants
API_VER = 'v25.0'
CACHE_TTL = 3600
REQUEST_TIMEOUT = 30
SESSION_CACHE_KEY = 'facebook_pages_data'
LAST_FETCH_KEY = 'last_fetch_time'

# Custom CSS
st.markdown('''
<style>
.stApp {
    background: linear-gradient(135deg, #0f172a 0%, #111827 50%, #1e293b 100%);
    color: white;
}
[data-testid="stSidebar"] {
    background: rgba(15, 23, 42, 0.95);
    backdrop-filter: blur(10px);
    border-right: 1px solid rgba(255, 255, 255, 0.08);
}
[data-testid="stMetric"] {
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.08);
    padding: 16px;
    border-radius: 18px;
    backdrop-filter: blur(8px);
    transition: all 0.3s ease;
}
[data-testid="stMetric"]:hover {
    transform: translateY(-2px);
    background: rgba(255, 255, 255, 0.1);
}
.cache-info {
    background: rgba(59, 130, 246, 0.1);
    border: 1px solid rgba(59, 130, 246, 0.3);
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 12px;
    margin-bottom: 10px;
}
/* Button styles */
div.stButton > button {
    border-radius: 8px;
    padding: 4px 12px;
    font-size: 12px;
    font-weight: 500;
    transition: all 0.2s ease;
}
div.stButton > button:hover {
    transform: translateY(-1px);
}
/* Watermark */
.watermark-container {
    position: fixed;
    bottom: 20px;
    left: 0;
    right: 0;
    text-align: center;
    z-index: 999;
    pointer-events: none;
}
.watermark {
    background: rgba(0, 0, 0, 0.6);
    backdrop-filter: blur(10px);
    border-radius: 30px;
    padding: 6px 16px;
    display: inline-block;
    border: 1px solid rgba(255, 255, 255, 0.15);
    font-size: 12px;
    color: rgba(255, 255, 255, 0.7);
    font-family: monospace;
}
.watermark strong {
    color: #14b8a6;
    font-weight: 600;
}
</style>

<div class='watermark-container'>
    <div class='watermark'>
        💻 Phát triển bởi <strong>AnBub</strong> • © 2026 Meta System Intelligence PRO
    </div>
</div>
''', unsafe_allow_html=True)

# ==================== DATA MODELS ====================
@dataclass
class FacebookPageData:
    page_id: str
    page_name: str
    followers: int
    likes: int
    category: str
    viewers_28d: int
    media_views_28d: int
    posts: List[Dict]
    last_updated: datetime
    error: Optional[str] = None

# ==================== CACHE MANAGER (Cloud Compatible) ====================
class CacheManager:
    def __init__(self):
        # Sử dụng temp directory cho cloud environment
        try:
            self.cache_dir = Path(tempfile.gettempdir()) / "meta_cache"
            self.cache_dir.mkdir(exist_ok=True)
            self.use_file_cache = True
        except:
            self.use_file_cache = False
            logger.warning("Cannot create cache directory, using session cache only")
    
    def _get_cache_key(self, key: str) -> str:
        return hashlib.md5(key.encode('utf-8')).hexdigest()
    
    def get(self, key: str, ttl: int = CACHE_TTL) -> Optional[any]:
        # Check session state first (more reliable in cloud)
        session_key = f"cache_{self._get_cache_key(key)}"
        if session_key in st.session_state:
            cache_time = st.session_state.get(f"{session_key}_time")
            if cache_time and datetime.now() - cache_time < timedelta(seconds=ttl):
                return st.session_state[session_key]
        
        # Try file cache if available
        if self.use_file_cache:
            try:
                cache_file = self.cache_dir / f"{self._get_cache_key(key)}.json"
                if cache_file.exists():
                    with open(cache_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        cache_time = datetime.fromisoformat(data['timestamp'])
                        if datetime.now() - cache_time < timedelta(seconds=ttl):
                            return data['value']
            except:
                pass
        return None
    
    def set(self, key: str, value: any):
        session_key = f"cache_{self._get_cache_key(key)}"
        st.session_state[session_key] = value
        st.session_state[f"{session_key}_time"] = datetime.now()
        
        # Try file cache if available
        if self.use_file_cache:
            try:
                cache_file = self.cache_dir / f"{self._get_cache_key(key)}.json"
                with open(cache_file, 'w', encoding='utf-8') as f:
                    json.dump({'timestamp': datetime.now().isoformat(), 'value': value}, f, default=str)
            except:
                pass
    
    def clear(self):
        # Clear session cache
        keys_to_remove = [k for k in st.session_state.keys() if k.startswith('cache_')]
        for k in keys_to_remove:
            del st.session_state[k]
        
        # Clear file cache if available
        if self.use_file_cache:
            try:
                for cache_file in self.cache_dir.glob("*.json"):
                    cache_file.unlink()
            except:
                pass
        logger.info("Cache cleared")

# ==================== FACEBOOK API HANDLER ====================
class FacebookAPIHandler:
    def __init__(self):
        self.cache = CacheManager()
        self.session = requests.Session()
    
    def _request(self, url: str, params: Dict) -> Optional[Dict]:
        try:
            resp = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return resp.json()
            else:
                logger.warning(f"API {resp.status_code}")
                return None
        except Exception as e:
            logger.error(f"Request error: {e}")
            return None
    
    def fetch_page_data(self, page_id: str, token: str, force_refresh: bool = False) -> FacebookPageData:
        cache_key = f"fb_{page_id}_{token[:20]}"
        
        if not force_refresh:
            cached = self.cache.get(cache_key)
            if cached:
                if 'last_updated' in cached:
                    cached['last_updated'] = datetime.fromisoformat(cached['last_updated'])
                logger.info(f"📦 Cache: {cached.get('page_name', page_id)}")
                return FacebookPageData(**cached)
        
        logger.info(f"🌐 API: {page_id}")
        
        try:
            base_url = f'https://graph.facebook.com/{API_VER}/{page_id}'
            info = self._request(base_url, {
                'fields': 'name,fan_count,followers_count,category',
                'access_token': token
            })
            
            if not info:
                raise Exception("Không thể lấy thông tin trang")
            
            insights_url = f'https://graph.facebook.com/{API_VER}/{page_id}/insights'
            viewers_data = self._request(insights_url, {
                'metric': 'page_total_media_view_unique',
                'period': 'days_28',
                'access_token': token
            })
            
            media_views_data = self._request(insights_url, {
                'metric': 'page_media_view',
                'period': 'days_28',
                'access_token': token
            })
            
            viewers_28d = 0
            media_views_28d = 0
            
            if viewers_data and 'data' in viewers_data and viewers_data['data']:
                values = viewers_data['data'][0].get('values', [])
                if values:
                    viewers_28d = values[-1].get('value', 0)
            
            if media_views_data and 'data' in media_views_data and media_views_data['data']:
                values = media_views_data['data'][0].get('values', [])
                if values:
                    media_views_28d = values[-1].get('value', 0)
            
            posts = []
            posts_data = self._request(f'{base_url}/posts', {
                'fields': 'id,message,created_time,permalink_url',
                'limit': 10,
                'access_token': token
            })
            
            if posts_data and 'data' in posts_data:
                for post in posts_data['data']:
                    post_viewers = 0
                    post_insight = self._request(f'https://graph.facebook.com/{API_VER}/{post["id"]}/insights', {
                        'metric': 'post_total_media_view_unique',
                        'access_token': token
                    })
                    
                    if post_insight and 'data' in post_insight and post_insight['data']:
                        vals = post_insight['data'][0].get('values', [])
                        if vals:
                            post_viewers = vals[-1].get('value', 0)
                    
                    posts.append({
                        'id': post.get('id'),
                        'message': (post.get('message') or '')[:200],
                        'created_time': post.get('created_time'),
                        'viewers': post_viewers
                    })
            
            page_data = FacebookPageData(
                page_id=page_id,
                page_name=info.get('name', 'Unknown'),
                followers=info.get('followers_count', 0),
                likes=info.get('fan_count', 0),
                category=info.get('category', 'General'),
                viewers_28d=viewers_28d,
                media_views_28d=media_views_28d,
                posts=posts,
                last_updated=datetime.now(),
                error=None
            )
            
            self.cache.set(cache_key, asdict(page_data))
            return page_data
            
        except Exception as e:
            logger.error(f"Error: {e}")
            return FacebookPageData(
                page_id=page_id, page_name="Lỗi",
                followers=0, likes=0, category="",
                viewers_28d=0, media_views_28d=0,
                posts=[], last_updated=datetime.now(),
                error=str(e)
            )

# ==================== SESSION STATE MANAGER ====================
class SessionStateManager:
    @staticmethod
    def get_data() -> Optional[List[FacebookPageData]]:
        if SESSION_CACHE_KEY in st.session_state:
            data = st.session_state[SESSION_CACHE_KEY]
            if data and isinstance(data[0], dict):
                data = [FacebookPageData(**item) for item in data]
            return data
        return None
    
    @staticmethod
    def set_data(data: List[FacebookPageData]):
        st.session_state[SESSION_CACHE_KEY] = [asdict(item) for item in data]
        st.session_state[LAST_FETCH_KEY] = datetime.now()
    
    @staticmethod
    def get_last_fetch_time() -> Optional[datetime]:
        if LAST_FETCH_KEY in st.session_state:
            return st.session_state[LAST_FETCH_KEY]
        return None
    
    @staticmethod
    def is_data_stale(max_age_minutes: int = 60) -> bool:
        last_fetch = SessionStateManager.get_last_fetch_time()
        if not last_fetch:
            return True
        return datetime.now() - last_fetch > timedelta(minutes=max_age_minutes)
    
    @staticmethod
    def clear():
        if SESSION_CACHE_KEY in st.session_state:
            del st.session_state[SESSION_CACHE_KEY]
        if LAST_FETCH_KEY in st.session_state:
            del st.session_state[LAST_FETCH_KEY]

# ==================== UI COMPONENTS ====================
class DashboardUI:
    @staticmethod
    def render_header():
        st.markdown("""
        <div style='padding: 20px; border-radius: 22px; 
                    background: linear-gradient(135deg, rgba(59,130,246,0.25), rgba(16,185,129,0.18));
                    border: 1px solid rgba(255,255,255,0.08); margin-bottom: 20px'>
            <div style='display: flex; justify-content: space-between; align-items: center'>
                <div>
                    <h1 style='margin: 0'>🚀 Meta System Intelligence PRO</h1>
                    <p style='margin: 8px 0 0 0; color: #cbd5e1'>Công cụ quản lí Fanpage Facebook • Realtime • Cache Thông Minh</p>
                </div>
                <div>
                    <span style='padding: 6px 12px; border-radius: 999px; background: rgba(16,185,129,0.2); border: 1px solid #10b981'>
                        🟢 v3.3
                    </span>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    @staticmethod
    def render_cache_info():
        last_fetch = SessionStateManager.get_last_fetch_time()
        data = SessionStateManager.get_data()
        
        if data and last_fetch:
            age = (datetime.now() - last_fetch).seconds // 60
            st.markdown(f"""
            <div class='cache-info'>
                📦 <strong>Trạng thái Cache:</strong> Đã tải {len(data)} trang • {age} phút trước
                <br>🔄 <strong>Tự động cập nhật sau 60 phút</strong> để tránh bị chặn
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div class='cache-info'>
                ⚡ <strong>Sẵn sàng tải dữ liệu</strong> • Nhấn nút làm mới để lấy dữ liệu từ Facebook
            </div>
            """, unsafe_allow_html=True)
    
    @staticmethod
    def render_sidebar():
        with st.sidebar:
            mode = st.radio("🚀 Meta System Intelligence PRO", ['📊 Tổng Quan', '📈 Phân Tích Trang', '📉 Xuất Dữ Liệu'])
            
            st.markdown("---")
            
            # Two buttons in one row
            col1, col2 = st.columns(2)
            with col1:
                refresh_clicked = st.button("🔄 Làm Mới", use_container_width=True, key="refresh_btn")
                if refresh_clicked:
                    st.markdown("""
                    <style>
                    div[data-testid="column"]:first-child button {
                        background: linear-gradient(90deg, #10b981, #059669);
                        border: none;
                    }
                    </style>
                    """, unsafe_allow_html=True)
            
            with col2:
                clear_clicked = st.button("🗑️ Xóa Cache", use_container_width=True, key="clear_btn")
                if clear_clicked:
                    st.markdown("""
                    <style>
                    div[data-testid="column"]:last-child button {
                        background: linear-gradient(90deg, #ef4444, #dc2626);
                        border: none;
                    }
                    </style>
                    """, unsafe_allow_html=True)
            
            if refresh_clicked:
                CacheManager().clear()
                SessionStateManager.clear()
                st.cache_data.clear()
                st.rerun()
            
            if clear_clicked:
                CacheManager().clear()
                st.success("✅ Đã xóa cache!")
                time.sleep(1)
                st.rerun()
            
            st.markdown("---")
            search = st.text_input("🔍 Tìm Kiếm", placeholder="Tên trang...")
            
            st.markdown("---")
            stats_placeholder = st.empty()
            
            st.markdown("---")
            st.caption("💡 **Update V3.3**")
            st.caption("• Dữ liệu được cache 60 phút")
            st.caption("• Chỉ gọi API 1 lần mỗi giờ")
            st.caption("• Chuyển tab = KHÔNG gọi API")
            
            return mode, search, stats_placeholder
    
    @staticmethod
    def render_overview(pages_data: List[FacebookPageData]):
        valid = [p for p in pages_data if not p.error]
        
        if not valid:
            st.warning("Không có dữ liệu. Nhấn 'Làm Mới' để tải.")
            return
        
        total_followers = sum(p.followers for p in valid)
        total_viewers = sum(p.viewers_28d for p in valid)
        total_media_views = sum(p.media_views_28d for p in valid)
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("📄 Tổng Số Trang", len(valid))
        c2.metric("👥 Tổng Người Theo Dõi", f"{total_followers:,}")
        c3.metric("👁️ Lượt Xem", f"{total_viewers:,}")
        c4.metric("🎬 Lượt Xem Nội Dung", f"{total_media_views:,}")
        
        df = pd.DataFrame([{
            'Tên Trang': p.page_name,
            'Danh Mục': p.category,
            'Người Theo Dõi': p.followers,
            'Lượt Xem': p.viewers_28d,
            'Lượt Xem ND': p.media_views_28d
        } for p in valid])
        
        st.markdown("### 📊 Danh Sách Trang")
        
        st.dataframe(
            df.sort_values('Người Theo Dõi', ascending=False),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Người Theo Dõi": st.column_config.NumberColumn("Người Theo Dõi", format="%d"),
                "Lượt Xem": st.column_config.NumberColumn("Lượt Xem", format="%d"),
                "Lượt Xem ND": st.column_config.NumberColumn("Lượt Xem ND", format="%d"),
            }
        )
        
        all_posts = []
        for p in valid:
            for post in p.posts:
                if post.get('viewers', 0) > 0:
                    all_posts.append({
                        'Trang': p.page_name,
                        'Ngày': post['created_time'][:10] if post['created_time'] else 'N/A',
                        'Nội Dung': (post['message'][:60] + '...') if len(post['message']) > 60 else post['message'],
                        'Lượt Xem': post['viewers']
                    })
        
        if all_posts:
            df_posts = pd.DataFrame(all_posts).sort_values('Lượt Xem', ascending=False).head(10)
            st.markdown("### 🔥 Bài Viết Nổi Bật Nhất")
            st.dataframe(df_posts, use_container_width=True, hide_index=True)
    
    @staticmethod
    def render_page_detail(pages_data: List[FacebookPageData]):
        valid = [p for p in pages_data if not p.error]
        if not valid:
            st.warning("Không có dữ liệu")
            return
        
        selected = st.selectbox("Chọn Trang", [p.page_name for p in valid])
        page = next(p for p in valid if p.page_name == selected)
        
        if page.followers > 0:
            viewer_rate = (page.viewers_28d / page.followers) * 100
            viewer_rate_display = min(viewer_rate, 100)
        else:
            viewer_rate_display = 0
        
        health = min(100, viewer_rate_display * 2)
        
        st.markdown(f"""
        <div style='background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.3); border-radius: 18px; padding: 15px;'>
            <h2>📱 {page.page_name}</h2>
            <p><strong>Danh Mục:</strong> {page.category}</p>
            <p><strong>Cập nhật lần cuối:</strong> {page.last_updated.strftime('%H:%M:%S %d/%m/%Y')}</p>
            <div style='font-size: 2rem; font-weight: bold'>{health:.0f}/100</div>
            <div>Điểm Sức Khỏe</div>
        </div>
        """, unsafe_allow_html=True)
        
        c1, c2, c3 = st.columns(3)
        c1.metric("👥 Người Theo Dõi", f"{page.followers:,}")
        c2.metric("👍 Lượt Thích", f"{page.likes:,}")
        c3.metric("👁️ Lượt Xem", f"{page.viewers_28d:,}")
        
        st.metric("📈 Tỷ Lệ Tương Tác", f"{viewer_rate_display:.2f}%")
        
        if page.posts:
            st.markdown("### 📝 Bài Viết Gần Đây")
            for post in page.posts[:10]:
                with st.container():
                    cols = st.columns([3, 1])
                    cols[0].markdown(f"**📅 {post['created_time'][:10] if post['created_time'] else 'Không rõ'}**")
                    cols[0].markdown(post['message'] if post['message'] else "*Không có nội dung*")
                    if post['viewers'] > 0:
                        cols[1].metric("Lượt Xem", f"{post['viewers']:,}")
                    else:
                        cols[1].markdown("📊 *Chưa có dữ liệu*")
                    st.divider()
    
    @staticmethod
    def render_export(pages_data: List[FacebookPageData]):
        valid = [p for p in pages_data if not p.error]
        if not valid:
            st.warning("Không có dữ liệu để xuất")
            return
        
        export_data = []
        for p in valid:
            export_data.append({
                'Tên Trang': p.page_name,
                'Danh Mục': p.category,
                'ID Trang': p.page_id,
                'Người Theo Dõi': p.followers,
                'Lượt Thích': p.likes,
                'Lượt Xem': p.viewers_28d,
                'Lượt Xem Nội Dung': p.media_views_28d,
                'Cập Nhật Lần Cuối': p.last_updated.strftime('%Y-%m-%d %H:%M:%S')
            })
        
        df = pd.DataFrame(export_data)
        csv = df.to_csv(index=False).encode('utf-8-sig')
        
        st.download_button(
            "📥 Tải CSV",
            csv,
            f"facebook_analytics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            "text/csv"
        )
        st.dataframe(df, use_container_width=True)

# ==================== MAIN ====================
def main():
    fb_handler = FacebookAPIHandler()
    ui = DashboardUI()
    
    # Ưu tiên đọc config từ Streamlit Secrets, nếu không có thì đọc file
    config = None
    try:
        if 'config_json' in st.secrets:
            config = json.loads(st.secrets['config_json'])
        elif 'pages' in st.secrets:
            config = {'pages': st.secrets['pages']}
    except Exception as e:
        st.error(f"Lỗi đọc Streamlit Secrets: {e}")
        st.stop()

    if config is None:
        config_path = None
        possible_paths = ['config.json', 'facebook_config.json', 'fb_config.json']
        for path in possible_paths:
            if Path(path).exists():
                config_path = Path(path)
                break
        if not config_path and Path('../config.json').exists():
            config_path = Path('../config.json')

        if not config_path:
            st.error("❌ Không tìm thấy config trong Secrets hoặc file config.json")
            st.stop()

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except Exception as e:
            st.error(f"Lỗi đọc config: {e}")
            st.stop()

    pages = config.get('pages', [])
    if not pages:
        st.warning("Chưa có trang nào trong config")
        st.stop()
    
    pages_data = SessionStateManager.get_data()
    need_fetch = not pages_data or SessionStateManager.is_data_stale(max_age_minutes=60)
    
    ui.render_header()
    mode, search, stats_placeholder = ui.render_sidebar()
    ui.render_cache_info()
    
    if need_fetch:
        with st.spinner(f"📡 Đang Tải Dữ Liệu Fanpage ! Chờ Xíu Nhaaaaa! ..."):
            pages_data = []
            progress = st.progress(0)
            
            for i, page in enumerate(pages):
                logger.info(f"Đang tải: {page.get('name', page.get('id'))}")
                data = fb_handler.fetch_page_data(page['id'], page['access_token'])
                pages_data.append(data)
                progress.progress((i + 1) / len(pages))
                time.sleep(0.5)
            
            progress.empty()
            SessionStateManager.set_data(pages_data)
            st.success(f"✅ Đã tải {len(pages_data)} trang. Dữ liệu được cache trong 60 phút.")
            time.sleep(1)
            st.rerun()
    else:
        if pages_data:
            last_fetch = SessionStateManager.get_last_fetch_time()
            age = (datetime.now() - last_fetch).seconds // 60
            st.info(f"📦 Đang dùng dữ liệu cache (tải {age} phút trước). Chuyển tab cực nhanh - không gọi API!")
    
    if pages_data:
        valid = [p for p in pages_data if not p.error]
        if valid:
            stats_placeholder.metric("📊 Trang Hoạt Động", len(valid))
            stats_placeholder.metric("👥 Tổng Người Theo Dõi", f"{sum(p.followers for p in valid):,}")
    
    if pages_data and search:
        pages_data = [p for p in pages_data if search.lower() in p.page_name.lower()]
    
    if pages_data:
        if mode == '📊 Tổng Quan':
            ui.render_overview(pages_data)
        elif mode == '📈 Phân Tích Trang':
            ui.render_page_detail(pages_data)
        elif mode == '📉 Xuất Dữ Liệu':
            ui.render_export(pages_data)
    else:
        st.warning("Không có dữ liệu. Vui lòng đợi tải lần đầu.")

if __name__ == "__main__":
    main()
