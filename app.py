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

# Affiliate links
expanded_affiliate_links = {
    "mixer": {"keywords": ["mixer", "stand mixer"], "url": "https://amzn.to/44QqzQf"},
    "almond flour": {"keywords": ["almond flour"], "url": "https://amzn.to/4iCs3kx"},
    "cake pan": {"keywords": ["cake pan", "9-inch pan"], "url": "https://amzn.to/42xSUtc"},
    "spatula": {"keywords": ["spatula"], "url": "https://amzn.to/4iILIiP"},
}

def add_affiliate_links_inline(text, product_map):
    lower = text.lower()
    added = 0
    links = []
    for product, data in product_map.items():
        matched = False
        for kw in data["keywords"]:
            if kw in lower and added < 4:
                text = re.sub(rf"\b({kw})\b", f"[\\1]({data['url']})", text, flags=re.IGNORECASE)
                added += 1
                matched = True
                break
        if not matched and added < 4:
            links.append(f"[{product}]({data['url']})")
            added += 1
    if links:
        text += "\n\nRecommended tools:\n" + ", ".join(links)
    return text

@app.route('/ask_gpt', methods=['POST'])
def ask_gpt():
    data = request.get_json()
    messages = data.get('messages')
    user_id = data.get('user_id')

    if not messages:
        return jsonify({"error": "No messages provided"}), 400

    # Get user pantry from Firestore
    pantry_items = []
    if user_id:
        try:
            doc = db.collection('users').document(user_id).get()
            if doc.exists:
                pantry_items = doc.to_dict().get('pantry', [])
        except Exception as e:
            print(f"Error fetching pantry: {e}")

    try:
        # Generate recipe from GPT
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo-1106",
            messages=messages,
            max_tokens=700,
            temperature=0.7
        )
        reply = response.choices[0].message.content
        reply_with_links = add_affiliate_links_inline(reply, expanded_affiliate_links)

        # Extract recipe keyword
        user_msg = [m['content'] for m in messages if m['role'] == 'user'][-1]
        recipe_query = re.findall(r'\b[a-zA-Z ]+\b', user_msg)[-1].strip()

        # Call Spoonacular API
        spoonacular_url = "https://api.spoonacular.com/recipes/complexSearch"
        params = {
            'query': recipe_query,
            'number': 1,
            'addRecipeNutrition': True,
            'apiKey': SPOONACULAR_API_KEY
        }
        spoonacular_resp = requests.get(spoonacular_url, params=params)

        image_url, nutrition, servings, time, recipe_ingredients = None, None, None, None, []
        missing_ingredients = []

        if spoonacular_resp.status_code == 200:
            results = spoonacular_resp.json().get('results', [])
            if results:
                r = results[0]
                image_url = r.get('image')
                nutrition = r.get('nutrition', {}).get('nutrients', [])
                servings = r.get('servings')
                time = r.get('readyInMinutes')

                # Optional: simulate ingredients list
                recipe_ingredients = [i['name'] for i in r.get('nutrition', {}).get('ingredients', [])]
                # fallback if no ingredients provided
                if not recipe_ingredients:
                    recipe_ingredients = ["flour", "sugar", "butter", "eggs"]

                # Check what's missing from pantry
                missing_ingredients = [item for item in recipe_ingredients if item.lower() not in [p.lower() for p in pantry_items]]

        return jsonify({
            "reply": reply_with_links,
            "image_url": image_url,
            "nutrition": nutrition,
            "servings": servings,
            "time": time,
            "missing_ingredients": missing_ingredients
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/update_pantry', methods=['POST'])
def update_pantry():
    data = request.get_json()
    user_id = data.get('user_id')
    pantry_items = data.get('pantry_items')

    if not user_id or pantry_items is None:
        return jsonify({'error': 'Missing user_id or pantry_items'}), 400

    try:
        db.collection('users').document(user_id).set({'pantry': pantry_items}, merge=True)
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)