
**How to get Facebook Access Token:**

1. Go to Graph API Explorer
2. Select your App
3. Add permissions: pages_read_engagement, pages_show_list, read_insights
4. Generate token and get page token from /me/accounts
""")
st.stop()

fb_api = FacebookAPI()
ui = UI()

pages_data = SessionManager.get_data()
need_fetch = not pages_data or SessionManager.is_stale(max_minutes=60)

ui.render_header()

total_pages = len(pages_config) if pages_data else 0
mode, search = ui.render_sidebar(total_pages=total_pages)

ui.render_cache_info()
st.caption("🔐 **Configuration:** Streamlit Secrets (Secure)")

if need_fetch:
with st.spinner(f"📡 Fetching {len(pages_config)} page(s) from Facebook..."):
pages_data = []
progress_bar = st.progress(0)

for i, page_config in enumerate(pages_config):
    page_name = page_config.get('name', page_config.get('id', 'Unknown'))
    st.write(f"📄 Fetching: {page_name}")
    
    data = fb_api.fetch_page(page_config['id'], page_config['access_token'])
    pages_data.append(data)
    progress_bar.progress((i + 1) / len(pages_config))
    time.sleep(0.3)

progress_bar.empty()
SessionManager.set_data(pages_data)
st.success(f"✅ Loaded {len(pages_data)} page(s)")
time.sleep(1)
st.rerun()
else:
if pages_data:
last_fetch = SessionManager.get_last_fetch()
age = (datetime.now() - last_fetch).seconds // 60
st.info(f"📦 Using cached data (fetched {age} minutes ago)")

if pages_data and search:
pages_data = [p for p in pages_data if search.lower() in p.page_name.lower()]

if pages_data:
if mode == '📊 Overview':
ui.render_overview(pages_data)
elif mode == '📈 Page Analytics':
ui.render_page_detail(pages_data)
elif mode == '📉 Export Data':
ui.render_export(pages_data)
else:
if not need_fetch:
st.warning("No data available. Click 'Refresh' to load from Facebook.")


if __name__ == "__main__":
main()
