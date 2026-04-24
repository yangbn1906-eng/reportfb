import streamlit as st
import pandas as pd
import requests
import json
import logging
import hashlib
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
import numpy as np

st.set_page_config(
    page_title='Meta System Intelligence PRO',
    page_icon='🚀',
    layout='wide',
    initial_sidebar_state='expanded'
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

API_VERSION = 'v25.0'
CACHE_TTL_SECONDS = 3600
REQUEST_TIMEOUT = 30
SESSION_DATA_KEY = 'fb_pages_data'
SESSION_TIME_KEY = 'fb_fetch_time'

st.markdown("""
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
    border-radius: 18px;
    padding: 16px;
    backdrop-filter: blur(8px);
}
div.stButton > button {
    border-radius: 8px;
    padding: 4px 12px;
    font-size: 12px;
}
.stDataFrame {
    background: transparent !important;
}
.stDataFrame thead tr th {
    background: rgba(255, 255, 255, 0.04) !important;
    color: #fff !important;
}
.cache-info {
    background: rgba(59, 130, 246, 0.1);
    border: 1px solid rgba(59, 130, 246, 0.3);
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 12px;
    margin-bottom: 10px;
}
.success-card {
    background: rgba(16, 185, 129, 0.1);
    border: 1px solid rgba(16, 185, 129, 0.3);
    border-radius: 18px;
    padding: 15px;
}
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
    font-size: 12px;
    color: rgba(255, 255, 255, 0.7);
}
.watermark strong {
    color: #14b8a6;
}
</style>

<div class='watermark-container'>
    <div class='watermark'>
        💻 Developed by <strong>AnBub</strong> • © 2026
    </div>
</div>
""", unsafe_allow_html=True)


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


class ConfigLoader:
    @staticmethod
    def load_from_secrets() -> Optional[List[Dict]]:
        try:
            if 'facebook_pages' in st.secrets:
                pages = st.secrets['facebook_pages']
                if isinstance(pages, list) and len(pages) > 0:
                    logger.info(f"Loaded {len(pages)} page(s) from Streamlit Secrets")
                    return pages
            return None
        except Exception as e:
            logger.error(f"Error loading secrets: {e}")
            return None


class CacheManager:
    def __init__(self):
        self.use_file_cache = False
        try:
            self.cache_dir = Path(tempfile.gettempdir()) / "meta_cache_v4"
            self.cache_dir.mkdir(exist_ok=True)
            self.use_file_cache = True
        except Exception:
            pass
    
    def _get_key(self, key: str) -> str:
        return hashlib.md5(key.encode('utf-8')).hexdigest()
    
    def get(self, key: str, ttl: int = CACHE_TTL_SECONDS) -> Optional[any]:
        session_key = f"cache_{self._get_key(key)}"
        if session_key in st.session_state:
            cache_time = st.session_state.get(f"{session_key}_time")
            if cache_time and datetime.now() - cache_time < timedelta(seconds=ttl):
                return st.session_state[session_key]
        
        if self.use_file_cache:
            try:
                cache_file = self.cache_dir / f"{self._get_key(key)}.json"
                if cache_file.exists():
                    with open(cache_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        cache_time = datetime.fromisoformat(data['timestamp'])
                        if datetime.now() - cache_time < timedelta(seconds=ttl):
                            return data['value']
            except Exception:
                pass
        return None
    
    def set(self, key: str, value: any):
        session_key = f"cache_{self._get_key(key)}"
        st.session_state[session_key] = value
        st.session_state[f"{session_key}_time"] = datetime.now()
        
        if self.use_file_cache:
            try:
                cache_file = self.cache_dir / f"{self._get_key(key)}.json"
                with open(cache_file, 'w', encoding='utf-8') as f:
                    json.dump({
                        'timestamp': datetime.now().isoformat(),
                        'value': value
                    }, f, default=str, ensure_ascii=False)
            except Exception:
                pass
    
    def clear(self):
        keys_to_remove = [k for k in st.session_state.keys() if k.startswith('cache_')]
        for k in keys_to_remove:
            del st.session_state[k]
        
        if self.use_file_cache:
            try:
                for cache_file in self.cache_dir.glob("*.json"):
                    cache_file.unlink()
            except Exception:
                pass


class FacebookAPI:
    def __init__(self):
        self.cache = CacheManager()
        self.session = requests.Session()
    
    def _request(self, url: str, params: Dict) -> Optional[Dict]:
        try:
            response = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"API error {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Request failed: {e}")
            return None
    
    def fetch_page(self, page_id: str, token: str, force_refresh: bool = False) -> FacebookPageData:
        cache_key = f"page_{page_id}_{token[:20]}"
        
        if not force_refresh:
            cached = self.cache.get(cache_key)
            if cached:
                if 'last_updated' in cached:
                    cached['last_updated'] = datetime.fromisoformat(cached['last_updated'])
                logger.info(f"Cache: {cached.get('page_name', page_id)}")
                return FacebookPageData(**cached)
        
        logger.info(f"API: {page_id}")
        
        try:
            base_url = f'https://graph.facebook.com/{API_VERSION}/{page_id}'
            info = self._request(base_url, {
                'fields': 'name,fan_count,followers_count,category',
                'access_token': token
            })
            
            if not info:
                raise Exception("Cannot fetch page info")
            
            insights_url = f'{base_url}/insights'
            
            viewers_data = self._request(insights_url, {
                'metric': 'page_total_media_view_unique',
                'period': 'days_28',
                'access_token': token
            })
            
            media_data = self._request(insights_url, {
                'metric': 'page_media_view',
                'period': 'days_28',
                'access_token': token
            })
            
            viewers = 0
            media_views = 0
            
            if viewers_data and viewers_data.get('data'):
                values = viewers_data['data'][0].get('values', [])
                if values:
                    viewers = values[-1].get('value', 0)
            
            if media_data and media_data.get('data'):
                values = media_data['data'][0].get('values', [])
                if values:
                    media_views = values[-1].get('value', 0)
            
            posts = []
            posts_data = self._request(f'{base_url}/posts', {
                'fields': 'id,message,created_time,permalink_url',
                'limit': 10,
                'access_token': token
            })
            
            if posts_data and posts_data.get('data'):
                for post in posts_data['data'][:10]:
                    post_viewers = 0
                    
                    post_insight = self._request(
                        f'https://graph.facebook.com/{API_VERSION}/{post["id"]}/insights',
                        {'metric': 'post_total_media_view_unique', 'access_token': token}
                    )
                    
                    if post_insight and post_insight.get('data'):
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
                viewers_28d=viewers,
                media_views_28d=media_views,
                posts=posts,
                last_updated=datetime.now(),
                error=None
            )
            
            self.cache.set(cache_key, asdict(page_data))
            logger.info(f"Fetched: {page_data.page_name} | Viewers: {viewers:,}")
            return page_data
            
        except Exception as e:
            logger.error(f"Error: {e}")
            return FacebookPageData(
                page_id=page_id,
                page_name="Error",
                followers=0, likes=0, category="",
                viewers_28d=0, media_views_28d=0,
                posts=[],
                last_updated=datetime.now(),
                error=str(e)
            )


class SessionManager:
    @staticmethod
    def get_data() -> Optional[List[FacebookPageData]]:
        if SESSION_DATA_KEY in st.session_state:
            data = st.session_state[SESSION_DATA_KEY]
            if data and isinstance(data[0], dict):
                data = [FacebookPageData(**item) for item in data]
            return data
        return None
    
    @staticmethod
    def set_data(data: List[FacebookPageData]):
        st.session_state[SESSION_DATA_KEY] = [asdict(item) for item in data]
        st.session_state[SESSION_TIME_KEY] = datetime.now()
    
    @staticmethod
    def get_last_fetch() -> Optional[datetime]:
        return st.session_state.get(SESSION_TIME_KEY)
    
    @staticmethod
    def is_stale(max_minutes: int = 60) -> bool:
        last_fetch = SessionManager.get_last_fetch()
        if not last_fetch:
            return True
        return datetime.now() - last_fetch > timedelta(minutes=max_minutes)
    
    @staticmethod
    def clear():
        if SESSION_DATA_KEY in st.session_state:
            del st.session_state[SESSION_DATA_KEY]
        if SESSION_TIME_KEY in st.session_state:
            del st.session_state[SESSION_TIME_KEY]


class UI:
    @staticmethod
    def render_header():
        st.markdown("""
        <div style='padding: 20px; border-radius: 22px; 
                    background: linear-gradient(135deg, rgba(59,130,246,0.25), rgba(16,185,129,0.18));
                    border: 1px solid rgba(255,255,255,0.08); margin-bottom: 20px'>
            <div style='display: flex; justify-content: space-between; align-items: center'>
                <div>
                    <h1 style='margin: 0'>🚀 Meta System Intelligence PRO</h1>
                    <p style='margin: 8px 0 0 0; color: #cbd5e1'>
                        Facebook Page Analytics • Real-time • Secure
                    </p>
                </div>
                <div>
                    <span style='padding: 6px 12px; border-radius: 999px; 
                                 background: rgba(16,185,129,0.2); border: 1px solid #10b981'>
                        🟢 ACTIVE
                    </span>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    @staticmethod
    def render_sidebar(total_pages: int = 0):
        with st.sidebar:
            st.markdown("### 🎮 Controls")
            
            mode = st.radio(
                "View Mode",
                ['📊 Overview', '📈 Page Analytics', '📉 Export Data']
            )
            
            st.markdown("---")
            
            col1, col2 = st.columns(2)
            with col1:
                refresh = st.button("🔄 Refresh", use_container_width=True)
            with col2:
                clear = st.button("🗑️ Clear Cache", use_container_width=True)
            
            if refresh:
                CacheManager().clear()
                SessionManager.clear()
                st.cache_data.clear()
                st.rerun()
            
            if clear:
                CacheManager().clear()
                st.success("✅ Cache cleared!")
                time.sleep(1)
                st.rerun()
            
            st.markdown("---")
            search = st.text_input("🔍 Search Pages", placeholder="Page name...")
            st.markdown("---")
            
            st.markdown("""
            <div style='background: rgba(16, 185, 129, 0.15); border-radius: 8px; padding: 8px; text-align: center'>
                🔐 <strong>Streamlit Secrets</strong><br>
                <span style='font-size: 11px'>Tokens are encrypted</span>
            </div>
            """, unsafe_allow_html=True)
            
            st.markdown("---")
            stats_placeholder = st.empty()
            
            if total_pages > 0:
                stats_placeholder.metric("📊 Pages Loaded", total_pages)
            
            st.caption("💡 **Tips**")
            st.caption("• Data cached for 1 hour")
            st.caption("• Only 1 API call per page/hour")
            
            return mode, search
    
    @staticmethod
    def render_cache_info():
        last_fetch = SessionManager.get_last_fetch()
        data = SessionManager.get_data()
        
        if data and last_fetch:
            age = (datetime.now() - last_fetch).seconds // 60
            st.markdown(f"""
            <div class='cache-info'>
                📦 <strong>Cache:</strong> {len(data)} pages • {age} minutes ago
                <br>🔄 Auto-refresh after 60 minutes
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div class='cache-info'>
                ⚡ <strong>Ready</strong> • Click Refresh to load data from Facebook
            </div>
            """, unsafe_allow_html=True)
    
    @staticmethod
    def render_overview(pages_data: List[FacebookPageData]):
        valid = [p for p in pages_data if not p.error and p.followers > 0]
        
        if not valid:
            st.warning("No valid data. Click 'Refresh' to load from Facebook.")
            return
        
        total_followers = sum(p.followers for p in valid)
        total_viewers = sum(p.viewers_28d for p in valid)
        total_posts = sum(len(p.posts) for p in valid)
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("📄 Total Pages", len(valid))
        col2.metric("👥 Total Followers", f"{total_followers:,}")
        col3.metric("👁️ Total Viewers", f"{total_viewers:,}")
        col4.metric("📝 Total Posts", total_posts)
        
        df_pages = pd.DataFrame([{
            'Page Name': p.page_name,
            'Category': p.category,
            'Followers': p.followers,
            'Viewers': p.viewers_28d,
            'Media Views': p.media_views_28d
        } for p in valid])
        
        st.markdown("### 📊 Pages Overview")
        st.dataframe(
            df_pages.sort_values('Followers', ascending=False),
            use_container_width=True,
            hide_index=True
        )
        
        all_posts = []
        for page in valid:
            for post in page.posts:
                if post.get('viewers', 0) > 0:
                    all_posts.append({
                        'Page': page.page_name,
                        'Date': post['created_time'][:10] if post['created_time'] else 'N/A',
                        'Content': (post['message'][:60] + '...') if len(post['message']) > 60 else post['message'],
                        'Viewers': post['viewers']
                    })
        
        if all_posts:
            df_posts = pd.DataFrame(all_posts).sort_values('Viewers', ascending=False).head(10)
            st.markdown("### 🔥 Top Posts")
            st.dataframe(df_posts, use_container_width=True, hide_index=True)
    
    @staticmethod
    def render_page_detail(pages_data: List[FacebookPageData]):
        valid = [p for p in pages_data if not p.error and p.followers > 0]
        
        if not valid:
            st.warning("No valid data. Click 'Refresh' to load.")
            return
        
        selected = st.selectbox("Select Page", [p.page_name for p in valid])
        page = next(p for p in valid if p.page_name == selected)
        
        if page.followers > 0:
            viewer_rate = min((page.viewers_28d / page.followers) * 100, 100)
        else:
            viewer_rate = 0
        
        health_score = min(100, viewer_rate * 2)
        
        st.markdown(f"""
        <div class='success-card'>
            <h2>📱 {page.page_name}</h2>
            <p><strong>Category:</strong> {page.category}</p>
            <p><strong>Last updated:</strong> {page.last_updated.strftime('%H:%M:%S %d/%m/%Y')}</p>
            <div style='font-size: 2rem; font-weight: bold; margin-top: 10px'>{health_score:.0f}/100</div>
            <div>Health Score</div>
        </div>
        """, unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns(3)
        col1.metric("👥 Followers", f"{page.followers:,}")
        col2.metric("👍 Likes", f"{page.likes:,}")
        col3.metric("👁️ Viewers", f"{page.viewers_28d:,}")
        
        st.metric("📈 Viewer Rate", f"{viewer_rate:.2f}%")
        
        if page.posts:
            st.markdown("### 📝 Recent Posts")
            for post in page.posts[:10]:
                with st.container():
                    cols = st.columns([3, 1])
                    date_str = post['created_time'][:10] if post['created_time'] else 'Unknown'
                    cols[0].markdown(f"**📅 {date_str}**")
                    cols[0].markdown(post['message'] if post['message'] else "*No content*")
                    cols[1].metric("Viewers", f"{post['viewers']:,}")
                    st.divider()
    
    @staticmethod
    def render_export(pages_data: List[FacebookPageData]):
        valid = [p for p in pages_data if not p.error and p.followers > 0]
        
        if not valid:
            st.warning("No data to export. Click 'Refresh' to load.")
            return
        
        export_data = []
        for page in valid:
            export_data.append({
                'Page Name': page.page_name,
                'Category': page.category,
                'Page ID': page.page_id,
                'Followers': page.followers,
                'Likes': page.likes,
                'Viewers': page.viewers_28d,
                'Media Views': page.media_views_28d,
                'Last Updated': page.last_updated.strftime('%Y-%m-%d %H:%M:%S')
            })
        
        df = pd.DataFrame(export_data)
        csv_data = df.to_csv(index=False).encode('utf-8-sig')
        
        st.download_button(
            "📥 Download CSV",
            csv_data,
            f"facebook_analytics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            "text/csv",
            use_container_width=True
        )
        
        st.markdown("### 📊 Data Preview")
        st.dataframe(df, use_container_width=True)


def main():
    pages_config = ConfigLoader.load_from_secrets()
    
    if not pages_config:
        st.error("🔒 No configuration found in Streamlit Secrets!")
        
        
