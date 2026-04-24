import streamlit as st
import pandas as pd
from html import escape
from JobStruct import get_all_jobs

# --- Setup Page Config & Theming ---
st.set_page_config(
    page_title="JobHunter DB Viewer",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Atmospheric, light-forward visual language with stronger typographic hierarchy
MODERN_UI_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;600;700&display=swap');

    :root {
        --page-bg: #f6f8f2;
        --ink: #1f2a24;
        --muted: #526157;
        --surface: rgba(255, 255, 255, 0.86);
        --surface-strong: rgba(255, 255, 255, 0.95);
        --stroke: #d2ddd4;
        --accent: #0f766e;
        --accent-2: #c96c2e;
        --accent-soft: #d8f4ef;
        --shadow: 0 16px 38px rgba(25, 43, 36, 0.10);
    }

    .stApp {
        background:
            radial-gradient(circle at 6% 8%, #e8f7f2 0%, transparent 38%),
            radial-gradient(circle at 96% 4%, #f9e9dc 0%, transparent 34%),
            linear-gradient(180deg, #f8faf6 0%, #f0f5ef 100%);
        color: var(--ink);
        font-family: 'Manrope', 'Segoe UI', sans-serif;
    }

    .block-container {
        max-width: 1180px;
        padding-top: 1.9rem;
        padding-bottom: 2.1rem;
    }

    h1, h2, h3 {
        font-family: 'Space Grotesk', 'Manrope', sans-serif;
        letter-spacing: -0.02em;
        color: var(--ink) !important;
        font-weight: 700 !important;
    }

    h1, h2, h3, h4, h5, h6 {
        color: var(--ink) !important;
    }

    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #f2f7f3 0%, #eaf0eb 100%);
        border-right: 1px solid #d6e0d8;
    }

    [data-testid="stSidebar"] * {
        color: #213129;
    }

    .hero-shell {
        background: linear-gradient(120deg, rgba(255, 255, 255, 0.93) 0%, rgba(247, 255, 252, 0.82) 62%);
        border: 1px solid var(--stroke);
        border-radius: 24px;
        padding: 1.65rem 1.6rem;
        box-shadow: var(--shadow);
        margin-bottom: 1.15rem;
    }

    .hero-kicker {
        color: var(--accent);
        font-size: 0.78rem;
        text-transform: uppercase;
        letter-spacing: 0.14em;
        font-weight: 700;
        margin-bottom: 0.3rem;
    }

    .hero-title {
        font-size: clamp(1.65rem, 2.8vw, 2.35rem);
        line-height: 1.12;
        margin: 0;
    }

    .hero-subtitle {
        margin-top: 0.55rem;
        margin-bottom: 0.8rem;
        color: var(--muted);
        max-width: 860px;
        font-size: 0.98rem;
    }

    .hero-pills {
        display: flex;
        gap: 0.55rem;
        flex-wrap: wrap;
    }

    .hero-pill {
        background: var(--surface-strong);
        border: 1px solid #cad8cf;
        border-radius: 999px;
        padding: 0.34rem 0.78rem;
        font-size: 0.84rem;
        color: #2a3b32;
    }

    .section-label {
        margin-top: 0.65rem;
        margin-bottom: 0.4rem;
        color: #33473b;
        font-weight: 700;
        letter-spacing: 0.02em;
        font-size: 0.95rem;
    }

    .metric-shell {
        background: var(--surface);
        border: 1px solid var(--stroke);
        border-radius: 16px;
        padding: 0.92rem 1rem;
        box-shadow: 0 8px 18px rgba(28, 45, 39, 0.07);
    }

    .metric-label {
        font-size: 0.8rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: #506055;
        font-weight: 700;
        margin-bottom: 0.25rem;
    }

    .metric-value {
        font-family: 'Space Grotesk', 'Manrope', sans-serif;
        font-size: 1.62rem;
        color: #192721;
        font-weight: 700;
        line-height: 1.1;
    }

    .metric-accent .metric-value {
        color: var(--accent);
    }

    .metric-warm .metric-value {
        color: var(--accent-2);
    }

    [data-testid="stDataFrame"] {
        background: var(--surface);
        border-radius: 16px;
        border: 1px solid var(--stroke);
        overflow: hidden;
        box-shadow: var(--shadow);
    }

    [data-baseweb="tab-list"] {
        gap: 0.38rem;
    }

    [data-baseweb="tab"] {
        background: rgba(255, 255, 255, 0.67);
        border-radius: 12px;
        border: 1px solid #d0dbd2;
        height: 40px;
        padding-left: 0.95rem;
        padding-right: 0.95rem;
        color: #2c3f34;
        font-weight: 600;
    }

    [aria-selected="true"][data-baseweb="tab"] {
        background: var(--accent-soft);
        border-color: #a9d8d0;
        color: #0f4f49;
    }

    .spotlight-card {
        background: linear-gradient(156deg, rgba(255, 255, 255, 0.98) 0%, rgba(244, 251, 248, 0.92) 100%);
        border: 1px solid var(--stroke);
        border-radius: 20px;
        padding: 1.25rem;
        box-shadow: var(--shadow);
        margin-top: 0.9rem;
        margin-bottom: 0.95rem;
    }

    .spotlight-top {
        display: flex;
        justify-content: space-between;
        gap: 0.95rem;
        flex-wrap: wrap;
        align-items: flex-start;
    }

    .spotlight-kicker {
        margin: 0;
        font-size: 0.77rem;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: var(--accent);
        font-weight: 700;
    }

    .spotlight-title {
        margin: 0.15rem 0 0.15rem;
        color: #13221b;
        font-family: 'Space Grotesk', 'Manrope', sans-serif;
        font-weight: 700;
        font-size: 1.42rem;
        line-height: 1.2;
    }

    .spotlight-company {
        margin: 0;
        color: #4b5d51;
        font-size: 0.96rem;
    }

    .spotlight-link {
        background: #173a34;
        color: #f2faf8 !important;
        border-radius: 11px;
        border: 1px solid #2a554c;
        text-decoration: none;
        padding: 0.48rem 0.84rem;
        font-size: 0.86rem;
        font-weight: 700;
        transition: all 0.18s ease;
        align-self: center;
    }

    .spotlight-link:hover {
        background: #205048;
        text-decoration: underline;
    }

    .chip-row {
        display: flex;
        gap: 0.5rem;
        flex-wrap: wrap;
        margin-top: 0.9rem;
        margin-bottom: 0.8rem;
    }

    .meta-chip {
        background: rgba(242, 247, 243, 0.9);
        border: 1px solid #d0ddd3;
        color: #2d4135;
        border-radius: 999px;
        padding: 0.33rem 0.72rem;
        font-size: 0.82rem;
        line-height: 1.15;
    }

    .insight-panel {
        background: linear-gradient(130deg, #e7f7f3 0%, #f4fbf8 100%);
        border: 1px solid #c6e6df;
        border-radius: 12px;
        padding: 0.72rem 0.8rem;
    }

    .insight-label {
        font-size: 0.74rem;
        text-transform: uppercase;
        letter-spacing: 0.09em;
        color: #1e6b61;
        font-weight: 800;
        margin-bottom: 0.35rem;
    }

    .insight-text {
        color: #2f4539;
        font-size: 0.91rem;
        margin: 0;
        line-height: 1.43;
    }

    [data-testid="stExpander"] {
        border: 1px solid var(--stroke);
        border-radius: 14px;
        background: rgba(255, 255, 255, 0.82);
    }

    [data-baseweb="input"] > div,
    [data-baseweb="select"] > div {
        border-radius: 12px;
        background: rgba(255, 255, 255, 0.78);
        border-color: #cad8cf;
    }

    [data-testid="stTextInput"] label,
    [data-testid="stMultiSelect"] label,
    [data-testid="stSelectbox"] label,
    [data-testid="stCheckbox"] label {
        font-weight: 600;
        color: #2d3e34;
    }

    @media (max-width: 900px) {
        .hero-shell {
            padding: 1.25rem 1.1rem;
            border-radius: 20px;
        }

        .spotlight-card {
            padding: 1rem;
        }
    }
</style>
"""
st.markdown(MODERN_UI_CSS, unsafe_allow_html=True)


def clean_text(value, fallback="N/A"):
    if value is None:
        return fallback
    if isinstance(value, float) and pd.isna(value):
        return fallback
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return fallback
    return text


def is_remote_value(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, float) and pd.isna(value):
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y", "remote"}


def safe_job_url(value):
    url = clean_text(value, fallback="#")
    if url.startswith("http://") or url.startswith("https://"):
        return escape(url, quote=True)
    return "#"


def grid_listing_url(value):
    url = clean_text(value, fallback="")
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return ""


def normalize_job_type(value):
    if value is None:
        return "undefined"
    if isinstance(value, float) and pd.isna(value):
        return "undefined"
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        return "undefined"
    return text


def render_metric(label, value, tone="default"):
    tone_class = ""
    if tone == "accent":
        tone_class = " metric-accent"
    elif tone == "warm":
        tone_class = " metric-warm"

    st.markdown(
        f"""
        <div class="metric-shell{tone_class}">
            <div class="metric-label">{escape(label)}</div>
            <div class="metric-value">{escape(str(value))}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# --- Sidebar Configuration ---
st.sidebar.markdown("### Data Source")
profile_name = st.sidebar.text_input("Profile Name", value="Thea")
if st.sidebar.button("Refresh cache", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

@st.cache_data(ttl=60)
def load_data(name):
    try:
        jobs = get_all_jobs(name=name)
        return pd.DataFrame(jobs) if jobs else pd.DataFrame()
    except Exception as e:
        st.error(f"Error loading data: {e}")
        return pd.DataFrame()

df = load_data(profile_name)

if not df.empty:
    if "type" in df.columns:
        df["type"] = df["type"].apply(normalize_job_type)
    else:
        df["type"] = "undefined"

hero_profile = escape(clean_text(profile_name, fallback="Unknown profile"))
hero_total = len(df)
st.markdown(
    f"""
    <section class="hero-shell">
        <div class="hero-kicker">Job Pipeline Command Center</div>
        <h1 class="hero-title">JobHunter Pulse Board</h1>
        <p class="hero-subtitle">
            Track opportunities with cleaner signal: scan the full pipeline, filter hard, and inspect each role without visual clutter.
        </p>
        <div class="hero-pills">
            <span class="hero-pill">Profile: {hero_profile}</span>
            <span class="hero-pill">Loaded records: {hero_total}</span>
            <span class="hero-pill">Live cache: 60s</span>
        </div>
    </section>
    """,
    unsafe_allow_html=True,
)

if df.empty:
    st.warning(f"No jobs found for profile: {profile_name}")
    st.info("Run your scraper for this profile, then click Refresh cache in the sidebar.")
else:
    # --- Sidebar Filters ---
    st.sidebar.markdown("---")
    st.sidebar.markdown("### Filter Matrix")

    search_kw = st.sidebar.text_input(
        "Keyword Search",
        placeholder="title, company, location, AI comment...",
    )

    remote_only = st.sidebar.toggle("Remote only", value=False)

    available_types = []
    if "type" in df.columns:
        valid_types = [str(t).strip() for t in df["type"].dropna() if str(t).strip()]
        if valid_types:
            available_types = sorted(list(set(valid_types)))

    selected_types = []
    if available_types:
        selected_types = st.sidebar.multiselect(
            "Job Type",
            options=available_types,
            default=available_types,
        )

    available_sources = []
    if "source" in df.columns:
        valid_sources = [str(s).strip() for s in df["source"].dropna() if str(s).strip()]
        if valid_sources:
            available_sources = sorted(list(set(valid_sources)))

    selected_sources = []
    if available_sources:
        selected_sources = st.sidebar.multiselect(
            "Source",
            options=available_sources,
            default=available_sources,
        )

    # --- Apply Filters ---
    filtered_df = df.copy()

    if search_kw:
        search_str = search_kw.lower()
        search_columns = [
            c
            for c in ["job_title", "company_name", "job_location", "LLMComment", "source"]
            if c in filtered_df.columns
        ]
        if search_columns:
            mask = pd.Series(False, index=filtered_df.index)
            for col in search_columns:
                mask = mask | filtered_df[col].astype(str).str.lower().str.contains(search_str, na=False)
            filtered_df = filtered_df[mask]

    if "type" in filtered_df.columns:
        if available_types and not selected_types:
            filtered_df = filtered_df.iloc[0:0]
        elif selected_types:
            filtered_df = filtered_df[filtered_df["type"].astype(str).isin(selected_types)]

    if "source" in filtered_df.columns:
        if available_sources and not selected_sources:
            filtered_df = filtered_df.iloc[0:0]
        elif selected_sources:
            filtered_df = filtered_df[filtered_df["source"].astype(str).isin(selected_sources)]

    if remote_only and "isRemote" in filtered_df.columns:
        filtered_df = filtered_df[filtered_df["isRemote"].apply(is_remote_value)]

    # --- Metrics Dashboard ---
    remote_count = 0
    if "isRemote" in filtered_df.columns:
        remote_count = int(filtered_df["isRemote"].apply(is_remote_value).sum())

    source_count = 1
    if "source" in filtered_df.columns and not filtered_df.empty:
        source_count = int(filtered_df["source"].astype(str).nunique())

    st.markdown('<div class="section-label">Snapshot</div>', unsafe_allow_html=True)
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        render_metric("Visible Jobs", f"{len(filtered_df):,}", tone="accent")
    with m2:
        render_metric("Remote Roles", f"{remote_count:,}")
    with m3:
        render_metric("Filtered Out", f"{(len(df) - len(filtered_df)):,}", tone="warm")
    with m4:
        render_metric("Active Sources", f"{source_count:,}")

    # --- Views ---
    st.markdown('<div class="section-label">Pipeline Views</div>', unsafe_allow_html=True)
    tab_grid, tab_spotlight, tab_all = st.tabs(["Grid", "Spotlight", "All"])

    with tab_grid:
        display_columns = [
            "job_title",
            "date",
            "company_name",
            "job_location",
            "type",
            "isRemote",
            "salary",
            "source",
            "LLMComment",
            "scraped_at_utc",
        ]
        existing_cols = [c for c in display_columns if c in filtered_df.columns]

        if existing_cols:
            grid_df = filtered_df[existing_cols].copy()
            if "isRemote" in grid_df.columns:
                grid_df["isRemote"] = grid_df["isRemote"].apply(
                    lambda x: "Remote" if is_remote_value(x) else "On-site"
                )

            open_listing_series = pd.Series([""] * len(filtered_df), index=filtered_df.index)
            if "job_url" in filtered_df.columns:
                open_listing_series = filtered_df["job_url"].apply(grid_listing_url)

            grid_df.insert(1, "open_listing", open_listing_series)

            column_config = {
                "open_listing": st.column_config.LinkColumn(
                    "Open listing",
                    display_text="Open listing",
                )
            }

            st.dataframe(
                grid_df,
                use_container_width=True,
                hide_index=True,
                height=420,
                column_config=column_config,
            )
        else:
            st.info("No columns available for the table view with the current dataset.")

    with tab_spotlight:
        if filtered_df.empty:
            st.info("Adjust filters to spotlight a role.")
        else:
            titles = (
                filtered_df["job_title"].astype(str)
                if "job_title" in filtered_df.columns
                else pd.Series(["Untitled role"] * len(filtered_df))
            )
            companies = (
                filtered_df["company_name"].astype(str)
                if "company_name" in filtered_df.columns
                else pd.Series(["Unknown company"] * len(filtered_df))
            )

            options = [
                f"{clean_text(title, 'Untitled role')} | {clean_text(company, 'Unknown company')}"
                for title, company in zip(titles, companies)
            ]

            selected_job_idx = st.selectbox(
                "Choose role",
                range(len(options)),
                format_func=lambda x: options[x],
                label_visibility="collapsed",
            )
            selected_job = filtered_df.iloc[selected_job_idx]

            title = escape(clean_text(selected_job.get("job_title"), "Untitled role"))
            company = escape(clean_text(selected_job.get("company_name"), "Unknown company"))
            location = escape(clean_text(selected_job.get("job_location"), "Location not listed"))
            date_str = escape(clean_text(selected_job.get("date"), "Date unknown"))
            salary = escape(clean_text(selected_job.get("salary"), "Salary unlisted"))
            role_type = escape(clean_text(selected_job.get("type"), "Type not listed"))
            source = escape(clean_text(selected_job.get("source"), "Unknown source"))
            remote_flag = "Remote" if is_remote_value(selected_job.get("isRemote")) else "On-site"
            llm_tag = escape(clean_text(selected_job.get("LLMComment"), "No AI comment available."))
            job_url = safe_job_url(selected_job.get("job_url"))

            spotlight_html = f"""
            <div class="spotlight-card">
                <div class="spotlight-top">
                    <div>
                        <p class="spotlight-kicker">Role Spotlight</p>
                        <h3 class="spotlight-title">{title}</h3>
                        <p class="spotlight-company">{company}</p>
                    </div>
                    <a class="spotlight-link" href="{job_url}" target="_blank">Open listing</a>
                </div>
                <div class="chip-row">
                    <span class="meta-chip">Location: {location}</span>
                    <span class="meta-chip">Date: {date_str}</span>
                    <span class="meta-chip">Salary: {salary}</span>
                    <span class="meta-chip">Type: {role_type}</span>
                    <span class="meta-chip">Mode: {remote_flag}</span>
                    <span class="meta-chip">Source: {source}</span>
                </div>
                <div class="insight-panel">
                    <div class="insight-label">AI Insight</div>
                    <p class="insight-text">{llm_tag}</p>
                </div>
            </div>
            """
            st.markdown(spotlight_html, unsafe_allow_html=True)

            job_desc = clean_text(selected_job.get("job_description"), "No description text available.")
            with st.expander("Read full description", expanded=True):
                st.text(job_desc)

    with tab_all:
        st.caption("Showing all jobs in the database for this profile (ignores sidebar filters).")

        if df.empty:
            st.info("No jobs available in the database for this profile.")
        else:
            all_display_columns = [
                "date",
                "job_title",
                "company_name",
                "job_location",
                "type",
                "isRemote",
                "salary",
                "source",
                "LLMComment",
                "scraped_at_utc",
            ]
            all_existing_cols = [c for c in all_display_columns if c in df.columns]
            all_df = df[all_existing_cols].copy() if all_existing_cols else df.copy()

            if "isRemote" in all_df.columns:
                all_df["isRemote"] = all_df["isRemote"].apply(
                    lambda x: "Remote" if is_remote_value(x) else "On-site"
                )

            st.dataframe(
                all_df,
                use_container_width=True,
                hide_index=True,
                height=420,
            )
