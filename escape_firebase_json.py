import json
import os

def escape_firebase_json(json_path):
    try:
        with open(json_path, "r") as f:
            data = f.read()

        # Escape newlines and double quotes
        escaped = data.replace('\n', '\\n').replace('"', '\\"')

        # Print the result for your .env file
        print("\nCopy this line to your .env file:")
        print(f'FIREBASE_SERVICE_ACCOUNT="{escaped}"')
        
        # Also save to a file for backup
        with open("firebase_creds_escaped.txt", "w") as f:
            f.write(f'FIREBASE_SERVICE_ACCOUNT="{escaped}"')
        print("\nA backup has been saved to 'firebase_creds_escaped.txt'")
        
    except FileNotFoundError:
        print(f"Error: Could not find the file at {json_path}")
    except Exception as e:
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    # Use the local file
    json_path = "firebase-credentials.json"
    escape_firebase_json(json_path) 