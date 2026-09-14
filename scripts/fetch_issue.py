import os
import json
import urllib.request
import urllib.error
import sys

def fetch_issue(issue_number, token):
    repo = "AI20K-Build-Phase-Cohort-3/P-156"
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}"
    
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
        print(f"HTTP Error {e.code} for issue #{issue_number}: {e.reason}")
        return None
    except Exception as e:
        print(f"Error fetching issue #{issue_number}: {e}")
        return None

def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/fetch_issue.py <issue_number>")
        sys.exit(1)
        
    issue_number = sys.argv[1]
    
    # Load Token
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
        
    print(f"Fetching Issue #{issue_number}...")
    issue = fetch_issue(issue_number, token)
    if not issue:
        sys.exit(1)
        
    title = issue.get("title")
    body = issue.get("body")
    assignee = issue.get("assignee", {}).get("login") if issue.get("assignee") else "Unassigned"
    
    # Create docs/tasks directory if it doesn't exist
    os.makedirs("docs/tasks", exist_ok=True)
    
    output_content = (
        f"# {title}\n"
        f"* **GitHub Issue:** #{issue_number}\n"
        f"* **Assignee:** @{assignee}\n\n"
        f"{body}\n"
    )
    
    file_path = f"docs/tasks/issue_{issue_number}.md"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(output_content)
        
    print(f"Success! Issue detail saved locally to: {file_path}")

if __name__ == "__main__":
    main()
