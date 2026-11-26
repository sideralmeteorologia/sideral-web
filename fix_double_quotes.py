import re
from pathlib import Path

WORKFLOW_DIR = Path("c:/Users/bryan/Downloads/BREAKOUT/sideral-web/.github/workflows")

def fix_quotes():
    for f in WORKFLOW_DIR.glob("*.yml"):
        content = f.read_text(encoding='utf-8')
        # Replace WRF_ARTIFACT_RESTORE_TO: 'target'' with WRF_ARTIFACT_RESTORE_TO: 'target'
        new_content = re.sub(r"(WRF_ARTIFACT_RESTORE_TO:\s*'[^']+')'", r"\1", content)
        if new_content != content:
            f.write_text(new_content, encoding='utf-8')
            print(f"Fixed double quotes in {f.name}")

if __name__ == "__main__":
    fix_quotes()
