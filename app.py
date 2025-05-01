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

# Expanded affiliate links with keyword variants
expanded_affiliate_links = {
    "mixer": {
        "keywords": ["mixer", "stand mixer", "hand mixer", "electric mixer", "kitchen mixer"],
        "url": "https://amzn.to/44QqzQf"
    },
    "mixing bowl": {
        "keywords": ["mixing bowl", "bowl", "baking bowl", "prep bowl"],
        "url": "https://amzn.to/3SepGJI"
    },
    "measuring cup": {
        "keywords": ["measuring cup", "measuring cups", "measuring tools"],
        "url": "https://amzn.to/44h5HBt"
    },
    "spatula": {
        "keywords": ["spatula", "rubber spatula", "silicone spatula"],
        "url": "https://amzn.to/4iILIiP"
    },
    "scale": {
        "keywords": ["scale", "kitchen scale", "digital scale", "food scale"],
        "url": "https://amzn.to/4cUBs5t"
    },
    "rolling pin": {
        "keywords": ["rolling pin", "dough roller", "pastry roller"],
        "url": "https://amzn.to/3Gy1mQv"
    },
    "6-inch pan": {
        "keywords": ["6-inch pan", "6-inch", "six inch cake pan", "6\" cake pan"],
        "url": "https://amzn.to/4lRwo64"
    },
    "9-inch pan": {
        "keywords": ["9-inch", "9-inch pan", "nine inch cake pan", "9\" cake pan"],
        "url": "https://amzn.to/42xSUtc"
    },
    "cake decorating": {
        "keywords": ["cake decorating", "piping tips", "frosting tools", "decorating kit", "icing tools"],
        "url": "https://amzn.to/4lUd08m"
    },
    "whisk": {
        "keywords": ["whisk", "balloon whisk", "wire whisk"],
        "url": "https://amzn.to/3GwiBlk"
    },
    "bench scraper": {
        "keywords": ["bench scraper", "dough scraper", "pastry scraper"],
        "url": "https://amzn.to/3GzcuN2"
    },
    "loaf pan": {
        "keywords": ["loaf pan", "bread pan"],
        "url": "https://amzn.to/42XzcpD"
    },
    "almond flour": {
        "keywords": ["almond flour", "blanched almond flour"],
        "url": "https://amzn.to/4iCs3kx"
    },
    "no sugar added chocolate chips": {
        "keywords": ["no sugar chocolate chips", "sugar-free chocolate chips", "healthy chocolate chips"],
        "url": "https://amzn.to/3SfqlKU"
    },
    "monk fruit sweetener": {
        "keywords": ["monk fruit", "monk fruit sweetener", "monkfruit"],
        "url": "https://amzn.to/4cSRP2u"
    },
    "coconut sugar": {
        "keywords": ["coconut sugar", "natural sugar"],
        "url": "https://amzn.to/42TZN6S"
    },
    "whole wheat flour": {
        "keywords": ["whole wheat flour", "whole grain flour"],
        "url": "https://amzn.to/4jAbpmQ"
    },
    "cake flour": {
        "keywords": ["cake flour", "soft wheat flour"],
        "url": "https://amzn.to/3YmwUz1"
    },
    "silicone baking mat": {
        "keywords": ["silicone baking mat", "silpat", "nonstick baking mat"],
        "url": "https://amzn.to/4jJcRmI"
    },
    "avocado oil": {
        "keywords": ["avocado oil", "healthy oil", "cooking oil"],
        "url": "https://amzn.to/3EwlK43"
    },
    "digital thermometer": {
        "keywords": ["digital thermometer", "meat thermometer", "kitchen thermometer"],
        "url": "https://amzn.to/42SIDXr"
    },
    "food storage containers": {
        "keywords": ["food storage", "meal prep containers", "storage containers"],
        "url": "https://amzn.to/4k1U7ip"
    }
}

}

# Load environment variables from .env
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
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Function to inject one random affiliate link inline
def add_affiliate_links_inline(response_text, product_map):
    lower_text = response_text.lower()
    candidates = []

    for product, data in product_map.items():
        for keyword in data["keywords"]:
            pattern = r'\\b' + re.escape(keyword.lower()) + r's?\\b'
            if re.search(pattern, lower_text):
                candidates.append((keyword, data["url"]))
                break

    if not candidates:
        return response_text

    chosen_keyword, url = random.choice(candidates)
    pattern = re.compile(r'\\b(' + re.escape(chosen_keyword) + r')\\b', re.IGNORECASE)

    def replacer(match):
        return f"[{match.group(1)}]({url})"

    return pattern.sub(replacer, response_text, count=1)

@app.route('/')
def home():
    return "Kitchen Companion is live!"

@app.route('/ask_gpt', methods=['POST'])
def ask_gpt():
    data = request.get_json()
    messages = data.get('messages')  # now expecting a list of role/content pairs

    if not messages:
        return jsonify({"error": "No messages provided"}), 400

    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo-1106",
            messages=messages,
            max_tokens=700,
            temperature=0.7
        )
        reply = response.choices[0].message.content
        reply_with_links = add_affiliate_links_inline(reply, expanded_affiliate_links)
        return jsonify({"reply": reply_with_links})
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

# Run the Flask app on Render
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
