import requests
import json
from core.config import load_config

class FrappeAPI:
    def __init__(self):
        self.reload_config()

    def reload_config(self):
        config = load_config()
        self.url = config.get("url", "").rstrip('/')
        self.api_key = config.get("api_key", "")
        self.api_secret = config.get("api_secret", "")

    def get_headers(self, is_json=True):
        headers = {
            "Authorization": f"token {self.api_key}:{self.api_secret}",
            "Accept": "application/json"
        }
        if is_json:
            headers["Content-Type"] = "application/json"
        return headers

    def is_configured(self):
        return bool(self.url and self.api_key and self.api_secret)

    def ping(self, url, api_key, api_secret):
        test_url = f"{url.rstrip('/')}/api/method/frappe.auth.get_logged_user"
        headers = {
            "Authorization": f"token {api_key}:{api_secret}",
            "Accept": "application/json"
        }
        try:
            response = requests.get(test_url, headers=headers, timeout=10)
            if response.status_code == 200:
                return True, "Success"
            else:
                return False, f"Error: {response.status_code} - {response.text}"
        except Exception as e:
            return False, str(e)

    def fetch_data(self, doctype, fields='["*"]', filters=None, limit=0):
        if not self.is_configured():
            return None
        endpoint = f"{self.url}/api/resource/{doctype}"
        params = {"fields": fields, "limit_page_length": limit}
        
        if filters:
            if isinstance(filters, dict):
                # Format to frappe's expected JSON array of arrays string format
                # Example: [["POS Invoice", "cashier", "=", "Administrator"]]
                filter_list = []
                for k, v in filters.items():
                    filter_list.append([doctype, k, "=", v])
                params["filters"] = json.dumps(filter_list)
            elif isinstance(filters, str):
                params["filters"] = filters
                
        try:
            response = requests.get(endpoint, headers=self.get_headers(is_json=False), params=params, timeout=15)
            if response.status_code == 200:
                return response.json().get('data', [])
            return []
        except:
            return []

    def call_method(self, method, data=None):
        if not self.is_configured():
            return False, "API sozlanmagan"
            
        endpoint = f"{self.url}/api/method/{method}"
        try:
            headers = self.get_headers(is_json=True)
            
            if data is not None:
                # Send as PURE JSON to ensure all arguments are picked up by Frappe RPC
                response = requests.post(endpoint, headers=headers, json=data, timeout=15)
            else:
                response = requests.get(endpoint, headers=headers, timeout=15)
                
            if response.status_code == 200:
                return True, response.json().get('message', response.json())
            else:
                try:
                    error_data = response.json()
                    # Extract more descriptive error if available
                    error_msg = error_data.get('exception', str(error_data.get('_server_messages', response.text)))
                except:
                    error_msg = response.text
                return False, f"Server xatosi ({response.status_code}): {error_msg}"
        except Exception as e:
            return False, f"Ulanish xatosi: {e}"
