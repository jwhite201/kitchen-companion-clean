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

# OpenAI and Spoonacular API setup
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SPOONACULAR_API_KEY = os.getenv("SPOONACULAR_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Affiliate links
affiliate_links = {
    "mixer": "https://amzn.to/44QqzQf",
    "mixing bowl": "https://amzn.to/3SepGJI",
    "measuring cup": "https://amzn.to/44h5HBt",
    "spatula": "https://amzn.to/4iILIiP",
    "scale": "https://amzn.to/4cUBs5t",
    "rolling pin": "https://amzn.to/3Gy1mQv",
    "6 inch pan": "https://amzn.to/4lRwo64",
    "9 inch pan": "https://amzn.to/42xSUtc",
    "cake decorating": "https://amzn.to/4lUd08m",
    "whisk": "https://amzn.to/3GwiBlk",
    "bench scraper": "https://amzn.to/3GzcuN2",
    "loaf pan": "https://amzn.to/42XzcpD",
    "almond flour": "https://amzn.to/4iCs3kx",
    "no sugar added chocolate chips": "https://amzn.to/3SfqlKU",
    "monk fruit sweetener": "https://amzn.to/4cSRP2u",
    "coconut sugar": "https://amzn.to/42TZN6S",
    "whole wheat flour": "https://amzn.to/4jAbpmQ",
    "cake flour": "https://amzn.to/3YmwUz1",
    "silicone baking mat": "https://amzn.to/4jJcRmI",
    "avocado oil": "https://amzn.to/3EwlK43",
    "digital thermometer": "https://amzn.to/42SIDXr",
    "food storage containers": "https://amzn.to/4k1U7ip",
    "baking sheet": "https://amzn.to/44ijPdO",
    "hand mixer": "https://amzn.to/437UVwi",
    "wire racks": "https://amzn.to/42Rghg3",
    "cookie scoop": "https://amzn.to/3EH8Yjd",
    "food processor": "https://amzn.to/4iLcbvY",
    "matcha": "https://amzn.to/4d0bGwL",
    "cocoa powder": "https://amzn.to/42WB3Lp"
}

def add_affiliate_links(text):
    for keyword, url in affiliate_links.items():
        pattern = re.compile(rf'\b({re.escape(keyword)})\b', re.IGNORECASE)
        text = pattern.sub(rf'[\1]({url})', text)
    return text

@app.route('/ask_gpt', methods=['POST'])
def ask_gpt():
    data = request.get_json()
    messages = data.get('messages')
    pantry = data.get('pantry', [])

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

        # Extract search query (basic fallback to last user message)
        user_msg = [m['content'] for m in messages if m['role'] == 'user'][-1]
        recipe_query = user_msg

        # Get Spoonacular recipe details
        spoonacular_url = "https://api.spoonacular.com/recipes/complexSearch"
        params = {
            'query': recipe_query,
            'number': 1,
            'addRecipeNutrition': True,
            'apiKey': SPOONACULAR_API_KEY
        }
        r = requests.get(spoonacular_url, params=params)
        image_url, nutrition_summary, servings, ready_time, missed_ingredients = None, "", None, None, []

        if r.status_code == 200:
            results = r.json().get('results', [])
            if results:
                recipe = results[0]
                image_url = recipe.get('image')
                servings = recipe.get('servings')
                ready_time = recipe.get('readyInMinutes')
                nutrients = recipe.get('nutrition', {}).get('nutrients', [])
                nutrition_summary = ", ".join([f"{n['name']}: {n['amount']}{n['unit']}" for n in nutrients[:4]])

                recipe_ingredients = [ing['name'] for ing in recipe.get('nutrition', {}).get('ingredients', [])]
                missed_ingredients = [i for i in recipe_ingredients if i.lower() not in [p.lower() for p in pantry]]

        # Insert affiliate links
        reply_with_links = add_affiliate_links(reply)

        return jsonify({
            "reply": reply_with_links,
            "image_url": image_url,
            "nutrition_summary": nutrition_summary,
            "servings": servings,
            "time": f"{ready_time} minutes",
            "missing_ingredients": missed_ingredients
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/save_data', methods=['POST'])
def save_data():
    data = request.get_json()
    user_id = data.get('user_id')
    collection = data.get('collection')
    item = data.get('item')

    if not user_id or not collection or not item:
        return jsonify({'error': 'Missing user_id, collection, or item'}), 400

    try:
        db.collection('users').document(user_id).collection(collection).add({
            'data': item,
            'timestamp': firestore.SERVER_TIMESTAMP
        })
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)