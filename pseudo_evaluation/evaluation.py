import time
import pandas as pd
from pymongo import MongoClient
from dotenv import load_dotenv
import requests
import json


load_dotenv()


MONGO_DETAILS = "mongodb://localhost:27017/"
client = MongoClient(MONGO_DETAILS)
database = client["sproc"]
collection = database["sproc_it"]

QUESTIONS = {
    0: 'Write a pseudocode to find the difference between the largest and smallest element in the given array',
    1: 'Design a pseudocode to find the frequency of each element in an array.',
    2: 'Write a pseudocode to check if a given string is a palindrome and to count the number of vowels in a given string.',
    3: 'Write a pseudocode to find the greatest common divisor (GCD) of two numbers using the Euclidean algorithm.',
    4: 'Design a pseudocode to reverse the digits of a number and also find its digits sum'
}

def evaluate_pseudocode(pseudo_code, question_id):
    try:
        model = "llama3.1:latest"
        question = QUESTIONS.get(int(question_id), "Unknown question")
        prompt = f"""
        Evaluate the following pseudocode for the given question based on the logic out of 10. Don't consider pseudocode syntax, indentation, time complexity, space complexity, or the approach used, only evaluate based on the logic.
        Your response should be in the format:
        {{
          "Score": [number],
          "Explanation": "[brief explanation]"
        }}
        Question: {question}
        
        Pseudocode:
        {pseudo_code}
        """

        url = "http://172.16.100.16:11434/api/generate"
        headers = {"Content-Type": "application/json"}
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False
        }

        response = requests.post(url, headers=headers, json=payload)

        if response.status_code == 200:
            print("Raw API Response:")
            
            response_json = json.loads(response.text)
            
            nested_response = response_json.get("response", "{}")
            nested_json = json.loads(nested_response)

            score = nested_json.get("Score")
            explanation = nested_json.get("Explanation")
            
            if score is not None and explanation is not None:
                return score, explanation
            else:
                print("Could not extract a valid score or explanation from the response.")
                return None, None
        else:
            print(f"Error in Ollama API request: {response.status_code} {response.text}")
            return None, None
    except Exception as e:
        print(f"An error occurred while evaluating pseudocode: {e}")
        return None, None

def get_all_user_details():
    try:
        user_details_cursor = collection.find({})
        user_details_list = list(user_details_cursor)
        if not user_details_list:
            print("No user details found in the database.")
            return []
        return user_details_list
    except Exception as e:
        print(f"An error occurred while fetching user details: {e}")
        return []

if __name__ == "__main__":
    user_data = get_all_user_details()
    if user_data:
        print(f"Found {len(user_data)} user records.")
        user_list = []

        for user in user_data:
            print(f"\nProcessing user: {user.get('Name', 'Unknown')}")

            scores = []
            explanations = []
            pseudo_code_answers = user.get('pseudoCodeAnswers', {})
            
            if isinstance(pseudo_code_answers, dict):
                pseudo_code_answers = pseudo_code_answers.get('pseudoCodeAnswers', {})

            if not isinstance(pseudo_code_answers, dict):
                print(f"Invalid pseudoCodeAnswers format for user {user.get('Name', 'Unknown')}. Skipping.")
                continue

            for question_id, pseudo_code in pseudo_code_answers.items():
                if pseudo_code == "":
                    print("Score: 0")
                    scores.append(0)
                    explanations.append("blank answer")
                else:
                    print(f"\nEvaluating pseudocode for question {question_id}")
                    score, explanation = evaluate_pseudocode(pseudo_code, question_id)
                    if score is not None:
                        print(f"Score: {score}")
                        print(f"Explanation: {explanation}")
                        scores.append(score)
                        explanations.append(explanation)
                    else:
                        print("Failed to get a valid score or explanation for this pseudocode.")

                    time.sleep(2) 

            if scores and explanations:
                print(f"Final scores for {user.get('Name', 'Unknown')}: {scores}")
                print(f"Final explanations for {user.get('Name', 'Unknown')}: {explanations}")

                update_result = collection.update_one(
                    {'_id': user['_id']},
                    {'$set': {'pseudoCodeScores': scores, 'pseudoCodeExplanations': explanations}}
                )
                print(f"MongoDB update result: {update_result.modified_count} document(s) modified")

                user_list.append({
                    "Name": user.get('Name', 'Unknown'),
                    "RegNo": user.get('RegNo', 'Unknown'),
                    "Email": user.get('email', 'Unknown'),
                    "PseudoCodeAnswers": pseudo_code_answers,
                    "Scores": scores,
                    "Explanations": explanations,
                    "TOTAL SCORE": sum(scores)
                })
            else:
                print(f"No valid scores or explanations obtained for user {user.get('Name', 'Unknown')}.")

        if user_list:
            df = pd.DataFrame(user_list)
            print("\nFinal DataFrame:")
            print(df)

            try:
                df.to_excel("user_pseudocode_scores.xlsx", index=False)
                print("Scores and explanations have been evaluated and saved to user_pseudocode_scores.xlsx")
            except PermissionError as e:
                print(f"Permission error: {e}. Ensure the file is not open and you have write permissions.")
        else:
            print("No user data with valid scores or explanations to save.")
    else:
        print("No user details to process.")
