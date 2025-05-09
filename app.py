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

@st.cache_data(ttl=900)
def get_google_trends():
    pytrends = TrendReq(hl='fr-FR', geo='FR')
    return pytrends.trending_searches(pn='france')

@st.cache_data(ttl=900)
def get_google_news():
    rss_url = "https://news.google.com/rss/search?q=technologie+OR+pop+culture&hl=fr&gl=FR&ceid=FR:FR"
    feed = feedparser.parse(rss_url)
    return feed.entries

def get_twitter_trends(api):
    woeid_fr = 23424819
    trends = api.get_place_trends(id=woeid_fr)
    hashtags = [t['name'] for t in trends[0]['trends'] if t['name'].startswith('#')]
    return hashtags[:10]

@st.cache_data(ttl=900)
def get_twitter_data():
    consumer_key = st.secrets["twitter"]["consumer_key"]
    consumer_secret = st.secrets["twitter"]["consumer_secret"]
    access_token = st.secrets["twitter"]["access_token"]
    access_secret = st.secrets["twitter"]["access_secret"]
    auth = tweepy.OAuth1UserHandler(consumer_key, consumer_secret, access_token, access_secret)
    api = tweepy.API(auth)
    tags = get_twitter_trends(api)
    sentiments = {}
    for tag in tags:
        tweets = api.search_tweets(q=tag, lang='fr', count=50)
        polarity = sum(TextBlob(tweet.text).sentiment.polarity for tweet in tweets) / len(tweets)
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
    for subreddit in ["technology", "popculture"]:
        for post in reddit.subreddit(subreddit).hot(limit=10):
            posts.append({"subreddit": subreddit, "title": post.title, "score": post.score, "comments": post.num_comments})
    return posts

def send_alerts(message):
    if "slack" in st.secrets:
        webhook = st.secrets["slack"]["webhook_url"]
        requests.post(webhook, json={"text": message})
    if "email" in st.secrets:
        smtp_server = st.secrets["email"]["smtp_server"]
        smtp_port = st.secrets["email"]["smtp_port"]
        smtp_user = st.secrets["email"]["smtp_user"]
        smtp_password = st.secrets["email"]["smtp_password"]
        recipient = st.secrets["email"]["recipient"]
        msg = MIMEText(message)
        msg["Subject"] = "Tech & Pop Trends Alert"
        msg["From"] = smtp_user
        msg["To"] = recipient
        with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
