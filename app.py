from flask import Flask, render_template, request, jsonify
from bs4 import BeautifulSoup
import requests
from urllib.parse import urljoin
import re

app = Flask(__name__)


def fetch_html(url: str, timeout: int = 12):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; SEOAEOGEOBot/3.0)"}
    candidates = [url]
    if url.startswith("https://"):
        candidates.append("http://" + url[len("https://"):])

    errors = []
    for candidate in candidates:
        try:
            s = requests.Session()
            s.trust_env = False  # avoid broken proxy env
            r = s.get(candidate, headers=headers, timeout=timeout, allow_redirects=True, verify=False)
            r.raise_for_status()
            return r.url, r.text
        except Exception as e:
            errors.append(f"{candidate}: {e}")
    raise RuntimeError(" | ".join(errors))


def text_len(v):
    return len(v.strip()) if v else 0


def score_item(ok, weight):
    return weight if ok else 0


def build_actions(audit, url, geo_terms):
    actions = []
    def add(priority, area, action, auto_fix, snippet=None):
        actions.append({"priority": priority, "area": area, "action": action, "auto_fix": auto_fix, "snippet": snippet})
    if not audit["title_ok"]:
        add("High", "SEO", "Write a unique title tag (50-60 chars).", True, f"<title>{audit.get('suggested_title','Primary Keyword | Brand')}</title>")
    if not audit["meta_desc_ok"]:
        add("High", "SEO", "Add meta description (140-160 chars).", True, f"<meta name=\"description\" content=\"{audit.get('suggested_meta','Clear offer + proof + CTA.')}\">")
    if not audit["canonical_ok"]:
        add("High", "SEO", "Set canonical URL.", True, f"<link rel=\"canonical\" href=\"{url}\">")
    if not audit["h1_ok"]:
        add("High", "SEO", "Use exactly one H1.", False)
    if not audit["schema_ok"]:
        add("Medium", "AEO", "Add JSON-LD schema.", True)
    if not audit["aeo_answer_ok"]:
        add("High", "AEO", "Add question headings with concise answers.", False)
    if geo_terms and not audit["geo_ok"]:
        add("High", "GEO", "Include all geo terms in body and headings.", False)
    if not audit["local_schema_ok"]:
        add("Medium", "GEO", "Add LocalBusiness schema and NAP.", True)
    if not audit["og_ok"]:
        add("Low", "SEO", "Add OpenGraph/Twitter tags.", True)
    actions.sort(key=lambda x: {"High": 0, "Medium": 1, "Low": 2}[x["priority"]])
    return actions


def run_audit(final_url, html, geo_terms):
    soup = BeautifulSoup(html, "html.parser")
    text_content = soup.get_text(" ", strip=True).lower()
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    meta_desc = ""
    m = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    if m:
        meta_desc = m.get("content", "").strip()
    canonical = ""
    c = soup.find("link", rel=lambda v: v and "canonical" in str(v).lower())
    if c:
        canonical = c.get("href", "").strip()
    h1s = soup.find_all("h1")
    schema_blocks = soup.find_all("script", attrs={"type": "application/ld+json"})
    local_like = any("localbusiness" in (b.get_text() or "").lower() for b in schema_blocks)
    og_ok = bool(soup.find("meta", property="og:title") and soup.find("meta", attrs={"name": "twitter:card"}))
    images = soup.find_all("img")
    images_missing_alt = sum(1 for i in images if not i.get("alt"))
    q_headers = [h.get_text(" ", strip=True) for h in soup.find_all(re.compile(r"^h[2-4]$")) if "?" in h.get_text(" ", strip=True)]

    title_ok = 50 <= text_len(title) <= 60
    meta_desc_ok = 140 <= text_len(meta_desc) <= 160
    canonical_ok = canonical != ""
    h1_ok = len(h1s) == 1
    schema_ok = len(schema_blocks) > 0
    aeo_answer_ok = len(q_headers) > 0 and ("what is" in text_content or "how to" in text_content or "answer" in text_content)
    geo_ok = all(term in text_content for term in geo_terms) if geo_terms else True

    score = sum([score_item(title_ok,12),score_item(meta_desc_ok,12),score_item(canonical_ok,8),score_item(h1_ok,8),score_item(schema_ok,12),score_item(aeo_answer_ok,14),score_item(geo_ok,14),score_item(local_like,8),score_item(og_ok,6),max(0,6-min(images_missing_alt,6))])

    audit = {"final_url":final_url,"title_length":text_len(title),"meta_description_length":text_len(meta_desc),"checks":{"title_ok":title_ok,"meta_desc_ok":meta_desc_ok,"canonical_ok":canonical_ok,"h1_ok":h1_ok,"schema_ok":schema_ok,"aeo_answer_ok":aeo_answer_ok,"geo_ok":geo_ok,"local_schema_ok":local_like,"og_ok":og_ok},"score":score,"images_missing_alt":images_missing_alt,"robots_txt":urljoin(final_url,"/robots.txt"),"sitemap_xml":urljoin(final_url,"/sitemap.xml"),"title_ok":title_ok,"meta_desc_ok":meta_desc_ok,"canonical_ok":canonical_ok,"h1_ok":h1_ok,"schema_ok":schema_ok,"aeo_answer_ok":aeo_answer_ok,"geo_ok":geo_ok,"local_schema_ok":local_like,"og_ok":og_ok,"suggested_title":title[:50] if title else "Primary Keyword | Brand","suggested_meta":meta_desc[:150] if meta_desc else "Clear value proposition + CTA."}
    return {"audit": audit, "actions": build_actions(audit, final_url, geo_terms)}


@app.route('/')
def home():
    return render_template('index.html')

@app.route('/demo_report')
def demo_report():
    demo_html = """<!doctype html><html><head><title>Austin Roofing Company</title></head><body><h1>Roof Repair</h1><h2>How much does roof repair cost?</h2><p>Answer: depends on damage severity and material type.</p><img src='roof.jpg'></body></html>"""
    return jsonify(run_audit('https://demo.local', demo_html, ['austin','texas']))

@app.route('/audit', methods=['POST'])
def audit_site():
    p = request.get_json(force=True)
    url = p.get('url', '').strip()
    geo_terms = [t.strip().lower() for t in p.get('geo_terms', []) if t.strip()]
    if not url.startswith(('http://','https://')):
        url = 'https://' + url
    try:
        final_url, html = fetch_html(url)
        return jsonify(run_audit(final_url, html, geo_terms))
    except Exception as e:
        return jsonify({'error': f"Live fetch failed. Try Paste HTML or Demo. Details: {e}"}), 400

@app.route('/audit_html', methods=['POST'])
def audit_html():
    p = request.get_json(force=True)
    html = p.get('html', '').strip()
    if not html:
        return jsonify({'error':'html is required'}), 400
    return jsonify(run_audit(p.get('base_url','https://example.com'), html, [t.strip().lower() for t in p.get('geo_terms', []) if t.strip()]))

if __name__ == '__main__':
    app.run(debug=True)
