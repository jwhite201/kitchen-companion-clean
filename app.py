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

# Load env variables
load_dotenv()

# Initialize Firebase
if not firebase_admin._apps:
    cred = credentials.Certificate("firebase-service-account.json")
    firebase_admin.initialize_app(cred)
db = firestore.client()

# Initialize Flask + OpenAI
app = Flask(__name__)
CORS(app)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SPOONACULAR_API_KEY = os.getenv("SPOONACULAR_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Affiliate links (same as before, skip here for brevity)
expanded_affiliate_links = {
    # ... [keep your existing product map here]
}

def add_affiliate_links_inline(response_text, product_map):
    lower_text = response_text.lower()
    candidates = []
    for product, data in product_map.items():
        for keyword in data["keywords"]:
            if keyword.lower() in lower_text:
                candidates.append((keyword, data["url"]))
                break
    if not candidates:
        return response_text
    selected = random.sample(candidates, min(4, len(candidates)))
    for keyword, url in selected:
        pattern = re.compile(rf'\b({re.escape(keyword)})\b', re.IGNORECASE)
        response_text = pattern.sub(f"[\\1]({url})", response_text, count=1)
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

    # Get user preferences
    user_preferences = {}
    if user_id:
        try:
            user_doc = db.collection('users').document(user_id).get()
            if user_doc.exists:
                user_preferences = user_doc.to_dict().get('preferences', {})
        except Exception as e:
            print(f"Error fetching preferences: {e}")

    prefs_prompt = ""
    if user_preferences:
        prefs_list = [k for k, v in user_preferences.items() if v]
        if prefs_list:
            prefs_prompt = f" (user preferences: {', '.join(prefs_list)})"

    if messages[-1]['role'] == 'user':
        messages[-1]['content'] += prefs_prompt

    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo-1106",
            messages=messages,
            max_tokens=700,
            temperature=0.7
        )
        reply = response.choices[0].message.content
        reply_with_links = add_affiliate_links_inline(reply, expanded_affiliate_links)

        # Extract keyword for Spoonacular (use last user message)
        user_message = [m['content'] for m in messages if m['role'] == 'user'][-1]
        search_query = user_message.split(' ')[-1]

        spoonacular_url = f"https://api.spoonacular.com/recipes/complexSearch"
        params = {'query': search_query, 'number': 1, 'apiKey': SPOONACULAR_API_KEY}
        spoonacular_resp = requests.get(spoonacular_url, params=params)

        image_url, servings, ready_in_minutes, nutrition_facts = None, None, None, {}

        if spoonacular_resp.status_code == 200:
            results = spoonacular_resp.json()
            if results['results']:
                recipe_id = results['results'][0]['id']
                image_url = results['results'][0]['image']

                # Get detailed recipe info
                detail_url = f"https://api.spoonacular.com/recipes/{recipe_id}/information"
                detail_params = {'apiKey': SPOONACULAR_API_KEY}
                detail_resp = requests.get(detail_url, params=detail_params)

                if detail_resp.status_code == 200:
                    detail = detail_resp.json()
                    servings = detail.get('servings')
                    ready_in_minutes = detail.get('readyInMinutes')
                    nutrition = detail.get('nutrition', {}).get('nutrients', [])
                    for item in nutrition:
                        name = item.get('name')
                        amount = f"{item.get('amount')}{item.get('unit')}"
                        nutrition_facts[name] = amount

        return jsonify({
            "reply": reply_with_links,
            "image_url": image_url,
            "servings": servings,
            "ready_in_minutes": ready_in_minutes,
            "nutrition_facts": nutrition_facts
        })

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