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

if not firebase_admin._apps:
    cred = credentials.Certificate("firebase-service-account.json")
    firebase_admin.initialize_app(cred)
db = firestore.client()

app = Flask(__name__)
CORS(app)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SPOONACULAR_API_KEY = os.getenv("SPOONACULAR_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY)

expanded_affiliate_links = {
    "mixer": {"keywords": ["mixer"], "url": "https://amzn.to/44QqzQf"},
    "mixing bowl": {"keywords": ["mixing bowl"], "url": "https://amzn.to/3SepGJI"},
    "measuring cup": {"keywords": ["measuring cup"], "url": "https://amzn.to/44h5HBt"},
    "spatula": {"keywords": ["spatula"], "url": "https://amzn.to/4iILIiP"},
    "scale": {"keywords": ["scale"], "url": "https://amzn.to/4cUBs5t"},
    "rolling pin": {"keywords": ["rolling pin"], "url": "https://amzn.to/3Gy1mQv"},
    "6 inch pan": {"keywords": ["6 inch pan"], "url": "https://amzn.to/4lRwo64"},
    "9 inch pan": {"keywords": ["9 inch pan"], "url": "https://amzn.to/42xSUtc"},
    "cake decorating": {"keywords": ["cake decorating"], "url": "https://amzn.to/4lUd08m"},
    "whisk": {"keywords": ["whisk"], "url": "https://amzn.to/3GwiBlk"},
    "bench scraper": {"keywords": ["bench scraper"], "url": "https://amzn.to/3GzcuN2"},
    "loaf pan": {"keywords": ["loaf pan"], "url": "https://amzn.to/42XzcpD"},
    "almond flour": {"keywords": ["almond flour"], "url": "https://amzn.to/4iCs3kx"},
    "no sugar added chocolate chips": {"keywords": ["no sugar chocolate chips"], "url": "https://amzn.to/3SfqlKU"},
    "monk fruit sweetener": {"keywords": ["monk fruit"], "url": "https://amzn.to/4cSRP2u"},
    "coconut sugar": {"keywords": ["coconut sugar"], "url": "https://amzn.to/42TZN6S"},
    "whole wheat flour": {"keywords": ["whole wheat flour"], "url": "https://amzn.to/4jAbpmQ"},
    "cake flour": {"keywords": ["cake flour"], "url": "https://amzn.to/3YmwUz1"},
    "silicone baking mat": {"keywords": ["silicone baking mat"], "url": "https://amzn.to/4jJcRmI"},
    "avocado oil": {"keywords": ["avocado oil"], "url": "https://amzn.to/3EwlK43"},
    "digital thermometer": {"keywords": ["digital thermometer"], "url": "https://amzn.to/42SIDXr"},
    "food storage containers": {"keywords": ["food storage containers"], "url": "https://amzn.to/4k1U7ip"},
    "baking sheet": {"keywords": ["baking sheet"], "url": "https://amzn.to/44ijPdO"},
    "hand mixer": {"keywords": ["hand mixer"], "url": "https://amzn.to/437UVwi"},
    "wire racks": {"keywords": ["wire racks"], "url": "https://amzn.to/42Rghg3"},
    "cookie scoop": {"keywords": ["cookie scoop"], "url": "https://amzn.to/3EH8Yjd"},
    "food processor": {"keywords": ["food processor"], "url": "https://amzn.to/4iLcbvY"},
    "matcha": {"keywords": ["matcha"], "url": "https://amzn.to/4d0bGwL"},
    "cocoa powder": {"keywords": ["cocoa powder"], "url": "https://amzn.to/42WB3Lp"}
}

def add_affiliate_links(text, product_map):
    for product, data in product_map.items():
        for keyword in data["keywords"]:
            pattern = re.compile(rf'\b({keyword})\b', re.IGNORECASE)
            text = pattern.sub(f"[\\1]({data['url']})", text)
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
        gpt_reply = response.choices[0].message.content
        reply_with_links = add_affiliate_links(gpt_reply, expanded_affiliate_links)

        recipe_match = re.search(r'(?i)(?:recipe for|make|cook)\s+([a-zA-Z\s]+)', gpt_reply)
        recipe_query = recipe_match.group(1).strip() if recipe_match else 'chocolate chip cookies'

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