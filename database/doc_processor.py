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
            with open(file_path, 'rb') as file:
                reader = PyPDF2.PdfReader(file)
                total_pages = len(reader.pages)
                for page in reader.pages:
                    text_content += page.extract_text() or ""
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

        # Build JSON object
        file_data = {
            "file_type": ext.strip('.'),
            "total_pages": pages,
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
