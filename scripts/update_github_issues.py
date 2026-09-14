import os
import json
import urllib.request
import urllib.error
import sys

# Define mapping from issue number to list of US codes
ISSUE_US_MAPPING = {
    47: ["US-12"],
    42: ["US-01"],
    41: ["US-03", "US-04"],
    40: ["US-07"],
    39: ["US-03", "US-04"],
    38: ["US-07"],
    37: ["US-01", "US-11"],
    36: ["US-01"],
    35: ["US-01", "US-02"],
    34: ["US-05"],
    28: ["US-06", "US-07"],
    27: ["US-07", "US-11"],
    26: ["US-01"],
    25: ["US-01", "US-03", "US-05"],
    24: ["US-03", "US-04", "US-07"]
}

# Define US detailed descriptions
US_DESCRIPTIONS = {
    "US-01": "Là dev, tôi muốn trỏ SDK OpenAI sang gateway (đổi `base_url`) mà không sửa code nghiệp vụ",
    "US-02": "Là dev, tôi muốn mỗi response kèm metadata routing (tier, model, cost, latency) để debug",
    "US-03": "Là admin, tôi muốn cấu hình model chính + danh sách fallback cho từng tier",
    "US-04": "Là admin, tôi muốn chọn policy tổng (cost-first / balanced / quality-first)",
    "US-05": "Là dev, tôi muốn hệ thống tự fallback sang provider khác khi lỗi 429/5xx/timeout",
    "US-06": "Là admin, tôi muốn dashboard hiển thị chi phí, savings %, phân bố tier/provider",
    "US-07": "Là admin, tôi muốn xem log từng request kèm lý do routing (điểm số, tín hiệu)",
    "US-08": "Là dev, tôi muốn hỗ trợ streaming (SSE) như OpenAI",
    "US-09": "Là admin, tôi muốn gửi feedback chất lượng để hệ thống điều chỉnh routing",
    "US-10": "Là dev, tôi muốn force model/tier cho request đặc biệt (override)",
    "US-11": "Là admin, tôi muốn quản lý API key của gateway và giới hạn rate theo key",
    "US-12": "Là giảng viên/reviewer, tôi muốn xem báo cáo eval chứng minh cost↓ & quality giữ"
}

def get_issue(issue_number, token):
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
    except Exception as e:
        print(f"Error fetching issue #{issue_number}: {e}")
        return None

def update_issue_github(issue_number, new_body, token):
    repo = "AI20K-Build-Phase-Cohort-3/P-156"
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Antigravity-Agent",
        "Content-Type": "application/json"
    }
    data = json.dumps({"body": new_body}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="PATCH")
    try:
        with urllib.request.urlopen(req) as response:
            return response.status == 200
    except Exception as e:
        print(f"Error updating issue #{issue_number}: {e}")
        return False

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
        
    print("Starting update of GitHub issues with User Story mappings...")
    
    for issue_number, us_list in ISSUE_US_MAPPING.items():
        print(f"\nProcessing Issue #{issue_number}...")
        issue = get_issue(issue_number, token)
        if not issue:
            print(f"Skipping Issue #{issue_number} (Could not fetch)")
            continue
            
        current_body = issue.get("body", "") or ""
        
        # Check if already contains US tags
        has_us = any(us in current_body for us in us_list)
        if has_us:
            print(f"Issue #{issue_number} already contains User Story references.")
            # We will still regenerate to make it clean if needed, or skip
            
        # Build the User Story section
        us_lines = []
        for us in us_list:
            desc = US_DESCRIPTIONS.get(us, "")
            us_lines.append(f"- **{us}:** {desc}")
            
        us_markdown = "\n## 👥 User Stories\n" + "\n".join(us_lines) + "\n"
        
        # Append or insert after assignee block
        if "## 👥 User Stories" in current_body:
            print(f"Issue #{issue_number} already has User Stories section.")
            # Replace the existing stories section
            # For simplicity, we can append it if we can't find a clean place, or just leave it.
            continue
        
        # Insert after metadata (e.g. after Assignee line)
        lines = current_body.split("\n")
        assignee_idx = -1
        for idx, line in enumerate(lines):
            if "Assignee:" in line or "GitHub Issue:" in line:
                assignee_idx = idx
                
        if assignee_idx != -1:
            new_lines = lines[:assignee_idx+1] + [""] + us_markdown.split("\n") + lines[assignee_idx+1:]
            new_body = "\n".join(new_lines)
        else:
            new_body = us_markdown + "\n" + current_body
            
        # Update on GitHub
        print(f"Updating issue #{issue_number} on GitHub...")
        success = update_issue_github(issue_number, new_body, token)
        if success:
            print(f"Successfully updated GitHub Issue #{issue_number}!")
            
            # Also update local markdown file if it exists
            local_path = f"docs/tasks/issue_{issue_number}.md"
            if os.path.exists(local_path):
                # Format local file
                local_content = (
                    f"# {issue.get('title')}\n"
                    f"* **GitHub Issue:** #{issue_number}\n"
                    f"* **Assignee:** @{issue.get('assignee', {}).get('login') if issue.get('assignee') else 'Unassigned'}\n\n"
                    f"{new_body}\n"
                )
                with open(local_path, "w", encoding="utf-8") as lf:
                    lf.write(local_content)
                print(f"Updated local file: {local_path}")
        else:
            print(f"Failed to update GitHub Issue #{issue_number}.")

if __name__ == "__main__":
    main()
