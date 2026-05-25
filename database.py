import os
import csv
import json
import uuid
from datetime import datetime
from pathlib import Path

# Try importing supabase, if fails or not configured we fall back
SUPABASE_AVAILABLE = False
try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    pass

class DatabaseManager:
    def __init__(self):
        self.supabase_url = os.getenv('SUPABASE_URL')
        self.supabase_key = os.getenv('SUPABASE_KEY')
        
        self.use_supabase = SUPABASE_AVAILABLE and bool(self.supabase_url) and bool(self.supabase_key)
        self.client = None
        
        self.data_dir = Path('data')
        self.data_dir.mkdir(exist_ok=True)
        
        self.users_file = self.data_dir / 'users.csv'
        self.analyses_file = self.data_dir / 'analyses.json'
        
        # Initialize local storage fallbacks
        self._init_local_db()
        
        if self.use_supabase:
            try:
                self.client = create_client(self.supabase_url, self.supabase_key)
                print("Successfully initialized Supabase Database Connection!")
            except Exception as e:
                print(f"Supabase connection failed, falling back to local files: {str(e)}")
                self.use_supabase = False
        else:
            print("Supabase credentials not fully configured. Using local CSV/JSON database.")

    def _init_local_db(self):
        """Initialize local files if they do not exist."""
        if not self.users_file.exists():
            with open(self.users_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['id', 'name', 'email', 'password_hash', 'created_at'])
                
        if not self.analyses_file.exists():
            with open(self.analyses_file, 'w', encoding='utf-8') as f:
                json.dump([], f)

    # --- USER OPERATIONS ---

    def get_user_by_email(self, email):
        """Retrieve a user record by email."""
        email = email.strip().lower()
        if self.use_supabase:
            try:
                response = self.client.table('users').select('*').eq('email', email).execute()
                if response.data and len(response.data) > 0:
                    return response.data[0]
                return None
            except Exception as e:
                print(f"Supabase get_user_by_email error: {str(e)}. Falling back to local file.")
        
        # Local CSV Fallback
        with open(self.users_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row['email'].strip().lower() == email:
                    return {
                        'id': row.get('id', str(uuid.uuid4())),
                        'name': row['name'],
                        'email': row['email'],
                        'password_hash': row['password_hash'] if row['password_hash'] else None,
                        'created_at': row.get('created_at', datetime.utcnow().isoformat())
                    }
        return None

    def create_user(self, name, email, password_hash=None):
        """Create a new user. Returns user details or None if failed."""
        email = email.strip().lower()
        if self.get_user_by_email(email):
            return None  # User already exists
            
        created_at = datetime.utcnow().isoformat()
        user_id = str(uuid.uuid4())
        
        if self.use_supabase:
            try:
                data = {
                    'email': email,
                    'name': name,
                    'password_hash': password_hash,
                    'created_at': created_at
                }
                response = self.client.table('users').insert(data).execute()
                if response.data and len(response.data) > 0:
                    return response.data[0]
            except Exception as e:
                print(f"Supabase create_user error: {str(e)}. Falling back to local file.")
        
        # Local CSV Fallback
        with open(self.users_file, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([user_id, name, email, password_hash or '', created_at])
            
        return {
            'id': user_id,
            'name': name,
            'email': email,
            'password_hash': password_hash,
            'created_at': created_at
        }

    # --- ANALYSIS OPERATIONS ---

    def save_analysis(self, email, query, platform_status, analysis, google_trends, source_count, scraped_sources):
        """Save a new analysis to history."""
        email = email.strip().lower()
        analysis_id = str(uuid.uuid4())
        created_at = datetime.utcnow().isoformat()
        
        if self.use_supabase:
            try:
                data = {
                    'user_email': email,
                    'query': query,
                    'platform_status': platform_status,
                    'analysis': analysis,
                    'google_trends': google_trends,
                    'source_count': source_count,
                    'scraped_sources': scraped_sources,
                    'created_at': created_at
                }
                response = self.client.table('analyses').insert(data).execute()
                if response.data and len(response.data) > 0:
                    return response.data[0]
            except Exception as e:
                print(f"Supabase save_analysis error: {str(e)}. Falling back to local file.")
                
        # Local JSON Fallback
        try:
            with open(self.analyses_file, 'r', encoding='utf-8') as f:
                analyses = json.load(f)
        except Exception:
            analyses = []
            
        new_analysis = {
            'id': analysis_id,
            'user_email': email,
            'query': query,
            'platform_status': platform_status,
            'analysis': analysis,
            'google_trends': google_trends,
            'source_count': source_count,
            'scraped_sources': scraped_sources,
            'created_at': created_at
        }
        
        analyses.insert(0, new_analysis) # Prepend to show most recent first
        
        with open(self.analyses_file, 'w', encoding='utf-8') as f:
            json.dump(analyses, f, indent=2)
            
        return new_analysis

    def get_cached_analysis(self, query):
        """Retrieve a cached analysis for a given query if it exists and is recent."""
        query = query.strip().lower()
        
        if self.use_supabase:
            try:
                response = self.client.table('analyses').select('*').eq('query', query).order('created_at', desc=True).limit(1).execute()
                if response.data and len(response.data) > 0:
                    return response.data[0]
            except Exception as e:
                print(f"Supabase cache search error: {str(e)}")
        
        # Local JSON fallback
        try:
            with open(self.analyses_file, 'r', encoding='utf-8') as f:
                analyses = json.load(f)
                for a in analyses:
                    if a.get('query', '').strip().lower() == query:
                        return a
        except Exception:
            pass
            
        return None

    def get_user_analyses(self, email):
        """Fetch past analyses for a specific user."""
        email = email.strip().lower()
        
        if self.use_supabase:
            try:
                response = self.client.table('analyses').select('*').eq('user_email', email).order('created_at', desc=True).execute()
                return response.data or []
            except Exception as e:
                print(f"Supabase get_user_analyses error: {str(e)}. Falling back to local file.")
                
        # Local JSON Fallback
        try:
            with open(self.analyses_file, 'r', encoding='utf-8') as f:
                analyses = json.load(f)
        except Exception:
            return []
            
        return [a for a in analyses if a['user_email'].strip().lower() == email]

    def delete_analysis(self, analysis_id, email):
        """Delete an analysis record from history."""
        email = email.strip().lower()
        
        if self.use_supabase:
            try:
                # UUID check
                response = self.client.table('analyses').delete().eq('id', analysis_id).eq('user_email', email).execute()
                return True
            except Exception as e:
                print(f"Supabase delete_analysis error: {str(e)}. Falling back to local file.")
                
        # Local JSON Fallback
        try:
            with open(self.analyses_file, 'r', encoding='utf-8') as f:
                analyses = json.load(f)
        except Exception:
            return False
            
        initial_count = len(analyses)
        analyses = [a for a in analyses if not (str(a.get('id')) == str(analysis_id) and a.get('user_email', '').strip().lower() == email)]
        
        if len(analyses) < initial_count:
            with open(self.analyses_file, 'w', encoding='utf-8') as f:
                json.dump(analyses, f, indent=2)
            return True
            
        return False
