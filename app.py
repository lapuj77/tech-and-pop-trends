import streamlit as st
import pandas as pd
from pytrends.request import TrendReq
import feedparser
import tweepy
from textblob import TextBlob
import praw
import requests
import smtplib
from email.mime.text import MIMEText

st.set_page_config(page_title="Tech & Pop Trends", layout="wide")
st.title("🚀 Tech & Pop Trends")

# ─── Fonctions de récupération ────────────────────────────────────────────

@st.cache_data(ttl=900)
def get_google_trends():
    import pandas as pd, requests, xml.etree.ElementTree as ET
    # URLs RSS à tester
    rss_urls = [
        "https://trends.google.com/trends/trendingsearches/daily/rss?geo=FR",
        "https://trends.google.com/trends/trendingsearches/daily/rss?hl=fr&geo=FR",
        "https://trends.google.fr/trends/trendingsearches/daily/rss?hl=fr&geo=FR"
    ]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    for url in rss_urls:
        try:
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                # Parse le XML
                root = ET.fromstring(resp.content)
                items = root.findall(".//item")
                titles = [item.find("title").text for item in items if item.find("title") is not None]
                if titles:
                    return pd.DataFrame(titles, columns=["Trending"])
        except Exception:
            continue
    # Si on arrive ici, aucun flux n'a marché
    st.error("⚠️ Impossible de récupérer les Google Trends via RSS.")
    return pd.DataFrame()

@st.cache_data(ttl=900)
def get_google_news():
    rss_url = (
        "https://news.google.com/rss/"
        "search?q=technologie+OR+pop+culture&hl=fr&gl=FR&ceid=FR:FR"
    )
    feed = feedparser.parse(rss_url)
    return feed.entries

@st.cache_data(ttl=900)
def get_twitter_data():
    # récupère les clés dans les Secrets (sinon lève KeyError)
    auth = tweepy.OAuth1UserHandler(
        st.secrets["twitter"]["consumer_key"],
        st.secrets["twitter"]["consumer_secret"],
        st.secrets["twitter"]["access_token"],
        st.secrets["twitter"]["access_secret"]
    )
    api = tweepy.API(auth)
    # top hashtags France
    trends = api.get_place_trends(id=23424819)[0]["trends"]
    tags = [t["name"] for t in trends if t["name"].startswith("#")][:10]
    # sentiment avec TextBlob
    sentiments = {}
    for tag in tags:
        tweets = api.search_tweets(q=tag, lang="fr", count=30)
        if tweets:
            polarity = sum(TextBlob(t.text).sentiment.polarity for t in tweets) / len(tweets)
            sentiments[tag] = polarity
    return tags, sentiments

@st.cache_data(ttl=900)
def get_reddit_data():
    reddit = praw.Reddit(
        client_id=st.secrets["reddit"]["client_id"],
        client_secret=st.secrets["reddit"]["client_secret"],
        user_agent="techpop_trends"
    )
    posts = []
    for sub in ["technology", "popculture"]:
        for post in reddit.subreddit(sub).hot(limit=10):
            posts.append({
                "subreddit": sub,
                "title": post.title,
                "score": post.score,
                "comments": post.num_comments
            })
    return posts

def send_alerts(message: str):
    # Slack
    if "slack" in st.secrets:
        requests.post(st.secrets["slack"]["webhook_url"], json={"text": message})
    # Email
    if "email" in st.secrets:
        msg = MIMEText(message)
        msg["Subject"] = "Tech & Pop Trends Alert"
        msg["From"] = st.secrets["email"]["smtp_user"]
        msg["To"] = st.secrets["email"]["recipient"]
        with smtplib.SMTP_SSL(
            st.secrets["email"]["smtp_server"],
            st.secrets["email"]["smtp_port"]
        ) as server:
            server.login(
                st.secrets["email"]["smtp_user"],
                st.secrets["email"]["smtp_password"]
            )
            server.send_message(msg)

# ─── Affichage du dashboard ───────────────────────────────────────────────

st.header("📈 Google Trends en France")
trends_df = get_google_trends()
if trends_df.empty:
    st.warning("😕 Aucune tendance disponible pour le moment.")
else:
    st.table(trends_df.head(10))

# Google Actualités
st.header("📰 Google Actualités Tech & Pop Culture")
for entry in get_google_news()[:10]:
    st.markdown(f"- [{entry.title}]({entry.link})")

# Twitter (si configuré)
try:
    st.header("🐦 Twitter : hashtags & sentiment")
    tags, sentiments = get_twitter_data()
    for tag in tags:
        st.write(f"{tag} → Sentiment moyen : {sentiments.get(tag, 0):.2f}")
except KeyError:
    st.warning("⚠️ Twitter non configuré – ajoute tes clés dans les Secrets.")

# Reddit (si configuré)
try:
    st.header("👽 Reddit : posts populaires")
    reddit_df = pd.DataFrame(get_reddit_data())
    st.dataframe(reddit_df)
except KeyError:
    st.warning("⚠️ Reddit non configuré – ajoute tes clés dans les Secrets.")

# Bouton d’alerte manuelle
if st.button("🔔 Envoyer alerte e-mail/Slack"):
    top5 = trends_df.head(5)[0].tolist()
    send_alerts("Nouvelles tendances : " + ", ".join(top5))
    st.success("Alertes envoyées ! 🎉")

st.info("Actualisation automatique toutes les 15 minutes.")
