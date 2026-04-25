from __future__ import annotations

import streamlit as st


def set_page() -> None:
    st.set_page_config(
        page_title="Medical Health Units – Data Collection",
        layout="wide",
        initial_sidebar_state="expanded",
    )


def inject_css() -> None:
    st.markdown(
        """
        <style>
        :root{
          --bg: #0b1220;
          --card: rgba(255,255,255,0.06);
          --card2: rgba(255,255,255,0.08);
          --border: rgba(255,255,255,0.10);
          --text: rgba(255,255,255,0.92);
          --muted: rgba(255,255,255,0.72);
          --accent: #7c3aed;
          --accent2: #22c55e;
          --warn: #f59e0b;
          --danger: #ef4444;
          --shadow: 0 18px 60px rgba(0,0,0,0.38);
        }

        .stApp{
          background:
            radial-gradient(1200px 500px at 20% 0%, rgba(124, 58, 237, 0.18), transparent 60%),
            radial-gradient(900px 500px at 90% 10%, rgba(34, 197, 94, 0.16), transparent 55%),
            radial-gradient(700px 420px at 60% 120%, rgba(59, 130, 246, 0.10), transparent 60%),
            var(--bg);
          color: var(--text);
        }

        /* Sidebar */
        section[data-testid="stSidebar"]{
          background: linear-gradient(180deg, rgba(255,255,255,0.06), rgba(255,255,255,0.03));
          border-right: 1px solid var(--border);
        }

        /* Cards */
        div[data-testid="stMetric"]{
          background: var(--card);
          border: 1px solid var(--border);
          border-radius: 16px;
          padding: 10px 14px;
          box-shadow: var(--shadow);
        }

        /* Inputs */
        .stTextInput input, .stNumberInput input, .stDateInput input, .stSelectbox div[data-baseweb="select"]{
          background: rgba(255,255,255,0.06) !important;
          border: 1px solid rgba(255,255,255,0.12) !important;
          border-radius: 12px !important;
        }

        /* Buttons */
        .stButton > button{
          border-radius: 14px;
          border: 1px solid rgba(255,255,255,0.14);
          background: linear-gradient(135deg, rgba(124,58,237,0.95), rgba(79,70,229,0.95));
          color: white;
          box-shadow: var(--shadow);
          padding: 0.55rem 1rem;
          font-weight: 650;
        }
        .stButton > button:hover{
          filter: brightness(1.05);
          border-color: rgba(255,255,255,0.22);
        }

        /* Headings */
        h1, h2, h3{
          letter-spacing: -0.02em;
        }

        /* Alert box */
        .mhud-alert{
          background: rgba(245, 158, 11, 0.10);
          border: 1px solid rgba(245, 158, 11, 0.25);
          padding: 10px 12px;
          border-radius: 14px;
          color: rgba(255,255,255,0.92);
        }
        .mhud-danger{
          background: rgba(239, 68, 68, 0.10);
          border: 1px solid rgba(239, 68, 68, 0.25);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def warn_box(msg: str) -> None:
    st.markdown(f'<div class="mhud-alert">{msg}</div>', unsafe_allow_html=True)


def danger_box(msg: str) -> None:
    st.markdown(f'<div class="mhud-alert mhud-danger">{msg}</div>', unsafe_allow_html=True)

