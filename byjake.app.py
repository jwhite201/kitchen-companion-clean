@app.route('/ask_gpt', methods=['POST'])
def ask_gpt():
    logger.info("Request received at /ask_gpt")
    try:
        user_id = verify_firebase_token()
        if not user_id:
            logger.warning("Unauthorized request")
            return jsonify({"error": "Unauthorized"}), 401

        data = request.get_json()
        logger.info(f"Request JSON: {data}")
        messages = data.get('messages')
        if not messages:
            logger.warning("Missing messages in request")
            return jsonify({"error": "No messages provided"}), 400

        user_message = [m['content'] for m in messages if m['role'] == 'user'][-1]

        # Fetch user preferences & pantry
        doc = db.collection('users').document(user_id).get()
        prefs = doc.to_dict() if doc.exists else {}
        dietary_prefs = prefs.get('preferences', [])
        pantry_items = prefs.get('pantry', [])

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

        # GPT call
        gpt_response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            max_tokens=700,
            temperature=0.7
        )

        reply = gpt_response.choices[0].message.content
        reply = add_affiliate_links(reply)
        reply = f"<strong>🍽️ Recipe: {user_message.title()}</strong><br><br>" + reply.replace("\n", "<br>")

        # Spoonacular call
        spoonacular_resp = requests.get(
            "https://api.spoonacular.com/recipes/complexSearch",
            params={'query': user_message, 'number': 1, 'addRecipeNutrition': True, 'apiKey': SPOONACULAR_API_KEY}
        )

        image_url, nutrition, servings, time = None, None, None, None
        if spoonacular_resp.status_code == 200:
            try:
                res = spoonacular_resp.json()
                if res.get('results'):
                    item = res['results'][0]
                    image_url = item.get('image')
                    nutrition = item.get('nutrition', {}).get('nutrients')
                    servings = item.get('servings')
                    time = item.get('readyInMinutes')
            except Exception as parse_err:
                logger.warning(f"Failed to parse Spoonacular response: {parse_err}")

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
