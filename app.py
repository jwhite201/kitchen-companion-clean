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

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Initialize OpenAI
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
    user_id = data.get('user_id')

    if not messages:
        return jsonify({"error": "No messages provided"}), 400

    try:
        # Get pantry items
        pantry_items = []
        if user_id:
            pantry_doc = db.collection('users').document(user_id).get()
            if pantry_doc.exists:
                pantry_items = pantry_doc.to_dict().get('pantry', [])

        # Get GPT response
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

        # Get Spoonacular recipe details
        spoonacular_url = "https://api.spoonacular.com/recipes/complexSearch"
        params = {
            'query': recipe_query,
            'number': 1,
            'addRecipeNutrition': True,
            'apiKey': SPOONACULAR_API_KEY
        }
        spoonacular_resp = requests.get(spoonacular_url, params=params)
        image_url, ingredients, nutrition, servings, time = None, [], None, None, None
        if spoonacular_resp.status_code == 200:
            results = spoonacular_resp.json().get('results', [])
            if results:
                r = results[0]
                image_url = r.get('image')
                ingredients = [ing['name'] for ing in r.get('nutrition', {}).get('ingredients', [])]
                nutrition = r.get('nutrition', {}).get('nutrients', [])
                servings = r.get('servings')
                time = r.get('readyInMinutes')

        # Compare pantry vs needed ingredients
        missing_items = [ing for ing in ingredients if ing.lower() not in [p.lower() for p in pantry_items]]

        # Generate shopping links
        missing_query = ",".join(missing_items)
        instacart_link = f"https://www.instacart.com/store/checkout_v3?term={missing_query}" if missing_items else ""
        amazon_link = f"https://www.amazon.com/s?k={missing_query}" if missing_items else ""

        return jsonify({
            "reply": reply_with_links,
            "image_url": image_url,
            "ingredients": ingredients,
            "nutrition": nutrition,
            "servings": servings,
            "time": time,
            "missing_items": missing_items,
            "instacart_link": instacart_link,
            "amazon_link": amazon_link
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/save_pantry', methods=['POST'])
def save_pantry():
    data = request.get_json()
    user_id = data.get('user_id')
    pantry = data.get('pantry', [])

    if not user_id:
        return jsonify({"error": "Missing user_id"}), 400

    try:
        db.collection('users').document(user_id).set({'pantry': pantry}, merge=True)
        return jsonify({"status": "Pantry saved successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/get_pantry', methods=['GET'])
def get_pantry():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({"error": "Missing user_id"}), 400

    try:
        pantry_doc = db.collection('users').document(user_id).get()
        if pantry_doc.exists:
            return jsonify({"pantry": pantry_doc.to_dict().get('pantry', [])})
        else:
            return jsonify({"pantry": []})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)