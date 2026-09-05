import os, sys
sys.path.append('.')
from database.doc_processor import extract_text_from_file
from database.config import MISTRAL_API_KEY, MISTRAL_MODEL, MISTRAL_API_URL
import requests
import json

file_path = r'd:\Project_Backend_2025\TraverseAi_2026\D-AgentV1.1\Dagent_BE_V2\uploads\RGAOA 2025-26 AnnualReport2025-26 Updated.pdf'
raw_text, _, _ = extract_text_from_file(file_path)

url = MISTRAL_API_URL or 'https://api.mistral.ai/v1/chat/completions'
headers = {'Authorization': f'Bearer {MISTRAL_API_KEY}', 'Content-Type': 'application/json'}
system_prompt = '''You are a document structuring AI. Extract tables and paragraphs from the raw text into a JSON format.
The JSON must have this exact structure:
{
  "paragraphs": [
    {
      "title": "Title or Header of the section",
      "text": "Full text of the paragraph."
    }
  ],
  "tables": [
    {
      "table_name": "Context or name of the table",
      "headers": ["Col1", "Col2"],
      "rows": [
        ["Row1Col1", "Row1Col2"]
      ]
    }
  ]
}
Return ONLY valid JSON.'''

payload = {
    'model': MISTRAL_MODEL or 'mistral-large-latest',
    'messages': [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': f'Raw document text:\n\n{raw_text[:8000]}'}
    ],
    'response_format': {'type': 'json_object'},
    'temperature': 0.1
}

resp = requests.post(url, headers=headers, json=payload)
print(resp.json()['choices'][0]['message']['content'])
