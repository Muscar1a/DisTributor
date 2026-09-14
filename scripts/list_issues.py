import os
import json
import urllib.request
import urllib.error
import sys

def list_issues(token):
    repo = "AI20K-Build-Phase-Cohort-3/P-156"
    url = f"https://api.github.com/repos/{repo}/issues?state=all&per_page=100"
    
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Antigravity-Agent"
    }
    
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code}: {e.reason}")
        return None
    except Exception as e:
        print(f"Error: {e}")
        return None

def main():
    import sys
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    token = None
    if os.path.exists(".env"):
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                line_stripped = line.strip()
                if line_stripped.startswith("GITHUB_TOKEN="):
                    token = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
                elif line_stripped.startswith("GITHUB_PAT="):
                    token = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
                    
    if not token:
        print("Error: GITHUB_TOKEN or GITHUB_PAT not found in .env file.")
        sys.exit(1)
        
    issues = list_issues(token)
    if not issues:
        print("No issues found or error fetching.")
        sys.exit(1)
        
    for issue in issues:
        # Filter out PRs
        if "pull_request" in issue:
            continue
        print(f"#{issue.get('number')}: {issue.get('title')} (State: {issue.get('state')})")

if __name__ == "__main__":
    main()
