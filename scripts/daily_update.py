import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
import os

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

RSS_FEEDS = [
    {"url": "https://techcrunch.com/category/artificial-intelligence/feed/", "source": "TechCrunch"},
    {"url": "https://venturebeat.com/category/ai/feed/", "source": "VentureBeat"},
    {"url": "https://www.marketingaiinstitute.com/blog/rss.xml", "source": "Marketing AI Institute"},
    {"url": "https://searchengineland.com/feed", "source": "Search Engine Land"},
    {"url": "https://www.searchenginejournal.com/feed/", "source": "Search Engine Journal"},
    {"url": "https://martech.org/feed/", "source": "MarTech"},
    {"url": "https://blog.hubspot.com/marketing/rss.xml", "source": "HubSpot"},
    {"url": "https://news.crunchbase.com/feed/", "source": "Crunchbase News"},
    {"url": "https://techcrunch.com/category/venture/feed/", "source": "TechCrunch VC"},
    {"url": "https://www.adexchanger.com/feed/", "source": "AdExchanger"},
    {"url": "https://www.marketingdive.com/feeds/news/", "source": "Marketing Dive"},
    {"url": "https://www.socialmediaexaminer.com/feed/", "source": "Social Media Examiner"},
]

# How many articles each homepage section needs, and the category label to
# fall back on if Claude's selection doesn't supply one.
SLOT_SPECS = {
    "featured_main": {"count": 1, "default_category": "AI Strategy"},
    "featured_side": {"count": 2, "default_category": "Leadership"},
    "seo": {"count": 6, "default_category": "AI & SEO"},
    "martech": {"count": 4, "default_category": "MarTech"},
    "leadership": {"count": 3, "default_category": "Leadership"},
    "strategy": {"count": 3, "default_category": "AI Strategy"},
    "research": {"count": 5, "default_category": "Research"},
}

CATEGORY_CSS = {
    "AI Strategy": "strategy",
    "MarTech": "martech",
    "AI & SEO": "seo",
    "Leadership": "leadership",
    "Research": "research",
    "Product Launch": "product",
}

STRATEGY_EMOJIS = ["&#x1F4DD;", "&#x1F916;", "&#x1F4B0;"]
STRATEGY_GRADIENTS = [
    "135deg, #533483 0%, #e94560 100%",
    "135deg, #16213e 0%, #533483 100%",
    "135deg, #0f3460 0%, #16813e 100%",
]

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "for", "with", "that", "this",
    "from", "are", "is", "to", "of", "in", "on", "at", "as", "by", "its",
    "it's", "how", "why", "what", "your", "you", "new",
}


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def fetch_rss_feed(feed_url, source_name):
    """Fetch and parse a single RSS feed, return list of articles."""
    articles = []
    try:
        req = urllib.request.Request(feed_url, headers={"User-Agent": "TechMarketingDose/1.0"})
        with urllib.request.urlopen(req, timeout=15) as response:
            xml_data = response.read()
        root = ET.fromstring(xml_data)

        namespaces = {"atom": "http://www.w3.org/2005/Atom"}

        # RSS format
        for item in root.findall(".//item"):
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            description = item.findtext("description", "").strip()
            pub_date = item.findtext("pubDate", "").strip()
            if title:
                clean_desc = re.sub(r"<[^>]+>", "", description)[:300]
                articles.append({
                    "title": title,
                    "link": link,
                    "description": clean_desc,
                    "source": source_name,
                    "pub_date": pub_date
                })

        # Atom format
        for entry in root.findall("atom:entry", namespaces):
            title = entry.findtext("atom:title", "", namespaces).strip()
            link_el = entry.find("atom:link", namespaces)
            link = link_el.get("href", "") if link_el is not None else ""
            summary = entry.findtext("atom:summary", "", namespaces).strip()
            published = entry.findtext("atom:published", "", namespaces).strip()
            if title:
                clean_summary = re.sub(r"<[^>]+>", "", summary)[:300]
                articles.append({
                    "title": title,
                    "link": link,
                    "description": clean_summary,
                    "source": source_name,
                    "pub_date": published
                })

    except Exception as e:
        print(f"  Warning: Could not fetch {source_name}: {e}")

    return articles


def fetch_all_feeds():
    """Fetch all RSS feeds and return combined article list."""
    all_articles = []
    for feed in RSS_FEEDS:
        print(f"  Fetching {feed['source']}...")
        articles = fetch_rss_feed(feed["url"], feed["source"])
        all_articles.extend(articles[:8])
    print(f"  Total articles fetched: {len(all_articles)}")
    return all_articles


def call_claude(prompt, max_tokens=4000):
    """Call the Claude API and return the response text."""
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01"
    }
    body = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}]
    }).encode("utf-8")

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=60) as response:
        result = json.loads(response.read())

    return result["content"][0]["text"]


def _extract_json_object(text):
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return {}
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {}


def normalize_category(raw, default):
    if not raw:
        return default
    raw_lower = raw.strip().lower()
    for canon in CATEGORY_CSS:
        if canon.lower() == raw_lower:
            return canon
    for canon in CATEGORY_CSS:
        if raw_lower in canon.lower() or canon.lower() in raw_lower:
            return canon
    return default


def select_and_categorize(articles):
    """Ask Claude to pick and categorize articles for every homepage section."""
    pool = articles[:70]
    articles_text = ""
    for i, a in enumerate(pool):
        articles_text += f"{i + 1}. [{a['source']}] {a['title']}\n   {a['description'][:150]}\n\n"

    prompt = f"""You are a news editor for Tech Marketing Dose, a site for tech marketers interested in AI.

Below are {len(pool)} recent articles. You need to fill every section of today's homepage. Assign each selected article to exactly ONE section below, and never reuse the same article number in more than one section.

Sections (name: how many articles needed: category guidance):
- featured_main: 1 article : the single most important story of the day overall. Category must be one of: AI Strategy, MarTech, AI & SEO, Leadership, Research, Product Launch.
- featured_side: 2 articles : the next two most important stories overall. Same category options.
- seo: 6 articles : AI search, AI Overviews, answer engine optimization, or SEO. Category should usually be "AI & SEO".
- martech: 4 articles : marketing technology product news, platform updates, vendor announcements. Category should usually be "MarTech" or "Product Launch".
- leadership: 3 articles : CMO hires, marketing leadership moves, org changes. Category should be "Leadership".
- strategy: 3 articles : AI strategy guidance, playbooks, how-to frameworks for marketers. Category should be "AI Strategy".
- research: 5 articles : research reports, survey data, studies, statistics about AI and marketing. Category should be "Research".

If there are not enough perfectly-on-topic articles for a section, still fill it with the closest fit available rather than leaving it short.

Articles:
{articles_text}

Return ONLY a JSON object with this exact shape (1-indexed article numbers, no duplicates anywhere in the object):
{{"featured_main": [{{"index": 1, "category": "AI Strategy"}}], "featured_side": [{{"index": 2, "category": "Leadership"}}, {{"index": 3, "category": "MarTech"}}], "seo": [ ... 6 items ... ], "martech": [ ... 4 items ... ], "leadership": [ ... 3 items ... ], "strategy": [ ... 3 items ... ], "research": [ ... 5 items ... ]}}

Return ONLY the JSON object, nothing else."""

    response = call_claude(prompt, max_tokens=1800)
    data = _extract_json_object(response)

    result = {}
    used_indices = set()
    for slot, spec in SLOT_SPECS.items():
        items = []
        for entry in (data.get(slot) or [])[:spec["count"]]:
            idx = entry.get("index")
            if not isinstance(idx, int) or idx < 1 or idx > len(pool) or idx in used_indices:
                continue
            category = normalize_category(entry.get("category"), spec["default_category"])
            used_indices.add(idx)
            items.append((pool[idx - 1], category))
        result[slot] = items

    # Backfill any section that came up short so the site always has content.
    leftover = [a for i, a in enumerate(pool, start=1) if i not in used_indices]
    for slot, spec in SLOT_SPECS.items():
        while len(result[slot]) < spec["count"] and leftover:
            result[slot].append((leftover.pop(0), spec["default_category"]))

    return result


def generate_daily_dose(slots):
    """Use Claude to write today's Daily Dose from the selected articles."""
    flat = []
    for slot in ("featured_main", "featured_side", "seo", "strategy", "martech", "research", "leadership"):
        flat.extend(slots[slot])

    seen_links = set()
    top_articles = []
    for article, _category in flat:
        if article["link"] in seen_links:
            continue
        seen_links.add(article["link"])
        top_articles.append(article)
        if len(top_articles) >= 15:
            break

    today = datetime.now().strftime("%A, %B %d, %Y")
    articles_text = ""
    for a in top_articles:
        articles_text += f"- [{a['source']}] {a['title']}: {a['description'][:200]}\n"

    prompt = f"""You are the writer for Tech Marketing Dose, a daily AI news site for tech marketers. Write today's "Marketing AI Daily Dose" for {today}.

Based on today's top news stories, write a Daily Dose following this EXACT format, with each labeled part on its OWN line (do not merge multiple parts onto the same line):

HEADLINE: a single punchy sentence under 100 characters summarizing the single most important story or signal today

Today's big signal: 2-3 sentences on the single most important stat, announcement, or trend from the news below

Skill to Build: a specific skill marketers should learn. This week: a specific action item

Stat That Matters: a specific data point. Why it matters: explanation

Tool to Know: a specific tool. This week: a specific action item

The Bottom Line: 2-3 sentences tying it all together

Rules:
- Be specific and practical, not generic
- Include real company names and numbers when possible
- Write for senior marketers at tech companies
- Each of the three tips (Skill to Build, Stat That Matters, Tool to Know) should be 80-120 words
- Use plain text, no markdown formatting or headers

Today's top news stories:
{articles_text}

Write the Daily Dose now."""

    return call_claude(prompt, max_tokens=2000)


def parse_dose_text(raw_text):
    """Pull the headline, intro, three tips, and bottom line out of Claude's
    response. Anchor-based so it works whether or not Claude puts each part
    on its own line."""
    text = raw_text.strip()

    headline_match = re.search(r'HEADLINE:\s*(.+)', text)
    headline = headline_match.group(1).strip() if headline_match else "Today's Marketing AI Daily Dose"
    if headline_match:
        text = (text[:headline_match.start()] + text[headline_match.end():]).strip()

    anchors = [
        ("Skill to Build:", re.compile(r'Skill to Build:', re.IGNORECASE)),
        ("Stat That Matters:", re.compile(r'Stat That Matters:', re.IGNORECASE)),
        ("Tool to Know:", re.compile(r'Tool to Know:', re.IGNORECASE)),
        ("The Bottom Line", re.compile(r'The Bottom Line:?', re.IGNORECASE)),
    ]

    positions = []
    for label, pattern in anchors:
        m = pattern.search(text)
        if m:
            positions.append((m.start(), m.end(), label))
    positions.sort(key=lambda p: p[0])

    def clean(s):
        return re.sub(r"\s+", " ", s).strip(" \n\t:-—")

    if len(positions) == 4:
        intro = clean(text[:positions[0][0]])
        tips = []
        for i in range(3):
            body = clean(text[positions[i][1]:positions[i + 1][0]])
            tips.append({"title": positions[i][2], "body": body})
        bottom_line = clean(text[positions[3][1]:])
    else:
        intro = clean(text)
        tips = [
            {"title": "Skill to Build:", "body": ""},
            {"title": "Stat That Matters:", "body": ""},
            {"title": "Tool to Know:", "body": ""},
        ]
        bottom_line = ""

    return headline, intro, tips, bottom_line


def build_featured_main(article, category, date_str):
    css_class = CATEGORY_CSS.get(category, "strategy")
    return f"""<div class="card featured-main">
                    <div class="card-image" style="background: linear-gradient(135deg, #e94560 0%, #533483 100%); font-size: 4rem;">
                        &lbrace;AI&rbrace;
                    </div>
                    <div class="card-body">
                        <span class="card-tag {css_class}">{esc(category)}</span>
                        <h3 class="card-title"><a href="{article['link']}" target="_blank" rel="noopener">{esc(article['title'])}</a></h3>
                        <p class="card-excerpt">{esc(article['description'][:220])}</p>
                        <div class="card-meta">
                            <span>{esc(article['source'])}</span>
                            <span>{date_str}</span>
                        </div>
                    </div>
                </div>"""


def build_featured_side(pairs, date_str):
    cards = []
    for i, (article, category) in enumerate(pairs):
        css_class = CATEGORY_CSS.get(category, "strategy")
        margin = ' style="margin-bottom: 1.5rem;"' if i == 0 else ""
        cards.append(f"""<div class="card"{margin}>
                        <div class="card-body">
                            <span class="card-tag {css_class}">{esc(category)}</span>
                            <h3 class="card-title"><a href="{article['link']}" target="_blank" rel="noopener">{esc(article['title'])}</a></h3>
                            <p class="card-excerpt">{esc(article['description'][:150])}</p>
                            <div class="card-meta">
                                <span>{esc(article['source'])}</span>
                                <span>{date_str}</span>
                            </div>
                        </div>
                    </div>""")
    return "<div>\n                    " + "\n                    ".join(cards) + "\n                </div>"


def build_card(article, category, date_str):
    css_class = CATEGORY_CSS.get(category, "strategy")
    return f"""<div class="card">
                    <div class="card-body">
                        <span class="card-tag {css_class}">{esc(category)}</span>
                        <h3 class="card-title"><a href="{article['link']}" target="_blank" rel="noopener">{esc(article['title'])}</a></h3>
                        <p class="card-excerpt">{esc(article['description'][:150])}</p>
                        <div class="card-meta">
                            <span>{esc(article['source'])}</span>
                            <span>{date_str}</span>
                        </div>
                    </div>
                </div>"""


def build_strategy_card(article, category, idx, date_str):
    css_class = CATEGORY_CSS.get(category, "strategy")
    emoji = STRATEGY_EMOJIS[idx % len(STRATEGY_EMOJIS)]
    gradient = STRATEGY_GRADIENTS[idx % len(STRATEGY_GRADIENTS)]
    return f"""<div class="card">
                    <div class="card-image" style="background: linear-gradient({gradient});">
                        {emoji}
                    </div>
                    <div class="card-body">
                        <span class="card-tag {css_class}">{esc(category)}</span>
                        <h3 class="card-title"><a href="{article['link']}" target="_blank" rel="noopener">{esc(article['title'])}</a></h3>
                        <p class="card-excerpt">{esc(article['description'][:150])}</p>
                        <div class="card-meta">
                            <span>{esc(article['source'])}</span>
                            <span>{date_str}</span>
                        </div>
                    </div>
                </div>"""


def build_research_item(article, idx, date_str):
    number = f"{idx + 1:02d}"
    return f"""<div class="compact-item">
                    <span class="compact-number">{number}</span>
                    <div class="compact-content">
                        <h3><a href="{article['link']}" target="_blank" rel="noopener">{esc(article['title'])}</a></h3>
                        <p>{esc(article['description'][:180])} <span style="color:#16813e; font-weight:600;">Research</span> &middot; {date_str}</p>
                    </div>
                </div>"""


def build_dose_section_html(headline, intro, tips, bottom_line, today_date):
    today_long = today_date.strftime("%A, %B %d, %Y")
    tips_html = ""
    for i, tip in enumerate(tips[:3], 1):
        tips_html += f"""                <div class="dose-tip">
                    <div class="dose-tip-number">{i}</div>
                    <div class="dose-tip-content">
                        <h3>{esc(tip['title'])}</h3>
                        <p>{esc(tip['body'])}</p>
                    </div>
                </div>
"""
    return f"""<section class="daily-dose">
            <div class="dose-header">
                <div class="dose-icon">&#x26A1;</div>
                <div>
                    <h2>Marketing AI Daily Dose</h2>
                    <p class="dose-date">{today_long}</p>
                </div>
            </div>

            <div class="dose-intro">
                <p>{esc(intro)}</p>
            </div>

            <div class="dose-tips">
{tips_html}            </div>

            <div class="dose-bottom-line">
                <h4>The Bottom Line</h4>
                <p>{esc(bottom_line)}</p>
            </div>
        </section>"""


def build_teaser_html(headline, tips, today_date):
    today_short = today_date.strftime("%B %d, %Y")
    subtitle_parts = []
    for tip in tips[:3]:
        body = tip["body"]
        snippet = body[:40].rsplit(" ", 1)[0] if len(body) > 40 else body
        if snippet:
            subtitle_parts.append(snippet)
    subtitle = " &bull; ".join(subtitle_parts)

    return f"""<a class="dose-teaser-card" href="#" onclick="showTab('daily-dose'); return false;">
            <div class="dose-teaser-badge">&#x26A1;</div>
            <div class="dose-teaser-content">
                <div class="dose-teaser-label">Today's Daily Dose &mdash; {today_short}</div>
                <div class="dose-teaser-title">{esc(headline)}</div>
                <div class="dose-teaser-subtitle">{subtitle}</div>
            </div>
            <button class="dose-teaser-cta" onclick="showTab('daily-dose'); return false;">Read Today's Dose</button>
        </a>"""


def replace_marker(html, name, content):
    pattern = re.compile(
        r'(<!-- AUTO:' + name + r':START -->)(.*?)(<!-- AUTO:' + name + r':END -->)',
        re.DOTALL
    )
    if not pattern.search(html):
        print(f"  WARNING: AUTO:{name} markers not found, skipping")
        return html
    return pattern.sub(
        lambda m: m.group(1) + "\n                " + content + "\n                " + m.group(3),
        html, count=1
    )


def update_index_html(sections_html, teaser_html, dose_html):
    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    for name, content in sections_html.items():
        html = replace_marker(html, name, content)

    html = replace_marker(html, "TEASER", teaser_html)
    html = replace_marker(html, "DOSE", dose_html)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

    print("  index.html updated successfully")


def bump_stat(html, stat_id, delta):
    pattern = re.compile(r'(<strong id="' + stat_id + r'">)(\d+)(</strong>)')
    return pattern.sub(lambda m: m.group(1) + str(int(m.group(2)) + delta) + m.group(3), html, count=1)


def update_itemlist_json(html, new_item):
    pattern = re.compile(
        r'(<!-- AUTO:ITEMLIST:START -->\s*<script type="application/ld\+json">\s*)(.*?)(\s*</script>\s*<!-- AUTO:ITEMLIST:END -->)',
        re.DOTALL
    )
    m = pattern.search(html)
    if not m:
        print("  WARNING: ItemList JSON markers not found, skipping")
        return html
    data = json.loads(m.group(2))
    data["itemListElement"] = [
        item for item in data["itemListElement"] if item["item"]["url"] != new_item["url"]
    ]
    data["itemListElement"].insert(0, {"@type": "ListItem", "position": 1, "item": new_item})
    for i, item in enumerate(data["itemListElement"]):
        item["position"] = i + 1
    data["numberOfItems"] = len(data["itemListElement"])
    new_json_text = json.dumps(data, indent=4)
    return pattern.sub(lambda mm: mm.group(1) + new_json_text + mm.group(3), html, count=1)


def update_recent_dose_json(html, headline, date_id, description, keywords):
    pattern = re.compile(
        r'(<!-- AUTO:RECENT_DOSE:START -->\s*<script type="application/ld\+json">\s*)(.*?)(\s*</script>\s*<!-- AUTO:RECENT_DOSE:END -->)',
        re.DOTALL
    )
    m = pattern.search(html)
    if not m:
        print("  WARNING: Recent dose JSON markers not found, skipping")
        return html
    data = json.loads(m.group(2))
    data["headline"] = headline
    data["datePublished"] = date_id
    data["dateModified"] = date_id
    data["description"] = description
    data["mainEntityOfPage"] = f"https://www.techmarketingdose.com/daily-dose-archive.html#dose-{date_id}"
    data["keywords"] = keywords
    new_json_text = json.dumps(data, indent=4)
    return pattern.sub(lambda mm: mm.group(1) + new_json_text + mm.group(3), html, count=1)


def extract_keywords(headline):
    words = re.findall(r"[A-Za-z][A-Za-z0-9'&-]*", headline)
    keywords = []
    seen = set()
    for w in words:
        lw = w.lower()
        if lw in STOPWORDS or len(w) < 3 or lw in seen:
            continue
        seen.add(lw)
        keywords.append(w)
        if len(keywords) >= 6:
            break
    return keywords or ["AI marketing"]


def update_archive_html(headline, intro, tips, bottom_line, today_date):
    with open("daily-dose-archive.html", "r", encoding="utf-8") as f:
        html = f.read()

    date_id = today_date.strftime("%Y-%m-%d")
    date_long = today_date.strftime("%A, %B %d, %Y")
    entry_id = f"dose-{date_id}"

    if f'id="{entry_id}"' in html:
        print(f"  Archive already has an entry for {date_id}, skipping duplicate entry")
        return

    tip_html = ""
    for i, tip in enumerate(tips[:3], 1):
        tip_html += f"""                <div class="dose-entry-tip">
                    <div class="dose-entry-tip-num">{i}</div>
                    <div>
                        <h3>{esc(tip['title'])}</h3>
                        <p>{esc(tip['body'])}</p>
                    </div>
                </div>
"""

    entry_html = f"""        <!-- Dose: {date_long} -->
        <article class="dose-entry" id="{entry_id}" itemscope itemtype="https://schema.org/Article">
            <meta itemprop="datePublished" content="{date_id}">
            <meta itemprop="author" content="Tech Marketing Dose">
            <div class="dose-entry-header">
                <div class="dose-entry-icon">&#x26A1;</div>
                <div class="dose-entry-meta">
                    <h2 itemprop="headline">{esc(headline)}</h2>
                    <div class="dose-entry-date"><time datetime="{date_id}">{date_long}</time></div>
                    <div class="dose-entry-tags">
                        <span class="dose-tag skill">Skill</span>
                        <span class="dose-tag stat">Stat</span>
                        <span class="dose-tag tool">Tool</span>
                    </div>
                </div>
            </div>
            <div class="dose-entry-intro" itemprop="description">
                <p>{esc(intro)}</p>
            </div>
            <div class="dose-entry-tips" itemprop="articleBody">
{tip_html}            </div>
            <div class="dose-entry-bottom">
                <h4>The Bottom Line</h4>
                <p>{esc(bottom_line)}</p>
            </div>
            <a href="#{entry_id}" class="dose-permalink">&#x1F517; Permalink</a>
        </article>

"""

    html = html.replace("<!-- AUTO:NEW_ENTRY -->", "<!-- AUTO:NEW_ENTRY -->\n" + entry_html, 1)
    html = bump_stat(html, "stat-editions", 1)
    html = bump_stat(html, "stat-tips", 3)
    html = bump_stat(html, "stat-tools", 1)

    new_item = {
        "@type": "Article",
        "headline": headline,
        "datePublished": date_id,
        "description": intro[:250],
        "url": f"https://www.techmarketingdose.com/daily-dose-archive.html#{entry_id}",
    }
    html = update_itemlist_json(html, new_item)
    html = update_recent_dose_json(html, headline, date_id, intro[:250], extract_keywords(headline))

    with open("daily-dose-archive.html", "w", encoding="utf-8") as f:
        f.write(html)

    print("  daily-dose-archive.html updated successfully")


def main():
    print("=" * 50)
    print("Tech Marketing Dose - Daily Update")
    today = datetime.now()
    print(f"Date: {today.strftime('%Y-%m-%d %H:%M')}")
    print("=" * 50)

    if not ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY environment variable not set")
        return

    print("\n[1/5] Fetching RSS feeds...")
    all_articles = fetch_all_feeds()
    if not all_articles:
        print("ERROR: No articles fetched. Aborting.")
        return

    print("\n[2/5] Selecting and categorizing articles for every section...")
    slots = select_and_categorize(all_articles)
    for slot, spec in SLOT_SPECS.items():
        print(f"  {slot}: {len(slots[slot])}/{spec['count']} articles")

    if not slots["featured_main"] or len(slots["featured_side"]) < 2:
        print("ERROR: Not enough articles were fetched to fill all sections. Aborting.")
        return

    print("\n[3/5] Generating Daily Dose...")
    raw_dose_text = generate_daily_dose(slots)
    headline, intro, tips, bottom_line = parse_dose_text(raw_dose_text)
    print(f"  Headline: {headline}")

    print("\n[4/5] Building HTML for all sections...")
    date_str = today.strftime("%B %d, %Y")
    sections_html = {
        "FEATURED": (
            build_featured_main(*slots["featured_main"][0], date_str) + "\n                "
            + build_featured_side(slots["featured_side"], date_str)
        ),
        "SEO": "\n                ".join(build_card(a, c, date_str) for a, c in slots["seo"]),
        "MARTECH": "\n                        ".join(build_card(a, c, date_str) for a, c in slots["martech"]),
        "RESEARCH": "\n                ".join(
            build_research_item(a, i, date_str) for i, (a, c) in enumerate(slots["research"])
        ),
        "LEADERSHIP": "\n                ".join(build_card(a, c, date_str) for a, c in slots["leadership"]),
        "STRATEGY": "\n                ".join(
            build_strategy_card(a, c, i, date_str) for i, (a, c) in enumerate(slots["strategy"])
        ),
    }
    dose_html = build_dose_section_html(headline, intro, tips, bottom_line, today)
    teaser_html = build_teaser_html(headline, tips, today)

    print("\n[5/5] Updating index.html and archive...")
    update_index_html(sections_html, teaser_html, dose_html)
    update_archive_html(headline, intro, tips, bottom_line, today)

    print("\n" + "=" * 50)
    print("Daily update complete!")
    print("=" * 50)


if __name__ == "__main__":
    main()
