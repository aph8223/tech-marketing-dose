import json
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import os
import re

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


def fetch_rss_feed(feed_url, source_name):
    """Fetch and parse a single RSS feed, return list of articles."""
    articles = []
    try:
        req = urllib.request.Request(feed_url, headers={"User-Agent": "TechMarketingDose/1.0"})
        with urllib.request.urlopen(req, timeout=15) as response:
            xml_data = response.read()
        root = ET.fromstring(xml_data)

        # Handle both RSS and Atom formats
        namespaces = {"atom": "http://www.w3.org/2005/Atom"}

        # RSS format
        for item in root.findall(".//item"):
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            description = item.findtext("description", "").strip()
            pub_date = item.findtext("pubDate", "").strip()
            if title:
                # Clean HTML from description
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
        all_articles.extend(articles[:5])  # Take top 5 from each feed
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


def filter_and_rank_articles(articles):
    """Use Claude to filter articles for relevance to AI + marketing."""
    articles_text = ""
    for i, a in enumerate(articles[:50]):
        articles_text += f"{i+1}. [{a['source']}] {a['title']}\n   {a['description'][:150]}\n\n"

    prompt = f"""You are a news editor for Tech Marketing Dose, a site for tech marketers interested in AI.

Below are {min(len(articles), 50)} recent articles from various sources. Select the 15 MOST relevant to tech marketers interested in AI. They must be about one of these topics:
- AI tools for marketing
- AI and SEO/search
- Marketing technology (martech) product launches or updates
- CMO/marketing leadership hires at tech companies
- AI research relevant to marketers
- Funding/acquisitions of marketing tech companies
- AI strategy for marketing teams

Return ONLY a JSON array of the article numbers (1-indexed) that are most relevant, ranked by importance. Example: [3, 7, 12, 1, 15, ...]

Articles:
{articles_text}

Return ONLY the JSON array, nothing else."""

    response = call_claude(prompt, max_tokens=200)
    # Extract JSON array from response
    match = re.search(r'\[[\d,\s]+\]', response)
    if match:
        indices = json.loads(match.group())
        return [articles[i-1] for i in indices if 0 < i <= len(articles)]
    return articles[:15]


def generate_daily_dose(top_articles):
    """Generate today's Daily Dose content using Claude."""
    today = datetime.now().strftime("%A, %B %d, %Y")

    articles_text = ""
    for a in top_articles[:15]:
        articles_text += f"- [{a['source']}] {a['title']}: {a['description'][:200]}\n"

    prompt = f"""You are the writer for Tech Marketing Dose, a daily AI news site for tech marketers. Write today's "Marketing AI Daily Dose" for {today}.

Based on today's top news stories, write a Daily Dose following this EXACT format:

1. Start with "Today's big signal:" — pick the single most important stat, announcement, or trend from the news below
2. Write 3 tips:
   - Tip 1: "Skill to Build:" — a specific skill marketers should learn, with a "This week:" action item
   - Tip 2: "Stat That Matters:" — a specific data point and "Why it matters:" explanation
   - Tip 3: "Tool to Know:" — a specific tool and "This week:" action item
3. End with "The Bottom Line" — 2-3 sentences tying it all together

Rules:
- Be specific and practical, not generic
- Include real company names and numbers when possible
- Write for senior marketers at tech companies
- Each tip should be 80-120 words
- The intro should be 2-3 sentences max

Today's top news stories:
{articles_text}

Write the Daily Dose now. Use plain text, no markdown formatting or headers."""

    return call_claude(prompt, max_tokens=2000)


def generate_news_html(articles):
    """Generate HTML cards for the news grid."""
    categories = {
        "AI Strategy": "strategy",
        "MarTech": "martech",
        "AI & SEO": "seo",
        "Leadership": "leadership",
        "Research": "research",
        "Product Launch": "product"
    }

    # Use Claude to categorize articles
    articles_text = "\n".join([f"{i+1}. {a['title']}" for i, a in enumerate(articles[:15])])
    prompt = f"""Categorize each article into exactly ONE of these categories: AI Strategy, MarTech, AI & SEO, Leadership, Research, Product Launch

Articles:
{articles_text}

Return a JSON array where each element is the category name for that article number. Example: ["MarTech", "AI Strategy", "Product Launch", ...]
Return ONLY the JSON array."""

    response = call_claude(prompt, max_tokens=300)
    match = re.search(r'\[.*?\]', response, re.DOTALL)
    if match:
        cats = json.loads(match.group())
    else:
        cats = ["AI Strategy"] * len(articles)

    html_cards = ""
    for i, article in enumerate(articles[:12]):
        cat = cats[i] if i < len(cats) else "AI Strategy"
        css_class = categories.get(cat, "strategy")
        source = article["source"]
        title = article["title"].replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
        desc = article["description"][:150].replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
        link = article["link"]

        html_cards += f"""                <div class="card">
                    <div class="card-body">
                        <span class="card-tag {css_class}">{cat}</span>
                        <h3 class="card-title"><a href="{link}" target="_blank" rel="noopener">{title}</a></h3>
                        <p class="card-excerpt">{desc}</p>
                        <div class="card-meta">
                            <span>{source}</span>
                            <span>{datetime.now().strftime("%B %d, %Y")}</span>
                        </div>
                    </div>
                </div>
"""
    return html_cards


def format_daily_dose_html(dose_text):
    """Convert the Daily Dose plain text into HTML."""
    today = datetime.now().strftime("%A, %B %d, %Y")
    today_short = datetime.now().strftime("%B %d, %Y")

    # Parse the dose text into sections
    lines = dose_text.strip().split("\n")
    intro = ""
    tips = []
    bottom_line = ""

    current_section = "intro"
    current_tip = {"title": "", "body": ""}

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if "Skill to Build:" in line or "Stat That Matters:" in line or "Tool to Know:" in line:
            if current_tip["title"]:
                tips.append(current_tip)
            current_section = "tip"
            current_tip = {"title": line, "body": ""}
        elif "The Bottom Line" in line or "Bottom Line:" in line:
            if current_tip["title"]:
                tips.append(current_tip)
            current_section = "bottom"
        elif current_section == "intro":
            intro += line + " "
        elif current_section == "tip":
            current_tip["body"] += line + " "
        elif current_section == "bottom":
            bottom_line += line + " "

    if current_tip["title"] and current_tip not in tips:
        tips.append(current_tip)

    # Build HTML
    tips_html = ""
    for i, tip in enumerate(tips[:3], 1):
        tips_html += f"""                <div class="dose-tip">
                    <div class="dose-tip-number">{i}</div>
                    <div class="dose-tip-content">
                        <h3>{tip['title']}</h3>
                        <p>{tip['body'].strip()}</p>
                    </div>
                </div>
"""

    dose_html = f"""        <section class="daily-dose">
            <div class="dose-header">
                <div class="dose-icon">&#x26A1;</div>
                <div>
                    <h2>Marketing AI Daily Dose</h2>
                    <p class="dose-date">{today}</p>
                </div>
            </div>

            <div class="dose-intro">
                <p>{intro.strip()}</p>
            </div>

            <div class="dose-tips">
{tips_html}
            </div>

            <div class="dose-bottom-line">
                <h4>The Bottom Line</h4>
                <p>{bottom_line.strip()}</p>
            </div>
        </section>"""

    # Teaser HTML
    teaser_title = intro.strip()[:100]
    if len(intro.strip()) > 100:
        teaser_title = teaser_title.rsplit(" ", 1)[0] + "..."

    tip_topics = " &bull; ".join([t["title"].split(":")[1].strip()[:40] for t in tips[:3]])

    teaser_html = f"""    <div class="dose-teaser" id="dose-teaser">
        <a class="dose-teaser-card" href="#" onclick="showTab('daily-dose'); return false;">
            <div class="dose-teaser-badge">&#x26A1;</div>
            <div class="dose-teaser-content">
                <div class="dose-teaser-label">Today's Daily Dose &mdash; {today_short}</div>
                <div class="dose-teaser-title">{teaser_title}</div>
                <div class="dose-teaser-subtitle">{tip_topics}</div>
            </div>
            <button class="dose-teaser-cta" onclick="showTab('daily-dose'); return false;">Read Today's Dose</button>
        </a>
    </div>"""

    return dose_html, teaser_html


def update_html_file(news_html, dose_html, teaser_html):
    """Update the index.html file with fresh content."""
    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    # Update the Featured Stories news grid
    # Find and replace the featured-grid content
    pattern_news = r'(<div class="news-grid">\s*)(.*?)(</div>\s*</section>\s*<!-- MarTech Section -->)'
    replacement_news = f'\\1\n{news_html}\\3'
    html = re.sub(pattern_news, replacement_news, html, count=1, flags=re.DOTALL)

    # Update the Daily Dose teaser
    pattern_teaser = r'(<\!-- Daily Dose Teaser.*?-->)\s*<div class="dose-teaser".*?</a>\s*</div>'
    replacement_teaser = f'\\1\n{teaser_html}'
    html = re.sub(pattern_teaser, replacement_teaser, html, count=1, flags=re.DOTALL)

    # Update the Daily Dose tab content
    pattern_dose = r'(<\!-- DAILY DOSE TAB -->.*?<div class="dose-page">)\s*<section class="daily-dose">.*?</section>'
    replacement_dose = f'\\1\n{dose_html}'
    html = re.sub(pattern_dose, replacement_dose, html, count=1, flags=re.DOTALL)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

    print("  index.html updated successfully")


def main():
    print("=" * 50)
    print(f"Tech Marketing Dose - Daily Update")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 50)

    if not ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY environment variable not set")
        return

    # Step 1: Fetch RSS feeds
    print("\n[1/5] Fetching RSS feeds...")
    all_articles = fetch_all_feeds()

    if not all_articles:
        print("ERROR: No articles fetched. Aborting.")
        return

    # Step 2: Filter and rank for relevance
    print("\n[2/5] Filtering for AI marketing relevance...")
    top_articles = filter_and_rank_articles(all_articles)
    print(f"  Selected {len(top_articles)} relevant articles")

    # Step 3: Generate Daily Dose
    print("\n[3/5] Generating Daily Dose...")
    dose_text = generate_daily_dose(top_articles)
    print("  Daily Dose generated")

    # Step 4: Generate HTML
    print("\n[4/5] Building HTML...")
    news_html = generate_news_html(top_articles)
    dose_html, teaser_html = format_daily_dose_html(dose_text)

    # Step 5: Update the HTML file
    print("\n[5/5] Updating index.html...")
    update_html_file(news_html, dose_html, teaser_html)

    print("\n" + "=" * 50)
    print("Daily update complete!")
    print("=" * 50)


if __name__ == "__main__":
    main()
