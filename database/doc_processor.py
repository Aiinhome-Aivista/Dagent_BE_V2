import os
import json
import PyPDF2
from sqlalchemy import create_engine, text
from urllib.parse import quote_plus

try:
    import docx
except ImportError:
    docx = None

def extract_text_from_file(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    text_content = ""
    total_pages = 0
    
    try:
        if ext == '.pdf':
            import pymupdf as fitz
            # pyrefly: ignore [missing-import]
            import easyocr
            import io
            
            # Initialize reader (will run on CPU by default if cuda not available)
            reader = easyocr.Reader(['en'], gpu=False, verbose=False)
            
            doc = fitz.open(file_path)
            total_pages = len(doc)
            
            for page in doc:
                # 1. Extract regular text
                page_text = page.get_text("text")
                text_content += page_text + "\n"
                
                # 2. Extract images on the page and OCR them
                image_list = page.get_images(full=True)
                for img_index, img_info in enumerate(image_list):
                    xref = img_info[0]
                    base_image = doc.extract_image(xref)
                    image_bytes = base_image["image"]
                    
                    try:
                        # EasyOCR can read from bytes directly
                        results = reader.readtext(image_bytes, detail=0)
                        if results:
                            text_content += "\n--- Extracted from Image Table ---\n"
                            text_content += "\n".join(results)
                            text_content += "\n----------------------------------\n"
                    except Exception as img_e:
                        print(f"Error running OCR on image: {img_e}")
            doc.close()
        elif ext in ['.docx']:
            if docx:
                doc = docx.Document(file_path)
                text_content = "\n".join([para.text for para in doc.paragraphs])
                total_pages = 1 # DOCX doesn't easily expose pages via python-docx
            else:
                text_content = "Error: 'python-docx' library is not installed. Please install it to parse .docx files."
                
        elif ext in ['.txt', '.md', '.csv']:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
                text_content = file.read()
                total_pages = 1
        else:
            text_content = f"Unsupported or binary file format: {ext}"
    except Exception as e:
        print(f"Error extracting text from {file_path}: {e}")
        text_content = f"Error extracting text: {e}"
        
    return text_content, total_pages, ext

def structure_text_with_llm(raw_text):
    try:
        from database.config import MISTRAL_API_KEY, MISTRAL_MODEL
        import requests
        
        url = 'https://api.mistral.ai/v1/chat/completions'
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
                {'role': 'user', 'content': f'Raw document text:\n\n{raw_text[:100000]}'}
            ],
            'response_format': {'type': 'json_object'},
            'temperature': 0.1
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        if resp.status_code == 200:
            return json.loads(resp.json()['choices'][0]['message']['content'])
    except Exception as e:
        print(f"Error structuring text with LLM: {e}")
    return None

def process_doc_job(file_path, allocated_db_name, db_host, db_user, db_pass, db_port):
    try:
        safe_user = quote_plus(db_user)
        safe_pass = quote_plus(db_pass)
        base_url = f"mysql+pymysql://{safe_user}:{safe_pass}@{db_host}:{db_port}"

        target_engine = create_engine(
            f"{base_url}/{allocated_db_name}",
            pool_size=5, max_overflow=10, pool_pre_ping=True
        )

        filename = os.path.basename(file_path)
        content, pages, ext = extract_text_from_file(file_path)
        
        structured_content = structure_text_with_llm(content)

        # Build JSON object
        file_data = {
            "file_type": ext.strip('.'),
            "total_pages": pages,
            "structured_content": structured_content,
            "content": content,
            "status": "completed"
        }
        
        json_str = json.dumps(file_data)

        with target_engine.connect() as conn:
            # Create table if not exists
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS workspace_files (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    file_name VARCHAR(255),
                    file_data JSON,
                    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            
            # Check if file already exists to update it, or insert new
            check_res = conn.execute(text("SELECT id FROM workspace_files WHERE file_name = :fname"), {"fname": filename}).fetchone()
            
            if check_res:
                conn.execute(text("UPDATE workspace_files SET file_data = :fdata WHERE file_name = :fname"), {"fdata": json_str, "fname": filename})
            else:
                conn.execute(text("INSERT INTO workspace_files (file_name, file_data) VALUES (:fname, :fdata)"), {"fname": filename, "fdata": json_str})
                
            conn.commit()

        print(f"Successfully processed document and saved to workspace_files in {allocated_db_name}")

    except Exception as e:
        print(f"Error processing document job for {file_path}: {e}")
