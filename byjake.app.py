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

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

if not firebase_admin._apps:
    try:
        # Get Firebase credentials from environment variable
        firebase_creds = os.getenv('FIREBASE_SERVICE_ACCOUNT')
        if not firebase_creds:
            logger.error("Missing FIREBASE_SERVICE_ACCOUNT environment variable")
            raise EnvironmentError("Missing FIREBASE_SERVICE_ACCOUNT environment variable")
        
        # Parse the JSON string into a dictionary
        cred_dict = json.loads(firebase_creds)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        logger.info("Firebase initialized successfully")
    except Exception as e:
        logger.error(f"Error initializing Firebase: {str(e)}")
        raise

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

@app.route('/ask_gpt', methods=['POST'])
def ask_gpt():
    try:
        user_id = verify_firebase_token()
        if not user_id:
            logger.error("Unauthorized request to /ask_gpt")
            return jsonify({"error": "Unauthorized"}), 401

        data = request.get_json()
        messages = data.get('messages')
        if not messages:
            logger.error("No messages provided in request")
            return jsonify({"error": "No messages provided"}), 400

        user_message = [m['content'] for m in messages if m['role'] == 'user'][-1]
        logger.info(f"Processing request for user {user_id}: {user_message}")

        system_prompt = {
            "role": "system",
            "content": (
                "You are Jake's Kitchen Companion, a sharp, witty, and sometimes cheeky culinary assistant. You serve up expert-level cooking advice with a splash of humor and a dash of sass. Channel a mix of Martha Stewart's polish, Gordon Ramsay's directness (without the swearing), and a best friend's playful sarcasm. Keep recipes precise and helpful, but don't be afraid to toss in a clever joke or playful banter. Stay charming, confident, and fun — but never mean or offensive. Help users cook amazing meals, suggest creative swaps, and make the kitchen feel like the coolest place in the house."
                "who channels the refinement of Martha Stewart and the fearless creativity of Julia Child. "
                "You help users cook confidently with high-quality recipe suggestions, smart ingredient swaps, "
                "kitchen hacks, prep tips, and clear instructions. Always prioritize accuracy, clarity, and "
                "trusted sources (like USDA, Mayo Clinic). Default to giving full, detailed recipes when a dish is requested. "
                "Offer helpful context or background only if the user asks. You handle dietary needs (vegan, gluten-free, "
                "dairy-free, sugar-free) and scale recipes with precise unit conversions. Your tone is clear, direct, and no-nonsense—"
                "cut the fluff—but still thoughtful and charming. You've got a chill, sharp, bro-like vibe: work hard, vibe harder. "
                "Efficient but never stiff. Cool but never careless. You never invent health claims and you always ask clarifying questions "
                "if the user's request is vague. You also help with meal planning, grocery lists, pantry use, and creative leftovers."
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
            title_line = f"🍽️ Recipe: {user_message.title()}\n\n"
            reply = title_line + reply

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
            logger.error(f"Error generating GPT response: {str(e)}")
            return jsonify({"error": "Failed to generate response"}), 500
    except Exception as e:
        logger.error(f"Unexpected error in ask_gpt: {str(e)}")
        return jsonify({"error": "An unexpected error occurred"}), 500

@app.route('/save_recipe', methods=['POST'])
def save_recipe():
    try:
        user_id = verify_firebase_token()
        if not user_id:
            return jsonify({"error": "Unauthorized"}), 401

        data = request.get_json()
        recipe = data.get('recipe')
        if not recipe:
            logger.error("Missing recipe in save_recipe request")
            return jsonify({"error": "Missing recipe"}), 400
        
        logger.info(f"Saving recipe for user: {user_id}")
        db.collection('users').document(user_id).collection('recipes').add(recipe)
        logger.info("Recipe saved successfully")
        return jsonify({"status": "Recipe saved"})
    except Exception as e:
        logger.error(f"Error in save_recipe: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/get_recipes', methods=['GET'])
def get_recipes():
    try:
        user_id = verify_firebase_token()
        if not user_id:
            return jsonify({"error": "Unauthorized"}), 401
        
        logger.info(f"Fetching recipes for user: {user_id}")
        recipes = []
        docs = db.collection('users').document(user_id).collection('recipes').stream()
        for doc in docs:
            r = doc.to_dict()
            r['id'] = doc.id
            recipes.append(r)
        logger.info(f"Successfully fetched {len(recipes)} recipes")
        return jsonify(recipes)
    except Exception as e:
        logger.error(f"Error in get_recipes: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/delete_recipe', methods=['DELETE'])
def delete_recipe():
    user_id = verify_firebase_token()
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    recipe_id = request.args.get('recipe_id')
    if not recipe_id:
        return jsonify({'error': 'Missing recipe_id'}), 400

    recipe_ref = db.collection('users').document(user_id).collection('recipes').document(recipe_id)
    if not recipe_ref.get().exists:
        return jsonify({'error': 'Recipe not found'}), 404

    recipe_ref.delete()
    return jsonify({'message': 'Recipe deleted successfully'}), 200

@app.route('/update_grocery_list', methods=['POST'])
def update_grocery_list():
    user_id = verify_firebase_token()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    grocery_items = data.get('grocery_list')
    if grocery_items is None:
        return jsonify({"error": "Missing grocery_list"}), 400

    db.collection('users').document(user_id).update({'grocery_list': grocery_items})
    return jsonify({"status": "Grocery list updated"})

@app.route('/save_pantry', methods=['POST'])
def save_pantry():
    user_id = verify_firebase_token()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    pantry = data.get('pantry')
    if pantry is None:
        return jsonify({"error": "Missing pantry"}), 400

    db.collection('users').document(user_id).set({'pantry': pantry}, merge=True)
    return jsonify({"status": "Pantry saved"})

@app.route('/get_recipe_detail', methods=['GET'])
def get_recipe_detail():
    user_id = verify_firebase_token()
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    recipe_id = request.args.get('recipe_id')
    if not recipe_id:
        return jsonify({"error": "Missing recipe_id"}), 400

    doc = db.collection('users').document(user_id).collection('recipes').document(recipe_id).get()
    if not doc.exists:
        return jsonify({"error": "Recipe not found"}), 404
    return jsonify(doc.to_dict())

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)