import os
import json
import urllib.request
import urllib.error
import sys

def create_issue(title, body, labels=None):
    # Try environment variables
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PAT")
    
    # Try .env file if not in environment
    if not token and os.path.exists(".env"):
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
        print("Error: GITHUB_TOKEN or GITHUB_PAT not found in environment variables or .env file.")
        print("Please set it in your PowerShell terminal:")
        print("  $env:GITHUB_PAT = 'your_personal_access_token'")
        print("Or add it to your .env file:")
        print("  GITHUB_PAT=your_personal_access_token")
        sys.exit(1)
        
    repo = "AI20K-Build-Phase-Cohort-3/P-156"
    url = f"https://api.github.com/repos/{repo}/issues"
    
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Antigravity-Agent",
        "Content-Type": "application/json"
    }
    
    data = {
        "title": title,
        "body": body
    }
    if labels:
        data["labels"] = [l.strip() for l in labels if l.strip()]
        
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers=headers,
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            print(f"Success! Issue created successfully.")
            print(f"Issue Number: #{res_data.get('number')}")
            print(f"Issue URL: {res_data.get('html_url')}")
            return res_data
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code}: {e.reason}")
        try:
            error_body = json.loads(e.read().decode("utf-8"))
            print(f"Message from GitHub: {error_body.get('message')}")
        except Exception:
            pass
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage:")
        print("  python scripts/create_issue.py <title> <body> [labels_comma_separated]")
        print("  python scripts/create_issue.py <title> --file <path_to_body_file> [labels_comma_separated]")
        sys.exit(1)
        
    title = sys.argv[1]
    
    # Check if we should read body from file
    if sys.argv[2] in ("--file", "-f"):
        if len(sys.argv) < 4:
            print("Error: Please specify the file path when using --file or -f")
            sys.exit(1)
        file_path = sys.argv[3]
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                body = f.read()
        except Exception as e:
            print(f"Error reading file '{file_path}': {e}")
            sys.exit(1)
        labels = sys.argv[4].split(",") if len(sys.argv) > 4 else None
    else:
        body = sys.argv[2]
        labels = sys.argv[3].split(",") if len(sys.argv) > 3 else None
        
    create_issue(title, body, labels)
