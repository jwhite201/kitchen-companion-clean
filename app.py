from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os
from openai import OpenAI
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
import re

load_dotenv()

if not firebase_admin._apps:
    cred = credentials.Certificate("firebase-service-account.json")
    firebase_admin.initialize_app(cred)
db = firestore.client()

app = Flask(__name__)
CORS(app)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SPOONACULAR_API_KEY = os.getenv("SPOONACULAR_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY)

affiliate_links = {
    "mixer": "https://amzn.to/44QqzQf", "mixing bowl": "https://amzn.to/3SepGJI",
    "measuring cup": "https://amzn.to/44h5HBt", "spatula": "https://amzn.to/4iILIiP",
    "scale": "https://amzn.to/4cUBs5t", "rolling pin": "https://amzn.to/3Gy1mQv",
    "6 inch pan": "https://amzn.to/4lRwo64", "9 inch pan": "https://amzn.to/42xSUtc",
    "cake decorating": "https://amzn.to/4lUd08m", "whisk": "https://amzn.to/3GwiBlk",
    "bench scraper": "https://amzn.to/3GzcuN2", "loaf pan": "https://amzn.to/42XzcpD",
    "almond flour": "https://amzn.to/4iCs3kx", "no sugar added chocolate chips": "https://amzn.to/3SfqlKU",
    "monk fruit sweetener": "https://amzn.to/4cSRP2u", "coconut sugar": "https://amzn.to/42TZN6S",
    "whole wheat flour": "https://amzn.to/4jAbpmQ", "cake flour": "https://amzn.to/3YmwUz1",
    "silicone baking mat": "https://amzn.to/4jJcRmI", "avocado oil": "https://amzn.to/3EwlK43",
    "digital thermometer": "https://amzn.to/42SIDXr", "food storage containers": "https://amzn.to/4k1U7ip",
    "baking sheet": "https://amzn.to/44ijPdO", "hand mixer": "https://amzn.to/437UVwi",
    "wire racks": "https://amzn.to/42Rghg3", "cookie scoop": "https://amzn.to/3EH8Yjd",
    "food processor": "https://amzn.to/4iLcbvY", "matcha": "https://amzn.to/4d0bGwL",
    "cocoa powder": "https://amzn.to/42WB3Lp"
}

def add_affiliate_links(text):
    added = 0
    for keyword, url in affiliate_links.items():
        if re.search(rf"\b{re.escape(keyword)}\b", text, re.IGNORECASE) and added < 4:
            text = re.sub(rf"\b({re.escape(keyword)})\b", f"[\\1]({url})", text, count=1, flags=re.IGNORECASE)
            added += 1
    return text

@app.route('/')
def home():
    return jsonify({"message": "Kitchen Companion backend is live!"})

@app.route('/ask_gpt', methods=['POST'])
def ask_gpt():
    data = request.get_json()
    messages = data.get('messages')
    if not messages:
        return jsonify({"error": "No messages provided"}), 400

    user_message = [m['content'] for m in messages if m['role'] == 'user'][-1]
    try:
        gpt_response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            max_tokens=700,
            temperature=0.7
        )
        reply = gpt_response.choices[0].message.content
        reply = add_affiliate_links(reply)

        # Spoonacular
        spoonacular_resp = requests.get(
            "https://api.spoonacular.com/recipes/complexSearch",
            params={'query': user_message, 'number': 1, 'addRecipeNutrition': True, 'apiKey': SPOONACULAR_API_KEY}
        )
        image_url, nutrition, servings, time = None, None, None, None
        if spoonacular_resp.status_code == 200:
            res = spoonacular_resp.json()
            if res['results']:
                item = res['results'][0]
                image_url = item.get('image')
                nutrition = item.get('nutrition', {}).get('nutrients')
                servings = item.get('servings')
                time = item.get('readyInMinutes')

        # Fetch pantry from test_user
        user_doc = db.collection('users').document('test_user').get()
        pantry = user_doc.to_dict().get('pantry', []) if user_doc.exists else []

        # Determine missing items
        missing_items = [item for item in pantry if item.lower() not in reply.lower()]

        return jsonify({
            "reply": reply,
            "image_url": image_url,
            "nutrition": nutrition,
            "servings": servings,
            "time": time,
            "missing_items": missing_items
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/save_recipe', methods=['POST'])
def save_recipe():
    data = request.get_json()
    user_id = data.get('user_id')
    recipe = data.get('recipe')
    if not user_id or not recipe:
        return jsonify({"error": "Missing user_id or recipe"}), 400
    db.collection('users').document(user_id).collection('recipes').add(recipe)
    return jsonify({"status": "Recipe saved"})

@app.route('/get_recipes', methods=['GET'])
def get_recipes():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({"error": "Missing user_id"}), 400
    recipes = []
    docs = db.collection('users').document(user_id).collection('recipes').stream()
    for doc in docs:
        r = doc.to_dict()
        r['id'] = doc.id
        recipes.append(r)
    return jsonify(recipes)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)