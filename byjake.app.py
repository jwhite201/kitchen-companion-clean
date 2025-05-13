from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os
import json
import logging
from openai import OpenAI
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore, auth
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# ✅ Firebase setup from env var (Render-friendly)
if not firebase_admin._apps:
    firebase_creds = os.getenv('FIREBASE_SERVICE_ACCOUNT')
    if not firebase_creds:
        logger.error("Missing FIREBASE_SERVICE_ACCOUNT environment variable")
        raise EnvironmentError("Missing FIREBASE_SERVICE_ACCOUNT environment variable")

    try:
        cred_dict = json.loads(firebase_creds)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        logger.info("Firebase initialized successfully")
    except Exception as e:
        logger.error(f"Error initializing Firebase: {e}")
        raise

db = firestore.client()

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SPOONACULAR_API_KEY = os.getenv("SPOONACULAR_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY)

affiliate_links = {
    "mixer": "https://amzn.to/44QqzQf",
    "mixing bowl": "https://amzn.to/3SepGJI",
    "measuring cup": "https://amzn.to/44h5HBt",
    # ... (truncated for brevity)
}

def add_affiliate_links(text):
    added = 0
    for keyword, url in affiliate_links.items():
        pattern = re.compile(rf"\\b({re.escape(keyword)})\\b", re.IGNORECASE)
        if pattern.search(text) and added < 4:
            text = pattern.sub(f'<a href="{url}" target="_blank">\\1</a>', text, count=1)
            added += 1
    return text

def extract_ingredients(text):
    lines = text.split('\n')
    ingredients = []
    for line in lines:
        match = re.match(r'- (.+)', line)
        if match:
            raw = match.group(1).strip()
            cleaned = re.sub(r'\b(\d+([\/.]\d+)?\s*(cups?|cup|tbsp|tablespoons?|tsp|teaspoons?|oz|grams?|g|ml|large|small|medium))\b', '', raw, flags=re.IGNORECASE).strip()
            if cleaned:
                ingredients.append(cleaned)
    return list(set(ingredients))

def verify_firebase_token():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return None
    token = auth_header.split('Bearer ')[1]
    try:
        decoded_token = auth.verify_id_token(token)
        return decoded_token['uid']
    except Exception as e:
        logger.error(f"Token verification failed: {e}")
        return None

@app.route('/')
def home():
    return jsonify({"message": "Kitchen Companion backend is live!"})

@app.route('/healthcheck')
def health():
    return "OK", 200

@app.route('/ask_gpt', methods=['POST'])
def ask_gpt():
    user_id = verify_firebase_token()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    messages = data.get('messages')
    if not messages:
        return jsonify({"error": "No messages provided"}), 400

    prefs = db.collection('users').document(user_id).get().to_dict() or {}
    dietary_prefs = prefs.get('preferences', [])
    pantry_items = prefs.get('pantry', [])

    system_prompt = {
        "role": "system",
        "content": (
            "You are Jake's Kitchen Companion, a clever and charming assistant with expert culinary advice."
            " You tailor your suggestions to the user's dietary preferences: " + ', '.join(dietary_prefs) + "."
            " Suggest creative recipes using these pantry items: " + ', '.join(pantry_items) + "."
            " Keep responses detailed, practical, and engaging."
        )
    }

    messages.insert(0, system_prompt)

    try:
        gpt_response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            max_tokens=700,
            temperature=0.7
        )
        reply = gpt_response.choices[0].message.content
        reply = add_affiliate_links(reply)

        user_message = [m['content'] for m in messages if m['role'] == 'user'][-1]
        title_line = f"<strong>🍽️ Recipe: {user_message.title()}</strong><br><br>"
        reply = title_line + reply.replace('\n', '<br>')

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

        ingredients = extract_ingredients(reply)

        return jsonify({
            "reply": reply,
            "image_url": image_url,
            "nutrition": nutrition,
            "servings": servings,
            "time": time,
            "ingredients": ingredients
        })
    except Exception as e:
        logger.error(f"GPT response failed: {e}")
        return jsonify({"error": "Failed to generate response"}), 500

@app.route('/save_recipe', methods=['POST'])
def save_recipe():
    user_id = verify_firebase_token()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    recipe = data if isinstance(data, dict) else data.get('recipe')
    if not recipe:
        return jsonify({"error": "Missing recipe"}), 400

    db.collection('users').document(user_id).collection('recipes').add(recipe)
    return jsonify({"status": "Recipe saved"})

@app.route('/get_recipes', methods=['GET'])
def get_recipes():
    user_id = verify_firebase_token()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    recipes = []
    docs = db.collection('users').document(user_id).collection('recipes').stream()
    for doc in docs:
        r = doc.to_dict()
        r['id'] = doc.id
        recipes.append(r)
    return jsonify(recipes)

@app.route('/delete_recipe', methods=['DELETE'])
def delete_recipe():
    user_id = verify_firebase_token()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    recipe_id = request.args.get('recipe_id')
    if not recipe_id:
        return jsonify({"error": "Missing recipe_id"}), 400

    recipe_ref = db.collection('users').document(user_id).collection('recipes').document(recipe_id)
    if not recipe_ref.get().exists:
        return jsonify({"error": "Recipe not found"}), 404

    recipe_ref.delete()
    return jsonify({"message": "Recipe deleted successfully"})

@app.route('/get_pantry', methods=['GET'])
def get_pantry():
    user_id = verify_firebase_token()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    doc = db.collection('users').document(user_id).get()
    pantry = doc.to_dict().get('pantry', []) if doc.exists else []
    return jsonify({"pantry": pantry})

@app.route('/update_pantry', methods=['POST'])
def update_pantry():
    user_id = verify_firebase_token()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    items = data.get('items')
    if items is None:
        return jsonify({"error": "Missing items"})

    db.collection('users').document(user_id).set({'pantry': items}, merge=True)
    return jsonify({"status": "Pantry updated"})

@app.route('/update_preferences', methods=['POST'])
def update_preferences():
    user_id = verify_firebase_token()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    prefs = data.get('preferences')
    if prefs is None:
        return jsonify({"error": "Missing preferences"})

    db.collection('users').document(user_id).set({'preferences': prefs}, merge=True)
    return jsonify({"status": "Preferences updated"})

@app.route('/get_grocery_list', methods=['GET'])
def get_grocery_list():
    user_id = verify_firebase_token()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    doc = db.collection('users').document(user_id).get()
    grocery_list = doc.to_dict().get('grocery_list', []) if doc.exists else []
    return jsonify({"grocery_list": grocery_list})

@app.route('/update_grocery_list', methods=['POST'])
def update_grocery_list():
    user_id = verify_firebase_token()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    grocery_items = data.get('grocery_list') or data.get('items')
    if grocery_items is None:
        return jsonify({"error": "Missing grocery_list"})

    db.collection('users').document(user_id).set({'grocery_list': grocery_items}, merge=True)
    return jsonify({"status": "Grocery list updated"})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
