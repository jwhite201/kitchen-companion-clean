from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os
from openai import OpenAI
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
import re
import random

# Load environment variables
load_dotenv()

# Initialize Firebase
if not firebase_admin._apps:
    cred = credentials.Certificate("firebase-service-account.json")
    firebase_admin.initialize_app(cred)
db = firestore.client()

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Initialize OpenAI client
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SPOONACULAR_API_KEY = os.getenv("SPOONACULAR_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Affiliate product map
expanded_affiliate_links = {
    "mixer": {"keywords": ["mixer"], "url": "https://amzn.to/44QqzQf"},
    "mixing bowl": {"keywords": ["mixing bowl"], "url": "https://amzn.to/3SepGJI"},
    "measuring cup": {"keywords": ["measuring cup"], "url": "https://amzn.to/44h5HBt"},
    "spatula": {"keywords": ["spatula"], "url": "https://amzn.to/4iILIiP"},
    "whisk": {"keywords": ["whisk"], "url": "https://amzn.to/3GwiBlk"},
    "loaf pan": {"keywords": ["loaf pan"], "url": "https://amzn.to/42XzcpD"},
    "almond flour": {"keywords": ["almond flour"], "url": "https://amzn.to/4iCs3kx"},
    "digital thermometer": {"keywords": ["thermometer"], "url": "https://amzn.to/42SIDXr"},
    "food storage containers": {"keywords": ["storage container"], "url": "https://amzn.to/4k1U7ip"}
}

# Improve affiliate matcher
def add_affiliate_links_inline(response_text, product_map):
    lower_text = response_text.lower()
    candidates = []

    for product, data in product_map.items():
        for keyword in data["keywords"]:
            pattern = re.compile(rf'\b{re.escape(keyword)}s?\b', re.IGNORECASE)
            if pattern.search(lower_text):
                candidates.append((keyword, data["url"]))
                break

    if candidates:
        selected = random.sample(candidates, min(4, len(candidates)))
        for keyword, url in selected:
            pattern = re.compile(rf'\b({re.escape(keyword)})s?\b', re.IGNORECASE)
            response_text = pattern.sub(f"[\\1]({url})", response_text, count=1)
    else:
        fallback = random.sample(list(product_map.items()), min(3, len(product_map)))
        response_text += "\n\nRecommended Tools:\n"
        for keyword, data in fallback:
            response_text += f"- [{keyword}]({data['url']})\n"

    return response_text

@app.route('/')
def home():
    return "Kitchen Companion is live!"

@app.route('/ask_gpt', methods=['POST'])
def ask_gpt():
    data = request.get_json()
    messages = data.get('messages')
    user_id = data.get('user_id')

    if not messages:
        return jsonify({"error": "No messages provided"}), 400

    # Get last user message (full string)
    user_message = [m['content'] for m in messages if m['role'] == 'user'][-1]

    try:
        # Fetch GPT response
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo-1106",
            messages=messages,
            max_tokens=700,
            temperature=0.7
        )
        reply = response.choices[0].message.content

        # Add affiliate links
        reply_with_links = add_affiliate_links_inline(reply, expanded_affiliate_links)

        # Fetch Spoonacular image
        spoonacular_url = "https://api.spoonacular.com/recipes/complexSearch"
        params = {'query': user_message, 'number': 1, 'apiKey': SPOONACULAR_API_KEY}
        spoonacular_resp = requests.get(spoonacular_url, params=params)
        image_url = None
        if spoonacular_resp.status_code == 200:
            results = spoonacular_resp.json()
            if results['results']:
                image_url = results['results'][0]['image']

        return jsonify({"reply": reply_with_links, "image_url": image_url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/save_recipe', methods=['POST'])
def save_recipe():
    data = request.get_json()
    user_id = data.get('user_id')
    content = data.get('content')
    title = data.get('title') or "Untitled Recipe"

    if not user_id or not content:
        return jsonify({'error': 'Missing user_id or content'}), 400

    try:
        db.collection('users').document(user_id).collection('recipes').add({
            'title': title,
            'content': content,
            'timestamp': firestore.SERVER_TIMESTAMP
        })
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)