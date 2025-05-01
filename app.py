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

load_dotenv()

# Initialize Firebase
if not firebase_admin._apps:
    cred = credentials.Certificate("firebase-service-account.json")
    firebase_admin.initialize_app(cred)
db = firestore.client()

app = Flask(__name__)
CORS(app)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SPOONACULAR_API_KEY = os.getenv("SPOONACULAR_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Affiliate links map
expanded_affiliate_links = {
    "mixer": {"keywords": ["mixer", "stand mixer"], "url": "https://amzn.to/44QqzQf"},
    "almond flour": {"keywords": ["almond flour"], "url": "https://amzn.to/4iCs3kx"},
    "cake pan": {"keywords": ["cake pan", "9-inch pan"], "url": "https://amzn.to/42xSUtc"},
    "spatula": {"keywords": ["spatula"], "url": "https://amzn.to/4iILIiP"},
}

def add_affiliate_links_inline(text, product_map):
    lower = text.lower()
    added = 0
    for product, data in product_map.items():
        for kw in data["keywords"]:
            if kw in lower and added < 4:
                text = re.sub(rf"\b({kw})\b", f"[\\1]({data['url']})", text, flags=re.IGNORECASE)
                added += 1
                break
    return text

@app.route('/ask_gpt', methods=['POST'])
def ask_gpt():
    data = request.get_json()
    messages = data.get('messages')
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

        # Extract recipe keyword (improve later with NLP if needed)
        user_msg = [m['content'] for m in messages if m['role'] == 'user'][-1]
        recipe_query = re.findall(r'\b[a-zA-Z ]+\b', user_msg)[-1].strip()

        spoonacular_url = f"https://api.spoonacular.com/recipes/complexSearch"
        params = {'query': recipe_query, 'number': 1, 'addRecipeNutrition': True, 'apiKey': SPOONACULAR_API_KEY}
        spoonacular_resp = requests.get(spoonacular_url, params=params)

        image_url, nutrition, servings, time = None, None, None, None
        if spoonacular_resp.status_code == 200:
            results = spoonacular_resp.json().get('results', [])
            if results:
                r = results[0]
                image_url = r.get('image')
                nutrition = r.get('nutrition', {}).get('nutrients', [])
                servings = r.get('servings')
                time = r.get('readyInMinutes')

        return jsonify({
            "reply": reply_with_links,
            "image_url": image_url,
            "nutrition": nutrition,
            "servings": servings,
            "time": time
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)