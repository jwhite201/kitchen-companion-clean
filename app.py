from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os
from openai import OpenAI
from dotenv import load_dotenv
import re
import random

# Expanded affiliate links with keyword variants
expanded_affiliate_links = {
    "mixer": {
        "keywords": ["mixer", "stand mixer", "hand mixer", "electric mixer", "kitchen mixer"],
        "url": "https://amzn.to/44QqzQf"
    },
    "mixing bowl": {
        "keywords": ["mixing bowl", "bowl", "baking bowl", "prep bowl"],
        "url": "https://amzn.to/3SepGJI"
    },
    "measuring cup": {
        "keywords": ["measuring cup", "measuring cups", "measuring tools"],
        "url": "https://amzn.to/44h5HBt"
    },
    "spatula": {
        "keywords": ["spatula", "rubber spatula", "silicone spatula"],
        "url": "https://amzn.to/4iILIiP"
    },
    "scale": {
        "keywords": ["scale", "kitchen scale", "digital scale", "food scale"],
        "url": "https://amzn.to/4cUBs5t"
    },
    "rolling pin": {
        "keywords": ["rolling pin", "dough roller", "pastry roller"],
        "url": "https://amzn.to/3Gy1mQv"
    },
    "6-inch pan": {
        "keywords": ["6-inch pan", "6-inch", "six inch cake pan", "6\" cake pan"],
        "url": "https://amzn.to/4lRwo64"
    },
    "9-inch pan": {
        "keywords": ["9-inch", "9-inch pan", "nine inch cake pan", "9\" cake pan"],
        "url": "https://amzn.to/42xSUtc"
    },
    "cake decorating": {
        "keywords": ["cake decorating", "piping tips", "frosting tools", "decorating kit", "icing tools"],
        "url": "https://amzn.to/4lUd08m"
    },
    "whisk": {
        "keywords": ["whisk", "balloon whisk", "wire whisk"],
        "url": "https://amzn.to/3GwiBlk"
    },
    "bench scraper": {
        "keywords": ["bench scraper", "dough scraper", "pastry scraper"],
        "url": "https://amzn.to/3GzcuN2"
    },
    "loaf pan": {
        "keywords": ["loaf pan", "bread pan"],
        "url": "https://amzn.to/42XzcpD"
    },
    "almond flour": {
        "keywords": ["almond flour", "blanched almond flour"],
        "url": "https://amzn.to/4iCs3kx"
    },
    "no sugar added chocolate chips": {
        "keywords": ["no sugar chocolate chips", "sugar-free chocolate chips", "healthy chocolate chips"],
        "url": "https://amzn.to/3SfqlKU"
    },
    "monk fruit sweetener": {
        "keywords": ["monk fruit", "monk fruit sweetener", "monkfruit"],
        "url": "https://amzn.to/4cSRP2u"
    },
    "coconut sugar": {
        "keywords": ["coconut sugar", "natural sugar"],
        "url": "https://amzn.to/42TZN6S"
    },
    "whole wheat flour": {
        "keywords": ["whole wheat flour", "whole grain flour"],
        "url": "https://amzn.to/4jAbpmQ"
    },
    "cake flour": {
        "keywords": ["cake flour", "soft wheat flour"],
        "url": "https://amzn.to/3YmwUz1"
    },
    "silicone baking mat": {
        "keywords": ["silicone baking mat", "silpat", "nonstick baking mat"],
        "url": "https://amzn.to/4jJcRmI"
    },
    "avocado oil": {
        "keywords": ["avocado oil", "healthy oil", "cooking oil"],
        "url": "https://amzn.to/3EwlK43"
    },
    "digital thermometer": {
        "keywords": ["digital thermometer", "meat thermometer", "kitchen thermometer"],
        "url": "https://amzn.to/42SIDXr"
    },
    "food storage containers": {
        "keywords": ["food storage", "meal prep containers", "storage containers"],
        "url": "https://amzn.to/4k1U7ip"
    }
}

# Function to inject one inline affiliate link per GPT response
def add_affiliate_links_inline(response_text, product_map):
    lower_text = response_text.lower()
    candidates = []

    for product, data in product_map.items():
        for keyword in data["keywords"]:
            pattern = r'\b' + re.escape(keyword.lower()) + r's?\b'
            if re.search(pattern, lower_text):
                candidates.append((keyword, data["url"]))
                break

    if not candidates:
        return response_text

    chosen_keyword, url = random.choice(candidates)
    pattern = re.compile(r'\b(' + re.escape(chosen_keyword) + r')\b', re.IGNORECASE)

    def replacer(match):
        return f"[{match.group(1)}]({url})"

    return pattern.sub(replacer, response_text, count=1)

# Load environment variables from .env
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Load API keys
SPOONACULAR_API_KEY = os.getenv("SPOONACULAR_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Initialize OpenAI client
openai_client = OpenAI(api_key=OPENAI_API_KEY)

@app.route('/')
def home():
    return "Kitchen Companion is live!"

@app.route('/ask_gpt', methods=['POST'])
def ask_gpt():
    data = request.get_json()
    user_input = data.get('message')

    if not user_input:
        return jsonify({"error": "No message provided"}), 400

    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo-1106",
            messages=[
                {"role": "system", "content": "You are The Kitchen Companion, a culinary-savvy bro with sharp instincts and chill energy. You're clear, direct, and no-nonsense—cut the crap and get to the point—but still thoughtful and intentional. You ask smart questions, expect precise answers, and you’re not afraid to call it like it is. You’ve got that 'work hard, vibe harder' attitude: sharp when it matters, laid-back when it doesn’t. Whether you’re dialing in substitutions, walking someone through a recipe, or cracking a joke, keep it grounded, smart, and unbothered. Efficient, but never stiff. Cool, but never careless. Never invent scientific claims, and always ask for clarification if a user’s request is unclear. You're here to help people feel confident in the kitchen—beginner to pro—with just the right mix of grit and good vibes."},
                {"role": "user", "content": user_input}
            ],
            max_tokens=700,
            temperature=0.7
        )
        reply = response.choices[0].message.content
        reply_with_links = add_affiliate_links_inline(reply, expanded_affiliate_links)
        return jsonify({"reply": reply_with_links})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/search_recipes', methods=['GET'])
def search_recipes():
    query = request.args.get('query')
    diet = request.args.get('diet')
    max_ready_time = request.args.get('maxReadyTime')
    number = request.args.get('number', default=5)

    if not query:
        return jsonify({'error': 'Missing query parameter'}), 400

    url = 'https://api.spoonacular.com/recipes/complexSearch'
    params = {
        'query': query,
        'number': number,
        'apiKey': SPOONACULAR_API_KEY
    }

    if diet:
        params['diet'] = diet
    if max_ready_time:
        params['maxReadyTime'] = max_ready_time

    response = requests.get(url, params=params)

    if response.status_code == 200:
        return jsonify(response.json())
    else:
        return jsonify({'error': 'API call failed', 'details': response.text}), response.status_code

@app.route('/get_recipe_details', methods=['GET'])
def get_recipe_details():
    recipe_id = request.args.get('id')

    if not recipe_id:
        return jsonify({'error': 'Missing id parameter'}), 400

    url = f'https://api.spoonacular.com/recipes/{recipe_id}/information'
    params = {'apiKey': SPOONACULAR_API_KEY}

    response = requests.get(url, params=params)

    if response.status_code == 200:
        return jsonify(response.json())
    else:
        return jsonify({'error': 'API call failed', 'details': response.text}), response.status_code

# Run the Flask app on Render
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)