import sys
sys.path.append('e:/D-API-UI/api')
from database.db_connection import get_db_connection

def main():
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("DESCRIBE session_tracking")
        rows = cur.fetchall()
        for r in rows:
            print(f"{r['Field']}: {r['Type']}")
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    main()
