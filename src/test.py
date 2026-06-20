import google.generativeai as genai

genai.configure(api_key="YOUR_NEW_KEY")

model = genai.GenerativeModel("gemini-2.5-flash")

response = model.generate_content("Hello")

print(response.text)