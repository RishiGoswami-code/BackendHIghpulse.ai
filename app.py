from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from datetime import datetime
import google.generativeai as genai
import os
from dotenv import load_dotenv
from youtube_transcript_api import YouTubeTranscriptApi
from googleapiclient.discovery import build
import tweepy
import wikipedia
from bs4 import BeautifulSoup
import re
import json
from pathlib import Path
import csv
import hashlib
import pytrends
from pytrends.request import TrendReq
import pandas as pd

load_dotenv()

# Configuration
genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
model = genai.GenerativeModel('gemini-1.5-flash')

app = Flask(__name__)
CORS(app, resources={
    r"/api/*": {
        "origins": ["https://highpulse-ai-vga3.onrender.com"],
        "methods": ["POST", "OPTIONS"],
        "allow_headers": ["Content-Type"]
    }
})

# API Clients
REDDIT_API_URL = "https://www.reddit.com"
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)

# Twitter API Configuration
try:
    TWITTER_API_KEY = os.getenv('TWITTER_API_KEY')
    TWITTER_API_SECRET = os.getenv('TWITTER_API_SECRET')
    TWITTER_ACCESS_TOKEN = os.getenv('TWITTER_ACCESS_TOKEN')
    TWITTER_ACCESS_SECRET = os.getenv('TWITTER_ACCESS_SECRET')
    
    twitter_auth = tweepy.OAuthHandler(TWITTER_API_KEY, TWITTER_API_SECRET)
    twitter_auth.set_access_token(TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET)
    twitter_api = tweepy.API(twitter_auth, wait_on_rate_limit=True)
except Exception as e:
    print(f"Twitter API initialization failed: {str(e)}")
    twitter_api = None

# Google Trends
pytrends = TrendReq(hl='en-US', tz=360)

WIKIPEDIA_LANG = 'en'
wikipedia.set_lang(WIKIPEDIA_LANG)

DATA_DIR = Path('data')
DATA_DIR.mkdir(exist_ok=True)

# User database file
USERS_FILE = DATA_DIR / 'users.csv'

# Initialize users file if it doesn't exist
if not USERS_FILE.exists():
    with open(USERS_FILE, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['name', 'email', 'password_hash'])

def hash_password(password):
    """Hash a password for storing."""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(stored_hash, provided_password):
    """Verify a stored password against one provided by user"""
    return stored_hash == hashlib.sha256(provided_password.encode()).hexdigest()

def user_exists(email):
    """Check if a user exists in the database"""
    with open(USERS_FILE, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['email'] == email:
                return True
    return False

def create_user(name, email, password):
    """Create a new user in the database"""
    if user_exists(email):
        return False
    
    with open(USERS_FILE, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([name, email, hash_password(password)])
    return True

def authenticate_user(email, password):
    """Authenticate a user"""
    with open(USERS_FILE, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['email'] == email and verify_password(row['password_hash'], password):
                return {
                    'name': row['name'],
                    'email': row['email']
                }
    return None

def refine_query_with_gemini(user_query):
    try:
        response = model.generate_content(
            f"Extract key keywords from: '{user_query}'. Return only 2-3 space-separated keywords."
        )
        return response.text.strip().strip('"')
    except Exception as e:
        print(f"Gemini refinement error: {str(e)}")
        return user_query

def analyze_with_gemini(prompt, content):
    try:
        response = model.generate_content(
            f"{prompt}\n\nData:\n{json.dumps(content, indent=2)[:10000]}",
            generation_config={
                "temperature": 0.3,
                "max_output_tokens": 2000,
                "top_p": 0.9
            }
        )
        return response.text
    except Exception as e:
        print(f"Gemini analysis error: {str(e)}")
        return f"Analysis failed: {str(e)}"

def scrape_reddit(query, max_posts=5):
    try:
        refined_query = refine_query_with_gemini(query)
        url = f"{REDDIT_API_URL}/search.json?q={requests.utils.quote(refined_query)}&sort=top&limit={max_posts}"
        headers = {'User-Agent': 'SocialMediaAnalyzer/1.0'}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        posts = []
        for post in response.json().get('data', {}).get('children', []):
            data = post.get('data', {})
            posts.append({
                'title': data.get('title', 'No title'),
                'author': f"u/{data.get('author', 'anonymous')}",
                'upvotes': data.get('ups', 0),
                'url': f"https://reddit.com{data.get('permalink', '')}",
                'content': (data.get('selftext', '')[:500] + '...') if data.get('selftext') else '[Media Post]',
                'comments': data.get('num_comments', 0),
                'created': datetime.fromtimestamp(data.get('created_utc', 0)).strftime('%Y-%m-%d'),
                'platform': 'reddit'
            })
        return posts
    except Exception as e:
        print(f"Reddit scrape error: {str(e)}")
        return None

def scrape_youtube(query, max_videos=3):
    try:
        search_response = youtube.search().list(
            q=query,
            part='id,snippet',
            maxResults=max_videos,
            type='video',
            order='relevance'
        ).execute()

        videos = []
        for item in search_response.get('items', []):
            video_id = item['id']['videoId']
            video_info = youtube.videos().list(
                part='snippet,statistics',
                id=video_id
            ).execute().get('items', [{}])[0]

            try:
                transcript = YouTubeTranscriptApi.get_transcript(video_id)
                transcript_text = ' '.join([t['text'] for t in transcript][:500])
            except:
                transcript_text = None

            videos.append({
                'title': item['snippet']['title'],
                'channel': item['snippet']['channelTitle'],
                'views': int(video_info.get('statistics', {}).get('viewCount', 0)),
                'likes': int(video_info.get('statistics', {}).get('likeCount', 0)),
                'comments_count': int(video_info.get('statistics', {}).get('commentCount', 0)),
                'url': f"https://youtube.com/watch?v={video_id}",
                'transcript': transcript_text,
                'platform': 'youtube'
            })
        return videos
    except Exception as e:
        print(f"YouTube scrape error: {str(e)}")
        return None

def scrape_twitter(query, max_tweets=5):
    if not twitter_api:
        return None
        
    try:
        tweets = []
        for tweet in tweepy.Cursor(twitter_api.search_tweets,
                                 q=query,
                                 tweet_mode='extended',
                                 result_type='recent',
                                 lang='en').items(max_tweets):
            tweets.append({
                'text': tweet.full_text,
                'user': tweet.user.screen_name,
                'retweets': tweet.retweet_count,
                'likes': tweet.favorite_count,
                'date': tweet.created_at.strftime('%Y-%m-%d'),
                'url': f"https://twitter.com/{tweet.user.screen_name}/status/{tweet.id}",
                'platform': 'twitter'
            })
        return tweets
    except Exception as e:
        print(f"Twitter scrape error: {str(e)}")
        return None

def scrape_quora(query, max_questions=3):
    try:
        url = f"https://www.quora.com/search?q={requests.utils.quote(query)}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        questions = []
        
        for item in soup.select('.q-box.qu-borderBottom')[:max_questions]:
            title_elem = item.select_one('.q-text.qu-dynamicFontSize--large')
            if not title_elem:
                continue
                
            questions.append({
                'title': title_elem.get_text(strip=True),
                'url': "https://www.quora.com" + item.find('a')['href'],
                'platform': 'quora'
            })
        return questions
    except Exception as e:
        print(f"Quora scrape error: {str(e)}")
        return None

def scrape_wikipedia(query):
    try:
        search_results = wikipedia.search(query)
        if not search_results:
            return None
            
        page = wikipedia.page(search_results[0], auto_suggest=False)
        return {
            'title': page.title,
            'url': page.url,
            'summary': page.summary,
            'platform': 'wikipedia'
        }
    except Exception as e:
        print(f"Wikipedia scrape error: {str(e)}")
        return None

def get_google_trends(query, timeframe='today 12-m'):
    """Get Google Trends data for the query"""
    try:
        pytrends.build_payload([query], timeframe=timeframe)
        interest_over_time_df = pytrends.interest_over_time()
        
        if not interest_over_time_df.empty:
            # Convert to list of {date: value} objects
            trends_data = []
            for date, row in interest_over_time_df.iterrows():
                if date and not pd.isna(row[query]):
                    trends_data.append({
                        'date': date.strftime('%Y-%m-%d'),
                        'value': int(row[query])
                    })
            
            # Get related queries
            related_queries = pytrends.related_queries()
            top_related = related_queries[query]['top'].head(5).to_dict('records') if related_queries[query]['top'] is not None else []
            rising_related = related_queries[query]['rising'].head(5).to_dict('records') if related_queries[query]['rising'] is not None else []
            
            return {
                'trends': trends_data,
                'top_related': top_related,
                'rising_related': rising_related
            }
        return None
    except Exception as e:
        print(f"Google Trends error: {str(e)}")
        return None

@app.route('/api/auth/login', methods=['POST'])
def api_login():
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json()
    email = data.get('email', '').strip()
    password = data.get('password', '').strip()

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    user = authenticate_user(email, password)
    if not user:
        return jsonify({"error": "Invalid credentials"}), 401

    return jsonify({
        "success": True,
        "user": user
    })

@app.route('/api/auth/register', methods=['POST'])
def api_register():
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json()
    name = data.get('name', '').strip()
    email = data.get('email', '').strip()
    password = data.get('password', '').strip()

    if not name or not email or not password:
        return jsonify({"error": "All fields are required"}), 400

    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400

    if user_exists(email):
        return jsonify({"error": "Email already registered"}), 400

    if create_user(name, email, password):
        return jsonify({
            "success": True,
            "user": {
                "name": name,
                "email": email
            }
        })
    else:
        return jsonify({"error": "Registration failed"}), 500

@app.route('/api/chat', methods=['POST', 'OPTIONS'])
def chat():
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'preflight'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        return response

    try:
        if not request.is_json:
            return jsonify({"error": "Request must be JSON"}), 400

        data = request.get_json()
        if not data or 'query' not in data or 'chat_history' not in data:
            return jsonify({"error": "Query and chat history are required"}), 400

        # Include analysis data in the prompt for context
        analysis_data = data.get('analysis_data', {})
        platform_data = []
        
        if analysis_data.get('platform_status'):
            for platform, status in analysis_data['platform_status'].items():
                if status == 'success':
                    platform_data.append(f"{platform} data was successfully analyzed")
                else:
                    platform_data.append(f"{platform} data was not available")

        # Generate context-aware response
        prompt = f"""You are a social media analysis assistant helping a user understand data about '{data.get('context', 'the topic')}'.
        
                Platform Analysis Status:
                {'\n'.join(platform_data)}
                
                Chat History:
                """
        
        for msg in data['chat_history']:
            prompt += f"{msg['role']}: {msg['content']}\n"
        
        prompt += f"\nUser: {data['query']}\nAssistant:"
        
        response = model.generate_content(
            prompt,
            generation_config={
                "temperature": 0.7,
                "max_output_tokens": 1000,
                "top_p": 0.9
            }
        )

        return jsonify({
            "response": response.text,
            "context": data.get('context', '')
        })

    except Exception as e:
        return jsonify({
            "error": "An error occurred during chat",
            "details": str(e)
        }), 500

@app.route('/api/analyze', methods=['POST', 'OPTIONS'])
def analyze():
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'preflight'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        return response

    try:
        if not request.is_json:
            return jsonify({"error": "Request must be JSON"}), 400

        data = request.get_json()
        if not data or 'query' not in data:
            return jsonify({"error": "Query parameter is required"}), 400

        query = data['query'].strip()
        if not query:
            return jsonify({"error": "Query cannot be empty"}), 400

        # Scrape data from all platforms
        scraped_data = []
        platform_status = {}

        platforms = [
            ('reddit', scrape_reddit),
            ('youtube', scrape_youtube),
            ('twitter', scrape_twitter),
            ('quora', scrape_quora),
            ('wikipedia', scrape_wikipedia)
        ]

        for platform_name, scraper in platforms:
            try:
                data = scraper(query)
                if data:
                    scraped_data.extend(data if isinstance(data, list) else [data])
                    platform_status[platform_name] = "success"
                else:
                    platform_status[platform_name] = "failed"
            except Exception as e:
                print(f"{platform_name} scrape failed: {str(e)}")
                platform_status[platform_name] = "failed"

        # Get Google Trends data
        google_trends = None
        try:
            google_trends = get_google_trends(query)
            if google_trends:
                platform_status['google_trends'] = "success"
            else:
                platform_status['google_trends'] = "failed"
        except Exception as e:
            print(f"Google Trends failed: {str(e)}")
            platform_status['google_trends'] = "failed"

        if not scraped_data and not google_trends:
            return jsonify({
                "error": "No data could be collected from any platform",
                "platform_status": platform_status
            }), 404

        # Perform analysis
        analysis_result = {
            'query': query,
            'platform_status': platform_status,
            'analysis': {
                'detailed_explanation': analyze_with_gemini(
                    f"Provide a comprehensive 400-word explanation of '{query}' based on these posts. Include recent trends and developments.",
                    scraped_data
                ),
                'market_analysis': analyze_with_gemini(
                    f"Analyze commercial potential and market opportunities for '{query}'. Include data from the last 6 months where available.",
                    scraped_data
                ),
                'public_opinion': analyze_with_gemini(
                    f"Summarize public sentiment and key opinions about '{query}'. Identify major concerns and positive aspects mentioned.",
                    scraped_data
                ),
                'sentiment_analysis': analyze_with_gemini(
                    f"Perform detailed sentiment analysis on content about '{query}'. Provide percentages for positive, neutral, and negative sentiment. Include a breakdown by platform if possible.",
                    scraped_data
                ),
                'trend_analysis': analyze_with_gemini(
                    f"Identify emerging trends related to '{query}' based on the data. Highlight any patterns or changes over time.",
                    scraped_data
                )
            },
            'google_trends': google_trends,
            'source_count': len(scraped_data),
            'timestamp': datetime.now().isoformat()
        }

        return jsonify(analysis_result)

    except Exception as e:
        return jsonify({
            "error": "An error occurred during analysis",
            "details": str(e)
        }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
