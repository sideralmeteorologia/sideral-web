import glob
import re
import os

workflows_dir = "c:/Users/bryan/Downloads/BREAKOUT/sideral-web/.github/workflows"
files = glob.glob(os.path.join(workflows_dir, '*.yml'))

for file in files:
    with open(file, 'r', encoding='utf-8') as f:
        content = f.read()

    # Atualiza timeout-minutes para 480
    new_content = re.sub(r"timeout-minutes:\s*(\d+)", "timeout-minutes: 480", content)

    if new_content != content:
        with open(file, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Atualizado timeout: {file}")
