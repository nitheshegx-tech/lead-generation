import hmac, io, json, re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS

st.set_page_config(page_title="EGX Lead Finder", page_icon="📦", layout="wide")

# ---------- Login (set APP_USER / APP_PASSWORD in Streamlit secrets) ----------
def check_login():
    if st.session_state.get("ok"):
        return True
    st.title("📦 EGX Lead Finder")
    u = st.text_input("Username")
    p = st.text_input("Password", type="password")
    if st.button("Log in"):
        good_u = hmac.compare_digest(u, st.secrets.get("APP_USER", ""))
        good_p = hmac.compare_digest(p, st.secrets.get("APP_PASSWORD", ""))
        if good_u and good_p:
            st.session_state["ok"] = True
            st.rerun()
        else:
            st.error("Wrong username or password")
    return False

if not check_login():
    st.stop()

# ---------- Helpers ----------
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537.36"}
SKIP = ("facebook.", "instagram.", "linkedin.", "youtube.", "wikipedia.", "twitter.", "x.com",
        "tiktok.", "pinterest.", "alibaba.", "made-in-china.", "indiamart.", "tradeindia.",
        "amazon.", "ebay.", "reddit.", "quora.", "medium.", "yellowpages", "yelp.", "tripadvisor.",
        "google.", "bing.", "zoominfo.", "crunchbase.", "glassdoor.", "indeed.", "ikman.", "lankabd")
PHONE_RE = re.compile(r"(?:\+?\d{1,3}[\s\-.]?)?(?:\(?\d{2,4}\)?[\s\-.]?)\d{3}[\s\-.]?\d{3,4}")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

def get(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.ok and "text/html" in r.headers.get("content-type", ""):
            return r.text
    except Exception:
        pass
    return ""

def clean_phone(s):
    d = re.sub(r"\D", "", s)
    return s.strip() if 9 <= len(d) <= 13 else None

def scrape(url):
    home = get(url)
    if not home:
        return None
    soup = BeautifulSoup(home, "html.parser")
    pages = [soup]
    # also read the contact page
    for a in soup.find_all("a", href=True):
        if "contact" in a["href"].lower() or "contact" in a.get_text().lower():
            c = get(urljoin(url, a["href"]))
            if c:
                pages.append(BeautifulSoup(c, "html.parser"))
            break

    phones, emails, social = [], [], {"Instagram": "", "Facebook": "", "LinkedIn": ""}
    address = ""
    for s in pages:
        for a in s.find_all("a", href=True):
            h = a["href"]
            low = h.lower()
            if low.startswith("tel:"):
                phones.append(h[4:].replace("%20", " "))
            elif low.startswith("mailto:"):
                emails.append(h[7:].split("?")[0])
            elif "instagram.com/" in low and not social["Instagram"]:
                social["Instagram"] = h
            elif "facebook.com/" in low and "sharer" not in low and not social["Facebook"]:
                social["Facebook"] = h
            elif "linkedin.com/" in low and "share" not in low and not social["LinkedIn"]:
                social["LinkedIn"] = h
        for tag in s.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(tag.string or "")
                for d in (data if isinstance(data, list) else data.get("@graph", [data])):
                    ad = d.get("address") if isinstance(d, dict) else None
                    if isinstance(ad, dict) and not address:
                        address = ", ".join(str(ad.get(k, "")) for k in
                                            ("streetAddress", "addressLocality", "addressCountry") if ad.get(k))
                    if isinstance(d, dict) and d.get("telephone"):
                        phones.append(str(d["telephone"]))
            except Exception:
                pass
        text = s.get_text(" ", strip=True)
        if not phones:
            phones += [m for m in PHONE_RE.findall(text)]
        emails += EMAIL_RE.findall(text)
        if not address:
            m = re.search(r"(?:Address|Head Office|Location)\s*[:\-]?\s*(.{15,120}?)(?:Tel|Phone|Email|Call|$)", text, re.I)
            if m:
                address = m.group(1).strip()

    phones = list(dict.fromkeys(p for p in map(clean_phone, phones) if p))[:3]
    emails = list(dict.fromkeys(e for e in emails if not e.lower().endswith(("png", "jpg", "webp"))))[:2]

    site = soup.find("meta", property="og:site_name")
    title = soup.title.get_text(strip=True) if soup.title else ""
    name = (site["content"] if site and site.get("content") else re.split(r"[|\-–—:]", title)[0]).strip()
    desc = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", property="og:description")
    category = (desc["content"].strip()[:200] if desc and desc.get("content") else title[:200])
    return {"Company Name": name or urlparse(url).netloc, "Website": url,
            "Instagram": social["Instagram"], "Facebook": social["Facebook"],
            "LinkedIn": social["LinkedIn"], "Phone": ", ".join(phones),
            "Email": ", ".join(emails), "Product Category": category, "Location": address}

def find_sites(query, n):
    urls, seen = [], set()
    queries = [query, f"{query} contact", f"{query} manufacturer exporter importer"]
    serper = st.secrets.get("SERPER_API_KEY", "")
    for q in queries:
        results = []
        try:
            if serper:  # optional: free 2,500 searches at serper.dev
                r = requests.post("https://google.serper.dev/search",
                                  headers={"X-API-KEY": serper}, json={"q": q, "num": 20}, timeout=15)
                results = [x["link"] for x in r.json().get("organic", [])]
            else:
                results = [x["href"] for x in DDGS().text(q, max_results=30)]
        except Exception as e:
            st.warning(f"Search issue: {e}")
        for u in results:
            p = urlparse(u)
            dom = p.netloc.lower().replace("www.", "")
            if any(s in dom for s in SKIP) or dom in seen:
                continue
            seen.add(dom)
            urls.append(f"{p.scheme}://{p.netloc}")
        if len(urls) >= n:
            break
    return urls[:n]

# ---------- UI ----------
st.title("📦 EGX Lead Finder")
with st.sidebar:
    if st.button("Log out"):
        st.session_state.clear(); st.rerun()
query = st.text_input("Search", placeholder="paper companies in sri lanka")
n = st.slider("How many companies", 5, 50, 20)

if st.button("Find leads", type="primary") and query:
    with st.spinner("Searching..."):
        sites = find_sites(query, n)
    prog = st.progress(0.0, text=f"Reading {len(sites)} websites...")
    rows = []
    with ThreadPoolExecutor(8) as ex:
        for i, r in enumerate(ex.map(scrape, sites)):
            if r: rows.append(r)
            prog.progress((i + 1) / max(len(sites), 1))
    st.session_state["df"] = pd.DataFrame(rows)

df = st.session_state.get("df")
if df is not None:
    if df.empty:
        st.info("No results. Try a different search.")
    else:
        st.dataframe(df, use_container_width=True)
        buf = io.BytesIO()
        df.to_excel(buf, index=False)
        st.download_button("⬇️ Download Excel", buf.getvalue(), "leads.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
