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

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load .env variables
load_dotenv()

# Initialize Firebase
try:
    # Read credentials directly from JSON file
    with open('firebase-credentials.json', 'r') as f:
        cred_dict = json.load(f)
    
    # Ensure private key is properly formatted
    if "private_key" in cred_dict:
        cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
    
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    logger.info("Firebase initialized successfully")
except Exception as e:
    logger.error(f"Error initializing Firebase: {str(e)}")
    raise

# Initialize Flask app
app = Flask(__name__)
CORS(app, resources={r"/*": {
    "origins": [
        "http://localhost:8000",
        "http://localhost:8001",
        "https://kitchen-companion.onrender.com",
        "https://byjake.com"
    ],
    "methods": ["GET", "POST", "OPTIONS"],
    "allow_headers": ["Content-Type", "Authorization"]
}})

# Load API keys
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
    added = 0
    for keyword, url in affiliate_links.items():
        if re.search(rf"\b{re.escape(keyword)}\b", text, re.IGNORECASE) and added < 4:
            text = re.sub(rf"\b({re.escape(keyword)})\b", f"[\\1]({url})", text, count=1, flags=re.IGNORECASE)
            added += 1
    return text

def extract_ingredients(text):
    lines = text.split('\n')
    ingredients = []
    for line in lines:
        match = re.match(r'- (.+)', line)
        if match:
            ingredient = re.sub(r'\d+([\/\.]?\d+)?\s?(cups?|cup|tbsp|tsp|oz|g|ml)?\s?', '', match.group(1), flags=re.IGNORECASE)
            ingredients.append(ingredient.strip())
    return list(set(ingredients))

def verify_firebase_token():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        logger.error("No Authorization header or invalid format")
        return None

    token = auth_header.split('Bearer ')[1]
    try:
        decoded_token = auth.verify_id_token(token)
        return decoded_token['uid']
    except Exception as e:
        logger.error(f"Error verifying token: {str(e)}")
        return None

@app.route('/')
def home():
    return jsonify({"message": "Kitchen Companion backend is live!"})

@app.route('/update_preferences', methods=['POST', 'OPTIONS'])
def update_preferences():
    user_id = verify_firebase_token()
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    prefs = request.get_json().get('preferences', [])
    db.collection('users').document(user_id).set({'preferences': prefs}, merge=True)
    return jsonify({'status': 'ok'})

@app.route('/update_pantry', methods=['POST', 'OPTIONS'])
def update_pantry():
    user_id = verify_firebase_token()
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    items = request.get_json().get('items', [])
    db.collection('users').document(user_id).set({'pantry': items}, merge=True)
    return jsonify({'status': 'ok'})

@app.route('/get_pantry', methods=['GET'])
def get_pantry():
    user_id = verify_firebase_token()
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    doc = db.collection('users').document(user_id).get()
    pantry = doc.to_dict().get('pantry', []) if doc.exists else []
    return jsonify({'pantry': pantry})

@app.route('/ask_gpt', methods=['POST', 'OPTIONS'])
def ask_gpt():
    if request.method == 'OPTIONS':
        return '', 200  # Respond to CORS preflight

    logger.info("Request received at /ask_gpt")
    try:
        # Try to get user_id from token, but don't require it
        user_id = None
        try:
            user_id = verify_firebase_token()
        except Exception as auth_error:
            logger.info(f"No valid auth token: {str(auth_error)}")
            # Continue without user authentication

        # Get user preferences if authenticated
        dietary_prefs = []
        pantry_items = []
        if user_id:
            try:
                doc = db.collection('users').document(user_id).get()
                prefs = doc.to_dict() if doc.exists else {}
                dietary_prefs = prefs.get('preferences', [])
                pantry_items = prefs.get('pantry', [])
            except Exception as pref_error:
                logger.warning(f"Failed to get user preferences: {str(pref_error)}")

        data = request.get_json()
        logger.info(f"Request JSON: {data}")
        messages = data.get('messages')
        if not messages:
            return jsonify({"error": "No messages provided"}), 400

        user_message = [m['content'] for m in messages if m['role'] == 'user'][-1]

        system_prompt = {
            "role": "system",
            "content": (
                f"You are Jake's Kitchen Companion, a clever and charming assistant with expert culinary advice. "
                f"Tailor recipes to these dietary preferences: {', '.join(dietary_prefs)}. "
                f"Use available pantry items: {', '.join(pantry_items)}. "
                f"Keep responses detailed, practical, and engaging."
            )
        }
        messages.insert(0, system_prompt)

        gpt_response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            max_tokens=700,
            temperature=0.7
        )

        reply = gpt_response.choices[0].message.content
        reply = add_affiliate_links(reply)
        reply = f"<strong>🍽️ Recipe: {user_message.title()}</strong><br><br>" + reply.replace("\n", "<br>")

        try:
            spoonacular_resp = requests.get(
                "https://api.spoonacular.com/recipes/complexSearch",
                params={'query': user_message, 'number': 1, 'addRecipeNutrition': True, 'apiKey': SPOONACULAR_API_KEY},
                timeout=10
            )
            spoonacular_resp.raise_for_status()

            image_url, nutrition, servings, time = None, None, None, None
            if spoonacular_resp.status_code == 200:
                res = spoonacular_resp.json()
                if res.get('results'):
                    item = res['results'][0]
                    image_url = item.get('image')
                    nutrition = item.get('nutrition', {}).get('nutrients')
                    servings = item.get('servings')
                    time = item.get('readyInMinutes')
        except Exception as spoonacular_error:
            logger.warning(f"Failed to get Spoonacular data: {str(spoonacular_error)}")
            image_url, nutrition, servings, time = None, None, None, None

        ingredients = extract_ingredients(reply)

        logger.info(f"Successfully generated response for user {user_id}")
        return jsonify({
            "reply": reply,
            "image_url": image_url,
            "nutrition": nutrition,
            "servings": servings,
            "time": time,
            "ingredients": ingredients
        })
    except Exception as e:
        logger.error(f"Error in /ask_gpt: {str(e)}", exc_info=True)
        return jsonify({"error": "An unexpected error occurred"}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
