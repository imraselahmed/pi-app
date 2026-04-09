from flask import Flask, request, jsonify
from flask_cors import CORS
import re, time
from collections import Counter
from urllib.parse import urljoin, urlparse

app = Flask(__name__)
CORS(app)

def get_soup(url, timeout=15):
    import requests
    from bs4 import BeautifulSoup
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
    return BeautifulSoup(resp.text, "html.parser"), resp

def clean_text(soup):
    for t in soup(["script","style","nav","footer","header"]): t.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))

def require_url(data):
    url = data.get("url","").strip()
    if not url: return None, jsonify({"error":"url is required"}), 400
    return url, None, None

@app.route("/", methods=["GET"])
def index():
    routes = sorted([str(r) for r in app.url_map.iter_rules() if r.methods and "POST" in r.methods])
    return jsonify({"message":"SEO Toolkit API — 50 Tools","routes":routes})

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status":"ok"})

# 1. Anchor Text Analyzer
@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.json; url,err,code = require_url(data)
    if err: return err, code
    try:
        soup,_ = get_soup(url)
        base_domain = urlparse(url).netloc
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip(); full = urljoin(url,href)
            anchor = a.get_text(strip=True); t = anchor.lower().strip()
            is_internal = urlparse(full).netloc == base_domain
            is_image = bool(a.find("img")); nofollow = "nofollow" in a.get("rel",[])
            if is_image: atype="image"
            elif not t: atype="empty"
            elif t in ("click here","read more","learn more","here","this","link","more"): atype="generic"
            elif re.match(r"^https?://",t): atype="naked_url"
            else: atype="descriptive"
            links.append({"url":full[:200],"anchor_text":anchor[:100],"is_internal":is_internal,
                          "is_image_link":is_image,"nofollow":nofollow,"anchor_type":atype})
        types = Counter(l["anchor_type"] for l in links)
        top_anchors = Counter(l["anchor_text"] for l in links if l["anchor_text"]).most_common(10)
        return jsonify({"total":len(links),"internal":sum(1 for l in links if l["is_internal"]),
                        "external":sum(1 for l in links if not l["is_internal"]),
                        "type_distribution":dict(types),"top_anchors":top_anchors,"links":links[:100]})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 2. Meta Tag Analyzer
@app.route("/meta-tags", methods=["POST"])
def meta_tags():
    data = request.json; url,err,code = require_url(data)
    if err: return err, code
    try:
        import json as _j
        soup,_ = get_soup(url); issues=[]
        title = soup.title.get_text(strip=True) if soup.title else ""
        if not title: issues.append("Missing title tag")
        elif len(title)>60: issues.append(f"Title too long ({len(title)} chars)")
        elif len(title)<20: issues.append("Title too short")
        md = soup.find("meta",attrs={"name":"description"})
        desc = md["content"] if md and md.get("content") else ""
        if not desc: issues.append("Missing meta description")
        elif len(desc)>160: issues.append(f"Meta description too long ({len(desc)} chars)")
        canon = soup.find("link",rel="canonical")
        canonical = canon["href"] if canon and canon.get("href") else ""
        if not canonical: issues.append("Missing canonical URL")
        og = {m["property"]:m.get("content","") for m in soup.find_all("meta",attrs={"property":re.compile(r"^og:")}) if m.get("property")}
        tc = {m["name"]:m.get("content","") for m in soup.find_all("meta",attrs={"name":re.compile(r"^twitter:")}) if m.get("name")}
        if not og.get("og:title"): issues.append("Missing og:title")
        if not og.get("og:image"): issues.append("Missing og:image")
        if not tc.get("twitter:card"): issues.append("Missing twitter:card")
        schemas = soup.find_all("script",type="application/ld+json")
        schema_types=[]
        for s in schemas:
            try: j=_j.loads(s.string); schema_types.append(j.get("@type","?") if isinstance(j,dict) else "list")
            except: pass
        if not schemas: issues.append("No structured data found")
        h1s = soup.find_all("h1")
        if not h1s: issues.append("Missing H1")
        elif len(h1s)>1: issues.append(f"Multiple H1 tags ({len(h1s)})")
        vp = soup.find("meta",attrs={"name":"viewport"})
        if not vp: issues.append("Missing viewport meta tag")
        return jsonify({"title":title,"title_length":len(title),"meta_description":desc,
                        "meta_desc_length":len(desc),"canonical":canonical,
                        "og":og,"twitter":tc,"schema_count":len(schemas),"schema_types":schema_types,
                        "h1_count":len(h1s),"h1_text":h1s[0].get_text(strip=True)[:80] if h1s else "",
                        "has_viewport":vp is not None,"issues":issues,"issue_count":len(issues)})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 3. Heading Analyzer
@app.route("/headings", methods=["POST"])
def headings():
    data = request.json; url,err,code = require_url(data)
    if err: return err, code
    keyword = data.get("keyword","").lower()
    try:
        soup,_ = get_soup(url); heads=[]
        for tag in soup.find_all(re.compile(r"^h[1-6]$")):
            heads.append({"level":int(tag.name[1]),"tag":tag.name.upper(),"text":tag.get_text(strip=True)})
        issues=[]
        h1s=[h for h in heads if h["level"]==1]
        if not h1s: issues.append({"severity":"ERROR","message":"Missing H1"})
        elif len(h1s)>1: issues.append({"severity":"WARNING","message":f"Multiple H1 tags ({len(h1s)})"})
        levels=sorted(set(h["level"] for h in heads))
        for i in range(len(levels)-1):
            if levels[i+1]-levels[i]>1: issues.append({"severity":"WARNING","message":f"Heading level skip: H{levels[i]} to H{levels[i+1]}"})
        if keyword and h1s and not any(keyword in h["text"].lower() for h in h1s):
            issues.append({"severity":"WARNING","message":f"H1 doesn't contain keyword '{keyword}'"})
        h2_count=sum(1 for h in heads if h["level"]==2)
        if h2_count==0 and h1s: issues.append({"severity":"WARNING","message":"No H2 subheadings"})
        stats={f"h{i}_count":sum(1 for h in heads if h["level"]==i) for i in range(1,7)}
        return jsonify({"headings":heads,"stats":stats,"issues":issues,"total":len(heads)})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 4. Broken Link Checker
@app.route("/broken-links", methods=["POST"])
def broken_links():
    data = request.json; url,err,code = require_url(data)
    if err: return err, code
    try:
        import requests as req
        soup,_ = get_soup(url); links=[]
        for a in soup.find_all("a",href=True):
            href=a["href"].strip()
            if href.startswith(("#","mailto:","tel:","javascript:")): continue
            full=urljoin(url,href)
            if urlparse(full).scheme in ("http","https"):
                links.append({"target":full[:200],"anchor":a.get_text(strip=True)[:80]})
        unique=list({l["target"]:l for l in links}.values())[:25]
        results=[]
        for l in unique:
            try:
                r=req.head(l["target"],headers={"User-Agent":"Mozilla/5.0"},timeout=8,allow_redirects=True)
                status=r.status_code; error=""
            except Exception as ex: status=0; error=str(ex)[:60]
            results.append({"url":l["target"],"anchor":l["anchor"],"status":status,"error":error,"is_broken":status>=400 or status==0})
        broken=[r for r in results if r["is_broken"]]
        return jsonify({"total_links":len(unique),"broken_count":len(broken),"broken":broken,"all_results":results})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 5. Canonical Checker
@app.route("/canonical", methods=["POST"])
def canonical():
    data = request.json; url,err,code = require_url(data)
    if err: return err, code
    try:
        soup,resp = get_soup(url)
        canon=soup.find("link",rel="canonical")
        canonical_url=canon["href"].strip() if canon and canon.get("href") else ""
        if canonical_url and not canonical_url.startswith("http"): canonical_url=urljoin(url,canonical_url)
        issues=[]
        if not canonical_url: issues.append("No canonical tag found")
        else:
            final_url=resp.url.rstrip("/"); cc=canonical_url.rstrip("/")
            if urlparse(cc).netloc!=urlparse(final_url).netloc: issues.append(f"Cross-domain canonical: {cc[:60]}")
            elif cc!=final_url: issues.append(f"Points elsewhere: {cc[:60]}")
        is_self=canonical_url.rstrip("/")==resp.url.rstrip("/") if canonical_url else False
        return jsonify({"url":url,"final_url":resp.url,"status_code":resp.status_code,
                        "canonical":canonical_url,"is_self_referencing":is_self,"issues":issues,"has_issues":bool(issues)})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 6. Image SEO Analyzer
@app.route("/image-seo", methods=["POST"])
def image_seo():
    data = request.json; url,err,code = require_url(data)
    if err: return err, code
    try:
        soup,_ = get_soup(url); images=[]
        for img in soup.find_all("img"):
            src=img.get("src","") or img.get("data-src","")
            full_src=urljoin(url,src) if src else ""
            filename=urlparse(full_src).path.split("/")[-1] if full_src else ""
            ext=filename.rsplit(".",1)[-1].lower() if "." in filename else ""
            alt=img.get("alt",None); alt_text=(alt or "").strip()
            issues=[]
            if alt is None: issues.append("missing alt attribute")
            elif not alt_text: issues.append("empty alt text")
            elif len(alt_text)>125: issues.append(f"alt too long ({len(alt_text)} chars)")
            if not img.get("width") or not img.get("height"): issues.append("missing width/height")
            if ext in ("bmp","tiff"): issues.append(f"unoptimized format ({ext})")
            if re.match(r"^(img|image|photo|pic)\d*\.",filename.lower()): issues.append("generic filename")
            images.append({"src":full_src[:100],"filename":filename,"format":ext,"alt_text":alt_text[:80],
                           "has_alt":alt is not None,"lazy_loading":img.get("loading")=="lazy" or bool(img.get("data-src")),
                           "issues":"; ".join(issues) if issues else "OK","issue_count":len(issues)})
        return jsonify({"total":len(images),"missing_alt":sum(1 for i in images if not i["has_alt"]),
                        "empty_alt":sum(1 for i in images if i["has_alt"] and not i["alt_text"]),
                        "with_issues":sum(1 for i in images if i["issue_count"]>0),"images":images[:50]})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 7. Mobile Friendly
@app.route("/mobile", methods=["POST"])
def mobile():
    data = request.json; url,err,code = require_url(data)
    if err: return err, code
    try:
        import requests as req
        from bs4 import BeautifulSoup
        resp=req.get(url,headers={"User-Agent":"Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) Mobile/15E148"},timeout=15)
        soup=BeautifulSoup(resp.text,"html.parser"); html=resp.text; score=100; issues=[]
        vp=soup.find("meta",attrs={"name":"viewport"})
        if not vp: score-=25; issues.append("Missing viewport meta tag")
        else:
            content=vp.get("content","")
            if "width=device-width" not in content: score-=10; issues.append("Viewport missing width=device-width")
        fixed_width=re.findall(r'width:\s*(\d{4,})px',html)
        if fixed_width: score-=15; issues.append(f"Fixed widths found: {fixed_width[:2]}px")
        small_fonts=[int(f) for f in re.findall(r'font-size:\s*(\d+)px',html) if int(f)<12]
        if small_fonts: score-=10; issues.append(f"Small font sizes: {small_fonts[:2]}px")
        images=soup.find_all("img")
        non_responsive=[i for i in images if not i.get("srcset") and not i.get("sizes")]
        if non_responsive and len(non_responsive)>len(images)/2: score-=10; issues.append(f"{len(non_responsive)}/{len(images)} images lack responsive attrs")
        amp_link=soup.find("link",rel="amphtml")
        return jsonify({"score":max(score,0),"grade":"A" if score>=80 else "B" if score>=60 else "C" if score>=40 else "D",
                        "has_viewport":vp is not None,"has_amp":amp_link is not None,
                        "image_count":len(images),"issues":issues})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 8. Page Speed
@app.route("/page-speed", methods=["POST"])
def page_speed():
    data = request.json; url,err,code = require_url(data)
    if err: return err, code
    try:
        import requests as req
        from bs4 import BeautifulSoup
        start=time.time(); resp=req.get(url,headers={"User-Agent":"Mozilla/5.0"},timeout=20)
        load_time=round(time.time()-start,3); html=resp.text
        soup=BeautifulSoup(html,"html.parser")
        scripts=soup.find_all("script"); ext_scripts=[s for s in scripts if s.get("src")]
        render_blocking=[s for s in ext_scripts if not s.get("defer") and not s.get("async")]
        stylesheets=soup.find_all("link",rel="stylesheet"); images=soup.find_all("img")
        lazy_images=[i for i in images if i.get("loading")=="lazy" or i.get("data-src")]
        issues=[]
        if load_time>3: issues.append(f"Slow TTFB: {load_time}s")
        if len(render_blocking)>3: issues.append(f"{len(render_blocking)} render-blocking scripts")
        if images and not lazy_images: issues.append("No lazy-loaded images")
        if len(html.encode("utf-8"))>500000: issues.append("Large HTML (>500KB)")
        return jsonify({"response_time_s":load_time,"page_size_kb":round(len(html.encode("utf-8"))/1024,1),
                        "external_scripts":len(ext_scripts),"render_blocking_js":len(render_blocking),
                        "stylesheets":len(stylesheets),"images":len(images),"lazy_images":len(lazy_images),
                        "issues":issues,"score":max(0,100-len(issues)*12)})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 9. Core Web Vitals
@app.route("/cwv", methods=["POST"])
def cwv():
    data = request.json; url,err,code = require_url(data)
    if err: return err, code
    try:
        import requests as req
        from bs4 import BeautifulSoup
        start=time.time(); resp=req.get(url,headers={"User-Agent":"Mozilla/5.0"},timeout=20)
        ttfb=round(time.time()-start,3); soup=BeautifulSoup(resp.text,"html.parser"); issues=[]
        first_img=soup.find("img")
        if first_img and first_img.get("loading")=="lazy": issues.append("First image has lazy loading (delays LCP)")
        preloads=soup.find_all("link",rel="preload"); preload_images=[p for p in preloads if p.get("as")=="image"]
        if not preload_images and first_img: issues.append("No preloaded hero image")
        imgs_no_dims=[i for i in soup.find_all("img") if not (i.get("width") and i.get("height"))]
        if imgs_no_dims: issues.append(f"{len(imgs_no_dims)} images without dimensions (CLS risk)")
        scripts=soup.find_all("script"); ext=[s for s in scripts if s.get("src")]
        blocking=[s for s in ext if not s.get("defer") and not s.get("async")]
        if len(blocking)>3: issues.append(f"{len(blocking)} render-blocking scripts")
        lcp_score=max(0,33-len([i for i in issues if "LCP" in i or "preload" in i])*11)
        cls_score=max(0,33-len([i for i in issues if "CLS" in i or "dimension" in i])*8)
        fid_score=max(0,34-len([i for i in issues if "script" in i.lower()])*8)
        total=lcp_score+cls_score+fid_score
        return jsonify({"ttfb_s":ttfb,"score":total,"lcp_score":lcp_score,"cls_score":cls_score,"fid_score":fid_score,
                        "grade":"GOOD" if total>=80 else "NEEDS IMPROVEMENT" if total>=50 else "POOR","issues":issues,"blocking_scripts":len(blocking)})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 10. Readability
@app.route("/readability", methods=["POST"])
def readability():
    data = request.json; url=data.get("url","").strip(); text_input=data.get("text","").strip()
    if not url and not text_input: return jsonify({"error":"url or text required"}), 400
    try:
        import math
        if url: soup,_=get_soup(url); text=clean_text(soup)
        else: text=text_input
        def count_syl(w):
            w=w.lower()
            if len(w)<=2: return 1
            c=len(re.findall(r"[aeiouy]+",w))
            if w.endswith("e"): c-=1
            return max(c,1)
        sentences=[s.strip() for s in re.split(r"[.!?]+",text) if len(s.strip())>3]
        words=re.findall(r"\b[a-zA-Z]+\b",text)
        if not sentences or not words: return jsonify({"error":"Not enough text"})
        syls=[count_syl(w) for w in words]; total_syl=sum(syls); complex_words=sum(1 for s in syls if s>=3)
        n_sent=len(sentences); n_words=len(words); asl=n_words/n_sent; asw=total_syl/n_words
        fk=round(0.39*asl+11.8*asw-15.59,1); fre=round(206.835-1.015*asl-84.6*asw,1)
        fog=round(0.4*(asl+100*complex_words/n_words),1)
        chars=sum(len(w) for w in words); L=chars/n_words*100; S=n_sent/n_words*100
        cli=round(0.0588*L-0.296*S-15.8,1)
        grade_label="Easy" if fk<=6 else "Fairly Easy" if fk<=8 else "Standard" if fk<=10 else "Fairly Difficult" if fk<=12 else "Difficult"
        sent_lengths=[len(re.findall(r"\b\w+\b",s)) for s in sentences]
        return jsonify({"total_words":n_words,"total_sentences":n_sent,"avg_sentence_length":round(asl,1),
                        "complex_words_pct":round(complex_words/n_words*100,1),"flesch_reading_ease":fre,
                        "flesch_kincaid_grade":fk,"gunning_fog":fog,"coleman_liau":cli,"grade_label":grade_label,
                        "long_sentences":sum(1 for l in sent_lengths if l>25),
                        "very_long_sentences":sum(1 for l in sent_lengths if l>35)})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 11. Content Freshness
@app.route("/freshness", methods=["POST"])
def freshness():
    data = request.json; url,err,code = require_url(data)
    if err: return err, code
    try:
        from datetime import datetime
        soup,resp = get_soup(url); text=clean_text(soup); score=50; factors=[]; now=datetime.now()
        dates_found=[]
        time_tag=soup.find("time",attrs={"datetime":True})
        if time_tag:
            try: dt=datetime.fromisoformat(time_tag["datetime"].replace("Z","").split("+")[0].split("T")[0]); dates_found.append(("html_time_tag",dt.isoformat()))
            except: pass
        for name in ["article:published_time","article:modified_time","og:updated_time"]:
            meta=soup.find("meta",attrs={"property":name}) or soup.find("meta",attrs={"name":name})
            if meta and meta.get("content"):
                try: dt=datetime.fromisoformat(meta["content"].replace("Z","").split("+")[0].split("T")[0]); dates_found.append((name,dt.isoformat()))
                except: pass
        if dates_found:
            newest=datetime.fromisoformat(sorted(dates_found,key=lambda x:x[1])[-1][1])
            days_old=(now-newest).days
            if days_old<=30: score+=25; factors.append({"desc":f"Recently updated ({days_old}d ago)","pts":25})
            elif days_old<=90: score+=15; factors.append({"desc":f"Updated {days_old}d ago","pts":15})
            elif days_old<=365: score+=5; factors.append({"desc":f"Updated {days_old}d ago","pts":5})
            else: score-=15; factors.append({"desc":f"Not updated in {days_old}d","pts":-15})
        else: score-=10; factors.append({"desc":"No date signals found","pts":-10})
        if str(now.year) in text: score+=10; factors.append({"desc":f"References {now.year}","pts":10})
        if re.search(r"\b(flash player|internet explorer|windows xp)\b",text.lower()):
            score-=10; factors.append({"desc":"Outdated technology references","pts":-10})
        final=min(max(score,0),100)
        return jsonify({"score":final,"grade":"A" if final>=80 else "B" if final>=60 else "C" if final>=40 else "D",
                        "factors":factors,"dates_found":dates_found})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 12. Content Optimizer
@app.route("/content-optimizer", methods=["POST"])
def content_optimizer():
    data = request.json; url,err,code = require_url(data)
    if err: return err, code
    keyword=data.get("keyword","").lower()
    try:
        soup,_ = get_soup(url)
        title=soup.title.get_text(strip=True) if soup.title else ""
        md=soup.find("meta",attrs={"name":"description"})
        desc=md["content"] if md and md.get("content") else ""
        h1s=soup.find_all("h1"); h2s=soup.find_all("h2")
        text=clean_text(soup); words=re.findall(r"\b\w+\b",text)
        sentences=[s for s in re.split(r"[.!?]+",text) if len(s.strip())>3]
        internal_links=len([a for a in soup.find_all("a",href=True) if not a["href"].startswith("http")])
        score=0; details=[]
        if keyword and keyword in title.lower(): score+=15; details.append({"check":"Title contains keyword","pts":15,"max":15})
        else: details.append({"check":"Title contains keyword","pts":0,"max":15})
        if keyword and keyword in desc.lower(): score+=10; details.append({"check":"Meta desc contains keyword","pts":10,"max":10})
        else: details.append({"check":"Meta desc contains keyword","pts":0,"max":10})
        if h1s and keyword and keyword in h1s[0].get_text().lower(): score+=10; details.append({"check":"H1 contains keyword","pts":10,"max":10})
        else: details.append({"check":"H1 contains keyword","pts":0,"max":10})
        wc=len(words); wpts=15 if wc>=1500 else 10 if wc>=800 else 5 if wc>=300 else 0
        score+=wpts; details.append({"check":f"Word count: {wc}","pts":wpts,"max":15})
        h2pts=10 if len(h2s)>=2 else 5 if len(h2s)>=1 else 0
        score+=h2pts; details.append({"check":f"Heading structure H2:{len(h2s)}","pts":h2pts,"max":10})
        ilpts=10 if internal_links>=3 else 5 if internal_links>=1 else 0
        score+=ilpts; details.append({"check":f"Internal links: {internal_links}","pts":ilpts,"max":10})
        asl=len(words)/max(len(sentences),1); asw=sum(len(re.findall(r"[aeiouy]+",w)) for w in words)/max(len(words),1)
        fk=0.39*asl+11.8*asw-15.59; rkpts=10 if 6<=fk<=12 else 5 if 4<=fk<=14 else 0
        score+=rkpts; details.append({"check":f"Readability FK: {fk:.1f}","pts":rkpts,"max":10})
        kw_freq=text.lower().count(keyword) if keyword else 0
        kw_density=kw_freq*len(keyword.split())/max(wc,1)*100 if keyword else 0
        kdpts=10 if 0.5<=kw_density<=2.5 else 5 if kw_density>0 else 0
        score+=kdpts; details.append({"check":f"Keyword density: {kw_density:.2f}%","pts":kdpts,"max":10})
        return jsonify({"score":min(score,100),"grade":"A" if score>=80 else "B" if score>=60 else "C" if score>=40 else "D",
                        "word_count":wc,"title":title,"meta_description":desc,"h1_count":len(h1s),"h2_count":len(h2s),
                        "keyword_frequency":kw_freq,"keyword_density":round(kw_density,2),"details":details})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 13. Site Audit
@app.route("/site-audit", methods=["POST"])
def site_audit():
    data = request.json; url,err,code = require_url(data)
    if err: return err, code
    keyword=data.get("keyword","").lower()
    try:
        import requests as req
        from bs4 import BeautifulSoup
        start=time.time(); resp=req.get(url,headers={"User-Agent":"Mozilla/5.0"},timeout=20)
        load_time=round(time.time()-start,2); soup=BeautifulSoup(resp.text,"html.parser"); html=resp.text
        issues=[]; passed=[]
        title=soup.title.get_text(strip=True) if soup.title else ""
        if not title: issues.append("Missing title tag")
        elif len(title)>60: issues.append(f"Title too long ({len(title)} chars)")
        else: passed.append("Title length OK")
        if keyword and keyword not in title.lower(): issues.append("Keyword not in title")
        md=soup.find("meta",attrs={"name":"description"}); desc=md["content"] if md and md.get("content") else ""
        if not desc: issues.append("Missing meta description")
        elif len(desc)>160: issues.append("Meta description too long")
        else: passed.append("Meta description OK")
        h1s=soup.find_all("h1")
        if not h1s: issues.append("Missing H1")
        elif len(h1s)>1: issues.append(f"Multiple H1 tags ({len(h1s)})")
        else: passed.append("Single H1 present")
        for t in soup(["script","style","nav","footer","header"]): t.decompose()
        text=re.sub(r"\s+"," ",soup.get_text(" ",strip=True)); words=re.findall(r"\b\w+\b",text)
        if len(words)<300: issues.append(f"Thin content ({len(words)} words)")
        elif len(words)>=1000: passed.append(f"Good content length ({len(words)} words)")
        soup2=BeautifulSoup(html,"html.parser"); images=soup2.find_all("img")
        no_alt=[i for i in images if not i.get("alt")]
        if no_alt: issues.append(f"{len(no_alt)}/{len(images)} images missing alt text")
        elif images: passed.append("All images have alt text")
        canon=soup2.find("link",rel="canonical")
        if not canon: issues.append("Missing canonical tag")
        else: passed.append("Canonical present")
        vp=soup2.find("meta",attrs={"name":"viewport"})
        if not vp: issues.append("Missing viewport meta")
        else: passed.append("Viewport tag present")
        schemas=soup2.find_all("script",type="application/ld+json")
        if not schemas: issues.append("No structured data")
        else: passed.append(f"{len(schemas)} schema(s) found")
        og_title=soup2.find("meta",attrs={"property":"og:title"})
        og_image=soup2.find("meta",attrs={"property":"og:image"})
        if not og_title: issues.append("Missing og:title")
        if not og_image: issues.append("Missing og:image")
        if load_time>3: issues.append(f"Slow response ({load_time}s)")
        elif load_time<1: passed.append(f"Fast response ({load_time}s)")
        score=max(0,100-len(issues)*7)
        return jsonify({"score":score,"grade":"A" if score>=80 else "B" if score>=60 else "C" if score>=40 else "D",
                        "status_code":resp.status_code,"load_time_s":load_time,"page_size_kb":round(len(html.encode("utf-8"))/1024,1),
                        "word_count":len(words),"title":title,"meta_description":desc,"h1_count":len(h1s),
                        "h2_count":len(soup2.find_all("h2")),"images":len(images),"schema_count":len(schemas),
                        "issues":issues,"passed":passed,"issues_count":len(issues),"passed_count":len(passed)})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 14. Schema Extractor
@app.route("/schema", methods=["POST"])
def schema():
    data = request.json; url,err,code = require_url(data)
    if err: return err, code
    try:
        import json as _j
        soup,_ = get_soup(url); schemas=[]
        for script in soup.find_all("script",type="application/ld+json"):
            try:
                d=_j.loads(script.string); items=d if isinstance(d,list) else [d]
                for item in items:
                    if isinstance(item,dict): schemas.append({"type":item.get("@type","unknown"),"data":item})
            except: pass
        microdata=[]
        for el in soup.find_all(attrs={"itemscope":True}):
            item_type=el.get("itemtype","").split("/")[-1]
            props={p.get("itemprop"):(p.get("content") or p.get_text(strip=True))[:80] for p in el.find_all(attrs={"itemprop":True})}
            microdata.append({"type":item_type,"properties":props})
        return jsonify({"json_ld_count":len(schemas),"microdata_count":len(microdata),
                        "schemas":schemas,"microdata":microdata,"has_schema":len(schemas)+len(microdata)>0})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 15. FAQ Schema Generator
@app.route("/faq-schema", methods=["POST"])
def faq_schema():
    data = request.json; url=data.get("url","").strip(); manual_pairs=data.get("pairs",[])
    try:
        import json as _j; pairs=[]
        if url:
            soup,_ = get_soup(url)
            for tag in soup.find_all(re.compile(r"^h[2-6]$")):
                question=tag.get_text(strip=True)
                if not (question.endswith("?") or any(question.lower().startswith(w) for w in ["how","what","why","when","where","who","can","does","is","are"])): continue
                answer_parts=[]
                for sib in tag.next_siblings:
                    if sib.name and re.match(r"^h[1-6]$",sib.name): break
                    if hasattr(sib,"get_text") and sib.name in ("p","div","ul","ol"): answer_parts.append(sib.get_text(strip=True))
                answer=" ".join(answer_parts).strip()
                if answer and len(answer)>20: pairs.append({"question":question,"answer":answer[:1000]})
        for p in manual_pairs:
            if p.get("question") and p.get("answer"): pairs.append(p)
        schema={"@context":"https://schema.org","@type":"FAQPage",
                "mainEntity":[{"@type":"Question","name":p["question"],"acceptedAnswer":{"@type":"Answer","text":p["answer"]}} for p in pairs]}
        return jsonify({"pairs_count":len(pairs),"pairs":pairs,"schema":schema,"json_ld":_j.dumps(schema,indent=2,ensure_ascii=False)})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 16. Structured Data Generator
@app.route("/structured-data", methods=["POST"])
def structured_data():
    data = request.json; stype=data.get("type","article").lower(); url=data.get("url","").strip()
    try:
        import json as _j
        from datetime import datetime
        page={}
        if url:
            soup,_ = get_soup(url)
            page["title"]=soup.title.get_text(strip=True) if soup.title else ""
            h1=soup.find("h1"); page["h1"]=h1.get_text(strip=True) if h1 else page["title"]
            md=soup.find("meta",attrs={"name":"description"}); page["description"]=md["content"] if md and md.get("content") else ""
            og=soup.find("meta",attrs={"property":"og:image"}); page["image"]=og["content"] if og and og.get("content") else ""
        if stype=="article":
            schema={"@context":"https://schema.org","@type":"Article","headline":data.get("name") or page.get("h1",""),
                    "description":data.get("description") or page.get("description",""),"image":page.get("image",""),
                    "author":{"@type":"Person","name":data.get("author","Author")},
                    "publisher":{"@type":"Organization","name":"Publisher"},
                    "datePublished":datetime.now().strftime("%Y-%m-%d"),"dateModified":datetime.now().strftime("%Y-%m-%d"),
                    "mainEntityOfPage":{"@type":"WebPage","@id":url}}
        elif stype=="product":
            schema={"@context":"https://schema.org","@type":"Product","name":data.get("name","Product"),
                    "description":data.get("description",""),
                    "offers":{"@type":"Offer","price":str(data.get("price",0)),"priceCurrency":data.get("currency","USD"),"availability":"https://schema.org/InStock"}}
        elif stype=="local-business":
            schema={"@context":"https://schema.org","@type":"LocalBusiness","name":data.get("name",""),
                    "telephone":data.get("phone",""),"address":{"@type":"PostalAddress","streetAddress":data.get("address","")}}
        else:
            schema={"@context":"https://schema.org","@type":"WebSite","name":page.get("title",""),"url":url}
        return jsonify({"schema":schema,"json_ld":_j.dumps(schema,indent=2,ensure_ascii=False)})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 17. SERP Snippet Previewer
@app.route("/serp-preview", methods=["POST"])
def serp_preview():
    data = request.json; url=data.get("url","").strip()
    try:
        if url:
            soup,resp = get_soup(url)
            title=soup.title.get_text(strip=True) if soup.title else ""
            md=soup.find("meta",attrs={"name":"description"}); desc=md["content"].strip() if md and md.get("content") else ""
            parsed=urlparse(url); path_parts=[p for p in parsed.path.split("/") if p]
            breadcrumb=parsed.netloc+(" › "+" › ".join(path_parts) if path_parts else "")
        else:
            title=data.get("title",""); desc=data.get("description",""); breadcrumb=data.get("breadcrumb","")
        issues=[]
        if len(title)>60: issues.append(f"Title truncated ({len(title)} chars, aim ≤60)")
        if len(title)<30: issues.append(f"Title too short ({len(title)} chars)")
        if not desc: issues.append("No meta description")
        elif len(desc)>155: issues.append(f"Description truncated ({len(desc)} chars)")
        elif len(desc)<70: issues.append(f"Description too short ({len(desc)} chars)")
        return jsonify({"title":title,"title_length":len(title),"title_ok":len(title)<=60,
                        "description":desc,"desc_length":len(desc),"desc_ok":70<=len(desc)<=155,
                        "breadcrumb":breadcrumb,"issues":issues,
                        "title_preview":title[:60]+("..." if len(title)>60 else ""),
                        "desc_preview":desc[:155]+("..." if len(desc)>155 else "")})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 18. Social Preview Validator
@app.route("/social-preview", methods=["POST"])
def social_preview():
    data = request.json; url,err,code = require_url(data)
    if err: return err, code
    try:
        soup,_ = get_soup(url)
        og={m["property"]:m.get("content","") for m in soup.find_all("meta",attrs={"property":re.compile(r"^og:")}) if m.get("property")}
        tc={m["name"]:m.get("content","") for m in soup.find_all("meta",attrs={"name":re.compile(r"^twitter:")}) if m.get("name")}
        issues=[]
        if not og.get("og:title"): issues.append("Missing og:title")
        if not og.get("og:description"): issues.append("Missing og:description")
        if not og.get("og:image"): issues.append("Missing og:image (critical)")
        if not og.get("og:url"): issues.append("Missing og:url")
        if not tc.get("twitter:card"): issues.append("Missing twitter:card")
        score=max(0,100-len(issues)*12)
        return jsonify({"og_title":og.get("og:title",""),"og_description":og.get("og:description",""),
                        "og_image":og.get("og:image",""),"og_type":og.get("og:type",""),
                        "twitter_card":tc.get("twitter:card",""),"twitter_title":tc.get("twitter:title",""),
                        "twitter_image":tc.get("twitter:image",""),"score":score,"issues":issues,"issue_count":len(issues)})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 19. Redirect Chain Checker
@app.route("/redirects", methods=["POST"])
def redirects():
    data = request.json; url,err,code = require_url(data)
    if err: return err, code
    try:
        import requests as req
        chain=[{"url":url,"status":None}]; current=url; seen=set()
        for _ in range(10):
            if current in seen: chain.append({"url":current,"status":"LOOP"}); break
            seen.add(current)
            try:
                r=req.head(current,headers={"User-Agent":"Mozilla/5.0"},allow_redirects=False,timeout=8)
                chain[-1]["status"]=r.status_code
                if r.status_code in (301,302,303,307,308):
                    loc=r.headers.get("Location","")
                    if not loc: break
                    nxt=urljoin(current,loc); chain.append({"url":nxt,"status":None}); current=nxt
                else: break
            except Exception as ex: chain[-1]["status"]=f"ERROR: {str(ex)[:50]}"; break
        hops=len(chain)-1; issues=[]
        if hops>=3: issues.append(f"Long chain ({hops} hops)")
        if any("LOOP" in str(c.get("status","")) for c in chain): issues.append("Redirect loop detected")
        temp=[c for c in chain if c["status"] in (302,307)]
        if temp: issues.append(f"{len(temp)} temporary redirect(s)")
        return jsonify({"original_url":url,"final_url":chain[-1]["url"],"final_status":chain[-1].get("status",""),
                        "hops":hops,"chain":chain,"issues":issues,"has_issues":bool(issues)})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 20. Robots.txt Analyzer
@app.route("/robots", methods=["POST"])
def robots():
    data = request.json; url,err,code = require_url(data)
    if err: return err, code
    test_path=data.get("test_path","")
    try:
        import requests as req
        robots_url=url.rstrip("/")+"/robots.txt"
        r=req.get(robots_url,headers={"User-Agent":"Mozilla/5.0"},timeout=10)
        if r.status_code!=200: return jsonify({"error":f"robots.txt returned {r.status_code}","robots_url":robots_url}), 404
        content=r.text; rules=[]; sitemaps=[]; current_agent="*"; crawl_delay=None
        for line in content.split("\n"):
            line=line.strip()
            if not line or line.startswith("#") or ":" not in line: continue
            key,_,val=line.partition(":"); key=key.strip().lower(); val=val.strip()
            if key=="user-agent": current_agent=val
            elif key=="disallow": rules.append({"agent":current_agent,"type":"disallow","path":val})
            elif key=="allow": rules.append({"agent":current_agent,"type":"allow","path":val})
            elif key=="sitemap": sitemaps.append(val)
            elif key=="crawl-delay":
                try: crawl_delay=float(val)
                except: pass
        issues=[]; warnings=[]
        if any(r["type"]=="disallow" and r["path"]=="/" and r["agent"] in ("*","Googlebot") for r in rules):
            issues.append("CRITICAL: Entire site disallowed")
        if not sitemaps: warnings.append("No sitemap declared")
        if crawl_delay and crawl_delay>10: warnings.append(f"High crawl-delay: {crawl_delay}s")
        test_result=None
        if test_path:
            blocked=any(r["type"]=="disallow" and test_path.startswith(r["path"]) and r["path"] for r in rules if r["agent"] in ("*","Googlebot"))
            test_result="BLOCKED" if blocked else "ALLOWED"
        return jsonify({"robots_url":robots_url,"rules_count":len(rules),"sitemaps":sitemaps,
                        "crawl_delay":crawl_delay,"disallow_rules":[r for r in rules if r["type"]=="disallow" and r["path"]][:20],
                        "issues":issues,"warnings":warnings,"test_result":test_result})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 21. Sitemap Analyzer
@app.route("/sitemap", methods=["POST"])
def sitemap():
    data = request.json; url,err,code = require_url(data)
    if err: return err, code
    try:
        import requests as req
        from bs4 import BeautifulSoup
        from datetime import datetime
        r=req.get(url,headers={"User-Agent":"Mozilla/5.0"},timeout=30); r.raise_for_status()
        soup=BeautifulSoup(r.text,"xml")
        sitemap_refs=soup.find_all("sitemap")
        if sitemap_refs:
            children=[{"loc":s.find("loc").text.strip(),"lastmod":s.find("lastmod").text.strip() if s.find("lastmod") else ""} for s in sitemap_refs]
            return jsonify({"type":"index","children_count":len(children),"children":children[:20]})
        urls_list=[]
        for utag in soup.find_all("url"):
            loc=utag.find("loc"); lm=utag.find("lastmod"); pri=utag.find("priority")
            if loc: urls_list.append({"loc":loc.text.strip(),"lastmod":lm.text.strip() if lm else "","priority":pri.text.strip() if pri else ""})
        total=len(urls_list); dups=total-len(set(u["loc"] for u in urls_list))
        now=datetime.now(); fresh=stale=0
        for u in urls_list:
            if u["lastmod"]:
                try:
                    dt=datetime.fromisoformat(u["lastmod"].replace("Z","").split("+")[0].split("T")[0])
                    days=(now-dt).days
                    if days<=90: fresh+=1
                    elif days>365: stale+=1
                except: pass
        issues=[]
        if total>50000: issues.append(f"Exceeds 50k URL limit ({total})")
        if dups: issues.append(f"{dups} duplicate URLs")
        http_count=sum(1 for u in urls_list if u["loc"].startswith("http://"))
        https_count=sum(1 for u in urls_list if u["loc"].startswith("https://"))
        if http_count and https_count: issues.append("Mixed HTTP/HTTPS")
        return jsonify({"type":"urlset","total_urls":total,"fresh_90d":fresh,"stale_365d":stale,
                        "duplicates":dups,"https_urls":https_count,"http_urls":http_count,
                        "issues":issues,"sample_urls":urls_list[:10]})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 22. Local SEO Auditor
@app.route("/local-seo", methods=["POST"])
def local_seo():
    data = request.json; url,err,code = require_url(data)
    if err: return err, code
    try:
        import json as _j
        soup,resp = get_soup(url); text=soup.get_text(" ",strip=True); html=resp.text
        score=0; issues=[]
        phones=re.findall(r"[\+]?[\d\s\-\(\)]{10,15}",text)
        phones=[p.strip() for p in phones if re.search(r"\d{3}.*\d{3}.*\d{4}",p)]
        if phones: score+=10
        else: issues.append("No phone number detected")
        schemas=soup.find_all("script",type="application/ld+json"); local_schema=False; schema_type=""
        for s in schemas:
            try:
                d=_j.loads(s.string)
                if isinstance(d,dict) and "Business" in d.get("@type",""):
                    local_schema=True; schema_type=d.get("@type",""); score+=20
            except: pass
        if not local_schema: issues.append("No LocalBusiness schema found")
        has_maps=bool(re.search(r"google\.com/maps|maps\.googleapis\.com",html))
        if has_maps: score+=10
        else: issues.append("No Google Maps embed")
        has_hours=bool(re.search(r"(monday|tuesday|wednesday|thursday|friday)\s*[:\-]\s*\d",text.lower()))
        if has_hours: score+=10
        else: issues.append("No opening hours detected")
        social_domains=["facebook.com","instagram.com","twitter.com","linkedin.com","yelp.com"]
        social_found=[sd for sd in social_domains if any(sd in a.get("href","") for a in soup.find_all("a",href=True))]
        if social_found: score+=10
        emails=re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",text)
        if emails: score+=5
        score=min(score,100)
        return jsonify({"score":score,"grade":"A" if score>=70 else "B" if score>=50 else "C" if score>=30 else "D",
                        "phone_numbers":list(set(phones[:3])),"has_local_schema":local_schema,"schema_type":schema_type,
                        "has_google_maps":has_maps,"has_opening_hours":has_hours,
                        "social_profiles":social_found,"emails":list(set(emails[:3])),"issues":issues})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 23. Hreflang Validator
@app.route("/hreflang", methods=["POST"])
def hreflang():
    data = request.json; url,err,code = require_url(data)
    if err: return err, code
    try:
        soup,_ = get_soup(url); tags=[]
        for link in soup.find_all("link",rel="alternate"):
            hl=link.get("hreflang",""); href=link.get("href","")
            if hl and href: tags.append({"lang":hl,"href":href})
        issues=[]
        if not tags: issues.append({"severity":"ERROR","message":"No hreflang tags found"})
        else:
            if not any(t["lang"]=="x-default" for t in tags): issues.append({"severity":"WARNING","message":"Missing x-default tag"})
            self_ref=any(t["href"].rstrip("/")==url.rstrip("/") for t in tags)
            if not self_ref: issues.append({"severity":"ERROR","message":"Missing self-referencing hreflang"})
        return jsonify({"url":url,"hreflang_tags":tags,"tag_count":len(tags),
                        "has_xdefault":any(t["lang"]=="x-default" for t in tags),"issues":issues,"issues_count":len(issues)})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 24. SERP Feature Analyzer
@app.route("/serp-features", methods=["POST"])
def serp_features():
    data = request.json; url,err,code = require_url(data)
    if err: return err, code
    try:
        import json as _j
        soup,_ = get_soup(url); schema_types=[]
        for s in soup.find_all("script",type="application/ld+json"):
            try:
                d=_j.loads(s.string)
                if isinstance(d,dict): schema_types.append(d.get("@type",""))
            except: pass
        paras=[p for p in soup.find_all("p") if len(p.get_text(strip=True))>30]
        h2s=soup.find_all("h2"); question_h2s=[h for h in h2s if any(h.get_text().lower().startswith(w) for w in ["what","how","why","when","who","which"])]
        lists=soup.find_all(["ul","ol"]); tables=soup.find_all("table"); ols=soup.find_all("ol")
        videos=soup.find_all(["video","iframe"])
        results=[]
        fs_score=0
        if paras: fs_score+=20
        if lists: fs_score+=20
        if tables: fs_score+=20
        if question_h2s: fs_score+=20
        results.append({"feature":"Featured Snippet","score":min(fs_score,80),"tips":["Add question-style H2s","Use lists and tables","Add concise answer paragraphs"]})
        faq_score=50 if "FAQPage" in schema_types else (20 if len([s for s in soup.find_all(string=re.compile(r"\?"))])>=3 else 0)
        results.append({"feature":"FAQ Rich Result","score":faq_score,"tips":["Add FAQPage JSON-LD schema"]})
        howto_score=(50 if "HowTo" in schema_types else 0)+(20 if ols else 0)
        results.append({"feature":"How-To Rich Result","score":min(howto_score,80),"tips":["Add HowTo schema with steps","Use ordered lists"]})
        bc_score=60 if "BreadcrumbList" in schema_types else 0
        results.append({"feature":"Breadcrumbs","score":bc_score,"tips":["Add BreadcrumbList schema"]})
        vid_score=(30 if videos else 0)+(40 if "VideoObject" in schema_types else 0)
        results.append({"feature":"Video Result","score":min(vid_score,80),"tips":["Embed a video","Add VideoObject schema"]})
        return jsonify({"url":url,"features":results,"schema_types":schema_types})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 25. Content Repurposer
@app.route("/repurpose", methods=["POST"])
def repurpose():
    data = request.json; url,err,code = require_url(data)
    if err: return err, code
    try:
        soup,_ = get_soup(url)
        title=soup.title.get_text(strip=True) if soup.title else ""
        for t in soup(["script","style","nav","footer"]): t.decompose()
        headings=[(h.name,h.get_text(strip=True)) for h in soup.find_all(re.compile(r"^h[2-3]$"))]
        paras=[p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True))>40]
        pull_quotes=[]
        for para in paras:
            for s in re.split(r"(?<=[.!])\s+",para):
                s=s.strip()
                if 60<=len(s)<=200 and any(w in s.lower() for w in ["important","key","best","always","research","found","shows"]):
                    pull_quotes.append(s)
        pull_quotes=pull_quotes[:5]
        social=[{"platform":"Twitter/X","text":f"🧵 {title}\n\nHere's what you need to know 👇","type":"thread_hook"},
                {"platform":"LinkedIn","text":f"I just published: {title}\n\nKey insight: {paras[0][:200] if paras else ''}...\n\nFull post in comments 👇","type":"linkedin_promo"}]
        for _,text in headings[:4]:
            if len(text)<100: social.append({"platform":"Twitter/X","text":f"💡 {text}","type":"thread_point"})
        email=f"📝 New Post: {title}\n\n{paras[0][:200] if paras else ''}...\n\n[Read the full article →]"
        takeaways=[text for _,text in headings[:7] if len(text)<80]
        return jsonify({"title":title,"pull_quotes":pull_quotes,"social_posts":social[:6],"email_blurb":email,"key_takeaways":takeaways})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 26. Meta Description Generator
@app.route("/meta-generator", methods=["POST"])
def meta_generator():
    data = request.json; url,err,code = require_url(data)
    if err: return err, code
    keyword=data.get("keyword","")
    try:
        soup,_ = get_soup(url)
        title=soup.title.get_text(strip=True) if soup.title else ""
        h1=soup.find("h1"); h1_text=h1.get_text(strip=True) if h1 else title
        for t in soup(["script","style","nav","footer"]): t.decompose()
        paras=[p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True))>30]
        text=" ".join(paras); sentences=re.split(r"(?<=[.!?])\s+",text)
        sentences=[s.strip() for s in sentences if 40<len(s.strip())<200]
        kw_lower=keyword.lower() if keyword else ""; variants=[]
        for s in sentences[:20]:
            if kw_lower and kw_lower in s.lower():
                truncated=s[:155].rsplit(" ",1)[0]+"..." if len(s)>155 else s
                variants.append({"text":truncated,"strategy":"keyword_sentence","has_keyword":True,"length":len(truncated),"length_ok":120<=len(truncated)<=160}); break
        if paras:
            snippet=paras[0][:120].rsplit(" ",1)[0]
            desc=f"{h1_text[:60]}. {snippet}..."
            if len(desc)>160: desc=desc[:157]+"..."
            variants.append({"text":desc,"strategy":"title_plus_intro","has_keyword":kw_lower in desc.lower(),"length":len(desc),"length_ok":120<=len(desc)<=160})
        if keyword and paras:
            tmpl=f"Learn about {keyword}. {paras[0][:80].rsplit(' ',1)[0]}... Read our complete guide."
            if len(tmpl)<=160: variants.append({"text":tmpl,"strategy":"template","has_keyword":True,"length":len(tmpl),"length_ok":120<=len(tmpl)<=160})
        return jsonify({"title":title,"keyword":keyword,"variants":variants[:3]})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 27. Title Tag Optimizer
@app.route("/title-optimizer", methods=["POST"])
def title_optimizer():
    data = request.json; titles=data.get("titles",[]); url=data.get("url","").strip(); keyword=data.get("keyword","")
    if url:
        try: soup,_=get_soup(url); titles.append(soup.title.get_text(strip=True)) if soup.title else None
        except: pass
    if not titles: return jsonify({"error":"titles or url required"}), 400
    POWER_WORDS=set("ultimate best top proven free easy quick guide essential complete definitive".split())
    results=[]
    for title in titles:
        tl=title.lower(); words=re.findall(r"\b[a-z]+\b",tl); score=50; factors=[]
        l=len(title)
        if 50<=l<=60: score+=10; factors.append({"check":"Length ideal","pts":10})
        elif 40<=l<50: score+=5; factors.append({"check":"Length acceptable","pts":5})
        elif l>60: score-=5; factors.append({"check":"Title will be truncated","pts":-5})
        elif l<30: score-=10; factors.append({"check":"Title too short","pts":-10})
        if re.search(r"\d+",title): score+=8; factors.append({"check":"Contains number","pts":8})
        pw=set(words)&POWER_WORDS
        if pw: score+=min(len(pw)*4,12); factors.append({"check":f"Power words: {', '.join(pw)}","pts":min(len(pw)*4,12)})
        if re.search(r"\b20\d{2}\b",title): score+=5; factors.append({"check":"Contains year","pts":5})
        if re.search(r"[\[\(]",title): score+=5; factors.append({"check":"Has brackets","pts":5})
        if keyword:
            kl=keyword.lower()
            if kl in tl:
                pos=tl.index(kl)
                if pos==0: score+=10; factors.append({"check":"Keyword at start","pts":10})
                elif pos<20: score+=5; factors.append({"check":"Keyword near start","pts":5})
                else: score+=2; factors.append({"check":"Keyword present but late","pts":2})
            else: score-=10; factors.append({"check":"Target keyword missing","pts":-10})
        suggestions=[]
        if l>60: suggestions.append("Shorten to <60 chars")
        if not re.search(r"\d+",title): suggestions.append("Add a number (e.g., 'Top 10...')")
        if not pw: suggestions.append("Add power word (best, ultimate, guide)")
        if not re.search(r"\b20\d{2}\b",title): suggestions.append("Add current year")
        results.append({"title":title,"score":min(max(score,0),100),"grade":"A" if score>=80 else "B" if score>=65 else "C" if score>=50 else "D",
                        "length":len(title),"factors":factors,"suggestions":suggestions})
    return jsonify({"results":results})

# 28. Keyword Intent Classifier
@app.route("/keyword-intent", methods=["POST"])
def keyword_intent():
    data = request.json; keywords=data.get("keywords",[])
    if not keywords: return jsonify({"error":"keywords array required"}), 400
    TRANS=r"\b(buy|purchase|order|shop|deal|discount|price|subscribe|download now|hire|book)\b"
    COMM=r"\b(best|top|review|comparison|compare|vs|versus|alternative|recommend|rated)\b"
    NAV=r"\b(login|log in|sign in|official|website|portal|dashboard|account|app)\b"
    INFO=r"\b(how to|what is|what are|why|when|where|who|guide|tutorial|tips|learn|explain|definition)\b"
    results=[]
    for kw in keywords:
        kl=kw.lower(); scores={"transactional":0,"commercial":0,"navigational":0,"informational":0}
        if re.search(TRANS,kl): scores["transactional"]+=2
        if re.search(COMM,kl): scores["commercial"]+=2
        if re.search(NAV,kl): scores["navigational"]+=2
        if re.search(INFO,kl): scores["informational"]+=2
        intent=max(scores,key=scores.get) if max(scores.values())>0 else "commercial"
        conf=round(scores[intent]/max(sum(scores.values()),1),2)
        results.append({"keyword":kw,"intent":intent,"confidence":conf})
    distribution=Counter(r["intent"] for r in results)
    return jsonify({"results":results,"distribution":dict(distribution),"total":len(results)})

# 29. N-gram Analyzer
@app.route("/ngrams", methods=["POST"])
def ngrams():
    data = request.json; url=data.get("url","").strip(); text_input=data.get("text","").strip()
    max_n=data.get("max_n",3); top=data.get("top",20)
    if not url and not text_input: return jsonify({"error":"url or text required"}), 400
    try:
        if url: soup,_=get_soup(url); text=clean_text(soup)
        else: text=text_input
        stops=set("the a an in on at to for of and or but is are was were be been being have has had do does did will would could should may might shall can".split())
        words=re.findall(r"\b[a-z]+\b",text.lower()); results={}
        for n in range(1,min(max_n+1,5)):
            grams=[]
            for i in range(len(words)-n+1):
                gram=tuple(words[i:i+n])
                if n==1 and gram[0] in stops: continue
                if n>1 and all(w in stops for w in gram): continue
                grams.append(" ".join(gram))
            label={1:"unigrams",2:"bigrams",3:"trigrams"}.get(n,f"{n}-grams")
            results[label]=[{"ngram":g,"count":c} for g,c in Counter(grams).most_common(top)]
        return jsonify({"total_words":len(words),"ngrams":results})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 30. Outbound Link Analyzer
@app.route("/outbound-links", methods=["POST"])
def outbound_links():
    data = request.json; url,err,code = require_url(data)
    if err: return err, code
    try:
        soup,_ = get_soup(url); base_domain=urlparse(url).netloc; links=[]
        for a in soup.find_all("a",href=True):
            href=a["href"].strip()
            if not href.startswith("http"): continue
            target_domain=urlparse(href).netloc
            if target_domain==base_domain: continue
            links.append({"target_url":href[:150],"target_domain":target_domain,
                          "anchor_text":a.get_text(strip=True)[:80],"nofollow":"nofollow" in a.get("rel",[]),"sponsored":"sponsored" in a.get("rel",[])})
        domain_counts=Counter(l["target_domain"] for l in links); nofollow_count=sum(1 for l in links if l["nofollow"])
        return jsonify({"total":len(links),"dofollow":len(links)-nofollow_count,"nofollow":nofollow_count,
                        "unique_domains":len(domain_counts),
                        "top_domains":[{"domain":d,"count":c} for d,c in domain_counts.most_common(15)],
                        "links":links[:50]})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 31. Internal Links
@app.route("/internal-links", methods=["POST"])
def internal_links():
    data = request.json; url,err,code = require_url(data)
    if err: return err, code
    try:
        soup,_ = get_soup(url); base_domain=urlparse(url).netloc; internal=[]; external=[]
        for a in soup.find_all("a",href=True):
            href=a["href"].strip(); full=urljoin(url,href); anchor=a.get_text(strip=True)[:80]; nofollow="nofollow" in a.get("rel",[])
            if urlparse(full).netloc==base_domain: internal.append({"target":full.split("#")[0][:150],"anchor":anchor,"nofollow":nofollow})
            else: external.append({"target":full[:150],"anchor":anchor,"nofollow":nofollow})
        anchor_counts=Counter(l["anchor"] for l in internal if l["anchor"])
        top_anchors=[{"anchor":a,"count":c} for a,c in anchor_counts.most_common(15)]
        target_counts=Counter(l["target"] for l in internal)
        top_targets=[{"url":u,"inbound_count":c} for u,c in target_counts.most_common(15)]
        return jsonify({"internal_count":len(internal),"external_count":len(external),"nofollow_count":sum(1 for l in internal if l["nofollow"]),
                        "top_anchor_texts":top_anchors,"top_linked_pages":top_targets,"all_internal":internal[:50],"all_external":external[:30]})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 32. Content Pruning
@app.route("/content-pruning", methods=["POST"])
def content_pruning():
    data = request.json; url,err,code = require_url(data)
    if err: return err, code
    try:
        from datetime import datetime
        soup,resp = get_soup(url)
        for t in soup(["script","style","nav","footer","header"]): t.decompose()
        text=re.sub(r"\s+"," ",soup.get_text(" ",strip=True)); words=re.findall(r"\b\w+\b",text)
        title=soup.title.get_text(strip=True) if soup.title else ""; days_old=None
        for meta_name in ["article:modified_time","article:published_time"]:
            meta=soup.find("meta",attrs={"property":meta_name})
            if meta and meta.get("content"):
                try:
                    dt=datetime.fromisoformat(meta["content"].replace("Z","").split("+")[0].split("T")[0])
                    days_old=(datetime.now()-dt).days; break
                except: pass
        actions=[]; priority="LOW"
        if len(words)<200: actions.append("DELETE or MERGE — extremely thin content"); priority="HIGH"
        elif len(words)<500: actions.append("EXPAND or MERGE — thin content"); priority="MEDIUM"
        if days_old and days_old>730: actions.append("UPDATE — not modified in 2+ years"); priority="MEDIUM" if priority=="LOW" else priority
        if resp.status_code>=400: actions.append(f"FIX — HTTP {resp.status_code}"); priority="HIGH"
        if not actions: actions.append("KEEP — no issues detected")
        return jsonify({"url":url,"title":title,"word_count":len(words),"status_code":resp.status_code,
                        "days_since_update":days_old,"action":"; ".join(actions),"priority":priority})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 33. Page Segmenter
@app.route("/page-segmenter", methods=["POST"])
def page_segmenter():
    data = request.json; url,err,code = require_url(data)
    if err: return err, code
    try:
        import requests as req
        from bs4 import BeautifulSoup
        resp=req.get(url,headers={"User-Agent":"Mozilla/5.0"},timeout=15); html=resp.text
        soup=BeautifulSoup(html,"html.parser")
        bp_classes=re.compile(r"(sidebar|widget|menu|nav|footer|header|ad|banner|comment|social|share)",re.I)
        boilerplate_text=""
        for tag in soup.find_all(["nav","footer","header","aside"]): boilerplate_text+=tag.get_text(" ",strip=True)+" "; tag.decompose()
        for tag in soup.find_all(attrs={"class":bp_classes}): boilerplate_text+=tag.get_text(" ",strip=True)+" "; tag.decompose()
        for tag in soup(["script","style","iframe","noscript"]): tag.decompose()
        main_text=re.sub(r"\s+"," ",soup.get_text(" ",strip=True))
        main_words=len(re.findall(r"\b\w+\b",main_text)); bp_words=len(re.findall(r"\b\w+\b",boilerplate_text))
        total_words=main_words+bp_words; ratio=main_words/max(total_words,1)*100
        article=soup.find("article") or soup.find("main") or soup.find(attrs={"role":"main"})
        return jsonify({"total_words":total_words,"main_content_words":main_words,"boilerplate_words":bp_words,
                        "content_ratio_pct":round(ratio,1),"has_article_tag":article is not None,
                        "main_text_preview":main_text[:300],"status":"GOOD" if ratio>60 else "LOW" if ratio>30 else "VERY LOW"})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 34. Text HTML Ratio
@app.route("/text-html-ratio", methods=["POST"])
def text_html_ratio():
    data = request.json; url,err,code = require_url(data)
    if err: return err, code
    try:
        import requests as req
        from bs4 import BeautifulSoup
        resp=req.get(url,headers={"User-Agent":"Mozilla/5.0"},timeout=15); html=resp.text; raw_size=len(html.encode("utf-8"))
        soup=BeautifulSoup(html,"html.parser"); scripts=soup.find_all("script"); styles=soup.find_all("style")
        ext_scripts=len([s for s in scripts if s.get("src")]); inline_script_size=sum(len(s.string or "") for s in scripts); inline_style_size=sum(len(s.string or "") for s in styles)
        for t in soup(["script","style","nav","footer","header","aside"]): t.decompose()
        text=re.sub(r"\s+"," ",soup.get_text(" ",strip=True)); text_size=len(text.encode("utf-8")); ratio=text_size/max(raw_size,1)*100
        return jsonify({"raw_html_kb":round(raw_size/1024,1),"text_content_kb":round(text_size/1024,1),"text_ratio_pct":round(ratio,1),
                        "inline_script_kb":round(inline_script_size/1024,1),"inline_style_kb":round(inline_style_size/1024,1),
                        "external_scripts":ext_scripts,"word_count":len(re.findall(r"\b\w+\b",text)),
                        "status":"OK" if ratio>=25 else "LOW" if ratio>=10 else "VERY LOW"})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 35. Thin Content Detector
@app.route("/thin-content", methods=["POST"])
def thin_content():
    data = request.json; url,err,code = require_url(data)
    if err: return err, code
    min_words=data.get("min_words",300)
    try:
        soup,resp = get_soup(url)
        for t in soup(["script","style","nav","footer","header"]): t.decompose()
        text=re.sub(r"\s+"," ",soup.get_text(" ",strip=True)); words=re.findall(r"\b\w+\b",text)
        sentences=[s.strip() for s in re.split(r"[.!?]+",text) if len(s.strip())>5]
        paras=[p for p in soup.find_all("p") if len(p.get_text(strip=True))>20]
        text_ratio=len(text)/max(len(resp.text),1)*100; issues=[]
        if len(words)<min_words: issues.append(f"Thin content ({len(words)} words < {min_words})")
        if text_ratio<10: issues.append(f"Low text ratio ({text_ratio:.1f}%)")
        if len(paras)<2: issues.append("Very few paragraphs")
        status="THIN" if issues else "OK"
        return jsonify({"word_count":len(words),"sentence_count":len(sentences),"paragraph_count":len(paras),
                        "text_html_ratio_pct":round(text_ratio,1),"status":status,"issues":issues,"priority":"HIGH" if status=="THIN" else "LOW"})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 36. Question Extractor
@app.route("/questions", methods=["POST"])
def questions():
    data = request.json; url=data.get("url","").strip(); keyword=data.get("keyword","")
    if not url: return jsonify({"error":"url required"}), 400
    try:
        soup,_ = get_soup(url)
        for t in soup(["script","style"]): t.decompose()
        text=re.sub(r"\s+"," ",soup.get_text(" ",strip=True))
        explicit=[s.strip() for s in re.split(r"(?<=[.!?])\s+",text) if s.strip().endswith("?") and len(s.strip())>10]
        heading_qs=[]
        for tag in soup.find_all(re.compile(r"^h[1-6]$")):
            t2=tag.get_text(strip=True)
            if "?" in t2 or any(t2.lower().startswith(w) for w in ["how","what","why","when","where","who","can","does","is","are"]):
                heading_qs.append({"text":t2,"source":tag.name.upper()})
        generated=[]
        if keyword:
            for tmpl in [f"What is {keyword}?",f"How does {keyword} work?",f"Why is {keyword} important?",f"What are the benefits of {keyword}?",
                         f"How to choose {keyword}?",f"What is the best {keyword}?",f"Is {keyword} worth it?",f"How much does {keyword} cost?"]:
                generated.append(tmpl)
        return jsonify({"explicit_questions":explicit[:15],"heading_questions":heading_qs,"generated_questions":generated,"total_found":len(explicit)+len(heading_qs)})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 37. Sentiment Analyzer
@app.route("/sentiment", methods=["POST"])
def sentiment():
    data = request.json; url=data.get("url","").strip(); text_input=data.get("text","").strip()
    if not url and not text_input: return jsonify({"error":"url or text required"}), 400
    try:
        import nltk; nltk.download("vader_lexicon",quiet=True)
        from nltk.sentiment.vader import SentimentIntensityAnalyzer
        sia=SentimentIntensityAnalyzer()
        if url:
            soup,_ = get_soup(url)
            for t in soup(["script","style","nav","footer"]): t.decompose()
            title=soup.title.get_text(strip=True) if soup.title else ""; paras=[p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True))>30]; text=" ".join(paras)
        else: title=""; paras=[]; text=text_input
        def label(c): return "POSITIVE" if c>=0.05 else "NEGATIVE" if c<=-0.05 else "NEUTRAL"
        overall=sia.polarity_scores(text[:5000])
        para_data=[{"text":p[:100],"sentiment":label(sia.polarity_scores(p)["compound"]),"compound":round(sia.polarity_scores(p)["compound"],3)} for p in paras[:20]]
        pos_count=sum(1 for p in para_data if p["sentiment"]=="POSITIVE"); neg_count=sum(1 for p in para_data if p["sentiment"]=="NEGATIVE")
        return jsonify({"overall":{"sentiment":label(overall["compound"]),"compound":round(overall["compound"],3),"pos":overall["pos"],"neg":overall["neg"],"neu":overall["neu"]},
                        "title_sentiment":label(sia.polarity_scores(title)["compound"]) if title else None,
                        "paragraph_distribution":{"positive":pos_count,"negative":neg_count,"neutral":len(para_data)-pos_count-neg_count},"paragraphs":para_data})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 38. Content Calendar Generator
@app.route("/content-calendar", methods=["POST"])
def content_calendar():
    data = request.json; keywords=data.get("keywords",[]); weeks=data.get("weeks",4); posts_per_week=data.get("posts_per_week",3)
    if not keywords: return jsonify({"error":"keywords array required"}), 400
    from datetime import datetime, timedelta
    TYPES={"informational":["Ultimate Guide","How-To Tutorial","Explainer Post","Listicle"],
           "commercial":["Comparison Post","Best-Of Roundup","Product Review","Buyer's Guide"],
           "transactional":["Landing Page","Pricing Guide","Free Tool Page"]}
    def classify(kw):
        kl=kw.lower()
        if re.search(r"\b(buy|price|deal|shop)\b",kl): return "transactional"
        if re.search(r"\b(best|top|review|vs|compare)\b",kl): return "commercial"
        return "informational"
    today=datetime.now(); start=today+timedelta(days=(7-today.weekday()))
    calendar=[]; kw_index=0
    for week in range(1,weeks+1):
        for post in range(posts_per_week):
            if kw_index>=len(keywords): kw_index=0
            kw=keywords[kw_index]; intent=classify(kw); ctypes=TYPES.get(intent,TYPES["informational"]); ctype=ctypes[kw_index%len(ctypes)]
            offsets=[0,2,4] if posts_per_week==3 else list(range(posts_per_week))
            pub=start+timedelta(weeks=week-1,days=offsets[post%len(offsets)])
            wc=len(kw.split()); priority="high" if wc>=4 else "medium" if wc>=2 else "low"
            calendar.append({"week":week,"publish_date":pub.strftime("%Y-%m-%d"),"day":pub.strftime("%A"),"keyword":kw,"intent":intent,"content_type":ctype,"priority":priority,
                             "suggested_title":f"The Ultimate Guide to {kw.title()}" if ctype=="Ultimate Guide" else f"Best {kw.title()} in 2025","target_word_count":2000 if "Guide" in ctype else 1200})
            kw_index+=1
    return jsonify({"weeks":weeks,"posts_per_week":posts_per_week,"total_posts":len(calendar),"calendar":calendar})

# 39. TF-IDF Extractor
@app.route("/tfidf", methods=["POST"])
def tfidf():
    data = request.json; url=data.get("url","").strip(); text_input=data.get("text","").strip(); top=data.get("top",30)
    if not url and not text_input: return jsonify({"error":"url or text required"}), 400
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        if url: soup,_=get_soup(url); text=clean_text(soup)
        else: text=text_input
        paras=re.split(r"\n{2,}|(?<=[.!?])\s{2,}",text); paras=[p.strip() for p in paras if len(p.strip())>20]
        if not paras: paras=[text]
        vec=TfidfVectorizer(ngram_range=(1,3),stop_words="english",max_features=500)
        matrix=vec.fit_transform(paras); features=vec.get_feature_names_out(); avg=matrix.mean(axis=0).A1
        term_scores=sorted(zip(features,avg),key=lambda x:-x[1])[:top]
        return jsonify({"total_words":len(re.findall(r"\b\w+\b",text)),"terms":[{"term":t,"score":round(float(s),5)} for t,s in term_scores]})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 40. Content Similarity
@app.route("/content-similarity", methods=["POST"])
def content_similarity():
    data = request.json; urls=data.get("urls",[]); threshold=data.get("threshold",0.7)
    if len(urls)<2: return jsonify({"error":"At least 2 URLs required"}), 400
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity as cos_sim
        texts=[]
        for u in urls[:5]:
            try: soup,_=get_soup(u); texts.append(clean_text(soup))
            except: pass
        if len(texts)<2: return jsonify({"error":"Could not fetch enough pages"}), 500
        vec=TfidfVectorizer(stop_words="english",max_features=2000); matrix=vec.fit_transform(texts); sim=cos_sim(matrix)
        pairs=[]
        for i in range(len(urls)):
            for j in range(i+1,len(urls)):
                score=round(float(sim[i][j]),3)
                pairs.append({"page_a":urls[i],"page_b":urls[j],"similarity":score,"severity":"HIGH" if score>=0.7 else "MEDIUM" if score>=0.5 else "LOW","is_duplicate":score>=threshold})
        pairs.sort(key=lambda x:-x["similarity"])
        return jsonify({"urls_analyzed":len(texts),"threshold":threshold,"pairs":pairs,"duplicate_pairs":len([p for p in pairs if p["is_duplicate"]])})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 41. Keyword Difficulty
@app.route("/keyword-difficulty", methods=["POST"])
def keyword_difficulty():
    data = request.json; keyword=data.get("keyword","").strip(); urls=data.get("urls",[])
    if not keyword: return jsonify({"error":"keyword required"}), 400
    if not urls: return jsonify({"error":"urls (competitor pages) required"}), 400
    try:
        import numpy as np
        competitors=[]
        for u in urls[:5]:
            try:
                soup,_ = get_soup(u)
                for t in soup(["script","style"]): t.decompose()
                text=re.sub(r"\s+"," ",soup.get_text(" ",strip=True)); words=re.findall(r"\b\w+\b",text)
                competitors.append({"url":u[:60],"word_count":len(words),"h2_count":len(soup.find_all("h2")),"images":len(soup.find_all("img")),"schemas":len(soup.find_all("script",type="application/ld+json"))})
            except: pass
        if not competitors: return jsonify({"error":"Could not analyze competitor URLs"}), 500
        avg_words=int(np.mean([c["word_count"] for c in competitors])); avg_h2=float(np.mean([c["h2_count"] for c in competitors]))
        avg_images=float(np.mean([c["images"] for c in competitors])); schema_pct=np.mean([1 if c["schemas"]>0 else 0 for c in competitors])*100
        score=20
        if avg_words>3000: score+=20
        elif avg_words>1500: score+=10
        elif avg_words>800: score+=5
        if avg_h2>10: score+=10
        elif avg_h2>5: score+=5
        if avg_images>10: score+=10
        elif avg_images>5: score+=5
        if schema_pct>60: score+=10
        elif schema_pct>30: score+=5
        kw=keyword.lower()
        if len(kw.split())>=5: score-=10
        elif len(kw.split())<=2: score+=10
        if re.search(r"\b(best|top|review)\b",kw): score+=5
        score=min(max(score,5),95)
        label="Very Easy" if score<20 else "Easy" if score<35 else "Medium" if score<55 else "Hard" if score<75 else "Very Hard"
        return jsonify({"keyword":keyword,"difficulty_score":score,"difficulty_label":label,
                        "competitor_benchmarks":{"avg_words":avg_words,"avg_h2":round(avg_h2,1),"avg_images":round(avg_images,1),"schema_pct":round(schema_pct,1)},
                        "required_to_compete":{"word_count":int(avg_words*1.2),"h2_count":int(avg_h2+2),"images":int(avg_images)},"competitors":competitors})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 42. Sentence Complexity
@app.route("/sentence-complexity", methods=["POST"])
def sentence_complexity():
    data = request.json; url=data.get("url","").strip(); text_input=data.get("text","").strip(); threshold=data.get("threshold",30)
    if not url and not text_input: return jsonify({"error":"url or text required"}), 400
    try:
        if url: soup,_=get_soup(url); text=clean_text(soup)
        else: text=text_input
        def count_syl(w):
            w=w.lower()
            if len(w)<=2: return 1
            c=len(re.findall(r"[aeiouy]+",w))
            if w.endswith("e"): c-=1
            return max(c,1)
        PASSIVE=re.compile(r"\b(is|are|was|were|been|being|be)\b\s+\w+ed\b",re.I)
        sentences=[s.strip() for s in re.split(r"(?<=[.!?])\s+",text) if len(s.strip())>10]; results=[]
        for sent in sentences[:100]:
            words=re.findall(r"\b[a-zA-Z]+\b",sent)
            if not words: continue
            wc=len(words); syls=[count_syl(w) for w in words]; complex_w=sum(1 for s in syls if s>=3); is_passive=bool(PASSIVE.search(sent))
            score=0; issues=[]
            if wc>25: score+=25; issues.append(f"long ({wc} words)")
            if complex_w/max(wc,1)>0.3: score+=20; issues.append(f"{complex_w} complex words")
            if is_passive: score+=10; issues.append("passive voice")
            results.append({"sentence":sent[:120],"word_count":wc,"complex_words":complex_w,"is_passive":is_passive,"complexity_score":min(score,100),"issues":"; ".join(issues) if issues else "OK"})
        flagged=[r for r in results if r["complexity_score"]>=threshold]; passive_count=sum(1 for r in results if r["is_passive"])
        return jsonify({"total_sentences":len(results),"flagged_count":len(flagged),"passive_count":passive_count,
                        "avg_length":round(sum(r["word_count"] for r in results)/max(len(results),1),1),"most_complex":sorted(flagged,key=lambda x:-x["complexity_score"])[:10]})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 43. Topic Authority
@app.route("/topic-authority", methods=["POST"])
def topic_authority():
    data = request.json; urls=data.get("urls",[]); topic=data.get("topic","").strip()
    if not urls or not topic: return jsonify({"error":"urls and topic required"}), 400
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        pages=[]
        for u in urls[:10]:
            try:
                soup,_ = get_soup(u); text=clean_text(soup); headings=[h.get_text(strip=True) for h in soup.find_all(re.compile(r"^h[1-6]$"))]
                pages.append({"text":text,"headings":headings,"word_count":len(re.findall(r"\b\w+\b",text)),"url":u})
            except: pass
        if not pages: return jsonify({"error":"Could not fetch any pages"}), 500
        total_words=sum(p["word_count"] for p in pages); topic_lower=topic.lower()
        topic_mentions=sum(p["text"].lower().count(topic_lower) for p in pages)
        heading_mentions=sum(1 for p in pages for h in p["headings"] if topic_lower in h.lower())
        coverage_score=min(25,len(pages)*2.5+total_words/2000); relevance_score=min(25,topic_mentions*0.5+heading_mentions*3)
        total=round(coverage_score+relevance_score+15+15,1)
        return jsonify({"topic":topic,"pages_analyzed":len(pages),"total_words":total_words,"topic_mentions":topic_mentions,"heading_mentions":heading_mentions,
                        "score_coverage":round(coverage_score,1),"score_relevance":round(relevance_score,1),"total_score":min(total,100),
                        "grade":"A" if total>=80 else "B" if total>=60 else "C" if total>=40 else "D"})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 44. Backlink Profiler
@app.route("/backlink-profiler", methods=["POST"])
def backlink_profiler():
    data = request.json; rows=data.get("rows",[]); keyword=data.get("keyword","").lower(); brand=data.get("brand","").lower()
    if not rows: return jsonify({"error":"rows array required"}), 400
    def classify(text):
        t=text.strip().lower()
        if not t: return "empty"
        if re.match(r"^https?://",t): return "naked_url"
        if t in ("click here","here","this","link","read more","visit","website"): return "generic"
        if brand and brand in t: return "branded"
        if keyword and keyword==t: return "exact_match"
        if keyword and keyword in t: return "partial_match"
        return "other"
    anchors=[{"anchor":r.get("anchor","")[:100],"type":classify(r.get("anchor",""))} for r in rows]
    type_counts=Counter(a["type"] for a in anchors); total=len(anchors); issues=[]
    exact_pct=type_counts.get("exact_match",0)/total*100
    if exact_pct>30: issues.append(f"HIGH RISK: {exact_pct:.1f}% exact match anchors")
    elif exact_pct>10: issues.append(f"WARNING: {exact_pct:.1f}% exact match anchors")
    top_anchors=Counter(a["anchor"] for a in anchors if a["anchor"]).most_common(15)
    return jsonify({"total":total,"type_distribution":dict(type_counts),"percentages":{k:round(v/total*100,1) for k,v in type_counts.items()},
                    "top_anchors":[{"anchor":a,"count":c} for a,c in top_anchors],"issues":issues,"health":"GOOD" if not issues else "NEEDS REVIEW"})

# 45. Toxic Backlink Detector
@app.route("/toxic-backlinks", methods=["POST"])
def toxic_backlinks():
    data = request.json; rows=data.get("rows",[])
    if not rows: return jsonify({"error":"rows array required"}), 400
    RISKY_TLDS={".xyz",".tk",".pw",".top",".gq",".ml",".cf",".ga",".buzz",".icu",".monster"}
    SPAM_ANCHORS=re.compile(r"(viagra|casino|poker|payday|loan|pills|cheap|xxx|porn|gambling|forex)",re.I)
    LINK_FARM=re.compile(r"(blog\d{3,}|free-?links|link-?directory|article-?directory|web-?directory)",re.I)
    results=[]
    for row in rows:
        domain=str(row.get("domain","")).lower(); anchor=str(row.get("anchor","")); risk_score=0; flags=[]
        for tld in RISKY_TLDS:
            if domain.endswith(tld): risk_score+=25; flags.append(f"Risky TLD: {tld}"); break
        if SPAM_ANCHORS.search(anchor): risk_score+=30; flags.append("Spam anchor text")
        if LINK_FARM.search(domain): risk_score+=25; flags.append("Link farm domain")
        if domain.count(".")>=4: risk_score+=15; flags.append("Deep subdomain chain")
        if re.match(r"^\d+\.\d+",domain): risk_score+=20; flags.append("IP-based domain")
        results.append({"domain":domain[:60],"anchor":anchor[:80],"risk_score":min(risk_score,100),
                        "risk_level":"HIGH" if risk_score>=40 else "MEDIUM" if risk_score>=20 else "LOW","flags":"; ".join(flags) if flags else "Clean"})
    high=sum(1 for r in results if r["risk_level"]=="HIGH"); med=sum(1 for r in results if r["risk_level"]=="MEDIUM")
    return jsonify({"total":len(results),"high_risk":high,"medium_risk":med,"low_risk":len(results)-high-med,
                    "top_toxic":sorted([r for r in results if r["risk_level"]=="HIGH"],key=lambda x:-x["risk_score"])[:15],"results":results})

# 46. Keyword Gap Analyzer
@app.route("/keyword-gap", methods=["POST"])
def keyword_gap():
    data = request.json; my_urls=data.get("my_urls",[]); comp_urls=data.get("competitor_urls",[])
    if not my_urls or not comp_urls: return jsonify({"error":"my_urls and competitor_urls required"}), 400
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        my_texts=[]; comp_texts=[]
        for u in my_urls[:3]:
            try: soup,_=get_soup(u); my_texts.append(clean_text(soup))
            except: pass
        for u in comp_urls[:3]:
            try: soup,_=get_soup(u); comp_texts.append(clean_text(soup))
            except: pass
        if not my_texts or not comp_texts: return jsonify({"error":"Could not fetch pages"}), 500
        all_texts=my_texts+comp_texts
        vec=TfidfVectorizer(ngram_range=(1,3),stop_words="english",max_features=2000,min_df=1)
        matrix=vec.fit_transform(all_texts); features=vec.get_feature_names_out()
        my_avg=matrix[:len(my_texts)].mean(axis=0).A1; comp_avg=matrix[len(my_texts):].mean(axis=0).A1
        gaps=[{"term":features[i],"your_tfidf":round(my_avg[i],5),"competitor_tfidf":round(comp_avg[i],5),"gap_score":round(comp_avg[i]-my_avg[i],5),"priority":"HIGH" if comp_avg[i]>0.05 and my_avg[i]<0.01 else "MEDIUM"}
              for i in range(len(features)) if comp_avg[i]>0.02 and my_avg[i]<comp_avg[i]*0.3]
        strengths=[{"term":features[i],"your_tfidf":round(my_avg[i],5),"competitor_tfidf":round(comp_avg[i],5)}
                   for i in range(len(features)) if my_avg[i]>0.02 and comp_avg[i]<my_avg[i]*0.3]
        gaps.sort(key=lambda x:-x["gap_score"]); strengths.sort(key=lambda x:-x["your_tfidf"])
        return jsonify({"gaps_count":len(gaps),"strengths_count":len(strengths),"top_gaps":gaps[:25],"top_strengths":strengths[:15]})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 47. Keyword Cannibalization
@app.route("/cannibalization", methods=["POST"])
def cannibalization():
    data = request.json; urls=data.get("urls",[]); threshold=data.get("threshold",0.5)
    if len(urls)<2: return jsonify({"error":"At least 2 URLs required"}), 400
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity as cos_sim
        import numpy as np
        pages=[]
        for u in urls[:8]:
            try:
                soup,_ = get_soup(u); title=soup.title.get_text(strip=True) if soup.title else ""; text=clean_text(soup)
                pages.append({"url":u,"title":title,"text":text})
            except: pass
        if len(pages)<2: return jsonify({"error":"Could not fetch enough pages"}), 500
        vec=TfidfVectorizer(ngram_range=(1,2),stop_words="english",max_features=1000)
        matrix=vec.fit_transform([p["text"] for p in pages]); sim=cos_sim(matrix); features=vec.get_feature_names_out()
        conflicts=[]
        for i in range(len(pages)):
            for j in range(i+1,len(pages)):
                if sim[i][j]>=threshold:
                    ri=matrix[i].toarray().flatten(); rj=matrix[j].toarray().flatten()
                    overlap_idx=np.where((ri>0.05)&(rj>0.05))[0]
                    shared=[features[k] for k in sorted(overlap_idx,key=lambda k:-(ri[k]+rj[k]))[:5]]
                    conflicts.append({"page_a":pages[i]["url"],"title_a":pages[i]["title"][:50],"page_b":pages[j]["url"],"title_b":pages[j]["title"][:50],
                                      "similarity":round(float(sim[i][j]),3),"shared_terms":", ".join(shared),"severity":"HIGH" if sim[i][j]>=0.7 else "MEDIUM"})
        conflicts.sort(key=lambda x:-x["similarity"])
        return jsonify({"pages_analyzed":len(pages),"threshold":threshold,"conflicts_found":len(conflicts),"conflicts":conflicts})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 48. Topic Modeler
@app.route("/topic-model", methods=["POST"])
def topic_model():
    data = request.json; urls=data.get("urls",[]); num_topics=data.get("num_topics",5)
    if len(urls)<2: return jsonify({"error":"At least 2 URLs required"}), 400
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.decomposition import NMF
        import numpy as np
        texts=[]; labels=[]
        for u in urls[:10]:
            try: soup,_=get_soup(u); texts.append(clean_text(soup)); labels.append(u[:50])
            except: pass
        if len(texts)<2: return jsonify({"error":"Could not fetch enough pages"}), 500
        vec=TfidfVectorizer(ngram_range=(1,2),stop_words="english",max_features=1000,min_df=1)
        matrix=vec.fit_transform(texts); features=vec.get_feature_names_out()
        n_topics=min(num_topics,len(texts),len(features))
        nmf=NMF(n_components=n_topics,random_state=42,max_iter=200); doc_topics=nmf.fit_transform(matrix)
        topics=[{"topic_id":idx,"label":[features[i] for i in topic.argsort()[-8:][::-1]][0],"top_terms":[features[i] for i in topic.argsort()[-8:][::-1]]} for idx,topic in enumerate(nmf.components_)]
        assignments=[{"document":labels[i],"dominant_topic":int(np.argmax(doc_topics[i])),"topic_label":topics[int(np.argmax(doc_topics[i]))]["label"],"confidence":round(float(doc_topics[i][int(np.argmax(doc_topics[i]))]),3)} for i in range(len(labels))]
        return jsonify({"num_topics":n_topics,"topics":topics,"assignments":assignments})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 49. Search Console Analyzer
@app.route("/search-console", methods=["POST"])
def search_console():
    data = request.json; rows=data.get("rows",[]); min_impressions=data.get("min_impressions",50)
    if not rows: return jsonify({"error":"rows array required (each with query,clicks,impressions,position)"}), 400
    try:
        quick_wins=[r for r in rows if r.get("impressions",0)>=min_impressions and 4<=r.get("position",99)<=20]
        quick_wins.sort(key=lambda x:-x.get("impressions",0))
        striking=[r for r in rows if r.get("impressions",0)>=min_impressions//2 and 11<=r.get("position",99)<=20]
        striking.sort(key=lambda x:-x.get("impressions",0))
        low_ctr=[r for r in rows if r.get("impressions",0)>=min_impressions and r.get("position",99)<=5 and r.get("ctr",1)<0.05]
        low_ctr.sort(key=lambda x:-x.get("impressions",0))
        total_clicks=sum(r.get("clicks",0) for r in rows); total_impr=sum(r.get("impressions",0) for r in rows)
        avg_pos=sum(r.get("position",0) for r in rows)/max(len(rows),1)
        return jsonify({"total_queries":len(rows),"total_clicks":total_clicks,"total_impressions":total_impr,"avg_position":round(avg_pos,1),
                        "quick_wins":quick_wins[:10],"striking_distance":striking[:10],"low_ctr":low_ctr[:10]})
    except Exception as e: return jsonify({"error":str(e)}), 500

# 50. Log File Analyzer
@app.route("/log-analyzer", methods=["POST"])
def log_analyzer():
    data = request.json; log_content=data.get("log_content","")
    if not log_content: return jsonify({"error":"log_content required (paste access log lines)"}), 400
    try:
        import re as _re
        BOT_PATTERNS={"Googlebot":r"Googlebot|GoogleOther","Bingbot":r"bingbot","Yandex":r"YandexBot","Baidu":r"Baiduspider","Semrush":r"SemrushBot","Ahrefs":r"AhrefsBot"}
        LOG_PATTERN=_re.compile(r'(?P<ip>[\d.]+)\s+\S+\s+\S+\s+\[(?P<date>[^\]]+)\]\s+"(?P<method>\w+)\s+(?P<path>\S+)\s+\S+"\s+(?P<status>\d+)\s+(?P<size>\d+|-)\s*"(?P<referrer>[^"]*)"\s*"(?P<agent>[^"]*)"')
        entries=[]; lines=log_content.strip().split("\n")
        for line in lines[:5000]:
            m=LOG_PATTERN.match(line.strip())
            if m:
                d=m.groupdict(); d["status"]=int(d["status"]); d["size"]=int(d["size"]) if d["size"]!="-" else 0
                bot="Human"
                for name,pattern in BOT_PATTERNS.items():
                    if _re.search(pattern,d["agent"],_re.I): bot=name; break
                d["bot"]=bot; entries.append(d)
        if not entries: return jsonify({"error":"No valid log entries found. Use Combined Log Format."}), 400
        bot_counts=Counter(e["bot"] for e in entries); status_counts=Counter(e["status"] for e in entries)
        bot_entries=[e for e in entries if e["bot"]!="Human"]
        bot_paths=Counter(e["path"] for e in bot_entries).most_common(20)
        waste=[e for e in bot_entries if e["status"] in (301,302,404,410,500)]
        waste_paths=Counter(e["path"] for e in waste).most_common(10)
        return jsonify({"total_requests":len(entries),"bot_distribution":dict(bot_counts),"status_distribution":dict(status_counts),
                        "bot_crawled_paths":[{"path":p,"count":c} for p,c in bot_paths],"crawl_waste":{"total":len(waste),"top_waste_paths":[{"path":p,"count":c} for p,c in waste_paths]}})
    except Exception as e: return jsonify({"error":str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)
